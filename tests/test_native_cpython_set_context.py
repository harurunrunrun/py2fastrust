"""Original whole-context compiler facts and linked set-literal observations."""
import ast,dis,os,shutil,subprocess,sys,tempfile,types,unittest
from pathlib import Path
from types import SimpleNamespace


def instructions(code):
    yield from dis.get_instructions(code)
    for item in code.co_consts:
        if isinstance(item,types.CodeType):yield from instructions(item)


@unittest.skipUnless(sys.implementation.name=='cpython'and sys.version_info[:3]==(3,14,4),'CPython 3.14.4 construction facts are required')
class OriginalSetContexts(unittest.TestCase):
    def test_small_integer_constant_loads_remain_folded_metadata(self):
        from py2fastrust.native_cpython_set_context import PolicyProbe
        for mode in ('i64','i128'):
            for source,value in [('1+1',2),('0+0',0),('8+0',8)]:
                original=ast.parse(source,mode='eval').body
                self.assertIn('LOAD_SMALL_INT',{item.opname for item in dis.get_instructions(compile(ast.Expression(original),'original.py','eval',optimize=0))})
                result=PolicyProbe(mode).visit(original)
                self.assertIsInstance(result,ast.Constant);self.assertEqual(result.value,value)
            original=ast.parse('2**128',mode='eval').body
            self.assertIsInstance(PolicyProbe(mode).visit(original),ast.Call)

    def test_entire_original_expression_observation_matches_whole_source(self):
        from py2fastrust.native_cpython_set_context import construction_plan
        literal='{0,8,16,24,32}'
        wrappers=[literal,'('+literal+'if flag else other)','(other if flag else'+literal+')',
                  '(flag or'+literal+')','('+literal+'or other)','(flag and'+literal+')',
                  '('+literal+'and other)','(False or'+literal+')','(True and'+literal+')',
                  '(not'+literal+')','(not not'+literal+')','(captured:='+literal+')',
                  'identity('+literal+')','('+literal+',)[0]']
        contexts=['for value in EXPR:\n pass\n','out=[value for value in EXPR]\n',
                  'out=(value for value in EXPR)\n','value in EXPR\n',
                  'value in EXPR in other\n','if EXPR:\n pass\n',
                  'if value in EXPR in other:\n pass\n','out=EXPR\n']
        count=0
        for context in contexts:
            for wrapper in wrappers:
                source=context.replace('EXPR',wrapper)
                if ':='in wrapper and context.startswith(('out=[','out=(')):continue
                tree=ast.parse(source);node=next(item for item in ast.walk(tree)if isinstance(item,ast.Set))
                parents={id(child):parent for parent in ast.walk(tree)for child in ast.iter_child_nodes(parent)}
                location=(node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)
                emitted=[item for item in instructions(compile(tree,'whole_context.py','exec',optimize=0))
                         if tuple(item.positions)==location]
                operations={item.opname for item in emitted}
                if 'SET_UPDATE'in operations:expected='frozen_bulk'
                elif any(item.opname=='LOAD_CONST'and type(item.argval)is frozenset for item in emitted):expected='frozen_direct'
                else:self.fail((source,operations))
                actual=construction_plan(SimpleNamespace(integer='bigint'),node,parents)
                self.assertEqual(actual,expected,(source,operations));count+=1
        self.assertEqual(count,110)

    def test_width_normalized_lazy_control_does_not_use_host_integer_truth(self):
        from py2fastrust.native_cpython_set_context import construction_plan
        source='for value in ((18446744073709551616)or{0,8,16,24,32}):\n pass\n'
        tree=ast.parse(source);node=next(item for item in ast.walk(tree)if isinstance(item,ast.Set))
        parents={id(child):parent for parent in ast.walk(tree)for child in ast.iter_child_nodes(parent)}
        self.assertEqual(construction_plan(SimpleNamespace(integer='i64'),node,parents),'frozen_bulk')
        # The constructor is dead for i128/BigInt. A value plan only types the
        # unexecuted original lazy branch, without inventing an iteration use.
        self.assertEqual(construction_plan(SimpleNamespace(integer='i128'),node,parents),'frozen_bulk')
        self.assertEqual(construction_plan(SimpleNamespace(integer='bigint'),node,parents),'frozen_bulk')

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_imported_original_for_and_comprehension_contexts(self):
        from py2fastrust import transpile,TranspileOptions
        main='from helper import sequence,comprehension\nprint(sequence(),comprehension())\n'
        helper='def sequence():\n out=[]\n for value in {0,8,16,24,32}:out.append(value)\n return out\ndef comprehension():\n return [value for value in {0,8,16,24,32}]\n'
        with tempfile.TemporaryDirectory(prefix='pytors-imported-set-context-')as temporary:
            root=Path(temporary);(root/'main.py').write_text(main);(root/'helper.py').write_text(helper)
            expected={}
            for seed in (0,1,42,4294967295):
                self.assertFalse(list(root.rglob('*.pyc')))
                expected[seed]=subprocess.run([sys.executable,'-B',str(root/'main.py')],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':str(seed)},capture_output=True,text=True,timeout=10)
                self.assertFalse(list(root.rglob('*.pyc')))
            for mode in ('i64','i128','bigint'):
                converted=transpile(main,TranspileOptions(filename=str(root/'main.py'),module_paths=(str(root),),integer=mode,license='none'))
                self.assertTrue(converted.success,str(converted.diagnostics))
                rust=root/(mode+'.rs');rust.write_text(converted.rust_source)
                for optimized in (False,True):
                    binary=root/(mode+('_optimized'if optimized else'_debug'))
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(built.returncode,0,built.stderr[:12000])
                    for seed,oracle in expected.items():
                        actual=subprocess.run([str(binary)],env={**os.environ,'PYTHONHASHSEED':str(seed)},capture_output=True,text=True,timeout=10)
                        self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(oracle.returncode,oracle.stdout,oracle.stderr),(mode,optimized,seed))
