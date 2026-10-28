"""One selected-width decimal parser feeds canonical scalar/input/word consumers."""
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile, TranspileOptions
from py2fastrust.aot import rust_mask
from py2fastrust.literal_semantics import integer_policy
from py2fastrust.native_integer_parsing import render_helpers
import test_native_iterator_reductions as execution


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeFixedParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=execution.NativeIteratorReductionTests();cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()

    def compare(self,source,samples,*,debug=False,modes=('i64','i128','bigint'),inspect=None,string_mode='unicode'):
        for mode in modes:
            for release in ((False,True)if debug else(True,)):
                compiled=self.harness.compile(source,mode,release=release,string_mode=string_mode)
                if inspect:inspect(compiled[2],mode)
                for data in samples:
                    with self.subTest(mode=mode,release=release,data=data):self.harness.compare(compiled,data,mode=mode,trace=True)

    def test_scalar_text_conversion_signs_separators_and_whitespace(self):
        source='import sys\ns=sys.stdin.read()\nprint(int(s))\n'
        valid=('0','-0','+0',' +001_002\t','\v\f-1_2_3\r\n','\u0085+١_٢٣\u2003','\u3000９_８٧\u00a0')
        invalid=('',' ','+','-','_1','1_','1__2','+_1','--1','1 2','1\x00','\x1c1','1\x1f','\u200b1','+ 1','１２a','−1','²','0x10')
        self.compare(source,valid+invalid,debug=True)

    def test_every_ascii_control_matches_python_integer_whitespace(self):
        source='import sys\nprint(int(sys.stdin.read()))\n'
        samples=tuple(chr(code)+'12'+chr(code)for code in range(33))
        self.compare(source,samples,modes=('i64','i128'))

    def test_binary_conversion_retains_ascii_only_digits_and_repr_errors(self):
        source='import sys\nprint(int(sys.stdin.buffer.read()))\n'
        samples=(b'',b'  +001_23\r\n',b'\t\v\f-5\r\n',b'1__2',b'\x1c1',b'1\xff',b'\xc2\xa012',b'\xd9\xa1',bytes(range(256)))
        for mode in ('i64','i128','bigint'):
            compiled=self.harness.compile(source,mode)
            for data in samples:
                with self.subTest(mode=mode,data=data):
                    actual=subprocess.run([str(compiled[1])],input=data,capture_output=True,timeout=10)
                    expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,timeout=10)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    if actual.returncode:
                        self.assertEqual(actual.stderr.splitlines()[-1],expected.stderr.splitlines()[-1])

    def test_captured_builtin_alias_and_reader_keep_the_original_identity(self):
        source='''convert=int
original=convert
convert=7
read=input
original_read=read
read=9
print(original(original_read()))
'''
        self.compare(source,(' +١٢_٣ \n','bad\n',''),debug=True)

    def test_functions_classes_and_readonly_string_containers_share_conversion(self):
        source='''def parse(text):
 return int(text)
values=["12","-３","١_٤"]
for value in values:
 print(parse(value))
class Reader:
 def parse(self,text):return int(text)
print(Reader().parse(input()))
'''
        self.compare(source,('٤٢\n','\x1c1\n','invalid\n'),debug=True)

    def test_character_conversion_uses_the_selected_checked_projection(self):
        source='text=input()\nprint(sum(int(c) for c in text))\n'
        def inspect(rust,mode):
            if mode!='bigint':
                main=rust_mask(rust)[rust_mask(rust).rfind('fn main'):]
                self.assertIn('native_parse_integer_codepoint',main)
                self.assertNotIn('char::from_u32',main)
        self.compare(source,('1234567890\n','١٢٣９\n','1x2\n','\n'),debug=True,inspect=inspect)
        source='text=input()\nprint(int(text[int(input())]))\n'
        self.compare(source,('7\n0\n','７\n0\n','\n0\n','1\n3\n','-\n0\n'),debug=True)

    def test_word_producers_preserve_lazy_and_eager_error_order(self):
        programs=('a,b=map(convert,read().split())\nprint(a,b)\n',
                  'a,b=(convert(word)for word in read().split())\nprint(a,b)\n',
                  'a,b=[convert(word)for word in read().split()]\nprint(a,b)\n')
        for program in programs:
            source='convert=int\nread=input\nprint("before")\n'+program
            self.compare(source,('1 2\n','1 2 bad\n','1 2 3 bad\n','1\n','١ ９\n'))

    def test_shared_consumers_cover_text_and_bytes_words(self):
        source='''import sys
convert=int
reader=sys.stdin.buffer.readline
print(sum(map(convert,reader().split())))
print(list(convert(word)for word in reader().split()))
print(sorted(map(convert,reader().split())))
print(next(map(convert,reader().split()),-1))
'''
        self.compare(source,('1 -2 +3\n4 5\n9 2 8\n7 bad\n','\n\n\n\n','1_2\n-0\n3 3\n0\n'),debug=True)

    def test_selected_width_boundaries_random_and_very_long_decimal_literals(self):
        rng=random.Random(621160)
        values=[str(n)for bits in (63,64,127,128,256)for n in (-(1<<bits)-1,-(1<<bits),-(1<<bits)+1,(1<<bits)-1,1<<bits,(1<<bits)+1)]
        values += [''.join(str(rng.randrange(10))for _ in range(rng.randrange(1,220)))for _ in range(32)]
        values += ['9'*10000,'-'+'9876543210'*1000,'+'+'1_'*4999+'1']
        previous=sys.get_int_max_str_digits();sys.set_int_max_str_digits(0)
        try:
            expected=[int(value)for value in values]
            source='n=int(input())\nfor i in range(n):\n print(int(input()))\n'
            data=str(len(values))+'\n'+'\n'.join(values)+'\n'
            for mode,bits in (('i64',64),('i128',128),('bigint',0)):
                output=''.join(str(integer_policy(bits).normalize(value))+'\n'for value in expected)
                for release in (False,True):
                    compiled=self.harness.compile(source,mode,release=release)
                    result=subprocess.run([str(compiled[1])],input=data,text=True,capture_output=True,timeout=30)
                    self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,output)
        finally:sys.set_int_max_str_digits(previous)

    def test_text_receiver_and_conversion_error_frames_execute_once(self):
        source='''def source():
 print("source")
 return input()
def parse(text):
 print("parse")
 return int(text)
print("before")
print(parse(source()))
print(input())
'''
        self.compare(source,('١٢\nlast\n','bad\nlast\n',''),debug=True)

    def test_parse_only_fixed_programs_do_not_retain_generic_integer_storage(self):
        sources=('print(int(input()))\n','s=input()\nconvert=int\nprint(convert(s))\n',
                 'print(sum(map(int,input().split())))\n',
                 'import sys\nprint(sum(map(int,sys.stdin.buffer.read().split())))\n')
        for mode in ('i64','i128'):
            for string_mode in ('ascii','unicode'):
                for optimize in (False,True):
                    for source in sources:
                        result=transpile(source,TranspileOptions(integer=mode,optimize=optimize,string_mode=string_mode))
                        self.assertTrue(result.success,result.diagnostics)
                        masked=rust_mask(result.rust_source)
                        self.assertNotIn('struct Int(',masked);self.assertNotIn('Int::parse(',masked)
                        self.assertNotIn('enum IntRepr',masked)
                        if string_mode=='ascii'or('.buffer.'in source and optimize):
                            self.assertNotIn('NATIVE_FIXED_INT_ZEROES',masked)
                            self.assertNotIn('NATIVE_FIXED_INT_SPACE',masked)
                            self.assertNotIn('// UNICODE LICENSE V3',result.rust_source)
                        else:self.assertIn('// UNICODE LICENSE V3',result.rust_source)

    def test_default_ascii_scalar_alias_words_and_characters_share_parser(self):
        programs=(
            ('print(int(input()))\n',('  +1_234\n','bad\n','\v-4\f\n','\x1c1\n')),
            ('convert=int\noriginal=convert\nconvert=7\nprint(original(input()))\n',(' -1_234\n','bad\n')),
            ('print(sum(map(int,input().split())))\n',('1 -2 +3 4_5\n','1 bad 3\n','\n')),
            ('s=input()\nprint(sum(int(c)for c in s))\n',('1234567890\n','1x2\n','\n')),
        )
        for source,samples in programs:self.compare(source,samples,debug=True,string_mode='ascii')

    def test_pure_conversions_and_byte_helpers_do_not_construct_standard_input(self):
        sources=('''convert=int
saved=convert
convert=7
print(saved("12"),saved(b"-3"))
print(sum(saved(c)for c in "123"))
print(sum(map(saved,"1 2".split())))
print(sum(map(saved,b"3 4".split())))
''','''print(b" abc ".strip(),b"abc".decode())
''')
        for source in sources:
            for mode in ('i64','i128','bigint'):
                for string_mode in ('ascii','unicode'):
                    for optimize in (False,True):
                        compiled=self.harness.compile(source,mode,release=optimize,prune=optimize,string_mode=string_mode)
                        masked=rust_mask(compiled[2])
                        self.assertNotIn('struct StandardInput',masked)
                        self.assertNotIn('struct NativeInput',masked)
                        self.assertNotIn('let mut native_input',masked)
                        if mode!='bigint':self.assertNotIn('struct Int(',masked)
                        self.harness.compare(compiled,mode=mode,trace=True)

    def test_checked_structural_counts_and_modular_pow_keep_their_integer_requirements(self):
        source='import sys\nn=int(input())\nprint(sys.stdin.read(n))\n'
        self.compare(source,('2\nabcdef','-1\nabcdef','9223372036854775807\nx'),debug=True)
        source='print(pow(int(input()),5,7))\n'
        self.compare(source,('2\n','-3\n','invalid\n'),debug=True)


if __name__=='__main__':unittest.main()
