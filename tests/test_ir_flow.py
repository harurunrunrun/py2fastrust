"""Common IR flow proofs drive conservative runtime pruning."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.codegen import generate
from py2fastrust.compiler import Compiler
from py2fastrust.ir import Code, Instruction, Program
from py2fastrust.ir_flow import BindingVersion, analyze_code, analyze_program
from py2fastrust.reachability import dynamic_compilation_unreachable
from py2fastrust.typeflow import TypeSet


class IRFlowTests(unittest.TestCase):
    def compile(self, source):
        program = Compiler('flow.py').compile(textwrap.dedent(source))
        return program, program.flow.codes[0]

    def load(self, program, flow, name, *, last=True):
        uses = [pc for pc,op in enumerate(program.codes[flow.code].ops)
                if op.op == 'Load' and op.args[0] == name]
        pc = uses[-1] if last else uses[0]
        return pc, flow.instructions[pc]

    def test_type_set_shared_api_retains_native_union_and_unknown(self):
        integer, boolean = TypeSet.from_kind('int'), TypeSet.from_kind('bool')
        self.assertEqual(integer.join(boolean).native_kind, 'int_bool')
        self.assertEqual(TypeSet.from_kind('int_bool').kinds, {'int','bool'})
        self.assertIsNone(integer.join(TypeSet(unknown=True)).native_kind)
        self.assertIsNone(integer.join(TypeSet(maybe_unbound=True)).native_kind)

    def test_linear_type_changes_have_static_source_located_versions(self):
        program,flow = self.compile('x=1\nx="ready"\nprint(x)')
        stores = [pc for pc,op in enumerate(program.codes[0].ops) if op.op=='Store' and op.args==('x',)]
        pc,use = self.load(program,flow,'x')
        fact = use.entry.bindings['x']
        self.assertEqual(fact.types, TypeSet.from_kind('str'))
        self.assertEqual(fact.definitions, {BindingVersion(0,stores[-1],'x')})
        self.assertEqual(use.uses['x'], fact.definitions)
        self.assertEqual((use.location.filename,use.location.line,use.location.column),('flow.py',3,7))
        self.assertEqual([flow.definitions[BindingVersion(0,at,'x')].line for at in stores],[1,2])

    def test_branch_join_retains_bool_integer_and_both_definitions(self):
        program,flow = self.compile('x=1\nif input():x=True\nprint(x)')
        _,use = self.load(program,flow,'x')
        self.assertEqual(use.entry.bindings['x'].types,TypeSet.from_kind('int_bool'))
        self.assertEqual(len(use.uses['x']),2)
        self.assertTrue(flow.proves_leaf_calls)

    def test_zero_iteration_and_branch_paths_distinguish_unbound_from_none(self):
        for source in ['for i in range(0):\n x=True\nprint(x)',
                       'if input():x=True\nprint(x)']:
            with self.subTest(source=source):
                program,flow = self.compile(source)
                _,use = self.load(program,flow,'x')
                self.assertEqual(use.entry.bindings['x'].types,TypeSet(frozenset({'bool'}),True))
        program,flow = self.compile('x=None\nfor i in range(0):\n x=True\nprint(x)')
        _,use = self.load(program,flow,'x')
        self.assertEqual(use.entry.bindings['x'].types,TypeSet(frozenset({'none','bool'})))

    def test_loop_fixed_point_uses_static_versions_not_iteration_versions(self):
        program,flow = self.compile('x=0\nfor i in range(4):\n if i:x=True\n else:x=x+1\nprint(x)')
        _,use = self.load(program,flow,'x')
        self.assertEqual(use.entry.bindings['x'].types,TypeSet.from_kind('int_bool'))
        stores = {BindingVersion(0,pc,'x') for pc,op in enumerate(program.codes[0].ops)
                  if op.op=='Store' and op.args==('x',)}
        self.assertEqual(use.uses['x'],stores)
        self.assertEqual(len(stores),3)
        iterator = next(pc for pc,op in enumerate(program.codes[0].ops) if op.op=='ForIter')
        exits = flow.instructions[iterator].exits
        sizes = {edge.kind:len(state.stack) for edge,state in exits.items() if edge.kind in {'iterate','exhausted'}}
        self.assertEqual(sizes,{'iterate':2,'exhausted':0})

    def test_nested_calls_record_actual_operand_targets_in_execution_order(self):
        _,flow = self.compile('print(abs(int(input())))')
        self.assertEqual([site.callee.targets for site in flow.calls.values()],
                         [{'input'},{'int'},{'abs'},{'print'}])
        self.assertTrue(all(site.direct_unmodified_leaf for site in flow.calls.values()))
        self.assertTrue(flow.proves_leaf_calls)

    def test_rebinding_to_eval_propagates_target_and_static_use_definition(self):
        program,flow = self.compile('int=eval\nprint(int("3+4"))')
        first = next(iter(flow.calls.values()))
        self.assertEqual(first.callee.targets,{'eval'})
        self.assertFalse(first.direct_unmodified_leaf)
        self.assertEqual(len(first.callee.definitions),1)
        self.assertFalse(flow.proves_leaf_calls)
        self.assertFalse(dynamic_compilation_unreachable('int=eval\nprint(int("3+4"))',program))

    def test_fractional_power_keeps_possible_complex_promotion(self):
        program,flow = self.compile('value=(-1.0)**0.5\nprint(value)')
        _,use = self.load(program,flow,'value')
        self.assertEqual(use.entry.bindings['value'].types.kinds,{'float','complex'})

    def test_external_module_namespaces_do_not_assume_default_builtins(self):
        program,_ = self.compile('print(7)')
        self.assertFalse(analyze_code(program.codes[0]).proves_leaf_calls)
        self.assertTrue(analyze_code(program.codes[0],fresh_module=True).proves_leaf_calls)

    def test_effects_before_an_exception_reach_its_handler(self):
        program,flow=self.compile('x=1\ntry:exec("x=True;raise ValueError()")\nexcept:pass\nprint(x)')
        _,use=self.load(program,flow,'x')
        self.assertTrue(use.entry.bindings['x'].types.unknown)
        self.assertTrue(use.entry.bindings['x'].unknown_definition)
        self.assertFalse(flow.proves_leaf_calls)

    def test_parameter_entry_versions_are_separate_from_assignments(self):
        program,_ = self.compile('def f(value):\n return value')
        index=next(i for i,code in enumerate(program.codes) if code.name=='f')
        flow=program.flow.codes[index]
        _,use=self.load(program,flow,'value')
        entry=BindingVersion(index,-1,'value','parameter')
        self.assertEqual(flow.entry_definitions,{entry})
        self.assertEqual(use.uses['value'],{entry})

    def test_deleted_module_binding_can_load_builtin_fallback(self):
        program,flow=self.compile('int=3\ndel int\nrestored=int\nprint(restored)')
        _,use=self.load(program,flow,'restored')
        self.assertEqual(use.entry.bindings['restored'].types,TypeSet.from_kind('builtin'))
        self.assertEqual(use.entry.bindings['restored'].targets,{'int'})
        self.assertFalse(dynamic_compilation_unreachable('int=3\ndel int\nrestored=int\nprint(restored)',program))

    def test_unknown_calls_invalidate_bindings_and_later_builtin_lookup(self):
        program,flow = self.compile('x=1\neval(input())\nprint(x)')
        _,use = self.load(program,flow,'x')
        self.assertTrue(use.entry.bindings['x'].types.unknown)
        self.assertTrue(use.entry.bindings['x'].unknown_definition)
        self.assertIn('x',use.unknown_uses)
        self.assertTrue(any(version.kind=='effect' for version in use.uses['x']))
        self.assertTrue(all(version in flow.definitions for version in use.uses['x']))
        self.assertTrue(list(flow.calls.values())[-1].callee.unknown_target)
        self.assertFalse(flow.proves_leaf_calls)

    def test_exception_edges_join_types_and_restore_operand_depth(self):
        program,flow = self.compile('x=0\ntry:\n x=1\n 1//0\nexcept:\n x=True\nprint(x)')
        _,use = self.load(program,flow,'x')
        self.assertEqual(use.entry.bindings['x'].types,TypeSet.from_kind('int_bool'))
        self.assertEqual(len(use.uses['x']),3)
        setup = next(pc for pc,op in enumerate(program.codes[0].ops) if op.op=='SetupExcept')
        target = program.codes[0].ops[setup].args[0]
        binary = next(pc for pc,op in enumerate(program.codes[0].ops) if op.op=='Binary')
        self.assertTrue(any(edge.kind=='exception' and edge.target==target
                            for edge in flow.instructions[binary].successors))
        self.assertEqual(flow.instructions[target].entry.stack,())
        self.assertTrue(any(edge.target==-2 for edge in flow.instructions[binary].successors))

    def test_finally_keeps_pending_break_continue_and_return_paths(self):
        program,flow = self.compile('x=0\nfor i in range(2):\n try:\n  if i:break\n  continue\n finally:x=True\nprint(x)')
        targets = {op.args[0] for op in program.codes[0].ops if op.op in {'Break','Continue'}}
        resumes = {edge.target for pc,op in enumerate(program.codes[0].ops) if op.op=='EndFinally'
                   for edge in flow.instructions[pc].successors if edge.kind=='resume'}
        self.assertTrue(targets <= resumes)
        _,use = self.load(program,flow,'x')
        self.assertTrue({'int','bool'} <= use.entry.bindings['x'].types.kinds)
        program,_ = self.compile('def f():\n try:return 1\n finally:x=True')
        index = next(i for i,c in enumerate(program.codes) if c.name=='f')
        code,flow = program.codes[index],program.flow.codes[index]
        returned = next(pc for pc,op in enumerate(code.ops) if op.op=='Return')
        self.assertTrue(any(edge.kind=='finally' for edge in flow.instructions[returned].successors))

    def test_unknown_container_contents_do_not_invent_integer_iteration(self):
        program,flow = self.compile('rows=[["word"]]\nfor item in rows[0]:pass\nprint(item)')
        _,use = self.load(program,flow,'item')
        self.assertTrue(use.entry.bindings['item'].types.unknown)
        self.assertNotEqual(use.entry.bindings['item'].types.kinds,{'int'})

    def test_slices_and_starred_unpack_keep_container_result_types(self):
        program,flow=self.compile('a,*middle,z=(1,2,3)\nraw=b"abc"\nitem=raw[0]\ntail=raw[1:]\npart=(1,True)[1:]\nprint(middle,item,tail,part)')
        for name,kind in [('middle','list'),('item','int'),('tail','bytes'),('part','tuple')]:
            with self.subTest(name=name):
                _,use=self.load(program,flow,name)
                self.assertEqual(use.entry.bindings[name].types,TypeSet.from_kind(kind))

    def test_cell_storage_and_ordinary_names_have_independent_versions(self):
        code = Code('cells','flow.py','Module',locals=['x','got'],ops=[
            Instruction('Const',(1,)),Instruction('StoreCell',('x',)),
            Instruction('Const',('text',)),Instruction('Store',('x',)),
            Instruction('LoadCell',('x',)),Instruction('Store',('got',)),
            Instruction('Const',(None,)),Instruction('Return')])
        flow = analyze_code(code)
        self.assertEqual(flow.instructions[5].exit.bindings['got'].types,TypeSet.from_kind('int'))
        self.assertEqual(flow.instructions[4].uses['x'],{BindingVersion(0,1,'x','store_cell')})

    def test_custom_class_namespace_does_not_claim_exact_stored_types(self):
        program,_ = self.compile('class C:\n x=1\n y=x')
        index = next(i for i,code in enumerate(program.codes) if code.kind=='Class')
        _,use = self.load(program,program.flow.codes[index],'x')
        self.assertTrue(use.entry.bindings['x'].types.unknown)

    def test_ir_edits_refresh_analysis_and_lowered_dynamic_target_blocks_pruning(self):
        source='print(int("3+4"))'
        program,flow = self.compile(source)
        self.assertTrue(dynamic_compilation_unreachable(source,program))
        previous = program.flow
        changed = next(op for op in program.codes[0].ops if op.op=='Load' and op.args==('int',))
        changed.args=('eval',)
        self.assertFalse(dynamic_compilation_unreachable(source,program))
        self.assertIsNot(previous,program.flow)
        self.assertEqual(next(iter(program.flow.codes[0].calls.values())).callee.targets,{'eval'})
        self.assertIs(analyze_program(program),program.flow)

    def test_unsupported_ir_and_analysis_limits_retain_the_full_runtime(self):
        source='print(7)'
        program,_ = self.compile(source)
        program.codes[0].ops.insert(0,Instruction('UnknownCompilerHelper'))
        self.assertFalse(dynamic_compilation_unreachable(source,program))
        self.assertIn('unsupported operation: UnknownCompilerHelper',program.flow.codes[0].reasons)
        code=Code('limited','flow.py','Module',ops=[Instruction('Nop'),Instruction('Nop')])
        self.assertFalse(analyze_code(code,max_updates=0).complete)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IRFlowExecutionTests(unittest.TestCase):
    def execute(self,rust,data=''):
        with tempfile.TemporaryDirectory(prefix='pytors-ir-flow-') as directory:
            source=Path(directory)/'main.rs';binary=Path(directory)/'main'
            source.write_text(rust)
            compiled=subprocess.run(['rustc','--edition=2021',str(source),'-o',str(binary)],
                                    capture_output=True,text=True,timeout=120)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            return subprocess.run([str(binary)],input=data,capture_output=True,text=True,
                                  timeout=15,env={'PATH':'/pytors-no-python'})

    def test_changed_ir_target_keeps_a_working_dynamic_runtime(self):
        source='print(int("3+4"))'
        program=Compiler('changed.py').compile(source)
        next(op for op in program.codes[0].ops if op.op=='Load' and op.args==('int',)).args=('eval',)
        include_dynamic=not dynamic_compilation_unreachable(source,program)
        self.assertTrue(include_dynamic)
        rust,_=generate(program,include_dynamic=include_dynamic)
        self.assertIn('struct PegParser',rust)
        result=self.execute(rust)
        self.assertEqual((result.returncode,result.stdout),(0,'7\n'),result.stderr)

    def test_branch_loop_exception_and_dynamic_effect_programs_keep_python_behavior(self):
        sources=[
            ('state=0\nfor i in range(3):\n if i:state=True\nprint(state)',''),
            ('state=0\ntry:\n state=int(input())\nexcept:\n state=True\nprint(state)','invalid\n'),
            ('value=1\nexec("value=True")\nprint(value)',''),
        ]
        for source,data in sources:
            with self.subTest(source=source):
                result=transpile(source,TranspileOptions(optimize=False,filename='flow_execution.py'))
                self.assertTrue(result.success,result.diagnostics)
                actual=self.execute(result.rust_source,data)
                expected=subprocess.run([sys.executable,'-S','-c',source],input=data,capture_output=True,text=True)
                self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
