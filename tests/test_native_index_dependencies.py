"""Checked indexing works for streamed and borrowed sequence storage."""
import shutil
import unittest
import test_native_lambda_callbacks as helpers

CASES={'buffered_function': ['import sys\n'
                       'def main():\n'
                       ' read=sys.stdin.buffer.readline\n'
                       ' values=list(map(int,read().split()))\n'
                       ' index=int(read())\n'
                       ' print(values[index])\n'
                       'main()\n',
                       ['4 9 2\n-2\n', '4 9 2\n3\n']],
 'first_index_error_precedes_later_argument': ['def mark():\n'
                                               " print('argument')\n"
                                               ' return 9\n'
                                               'values=list(map(int,input().split()))\n'
                                               'print(values[int(input())],mark())\n',
                                               ['1 2\n0\n', '1 2\n7\n']],
 'mapped_text': ['values=list(map(int,input().split()))\nprint(values[0],values[-1])\n',
                 ['7 2 -3\n', '\n']],
 'nested_row_methods': ['n=int(input())\n'
                        'rows=[list(map(int,input().split()))for _ in range(n)]\n'
                        'rows[-1].append(9)\n'
                        'print(rows[-1][-1],rows[0][0])\n',
                        ['2\n1 2\n3 4\n', '0\n']],
 'owned_words': ['words=input().split()\nprint(words[-1],words[0])\n', ['red blue green\n', '\n']],
 'specialized_parameter': ['def choose(values,index):return values[index]\n'
                           'values=list(map(int,input().split()))\n'
                           'print(choose(values,int(input())))\n',
                           ['5 8 13\n-1\n', '5 8 13\n3\n']]}

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeIndexDependencyTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

def install(name,source,inputs):
    def test(self):self.exercise(source,inputs)
    setattr(NativeIndexDependencyTests,'test_'+name,test)
for name,(source,inputs)in CASES.items():install(name,source,inputs)
