"""Private vectors move to public list carriers at a proved tail return."""
import shutil,unittest
from py2fastrust import TranspileOptions,transpile
import test_native_lambda_callbacks as helpers

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TailVectorTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_recursive_vectors_publish_distinct_mutable_rows(self):
        source='''def build(n):
 values=[[0]*n for _ in range(n)]
 for i in range(n):
  for j in range(n):values[i][j]=i*10+j
 return values
a=build(int(input()))
a[0][1]+=7
print(a,a[0]is a[1])
'''
        self.exercise(source,('2\n','3\n','0\n'))
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('Option<Vec<Vec<NativeInt>>>',result.rust_source)

    def test_flat_vectors_append_pop_rebind_and_publish_once(self):
        self.exercise('''class Marker:pass
def build(n):
 values=[0]*n
 values.append(9)
 for i in range(n):values[i]=i+1
 values.pop()
 return values
a=build(3)
b=build(3)
a[0]=8
print(a,b,a is b)
''')

    def test_repeated_rows_and_copied_outer_vectors_keep_child_aliases(self):
        self.exercise('''class Marker:pass
def build(row):
 values=[row]*3
 values[1][0]=4
 return values
row=[1]
a=build(row)
a[2].append(9)
print(a,row,a[0]is a[1])
def shallow(source):
 result=list(source)
 result.append(source[0])
 return result
b=shallow(a)
b[0][0]=7
print(a,b,row)
''')

    def test_alias_exports_and_closure_writes_retain_shared_storage(self):
        self.exercise('''class Marker:pass
def build():
 values=[[1],[2]]
 alias=values
 alias[0][0]=5
 def change():values[1][0]=8
 change()
 return values
a=build()
a[0].append(9)
print(a)
''')

    def test_unbound_tail_return_has_original_failure_location(self):
        self.exercise('''class Marker:pass
def build(flag):
 if flag:values=[[1],[2]]
 return values
print(build(int(input())))
''',('0\n','1\n'))

    def test_pending_cleanup_keeps_its_explicit_unsupported_diagnostic(self):
        # This control-flow feature is also unsupported by the base compiler.
        # Ownership lowering must retain that diagnostic, never erase cleanup.
        source='''class Marker:pass
def build():
 values=[[1],[2]]
 try:
  return values
 finally:
  values[0][0]=7
print(build())
'''
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertEqual(result.diagnostics[0].line,4)
            self.assertIn('exception-handler routing',result.diagnostics[0].message)

    def test_cleanup_before_return_also_keeps_its_unsupported_diagnostic(self):
        source='''class Marker:pass
def build():
 values=[[1],[2]]
 try:
  values[0][0]=4
 finally:
  values[1][0]=9
 return values
print(build())
'''
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertEqual(result.diagnostics[0].line,4)
            self.assertIn('exception-handler routing',result.diagnostics[0].message)

    def test_lambda_body_is_not_a_statement_tail(self):
        self.exercise('''class Marker:pass
f=lambda flag:len(values)if flag else(values:=[1,2])[0]
print(f(int(input())))
''',('0\n','1\n'))

    def test_reference_object_payloads_keep_their_existing_carrier(self):
        source='''class Box:
 def __init__(self,value):self.value=value
def build():
 values=[Box(1)]
 values[0].value=3
 return values
a=build()
b=a[0]
a[0].value=7
print(b.value,a[0]is b)
'''
        self.exercise(source)
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('Option<Vec<ClassHandle_',result.rust_source)

    def test_three_dimensional_vectors_publish_without_row_copies(self):
        self.exercise('''class Marker:pass
def build():
 values=[[[0]*2 for _ in range(3)]for _ in range(2)]
 values[1][2][1]=7
 return values
a=build()
a[0][0][0]=9
print(a,a[0]is a[1],a[0][0]is a[0][1])
''')

    def test_mixed_scalar_vector_keeps_type_changes_after_return(self):
        self.exercise('''class Marker:pass
def build():
 values=[1,2]
 values[0]='left'
 values.append(False)
 return values
a=build()
a[1]='right'
print(a)
''')

if __name__=='__main__':unittest.main()
