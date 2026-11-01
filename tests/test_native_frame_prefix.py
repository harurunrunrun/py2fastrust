"""Native bounded prefix/suffix queries and lazy tuple-pattern validation."""
import ast
import shutil
import unittest
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from tests import test_native_frame_splits as text_helpers


class PrefixCapabilityTests(unittest.TestCase):
    def test_original_ast_and_scope_nodes_are_retained(self):
        from py2fastrust.native_classes import try_generate_classes
        source="class Box:\n def run(self,text):return text.startswith(('a','b'),0,None)\nprint(Box().run('abc'))\n"
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(try_generate_classes(source,'main.py','i64',unit=unit))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)

    def test_existing_static_input_count_and_loop_paths_are_retained(self):
        from py2fastrust.native_frame_selection import select_frames
        for source in ["text=input()\nprint(text.count('a'))\n",
                       "text=input()\nfor letter in text:print(letter)\n",
                       "values=list(map(int,input().split()))\nprint(sum(values))\n"]:
            self.assertFalse(select_frames(build_program(source,'main.py').main).required)

    def test_custom_slice_index_protocol_has_a_positioned_diagnostic(self):
        source="class Position:\n def __index__(self):return 1\nclass Box:\n def run(self):return 'abc'.startswith('b',Position())\nprint(Box().run())\n"
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('__index__',result.diagnostics[0].message)

    def test_custom_byte_pattern_protocol_has_a_positioned_diagnostic(self):
        source="class Pattern:pass\nclass Box:\n def run(self):return b'abc'.startswith(Pattern())\nprint(Box().run())\n"
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertGreater(result.diagnostics[0].line,0)
            self.assertIn('buffer protocol',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PrefixExecutionTests(unittest.TestCase):
    exercise=text_helpers.SplitExecutionTests.exercise

    def test_text_patterns(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in ['', 'a','ab','aba','b','z','ababab']:\n   print(self.text.startswith(pattern),self.text.endswith(pattern))\nBox('ababa').run()\n")

    def test_bytes_patterns(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in [b'',b'a',b'ab',b'aba',b'b',b'z',b'ababab']:\n   print(self.text.startswith(pattern),self.text.endswith(pattern))\nBox(b'ababa').run()\n")

    def test_text_bounds(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in ['', 'a','ba','z']:\n   for start in [None,-20,-5,-1,0,1,5,6,20]:\n    for end in [None,-20,-1,0,2,5,20]:print(self.text.startswith(pattern,start,end),self.text.endswith(pattern,start,end))\nBox('ababa').run()\n")

    def test_bytes_bounds(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in [b'',b'a',b'ba',b'z']:\n   for start in [None,-20,-5,-1,0,1,5,6,20]:\n    for end in [None,-20,-1,0,2,5,20]:print(self.text.startswith(pattern,start,end),self.text.endswith(pattern,start,end))\nBox(b'ababa').run()\n")

    def test_fixed_text_tuples(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in [(),('a',),('z','ab'),('z','x')]:print(self.text.startswith(pattern),self.text.endswith(pattern))\nBox('ababa').run()\n")

    def test_fixed_bytes_tuples(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in [(),(b'a',),(b'z',b'ab'),(b'z',b'x')]:print(self.text.startswith(pattern),self.text.endswith(pattern))\nBox(b'ababa').run()\n")

    def test_dynamic_tuple_text(self):
        self.exercise("class Box:\n def run(self,text,patterns):return text.startswith(patterns),text.endswith(patterns)\nprint(Box().run('ababa',tuple(['ab','ba'])))\n")

    def test_dynamic_tuple_bytes(self):
        self.exercise("class Box:\n def run(self,text,patterns):return text.startswith(patterns),text.endswith(patterns)\nprint(Box().run(b'ababa',tuple([b'ab',b'ba'])))\n")

    def test_text_tuple_short_circuit(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith(('a',7)),self.text.endswith(('a',None)))\nBox('ababa').run()\n")

    def test_bytes_tuple_short_circuit(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith((b'a',7)),self.text.endswith((b'a',None)))\nBox(b'ababa').run()\n")

    def test_unicode_bounds(self):
        self.exercise("# pytors: --string-mode unicode\nclass Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for pattern in ['', '猫','犬','é','́','猫犬']:\n   for start in [None,-10,-2,0,1,3,8,20]:print(self.text.startswith(pattern,start),self.text.endswith(pattern,start,-1))\nBox('猫犬猫éé猫').run()\n")

    def test_receiver_union(self):
        self.exercise("class Box:\n def run(self,text,pattern):return text.startswith(pattern),text.endswith(pattern)\nb=Box()\nprint(b.run('aba','a'))\nprint(b.run(b'aba',b'a'))\n")

    def test_optional_bounds(self):
        self.exercise("class Box:\n def run(self,text,start,end):return text.startswith('a',start,end),text.endswith('a',start,end)\nfor start in [None,0,True,-2]:\n for end in [None,False,4]:print(Box().run('ababa',start,end))\n")

    def test_argument_order(self):
        self.exercise("class Box:\n def __init__(self):self.text='ababa'\n def pattern(self):\n  print('pattern')\n  self.text='changed'\n  return 'a'\n def start(self):\n  print('start')\n  return 1\n def end(self):\n  print('end')\n  return 5\n def run(self):print(self.text.endswith(self.pattern(),self.start(),self.end()),self.text)\nBox().run()\n")

    def test_tuple_argument_side_effects(self):
        self.exercise("class Box:\n def item(self,n):\n  print(n)\n  return 'a' if n==1 else 7\n def run(self):print('abc'.startswith((self.item(1),self.item(2))))\nBox().run()\n")

    def test_ordinary_input(self):
        self.exercise("text=input()\nprint(text.startswith('#'),text.endswith('.rs'),text.startswith(('//','#')))\n",data='#main.rs\n')

    def test_ordinary_bytes(self):
        self.exercise("import sys\ntext=sys.stdin.buffer.readline().rstrip(b'\\n')\nprint(text.startswith(b'#'),text.endswith(b'.rs'),text.startswith((b'//',b'#')))\n",data='#main.rs\n')

    def test_empty_patterns(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  for text in ['', 'a']:\n   for start in [None,-1,0,1,2]:\n    for end in [None,-1,0,1,2]:print(text.startswith('',start,end),text.endswith('',start,end),text.startswith((),start,end))\nBox('ababa').run()\n")

    def test_text_integer(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith(7))\nBox('ababa').run()\n")

    def test_text_none(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.endswith(None))\nBox('ababa').run()\n")

    def test_text_bytes(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith(b'a'))\nBox('ababa').run()\n")

    def test_bytes_text(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'abc'.startswith('a'))\nBox('ababa').run()\n")

    def test_bytes_integer(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'abc'.endswith(97))\nBox('ababa').run()\n")

    def test_bytes_none(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'abc'.startswith(None))\nBox('ababa').run()\n")

    def test_text_list(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.endswith(['a']))\nBox('ababa').run()\n")

    def test_text_tuple_wrong_member(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith(('z',7)))\nBox('ababa').run()\n")

    def test_bytes_tuple_wrong_member(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'abc'.startswith((b'z',7)))\nBox('ababa').run()\n")

    def test_text_bad_pattern_float_bound(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith(7,1.5))\nBox('ababa').run()\n")

    def test_bytes_bad_pattern_float_bound(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(b'abc'.endswith('c',1.5))\nBox('ababa').run()\n")

    def test_empty_tuple_float_bound(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith((),1.5))\nBox('ababa').run()\n")

    def test_keyword_start(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith('a',start=0))\nBox('ababa').run()\n")

    def test_missing_pattern(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.startswith())\nBox('ababa').run()\n")

    def test_too_many_arguments(self):
        self.exercise("class Box:\n def __init__(self,text):self.text=text\n def run(self):\n  print(self.text.endswith('a',0,5,6))\nBox('ababa').run()\n")

    def test_random_bytes(self):
        self.exercise("cases=[(b'\\xff\\xff\\x00a\\x01\\xff\\x00baab\\x00\\xff\\x01\\x01\\x00\\x01\\xff\\x01\\x01abb\\xffbbbaaa', b'', 0, -5), (b'\\x01aaa\\xff\\x00\\xff\\x00\\x01', b'b\\x01\\xff\\x00', -100, 20), (b'bba\\xffb\\x01\\xff\\xffab\\x00ab\\xffb\\xff\\xff\\x01', b'b\\x00\\x00\\x01a', False, -1), (b'\\x00a\\xffa\\x00b\\xffa\\x00b', b'\\xffbb\\x00\\x00', False, 0), (b'\\xff\\x01a\\xff\\x00\\x01\\xff', b'', 4, -100), (b'b\\xff\\x01b\\x01\\x00b\\x00aa\\x00bb\\x01\\x01\\xff\\x01\\x01\\xffb\\xffb\\xff\\x01aaa\\x00', b'\\x00', 20, False), (b'\\xff\\x01\\x01\\x00\\x00aa\\x00\\x00\\xff\\xff\\xff\\x00\\x01', b'\\x01\\xff', False, None), (b'\\x00baa\\x00b\\x00\\x00\\x00\\x01\\x01\\x00\\x00bba\\x01a\\x01a\\x00\\xff\\xff\\xff\\x00\\xffb\\x00a\\x01bba\\x00\\x00', b'\\xff\\x01b\\xffb\\xff\\x00\\xff', -1, True), (b'\\xffb\\x00\\xff\\xff\\x00a\\x00\\xff\\x00\\x01a\\x00\\x01bbbba', b'\\xff\\xff', 100, None), (b'\\xff\\x01\\x00\\xff\\x01b\\x00\\x01\\x00\\x00b\\x01\\x01\\x01b\\xff\\x00a\\xffb', b'b\\x00', True, 20), (b'b\\xffb\\x01b\\x00\\x00aa\\x00a\\xff\\xff\\xff\\x00b', b'\\x00\\x01\\x00\\xff\\x01a\\xff', 0, 0), (b'\\x00\\xff\\x00bb\\x01\\x01\\x00', b'', 100, 0), (b'bbb\\xff\\x00\\xff\\x01b\\xffaaa\\x00\\xff\\x01\\x01\\x01b', b'\\xff\\x00a', 4, True), (b'', b'', -100, 20), (b'\\x00\\x01b\\xffa\\xffbb\\x01\\x01\\x00\\xffb\\xff\\xff', b'', -100, 100), (b'b\\x00b\\x01ba\\x00a\\x00a\\xff\\x01bb\\x01a\\x01baba\\x01\\x00\\x01ba\\x00\\xff\\x01\\x00bb\\x00\\x00bb\\x00\\xffb', b'b\\x00\\x00b\\x01\\x00b\\x00', False, 20), (b'\\x01\\x00a\\x00b\\x00\\x01a\\x00\\x01\\xffaabbba\\xffba\\xff\\x01ba\\x01a\\x00a\\xff\\x01ab\\x01b\\xff\\x01\\xff\\xff\\x01', b'', -1, 20), (b'\\xff\\x01\\x00', b'b\\x00', -5, 100), (b'\\xffa\\x00b\\xff\\xff\\x01\\xffb\\x00\\x00b\\x00\\x00\\xff\\x01ab\\xff\\x01\\x00b\\x01\\xff\\x00\\xff\\x00\\x01\\xff', b'\\x01a\\x00\\x01\\x00\\x01\\xff\\x00', True, 0), (b'\\x00\\x01\\x00\\xff\\x01b\\xff\\x00ba\\xffab\\xff\\x01b\\x01\\xffbb\\x01\\xff\\x00b\\xffaa\\xff\\x01ba\\x01a\\xff\\xff\\x00a\\x01', b'\\x01b\\x00\\x01\\x00\\x01', False, 1), (b'\\xffa', b'', -1, False), (b'\\xff\\xff\\xff\\x01ba\\x00\\x01a', b'a\\xff\\x01aaa\\x00', -5, None), (b'\\x01\\x01\\xff\\x01a\\x01aaab\\x00\\x01\\xff', b'', False, 20), (b'b\\x00bb\\xff', b'b', -1, 0), (b'\\x01\\xffa\\x01\\xff\\xffb\\x00aa', b'a', True, 100), (b'a\\x00a\\x00b\\x00b\\x01\\x00\\xff\\xff\\xffb\\x00\\xffbbba\\x00\\x00\\x01\\x01\\xff\\x01bbaa\\x00\\x00\\xff\\xff\\x01ba', b'', 1, 0), (b'a\\x01bb\\x00ba\\xffb\\xffab\\xff\\x00ab\\x00\\xff\\xffbab\\x00\\x00\\x00a\\x00\\x01', b'\\x00\\x00aa\\x01\\x01\\x01', -1, 100), (b'\\xff\\x01b', b'\\x01\\x00\\x01', 4, 20), (b'\\x01\\x00b\\xff\\x01b\\x01a\\xff', b'\\x00\\xff\\x01\\x00b\\x01\\xff', -100, 20), (b'abb\\x00\\x01\\xffaa\\x01b\\x01\\xff\\xffba\\x01\\xffb\\x01a\\x01b\\x01a\\xffaa\\xff\\xff\\x01b\\x00', b'\\x00\\x00\\x00\\xff\\x00b', None, 4), (b'\\x01\\xff\\x00\\xffaabb\\x00bbaa\\xff\\x00\\x01\\xff\\x01\\xff\\x00\\x00b\\xff\\xffb\\x01b\\x00abbb\\x00\\x00\\xffa\\x01a', b'ba', 4, None), (b'a\\x01', b'\\xffab\\x01b\\xff', 100, -5), (b'\\xffaa\\x00aa\\x01b\\x00\\x00\\x01\\x01\\x01\\x00\\x01b\\x00aa\\xff', b'\\x00\\x01\\xff\\xff\\x01b', -100, 1), (b'a', b'b', -100, -1), (b'b\\x00baa\\xffa\\xffa\\xff\\xff\\x01ba\\x00aa\\x00\\xff\\xffab\\x00\\x00\\x01\\x01a\\x01\\xff', b'\\xff\\xffb\\x00\\x00', 100, 1), (b'\\x01\\x00\\x00b\\xff\\x00\\x00\\x00\\x00\\x01babb\\x01\\xff\\x00\\x01\\x00\\x01\\xff\\x00aba\\xff\\x01\\x00\\x01\\xffa', b'\\xffa\\x00\\xffb', -1, 1), (b'\\xff\\x01', b'a', True, True), (b'\\xff\\x00\\x01\\x01\\x00\\x00\\x01\\xff\\x01a\\xff\\xffba\\x00b\\xffa\\xff\\x01', b'\\xffbbba\\xff\\x01', 1, 4), (b'\\x00\\x00b\\x01b\\x00\\xffb\\xff\\x00\\x01\\xffbb', b'\\xffb', True, 4), (b'\\xffa\\xffb\\xff\\x01a\\xffb\\x00\\xffb\\x01b\\xffb\\x00ba\\x01\\x01\\xff', b'\\x00\\x01aa', 100, 100), (b'a\\xff\\x00\\x00\\x00b\\x01ab\\x01\\xff\\x01\\x00\\x00\\x01\\x01a\\x00\\x00', b'', True, None), (b'\\x00\\xff\\xff\\x00\\x01\\xff\\x01a\\x00\\xffa\\x01\\xff\\x01', b'bb\\x00aa\\x00\\x00a', 1, 4), (b'\\xffb\\xff\\xffaa\\x01a\\xff', b'bb\\xff\\x00b\\x00b', False, None), (b'a\\xffb\\x01b\\x00ba\\xffb\\x00\\xff\\x01\\xff\\xff', b'\\xffb', True, -5), (b'babaaabb\\x01\\x01\\xff\\x01b\\x00\\xffab', b'\\x01\\x01', True, True), (b'\\x00\\x00\\xff\\xff', b'\\xffa', 100, -100), (b'\\x01\\xff\\xff\\x01\\x01a\\xffaa\\xff\\x00\\xffb\\x00\\x01\\xff\\xff\\xff\\x01\\x00ba\\xff\\x01bb\\x00b\\x01a\\x01a\\x01\\x00b\\xff\\xffba', b'', 4, 0), (b'b\\x01baa\\x01\\xff\\x00aa\\xffab\\xff', b'b\\x01\\x00b', 20, -100), (b'b\\x00\\xff\\x01\\x01a\\x01\\x00\\xff\\x00a\\xff\\x01b\\x00a\\x01\\x01\\xffbaba\\x00\\x01', b'b\\x00\\x01\\x00\\x01aa\\xff', -5, False), (b'\\x00a\\xffbab', b'bb\\xff\\xffb\\x01bb', 20, 20), (b'\\xff\\x00\\x00b\\xffbbaa\\x01\\x00\\x00\\x01', b'\\xff\\x01ba', True, -100), (b'\\x00\\x00\\xffb\\x01\\xff\\x00b\\xff\\x01bbb\\xff\\xff\\x01\\x00\\x01\\x01\\x00\\x01a\\x00\\x00\\x00\\xffaa', b'\\xff\\xff', -100, 1), (b'\\x01\\xff\\x00b\\x00\\x00b', b'aa', 4, 20), (b'', b'\\xffaba\\x00b\\xff\\x00', -100, -1), (b'aa\\x00\\x00bb\\x00a\\x01baa\\x00\\x00\\x00\\x00ba\\xff\\x01\\xff\\xff\\x00\\x00\\x00\\x01ab\\x01\\xff\\xff\\x01a\\x00a\\x01', b'b\\x00\\xff\\x01\\x00\\x00\\xff', 4, 20), (b'abb\\x01\\x00\\xffbab\\x00a\\x01\\x01a\\xff\\x01\\xff\\xffa\\xff', b'\\x00\\xff', -100, None), (b'\\x01\\xff\\x01aa\\x00\\xff\\x00a\\x00\\x00\\xff\\x01\\x00a\\xff\\xffb\\x01b\\x01b\\x01\\x00', b'\\xff\\x01b\\xffbb\\x01', -5, None), (b'bb\\x01\\xffa\\x00', b'\\x01\\xffb\\x00a\\x01', -1, True), (b'\\x01b\\xff\\x00b\\x01a\\x01', b'ba\\x00', -100, -5), (b'bb\\x00\\xff\\x01abb\\x01\\x01b\\x01a', b'b\\x01\\x01', -1, -5), (b'\\xff\\x00a\\x00\\xff\\x00\\x00\\x01bab\\x01b\\x00\\x00\\xff', b'b\\x00\\xffa\\x01', -5, True), (b'b\\xff\\x00\\x01\\xff\\xffaaaab\\x00b\\x01\\x01\\xffb\\xff\\xff', b'\\x00\\x00\\xffa\\x01b\\x01\\x01', 20, None), (b'b\\xff', b'\\x01\\x00\\x01', -1, 100), (b'\\x01a\\xffb\\x00\\xff\\xff\\x01a\\x01a\\x01\\x01\\x00\\x01\\x00\\xffa\\x01\\xffa\\x00\\xffa\\xff\\xff\\x01\\x00\\xff\\xff\\xffa\\x00\\xffa\\x01', b'\\x00', 1, 100), (b'b\\xff\\x00aa\\xffa\\x01\\xffb\\x00b\\x00\\xffa\\x00ab\\x00\\xff\\xff\\xff\\xffaa', b'', True, True), (b'\\xff\\xff\\x00aa\\x00\\x00', b'a\\x01\\x01\\xff\\xff\\xff', -1, -1), (b'\\x01\\xff\\xffab\\x01\\xff\\x00abb\\xff\\x00\\x00\\xffb\\x00b', b'', -5, -100), (b'\\xff\\x00\\xffb\\xff\\xff\\x01\\xffb\\x01b\\xff\\x00\\x00\\x00\\xff\\x00bb\\x01a\\xff\\x01\\x00b\\x01\\x00b\\x00', b'aa\\x00\\xffb\\xff', -1, 1), (b'\\x01\\xffa\\x00\\x00\\x00\\xff\\xff\\x01a\\xffb\\x00\\xffba\\x00\\x00a\\x01', b'\\xff\\x01\\xffb\\x00', False, -1), (b'\\xffa\\x00\\x01\\x00\\xff', b'\\x00a\\x01b', -5, True), (b'', b'b\\xff', True, 1), (b'\\x00\\x01ba\\x01\\xff\\x00a\\x01\\x01a\\x01\\x00\\xff\\x01\\x01\\x01b\\x00\\x00\\x00baab\\x00b\\x01\\xff', b'bb\\x00\\x01', 100, -1), (b'\\xff\\x00\\xff\\x00a\\x00\\xff\\xff\\x01b\\xff\\x01\\xffa\\x01\\xff\\x00ba', b'', 1, -100), (b'aa\\xff\\x00ba\\xffa\\x00\\xffaababbba\\xff\\x01aaa\\x00\\xffbb\\xffa\\x00\\x01\\x01\\x00\\x01\\x01', b'a\\x01\\x00\\xff\\x00', -5, 0), (b'\\x00\\xff\\x00\\x00\\xffbaa', b'bb\\x00\\x01\\x01\\xff', -100, True), (b'\\x00aa\\x01\\x01aa\\x00a\\x01\\xffb', b'\\x01\\x00ba', None, -5), (b'\\xff\\x01a\\x01\\x00\\xff\\x00\\x00a\\x01\\x00b\\x01', b'\\x00', 100, False), (b'\\xff\\x00\\xffa\\x00a\\xff\\x01\\xff\\x01a\\x00\\x00\\x01\\xffb\\xff\\xff\\x01a\\x00', b'', 20, -1), (b'', b'\\x01', 4, 1), (b'\\x01b\\x01\\x01\\x00\\xff\\x01a\\x01bb\\xff\\xffa\\x01abbb\\x00\\xff\\x01bb\\x00aab\\x00\\x01b', b'a\\x01', 0, -5), (b'\\x01\\x01\\x00\\x01baa', b'', 4, 4), (b'a\\x01\\xff', b'\\xffa', None, None), (b'\\x01\\x01ba\\x00', b'a\\x00\\xff', False, 20), (b'\\x01\\x01\\xff\\xff\\x00\\x01\\x01a\\xff\\xff\\x01\\x01\\x00aa\\xff', b'\\x00\\x01\\x00', None, 100), (b'\\x01a\\x00\\x00b\\x01\\xffa\\x00a\\x01\\x00\\x00', b'\\xff\\x01\\x00b\\x00\\x00\\x01', -100, 20), (b'\\x00\\x01\\x01\\x00\\xff\\xff\\x01b\\xff', b'\\xff\\x00\\x01b\\x01', 0, -5), (b'aaaaa\\x01a\\x00\\x01\\xffb\\x00\\x01\\x01\\x00\\xffaa\\x01ab\\x00b\\xffba\\xff\\xff\\x00\\xff', b'\\x01\\x00', 100, 1), (b'\\x01\\x01\\x01\\xff\\x01\\x00a\\xff\\x00\\xff\\x01\\x01\\x00\\x00\\x01ab\\x01\\x01aba\\x01\\xffbbba', b'', -1, 1), (b'a\\xff\\xffbb\\xff\\x00\\x00\\xffa\\x01b\\xffaaa\\x00\\x01\\xff', b'\\x01', 0, 1), (b'\\x01b\\xffa\\x00a\\x01b\\x01\\x00\\x01b\\xffa\\xff\\x00\\xffb\\xff\\xff\\xffb\\x01\\x01\\x01\\x00aaaaab', b'\\xff\\xffbb\\xff\\x00', -1, False), (b'\\xff\\xff\\xff', b'', False, 20), (b'\\xff\\x01\\x00\\x00a\\x00', b'\\xffa\\x01\\x01', 4, 20), (b'\\x00\\x01bb\\x00', b'b\\xffa\\x00a', -1, 20), (b'a', b'b\\x01\\xff', -1, 0), (b'a', b'\\xff\\x01\\xff\\x01\\x01', None, True), (b'a\\x01\\x00a\\x01\\x01\\x01ba\\x00b\\x00\\x01b\\x00a\\xff\\xffa', b'b\\x00\\xff\\x00bb\\x01', 20, 1), (b'\\x01\\xff\\x00a\\x00\\xffa\\x00a\\x00\\x00bb\\x01\\x00\\x00\\x00\\x00\\x01\\x01\\xff\\x00\\xffba\\x00\\x01b', b'\\x00', -5, -1), (b'aa\\xff\\x01\\x00\\x01a', b'\\x00b\\x00\\x01\\x01a', False, None), (b'b\\x00b\\xff\\xffba', b'b', 0, False), (b'\\x00b\\x01\\x01\\x00\\xffb\\xff\\xff\\x00a\\x00\\x00\\x00\\xff\\xff\\x01', b'', 0, 0)]\nfor text,pattern,start,end in cases:print(text.startswith(pattern,start,end),text.endswith(pattern,start,end))\n")

    def test_random_unicode(self):
        self.exercise("# pytors: --string-mode unicode\ncases=[('é\\x00犬犬ébébaa猫́猫́', '', -5, True), ('\\x00a猫é\\x00a\\x00́\\x00é犬b\\x00́a犬aéé猫́猫猫a犬́́b́', '', 20, 20), ('éaé́猫b猫犬bb猫é猫ab猫abééa\\x00é犬猫a\\x00́a', 'a犬', -5, -1), ('éb́a\\x00́ba猫犬é', 'é', 20, 100), ('b猫é́béb猫́é猫犬', '', -5, None), ('bbaa猫猫aé\\x00犬\\x00é́\\x00é', 'a猫', 4, 1), ('b犬éaa犬́é\\x00\\x00bé犬aé́a猫éé', '\\x00\\x00猫', 20, False), ('', '犬', True, 4), ('a猫猫́éb́́́é犬b́́aa猫b́猫\\x00a猫', '猫aaééá', -100, -5), ('猫é\\x00犬éa猫é́ba犬b\\x00a\\x00aaéab', 'aa', 20, -1), ('é\\x00́éb\\x00é\\x00́́́ébé犬ébbéa\\x00猫猫犬́', '', -1, True), ('b猫犬a\\x00犬aa猫é\\x00犬b猫\\x00猫猫éb猫', '犬犬aa', 4, -1), ('á犬\\x00\\x00́́a猫́ababé猫猫ébéé犬é\\x00é', 'b猫犬', None, None), ('éa猫b猫猫猫a\\x00\\x00b', 'é猫b́́\\x00́', 4, -1), ('猫b', '猫b\\x00', 20, 100), ('猫猫猫猫\\x00é\\x00', 'a\\x00́́', False, False), ('犬éa猫猫a犬猫\\x00猫猫猫aaa犬aá\\x00áéaaa猫猫é', '', -100, 20), ('éab犬é́aé́aéábéb', 'a\\x00\\x00a犬́', False, 1), ('́́猫\\x00́bé猫éáb\\x00́́é', 'bb\\x00a犬́', -1, 100), ('犬', '', 20, 4), ('猫b犬́́a犬犬aa犬é犬aa\\x00b犬猫́é', '', 20, 4), ('b', '', 0, 4), ('a犬a\\x00\\x00́b́', 'é́\\x00', False, 100), ('b犬éb\\x00', 'b', 1, -100), ('b猫é\\x00á́aab猫', 'bé', 1, False), ('猫猫́犬é\\x00猫', 'é́猫猫', 20, 1), ('́犬ba\\x00犬a\\x00b猫́猫\\x00猫́́́猫́', '', True, 0), ('á́犬éa犬犬ééb́猫猫猫\\x00aa\\x00猫a\\x00猫猫́bb', '́́́', None, -100), ('犬ábé\\x00é犬b', '́犬猫́b', 0, -5), ('犬', 'bab犬́b', -100, -5), ('\\x00犬猫a犬犬a犬', 'ab犬é́á', -1, -1), ('é猫\\x00猫犬b\\x00́a犬犬猫犬犬é', '猫́', -100, -1), ('é\\x00\\x00a犬', 'baa\\x00abb', 4, None), ('a\\x00犬猫baé犬a犬a犬犬́a猫犬́b́a犬猫', '', 0, 100), ('éaé犬áab猫é', '\\x00́b', -1, 20), ('犬é\\x00éé犬é\\x00\\x00b\\x00猫bba\\x00犬́aá́犬', '́aa', 0, -5), ('\\x00猫猫犬́é\\x00b́é犬aáa\\x00́́é犬b\\x00', 'b猫\\x00b́a', 4, None), ('犬猫\\x00é犬aé', '犬', 100, 20), ('犬猫\\x00\\x00b猫aaé猫a猫́', '́犬\\x00b́\\x00', -100, False), ('b́猫aaab\\x00\\x00á\\x00́b猫b́éé', 'aa猫\\x00a', -1, 20), ('犬猫é\\x00a猫猫', '犬b犬', 0, None), ('a猫́é́\\x00\\x00é犬b猫a犬baébb犬', '犬́', True, 4), ('́b́犬a犬́犬\\x00\\x00\\x00', '́b', True, 20), ('b́b猫', '\\x00a猫é犬', -5, 0), ('猫猫́犬b', 'éé猫bb', 20, True), ('́ééb\\x00犬犬\\x00\\x00b犬\\x00́́犬\\x00\\x00a猫ééa猫bé', '', 100, None), ('é́犬aé\\x00\\x00b́́ba猫\\x00é', '', 0, 1), ('猫́bbbé猫猫b猫猫a犬猫éaaa\\x00éébaa', '́ba', 1, None), ('犬犬a\\x00́é́犬\\x00́́b\\x00ab猫é́b\\x00́犬\\x00́\\x00́', 'é猫猫aaa\\x00', 20, False), ('犬\\x00\\x00\\x00犬犬猫\\x00\\x00́\\x00犬\\x00áb́', '\\x00á犬猫犬é', 0, False), ('猫猫é猫猫犬éá́́́\\x00猫a犬́́猫b\\x00b\\x00a犬áb', '犬\\x00猫', 100, None), ('a猫b犬猫', 'b́猫', 100, 20), ('', 'é犬犬', 1, -5), ('\\x00béa猫́猫猫́́a犬ébé\\x00犬́aéba猫́b', '\\x00犬b', 1, False), ('\\x00ébé\\x00b\\x00́ab́猫\\x00猫baébab\\x00\\x00', '猫b́', 20, 1), ('aé犬\\x00́\\x00犬a猫́b猫猫\\x00犬é猫aaab', 'ab', True, 0), ('b́\\x00́é猫́\\x00́b\\x00ééb́́b', '', True, -5), ('a\\x00́猫犬́犬́ab', 'a猫́', None, False), ('aéb\\x00bab犬b́́ébé犬犬́́\\x00猫a\\x00́\\x00ba犬', '', -5, -1), ('猫\\x00abb犬a猫é猫́\\x00犬犬', 'ab', -5, 20), ('猫éééaé\\x00', '́é\\x00猫犬犬́', 4, -1), ('\\x00́́犬é犬犬犬́b́\\x00b́犬́犬猫猫犬é猫́猫', '́\\x00猫', -100, -100), ('犬猫́á犬\\x00\\x00犬猫́é\\x00猫é́\\x00\\x00b猫', '́\\x00é猫猫́', -1, None), ('b猫bb猫猫́', 'éb́a', 0, 1), ('ba猫\\x00猫犬é犬́b猫', 'aé犬é犬ba', -5, 20), ('', 'b犬ba', 20, -1), ('b́́', '́éébb\\x00犬', 4, -5), ('abb\\x00', '猫a', 4, False), ('éb\\x00é\\x00a猫\\x00á犬́猫b\\x00犬犬\\x00é猫犬猫é犬', '犬b', -100, -100), ('\\x00aabéb́b\\x00猫', 'b', -5, False), ('猫猫ébaéééab猫\\x00́b猫béaa犬', 'aé猫́犬b\\x00', 0, 20), ('b犬猫猫́́éaa\\x00á猫́\\x00́́a猫ába\\x00é\\x00', '́猫', None, 0), ('éb犬é猫́b́猫\\x00犬犬', '́犬猫\\x00́', 100, False), ('́猫a\\x00éé猫́b犬猫', '\\x00́', 0, -100), ('b́猫犬é\\x00猫á́a\\x00ab犬\\x00\\x00\\x00\\x00é猫b', '', False, -5), ('baé́犬b\\x00bbé', '\\x00犬\\x00́', 0, None), ('b犬aé犬b\\x00b', '', -100, 0), ('b猫犬犬b́a猫́a\\x00犬́é́犬猫猫\\x00犬\\x00é', 'é猫éb猫a\\x00', -5, 4), ('犬á犬é́猫', 'ab', None, None), ('\\x00犬猫́é\\x00ab\\x00é́́b́猫犬́ab́a猫', '́犬犬éa', -5, False), ('犬\\x00́\\x00猫\\x00abb\\x00aaé́é', '\\x00犬́́猫é\\x00', -100, 100), ('猫犬\\x00犬b犬áé́猫\\x00́b', 'é猫', 100, None), ('́bé\\x00犬猫b́猫́ábbb犬ébb́犬a\\x00\\x00\\x00犬b', '́', -1, 100), ('a猫犬́\\x00猫aa犬aá猫a', '', True, 100), ('é\\x00猫é́́aa\\x00b犬b́́b́犬éaééé́\\x00犬á犬', 'aa犬é', -1, 4), ('é猫b猫猫́b犬́aé́aé', '犬猫', 4, 4), ('é́́aéaaaáb́é\\x00犬́猫b', 'a犬́é', 100, -1), ('猫\\x00aéébé\\x00\\x00猫犬é猫éb猫bb猫\\x00猫', '猫ba', False, 4), ('éaé́abaéba犬\\x00', '犬a猫é犬犬', 100, 0), ('éb犬b\\x00ééb犬́a\\x00éb́', '́éb\\x00', None, -5)]\nfor text,pattern,start,end in cases:print(text.startswith(pattern,start,end),text.endswith(pattern,start,end))\n")

    def test_start_width_normalization(self):
        self.exercise("class Box:\n def run(self):return 'abc'.startswith('',1<<63)\nprint(Box().run())\n",expected_by_integer={'i64': ('True\n', '', 0)})

    def test_end_width_normalization(self):
        self.exercise("class Box:\n def run(self):return b'abc'.endswith(b'c',0,1<<63)\nprint(Box().run())\n",expected_by_integer={'i64': ('False\n', '', 0)})

    def test_negative_start_width_normalization(self):
        self.exercise("class Box:\n def run(self):return 'abc'.startswith('a',-((1<<63)+1))\nprint(Box().run())\n",expected_by_integer={'i64': ('False\n', '', 0)})

    def test_negative_end_width_normalization(self):
        self.exercise("class Box:\n def run(self):return b'abc'.startswith(b'a',0,-((1<<63)+1))\nprint(Box().run())\n",expected_by_integer={'i64': ('True\n', '', 0)})

    def test_user_method_identity(self):
        self.exercise('class Box:\n def startswith(self,value):return value+1\n def endswith(self,value):return value+2\nb=Box()\nprint(b.startswith(4),b.endswith(6))\n')

    def test_nested_tuple_text_error(self):
        self.exercise("class Box:\n def run(self):return 'abc'.startswith((('a',),))\nprint(Box().run())\n")

    def test_nested_tuple_bytes_error(self):
        self.exercise("class Box:\n def run(self):return b'abc'.endswith(((b'c',),))\nprint(Box().run())\n")

    def test_tuple_sequence_lazy_error(self):
        self.exercise("class Box:\n def run(self,patterns):return 'abc'.startswith(patterns)\nb=Box()\nprint(b.run(tuple(['a',7])))\nprint(b.run(tuple(['z',7])))\n")

    def test_tuple_sequence_bytes_lazy_error(self):
        self.exercise("class Box:\n def run(self,patterns):return b'abc'.endswith(patterns)\nb=Box()\nprint(b.run(tuple([b'c',None])))\nprint(b.run(tuple([b'z',None])))\n")

    def test_bool_integer_join(self):
        self.exercise("class Box:\n def run(self,text,flag):\n  if flag:return text.startswith('a')\n  return 7\nb=Box()\nprint(b.run('abc',True),b.run('abc',False))\n")
