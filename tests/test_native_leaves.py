"""Guarded leaf entries coexist with general AOT bodies and original Code objects."""

from collections import Counter
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions, transpile
from py2fastrust.aot import closing, rust_mask
from py2fastrust.compiler import Compiler
from py2fastrust.codegen import generate
from wrapping_reference import execute as wrapping_execute


DRIVER = r'''
events=[]
def default():events.append('default');return 2
def scalar(a,b=default(),*,c=3):
    "leaf documentation"
    return a*b+c
class Number(int):
    def __mul__(self,other):events.append('subclass mul');return 40
print(scalar(4),scalar(a=5,c=1),scalar(True),scalar(Number(4)),events)
exec('print(scalar(6))')
exec('def dynamic_leaf(a):return a*3+2\nprint(dynamic_leaf(7))')
def predicate(a,b):return not (a<b<~a)
print(predicate(2,3),predicate(-4,1))
def booleans(a):return not a
print(booleans(0),booleans(3))
def plus(a):return a+1
def passthrough(a):return a
def positive(a):return +a
def constant(a):return 999999
large=int('1000000')
print(passthrough(large) is large,positive(large) is large)
print(constant(0) is constant(1))
saved=plus.__code__
plus.__name__='renamed'
print(plus(8))
plus.__code__=passthrough.__code__
print(plus(large) is large)
passthrough.__code__=saved
print(passthrough(9))
def outer():
    def same(a):return a+111
    first=same
    def same(a):return a*7
    return first,same
first,second=outer()
print(first(2),second(2))
def positional(a,/,b=3,*,c=4):return (a^b)&c
print(positional(2,c=7))
try:positional(a=2)
except TypeError:print('posonly error')
try:scalar(1,a=2)
except TypeError:print('duplicate error')
class Key(str):
    def __eq__(self,other):events.append('keyword equality');return str.__eq__(self,other)
    __hash__=str.__hash__
events.clear();print(scalar(**{Key('a'):3}),events)
class Owner:
    @staticmethod
    def private(__value):return __value*3-1
print(Owner.private(3))
print(scalar.__doc__,scalar.__code__.co_name)
'''


def leaf_body(source):
    masked=rust_mask(source)
    start=masked.index("fn try_native_leaf(")
    opening=masked.index("{",start)
    return source[opening+1:closing(masked,opening)]


def boundary_source(integer):
    bits = {'i64':64, 'i128':128, 'bigint':160}[integer]
    high = (1 << (bits-1))-1
    constant = (1 << 190)+123
    return f'''
def boundary(a,b):return -(a*b)+((a^b)&{constant})
def compare_boundary(a,b):return a*b < a+b < ~a
for a,b in [({high},3),(-{high},7),(0,0),(-1,1),(3,-8)]:
    print(boundary(a,b),compare_boundary(a,b))
'''


class NativeLeafProofTests(unittest.TestCase):
    def test_actual_code_ids_and_original_ops_maps_are_retained(self):
        program = Compiler('leaf.py').compile(textwrap.dedent(DRIVER))
        names = [program.codes[index].qualname for index in program.native_leaves]
        self.assertEqual(names.count('outer.<locals>.same'), 2)
        self.assertIn('Owner.private', names)
        self.assertNotIn('passthrough', names)
        self.assertNotIn('positive', names)
        self.assertNotIn('constant', names)
        before = repr(program.codes)
        optimized, optimized_map = generate(program, native_leaves=True)
        plain, plain_map = generate(program, native_leaves=False)
        self.assertEqual(repr(program.codes), before)
        self.assertEqual(optimized_map, plain_map)
        self.assertEqual(set(map(int,re.findall(r'PY2FASTRUST_NATIVE_LEAF_HIT code=(\d+)', optimized))),set(program.native_leaves))
        self.assertNotIn('PY2FASTRUST_NATIVE_LEAF_HIT', plain)

    def test_rejects_effects_generators_passthroughs_and_unsupported_operators(self):
        source='''
def name(x):return x
def positive(x):return +x
def constant(x):return 1234
def call(x):return int(x)
def global_read(x):return x+other
def attribute(x):return x.value+1
def container(x):return [x]
def divide(x):return x/2
def floor(x):return x//2
def modulo(x):return x%2
def power(x):return x**2
def shift(x):return x<<2
def variable(*x):return ~x
def keywords(**x):return ~x
def generator(x):return (yield x)
def body(x):
    x=3
    return x+1
def generic[T](x):return x+1
def no_parameter():return 1+2
'''
        self.assertEqual(Compiler('proof.py').compile(textwrap.dedent(source)).native_leaves,{})

    def test_native_body_uses_only_fixed_scalars_and_wraps_each_operation(self):
        source='def leaf(a,b):return -((a*b)+(a-b))^(~a|b)\nexec("pass")\n'
        result=transpile(source,TranspileOptions())
        self.assertEqual(result.backend,'aot')
        body=leaf_body(result.rust_source)
        self.assertIn('Object::Namespace',body)
        self.assertIn('Value::Int(value)',body)
        self.assertIn('wrapping_mul',body)
        self.assertIn('wrapping_add',body)
        self.assertIn('wrapping_sub',body)
        self.assertIn('wrapping_neg',body)
        for forbidden in ['self.binary','self.unary','self.call','Object::List','Vec::','Value::Float']:
            self.assertNotIn(forbidden,body)
        boolean=transpile('def leaf(a):return (not a)&True\nexec("pass")\n',TranspileOptions())
        body=leaf_body(boolean.rust_source)
        self.assertIn('Some(Value::Bool(',body)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeLeafRuntimeTests(unittest.TestCase):
    def compile_run(self,source,integer,optimized,release,root,instrument=True):
        result=transpile(source,TranspileOptions(integer=integer,optimize=optimized,filename='leaf.py'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'aot')
        generated=result.rust_source
        hits=re.findall(r'// PY2FASTRUST_NATIVE_LEAF_HIT code=(\d+)',generated)
        if instrument:
            generated=re.sub(r'// PY2FASTRUST_NATIVE_LEAF_HIT code=(\d+)',lambda m:f'eprintln!("native-leaf-hit:{m[1]}");',generated)
        # Probe guards through a normally bound frame, without a product counter
        # or a new runtime API. A dict locals mapping must always decline.
        extra='''
let owner=runtime.global_name_get(runtime.globals,"scalar").unwrap().unwrap();
let Value::Obj(index)=owner.clone() else{panic!("function")};
let Object::Function(function)=runtime.object(index).unwrap() else{panic!("function")};
let mut frame=runtime.bind_function(&function,owner,vec![Value::Int(Int::from_i128(1).into())],Vec::new()).unwrap();
frame.pc=0;assert!(runtime.try_native_leaf(&frame).is_none());
frame.pc=2;assert!(runtime.try_native_leaf(&frame).is_none());
if INT_BITS==64 {
    frame.pc=1;
    runtime.ns_set(frame.locals,"a".into(),Value::Int(Int::exact_small(i128::MAX).into()));
    assert!(runtime.try_native_leaf(&frame).is_none());
}
frame.pc=1;frame.locals=runtime.alloc(Object::Dict(Vec::new()));
assert!(runtime.try_native_leaf(&frame).is_none());
'''
        end=generated.rfind('runtime.finish();\n}')
        self.assertGreaterEqual(end,0)
        generated=generated[:end]+extra+generated[end:]
        path=root/(integer+('-release' if release else '-debug')+('-optimized' if optimized else '-plain'))
        path.with_suffix('.rs').write_text(generated)
        command=['rustc','--edition=2021',str(path.with_suffix('.rs')),'-o',str(path)]
        if release:command.append('-O')
        compiled=subprocess.run(command,text=True,capture_output=True,timeout=180)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        environment=os.environ.copy()
        environment['PATH']=str(root/'no-runtime-tools')
        environment.pop('PYTHONPATH',None)
        completed=subprocess.run([str(path)],text=True,capture_output=True,timeout=30,
                                 cwd=root,env=environment)
        self.assertEqual(completed.returncode,0,completed.stderr)
        return completed,hits

    def test_fixed_bigint_debug_release_matrix_and_actual_entry_hits(self):
        source=textwrap.dedent(DRIVER)
        expected=subprocess.run([sys.executable,'-I','-c',source],text=True,capture_output=True,timeout=30)
        self.assertEqual(expected.returncode,0,expected.stderr)
        with tempfile.TemporaryDirectory(prefix='native-leaf-matrix-') as directory:
            for integer in ['i64','i128','bigint']:
                boundary=boundary_source(integer)
                reference=wrapping_execute(boundary,integer)
                self.assertEqual(reference.returncode,0)
                outputs=[]
                for release in [False,True]:
                    with self.subTest(integer=integer,release=release):
                        completed,hits=self.compile_run(source+boundary,integer,True,release,Path(directory))
                        self.assertEqual(completed.stdout,expected.stdout+reference.stdout)
                        counts=Counter(map(int,re.findall(r'native-leaf-hit:(\d+)',completed.stderr)))
                        if integer=='bigint':self.assertEqual((hits,counts),([],Counter()))
                        else:
                            self.assertEqual(sum(counts.values()),24)
                            self.assertGreaterEqual(len(counts),10)
                            program=Compiler('leaf.py').compile(source+boundary)
                            scalar=next(index for index in program.native_leaves if program.codes[index].qualname=='scalar')
                            self.assertEqual(counts[scalar],4)
                        outputs.append(completed.stdout)
                if len(outputs)==2:self.assertEqual(outputs[0],outputs[1])

    def test_optimize_false_retains_vm_entry_and_identity(self):
        source=textwrap.dedent(DRIVER)
        expected=subprocess.run([sys.executable,'-I','-c',source],text=True,capture_output=True,timeout=30)
        with tempfile.TemporaryDirectory(prefix='native-leaf-disabled-') as directory:
            completed,hits=self.compile_run(source,'i64',False,False,Path(directory))
            self.assertEqual(completed.stdout,expected.stdout)
            self.assertEqual(hits,[])
            self.assertNotIn('native-leaf-hit:',completed.stderr)


if __name__=='__main__':unittest.main()
