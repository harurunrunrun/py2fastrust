"""UTF-8 encoding uses actual text bytes and preserves builtin binding order."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile

CASES={'default_unicode_empty_nul': "for value in ('','ascii','a\\x00b','é日😀'):\n print(value.encode())\n", 'utf8_positional_keyword': "value='é日😀'\nprint(value.encode('utf-8'))\nprint(value.encode(encoding='UTF_8',errors='strict'))\nprint(value.encode('utf8',errors='strict'))\n", 'receiver_and_argument_effects': "def source():print('receiver');return 'text'\ndef error():print('errors');return 'strict'\nprint(source().encode('utf8',error()))\n", 'positional_keyword_duplicate': "def argument(label):print(label);return 'utf8'\n'x'.encode(argument('first'),encoding=argument('second'))\n", 'unknown_keyword': "def argument():print('argument');return 'x'\n'x'.encode(extra=argument())\n", 'excess_arguments': "def argument(value):print(value);return value\n'x'.encode(argument('utf8'),argument('strict'),argument('extra'))\n", 'encoding_none': "'x'.encode(None)\n", 'errors_none': "'x'.encode('utf8',None)\n", 'encoding_integer': "'x'.encode(7)\n", 'embedded_nul_codec': "'x'.encode('utf8\\x00')\n", 'embedded_nul_errors': "'x'.encode('utf8','strict\\x00')\n", 'non_utf8_boundary': "print('é'.encode('latin-1'))\n", 'non_strict_boundary': "print('é'.encode('utf8','ignore'))\n", 'unknown_errors_are_lazy': "print('é'.encode('utf8','unknown-error-handler'))\n", 'dynamic_codec_boundary': "encoding=input()\nprint('é'.encode(encoding))\n", 'stored_method_boundary': "value='é'\nencode=value.encode\nprint(encode())\n", 'unbound_descriptor_boundary': "print(str.encode('é'))\n", 'surrogate_boundary': "print('\\ud800'.encode())\n", 'ordinary_user_method_preserved': "class Data:\n def encode(self):return b'user'\nprint(Data().encode())\n", 'codec_object_does_not_call_str': "class Codec:\n def __str__(self):print('unexpected str');return 'utf8'\n'x'.encode(Codec())\n", 'argument_validation_precedes_codec_lookup': "def argument():print('errors argument');return None\n'x'.encode('unimplemented-codec',argument())\n", 'all_argument_effects_precede_encoding_typecheck': "def argument():print('errors argument');return 'strict'\n'x'.encode(None,argument())\n"}

BOUNDARIES={'non_utf8_boundary':'codec','dynamic_codec_boundary':'dynamic encoding',
 'stored_method_boundary':'stored str.encode','unbound_descriptor_boundary':'str.encode',
 'surrogate_boundary':'encode'}


def normalize(value):
    return '\n'.join(line for line in value.splitlines()if not line.startswith('    '))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class Utf8EncodingExecutionTests(unittest.TestCase):
    def check(self,name):
        source=CASES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-encode-')as directory:
            script=Path(directory)/'encoding.py';script.write_text(source)
            expected=subprocess.run([sys.executable,'-I','-S',str(script)],capture_output=True,text=True,timeout=10)
            for mode in ('ascii','unicode')if name=='default_unicode_empty_nul'else('ascii',):
                for integer in ('i64','i128','bigint'):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                        result=transpile(source,TranspileOptions(integer=integer,string_mode=mode,filename=str(script),license='none'))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','struct PegParser','UNICODE LICENSE V3'):
                        self.assertNotIn(marker,result.rust_source)
                    rust=Path(directory)/(integer+'_'+mode+'.rs');rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        binary=rust.with_suffix('.opt'if optimized else'.debug')
                        built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                        self.assertEqual(built.returncode,0,built.stderr)
                        actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                        with self.subTest(integer=integer,mode=mode,optimized=optimized):
                            self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                            self.assertEqual(normalize(actual.stderr),normalize(expected.stderr))


class Utf8EncodingBoundaryTests(unittest.TestCase):
    def test_unimplemented_codec_and_callable_protocols_are_positioned(self):
        for name,reason in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                result=transpile(CASES[name],TranspileOptions(integer=integer,filename='encoding_boundary.py'))
                self.assertFalse(result.success)
                self.assertTrue(any(row.code=='E006'and row.line>0 and reason in row.message for row in result.diagnostics),result.diagnostics)


def _case(name):
    def test(self):self.check(name)
    return test


for _name in CASES:
    if _name not in BOUNDARIES:setattr(Utf8EncodingExecutionTests,'test_'+_name,_case(_name))

if __name__=='__main__':unittest.main()
