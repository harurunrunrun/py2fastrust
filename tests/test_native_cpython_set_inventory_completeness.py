"""CP-first contracts for unavailable original constant-origin metadata."""
import ast,builtins,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

FORWARD='{0,8,16,24,32}'
REVERSE='{32,24,16,8,0}'
MIXED='def unused():\n return '+REVERSE+'\nprint(list('+FORWARD+'))\n'
ERASED=MIXED.replace('print(list(', 'print(sorted(')
CONTEXTUAL='def unused():\n {32,24,16,8,False and (yield 99)}\nprint(list({False,8,16,24,32}))\n'
NONCONSTANT='def unused(value):\n {value,32,24,16,False and (yield 99)}\nprint(list('+FORWARD+'))\n'


@unittest.skipUnless(sys.implementation.name=='cpython'and sys.version_info[:3]==(3,14,4),'CPython 3.14.4 is required')
class IncompleteConstantInventories(unittest.TestCase):
    def oracle(self,source,modules=None):
        directory=tempfile.TemporaryDirectory(prefix='pytors-set-inventory-')
        self.addCleanup(directory.cleanup)
        root=Path(directory.name);(root/'main.py').write_text(source)
        for name,body in (modules or{}).items():(root/name).write_text(body)
        results={}
        for seed in (0,1,42,4294967295):
            ran=subprocess.run([sys.executable,'-B',str(root/'main.py')],capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':str(seed)},timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)
            results[seed]=ran
        self.assertFalse(list(root.rglob('*.pyc')))
        return root,results

    def origins(self,source,mode='i64',filename='inventory.py'):
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_cpython_set_constants import ConstantOrigins
        unit=parse_source(source,filename)
        parents={id(child):parent for parent in ast.walk(unit.tree)for child in ast.iter_child_nodes(parent)}
        return unit,ConstantOrigins(SimpleNamespace(unit=unit,integer=mode),parents)

    def fault(self,stage,error_type=ValueError,line=2):
        import py2fastrust.native_cpython_set_constants as constants
        original=getattr(constants,stage,builtins.compile if stage=='compile'else None)
        def unavailable(*args,**kwargs):
            node=args[0] if stage!='_classify'else args[1]
            if isinstance(node,ast.Expression):node=node.body
            if getattr(node,'lineno',None)==line:raise error_type('unavailable contributor metadata')
            return original(*args,**kwargs)
        return mock.patch.object(constants,stage,unavailable,create=stage=='compile')

    def test_metadata_unavailability_never_certifies_absence(self):
        from py2fastrust import transpile,TranspileOptions
        self.oracle(MIXED)
        for stage in ('compile','_compile','_classify'):
            for error_type in (SyntaxError,TypeError,ValueError):
                for mode in ('i64','i128','bigint'):
                    with self.subTest(stage=stage,error=error_type.__name__,mode=mode):
                        with self.fault(stage,error_type):
                            converted=transpile(MIXED,TranspileOptions(filename='missing_history.py',integer=mode,license='none'))
                        self.assertFalse(converted.success);self.assertIsNone(converted.rust_source)
                        error=converted.diagnostics[0]
                        self.assertEqual((error.code,error.filename,error.line),('E006','missing_history.py',3))
                        self.assertIn('inventory is incomplete',error.message)
                        self.assertIn('missing_history.py:2:',error.message)
                        self.assertIn(error_type.__name__,error.message)
                        self.assertIn('unavailable contributor metadata',error.message)

    def test_empty_classification_and_unrepresentable_history_are_incomplete(self):
        from py2fastrust.native_classes import ClassUnsupported
        import py2fastrust.native_cpython_set_constants as constants
        self.oracle(MIXED)
        original_classify=constants._classify;original_history=constants.history
        def no_plan(code,node):return set() if node.lineno==2 else original_classify(code,node)
        def no_history(values):return None if values==[32,24,16,8,0] else original_history(values)
        for name,replacement,reason in (('_classify',no_plan,'no proved instruction plan'),('history',no_history,'cannot be represented')):
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    unit,origins=self.origins(MIXED,mode)
                    target=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Set)and node.lineno==3)
                    with mock.patch.object(constants,name,replacement),self.assertRaises(ClassUnsupported)as raised:origins.certify(target)
                    self.assertIn('inventory is incomplete',str(raised.exception))
                    self.assertIn(reason,str(raised.exception))

    def test_real_context_failure_keeps_full_original_inventory_and_location(self):
        from py2fastrust import transpile,TranspileOptions
        from py2fastrust.native_classes import ClassUnsupported
        self.oracle(CONTEXTUAL)
        for mode in ('i64','i128','bigint'):
            unit,origins=self.origins(CONTEXTUAL,mode,'contextual.py')
            original_tree=ast.dump(unit.tree,include_attributes=True)
            target=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Set)and node.lineno==3)
            with self.assertRaises(ClassUnsupported)as raised:origins.certify(target)
            self.assertIn('inventory is incomplete',str(raised.exception))
            self.assertIn('contextual.py:2:',str(raised.exception))
            self.assertIn('SyntaxError',str(raised.exception))
            inventory=origins.units[id(unit)]
            self.assertTrue(inventory.issues)
            self.assertIs(inventory.issues[0].node,unit.tree.body[0].body[0].value.elts[-1])
            self.assertEqual(ast.dump(unit.tree,include_attributes=True),original_tree)
            converted=transpile(CONTEXTUAL,TranspileOptions(filename='contextual.py',integer=mode,license='none'))
            self.assertFalse(converted.success)
            # The complete frontend currently rejects expression yields even
            # in unused declarations, before this emitter proof is reached.
            self.assertEqual((converted.diagnostics[0].code,converted.diagnostics[0].line),('E006',2))
            self.assertIn('send() values',converted.diagnostics[0].message)

    def test_defaults_annotations_and_dead_source_contributors_cannot_disappear(self):
        from py2fastrust.native_classes import ClassUnsupported
        sources={
            'default':'def unused(value='+REVERSE+'):\n pass\nprint(list('+FORWARD+'))\n',
            'annotation':'def unused(value: [item for item in '+REVERSE+']):\n pass\nprint(list('+FORWARD+'))\n',
            'dead':'if False:\n def unused():\n  return '+REVERSE+'\nprint(list('+FORWARD+'))\n',
        }
        for name,source in sources.items():
            self.oracle(source)
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    unit,origins=self.origins(source,mode,name+'.py')
                    sets=[node for node in ast.walk(unit.tree)if isinstance(node,ast.Set)]
                    hidden=next(node for node in sets if node.elts[0].value==32)
                    target=next(node for node in sets if node.elts[0].value==0)
                    with self.fault('_compile',line=hidden.lineno),self.assertRaises(ClassUnsupported)as raised:origins.certify(target)
                    self.assertIn('inventory is incomplete',str(raised.exception))
                    self.assertIn(name+'.py:'+str(hidden.lineno)+':',str(raised.exception))

    def test_own_operand_history_is_required_even_with_order_erasure(self):
        from py2fastrust.native_classes import ClassUnsupported
        self.oracle(ERASED)
        for mode in ('i64','i128','bigint'):
            unit,origins=self.origins(ERASED,mode)
            target=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Set)and node.lineno==3)
            proof=mock.Mock(return_value=True)
            with self.fault('compile',line=3),self.assertRaises(ClassUnsupported)as raised:origins.certify(target,order_irrelevant=proof)
            self.assertIn('no proved typed constant operand history',str(raised.exception))
            proof.assert_not_called()

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_closed_order_erasure_remains_sound_when_metadata_is_unavailable(self):
        root,oracles=self.oracle(ERASED)
        with self.fault('_compile'):self.execute(ERASED,root,oracles)

    def test_contextual_closed_erasure_keeps_earlier_generator_boundary(self):
        from py2fastrust import transpile,TranspileOptions
        source=CONTEXTUAL.replace('print(list(', 'print(sorted(')
        self.oracle(source)
        for mode in ('i64','i128','bigint'):
            converted=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertFalse(converted.success)
            self.assertEqual(converted.diagnostics[0].code,'E006')
            self.assertIn('send() values',converted.diagnostics[0].message)

    def test_runtime_operand_excludes_only_its_original_contextual_run(self):
        from py2fastrust import transpile,TranspileOptions
        self.oracle(NONCONSTANT)
        for mode in ('i64','i128','bigint'):
            unit,origins=self.origins(NONCONSTANT,mode)
            inventory=origins.inventory(unit)
            self.assertFalse(inventory.issues)
            target=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Set)and node.lineno==3)
            origins.certify(target)
            converted=transpile(NONCONSTANT,TranspileOptions(integer=mode,license='none'))
            self.assertFalse(converted.success)
            self.assertIn('send() values',converted.diagnostics[0].message)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_runtime_operand_excludes_failed_sibling_without_changing_execution(self):
        import py2fastrust.native_cpython_set_constants as constants
        source='def unused(value):\n return {value,32,24,16,8}\nprint(list('+FORWARD+'))\n'
        root,oracles=self.oracle(source)
        def unavailable(tree,*args,**kwargs):
            if isinstance(tree,ast.Expression)and isinstance(tree.body,ast.Constant)and tree.body.lineno==2:
                raise SyntaxError('unavailable constant sibling metadata')
            return builtins.compile(tree,*args,**kwargs)
        with mock.patch.object(constants,'compile',unavailable,create=True):self.execute(source,root,oracles)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_separate_original_module_inventory_does_not_poison_main(self):
        source='import helper\n\n\nprint(list('+FORWARD+'))\n'
        root,oracles=self.oracle(source,{'helper.py':'def unused():\n return '+REVERSE+'\n'})
        with self.fault('_compile',line=2):self.execute(source,root,oracles)

    def execute(self,source,root,oracles):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            converted=transpile(source,TranspileOptions(filename=str(root/'main.py'),module_paths=(root,),integer=mode,license='none'))
            self.assertTrue(converted.success,str(converted.diagnostics))
            self.assertLessEqual(len(converted.rust_source.encode()),512*1024)
            rust=root/(mode+'.rs');rust.write_text(converted.rust_source)
            for optimized in (False,True):
                binary=root/(mode+('_O'if optimized else'_debug'))
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(built.returncode,0,built.stderr[:12000])
                for seed,oracle in oracles.items():
                    ran=subprocess.run([str(binary)],capture_output=True,text=True,env={**os.environ,'PYTHONHASHSEED':str(seed)},timeout=10)
                    self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(oracle.returncode,oracle.stdout,oracle.stderr),(mode,optimized,seed))
