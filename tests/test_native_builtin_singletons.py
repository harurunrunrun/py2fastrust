"""Canonical builtin singleton values and their fallible truth demands."""
import shutil,unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
from tests import test_native_context_managers as support

CASES = {'aliases_and_mixed_containers': {'main.py': 'saved=NotImplemented\n'
                                             'def choose(flag):return saved if flag else None\n'
                                             'values=[choose(True),choose(False)]\n'
                                             'print(saved,saved is NotImplemented,values,values[0]is '
                                             'saved)\n'},
 'function_argument_and_return': {'main.py': 'def same(value):return value\n'
                                             'print(same(NotImplemented)is '
                                             'NotImplemented,str(same(NotImplemented)),repr(NotImplemented))\n'},
 'conditional_truth_error': {'main.py': "print('before')\nif NotImplemented:print('wrong')\n"},
 'and_expression_truth_error': {'main.py': "print('before')\nvalue=NotImplemented and 3\n"},
 'captured_bool_error': {'main.py': "check=bool\nprint('before')\ncheck(NotImplemented)\n"},
 'print_flush_before_output_and_sep_validation': {'main.py': "print('before')\n"
                                                             "print('wrong "
                                                             "output',sep=3,flush=NotImplemented)\n"},
 'expanded_print_flush_before_output': {'main.py': "print('before')\n"
                                                   'print(*[1,2],flush=NotImplemented)\n'},
 'filter_truth_at_pull_location': {'main.py': 'source=filter(None,[NotImplemented])\n'
                                              "print('before')\n"
                                              'print(next(source))\n'},
 'any_truth_at_consumer_location': {'main.py': "print('before')\nprint(any([False,NotImplemented]))\n"},
 'all_short_circuits_before_singleton': {'main.py': 'print(all([False,NotImplemented]),any([True,NotImplemented]))\n'},
 'map_strict_truth_during_construction': {'main.py': 'def f(value):return value\n'
                                                     "print('before')\n"
                                                     'source=map(f,[1],strict=NotImplemented)\n'},
 'with_exit_result_ignored_on_normal_body': {'main.py': 'class Guard:\n'
                                                        " def __enter__(self):print('enter')\n"
                                                        " def __exit__(self,a,b,c):print('exit');return "
                                                        'NotImplemented\n'
                                                        "with Guard():print('body')\n"
                                                        "print('after')\n"},
 'with_exit_truth_error_preserves_body_context': {'main.py': 'class Guard:\n'
                                                             ' def __enter__(self):return self\n'
                                                             ' def __exit__(self,a,b,c):return '
                                                             'NotImplemented\n'
                                                             'with Guard():1//0\n'},
 'isinstance_invalid_late_tuple_short_circuit': {'main.py': 'print(isinstance(3,(int,NotImplemented)))\n'
                                                            "print(isinstance('x',(int,NotImplemented)))\n"},
 'noncallable_singleton_evaluates_arguments': {'main.py': "def mark():print('argument');return 3\n"
                                                          'NotImplemented(mark())\n'},
 'local_parameter_shadow': {'main.py': 'def run(NotImplemented):return NotImplemented+1\n'
                                       'print(run(4))\n'},
 'global_shadow_after_assignment': {'main.py': 'NotImplemented=4\n'
                                               'class Box:\n'
                                               ' def read(self):return 3\n'
                                               'print(NotImplemented+Box().read())\n'},
 'bool_union_finite_arguments': {'main.py': 'def check(value):return bool(value)\n'
                                            'print(check(0))\n'
                                            'print(check(NotImplemented))\n'},
 'class_field_singleton': {'main.py': 'class Box:\n'
                                      ' marker=NotImplemented\n'
                                      'print(Box.marker is NotImplemented,Box().marker)\n'},
 'filter_callback_returns_singleton': {'main.py': 'def predicate(value):return NotImplemented\n'
                                                  'source=filter(predicate,[1])\n'
                                                  "print('before')\n"
                                                  'next(source)\n'},
 'notimplemented_singleton_alias_and_display': {'main.py': 'value=NotImplemented\n'
                                                           'print(value,value is '
                                                           'NotImplemented,str(value),repr(value))\n'
                                                           'print(value is '
                                                           'None,value==None,value!=None)\n'}}

UNSUPPORTED = {'notimplemented_builtin_module_alias': 'import builtins\n'
                                        'saved=builtins.NotImplemented\n'
                                        'print(saved is NotImplemented,saved)\n',
 'notimplemented_captured_before_rebind': 'saved=NotImplemented\n'
                                          'NotImplemented=3\n'
                                          'print(saved,NotImplemented)\n'}


class SingletonBoundaryTests(unittest.TestCase):
    def test_native_singleton_selection_uses_binding_ownership(self):
        source='value=NotImplemented\nprint(value)\n'
        selected=select_frames(build_program(source,'main.py').main)
        self.assertTrue(selected.required)
        self.assertIn('canonical builtin singleton values',selected.reasons)
        shadow=select_frames(build_program('def f(NotImplemented):return NotImplemented+1\nprint(f(3))\n','main.py').main)
        self.assertNotIn('canonical builtin singleton values',shadow.reasons)

    def test_no_singleton_program_omits_singleton_runtime(self):
        result=transpile('print(7)\n')
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('struct NativeNotImplemented',result.rust_source)

    def test_mutable_builtin_fallback_and_module_exports_are_positioned(self):
        for name,source in UNSUPPORTED.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename='main.py',integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn('builtin',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SingletonExecutionTests(unittest.TestCase):
    exercise=support.ContextManagerExecutionTests.exercise


def _execution(files):
    def test(self):self.exercise(files)
    return test


CASES.update({'map_invalid_iterable_strict_error_first': {'main.py': 'def f(value):return value\n'
                                                        "print('before')\n"
                                                        'map(f,3,strict=NotImplemented)\n'},
 'zip_invalid_iterable_strict_error_first': {'main.py': "print('before')\n"
                                                        'zip(3,strict=NotImplemented)\n'}})

for _name,_files in CASES.items():setattr(SingletonExecutionTests,'test_'+_name,_execution(_files))
