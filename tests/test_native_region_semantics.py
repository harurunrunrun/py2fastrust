"""Independent execution checks for guarded and original checked Rust loops."""
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_native_iterator_reductions as _helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeRegionSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=_helpers.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def compile(self,source,mode='i64',*,guard=True,release=True,string_mode='ascii'):
        compiled=self.harness.compile(source,mode,release=release,string_mode=string_mode)
        from py2fastrust.aot import rust_mask
        masked=rust_mask(compiled[2])
        present=re.search(r'\blet\s+native_region_guard_\d+\s*=',masked) is not None
        self.assertEqual(present,guard,compiled[2])
        return compiled

    def compare(self,source,inputs,*,guard=True,wrapping=False,trace=True,modes=('i64','i128'),string_mode='ascii',debug=False):
        for mode in modes:
            for release in ((False,True) if debug else (True,)):
                compiled=self.compile(source,mode,guard=guard,release=release,string_mode=string_mode)
                for data in inputs:
                    with self.subTest(mode=mode,release=release,data=data):
                        self.harness.compare(compiled,data,mode=mode,wrapping=wrapping,trace=trace and not wrapping)

    def test_actual_owner_lengths_and_negative_python_indices(self):
        self.compare('''n=int(input())
offset=int(input())
s=input()
p=input()
total=0
for j in range(n):
 total+=s[j+offset]!=p[j]
print(total)
''',('3\n1\nabca\nbca\n','3\n-1\nabca\naxa\n','4\n0\nabc\nabcd\n','4\n0\nabcd\na\n'),debug=True)

    def test_guard_failure_preserves_print_input_and_exception_positions(self):
        self.compare('''n=int(input())
offset=int(input())
s=input()
p=input()
total=0
for j in range(n):
 print("visit",j)
 total+=s[j+offset]!=p[j]
 print("after",input())
print(total)
''',('3\n0\nabc\nx\nfirst\nsecond\n','3\n-1\nabcd\ndxy\na\nb\nc\n','0\n0\n\n\n'),debug=True)

    def test_zero_domains_preserve_prior_target_value_and_loop_else(self):
        self.compare('''n=int(input())
s=input()
p=input()
j=True
total=0
for j in range(n):
 total+=s[j]!=p[j]
else:
 print("done")
print(total,j)
''',('0\n\n\n','-2\n\n\n','3\nabc\nabc\n'),debug=True)

    def test_generator_filter_keeps_lazy_error_scope_and_prefix(self):
        self.compare('''n=int(input())
offset=int(input())
s=input()
p=input()
print("before")
answer=sum(s[j+offset]!=p[j] for j in range(n) if s[j]!="x")
print(answer)
''',('4\n0\nabcd\nab\n','4\n-1\nxabc\nqabc\n','0\n0\n\n\n','3\n0\nxxx\n\n'),debug=True)

    def test_list_comprehension_has_the_same_guarded_read_semantics(self):
        self.compare('''n=int(input())
offset=int(input())
s=input()
p=input()
answer=[s[j+offset]!=p[j] for j in range(n) if s[j]!="x"]
print(answer)
''',('3\n1\nabcd\nbcd\n','3\n-1\nabcd\ndab\n','4\n0\nabcd\na\n','0\n0\n\n\n'))

    def test_range_and_len_aliases_specialize_normal_functions(self):
        self.compare('''loop=range
size=len
def compare(s,p,offset,n):
 total=0
 for j in loop(n):
  total+=s[j+offset+size(p)-size(p)]!=p[j]
 return total
s=input()
p=input()
offset=int(input())
n=int(input())
print(compare(s,p,offset,n))
''',('abcd\nbcd\n1\n3\n','abcd\ndab\n-1\n3\n','abc\na\n0\n3\n','\n\n0\n0\n'))

    def test_intermediate_wrapping_cancellation_uses_original_checked_loop(self):
        source='''n=int(input())
offset=int(input())
s=input()
p=input()
answer=0
for i in range(1,n):
 answer+=s[(i+offset)-offset]!=p[i]
print(answer)
'''
        for mode,bits in (('i64',64),('i128',128)):
            maximum=(1<<(bits-1))-1
            self.compare(source,(f'4\n{maximum}\nabcdef\nabxd\n',f'4\n{-maximum}\nabcdef\nabxd\n'),wrapping=True,trace=False,modes=(mode,),debug=True)

    def test_ascii_reader_rejects_out_of_domain_utf8_without_corrupting_output(self):
        # ASCII text input is rejected before indexed operations. Rejection must
        # preserve UTF-8 output and a modeled exception; Unicode mode below
        # provides exact codepoint behavior for these characters.
        source='''n=int(input())
s=input()
p=input()
print(s,p)
answer=0
for i in range(n):
 print("read",i)
 answer+=s[i]!=p[i]
print(answer)
'''
        for mode in ('i64','i128'):
            guarded=self.compile(source,mode)
            for data in ('1\né\nx\n','2\nax\néx\n','0\né\n🦀\n'):
                actual=subprocess.run([str(guarded[1])],input=data.encode(),capture_output=True,timeout=5)
                output=actual.stdout.decode('utf-8')
                actual.stderr.decode('utf-8')
                self.assertEqual(actual.returncode,1)
                self.assertEqual(output,"")
                self.assertIn(b"UnicodeDecodeError:",actual.stderr)
                self.assertNotIn(b"panicked",actual.stderr)

    def test_unicode_mode_keeps_codepoint_behavior_and_lazy_errors(self):
        self.compare('''n=int(input())
s=input()
p=input()
answer=0
for i in range(n):
 answer+=s[i]!=p[i]
print(answer)
''',('3\n猫🙂a\n猫🙂b\n','4\n猫🙂a\n猫🙂ab\n','0\n猫\n🙂\n'),guard=False,string_mode='unicode',modes=('i64','i128','bigint'))


if __name__=='__main__':unittest.main()
