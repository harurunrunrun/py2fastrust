"""Fixed-width digit limits retain callback-safe source display ownership."""
import unittest
from unittest.mock import patch

import test_native_integer_digit_limits as support

CASES = {'tuple_rows_plain': ('class Item:\n def __repr__(self):\n  print("repr")\n  return "item"\nrows=[(Item(),3)]\nprint(rows)\n', ('',), ('i64', 'i128', 'bigint'), 'ascii'), 'tuple_rows_api': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __repr__(self):\n  print("repr")\n  return "item"\nrows=[(Item(),3)]\nprint(rows)\n', ('',), ('i64', 'i128'), 'ascii'), 'append_during_tuple_row_display_plain': ('rows=[]\nclass Item:\n def __init__(self,first):self.first=first\n def __repr__(self):\n  if self.first:\n   self.first=False\n   rows.append((Item(False),7))\n  return "item"\nrows.append((Item(True),3))\nprint(rows)\nprint(len(rows))\n', ('',), ('i64', 'i128', 'bigint'), 'ascii'), 'append_during_tuple_row_display_api': ('import sys\nsys.set_int_max_str_digits(640)\nrows=[]\nclass Item:\n def __init__(self,first):self.first=first\n def __repr__(self):\n  if self.first:\n   self.first=False\n   rows.append((Item(False),7))\n  return "item"\nrows.append((Item(True),3))\nprint(rows)\nprint(len(rows))\n', ('',), ('i64', 'i128'), 'ascii'), 'clear_during_tuple_row_display_plain': ('rows=[]\nclass Item:\n def __repr__(self):\n  rows.clear()\n  return "item"\nrows.append((Item(),3))\nrows.append((Item(),7))\nprint(rows)\nprint(len(rows))\n', ('',), ('i64', 'i128', 'bigint'), 'ascii'), 'clear_during_tuple_row_display_api': ('import sys\nsys.set_int_max_str_digits(640)\nrows=[]\nclass Item:\n def __repr__(self):\n  rows.clear()\n  return "item"\nrows.append((Item(),3))\nrows.append((Item(),7))\nprint(rows)\nprint(len(rows))\n', ('',), ('i64', 'i128'), 'ascii'), 'mixed_union_rows_plain': ('class Item:\n def __repr__(self):return "item"\nprint([Item(),3])\n', ('',), ('i64', 'i128', 'bigint'), 'ascii'), 'mixed_union_rows_api': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __repr__(self):return "item"\nprint([Item(),3])\n', ('',), ('i64', 'i128'), 'ascii'), 'dynamic_tuple_rows_plain': ('class Item:\n def __repr__(self):return "item"\nrows=tuple([(Item(),3)])\nprint(rows)\n', ('',), ('i64', 'i128', 'bigint'), 'ascii'), 'dynamic_tuple_rows_api': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __repr__(self):return "item"\nrows=tuple([(Item(),3)])\nprint(rows)\n', ('',), ('i64', 'i128'), 'ascii'), 'receiver_identity': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __repr__(self):\n  print("same",self is expected)\n  return "item"\nexpected=Item()\nrows=[expected,3]\nprint(rows)\nprint(expected is rows[0])\n', ('',), ('i64', 'i128'), 'ascii'), 'callback_parser_errors': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __repr__(self):\n  print("repr")\n  return str(int(input()))\nrows=[(Item(),3)]\nprint("before",rows,"after")\n', ('7\n', '99999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999\n'), ('i64', 'i128'), 'ascii'), 'noninteger_payload_callback': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __repr__(self):\n  sys.set_int_max_str_digits(0)\n  return "item"\nprint([Item(),"end"])\nprint(sys.get_int_max_str_digits())\n', ('',), ('i64', 'i128', 'bigint'), 'ascii'), 'mutable_receiver': ('import sys\nsys.set_int_max_str_digits(640)\nclass Item:\n def __init__(self):self.count=0\n def __repr__(self):\n  self.count+=1\n  return "item"\nexpected=Item()\nprint([expected,3])\nprint(expected.count)\n', ('',), ('i64', 'i128'), 'ascii'), 'original_mixed_callback_fixed_width': ('import sys\nvalue=1<<3000\nclass Change:\n def __repr__(self):\n  sys.set_int_max_str_digits(0)\n  return "changed"\nsys.set_int_max_str_digits(640)\nprint([Change(),value])\n', ('',), ('i64', 'i128'), 'ascii')}


class FixedDigitDisplayExecutionTests(unittest.TestCase):
    compare = support.IntegerDigitLimitExecutionTests.compare


def _case(name):
    def test(self):
        self.compare(*CASES[name])
    return test


for _name in CASES:
    setattr(FixedDigitDisplayExecutionTests, 'test_' + _name, _case(_name))


class FixedDigitDisplayOwnershipTests(unittest.TestCase):
    def test_source_receiver_capture_distinguishes_borrowed_arms_from_owned_values(self):
        from py2fastrust import transpile, TranspileOptions
        from py2fastrust.native_classes import Emitter
        import py2fastrust.native_source_display as display
        original_show = display.show
        original_capture = Emitter.capture
        contexts = []
        observed = []

        def show(emitter, value, node, representation=False):
            choice = display.selected(emitter.model, value.kind, representation)
            if choice is None:
                return original_show(emitter, value, node, representation)
            context = (value.kind, value.owned, value.code)
            contexts.append(context)
            try:
                return original_show(emitter, value, node, representation)
            finally:
                contexts.pop()

        def capture(emitter, value):
            if contexts and contexts[-1][0] == value.kind:
                observed.append((contexts[-1], value.owned, value.code))
            return original_capture(emitter, value)

        with patch.object(display, 'show', show), patch.object(Emitter, 'capture', capture):
            for name in ('mixed_union_rows_plain', 'tuple_rows_plain'):
                result = transpile(CASES[name][0], TranspileOptions(integer='i64'))
                self.assertTrue(result.success, result.diagnostics)
        borrowed = [row for row in observed if not row[0][1]]
        owned = [row for row in observed if row[0][1]]
        self.assertTrue(borrowed)
        self.assertTrue(owned)
        self.assertTrue(all(row[1] for row in observed))
        self.assertTrue(all(row[2] == row[0][2] for row in owned))
        self.assertTrue(all(row[2] != row[0][2] for row in borrowed))

    def test_bigint_custom_numeric_container_keeps_its_fallible_observer_boundary(self):
        from py2fastrust import transpile, TranspileOptions
        for name in ('tuple_rows_api', 'mixed_union_rows_api'):
            result = transpile(CASES[name][0], TranspileOptions(integer='bigint'))
            self.assertFalse(result.success)
            self.assertTrue(any(item.code == 'E006' and
                'callback-safe digit-limited container display' in item.message
                for item in result.diagnostics), result.diagnostics)


if __name__ == '__main__':
    unittest.main()
