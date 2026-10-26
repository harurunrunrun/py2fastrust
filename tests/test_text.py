"""Unicode 16 string behavior and byte-string behavior against CPython 3.14."""

from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class TextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-text-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="text_wrapper.py"))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0], expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_all_full_casefold_mappings(self):
        characters = "".join(chr(codepoint) for codepoint in range(sys.maxunicode+1) if chr(codepoint).casefold() != chr(codepoint))
        self.compare(f"value={characters!r}\nprint(value.casefold())\nprint('Straße Σς İ ﬃ'.casefold())\nprint('ASCII ABC'.casefold())")

    def test_character_property_ranges_and_ascii_boundaries(self):
        characters = set("aAzZ0129²½١Ⅳ四\x1c\x1f\u200b\u2028\u3000\u0345\u05b0\u01c5")
        for codepoint in range(sys.maxunicode+1):
            character = chr(codepoint)
            if character.isnumeric() or character.isspace():
                characters.add(character)
                for neighbor in (codepoint-1,codepoint+1):
                    if 0<=neighbor<=sys.maxunicode and not 0xD800<=neighbor<=0xDFFF:
                        characters.add(chr(neighbor))
        rng = random.Random(20261027)
        for _ in range(500):
            codepoint = rng.randrange(sys.maxunicode+1)
            if not 0xD800<=codepoint<=0xDFFF:
                characters.add(chr(codepoint))
        value = "".join(sorted(characters))
        self.compare(f"value={value!r}\nfor method in ['isdecimal','isdigit','isnumeric','isspace','isalpha','isalnum','islower','isupper']:\n print(''.join('1' if getattr(ch,method)() else '0' for ch in value))\nprint(''.isdigit(),''.isdecimal(),''.isnumeric(),''.isspace())\nprint('Aǅ'.isupper(),'aǅ'.islower(),'a²'.islower(),'A²'.isupper())")

    def test_search_prefix_suffix_and_empty_boundaries(self):
        self.compare('''
            for value in ["", "aaaa", "a日本🙂a日本"]:
                for needle in ["", "a", "aa", "日本", "🙂"]:
                    for start in [-100,-1,0,1,len(value),len(value)+1,100]:
                        for stop in [-100,-1,0,1,len(value),len(value)+1,100]:
                            print(value.find(needle,start,stop),value.rfind(needle,start,stop),value.count(needle,start,stop),value.startswith(needle,start,stop),value.endswith(needle,start,stop))
            print("abc".startswith(("a",1)),"abc".endswith(("c",1)))
            for prefix in [(1,"a"),["a"],None]:
                try: print("abc".startswith(prefix))
                except TypeError: print("type")
            try: print("abc".find(1))
            except TypeError: print("type")
            try: print("abc".index("z"))
            except ValueError: print("absent")
        ''')

    def test_identifier_start_continue_unicode_and_nfkc_closure(self):
        characters = set("aAzZ_09日本éK℘·²½\u0301\u200c\u200d\u2118\u212e\u309b\u309c")
        for predicate in (str.isidentifier, lambda ch: ("a"+ch).isidentifier()):
            previous = False
            for codepoint in range(sys.maxunicode+1):
                current = predicate(chr(codepoint))
                if current != previous:
                    for neighbor in (codepoint-1,codepoint,codepoint+1):
                        if 0<=neighbor<=sys.maxunicode and not 0xD800<=neighbor<=0xDFFF:
                            characters.add(chr(neighbor))
                previous = current
        source = "value="+repr("".join(sorted(characters)))+"\n"
        self.compare(source+"print(''.isidentifier())\nprint(''.join('1' if ch.isidentifier() else '0' for ch in value))\nprint(''.join('1' if ('a'+ch).isidentifier() else '0' for ch in value))\nfor word in ['class','_','日本語','a·b','℘x','a\\u0301','\\u0301a','abc def','a\\u200cb','']: print(word.isidentifier())\n")

    def test_python_whitespace_split_and_strip(self):
        whitespace = "".join(chr(codepoint) for codepoint in range(sys.maxunicode+1) if chr(codepoint).isspace())
        self.compare(f"space={whitespace!r}\n"+textwrap.dedent('''
            for maximum in [-2,-1,0,1,2,10]:
                for value in ["",space," a b  ","  a  ",space+"alpha"+space+"beta"+space]:
                    print(value.split(None,maximum),value.rsplit(None,maximum))
            value=space+"middle"+space
            print(repr(value.strip()),repr(value.lstrip()),repr(value.rstrip()))
            print("aaababa".strip("ab"),"abc".strip(""))
            print(" a b ".split(maxsplit=1)," a b ".rsplit(sep=None,maxsplit=1))
        '''))

    def test_explicit_separator_overlaps_and_limits(self):
        self.compare('''
            for value in ["", "aaa", "aaaaa", "a::b::::", "日本🙂日本"]:
                for separator in ["a", "aa", "::", "日本"]:
                    for maximum in [-1,0,1,2,10]:
                        print(value.split(separator,maximum),value.rsplit(separator,maximum))
            for call in [lambda:"x".split(""),lambda:"x".rsplit(1),lambda:"x".split(None,None),lambda:"x".strip(1)]:
                try: call()
                except ValueError: print("value")
                except TypeError: print("type")
        ''')

    def test_replace_count_keyword_and_argument_types(self):
        self.compare('''
            print("aaa".replace("a","x",count=1))
            print("日本日本".replace("日本","語",count=1))
            print("a🙂b".replace("","-",count=3))
            print("aaa".replace("a","x",0),"aaa".replace("a","x",-2))
            for call in [lambda:"aaa".replace(1,"x"),lambda:"aaa".replace("a",1),lambda:"aaa".replace("a","x",1,count=2),lambda:b"aaa".replace(b"a",b"x",count=1)]:
                try: call()
                except TypeError: print("type")
        ''')

    def test_bytes_use_ascii_whitespace_and_keep_raw_values(self):
        self.compare('''
            for value in [b"",b"  a b  ",b"\\x1ca\\x1f",b"\\xff a \\x80",b"\\t\\n\\r\\v\\f "]:
                for maximum in [-1,0,1,2]:
                    print(value.split(None,maximum),value.rsplit(None,maximum))
                print(value.strip(),value.lstrip(),value.rstrip())
            print(b"-".join([b"a",b"\\xff",b"b"]))
            print(b"abcabc".replace(b"ab",b"X",1),b"abc".replace(b"",b"-",2))
            print(b"aaa".rsplit(b"aa"),b"aaa".split(b"aa"))
        ''')

    def test_bytes_search_and_type_checks(self):
        self.compare('''
            for value in [b"",b"aaaa",b"a\\xffa"]:
                for needle in [b"",b"a",b"aa",255]:
                    for start in [-10,-1,0,1,len(value),len(value)+1,10]:
                        for stop in [-10,-1,0,1,len(value),len(value)+1,10]:
                            print(value.find(needle,start,stop),value.rfind(needle,start,stop),value.count(needle,start,stop))
            print(b"abc".startswith((b"a",1)),b"abc".endswith((b"c",1)))
            for needle in [-1,256,"a"]:
                try: print(b"abc".find(needle))
                except ValueError: print("value")
                except TypeError: print("type")
            try: b"a".startswith("a")
            except TypeError: print("type")
            try: b"a".join([b"a","b"])
            except TypeError: print("type")
        ''')

    def test_buffer_read_split_competitive_programming_idiom(self):
        source = "import sys\nvalues=list(map(int,sys.stdin.buffer.read().split()))\nprint(sum(values),len(values))\n"
        result = transpile(source)
        self.assertTrue(result.success,result.diagnostics)
        root = Path(self.directory.name)
        rust = root / "buffer.rs"
        binary = root / "buffer"
        rust.write_text(result.rust_source,encoding="utf-8")
        compiled = subprocess.run(["rustc","--edition=2021",str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=120)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        for data in [b"",b"12 -3\n4\t5\r\n",b"1\n2\n3"]:
            actual = subprocess.run([str(binary)],input=data,capture_output=True,timeout=15)
            expected = subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,timeout=15)
            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
            self.assertEqual(actual.stdout,expected.stdout,actual.stderr)

    def test_unicode_tables_are_reproducible(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable,str(root/"tools/generate_unicode.py"),"--check"],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == "__main__":
    unittest.main()
