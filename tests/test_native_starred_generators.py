"""Nonescaping generator expansions fill the native argument buffer directly."""
import unittest
import test_native_class_iterators as execution


CASES = {'body_error_frames': 'def divide(value):\n'
                      " print('body',value)\n"
                      ' return 10//value\n'
                      'print(*(divide(value) for value in [1,0]))\n',
 'compiled_variadic': 'def collect(first,*items,last=9):return first,items,last\n'
                      'print(collect(*(value+1 for value in range(4)),last=8))\n',
 'construction_error': 'def source():\n'
                       " print('source')\n"
                       ' return 1//0\n'
                       "print(*(value for value in source()),end='!')\n",
 'deferred_keyword_mutation': 'values=[1,2]\n'
                              'def later():\n'
                              ' values.append(3)\n'
                              " print('later')\n"
                              " return '!'\n"
                              'print(*(value*2 for value in values),end=later())\n'
                              'print(values)\n',
 'eager_multiple_segments': 'def mark(label,value):\n'
                            ' print(label,value)\n'
                            ' return value\n'
                            "print(0,*(mark('body',value) for value in "
                            "[1,2]),mark('later',3),sep=':')\n",
 'empty_expansion': 'def collect(*items):return items\n'
                    'print(collect(*(value for value in ())))\n'
                    "print(*(value for value in []),end='empty\\n')\n",
 'first_source_handle': 'class Box:\n'
                        ' def __init__(self):self.values=[1,2]\n'
                        'box=Box()\n'
                        'def later():\n'
                        ' box.values=[8]\n'
                        " return '!'\n"
                        'print(*(value for value in box.values),end=later())\n'
                        'print(box.values)\n',
 'mapping_payload_alias': 'mapping={1:[3],2:[4]}\n'
                          'def collect(*items):return items\n'
                          'values=collect(*(value for value in mapping.values()))\n'
                          'values[0].append(9)\n'
                          'print(mapping,values)\n',
 'nested_clauses': 'print(*(a*b for a in range(4) if a%2 for b in range(3) if b>a-2),sep=":")\n',
 'nested_consumers': 'print(*(sum(a*b for b in range(3)) for a in range(4)))\n',
 'pep479': 'cursor=iter([1])\nprint(*(next(cursor) for unused in range(2)))\n',
 'plain_print': 'print(*(value*value for value in range(5)))\n',
 'recursive_callback': 'def fib(n):\n'
                       ' if n<2:return n\n'
                       ' return fib(n-1)+fib(n-2)\n'
                       'print(*(fib(n) for n in range(8)))\n',
 'saved_print': 'output=print\nprint=0\noutput(*(n+2 for n in [1,2,3]))\n'}


class StarredGeneratorTests(unittest.TestCase):
    cases = CASES
    check = execution.IteratorExecutionTests.check

    def test_starred_generator_consumers(self):
        for name in CASES:
            with self.subTest(name=name):self.check(name)


if __name__ == '__main__':unittest.main()
