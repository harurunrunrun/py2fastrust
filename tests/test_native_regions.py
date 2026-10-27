"""General readonly owner and one-codepoint operand behavior."""
import unittest
import shutil
import re
import test_native_iterator_reductions as helpers

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeRegionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeIteratorReductionTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeIteratorReductionTests.tearDownClass.__func__)
    compile=helpers.NativeIteratorReductionTests.compile
    compare=helpers.NativeIteratorReductionTests.compare
    differential=helpers.NativeIteratorReductionTests.differential

    def test_readonly_modulo_owner_is_captured_once_per_loop(self):
        source='s=input()\nanswer=0\nfor i in range(100):\n answer+=s[i%len(s)]=="a"\nprint(answer)\n'
        for mode in ('i64','i128','bigint'):
            compiled=self.compile(source,mode)
            main=compiled[2][compiled[2].rfind('fn main()'):]
            self.assertRegex(main,r'let native_temp_\d+:&str=native_var_\d+\.as_str\(\);')
            self.assertIn(':u32=',main)
            self.compare(compiled,'abc\n')

    def test_character_operands_evaluate_once_and_keep_chain_short_circuit(self):
        self.differential('''
            def index(value):
                print(value,end="|")
                return value
            s=input()
            print(s[index(0)]<s[index(1)]<s[index(2)])
        ''',('abc\n','cba\n'),modes=('i64','i128','bigint'),trace=True)

    def test_unicode_single_char_order_and_owning_escape(self):
        self.differential('''# pytors: --string-mode unicode
s=input()
print(s[0]<s[1],s[0]=="α",s[-1]>"a")
letters=[]
for i in range(len(s)):
 letters.append(s[i])
print(letters,s[1]+s[0])
''',('α🦀a\n','aα🦀\n'),modes=('i64','i128','bigint'),trace=True)

    def test_owner_rebinding_prevents_stale_view(self):
        self.differential('''
            s="abc"
            for i in range(3):
                print(s[0])
                s=s[1:]
        ''',modes=('i64','i128','bigint'))

    def test_zero_loop_does_not_read_possibly_unbound_owner(self):
        self.differential('''
            if int(input()):
                s="abc"
            for i in range(0):
                print(s[i])
            print("end")
        ''',('0\n','1\n'),modes=('i64','i128','bigint'),trace=True)

    def test_generator_capture_runs_after_later_consumer_argument(self):
        self.differential('''
            def mark(value):
                print(value,end="|")
                return value
            s=input()
            print(sum((s[i]=="a" for i in range(mark(3))),mark(7)))
        ''',('abc\n','ab\n'),modes=('i64','i128','bigint'),trace=True)

    def test_character_error_keeps_prior_output_and_original_scope(self):
        self.differential('''
            s=input()
            for i in range(4):
                print(i,end="|")
                print(s[i]=="a")
        ''',('ab\n','\n'),modes=('i64','i128','bigint'),trace=True)

    def test_string_list_elements_are_not_assumed_single_char(self):
        self.differential('''
            values=["abc","ab","z"]
            print(values[0]>values[1],values[1]=="a",values[2]=="z")
        ''',modes=('i64','i128','bigint'))

    def test_guarded_break_continue_else_and_placeholder_hygiene(self):
        source='''s=input()
p=input()
answer=0
for i in range(len(s)):
 if i==1:
  continue
 answer+=s[i]!=p[i]
 if i==3:
  break
else:
 print("all")
print(answer,"native_region_char_100\\0")
'''
        for mode in ('i64','i128'):
            compiled=self.compile(source,mode)
            from py2fastrust.aot import rust_mask
            self.assertRegex(rust_mask(compiled[2]),r'let\s+native_region_guard_\d+\s*=')
            for data in ('abbdx\naccdx\n','abc\nab\n','\n\n'):
                self.compare(compiled,data,trace=True)

    def test_return_value_inside_loop_keeps_original_typed_path(self):
        source='''def first(s,p,n):
 for i in range(n):
  return s[i]==p[i]
 return False
print(first(input(),input(),int(input())))
'''
        for mode in ('i64','i128','bigint'):
            compiled=self.compile(source,mode)
            from py2fastrust.aot import rust_mask
            self.assertNotRegex(rust_mask(compiled[2]),r'let\s+native_region_guard_\d+\s*=')
            self.assertNotIn('\0',compiled[2])
            for data in ('ax\nab\n2\n','\n\n0\n','a\n\n1\n'):
                self.compare(compiled,data,trace=True)

    def test_nested_loop_versioning_has_a_single_growth_budget(self):
        source='''n=int(input())
s=input()
p=input()
answer=0
for i in range(n):
 answer+=s[i]!=p[i]
 for j in range(n):
  answer+=s[j]!=p[j]
print(answer)
'''
        for mode in ('i64','i128'):
            compiled=self.compile(source,mode)
            from py2fastrust.aot import rust_mask
            guards=re.findall(r'let\s+native_region_guard_\d+\s*=',rust_mask(compiled[2]))
            self.assertEqual(len(guards),1)
            for data in ('3\nabc\naxc\n','0\n\n\n','3\nabc\na\n'):
                self.compare(compiled,data,trace=True)
