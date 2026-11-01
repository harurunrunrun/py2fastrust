"""Native stripping of text and bytes with original captured arguments."""
import ast
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from tests import test_native_frame_splits as text_helpers


class StripCapabilityTests(unittest.TestCase):
    def test_string_literal_chars_keep_the_static_path(self):
        from py2fastrust.native_frame_selection import select_frames
        unit=build_program("s=input().rstrip('\\n')\nprint(s)\n",'main.py').main
        self.assertFalse(select_frames(unit).required)

    def test_source_ast_remains_original(self):
        from py2fastrust.native_classes import try_generate_classes
        source="class Box:\n def run(self,text):return text.rstrip('\\n')\nprint(Box().run('a\\n'))\n"
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(try_generate_classes(source,'main.py','i64',unit=unit))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_custom_bytes_buffer_has_a_positioned_protocol_diagnostic(self):
        source="class Characters:pass\nclass Box:\n def run(self):return b'abc'.strip(Characters())\nprint(Box().run())\n"
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('buffer protocol',result.diagnostics[0].message)
            self.assertIn('chars',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class StripExecutionTests(unittest.TestCase):
    exercise=text_helpers.SplitExecutionTests.exercise

    def test_text_directional_character_set(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for text in ['', 'ab', 'abbaXabab', '  a b  ', '\\x00a\\x00']:\n   print(text.strip('ab'),text.lstrip('ab'),text.rstrip('ab'),sep='|')\n  print(self.text.strip('ab'),self.text.lstrip('ab'),self.text.rstrip('ab'),sep='|')\nBox('ab cab baa').run()\n")

    def test_bytes_directional_character_set(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for text in [b'',b'ab',b'abbaXabab',b'  a b  ',b'\\x00a\\x00']:\n   print(text.strip(b'ab'),text.lstrip(b'ab'),text.rstrip(b'ab'))\n  print(self.text.strip(b'\\x00'),self.text.lstrip(b'\\x00'),self.text.rstrip(b'\\x00'))\nBox(b'\\x00a\\x00').run()\n")

    def test_text_empty_and_whitespace(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for text in ['', '  ', '\\x1ca\\x1d\\x1e\\x1f ', ' \\ta b\\r\\n']:\n   print(text.strip(),text.lstrip(),text.rstrip(),text.strip(''),text.lstrip(''),text.rstrip(''),sep='|')\nBox('ab cab baa').run()\n")

    def test_bytes_empty_and_whitespace(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for text in [b'',b'  ',b'\\x1ca\\x1d\\x1e\\x1f ',b' \\ta b\\r\\n']:\n   print(text.strip(),text.lstrip(),text.rstrip(),text.strip(b''),text.lstrip(b''),text.rstrip(b''))\nBox(b' a ').run()\n")

    def test_optional_text_characters(self):
        self.exercise("class Box:\n def run(self,text,chars):return text.strip(chars),text.lstrip(chars),text.rstrip(chars)\nb=Box()\nfor chars in [None,'ab','']:\n print(b.run(' abXba ',chars))\n")

    def test_optional_bytes_characters(self):
        self.exercise("class Box:\n def run(self,text,chars):return text.strip(chars),text.lstrip(chars),text.rstrip(chars)\nb=Box()\nfor chars in [None,b'ab',b'']:\n print(b.run(b' abXba ',chars))\n")

    def test_mixed_receiver_none(self):
        self.exercise("class Box:\n def run(self,text):return text.strip(None),text.lstrip(None),text.rstrip(None)\nfor text in [' ab ',b' ab ']:print(Box().run(text))\n")

    def test_unicode_character_sets(self):
        self.exercise("# pytors: --string-mode unicode\nclass Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.strip('猫海'),self.text.lstrip('猫海'),self.text.rstrip('猫海'),sep='|')\nBox('猫海猫犬鳥海猫').run()\n")

    def test_unicode_whitespace(self):
        self.exercise("# pytors: --string-mode unicode\nclass Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for text in ['\\u0085\\u00a0猫\\u2028\\u3000','\\u0085\\u2029','\\x1c猫\\x1f']:\n   print(text.strip(),text.lstrip(),text.rstrip(),sep='|')\nBox('ab cab baa').run()\n")

    def test_receiver_before_chars_rebinding(self):
        self.exercise("class Box:\n def __init__(self):self.text=',a,b,,'\n def chars(self):\n  print('chars')\n  self.text='rebound'\n  return ','\n def run(self):print(self.text.rstrip(self.chars()),self.text)\nBox().run()\n")

    def test_ordinary_stdin_rstrip_newline(self):
        self.exercise("import sys\nfor unused in range(3):\n line=sys.stdin.readline().rstrip('\\n')\n print(len(line),line)\n",data='a\n\nlast\n')

    def test_ordinary_buffer_rstrip_crlf(self):
        self.exercise("import sys\nfor unused in range(3):\n line=sys.stdin.buffer.readline().rstrip(b'\\r\\n')\n print(len(line),line)\n",data='a\n\nlast\n')

    def test_ordinary_captured_readline(self):
        self.exercise("import sys\ndef solve():\n input=sys.stdin.buffer.readline\n for unused in range(2):\n  line=input().rstrip(b'\\n')\n  print(len(line),line)\nsolve()\n",data='a\n\n')

    def test_ordinary_optional_chars(self):
        self.exercise("def clean(text,characters):return text.rstrip(characters)\nprint(clean(' a ',None))\nprint(clean('abXbaa','ab'))\n")

    def test_text_integer_chars(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.strip(7))\nBox('ab cab baa').run()\n")

    def test_text_bytes_chars(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.lstrip(b'a'))\nBox('ab cab baa').run()\n")

    def test_bytes_text_chars(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'a'.rstrip('a'))\nBox('ab cab baa').run()\n")

    def test_text_keyword_chars(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.rstrip(chars='a'))\nBox('ab cab baa').run()\n")

    def test_bytes_keyword_chars(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'a'.strip(chars=b'a'))\nBox('ab cab baa').run()\n")

    def test_text_extra_arguments(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.lstrip('a','b'))\nBox('ab cab baa').run()\n")

    def test_bytes_extra_arguments(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'a'.rstrip(b'a',b'b'))\nBox('ab cab baa').run()\n")

    def test_plain_object_text_chars(self):
        self.exercise("class Characters:pass\nclass Box:\n def run(self):return 'abc'.strip(Characters())\nprint(Box().run())\n")

    def test_user_method_names(self):
        self.exercise("class Box:\n def strip(self,chars):return chars+'s'\n def lstrip(self,chars):return chars+'l'\n def rstrip(self,chars):return chars+'r'\nb=Box()\nprint(b.strip('x'),b.lstrip('y'),b.rstrip('z'))\n")
