"""Plain metadata requires direct imports and unique module executions."""
from pathlib import Path
import shutil
import unittest

from py2fastrust import transpile, TranspileOptions
import test_native_lambda_callbacks as helpers
import test_native_finite_depth_calls as projects


CASES = {'plain_module_chain': {'main.py': 'import bridge\n'
                                   'from leaf import Token as Alias\n'
                                   'x=Alias(True)\n'
                                   'print(bridge.value,isinstance(x,Alias),x.flag)\n',
                        'leaf.py': 'class Token:\n def __init__(self,flag):self.flag=flag\n',
                        'bridge.py': 'import leaf\nvalue=leaf.Token(False).flag\n'},
 'pending_instance': {'main.py': 'import leaf\n'
                                 'x=leaf.Token(False)\n'
                                 'print(leaf.initial.flag,x.flag,isinstance(leaf.initial,leaf.Token))\n',
                      'leaf.py': 'class Token:\n'
                                 ' def __init__(self,flag):self.flag=flag\n'
                                 'initial=Token(True)\n'},
 'class_aliases': {'main.py': 'import leaf\n'
                              'from leaf import Token as Alias\n'
                              'Earlier=Alias\n'
                              'x=Earlier(True)\n'
                              'Alias=leaf.Other\n'
                              'y=Alias(False)\n'
                              'print(isinstance(x,Earlier),isinstance(x,Alias),isinstance(y,Earlier),isinstance(y,Alias),x.flag,y.flag)\n',
                   'leaf.py': 'class Token:\n'
                              ' def __init__(self,flag):self.flag=flag\n'
                              'class Other:\n'
                              ' def __init__(self,flag):self.flag=flag\n'},
 'direct_import_repeated': {'main.py': 'import leaf\n'
                                       'First=leaf.Token\n'
                                       'import leaf\n'
                                       'x=First(True)\n'
                                       'print(First is '
                                       'leaf.Token,isinstance(x,leaf.Token),x.flag)\n',
                            'leaf.py': 'class Token:\n def __init__(self,flag):self.flag=flag\n'},
 'function_import_unexecuted': {'main.py': 'class Token:\n'
                                           ' def __init__(self,flag):self.flag=flag\n'
                                           'def unused():\n'
                                           ' import leaf\n'
                                           ' return leaf.Token(True).flag\n'
                                           'saved=unused\n'
                                           'print(Token(True).flag)\n',
                                'leaf.py': 'class Token:\n'
                                           ' def __init__(self,flag):self.flag=flag\n'},
 'conditional_import': {'main.py': 'if True:\n import leaf\nprint(leaf.Token(True).flag)\n',
                        'leaf.py': 'class Token:\n def __init__(self,flag):self.flag=flag\n'},
 'loop_import': {'main.py': 'for _ in range(2):\n import leaf\nprint(leaf.Token(True).flag)\n',
                 'leaf.py': 'class Token:\n def __init__(self,flag):self.flag=flag\n'},
 'map_stop_failed_retry': {'main.py': 'import state\n'
                                      'def load(value):\n'
                                      ' import unstable\n'
                                      ' return value\n'
                                      'print(list(map(load,[1])))\n'
                                      'import unstable\n'
                                      'Old,New=state.saved\n'
                                      'old=Old(True)\n'
                                      'new=New(False)\n'
                                      'print(Old is '
                                      'New,isinstance(old,Old),isinstance(old,New),isinstance(new,Old),isinstance(new,New),old.flag,new.flag)\n',
                           'state.py': 'saved=[]\nfail=True\ndef keep(value):saved.append(value)\n',
                           'unstable.py': 'import state\n'
                                          'class Token:\n'
                                          ' def __init__(self,flag):self.flag=flag\n'
                                          'state.keep(Token)\n'
                                          'if state.fail:\n'
                                          ' state.fail=False\n'
                                          ' raise StopIteration("first import")\n'},
 'with_suppressed_failed_retry': {'main.py': 'import state\n'
                                             'class Suppress:\n'
                                             ' def __enter__(self):return None\n'
                                             ' def __exit__(self,a,b,c):return True\n'
                                             'with Suppress():\n'
                                             ' import unstable\n'
                                             'import unstable\n'
                                             'Old,New=state.saved\n'
                                             'old=Old(True)\n'
                                             'new=New(False)\n'
                                             'print(Old is '
                                             'New,isinstance(old,Old),isinstance(old,New),isinstance(new,Old),isinstance(new,New),old.flag,new.flag)\n',
                                  'state.py': 'saved=[]\n'
                                              'fail=True\n'
                                              'def keep(value):saved.append(value)\n',
                                  'unstable.py': 'import state\n'
                                                 'class Token:\n'
                                                 ' def __init__(self,flag):self.flag=flag\n'
                                                 'state.keep(Token)\n'
                                                 'if state.fail:\n'
                                                 ' state.fail=False\n'
                                                 ' raise ValueError("first import")\n'}}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeSingleExecutionMetadataTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise_project = projects.NativeFiniteDepthTests.exercise_project

    def compile_project(self, key, mode):
        folder = Path(self.directory.name) / (key + "_proof")
        folder.mkdir(exist_ok=True)
        for name, text in CASES[key].items():
            (folder / name).write_text(text)
        path = folder / "main.py"
        result = transpile(path.read_text(), TranspileOptions(integer=mode, filename=str(path)))
        self.assertTrue(result.success, result.diagnostics)
        return result.rust_source

    def test_direct_module_chain_uses_zero_size_metadata_in_all_integer_modes(self):
        for mode in ("i64", "i128", "bigint"):
            source = self.compile_project("plain_module_chain", mode)
            self.assertRegex(source, r"struct ClassValueMetadata_\d+;")
            self.assertNotIn("(&'static ClassClassRef)", source)
            self.assertNotIn("(Option<ClassClassRef>)", source)

    def test_control_flow_imports_keep_owned_capable_metadata(self):
        for key in ("conditional_import", "loop_import", "map_stop_failed_retry", "with_suppressed_failed_retry"):
            source = self.compile_project(key, "i64")
            self.assertIn("(Option<ClassClassRef>)", source)
            self.assertNotIn("(&'static ClassClassRef)", source)

    def test_plain_module_chain(self):
        self.exercise_project(CASES['plain_module_chain']["main.py"], files=CASES['plain_module_chain'])

    def test_pending_instance(self):
        self.exercise_project(CASES['pending_instance']["main.py"], files=CASES['pending_instance'])

    def test_class_aliases(self):
        self.exercise_project(CASES['class_aliases']["main.py"], files=CASES['class_aliases'])

    def test_direct_import_repeated(self):
        self.exercise_project(CASES['direct_import_repeated']["main.py"], files=CASES['direct_import_repeated'])

    def test_function_import_unexecuted(self):
        self.exercise_project(CASES['function_import_unexecuted']["main.py"], files=CASES['function_import_unexecuted'])

    def test_conditional_import(self):
        self.exercise_project(CASES['conditional_import']["main.py"], files=CASES['conditional_import'])

    def test_loop_import(self):
        self.exercise_project(CASES['loop_import']["main.py"], files=CASES['loop_import'])

    def test_map_stop_failed_retry(self):
        self.exercise_project(CASES['map_stop_failed_retry']["main.py"], files=CASES['map_stop_failed_retry'])

    def test_with_suppressed_failed_retry(self):
        self.exercise_project(CASES['with_suppressed_failed_retry']["main.py"], files=CASES['with_suppressed_failed_retry'])


if __name__ == "__main__":
    unittest.main()
