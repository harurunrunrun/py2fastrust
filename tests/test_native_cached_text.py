"""Immutable text storage stays shared through typed value and call flows."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_types import rust_type


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeCachedTextTests(unittest.TestCase):
    def compare(self,source,inputs=('',),policies=('unicode',),modes=('i64','i128','bigint')):
        sources=[]
        for policy in policies:
            for integer in modes:
                with self.subTest(policy=policy,integer=integer):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('general backend')):
                        result=transpile(source,TranspileOptions(filename='cached_text.py',integer=integer,string_mode=policy))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    self.assertNotIn('enum Value',result.rust_source)
                    self.assertNotIn('struct Runtime',result.rust_source)
                    sources.append(result.rust_source)
                    with tempfile.TemporaryDirectory(prefix='pytors-cached-text-')as directory:
                        path=Path(directory,'main.rs');path.write_text(result.rust_source);binary=path.with_suffix('')
                        built=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                        self.assertEqual(built.returncode,0,built.stderr)
                        for data in inputs:
                            expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=5)
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5)
                            self.assertEqual(actual.returncode,expected.returncode,(actual.stderr,expected.stderr))
                            self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
                            if actual.returncode:self.assertEqual(actual.stderr.splitlines()[-1].split(':')[0],expected.stderr.splitlines()[-1].split(':')[0])
        return sources

    def test_canonical_strings_cross_functions_lists_tuples_and_aliases(self):
        self.assertEqual(rust_type('str'),'NativeText')
        sources=self.compare('''def read(text,index):
 return text,text[index],len(text)
s=input()
alias=s
xs=[s,"second"]
print(read(s,int(input())),xs,alias)
s="changed"
print(xs[0],alias,len(xs[0]),xs[0][-1])
''',('あ🙂bé\n1\n','abcd\n-1\n','single\n99\n'))
        self.assertTrue(all('native_argument_0: NativeText'in source for source in sources))
        self.assertTrue(all('Vec<NativeText>'in source for source in sources))

    def test_class_field_snapshot_survives_callback_rebinding(self):
        self.compare('''class Box:
 def __init__(self,text):
  self.text=text
  self.saved=[text]
 def index(self):
  self.text="replaced"
  return 1
 def expose(self):
  return self.text,self.saved
box=Box(input())
saved=box.text
print(box.text[box.index()],box.text,saved,box.expose())
''',('あ🙂é\n','abc\n'))

    def test_unicode_string_keys_and_values_retain_typed_storage(self):
        self.compare('''s=input()
key=(s,1)
d={key:s+"!",("other",2):"last"}
values={s,"other"}
print(d[key],s in values,"other" in values,d.get((s,1)))
''',('あ🙂é\n','abc\n'))

    def test_existing_sorted_set_proof_boundary_remains_explicit(self):
        source='s=input()\nvalues={s,"other"}\nprint(sorted(values))\n'
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,string_mode='unicode'))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')

    def test_literal_sites_reuse_static_metadata_across_calls(self):
        literal='あ🙂éx'*250
        source='def label():\n return '+repr(literal)+'\ntotal=0\nfor i in range(80):\n text=label()\n total+=len(text)\n if text[-1]=="x":total+=1\nprint(total)\n'
        sources=self.compare(source)
        self.assertTrue(all('static NATIVE_LITERAL:NativeTextLiteral'in source for source in sources))

    def test_nullable_and_finite_loop_carriers_keep_original_values(self):
        self.compare('''n=int(input())
s=input()
x=None
for i in range(n):
 old=x
 x=s if i%2 else None
 print(old,x)
print(s,x)
y=s
for i in range(n):
 if i%2:y="other"
 else:y=3
 print(y)
print(s)
''',('0\nあ🙂é\n','5\nあ🙂é\n','4\nplain\n'))

    def test_long_nullable_loop_carrier_does_not_copy_string_payloads(self):
        source='''n=int(input())
s=input()
x=None
total=0
for i in range(n):
 x=s if i%2 else None
 if x is None:total+=1
print(total,len(s))
'''
        sources=self.compare(source,('100\n'+'あ🙂éx'*4000+'\n',))
        for rust in sources:
            main=rust[rust.index('fn main('):]
            self.assertIn('Option<NativeText>',main)
            self.assertNotIn('.to_owned()',main)
            self.assertNotIn('String::from',main)

    def test_borrowed_temporaries_and_short_circuit_preserve_input_order(self):
        self.compare('''def mark(n):
 print("mark",n)
 return input()
s=input()
print(s,mark(1)[1],s)
print(mark(2)<mark(3)<mark(4))
print(input())
''',('あ🙂é\nxyz\nz\na\nnot consumed\n','abc\n海猫\na\nb\nc\ntail\n'))

    def test_ascii_and_unicode_share_values_with_direct_ascii_access(self):
        sources=self.compare('''s=input()
xs=[s]
print(s[0],s[-1],len(s),xs[0][1],s[1:-1],s.count(""))
''',('abcdef\n','x\n'),policies=('ascii','unicode'))
        self.assertTrue(any('struct NativeText'in source and 'NATIVE_TEXT_UNICODE'not in source for source in sources))
        self.assertTrue(any('const NATIVE_TEXT_UNICODE:bool=true'in source for source in sources))

    def test_cached_index_helpers_never_rescan_the_owner(self):
        source='s=input()\nn=int(input())\ntotal=0\nfor i in range(n):\n if s[i%len(s)]=="x":total+=1\nprint(total)\n'
        result=transpile(source,TranspileOptions(string_mode='unicode'))
        self.assertTrue(result.success,result.diagnostics)
        main=result.rust_source[result.rust_source.index('fn main() {'):]
        self.assertIn('codepoint_len()',main)
        self.assertIn('native_text_codepoint(',main)
        self.assertNotIn('native_string_item(',main)
        self.assertNotIn('.chars().count()',main)
        self.assertNotIn('.chars().nth(',main)
        self.assertNotIn('.is_ascii()',main)


if __name__=='__main__':unittest.main()
