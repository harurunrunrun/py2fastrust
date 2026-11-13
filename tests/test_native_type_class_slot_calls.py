"""Solved builtin class objects remain callable in ordinary class namespaces."""
import shutil,unittest
import test_native_stdio as stdio_tests

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassSlotTypeCalls(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_returned_and_canonical_classes_stay_unbound_in_class_slots(self):
        self.differential('''class Factory:
    returned=type(1)
    original=int
    empty=type(None)
    buffer=type(bytearray())
factory=Factory()
saved=Factory.returned
print(Factory.returned('2'),factory.returned('3'),saved('4'))
print(Factory.original('5'),factory.original('6'),Factory.empty(),factory.empty())
print(factory.buffer(b'23'),Factory.buffer(2),type(Factory.returned)is type)
''',profiles=(False,True))

    def test_finite_class_slot_keeps_selected_constructor(self):
        self.differential('''flag=int(input())
class Factory:
    build=type(True) if flag else type(1)
factory=Factory()
print(Factory.build(3),factory.build(0),Factory.build is bool,Factory.build is int)
''',[b'0\n',b'1\n'],profiles=(False,True))

    def test_callee_capture_precedes_argument_class_slot_replacement(self):
        self.differential('''class Factory:
    build=type(1)
def argument():
    Factory.build=type('')
    print('argument')
    return '23'
print(Factory.build(argument()))
print(Factory.build(7),type(Factory.build(7))is str)
''',profiles=(False,True))

    def test_receiver_and_arguments_execute_once_in_source_order(self):
        self.differential('''class Factory:
    build=type(1)
factory=Factory()
def receiver():
    print('receiver')
    return factory
def argument():
    print('argument')
    return '17'
print(receiver().build(argument()))
''',profiles=(False,True))

    def test_class_alias_retains_stored_constructor_identity(self):
        self.differential('''class Factory:
    build=type(1)
Saved=Factory
saved=Saved.build
Factory.build=type('')
print(saved('31'),Saved.build(17),saved is int,Saved.build is str)
''',profiles=(False,True))

    def test_wrong_call_shape_runs_all_argument_effects_before_type_error(self):
        self.differential('''class Factory:
    build=type(None)
def argument(value):
    print(value)
    return value
Factory.build(argument(1),extra=argument(2))
''',profiles=(False,True))
