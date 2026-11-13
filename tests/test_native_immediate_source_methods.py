"""Only an exact, immediately invoked source-method descriptor uses the stack."""
import shutil,unittest
import test_native_stdio as stdio_tests
from py2fastrust import transpile,TranspileOptions
from py2fastrust.aot import rust_mask

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ImmediateSourceMethodTests(unittest.TestCase):
    setUpClass=classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass=classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile=stdio_tests.NativeStdioTests.compile
    differential=stdio_tests.NativeStdioTests.differential

    def test_exact_immediate_alias_uses_a_stack_payload(self):
        source='''class Receiver:
    def work(self,x=3): return x+1
    alias=work
obj=Receiver()
for i in range(3): print(obj.alias(i))
'''
        result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        code=rust_mask(result.rust_source)
        self.assertNotIn('Rc::new(ClassInstanceFunction_',code)
        self.assertIn('ClassInstanceFunction_',code)
        self.differential(source,profiles=(False,True))

    def test_stored_and_fresh_observable_methods_keep_their_heap_identity(self):
        source='''class Receiver:
    def work(self,x=3): return x+1
    alias=work
obj=Receiver()
saved=obj.alias
copy=saved
print(saved is copy,saved is obj.alias,saved==obj.alias,saved(4),obj.alias())
'''
        result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn('Rc::new(ClassInstanceFunction_',rust_mask(result.rust_source))
        self.differential(source,profiles=(False,True))

    def test_optional_instance_field_uses_the_general_captured_value(self):
        source='''def raw(x): return x+10
class Receiver:
    def work(self,x=3): return x+1
    alias=work
obj=Receiver()
if int(input()): obj.alias=raw
print(obj.alias(4))
'''
        self.differential(source,[b'0\n',b'1\n'],profiles=(False,True))
