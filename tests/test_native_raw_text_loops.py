"""Shared typed cursors admit raw text and bytes in direct for loops."""
import ast
import shutil
import unittest
from py2fastrust.frontend import build_program
from tests import test_native_frame_splits as text_helpers


class RawTextLoopCapabilityTests(unittest.TestCase):
    def test_ordinary_text_loop_keeps_the_existing_static_path(self):
        from py2fastrust.native_frame_selection import select_frames
        for source in ["text=input()\nfor letter in text:print(letter)\n",
                       "for index,letter in enumerate('abc'):print(index,letter)\n",
                       "values=list(map(int,input().split()))\nprint(sum(values))\n"]:
            self.assertFalse(select_frames(build_program(source,'main.py').main).required)

    def test_original_ast_and_scope_nodes_are_retained(self):
        from py2fastrust.native_classes import try_generate_classes
        source="class Box:\n def run(self,text):\n  for letter in text:print(letter)\nBox().run('abc')\n"
        unit=build_program(source,'main.py').main
        before=ast.dump(unit.tree,include_attributes=True);nodes=tuple(ast.walk(unit.tree))
        self.assertIsNotNone(try_generate_classes(source,'main.py','i64',unit=unit))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertEqual(tuple(ast.walk(unit.tree)),nodes)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class RawTextLoopExecutionTests(unittest.TestCase):
    exercise=text_helpers.SplitExecutionTests.exercise

    def test_raw_text(self):
        self.exercise("class Box:\n def run(self):\n  for letter in 'abcabc':print(letter)\nBox().run()\n")

    def test_raw_bytes(self):
        self.exercise("class Box:\n def run(self):\n  for byte in b'\\x00a\\xff':print(byte)\nBox().run()\n")

    def test_unicode_text(self):
        self.exercise("# pytors: --string-mode unicode\nclass Box:\n def run(self):\n  for letter in '猫éé犬':print(letter)\nBox().run()\n")

    def test_text_bytes_finite_union(self):
        self.exercise("class Box:\n def run(self,source):\n  for item in source:print(item)\nb=Box()\nb.run('abc')\nb.run(b'abc')\n")

    def test_text_list_range_union(self):
        self.exercise("class Box:\n def run(self,source):\n  for item in source:print(item)\nb=Box()\nb.run('ab')\nb.run([4,5])\nb.run(range(3))\n")

    def test_optional_text_valid(self):
        self.exercise("class Box:\n def run(self,source):\n  for item in source:print(item)\nb=Box()\nb.run('abc')\nb.run(None)\n")

    def test_nested_text_bytes(self):
        self.exercise("class Box:\n def run(self):\n  for letter in 'ab':\n   for byte in b'cd':print(letter,byte)\nBox().run()\n")

    def test_zero_trip_binding(self):
        self.exercise("class Box:\n def run(self):\n  last=17\n  for last in '':print('unreachable')\n  print(last)\nBox().run()\n")

    def test_zero_trip_unbound(self):
        self.exercise("class Box:\n def run(self):\n  for item in '':print('unreachable')\n  print(item)\nBox().run()\n")

    def test_source_local_rebinding(self):
        self.exercise("class Box:\n def run(self):\n  source='abc'\n  for letter in source:\n   print(letter)\n   source='new'\n  print(source)\nBox().run()\n")

    def test_source_field_rebinding(self):
        self.exercise("class Box:\n def __init__(self):self.text='abc'\n def change(self):self.text='new'\n def run(self):\n  for letter in self.text:\n   self.change()\n   print(letter,self.text)\nBox().run()\n")

    def test_source_evaluated_once(self):
        self.exercise("class Box:\n def source(self):\n  print('source')\n  return 'abc'\n def run(self):\n  for letter in self.source():print(letter)\nBox().run()\n")

    def test_enumerate_text(self):
        self.exercise("class Box:\n def run(self):\n  for index,letter in enumerate('abc',3):print(index,letter)\nBox().run()\n")

    def test_enumerate_bytes(self):
        self.exercise("class Box:\n def run(self):\n  for index,byte in enumerate(b'\\x00a\\xff',-2):print(index,byte)\nBox().run()\n")

    def test_break_continue(self):
        self.exercise("class Box:\n def run(self):\n  for letter in 'abxcde':\n   if letter=='b':continue\n   if letter=='d':break\n   print(letter)\nBox().run()\n")

    def test_ordinary_static_loop(self):
        self.exercise('source=input()\nfor letter in source:print(letter)\n',data='abc\n')

    def test_binary_line_loop(self):
        self.exercise("import sys\nclass Box:\n def run(self):\n  for byte in sys.stdin.buffer.readline().rstrip(b'\\n'):print(byte)\nBox().run()\n",data='abc\n')

    def test_nested_empty_text(self):
        self.exercise("class Box:\n def run(self):\n  for first in ['ab','','c']:\n   for letter in first:\n    print(letter)\nBox().run()\n")
