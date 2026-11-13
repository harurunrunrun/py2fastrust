"""CP-first compile-unit constant-origin boundary and module partitioning."""
import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

FORWARD='{0,8,16,24,32}'
REVERSE='{32,24,16,8,0}'
BOUNDARIES={
 'lazy_annotation':'def unused(value: [element for element in {8, 0}]):\n pass\nprint([element for element in {0, 8}])\n',
 'same_scope':'print(list('+FORWARD+'));print(list('+REVERSE+'))\n',
 'dead_if':'if False:\n hidden='+REVERSE+'\nprint(list('+FORWARD+'))\n',
 'unused_nested':'print(list('+FORWARD+'))\ndef unused():\n return '+REVERSE+'\n',
 'dead_nested':'print(list('+FORWARD+'))\nif False:\n def unused():\n  return '+REVERSE+'\n',
 'unused_star_segment':'def unused(values):\n return {32,24,16,8,0,*values}\nprint(list('+FORWARD+'))\n',
 'unused_numeric_duplicate':'def unused():\n return {32,32.0,24,16,8,0}\nprint(list('+FORWARD+'))\n',
 'prefix_effects':'print("prefix")\na='+FORWARD+'\nprint(list(a))\nb='+REVERSE+'\nprint(list(b))\n',
}


@unittest.skipUnless(sys.implementation.name=='cpython'and sys.version_info[:3]==(3,14,4),'CPython 3.14.4 is required')
class ConstantPoolOrigins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-set-constant-origins-');cls.root=Path(cls.directory.name)
        cls.CP={name:subprocess.run([sys.executable,'-c',source],capture_output=True,text=True,env={**os.environ,'PYTHONHASHSEED':'0'},timeout=10)for name,source in BOUNDARIES.items()}
        assert all(value.returncode==0 for value in cls.CP.values())

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def test_mixed_possible_histories_diagnose_before_emitting_changed_order(self):
        from py2fastrust import transpile,TranspileOptions
        for name,source in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    converted=transpile(source,TranspileOptions(filename='constant_pool.py',integer=mode,license='none'))
                    self.assertFalse(converted.success);self.assertIsNone(converted.rust_source)
                    self.assertTrue(converted.diagnostics)
                    error=converted.diagnostics[0]
                    self.assertEqual(error.code,'E006');self.assertGreater(error.line,0)
                    self.assertEqual(error.filename,'constant_pool.py')
                    if name=='dead_nested'and 'canonical lexical callable ownership'in error.message:
                        # This original shape can fail earlier at its existing
                        # conditional-definition boundary; do not erase it.
                        continue
                    self.assertIn('constant-pool origin adapter',error.message)
                    self.assertIn('different insertion histories',error.message)

    def test_inventory_retains_original_dead_nested_producers(self):
        import ast
        from types import SimpleNamespace
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_classes import ClassUnsupported
        from py2fastrust.native_cpython_set_constants import ConstantOrigins
        unit=parse_source(BOUNDARIES['dead_nested'],'dead_nested.py')
        parents={id(child):parent for parent in ast.walk(unit.tree)for child in ast.iter_child_nodes(parent)}
        original=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Set)and node.lineno==1)
        for mode in ('i64','i128','bigint'):
            with self.assertRaises(ClassUnsupported)as error:ConstantOrigins(SimpleNamespace(unit=unit,integer=mode),parents).certify(original)
            self.assertIn('constant-pool origin adapter',str(error.exception))

    def test_selected_width_changes_constant_equivalence_without_fake_none(self):
        from py2fastrust import transpile,TranspileOptions
        source='print(list('+FORWARD+'))\nprint(list({32+(1<<64),24,16,8,0}))\n'
        fixed=transpile(source,TranspileOptions(integer='i64',license='none'))
        self.assertFalse(fixed.success);self.assertIn('constant-pool origin adapter',fixed.diagnostics[0].message)
        for mode in ('i128','bigint'):
            converted=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(converted.success,str(converted.diagnostics))

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_small_arithmetic_matches_unmodified_source_compilation(self):
        # All values fit every selected width: use unmodified CP source, with
        # no reference normalization or replacement callable in the oracle.
        self.execute('print(list({0+0,8+0,16+0,24+0,32+0}))\n',{})

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_identical_history_and_typed_bool_representatives(self):
        source=('def unused():\n return '+FORWARD+'\nprint(list('+FORWARD+'))\n'
                'print(list({True,8,16,24,32}),list({1,8,16,24,32}))\n')
        self.execute(source,{})

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_distinct_original_module_caches_do_not_conflict(self):
        source='from helper import values\nprint(list('+FORWARD+'),values())\n'
        self.execute(source,{'helper.py':'def values():\n return list('+REVERSE+')\n'})

    def execute(self,source,modules):
        from py2fastrust import transpile,TranspileOptions
        root=Path(tempfile.mkdtemp(prefix='program-',dir=self.root))
        main=root/'main.py';main.write_text(source)
        for name,body in modules.items():(root/name).write_text(body)
        oracles={}
        for seed in (0,1,42,4294967295):
            self.assertFalse(list(root.rglob('*.pyc')))
            oracles[seed]=subprocess.run([sys.executable,'-B',str(main)],capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':str(seed)},timeout=10)
            self.assertFalse(list(root.rglob('*.pyc')))
        self.assertTrue(all(item.returncode==0 for item in oracles.values()))
        for mode in ('i64','i128','bigint'):
            converted=transpile(source,TranspileOptions(filename=str(main),module_paths=(root,),integer=mode,license='none'))
            self.assertTrue(converted.success,str(converted.diagnostics))
            rust=root/(mode+'.rs');rust.write_text(converted.rust_source)
            for optimized in (False,True):
                binary=root/(mode+('_O'if optimized else'_debug'))
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(built.returncode,0,built.stderr[:12000])
                for seed,oracle in oracles.items():
                    ran=subprocess.run([str(binary)],capture_output=True,text=True,env={**os.environ,'PYTHONHASHSEED':str(seed)},timeout=10)
                    self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(oracle.returncode,oracle.stdout,oracle.stderr),(mode,optimized,seed))
