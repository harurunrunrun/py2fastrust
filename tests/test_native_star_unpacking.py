"""Extended assignment unpacking captures sources before target stores."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
CASES={'map_input':'t,*inputs=map(int,input().split())\nprint(t,inputs)\n',
 'prefix_rest': 'first,*rest=(1,2,3)\nprint(first,rest)\n',
 'rest_tail': '*rest,last=(1,2,3)\nprint(rest,last)\n',
 'prefix_rest_tail': 'first,*rest,last=(1,2,3,4)\nprint(first,rest,last)\n',
 'only_rest': '*rest,=(1,2,3)\nprint(rest)\n',
 'empty_rest': '*rest,=[]\nprint(rest)\n',
 'empty_between': 'first,*rest,last=[1,2]\nprint(first,rest,last)\n',
 'heterogeneous_tuple': 'first,*rest,last=(1,"x",None,True)\n'
                        'print(first,rest,last)\n',
 'shared_iterator': 'source=iter([1,2,3,4])\n'
                    'other=source\n'
                    'first,*rest,last=source\n'
                    'print(first,rest,last,list(other))\n',
 'source_capture_before_stores': 'first="old first"\n'
                                 'rest="old rest"\n'
                                 'def item(x):\n'
                                 ' print(first,rest,x)\n'
                                 ' return x\n'
                                 'first,*rest=map(item,[1,2,3])\n'
                                 'print(first,rest)\n',
 'nested_store_order': 'first="old first"\n'
                       'rest="old rest"\n'
                       'last="old last"\n'
                       'def item(x):\n'
                       ' print(first,rest,last,x)\n'
                       ' return x\n'
                       'first,(*rest,last)=(7,map(item,[2,3]))\n'
                       'print(first,rest,last)\n',
 'too_few_empty': 'first,*rest,last=()\nprint(first,rest,last)\n',
 'too_few_prefix': 'first,second,*rest,last=[1,2]\n'
                   'print(first,second,rest,last)\n',
 'invalid_none': 'first,*rest=None\nprint(first,rest)\n',
 'invalid_integer': 'first,*rest=7\nprint(first,rest)\n',
 'invalid_plain_object': 'class Plain:pass\n'
                         'first,*rest=Plain()\n'
                         'print(first,rest)\n',
 'text': 'first,*rest,last="abcd"\nprint(first,rest,last)\n',
 'unicode_text': 'first,*rest,last="あいうえ"\nprint(first,rest,last)\n',
 'bytes': 'first,*rest,last=b"abcd"\nprint(first,rest,last)\n',
 'list_item_identity': 'a=[1]\n'
                       'b=[2]\n'
                       'c=[3]\n'
                       'first,*rest,last=(a,b,c)\n'
                       'rest[0].append(9)\n'
                       'print(a,b,c,first is a,last is c,rest)\n',
 'live_source_mutation': 'values=[1,2]\n'
                         'def item(x):\n'
                         ' if x==1:values.append(3)\n'
                         ' return x\n'
                         'first,*rest=map(item,values)\n'
                         'print(first,rest,values)\n',
 'strict_zip_error': 'first,*rest=zip([1,2],[3],strict=True)\n'
                     'print(first,rest)\n',
 'invalid_map_integer': 'first,*rest=map(int,["1","invalid"])\n'
                        'print(first,rest)\n',
 'empty_noncallable_map': 'first,*rest=map(None,[])\nprint(first,rest)\n',
 'noncallable_map': '*rest,=map(None,[1])\nprint(rest)\n',
 'nested_star_target': 'first,*(middle,last)=[1,2,3]\n'
                       'print(first,middle,last)\n',
 'chained_iterator_assignment': 'first,*rest=other,*tail=iter([1,2,3])\n'
                                'print(first,rest,other,tail)\n',
 'finite_source_alternatives': 'def values(flag):\n'
                               ' if flag:return range(4)\n'
                               ' return [9,8,7]\n'
                               'def solve(flag):\n'
                               ' first,*rest,last=values(flag)\n'
                               ' return first,rest,last\n'
                               'print(solve(True),solve(False))\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class StarUnpacking(unittest.TestCase):
    inputs={'map_input':'1 2 3 4\n'}
    def test_map_input(self):self.check('map_input')
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_prefix_rest(self):self.check('prefix_rest')
    def test_rest_tail(self):self.check('rest_tail')
    def test_prefix_rest_tail(self):self.check('prefix_rest_tail')
    def test_only_rest(self):self.check('only_rest')
    def test_empty_rest(self):self.check('empty_rest')
    def test_empty_between(self):self.check('empty_between')
    def test_heterogeneous_tuple(self):self.check('heterogeneous_tuple')
    def test_shared_iterator(self):self.check('shared_iterator')
    def test_source_capture_before_stores(self):self.check('source_capture_before_stores')
    def test_nested_store_order(self):self.check('nested_store_order')
    def test_too_few_empty(self):self.check('too_few_empty')
    def test_too_few_prefix(self):self.check('too_few_prefix')
    def test_invalid_none(self):self.check('invalid_none')
    def test_invalid_integer(self):self.check('invalid_integer')
    def test_invalid_plain_object(self):self.check('invalid_plain_object')
    def test_text(self):self.check('text')
    def test_unicode_text(self):self.check('unicode_text')
    def test_bytes(self):self.check('bytes')
    def test_list_item_identity(self):self.check('list_item_identity')
    def test_live_source_mutation(self):self.check('live_source_mutation')
    def test_strict_zip_error(self):self.check('strict_zip_error')
    def test_invalid_map_integer(self):self.check('invalid_map_integer')
    def test_empty_noncallable_map(self):self.check('empty_noncallable_map')
    def test_noncallable_map(self):self.check('noncallable_map')
    def test_nested_star_target(self):self.check('nested_star_target')
    def test_chained_iterator_assignment(self):self.check('chained_iterator_assignment')
    def test_finite_source_alternatives(self):self.check('finite_source_alternatives')


class StarUnpackingSelection(unittest.TestCase):
    def test_extended_target_is_selected_before_emission(self):
        unit=build_program('a,*rest,z=range(4)\nprint(a,rest,z)\n','star_case.py').main
        selection=select_frames(unit)
        self.assertTrue(selection.required)
        self.assertIn('extended assignment unpacking',selection.reasons)

    def test_reached_function_target_is_selected(self):
        unit=build_program('def values():\n a,*rest=range(4)\n return rest\nprint(values())\n','star_case.py').main
        self.assertIn('extended assignment unpacking',select_frames(unit).reasons)

    def test_unentered_target_keeps_existing_ordinary_selection(self):
        unit=build_program('def unused():\n a,*rest=range(4)\n return rest\nprint(7)\n','star_case.py').main
        self.assertNotIn('extended assignment unpacking',select_frames(unit).reasons)
