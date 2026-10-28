"""Name lookup precedes later arguments; borrowing follows their effects."""
import shutil
import unittest

import test_native_iterator_reductions as helpers
from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeContainerReadTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeIteratorReductionTests.tearDownClass.__func__)
    compile = helpers.NativeIteratorReductionTests.compile
    compare = helpers.NativeIteratorReductionTests.compare

    def exercise(self, source, inputs=("0\n", "1\n"), *, modes=("i64", "i128", "bigint")):
        for mode in modes:
            for release in (False, True):
                with self.subTest(mode=mode, release=release):
                    compiled = self.compile(source, mode, release)
                    for data in inputs:
                        self.compare(compiled, data, mode=mode, trace=True)

    def test_optional_set_name_is_resolved_before_sorted_keywords(self):
        self.exercise('''def keynone():
 print("key",end="|")
 return None
if int(input()):
 values=set([3,1])
print("start",end="|")
print(sorted(values,key=keynone()))
''')

    def test_optional_list_name_is_resolved_before_sum_start(self):
        self.exercise('''def mark(value):
 print(value,end="|")
 return value
if int(input()):
 values=[3,1]
print("start",end="|")
print(sum(values,mark(7)))
''')

    def test_optional_typed_list_name_is_resolved_before_sorted_keywords(self):
        self.exercise('''def keynone():
 print("key",end="|")
 return None
if int(input()):
 values=["b","a"]
print("start",end="|")
print(sorted(values,key=keynone()))
''')

    def test_optional_deque_name_is_resolved_before_sum_start(self):
        self.exercise('''from collections import deque
def mark(value):
 print(value,end="|")
 return value
if int(input()):
 values=deque([3,1])
print("start",end="|")
print(sum(values,mark(7)))
''', modes=("i64", "i128"))

    def test_optional_dictionary_names_and_views_precede_sorted_keywords(self):
        self.exercise('''def keynone():
 print("key",end="|")
 return None
if int(input()):
 values={(2,"b"):5,(1,"a"):3}
print("start",end="|")
print(sorted(values,key=keynone()))
print(sorted(values.keys(),key=keynone()))
print(sorted(values.values(),key=keynone()))
print(sorted(values.items(),key=keynone()))
''')

    def test_function_list_arguments_resolve_before_later_arguments(self):
        self.exercise('''def mark(value):
 print(value,end="|")
 return value
def total(values,start):
 return sum(values,start)
if int(input()):
 values=[3,1]
print("start",end="|")
print(total(values,mark(7)))
''')

    def test_unbound_local_errors_keep_the_callee_source_position(self):
        self.exercise('''def mark(value):
 print(value,end="|")
 return value
def total(flag):
 if flag:
  values=[3,1]
 print("start",end="|")
 return sum(values,mark(7))
print(total(int(input())))
''')

    def test_later_arguments_may_mutate_the_resolved_list_contents(self):
        self.exercise('''def total(values,start):
 return sum(values,start)
values=[1,2,3]
print(sum(values,values.pop()),values)
print(sorted(values,reverse=bool(values.pop())),values)
values=[4,5,6]
print(total(values,values.pop()),values)
''', ("",))

    def test_non_name_sources_are_evaluated_once_before_keywords(self):
        self.exercise('''def make():
 print("make",end="|")
 return [3,1,3]
def keynone():
 print("key",end="|")
 return None
print(sorted(make(),key=keynone()))
print(sorted(set(make()),key=keynone()))
''', ("",))

    def test_later_sum_argument_can_still_pop_from_a_deque(self):
        self.exercise('''from collections import deque
values=deque([1,2,3])
print(sum(values,values.popleft()),len(values),sum(values))
''', ("",), modes=("i64", "i128"))

    def test_callbacks_cannot_silently_replace_a_deferred_binding(self):
        # Namespace mutation still needs shared binding identities. These are
        # explicit unsupported boundaries, not successful feature acceptance.
        sources = (
            'values=[3,1]\ndef change():\n global values\n values=[9]\n return None\nprint(sorted(values,key=change()))\n',
            'values=set([3,1])\ndef change():\n global values\n values=set([9])\n return None\nprint(sorted(values,key=change()))\n',
            'values=[3,1]\nprint(sum(values,(values:=[9])[0]))\n',
        )
        for mode in ("i64", "i128", "bigint"):
            for source in sources:
                result = transpile(source, TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code, "E006")


if __name__ == "__main__":
    unittest.main()
