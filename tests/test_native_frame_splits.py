"""Split signatures, native word cursors and receiver/argument evaluation order."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.settings import apply_source_options,source_directives


class SplitCapabilityTests(unittest.TestCase):
    def test_custom_index_protocol_has_a_positioned_diagnostic(self):
        source="class Limit:\n def __index__(self):return 1\nclass Box:\n def run(self):return 'a,b,c'.split(',',Limit())\nprint(Box().run())\n"
        result=transpile(source)
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertGreater(result.diagnostics[0].line,0)
        self.assertIn('__index__',result.diagnostics[0].message)
        self.assertIn('protocol',result.diagnostics[0].message)

    def test_simple_forward_words_keep_the_existing_static_path(self):
        from py2fastrust.native_frame_selection import select_frames
        unit=build_program("values=list(map(int,input().split()))\nprint(sum(values))\n",'main.py').main
        self.assertFalse(select_frames(unit).required)

    def test_original_ast_and_scope_nodes_are_retained(self):
        from py2fastrust.native_classes import try_generate_classes
        source="class Box:\n def run(self,text):return text.rsplit(sep=',',maxsplit=1)\nprint(Box().run('a,b,c'))\n"
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True)
        nodes=tuple(ast.walk(unit.tree))
        result=try_generate_classes(source,'main.py','i64',unit=unit)
        self.assertIsNotNone(result)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SplitExecutionTests(unittest.TestCase):
    def exercise(self,source,*,expected_by_integer=None,data=""):
        with tempfile.TemporaryDirectory(prefix='pytors-frame-split-')as directory:
            root=Path(directory);main=root/'main.py';main.write_text(source)
            reference=subprocess.run([sys.executable,'-S',str(main)],input=data,text=True,capture_output=True,timeout=15)
            def frames(stderr):return re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',stderr)
            for mode in ('i64','i128','bigint'):
                expected=(expected_by_integer or {}).get(mode,(reference.stdout,reference.stderr,reference.returncode))
                options=TranspileOptions(filename=str(main),integer=mode)
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy generation entered')):
                    result=transpile(source,options)
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                effective=apply_source_options(options,source_directives(source,str(main)))
                if effective.string_mode=='ascii':self.assertNotIn('UNICODE LICENSE V3',result.rust_source)
                if 'UNICODE LICENSE V3'in result.rust_source:
                    self.assertTrue('const TEXT_PRINTABLE'in result.rust_source or 'const NATIVE_TUPLE_PRINTABLE'in result.rust_source)
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    with self.subTest(integer=mode,optimized=optimized):
                        binary=root/(mode+('_release'if optimized else'_debug'))
                        build=subprocess.run(['rustc','--edition=2021','--crate-name','frame_split_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
                        self.assertEqual(build.returncode,0,build.stderr)
                        actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                        self.assertEqual(actual.stdout,expected[0])
                        self.assertEqual(actual.returncode,expected[2],actual.stderr)
                        self.assertEqual(frames(actual.stderr),frames(expected[1]))
                        self.assertEqual(actual.stderr.rstrip().splitlines()[-1:]if actual.stderr else[],expected[1].rstrip().splitlines()[-1:]if expected[1]else[])

    def test_text_separator_boundaries(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for value in ['',',',',a,,b,','aaaaa','a<>b<><>c<>']:\n   print(value.split(','),value.rsplit(','),value.split('aa',1),value.rsplit('aa',1),value.split('<>',2),value.rsplit('<>',2))\nBox('a,b,c').run()\n")

    def test_text_whitespace_limits(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for value in ['', '   ', '  a b  ', '\\talpha\\nbeta\\r gamma\\v', '\\x1ca\\x1db\\x1ec\\x1fd ']:\n   for limit in [-8,-1,0,1,2,9,False,True]:\n    print(value.split(None,limit),value.rsplit(None,limit))\nBox('a,b,c').run()\n")

    def test_bytes_separator_boundaries(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for value in [b'',b'::',b'::a::::b::',b'aaaaa',b'\\x00a\\xffb\\x00']:\n   print(value.split(b'::'),value.rsplit(b'::'),value.split(b'aa',1),value.rsplit(b'aa',1),value.split(b'\\x00',2),value.rsplit(b'\\xff',0))\nBox(b'a,b,c').run()\n")

    def test_bytes_whitespace_limits(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for value in [b'',b'   ',b'  a b  ',b'\\ta\\nb\\rc\\v\\fd',b'\\x1ca\\x1db\\x1ec\\x1fd']:\n   for limit in [-8,-1,0,1,2,9,False,True]:\n    print(value.split(None,limit),value.rsplit(None,limit))\nBox(b'a b').run()\n")

    def test_optional_separator_arguments(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self,separator,limit):\n  print(self.text.split(separator,limit),self.text.rsplit(sep=separator,maxsplit=limit))\nb=Box(' a,b,c ')\nfor sep in [None,',']:\n for limit in [-1,0,1,2]:b.run(sep,limit)\n")

    def test_mixed_text_bytes_receiver(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):return self.text.split(maxsplit=1),self.text.rsplit(None,1)\nfor text in [' a b c ',b' a b c ']:\n print(Box(text).run())\n")

    def test_keyword_evaluation_order(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def split(self):return self.text.split(maxsplit=limit(),sep=separator())\ndef owner():\n print('owner')\n return Box('a,b,c')\ndef limit():\n print('limit')\n return 1\ndef separator():\n print('separator')\n return ','\nprint(owner().split())\n")

    def test_receiver_captured_before_separator_rebinding(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(self.separator()),self.text)\n def separator(self):\n  self.text='rebound'\n  return ','\nBox('a,b,c').run()\n")

    def test_list_payload_aliases(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  parts=self.text.split(',')\n  alias=parts\n  parts.append('d')\n  print(parts,alias,parts is alias,self.text)\nBox('a,b,c').run()\n")

    def test_unicode_whitespace(self):
        self.exercise("# pytors: --string-mode unicode\nclass Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for value in ['\\u0085a\\u00a0b\\u2028c\\u3000','\\u0085\\u3000','\\u3000猫\\u00a0犬\\u2029']:\n   for limit in [-1,0,1,2]:\n    a=value.split(None,limit)\n    b=value.rsplit(None,limit)\n    print('|'.join(a),len(a),'|'.join(b),len(b))\nBox('a,b,c').run()\n")

    def test_unicode_separator(self):
        self.exercise("# pytors: --string-mode unicode\nclass Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for limit in [-1,0,1,2,9]:\n   a=self.text.split('猫',limit)\n   b=self.text.rsplit('猫',limit)\n   print('|'.join(a),len(a),'|'.join(b),len(b))\nBox('猫犬猫鳥猫猫').run()\n")

    def test_large_in_range_limits(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(',',1<<62),self.text.rsplit(',',-(1<<62)))\nBox('a,b,c').run()\n")

    def test_text_empty_separator(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split('',0))\nBox('a,b,c').run()\n")

    def test_bytes_empty_separator(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'a'.rsplit(b''))\nBox('a,b,c').run()\n")

    def test_text_wrong_separator(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(7))\nBox('a,b,c').run()\n")

    def test_text_bytes_separator(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.rsplit(b','))\nBox('a,b,c').run()\n")

    def test_bytes_text_separator(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'a,b'.split(','))\nBox('a,b,c').run()\n")

    def test_float_limit(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(',',1.5))\nBox('a,b,c').run()\n")

    def test_none_limit(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.rsplit(None,None))\nBox('a,b,c').run()\n")

    def test_both_arguments_wrong(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(7,1.5))\nBox('a,b,c').run()\n")

    def test_duplicate_separator(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(',',sep=';'))\nBox('a,b,c').run()\n")

    def test_too_many_arguments(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.rsplit(',',1,2))\nBox('a,b,c').run()\n")

    def test_unknown_keyword(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.split(wrong=1))\nBox('a,b,c').run()\n")

    def test_custom_str_override_keeps_the_original_protocol_boundary(self):
        result=transpile("class Separator:\n def __str__(self):return ','\nclass Box:\n def run(self):return 'a,b'.split(Separator())\nprint(Box().run())\n")
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('__str__',result.diagnostics[0].message)
        self.assertIn('protocol',result.diagnostics[0].message)

    def test_signed_limit_endpoints(self):
        self.exercise("class Box:\n def run(self):\n  for limit in [-(1<<63),(1<<63)-1]:\n   print('a,b,c'.split(',',limit),b'a b c'.rsplit(None,limit))\nBox().run()\n")

    def test_positive_ssize_overflow(self):
        self.exercise("class Box:\n def run(self):return 'a,b,c'.split(',',1<<63)\nprint(Box().run())\n",expected_by_integer={'i64': ("['a', 'b', 'c']\n", '', 0)})

    def test_negative_ssize_overflow(self):
        self.exercise("class Box:\n def run(self):return 'a,b,c'.rsplit(',',-((1<<63)+1))\nprint(Box().run())\n",expected_by_integer={'i64': ("['a', 'b', 'c']\n", '', 0)})

    def test_ordinary_rsplit_function(self):
        self.exercise("def tokens(text,separator=None):return text.rsplit(separator,1)\nprint(tokens(' a b c '))\nprint(tokens('a,b,c',','))\n")

    def test_ordinary_split_keywords(self):
        self.exercise("s='a,b,c'\nprint(s.split(maxsplit=1,sep=','))\n")

    def test_ordinary_bytes_rsplit(self):
        self.exercise("s=b' a b c '\nprint(s.rsplit(None,0),s.rsplit(maxsplit=1))\n")

    def test_ordinary_split_optional_separator(self):
        self.exercise("def words(text,separator):return text.split(separator,1)\nprint(words(' a b c ',None))\nprint(words('a,b,c',','))\n")

    def test_ordinary_split_none_limit(self):
        self.exercise("print('a,b,c'.split(',',None))\n")

    def test_ordinary_split_invalid_separator(self):
        self.exercise("print('a,b,c'.split(7))\n")

    def test_ordinary_split_duplicate_argument(self):
        self.exercise("print('a,b,c'.split(',',sep=';'))\n")

    def test_plain_object_text_separator(self):
        self.exercise("class Separator:pass\nclass Box:\n def run(self):return 'a,b'.split(Separator())\nprint(Box().run())\n")
