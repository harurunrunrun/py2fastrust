"""Complete canonical math wildcard bindings use original ASTs and typed values."""
import ast
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions, transpile
from py2fastrust.native_math_exports import PUBLIC_NAMES, FUNCTION_NAMES, CONSTANT_BITS

SOURCES = {'exact_user_sqrt': 'from math import *\nprint(sqrt(2))\n', 'ordinary_supported_functions': 'from math import *\nprint(sqrt(81),gcd(18,24),isqrt(99),comb(12,3),factorial(7))\nprint(floor(-1.5),ceil(-1.5),trunc(-1.5),isfinite(0.0))\n', 'overwrites_prior_name': 'sqrt=99\nfrom math import *\nprint(sqrt(9))\n', 'later_source_definition': 'from math import *\ndef sqrt(value):return value+7\nprint(sqrt(2))\n', 'caller_defined_before_star': 'def run(value):return sqrt(value)\nfrom math import *\nprint(run(16))\n', 'before_star_builtin_pow': 'print(pow(2,3))\nfrom math import *\nprint(sqrt(4))\n', 'captured_alias_and_repeated_star': 'from math import *\nsaved=sqrt\nsqrt=lambda value:value+10\nprint(saved(25),sqrt(2))\nfrom math import *\nprint(saved(16),sqrt(36),saved is sqrt)\n', 'module_rebind_then_star': 'import math\noriginal=math.sqrt\nmath.sqrt=lambda value:value+7\nfrom math import *\nprint(sqrt(2),original(16))\n', 'saved_alias_before_module_rebind': 'import math\nfrom math import *\nsaved=sqrt\nmath.sqrt=lambda value:value+7\nfrom math import *\nprint(saved(25),sqrt(2),saved is sqrt)\n', 'unused_unimplemented_exports': 'from math import *\nprint("ready")\n', 'unimplemented_callable_reference': 'from math import *\nprint(sin)\n', 'all_constant_values': 'from math import *\nprint(pi,e,tau,inf,nan)\nprint(isfinite(pi),isinf(inf),isnan(nan))\n', 'constant_aliases_and_repeated_star': 'import math\nfrom math import *\nmarker=nan\nprint([marker]==[nan],[nan]==[math.nan],[nan]==[float("nan")])\nfrom math import *\nprint([marker]==[nan],[nan]==[math.nan])\n', 'constant_rebinding_keeps_captured_object': 'import math\nfrom math import *\nmarker=nan\nmath.nan=float("nan")\nfrom math import *\nprint([marker]==[nan],[nan]==[math.nan])\n', 'shadow_export_before_repeated_star': 'from math import *\nsqrt=lambda value:value-3\nsaved=sqrt\nprint(saved(8))\nfrom math import *\nprint(sqrt(81),saved(8))\n', 'source_globals_function_shadow': 'def globals():return "local"\nfrom math import *\nprint(globals(),sqrt(25))\n', 'callable_rebound_to_none': 'import math\nmath.sqrt=None\nsqrt="old"\nfrom math import *\nprint(sqrt)\n', 'constant_rebound_to_integer': 'import math\nmath.pi=7\nfrom math import *\nprint(pi,math.pi)\n', 'unused_unsupported_name_overwrites_source_function': 'def sin(value):return value+1\nfrom math import *\nprint(sqrt(2))\n'}
BOUNDARIES = {'unsupported_actual_sin': 'from math import *\nprint(sin(0))\n', 'unsupported_math_pow_shadows_builtin': 'from math import *\nprint(pow(2,3))\n', 'global_name_observer': 'from math import *\nprint("sin" in globals(),"pow" in globals())\n', 'dir_observer': 'from math import *\nprint("sin" in dir())\n', 'module_vars_observer': 'import math\nfrom math import *\nprint("sin" in vars(math))\n', 'module_late_added_export_boundary': 'import math\nmath.extra=7\nfrom math import *\nprint(extra)\n', 'module_all_override_boundary': 'import math\nmath.__all__=["sqrt"]\nfrom math import *\nprint(sqrt(9))\n'}
PROJECTS = {'source_math_shadow': {'math.py': '__all__=["sqrt"]\ndef sqrt(value):return value+100\n', 'main.py': 'from math import *\nprint(sqrt(2))\n'}, 'shared_module_reexport': {'library.py': 'from math import sqrt as original\n', 'main.py': 'from math import *\nfrom library import original\nprint(original(16),sqrt(25),original is sqrt)\n'}}
PROJECT_BOUNDARIES = {'transitive': {'library.py': 'from math import *\nvalue=sqrt(49)\n', 'main.py': 'import math\nfrom library import *\nprint(value,sqrt(16),[nan]==[math.nan])\n'}}


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class MathStarExecutionTests(unittest.TestCase):
    def compare(self, source, files=None):
        with tempfile.TemporaryDirectory(prefix='pytors-math-star-') as directory:
            directory=Path(directory)
            for name,body in (files or {}).items():
                path=directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
            script=directory/'entry.py';script.write_text(source)
            expected=subprocess.run([sys.executable,'-S','-B',str(script)],capture_output=True,text=True,timeout=20,
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            self.assertEqual(expected.returncode,0,expected.stderr)
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=str(script),module_paths=(directory,),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                rust=directory/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20,
                        env={**os.environ,'PATH':'/no-python-runtime','PYTHONPATH':'/no-python-runtime'})
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),
                                     (expected.returncode,expected.stdout,expected.stderr))

    def test_source_module_shadow_and_reexport(self):
        for name,files in PROJECTS.items():
            with self.subTest(name=name):
                self.compare(files['main.py'],{key:body for key,body in files.items()if key!='main.py'})


def _case(source):
    def test(self):self.compare(source)
    return test


for _name,_source in SOURCES.items():
    setattr(MathStarExecutionTests,'test_'+_name,_case(_source))


class MathStarMetadataTests(unittest.TestCase):
    def test_complete_target_export_inventory_and_constant_bits(self):
        self.assertEqual(len(PUBLIC_NAMES),62)
        self.assertEqual(len(FUNCTION_NAMES),57)
        self.assertEqual(set(PUBLIC_NAMES),FUNCTION_NAMES|set(CONSTANT_BITS))
        self.assertFalse(hasattr(math,'__all__'))
        self.assertEqual(tuple(name for name in vars(math)if not name.startswith('_')),PUBLIC_NAMES)
        self.assertEqual({name:struct.pack('>d',getattr(math,name)).hex()for name in CONSTANT_BITS},CONSTANT_BITS)

    def test_original_ast_and_official_star_scope_are_unchanged(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_module_linking import LinkedProgram
        program=build_program(SOURCES['exact_user_sqrt'],'main.py')
        before=[(id(node),ast.dump(node,include_attributes=True))for node in ast.walk(program.main.tree)]
        linked=LinkedProgram.from_program(program).unit
        after=[(id(node),ast.dump(node,include_attributes=True))for node in ast.walk(program.main.tree)]
        self.assertEqual(before,after)
        self.assertEqual(tuple(binding.exported_name for binding in linked.import_bindings(program.main.tree.body[0])),PUBLIC_NAMES)
        self.assertTrue(all(binding.node is program.main.tree.body[0].names[0]for binding in linked.import_bindings(program.main.tree.body[0])))

    def test_unused_exports_do_not_demand_numeric_kernels(self):
        for integer in ('i64','i128','bigint'):
            result=transpile(SOURCES['exact_user_sqrt'],TranspileOptions(integer=integer,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('fn native_math_sqrt',result.rust_source)
            for name in ('sin','gcd','factorial','comb','logarithm'):
                self.assertNotIn('fn native_math_'+name,result.rust_source)
            unused=transpile(SOURCES['unused_unimplemented_exports'],TranspileOptions(integer=integer,license='none'))
            self.assertTrue(unused.success,unused.diagnostics)
            self.assertNotIn('fn native_math_sqrt',unused.rust_source)


class MathStarBoundaryTests(unittest.TestCase):
    def test_unsupported_observers_and_calls_name_the_missing_protocol(self):
        for name,source in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer,license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(result.diagnostics)
                    self.assertTrue(all(d.code=='E006'and d.line>0 and d.column>0 for d in result.diagnostics))
                    self.assertTrue(all('Source:'in str(d)for d in result.diagnostics))
                    if name=='unsupported_actual_sin':self.assertTrue(any('math.sin'in d.message for d in result.diagnostics))
                    if name=='unsupported_math_pow_shadows_builtin':self.assertTrue(any('math.pow'in d.message for d in result.diagnostics))
        for files in PROJECT_BOUNDARIES.values():
            with tempfile.TemporaryDirectory(prefix='pytors-math-star-boundary-')as directory:
                directory=Path(directory)
                for name,body in files.items():(directory/name).write_text(body)
                for integer in ('i64','i128','bigint'):
                    result=transpile(files['main.py'],TranspileOptions(integer=integer,filename=str(directory/'main.py'),module_paths=(directory,),license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code=='E006'and'math.sqrt'in d.message and'identity'in d.message for d in result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MathStarConstantFactoryTests(unittest.TestCase):
    def test_checked_nan_identity_cache_and_error_cleanup(self):
        source='from math import *\nprint([nan]==[nan])\n'
        with tempfile.TemporaryDirectory(prefix='pytors-math-identity-')as directory:
            directory=Path(directory)
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,license='none'))
                self.assertTrue(result.success,result.diagnostics)
                module=re.search(r'fn class_import_(\d+)\(class_scope:ClassScope\)',result.rust_source)
                self.assertIsNotNone(module)
                number=module.group(1)
                kernel='\n#[test]fn math_data_checked_cache(){NATIVE_FLOAT_IDENTITY.with(|counter|counter.set(usize::MAX));let scope=ClassScope::new();'
                kernel+='let error=match class_import_'+number+'(scope.clone()){Err(error)=>error,Ok(_)=>panic!("expected checked identity capacity error")};'
                kernel+='assert!(error.message.contains("float identity capacity"));assert!(scope.modules.borrow()['+number+'].is_none());'
                kernel+='NATIVE_FLOAT_IDENTITY.with(|counter|counter.set(0));let first=class_import_'+number+'(scope.clone()).unwrap();'
                kernel+='let second=class_import_'+number+'(scope.clone()).unwrap();assert!(Rc::ptr_eq(&first,&second));'
                kernel+='assert_eq!(NATIVE_FLOAT_IDENTITY.with(|counter|counter.get()),1);}'
                rust=directory/(integer+'.rs');rust.write_text(result.rust_source+kernel)
                for optimized in(False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    build=subprocess.run(['rustc','--edition=2021','--test',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20,env={**os.environ,'PATH':'/no-python-runtime'})
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
