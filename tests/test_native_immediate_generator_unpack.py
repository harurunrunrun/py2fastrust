"""Consume fixed unpack targets without collecting a generator into a list."""
import unittest
import test_native_class_iterators as helpers

CASES={
    'base_conversion': 'class Marker:pass\na,b=(int(word,16)for word in input().split())\nprint(a+b)\n',
    'nested_filters': 'class Marker:pass\na,b,c=(x+y for x in range(3)for y in range(3)if x==y)\nprint(a,b,c)\n',
    'ordered_targets': 'class Marker:pass\nvalues=[0,0,0]\ndef mark(x):\n print("body",x)\n return x\nvalues[0],values[values[0]]=(mark(x)for x in [2,7])\nprint(values)\n',
    'short_before_targets': 'class Marker:pass\nvalues=[0,0]\ndef index():\n print("index")\n return 0\nvalues[index()],values[1]=(x for x in [7])\n',
    'excess_stops_before_fourth': 'class Marker:pass\ndef mark(x):\n print("body",x)\n return x\na,b=(mark(x)for x in range(5))\n',
    'body_exception_frames': 'class Marker:pass\ndef divide(x):return 10//x\na,b=(divide(x)for x in [2,0])\n',
    'tuple_members': 'class Marker:pass\n(a,b),(c,d)=((x,x+1)for x in [3,7])\nprint(a,b,c,d)\n',
}

class ImmediateGeneratorUnpackTests(unittest.TestCase):
    cases=CASES
    inputs={'base_conversion':'-FF 100\n'}
    check=helpers.IteratorExecutionTests.check

    def test_values_scopes_and_target_order(self):
        for name in ('base_conversion','nested_filters','ordered_targets','tuple_members'):
            with self.subTest(name=name):self.check(name)

    def test_failures_preserve_pull_order_and_tracebacks(self):
        for name in ('short_before_targets','excess_stops_before_fourth','body_exception_frames'):
            with self.subTest(name=name):self.check(name)

if __name__=='__main__':unittest.main()
