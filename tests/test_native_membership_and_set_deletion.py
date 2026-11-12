"""Membership and set deletion keep numeric equality, aliases and error order."""
import unittest
import test_native_class_iterators as helpers

CASES={
    'scalar_tuple': 'print(1 in (False,True),3 not in (0,2),"x" in (None,"x",7), b"a" in (b"b",b"a"))\n',
    'class_scalar_tuple': 'class Marker:pass\nprint(1 in (False,True),3 not in (0,2),"x" in (None,"x",7), b"a" in (b"b",b"a"))\n',
    'nested_tuple': 'class Marker:pass\nprint((2,"x") in ((1,"y"),(2,"x")),(1,2) not in ((3,4),))\n',
    'argument_order': 'class Marker:pass\ndef needle():\n print("needle")\n return 2\ndef haystack():\n print("haystack")\n return (0,2)\nprint(needle() in haystack())\n',
    'empty_tuple': 'class Marker:pass\ndef needle():\n print("needle")\n return 2\nprint(needle() in (),needle() not in ())\n',
    'deletion_alias': 'class Marker:pass\nvalues={1,2,3}\nsaved=values\nvalues.remove(True)\nvalues.discard(99)\nvalues.discard(2)\nprint(sorted(saved),1 in saved,3 in saved)\n',
    'missing_key': 'class Marker:pass\nvalues={1,2}\nvalues.remove("absent")\n',
    'missing_tuple_key': 'class Marker:pass\nvalues={(1,"x"),(2,"y")}\nvalues.discard((9,"z"))\nprint(len(values))\nvalues.remove((3,"z"))\n',
}
class MembershipAndSetDeletionTests(unittest.TestCase):
    cases=CASES
    check=helpers.IteratorExecutionTests.check
    def test_membership(self):
        for name in ('scalar_tuple','class_scalar_tuple','nested_tuple','argument_order','empty_tuple'):
            with self.subTest(name=name):self.check(name)
    def test_set_aliases_and_missing_keys(self):
        for name in ('deletion_alias','missing_key','missing_tuple_key'):
            with self.subTest(name=name):self.check(name)
if __name__=='__main__':unittest.main()
