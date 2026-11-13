"""Python 3.14.4 defaultdict factories retain reentrant same-key inserts."""
import shutil,unittest
import test_native_stdio as stdio_tests

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DefaultdictMissingEffects(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_factory_retains_same_key_insert_for_subscript_and_bound_method(self):
        source='''from collections import defaultdict
def factory():
    print('factory')
    d[2]=99
    return 7
d=defaultdict(factory)
f=d.__getitem__
print(d[2],f(2))
del d[2]
print(f(2),d[2])
'''
        self.differential(source,profiles=(False,True))

    def test_reentrant_inserted_mutable_value_preserves_alias_identity(self):
        source='''from collections import defaultdict
def factory():
    d[1]=[99]
    return result
result=[]
d=defaultdict(factory)
f=d.__getitem__
found=f(1)
found.append(4)
print(found is result,d[1] is result,result,d[1])
'''
        self.differential(source,profiles=(False,True))

    def test_deletion_and_reentrant_reads_release_borrows(self):
        source='''from collections import defaultdict
def factory():
    alias[3]=99
    del alias[3]
    print('deleted',alias.get(3))
    alias[3]=20
    print('inner',read(3))
    return 7
d=defaultdict(factory)
alias=d
read=d.__getitem__
print(read(3),alias[3])
'''
        self.differential(source,profiles=(False,True))

    def test_raising_factory_retains_its_own_insert(self):
        source='''from collections import defaultdict
class Cleanup:
    def __enter__(self):return self
    def __exit__(self,a,b,c):
        print('cleanup',d.get(2))
        return True

def factory():
    d[2]=99
    print('inserted',d[2])
    raise ValueError('failed')
d=defaultdict(factory)
with Cleanup():
    print(d.__getitem__(2))
print('after',d[2])
'''
        self.differential(source,profiles=(False,True))

    def test_dict_setdefault_still_observes_argument_effects_before_lookup(self):
        source='''def value():
    d[2]=99
    print('argument')
    return 7
d={}
f=d.setdefault
print(f(2,value()),d[2])
'''
        self.differential(source,profiles=(False,True))
