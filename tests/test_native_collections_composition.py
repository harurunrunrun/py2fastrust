"""Collection adapters compose with callbacks, shared fields and argument packs."""
import unittest
import test_native_class_iterators as execution


CASES = {'accumulate_callback_in_field_loop': 'from itertools import accumulate\n'
                                      'class Box:\n'
                                      ' def __init__(self):self.value=0\n'
                                      'box=Box()\n'
                                      'def add(left,right):\n'
                                      ' box.value+=1\n'
                                      ' return left+right\n'
                                      'for value in accumulate([1,2,3],add):\n'
                                      ' print(box.value,value)\n',
 'counter_callback_in_field_loop': 'from collections import Counter\n'
                                   'class Box:\n'
                                   ' def __init__(self):self.value=0\n'
                                   'box=Box()\n'
                                   'def change(value):\n'
                                   ' box.value+=value\n'
                                   ' return value\n'
                                   'for _ in range(3):\n'
                                   ' print(box.value)\n'
                                   ' Counter(map(change,[1,2]))\n'
                                   ' print(box.value)\n',
 'variadic_counter_accumulate_and_copy': 'from collections import Counter\n'
                                         'from itertools import accumulate\n'
                                         'def collect(*values):return Counter(accumulate(values))\n'
                                         'for counter in [collect(),collect(1,1,2)]:\n'
                                         ' print((counter,counter.copy()))\n'
                                         ' '
                                         'print(isinstance(counter,Counter),isinstance(counter,dict),counter.total())\n'}


class NativeCollectionsCompositionTests(unittest.TestCase):
    cases = CASES
    check = execution.IteratorExecutionTests.check

    def test_collections_and_callback_state(self):
        for name in CASES:
            with self.subTest(name=name):self.check(name)


if __name__ == '__main__':unittest.main()
