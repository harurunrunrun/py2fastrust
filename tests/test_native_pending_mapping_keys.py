"""Late producer evidence must resolve before selecting native hash key ABI."""
import shutil,unittest
from py2fastrust import TranspileOptions,transpile
import test_native_lambda_callbacks as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PendingMappingKeys(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_set_keys_from_late_nested_list_elements(self):
        self.exercise('''def make(n):
 rows=[[]for _ in range(3)]
 for i in range(n):rows[i%3].append((i,i+1))
 return rows
seen=set()
for row in make(int(input())):
 for left,right in row:seen.add((left,right))
print(sorted(seen))
''',('0\n','7\n'))

    def test_dictionary_tuple_keys_follow_later_function_results(self):
        self.exercise('''def first(x):return second(x)
def second(x):return third(x),x+1
def third(x):return x-2
table={}
for i in range(int(input())):table[first(i)]=i*3
print(sorted(table.items()))
''',('0\n','5\n'))

    def test_dictionary_literals_keep_nested_tuple_key_evidence(self):
        self.exercise('''def make(x):return ((leaf(x),"s"),x+1)
def leaf(x):return x*2
def collect(x):return {make(x):[x],make(x+1):[x+1]}
data=collect(int(input()))
print(sorted(data.items()))
''',('0\n','4\n'))

    def test_setdefault_values_retain_mutable_aliases(self):
        self.exercise('''def first(x):return leaf(x),x%2
def leaf(x):return x//2
table={}
for i in range(int(input())):
 value=table.setdefault(first(i),[])
 value.append(i)
print(sorted(table.items()))
''',('0\n','6\n'))

    def test_set_deletion_queries_wait_for_tuple_producers(self):
        self.exercise('''def key(x):return leaf(x),x+1
def leaf(x):return x
values={(i,i+1)for i in range(5)}
alias=values
alias.discard(key(1))
alias.remove(key(int(input())))
print(sorted(values))
''',('2\n','7\n'))

    def test_sequence_tuple_keys_keep_exact_hash_equality(self):
        self.exercise('''def key(n):return tuple(range(n))
values={}
for i in range(int(input())):values[key(i)]=i
print(sorted(values.items()))
''',('0\n','5\n'))

    def test_unhashable_tuple_members_still_have_specific_diagnostics(self):
        for source in ('''def key(x):return x,[]
s=set()
s.add(key(2))
''','''def key(x):return x,[]
s={(1,2)}
s.discard(key(2))
'''):
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertIn('key',result.diagnostics[0].message)
                self.assertIn('list',result.diagnostics[0].message)


if __name__=='__main__':unittest.main()
