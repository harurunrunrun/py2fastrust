"""Iterator state selection preserves existing direct unpack consumers."""
import unittest

from py2fastrust.frontend import parse_source
from py2fastrust.native_frame_selection import select_frames
import test_native_class_iterators as execution


CASES = {
    "word_unpack_and_set": 'a,b=map(int,"12 30".split())\nvalues={(a,b)}\nprint((12,30)in values)\n',
    "alias_and_tuple_unpack": 'convert=int\na,b=map(convert,("2","3"))\nprint(a,b)\n',
    "range_unpack": 'a,b=map(abs,range(2))\nprint(a,b)\n',
    "bytes_unpack": 'a,b=map(int,b"-2 17".split())\nprint(a,b)\n',
    "unpack_noncallable": 'a,b=map(None,[1,2])\nprint(a,b)\n',
    "unpack_invalid_int": 'a,b=map(int,[None,None])\nprint(a,b)\n',
    "unpack_float_abs": 'a,b=map(abs,[-1.5,2.5])\nprint(a,b)\n',
    "unpack_strict": 'a,b=map(int,["1","2"],strict=True)\nprint(a,b)\n',
    "chained_unpack": 'a,b=c,d=map(int,["1","2"])\nprint(a,b,c,d)\n',
    "saved_map_cursor": 'source=map(int,["1","2"])\nprint(next(source),list(source))\n',
}


class IteratorSelectionTests(unittest.TestCase):
    def test_proved_single_unpack_keeps_ordinary_storage(self):
        for name in ("word_unpack_and_set", "alias_and_tuple_unpack", "range_unpack", "bytes_unpack"):
            with self.subTest(name=name):
                self.assertFalse(select_frames(parse_source(CASES[name])).required)

    def test_runtime_callback_and_cursor_protocols_keep_frames(self):
        for name in ("unpack_noncallable", "unpack_invalid_int", "unpack_float_abs", "unpack_strict", "chained_unpack", "saved_map_cursor"):
            with self.subTest(name=name):
                self.assertTrue(select_frames(parse_source(CASES[name])).required)


class IteratorSelectionExecutionTests(unittest.TestCase):
    cases = CASES
    check = execution.IteratorExecutionTests.check

    def test_immediate_consumers(self):
        for name in ("word_unpack_and_set", "alias_and_tuple_unpack", "range_unpack", "bytes_unpack"):
            with self.subTest(name=name):
                self.check(name)

    def test_runtime_error_and_saved_cursor_consumers(self):
        for name in ("unpack_noncallable", "unpack_invalid_int", "unpack_float_abs", "unpack_strict", "chained_unpack", "saved_map_cursor"):
            with self.subTest(name=name):
                self.check(name)


if __name__ == "__main__":
    unittest.main()
