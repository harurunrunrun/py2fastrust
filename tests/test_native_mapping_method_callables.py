"""Builtin mapping bound methods retain receiver, binding and lookup effects."""
import shutil,unittest
import test_native_stdio as stdio_tests
from py2fastrust import transpile,TranspileOptions

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MappingMethodCallableTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_temporary_dictionary_and_saved_map_callback(self):
        source='''values=list(map(int,input().split()))
order=sorted(set(values))
callback={value:index for index,value in enumerate(order)}.__getitem__
print(list(map(callback,values)))
print(list(map({3:7,4:8}.__getitem__,[4,3,4])))
'''
        self.differential(source,[b'8 3 8 1 3\n',b'\n'],profiles=(False,True))

    def test_saved_and_direct_receiver_precede_argument_rebinding(self):
        source='''d={1:8}
saved=d.__getitem__
def key():
    global d
    print('key')
    d={1:9}
    return 1
print(saved(key()),d[1])
d={1:12}
print(d.__getitem__(key()),d[1])
'''
        self.differential(source,profiles=(False,True))

    def test_alias_identity_and_receiver_operation_equality(self):
        source='''d={1:8}
f=d.__getitem__
saved=f
other=d.__getitem__
get=d.get
print(bool(f),f is saved,f is other,f==other,f==get)
print(f!=other,f is not other,f==None,f==1)
other_dict={1:8}
print(f==other_dict.__getitem__)
print(f(1),saved(1))
'''
        self.differential(source,profiles=(False,True))

    def test_all_arguments_run_before_binding_errors(self):
        for method,arguments in [('__getitem__',"trace('a',1),trace('b',2)"),
                                 ('__getitem__',"key=trace('key',1)"),
                                 ('get',"trace('a',1),trace('b',2),trace('c',3)"),
                                 ('setdefault',"key=trace('key',1),default=trace('default',2)")]:
            source='''def trace(label,value):
    print(label)
    return value
d={1:8}
f=d.'''+method+'\nf('+arguments+')\n'
            self.differential(source,profiles=(False,True))

    def test_get_setdefault_and_alias_mutation_observe_current_dictionary(self):
        source='''d={1:8}
fetch=d.get
put=d.setdefault
lookup=d.__getitem__
print(fetch(1),fetch(3),fetch(3,7))
print(put(1,99),put(3,6),lookup(3))
d[1]=14
print(fetch(1),lookup(True),len(d))
print(put(5),fetch(5,19),len(d))
'''
        self.differential(source,profiles=(False,True))

    def test_missing_and_unhashable_keys_keep_real_errors(self):
        for expression in ['99','[1]']:
            source='d={1:8}\nf=d.__getitem__\nprint(1)\nprint(f('+expression+'))\n'
            self.differential(source,profiles=(False,True))

    def test_counter_getitem_and_get_have_different_missing_rules(self):
        source='''from collections import Counter
counts=Counter()
f=counts.__getitem__
get=counts.get
print(f(7),get(7),len(counts))
counts[7]=3
print(f(7),get(7),len(counts))
'''
        self.differential(source,profiles=(False,True))

    def test_defaultdict_factory_runs_after_receiver_borrow_ends(self):
        source='''from collections import defaultdict

def factory():
    print('factory')
    d[0]=99
    return 7

d=defaultdict(factory)
f=d.__getitem__
get=d.get
print(get(4),len(d))
print(f(4),f(4),d[0],len(d))
'''
        self.differential(source,profiles=(False,True))

    def test_mapping_method_as_default_factory_defers_its_binding_error(self):
        source='''from collections import defaultdict
owner={1:8}
d=defaultdict(owner.__getitem__)
print('constructed')
print(d[4])
'''
        self.differential(source,profiles=(False,True))

    def test_returned_method_and_finite_callable_choices(self):
        source='''def method(d):return d.__getitem__
def negate(x):return -x
d={1:8,2:9}
f=method(d) if int(input()) else negate
print(list(map(f,[1,2,1])))
'''
        self.differential(source,[b'0\n',b'1\n'],profiles=(False,True))
