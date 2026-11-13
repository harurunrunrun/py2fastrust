"""Module builtin shadows retain their real bindings inside source callables."""
import shutil,unittest
import test_native_stdio as stdio_tests

CASES={'ordinary_direct_type': 'def type(value):return value+7\ndef test():return type(3)\nprint(test()+1)\n',
 'ordinary_alias_lambda': 'type=lambda value:value+7\ndef test():return type(3)\nprint(test()+1)\n',
 'ordinary_dormant_store': 'def type(value):return value+7\n'
                           'def unused():\n'
                           '    global type\n'
                           '    type=lambda value:value*9\n'
                           'def test():return type(3)\n'
                           'print(test()+1)\n',
 'ordinary_dormant_delete': 'def type(value):return value+7\n'
                            'def unused():\n'
                            '    global type\n'
                            '    del type\n'
                            'def test():return type(3)+type(4)\n'
                            'print(test())\n',
 'ordinary_before_after_publication': 'def observe():return type(3)\n'
                                      'print(observe() is int)\n'
                                      'def type(value):return value+7\n'
                                      'print(observe())\n',
 'ordinary_callback_rebind': 'def type(value):return value+7\n'
                             'def mutate():\n'
                             '    global type\n'
                             '    type=lambda value:value*9\n'
                             'def observe():\n'
                             '    before=type(3)\n'
                             '    mutate()\n'
                             '    after=type(3)\n'
                             '    return before+after\n'
                             'print(observe())\n',
 'ordinary_callback_delete': 'def type(value):return value+7\n'
                             'def remove():\n'
                             '    global type\n'
                             '    del type\n'
                             'def observe():\n'
                             '    remove()\n'
                             '    return type(3)\n'
                             'print(observe() is int)\n',
 'method_alias_before_class': 'type=lambda value:value+7\n'
                              'class Runner:\n'
                              '    def run(self):return type(3)\n'
                              'print(Runner().run()+1)\n',
 'method_alias_after_class': 'class Runner:\n'
                             '    def run(self):return type(3)\n'
                             'type=lambda value:value+7\n'
                             'print(Runner().run()+1)\n',
 'ordinary_alias_after_definition': 'def run():return type(3)\n'
                                    'type=lambda value:value+7\n'
                                    'print(run()+1)\n',
 'method_call_before_then_after_publication': 'class Runner:\n'
                                              '    def run(self):return type(3)\n'
                                              'instance=Runner()\n'
                                              'print(instance.run() is int)\n'
                                              'type=lambda value:value+7\n'
                                              'print(instance.run())\n',
 'ordinary_call_before_then_after_publication': 'def run():return type(3)\n'
                                                'print(run() is int)\n'
                                                'type=lambda value:value+7\n'
                                                'print(run())\n',
 'recursion_inherits_published_entry': 'def read(depth):\n'
                                       '    if depth:return read(depth-1)\n'
                                       '    return type(3)\n'
                                       'type=lambda value:value+7\n'
                                       'print(read(4)+1)\n',
 'multiple_callers_intersect_entry': 'def read():return type(3)\n'
                                     'def first():return read()\n'
                                     'def second():return read()\n'
                                     'type=lambda value:value+7\n'
                                     'print(first()+second())\n',
 'new_early_indirect_context_removes_certainty': 'def read():return type(3)\n'
                                                 'def dispatch(callback):return callback()\n'
                                                 'print(dispatch(read) is int)\n'
                                                 'type=lambda value:value+7\n'
                                                 'print(read())\n',
 'argument_effects_preserve_callee_and_change_body_lookup': 'def type(value):return value+7\n'
                                                            'def replace():\n'
                                                            '    global type\n'
                                                            '    type=lambda value:value*9\n'
                                                            "    print('replace')\n"
                                                            '    return 3\n'
                                                            'def captured():return type(replace())\n'
                                                            'def lookup(argument):return type(3)\n'
                                                            'print(captured(),lookup(replace()),type(3))\n',
 'actual_function_instance_defaults_retained': 'def factory(delta):\n'
                                               '    def build(value=delta):return value+1\n'
                                               '    return build\n'
                                               'def read():return type()\n'
                                               'type=factory(7)\n'
                                               'saved=type\n'
                                               'print(read())\n'
                                               'type=factory(30)\n'
                                               'print(read(),saved(),saved is type)\n',
 'pending_returned_closure_after_consumer_definition': 'def factory(delta):\n'
                                                       '    def build(value):return delta+value\n'
                                                       '    return build\n'
                                                       'def read():return type(3)\n'
                                                       'type=factory(7)\n'
                                                       'print(read()+1)\n',
 'parameter_and_local_shadow_remain_lexical': 'def apply(type):return type(3)\n'
                                              'def local():\n'
                                              '    type=lambda value:value*9\n'
                                              '    return type(3)\n'
                                              'type=lambda value:value+7\n'
                                              'print(apply(type),local())\n',
 'real_none_is_not_a_pending_binding': 'type=None\n'
                                       'def argument():\n'
                                       "    print('argument')\n"
                                       '    return 3\n'
                                       'def read():return type(argument())\n'
                                       'read()\n',
 'method_callback_keeps_all_actual_producers': 'def type(value):return value+7\n'
                                               'def replace():\n'
                                               '    global type\n'
                                               '    type=lambda value:value*9\n'
                                               'class Runner:\n'
                                               '    def read(self):\n'
                                               '        first=type(3)\n'
                                               '        replace()\n'
                                               '        return first+type(3)\n'
                                               'print(Runner().read())\n',
 'same_source_callsite_before_after_publication': 'def read():return type(3)\n'
                                                  'for step in range(2):\n'
                                                  '    if step:type=lambda value:value+7\n'
                                                  '    print(read())\n'}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FunctionBindingPublicationTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_ordinary_and_method_publication_contexts(self):
        for name,source in CASES.items():
            with self.subTest(name=name):self.differential(source,profiles=(False,True))


class CrossModuleFunctionBindingTests(unittest.TestCase):
    import test_native_module_linking as _support
    exercise=_support.NativeLinkedModuleTests.exercise

    def test_source_globals_keep_their_original_module_in_functions_and_methods(self):
        self.exercise({
            'main.py':'''from library import Runner,observe
def type(value):return value*9
def read():return type(3)
print(Runner().read(),observe(),read())
''',
            'library.py':'''def type(value):return value+7
def observe():return type(3)
class Runner:
    def read(self):return type(3)
'''})
