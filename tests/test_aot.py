"""Direct static Rust bodies and runtime-compiled code share Python semantics."""

from importlib.resources import files
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust.aot import basic_blocks, generate, rust_mask, templates
from py2fastrust.codegen import generate as generate_rust
from py2fastrust.compiler import Compiler
from py2fastrust.ir import Code, Instruction, Pattern, Program


class AotStructureTests(unittest.TestCase):
    def compile(self, source):
        return Compiler("case.py").compile(textwrap.dedent(source))

    def test_straight_line_statements_share_a_basic_block(self):
        program = self.compile("first=1\nsecond=first\nthird=second\n")
        runtime = files("py2fastrust").joinpath("runtime", "vm.rs").read_text()
        blocks = basic_blocks(program.codes[0], templates(runtime))
        self.assertGreater(max(end-start for start, end in blocks), 3)
        body = generate(program)
        self.assertNotRegex(rust_mask(body), r"\bOp\b|\bInstr\b|\bmatch\s+op\b|\.step\(")
        self.assertIn("self.store(f, n, v)?", body)
        self.assertEqual(body.count("compiled_frame_checkpoint(f,root_index)"),
                         sum(len(code.ops) for code in program.codes))

    def test_scope_proof_removes_only_nonclass_namespace_callbacks(self):
        program = self.compile("""
            outer=1
            def function(value):
                first=value
                second=first
                return second
            class Example:
                first=outer
                second=first
        """)
        runtime = files("py2fastrust").joinpath("runtime", "vm.rs").read_text()
        available = templates(runtime)
        generated = generate(program)
        self.assertEqual(generated.count("compiled_frame_checkpoint(f,root_index)"),
                         sum(len(code.ops) for code in program.codes))
        for code_id, code in enumerate(program.codes):
            body = generated.split(f"fn generated_aot_code_{code_id}(", 1)[1].split("fn generated_aot_code_", 1)[0]
            if code.kind == "Class":
                self.assertIn("start_protocol_class_name", body)
                blocks = basic_blocks(code, available)
                ends = {end for _, end in blocks}
                for index, instruction in enumerate(code.ops):
                    if instruction.op in {"Load", "Store", "Delete", "SetupAnnotations"}:
                        self.assertIn(index+1, ends)
            else:
                self.assertNotIn("start_protocol_class_name", body)

    def test_closed_rust_has_no_instruction_interpreter(self):
        program = self.compile("items=[1,2]\nprint(items[0])\n")
        source, locations = generate_rust(program, include_dynamic=False)
        masked = rust_mask(source)
        self.assertNotRegex(masked, r"\bOp\b|\bInstr\b|\.ops\b|\bfn\s+step\b")
        self.assertEqual(source.count("compiled:Some(Runtime::generated_aot_code_"), len(program.codes))
        self.assertEqual(len(locations), sum(len(code.ops) for code in program.codes))

    def test_open_static_code_does_not_embed_instructions(self):
        program = self.compile("def f(x):\n return x+1\nprint(eval('f(2)'))\n")
        source, _ = generate_rust(program, include_dynamic=True)
        self.assertIn("fn step(", source)
        self.assertEqual(source.count("ops:vec![]"), len(program.codes))
        self.assertNotIn("Instr { op:", source)
        for code_id in range(len(program.codes)):
            self.assertIn(f"compiled:Some(Runtime::generated_aot_code_{code_id})", source)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class AotExecutionTests(unittest.TestCase):
    def run_source(self, source, *, dynamic=False, integer="i64", tripwire=False):
        source = textwrap.dedent(source)
        program = Compiler("case.py").compile(source)
        rust, _ = generate_rust(program, integer, include_dynamic=dynamic)
        if tripwire:
            self.assertTrue(dynamic)
            self.assertEqual(rust.count("self.step(&mut f, ins.op)"), 1)
            rust = rust.replace("self.step(&mut f, ins.op)", 'panic!("static execution entered interpreter")')
        with tempfile.TemporaryDirectory(prefix="pytors-aot-") as directory:
            root = Path(directory)
            target = root / "main.rs"
            target.write_text(rust, encoding="utf-8")
            compiled = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(root / "main")],
                                      text=True, capture_output=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            expected = subprocess.run([sys.executable, "-I", "-c", source],
                                      text=True, capture_output=True, timeout=20)
            actual = subprocess.run([str(root / "main")], text=True, capture_output=True, timeout=20)
            self.assertEqual(actual.returncode, expected.returncode, actual.stderr+"\n"+expected.stderr)
            self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
            return actual

    def test_static_code_never_enters_open_interpreter(self):
        self.run_source('''
            def outer(x):
                def inner(step=1):
                    nonlocal x
                    x += step
                    return x
                return inner
            f = outer(2)
            total = 0
            for i in range(8):
                if i == 2:
                    continue
                if i == 6:
                    break
                total += f(i)
            print(total, f(), [i*i for i in range(5) if i%2])
            class Example:
                def method(self):
                    return total
            print(Example().method())
            def recurse(n):
                return 0 if n==0 else recurse(n-1)+1
            print(recurse(350))
            try:
                recurse(2000)
            except RecursionError:
                print("recursion limit")
        ''', dynamic=True, tripwire=True)

    def test_closed_exception_and_generator_continuations(self):
        self.run_source('''
            events=[]
            def generator():
                try:
                    value=yield 1
                    yield value+2
                    yield from (x*x for x in range(3))
                finally:
                    events.append("closed")
            g=generator()
            print(next(g),g.send(5),list(g),events)
            def choose(n):
                try:
                    for i in range(4):
                        try:
                            if i==n:
                                return i
                            if i==1:
                                continue
                        finally:
                            events.append(i)
                finally:
                    events.append("done")
                return -1
            print(choose(3),events)
            try:
                raise ExceptionGroup("group",[ValueError("v"),TypeError("t")])
            except* ValueError as error:
                print(type(error).__name__,len(error.exceptions))
            except* TypeError:
                print("type")
        ''')

    def test_callbacks_keep_intermediate_values_alive(self):
        self.run_source('''
            import gc
            class Guard:
                def __init__(self,value):
                    self.value=value
                def __add__(self,other):
                    gc.collect()
                    return Guard(self.value+other.value)
                def __bool__(self):
                    gc.collect()
                    return self.value!=0
                @property
                def doubled(self):
                    gc.collect()
                    return self.value*2
            def collect():
                gc.collect()
                return 3
            for i in range(3):
                print(["keep",i],collect(),(Guard(i)+Guard(5)).doubled)
            print(bool(Guard(0)),bool(Guard(1)))
            print([Guard(7),collect()][0].value)
        ''')

    def test_closed_class_namespace_callbacks_preserve_scope_and_gc(self):
        self.run_source('''
            from __future__ import annotations
            import gc
            events=[]
            marker=41
            class Space(dict):
                def __getitem__(self,key):
                    gc.collect()
                    if key in ('marker','value'):events.append(('get',key))
                    return dict.__getitem__(self,key)
                def __setitem__(self,key,value):
                    gc.collect()
                    if key=='value':events.append(('set',key))
                    dict.__setitem__(self,key,value)
                def __delitem__(self,key):
                    gc.collect()
                    raise RuntimeError('mapping delete')
            class Meta(type):
                @classmethod
                def __prepare__(meta,name,bases):return Space()
            class Example(metaclass=Meta):
                value: int=marker
                copy=value
                def method(self):return __class__.value
            print(Example.value,Example.copy,Example().method(),Example.__annotations__,events)
            try:
                class Failed(metaclass=Meta):
                    victim=1
                    del victim
            except BaseException as error:print(type(error).__name__,str(error))
        ''')

    def test_closed_crossed_native_class_input_and_text_catches(self):
        self.run_source(r'''
            import functools,types,sys,gc
            events=[]
            class Reader:
                def readline(self):events.append('readline');gc.collect();return '7\n'
            class Writer:
                def write(self,text):events.append(('write',text));return len(text)
            class Error:
                flush=staticmethod(functools.partial(len,42))
            saved=sys.stdin,sys.stdout,sys.stderr
            class Box:
                def __init__(self,value):events.append(('box',value))
                __setattr__=staticmethod(functools.partial(print,flush=True))
            alias=types.GenericAlias(Box,int)
            Writer.flush=staticmethod(functools.partial(next,map(input,['prompt']),None))
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                value=alias(3)
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print('alias-outer',type(value).__name__,events)
            events.clear()
            class Box:
                def __init__(self,value):events.append(('box',value))
                __setattr__=staticmethod(functools.partial(len,42))
            alias=types.GenericAlias(Box,int)
            Error.flush=staticmethod(functools.partial(list,map(alias,range(3))))
            Writer.flush=lambda self:None
            try:
                sys.stdin=Reader();sys.stdout=Writer();sys.stderr=Error()
                value=input()
            finally:sys.stdin,sys.stdout,sys.stderr=saved
            print('input-outer',value,events)
            events.clear()
            class Box(int):
                __setattr__=staticmethod(functools.partial(len,42))
            alias=types.GenericAlias(Box,int)
            class Number:
                __int__=staticmethod(functools.partial(alias,7))
            print('text-outer','%d'%Number())
        ''')

    def test_dynamic_code_calls_static_and_static_code_objects(self):
        self.run_source('''
            import gc
            def outer(x):
                def f(y):
                    gc.collect()
                    return x+y
                return f
            static=outer(4)
            exec("def dynamic(x):\\n return static(x)*2")
            print(dynamic(5),eval("static(3)"))
            import types
            cloned=types.FunctionType(static.__code__,globals(),closure=static.__closure__)
            print(cloned(8))
            namespace={"static":static}
            exec(compile("answer=static(9)","runtime.py","exec"),namespace)
            print(namespace["answer"])
        ''', dynamic=True)

    def test_every_static_instruction_template_typechecks(self):
        runtime=files("py2fastrust").joinpath("runtime","vm.rs").read_text()
        available=templates(runtime)
        values={"usize":0,"i32":0,"bool":False,"String":"name","Vec<String>":[],
                "Option<String>":None,"Const":None,"MatchPattern":Pattern("Literal",(None,))}
        codes=[Code("<module>","case.py","Module",ops=[Instruction("Return")])]
        for name,template in available.items():
            fields=[field[1].strip() if isinstance(field,tuple) else field for field in template.types]
            operation=Instruction(name,tuple(values[field] for field in fields))
            codes.append(Code(name,"case.py","Function",ops=[operation,Instruction("Return")]))
        rust,_=generate_rust(Program(codes=codes),include_dynamic=False)
        with tempfile.TemporaryDirectory(prefix="pytors-aot-templates-") as directory:
            root=Path(directory)
            target=root/"main.rs"
            target.write_text(rust,encoding="utf-8")
            compiled=subprocess.run(["rustc","--edition=2021",str(target),"-o",str(root/"main")],
                                    capture_output=True,text=True,timeout=90)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            actual=subprocess.run([str(root/"main")],capture_output=True,text=True,timeout=15)
            self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,"",""))

    def test_closed_bigint_and_i128_literals(self):
        self.run_source('''
            value=10**60+17
            print(value,value//-13,value%-13)
            print(tuple([value,1]),{1,2,1},[*range(3)])
        ''',integer="bigint")
        self.run_source('''
            value=2**100+3
            print(value,value//7,value%7)
        ''',integer="i128")
