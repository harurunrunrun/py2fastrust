"""The ASCII profile emits byte operations without dormant Unicode support."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.rust_pruning import _lex


class NativeAsciiOutputTests(unittest.TestCase):
    def test_default_output_excludes_unicode_data_and_text_cache(self):
        programs=(
            'print(1)\n',
            'a,b,c=map(int,input().split())\nprint(max(0,(c-a+b-1)//b))\n',
            'n=int(input())\na=list(map(int,input().split()))\nprint(sum(x%2==1 for x in a))\n',
            's=input().strip()\nprint(s[0],s[-1],len(s),s[1:-1],s.count("x"))\n',
            's=input()\nprint(s.isupper(),s.isdigit(),s.istitle(),s.isidentifier())\n',
            's=input()\nprint((s,1),[s,"other"])\n',
            'class Text:\n def __init__(self,s):self.s=s\n def show(self):return self.s[0],len(self.s)\nt=Text(input())\nprint(t.show())\n',
        )
        for integer in ('i64','i128','bigint'):
            for source in programs+(('print(float(input()))\n',)if integer!='bigint'else()):
                with self.subTest(integer=integer,source=source):
                    result=transpile(source,TranspileOptions(integer=integer))
                    self.assertTrue(result.success,result.diagnostics)
                    tokens,_comments,_pairs=_lex(result.rust_source)
                    identifiers={token.text for token in tokens if token.kind=='identifier'}
                    self.assertFalse(identifiers.intersection({
                        'ZEROES','RANGES','TEXT_PRINTABLE','NATIVE_TUPLE_PRINTABLE',
                        'OnceCell','OnceLock','codepoint_len','byte_offset','char_indices',
                        'NATIVE_TEXT_UNICODE','is_whitespace',
                    }),identifiers.intersection({'ZEROES','RANGES','TEXT_PRINTABLE','NATIVE_TUPLE_PRINTABLE','OnceCell','OnceLock','codepoint_len','byte_offset','char_indices','NATIVE_TEXT_UNICODE','is_whitespace'}))
                    self.assertNotIn('UNICODE LICENSE V3',result.rust_source)

    def test_policy_never_rewrites_python_provenance_or_rust_literals(self):
        from py2fastrust.native_text_policy import apply_text_policy
        source='''// is_whitespace text.trim() const TEXT_PRINTABLE
const TEXT:&str="is_whitespace text.trim()";
fn native_scalar_digit(c:char)->Option<u32>{Some(c as u32)}
fn main(){println!("{}",TEXT);}
'''
        result=apply_text_policy(source)
        self.assertIn('// is_whitespace text.trim() const TEXT_PRINTABLE',result)
        self.assertIn('"is_whitespace text.trim()"',result)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_every_ascii_character_uses_python_whitespace_and_number_rules(self):
        from py2fastrust.native import _INPUT_HELPERS
        from py2fastrust.native_scalar import SCALAR_HELPERS
        from py2fastrust.native_text_methods import HELPERS as TEXT_HELPERS
        from py2fastrust.native_words import HELPERS as WORD_HELPERS
        from py2fastrust.native_tuples import HELPERS as TUPLE_HELPERS
        from py2fastrust.native_text_policy import apply_text_policy
        from py2fastrust.rust_pruning import prune_rust_source
        expected=[]
        for code in range(128):
            character=chr(code)
            for operation in ('space','strip','split','int','float','repr'):
                if operation=='space':value=str(character.isspace()).lower()
                elif operation=='strip':value=str((character+'x'+character).strip()=='x').lower()
                elif operation=='split':value=str(len(('1'+character+'2').split()))
                elif operation=='repr':value=repr(character)
                else:
                    try:
                        value=str((int if operation=='int'else float)(character+'12'+character)==12).lower()
                    except ValueError:value='false'
                expected.append(value)
        main=r'''
fn main(){for code in 0u8..128{
    let character=code as char;
    println!("{}",native_space(character));
    let text=format!("{character}x{character}");
    println!("{}",native_text_strip(&text,None,true,true)=="x");
    let text=format!("1{character}2");
    println!("{}",NativeWords::new(&text,None,-1).unwrap().count());
    let text=format!("{character}12{character}");
    println!("{}",native_parse_integer(&text)==Ok(12));
    println!("{}",native_scalar_float(&text)==Ok(12.0));
    println!("{}",native_tuple_repr_str(&character.to_string()));
}}
'''
        with tempfile.TemporaryDirectory(prefix='pytors-ascii-properties-')as directory:
            for integer in ('i64','i128'):
                program=f'type NativeInt={integer};\n'+_INPUT_HELPERS+SCALAR_HELPERS+TEXT_HELPERS+WORD_HELPERS+TUPLE_HELPERS+main
                program=prune_rust_source(apply_text_policy(program))
                path=Path(directory,'main.rs');path.write_text(program);binary=path.with_suffix('')
                build=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(build.returncode,0,build.stderr)
                actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout.splitlines(),expected)
            # Exact BigInt parsing uses the same selected character rules;
            # it does not call the fixed-width wrapping parser above.
            from importlib.resources import files
            kernel=files('py2fastrust').joinpath('runtime','integer.rs').read_text()
            probe=r'''fn main(){for code in 0u8..128{
    let c=code as char;let text=format!("{c}12{c}");
    println!("{}",Int::parse(&text,10)==Ok(Int::from_i128(12)));
}}'''
            program=prune_rust_source(apply_text_policy('const INT_BITS:u32=0;\n'+kernel+probe))
            path=Path(directory,'bigint.rs');path.write_text(program);binary=path.with_suffix('')
            build=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(build.returncode,0,build.stderr)
            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
            self.assertEqual(actual.returncode,0,actual.stderr)
            self.assertEqual(actual.stdout.splitlines(),expected[3::6])

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_ascii_numeric_parsing_and_shared_text_match_python(self):
        source='''a,b=map(int,input().split())
s=input().strip()
alias=s
values=[s]
s="changed"
print(a,b,a+b,len(alias),alias[0],alias[-1],alias[1:-1],values)
print(alias.isupper(),alias.isdigit(),alias.istitle(),alias.isidentifier())
'''
        inputs=(' +1_234 -9\n Abc_012 \n','0 0\n xyz \n','1 2\n A \n')
        with tempfile.TemporaryDirectory(prefix='pytors-ascii-output-')as directory:
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer))
                self.assertTrue(result.success,result.diagnostics)
                path=Path(directory,'main.rs');path.write_text(result.rust_source)
                binary=path.with_suffix('')
                build=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(build.returncode,0,build.stderr)
                for data in inputs:
                    expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=5)
                    actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5,env={'PATH':'/unavailable'})
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_unicode_mode_keeps_digit_properties_and_cached_indices(self):
        source='s=input()\nprint(int(input()),s[0],s[-1],len(s),s.isalpha())\n'
        data='猫é海\n٤٢\n'
        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=5)
        with tempfile.TemporaryDirectory(prefix='pytors-unicode-output-')as directory:
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,string_mode='unicode'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertIn('UNICODE LICENSE V3',result.rust_source)
                self.assertIn('codepoint_len',result.rust_source)
                path=Path(directory,'main.rs');path.write_text(result.rust_source);binary=path.with_suffix('')
                build=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(build.returncode,0,build.stderr)
                actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5,env={'PATH':'/unavailable'})
                self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_ascii_text_reader_rejects_non_ascii_without_a_rust_panic(self):
        with tempfile.TemporaryDirectory(prefix='pytors-ascii-input-')as directory:
            for integer in ('i64','i128','bigint'):
                result=transpile('print(input())\n',TranspileOptions(integer=integer))
                self.assertTrue(result.success,result.diagnostics)
                path=Path(directory,'main.rs');path.write_text(result.rust_source);binary=path.with_suffix('')
                build=subprocess.run(['rustc','--edition=2021','-O',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(build.returncode,0,build.stderr)
                for data in ('猫\n','é\n',*('a'*length+'é\n'for length in (63,64,8191,8192))):
                    actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5)
                    self.assertEqual(actual.returncode,1,actual.stderr)
                    self.assertEqual(actual.stdout,'')
                    self.assertIn('UnicodeDecodeError:',actual.stderr)
                    self.assertNotIn('panicked',actual.stderr)
                data='a'*20000+'\n'
                actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5)
                self.assertEqual((actual.returncode,actual.stdout),(0,data),actual.stderr)


if __name__=='__main__':unittest.main()
