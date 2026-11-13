"""Actual class-slot Python functions bind receivers without losing captures."""
import shutil,unittest
import test_native_stdio as stdio_tests
from py2fastrust import transpile,TranspileOptions

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SourceFunctionDescriptorTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_plain_alias_default_and_unbound_class_lookup(self):
        self.differential('''class Offset:
    def __init__(self,n): self.n=n
    def apply(receiver,x=4): return receiver.n+x
    alias=apply
item=Offset(3)
print(item.alias(),item.apply(5),Offset.alias(item,7))
a=item.apply
b=item.alias
copy=a
print(a==b,a is b,a is copy,a(1),b(2))
''',profiles=(False,True))

    def test_zero_parameter_function_still_receives_instance_and_errors_after_arguments(self):
        self.differential('''class Receiver:
    def bad(): return 9
    alias=bad
def mark(x):
    print('arg',x)
    return x
obj=Receiver()
print('before')
obj.alias(mark(3))
''',profiles=(False,True))

    def test_class_body_rebound_origin_and_saved_alias(self):
        self.differential('''class Receiver:
    def original(self,x=3): return x+1
    alias=original
    def replacement(self,x=7): return x+9
    original=replacement
obj=Receiver()
print(obj.alias(),obj.original(),obj.alias==obj.original)
saved=obj.alias
Receiver.alias=Receiver.replacement
print(saved(),obj.alias(),saved==obj.alias)
''',profiles=(False,True))

    def test_module_function_and_builtin_class_data(self):
        self.differential('''__class__=17
base=4
def external(receiver,x=2): return base+x+__class__
class Receiver:
    run=external
    length=len
obj=Receiver()
print(obj.run(),Receiver.run(obj,5),obj.length([1,2,3]))
print(obj.run==obj.run,obj.length is len)
''',profiles=(False,True))

    def test_distinct_actual_function_instances_and_shared_alias(self):
        self.differential('''def make(n):
    def callback(receiver,x=2): return n+x
    return callback
class Receiver:
    first=make(3)
    second=make(3)
    alias=first
obj=Receiver()
print(obj.first(),obj.second(5),obj.first==obj.second,obj.first==obj.alias)
print(obj.first is obj.alias)
''',profiles=(False,True))

    def test_instance_dictionary_functions_stay_unbound(self):
        self.differential('''def plain(x): return x+7
class Receiver:
    def work(self,x): return x+1
obj=Receiver()
saved=obj.work
obj.work=plain
obj.other=plain
print(saved(3),obj.work(3),obj.other(4),obj.work is plain)
''',profiles=(False,True))

    def test_class_function_lookup_captured_before_argument_mutation(self):
        self.differential('''class Receiver:
    def first(self,x): return x+1
    alias=first
    def second(self,x): return x+10
obj=Receiver()
def change():
    print('change')
    Receiver.alias=Receiver.second
    return 4
print(obj.alias(change()),obj.alias(4))
''',profiles=(False,True))

    def test_existing_static_and_class_descriptors_are_not_double_bound(self):
        self.differential('''class Receiver:
    number=8
    @staticmethod
    def static(x=2): return x+1
    @classmethod
    def class_call(cls,x=2): return cls.number+x
    def ordinary(self,x): return x+3
    alias=ordinary
obj=Receiver()
print(obj.static(),Receiver.static(4),obj.class_call(),Receiver.class_call(4),obj.alias(5))
''',profiles=(False,True))

    def test_defined_lexical_class_stays_original_after_aliasing(self):
        self.differential('''class Origin:
    value=7
    def method(self): return __class__.value
class Destination:
    value=19
    method=Origin.method
obj=Destination()
print(obj.method(),Destination.method(obj))
''',profiles=(False,True))

    def test_class_deleted_function_slot_is_not_resurrected(self):
        source='''class Receiver:
    def original(self): return 3
    alias=original
    del original
obj=Receiver()
print(obj.original())
'''
        result=transpile(source,TranspileOptions(filename='deleted.py'))
        if result.success:self.differential(source,profiles=(False,True))
        else:
            self.assertTrue(result.diagnostics)
            self.assertIn('deleted',result.diagnostics[0].message)

    def test_method_equality_uses_receiver_identity_without_user_equality(self):
        self.differential('''class Receiver:
    def __eq__(self,other):
        print('unexpected receiver equality')
        return True
    def work(self): return 7
    alias=work
first=Receiver()
second=Receiver()
print(first.work==first.alias,first.work==second.alias,first.work!=second.work)
print([first.work]==[first.alias],[first.work]==[second.work])
''',profiles=(False,True))

    def test_capture_precedes_instance_slot_update_and_starred_arguments(self):
        self.differential('''def raw(x): return x+10
class Receiver:
    def work(receiver,x=4): return x+1
    alias=work
obj=Receiver()
def change():
    obj.alias=raw
    return 7
print(obj.alias(change()),obj.alias(7))
f=obj.work
print(f(*[3]),f(x=5))
''',profiles=(False,True))

    def test_mutable_default_and_external_function_capture_are_preserved(self):
        self.differential('''def make():
    default=[]
    def action(receiver,x=default):
        x.append(1)
        return len(x)
    return action
class Receiver:
    first=make()
    alias=first
obj=Receiver()
print(obj.first(),obj.alias(),Receiver.first(obj))
''',profiles=(False,True))

    def test_unimplemented_expanded_keywords_have_explicit_diagnostic(self):
        source='''class Receiver:
    def original(self,x=3): return x
    alias=original
f=Receiver().alias
f(**{'x':5})
'''
        result=transpile(source,TranspileOptions(filename='keywords.py'))
        self.assertFalse(result.success)
        self.assertTrue(result.diagnostics)
        self.assertIn('expanded keyword',result.diagnostics[0].message)
        self.assertEqual(result.diagnostics[0].line,5)

    def test_already_bound_class_data_retains_its_original_receiver(self):
        self.differential('''class Original:
    def __init__(self,n): self.n=n
    def run(self,x): return self.n+x
original=Original(10)
class Holder:
    saved=original.run
holder=Holder()
print(holder.saved(4),Holder.saved(5),holder.saved==original.run)
''',profiles=(False,True))

    def test_unbound_class_reads_observe_replacements_and_builtin_values(self):
        self.differential('''class Receiver:
    def original(self,x=2): return x+1
    alias=original
    def replacement(self,x=4): return x+7
obj=Receiver()
old=Receiver.original
Receiver.original=Receiver.replacement
print(old(obj),Receiver.original(obj),obj.original())
Receiver.alias=len
print(Receiver.alias([1,2]),obj.alias([1,2,3]))
''',profiles=(False,True))
