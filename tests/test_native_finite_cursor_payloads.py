"""Heterogeneous yielded values use normal typed unions in native pull arms."""
import shutil,unittest
import test_native_class_iterators as iterator_tests

CASES={'scalar_payloads': 'def choose(flag):\n'
                    '    if flag:\n'
                    '        return iter([1,2])\n'
                    '    return iter(("east","west"))\n'
                    'cursor=choose(int(input()))\n'
                    'for value in cursor:\n'
                    '    print(value)\n'
                    'print(next(cursor,None))\n',
 'tuple_payloads': 'left=iter([(1,"a"),(2,"b")])\n'
                   'right=iter((("c",3),("d",4)))\n'
                   'cursor=left if int(input()) else right\n'
                   'for row in cursor:\n'
                   '    print(row,row[0],row[1])\n'
                   'print(next(cursor,None))\n'}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class FiniteCursorPayloads(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def run_case(self,name):
        for data in ("0\n","1\n"):
            self.inputs={name:data}
            with self.subTest(name=name,input=data):self.check(name)


for _name in CASES:
    setattr(FiniteCursorPayloads,"test_"+_name,lambda self,name=_name:self.run_case(name))
