"""Zip tuple payloads coerce to solved carriers, preserving lazy source effects."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'negative_heap_strict_empty': 'from heapq import nsmallest\n'
                               'source=zip([],[1],strict=True)\n'
                               'print(nsmallest(-3,source,key=7))\n'
                               'print("after")\n',
 'zero_heap_strict_empty': 'from heapq import nlargest\n'
                           'source=zip([],[1],strict=True)\n'
                           'print(nlargest(0,source,key=7))\n'
                           'print("after")\n',
 'sorted_empty_first': 'source=zip([],[1])\nprint(sorted(source))\n',
 'sorted_both_empty': 'source=zip([],[])\nprint(sorted(source))\n',
 'sorted_strict_longer': 'source=zip([],[1],strict=True)\n'
                         'print(sorted(source))\n',
 'sorted_empty_key_cold': 'source=zip([],[1])\nprint(sorted(source,key=7))\n',
 'mutable_source_populates': 'rows=[]\n'
                             'source=zip(rows,[1,2])\n'
                             'rows.append(3)\n'
                             'rows.append(4)\n'
                             'print(sorted(source))\n',
 'source_family_multiple_types': 'def pairs(rows):return zip(rows,[1,2])\n'
                                 'print(sorted(pairs([4,3])))\n'
                                 'print(sorted(pairs(["b","a"])))\n',
 'boolean_field_promotion': 'source=zip([True,False],[1,2])\n'
                            'print(sorted(source))\n',
 'shared_mutable_items': 'a=[2]\n'
                         'b=[1]\n'
                         'source=zip([a,b],[3,4])\n'
                         'rows=sorted(source)\n'
                         'rows[1][0].append(7)\n'
                         'print(rows,a,b)\n'}

CASES.update({'original_zero_tuple_bottom_zip': 'from heapq import nlargest\n'
                                   'print(nlargest(0,zip((),[1],strict=True)))\n'
                                   'print("after")\n',
 'original_zero_tuple_bottom_map': 'from heapq import nsmallest\n'
                                   'print(nsmallest(0,map(lambda '
                                   'a,b:a,(),[1],strict=True)))\n'
                                   'print("after")\n',
 'original_negative_empty_strict_zip': 'from heapq import nsmallest\n'
                                       'source=zip([],[1],strict=True)\n'
                                       'print(nsmallest(-3,source,key=7))\n'
                                       "print('after')\n",
 'immutable_empty_strict_pull': 'source=zip((),[1],strict=True)\n'
                                'print(list(source))\n',
 'immutable_empty_map_strict_pull': 'source=map(lambda '
                                    'a,b:a,(),[1],strict=True)\n'
                                    'print(list(source))\n',
 'immutable_empty_map_default': 'source=map(lambda a,b:a,(),[1])\n'
                                'print(next(source,"done"),list(source))\n'})

@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class ZipCarriers(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_negative_heap_strict_empty(self):
        self.check('negative_heap_strict_empty')

    def test_zero_heap_strict_empty(self):
        self.check('zero_heap_strict_empty')

    def test_sorted_empty_first(self):
        self.check('sorted_empty_first')

    def test_sorted_both_empty(self):
        self.check('sorted_both_empty')

    def test_sorted_strict_longer(self):
        self.check('sorted_strict_longer')

    def test_sorted_empty_key_cold(self):
        self.check('sorted_empty_key_cold')

    def test_mutable_source_populates(self):
        self.check('mutable_source_populates')

    def test_source_family_multiple_types(self):
        self.check('source_family_multiple_types')

    def test_boolean_field_promotion(self):
        self.check('boolean_field_promotion')

    def test_shared_mutable_items(self):
        self.check('shared_mutable_items')


    def test_original_zero_tuple_bottom_zip(self):
        self.check('original_zero_tuple_bottom_zip')

    def test_original_zero_tuple_bottom_map(self):
        self.check('original_zero_tuple_bottom_map')

    def test_original_negative_empty_strict_zip(self):
        self.check('original_negative_empty_strict_zip')

    def test_immutable_empty_strict_pull(self):
        self.check('immutable_empty_strict_pull')

    def test_immutable_empty_map_strict_pull(self):
        self.check('immutable_empty_map_strict_pull')

    def test_immutable_empty_map_default(self):
        self.check('immutable_empty_map_default')

