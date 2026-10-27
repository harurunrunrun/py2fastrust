"""Single-codepoint iterator operands retain text semantics without eager copies."""
import re
import shutil
import subprocess
import unittest

import test_native_iterator_reductions as helpers
from py2fastrust.aot import rust_mask


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeCharacterStreamTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeIteratorReductionTests.tearDownClass.__func__)
    compile = helpers.NativeIteratorReductionTests.compile
    compare = helpers.NativeIteratorReductionTests.compare

    def exercise(self, source, inputs=("",), *, profiles=(True,), string_mode="ascii", shape=None):
        for integer in ("i64", "i128", "bigint"):
            for release in profiles:
                with self.subTest(integer=integer, release=release, string_mode=string_mode):
                    compiled = self.compile(source, integer, release, string_mode=string_mode)
                    if shape:
                        shape(rust_mask(compiled[2]))
                    for data in inputs:
                        self.compare(compiled, data, trace=True)

    def no_character_materialization(self, rust):
        self.assertNotIn("char::from_u32", rust)
        self.assertNotRegex(rust, r"native_temp_\d+\.to_string\(\)")
        self.assertRegex(rust, r"let native_temp_\d+:u32=")

    def test_ascii_predicate_truth_and_length_reductions_do_not_materialize_items(self):
        def shape(rust):
            self.no_character_materialization(rust)
            self.assertIn(".bytes()", rust)
            self.assertNotIn(".chars()", rust[rust.rfind("fn main"):])
        self.exercise('''s=input()
print(sum(c=="X" for c in s),any(c for c in s),all(c for c in s))
print(sum(len(c) for c in s),sum(bool(c) for c in s))
''', ("XXxyX\n", "\n", "a\n"), profiles=(False, True), shape=shape)

    def test_unicode_iterates_codepoints_and_preserves_order(self):
        def shape(rust):
            self.no_character_materialization(rust)
            self.assertIn(".chars()", rust[rust.rfind("fn main"):])
        self.exercise('''s=input()
print(sum(c=="猫" for c in s),sum(c>"α" for c in s))
print(sum(len(c) for c in s),sum(bool(c) for c in s))
''', ("猫α🦀é\n", "\n", "a👩‍👧\n"), profiles=(False, True),
                      string_mode="unicode", shape=shape)

    def test_map_filter_and_builtin_aliases_keep_the_captured_projection(self):
        self.exercise('''s=input()
text=str
size=len
test=bool
print(sum(map(test,s)),sum(map(size,map(text,s))))
print(any(filter(None,s)),all(c==str(c) for c in map(text,s)))
''', ("aX00\n", "\n", "猫α🦀\n"), string_mode="unicode",
                      shape=self.no_character_materialization)

    def test_enumerate_reverse_and_flat_zip_share_field_metadata(self):
        self.exercise('''s=input()
print(sum(i*(c=="x") for i,c in enumerate(s,start=3)))
print(sum(a==b for a,b in zip(s,reversed(s))))
print(all(c for c in reversed(s)))
''', ("xoxx\n", "\n", "x\n"), profiles=(False, True),
                      shape=self.no_character_materialization)

    def test_nested_generator_locals_do_not_leak_or_reexecute_outer_operands(self):
        self.exercise('''s=input()
c="outside"
print(sum(a==b for a in s if a!="x" for b in s if b!="y"))
print(sum(c=="x" for c in (d for d in s)))
print(c)
''', ("xyax\n", "\n"), shape=self.no_character_materialization)

    def test_escaping_characters_materialize_exact_text(self):
        self.exercise('''s=input()
values=list(c for c in s)
print(values,":".join(c for c in s))
print(next((c for c in s),"empty"))
''', ("猫α🦀é\n", "\n"), string_mode="unicode")

    def test_persistent_for_targets_keep_after_loop_values_and_else(self):
        self.exercise('''s=input()
c="before"
for c in s:
 if c=="x":
  continue
 if c=="z":
  break
else:
 print("else")
print(c)
''', ("\n", "xyzrest\n", "xx\n", "ab\n"), profiles=(False, True))

    def test_zero_trip_target_is_still_unbound(self):
        self.exercise('''for c in input():
 pass
print(c)
''', ("\n", "ok\n"), profiles=(False, True))

    def test_owner_rebinding_and_aliases_retain_original_iteration_snapshot(self):
        self.exercise('''s=input()
alias=s
for s in s:
 print(s,end="|")
print(s,alias)
for c in alias:
 alias="rebound"
 print(c,end="|")
print(alias)
''', ("abc\n", "猫🦀\n", "\n"), string_mode="unicode")

    def test_outer_source_evaluates_once_before_later_consumer_arguments(self):
        self.exercise('''def source():
 print("source",end="|")
 return input()
def start():
 print("start",end="|")
 return int(input())
print(sum((c=="x" for c in source()),start()))
print(input())
''', ("xox\n5\nlast\n", "\n9\nlast\n"))

    def test_short_circuit_preserves_input_and_generator_exception_frames(self):
        self.exercise('''s=input()
print(any(c=="x" or int(input()) for c in s))
print(input())
''', ("ax\n0\nlast\n", "xx\nlast\n", "a\nbad\nlast\n"),
                      profiles=(False, True))

    def test_projected_truth_and_length_retain_checked_index_errors(self):
        for operation in ("len", "bool"):
            self.exercise(f'''s=input()
print("prefix",end="|")
print({operation}(s[int(input())]))
''', ("a\n0\n", "a\n2\n", "\n0\n"))

    def test_specialized_functions_use_the_same_lazy_producer(self):
        self.exercise('''def count(s):
 return sum(c=="x" for c in s)
print(count(input()),count(input()))
''', ("xox\nxxx\n", "\n\n"), shape=self.no_character_materialization)

    def test_general_string_lists_are_not_assumed_single_codepoint(self):
        self.exercise('''values=["","xx","x"]
print(any(c for c in values),all(c for c in values))
print(sum(len(c) for c in values),list(c for c in values))
''')

    def test_unpruned_profiles_keep_native_scalar_types(self):
        source='s=input()\nprint(sum(c=="x" for c in s))\n'
        for integer in ("i64", "i128", "bigint"):
            compiled=self.compile(source,integer,prune=False)
            self.compare(compiled,"xox\n")
            main=compiled[2][compiled[2].rfind("fn main"):]
            self.assertNotIn("char::from_u32",rust_mask(main))

    def test_ascii_out_of_domain_text_remains_safe_and_whole_io_is_utf8(self):
        source='s=input()\nprint(s)\nprint(list(c for c in s))\n'
        for integer in ("i64", "i128", "bigint"):
            compiled=self.compile(source,integer)
            actual=subprocess.run([str(compiled[1])],input="猫🦀\n",text=True,
                                  capture_output=True,timeout=10)
            self.assertEqual(actual.returncode,0,actual.stderr)
            self.assertTrue(actual.stdout.startswith("猫🦀\n"))


if __name__ == "__main__":
    unittest.main()
