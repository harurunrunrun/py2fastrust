"""Text and byte joins consume concrete cursors with Python ordering."""
import unittest,shutil
from py2fastrust import transpile,TranspileOptions
import test_native_class_iterators as iterator_tests
CASES={'join_int_map': 'values=[3,-1,12]\nprint(" ".join(map(str,values)))\n',
 'join_saved_map': 'it=map(str,[1,2,3])\n'
                   'other=it\n'
                   'print(next(other))\n'
                   'print("|".join(it))\n'
                   'print(list(other))\n',
 'join_list_iterator': 'parts=["a","bb","c"]\n'
                       'it=iter(parts)\n'
                       'print(next(it))\n'
                       'print("/".join(it))\n',
 'join_tuple': 'print("|".join(("a","bb","c")))\n',
 'join_text_iterator': 'print("|".join("abc"))\n',
 'join_empty_map_noncallable': 'print(repr("|".join(map(7,[]))))\n',
 'join_callback_effects': 'def word(value):\n'
                          ' print(value,end="|")\n'
                          ' return str(value)\n'
                          'print(":".join(map(word,[1,2,3])))\n',
 'join_wrong_first_consumes_all': 'def word(value):\n'
                                  ' print(value,end="|")\n'
                                  ' return value\n'
                                  'print(":".join(map(word,[1,2,3])))\n',
 'join_later_callback_error_wins': 'def word(value):\n'
                                   ' print(value,end="|")\n'
                                   ' if value==3:raise ValueError("late '
                                   'callback")\n'
                                   ' return value\n'
                                   'print(":".join(map(word,[1,2,3])))\n',
 'join_transient_callback_stop': 'def word(value):\n'
                                 ' print(value,end="|")\n'
                                 ' if value==2:raise StopIteration\n'
                                 ' return str(value)\n'
                                 'it=map(word,[1,2,3])\n'
                                 'print(":".join(it))\n'
                                 'print(next(it))\n',
 'join_immediate_generator': 'print("|".join(str(value*value)for value in '
                             'range(5)))\n',
 'join_nested_generator': 'from itertools import chain\n'
                          'values=chain([1,2],[3,4])\n'
                          'print("|".join(str(a+b)for a in values for b in '
                          'range(2)if(a+b)%2))\n',
 'join_generator_callback_stop': 'def word(value):\n'
                                 ' print(value,end="|")\n'
                                 ' if value==2:raise StopIteration\n'
                                 ' return str(value)\n'
                                 'print(":".join(word(value)for value in '
                                 'range(4)))\n',
 'join_bad_generator_late_error': 'def word(value):\n'
                                  ' print(value,end="|")\n'
                                  ' if value==3:raise ValueError("late '
                                  'generator")\n'
                                  ' return value\n'
                                  'print(":".join(word(value)for value in '
                                  'range(4)))\n',
 'join_receiver_captured': 'separator="|"\n'
                           'def source():\n'
                           ' global separator\n'
                           ' separator="/"\n'
                           ' print("source")\n'
                           ' return map(str,[1,2,3])\n'
                           'print(separator.join(source()))\n'
                           'print(separator)\n',
 'join_live_source_list': 'values=[1]\n'
                          'def word(value):\n'
                          ' if value==1:values.append(2)\n'
                          ' return str(value)\n'
                          'print("|".join(map(word,values)))\n'
                          'print(values)\n',
 'join_empty_list': 'print(repr("|".join([])))\n',
 'join_empty_tuple': 'print(repr("|".join(())))\n',
 'join_noniterable': 'print("|".join(7))\n',
 'join_text_bytes_error': 'print("|".join(["a",b"b","c"]))\n',
 'join_object_error': 'class Item:pass\nprint("|".join(["a",Item(),"c"]))\n',
 'join_bytes_list': 'print(b"|".join([b"a",b"bb",b"c"]))\n',
 'join_bytes_tuple': 'print(b"|".join((b"a",b"bb",b"c")))\n',
 'join_bytes_iterator': 'from itertools import chain\n'
                        'print(b"|".join(chain([b"a"],[b"bb",b"c"])))\n',
 'join_bytes_text_error': 'print(b"|".join([b"a","b",b"c"]))\n',
 'join_bytes_integers_error': 'print(b"|".join([1,2,3]))\n',
 'join_bytes_generator': 'from itertools import repeat\n'
                         'print(b"/".join(value for value in '
                         'repeat(b"a",3)))\n',
 'join_dict_keys': 'from collections import Counter\n'
                   'counts=Counter(["b","a","b"])\n'
                   'print("|".join(counts))\n',
 'join_no_arguments': 'print("|".join())\n',
 'join_excess_arguments': 'def mark(value):\n'
                          ' print(value)\n'
                          ' return value\n'
                          'print("|".join(mark(["a"]),mark(["b"])))\n',
 'join_keyword_argument': 'def mark(value):\n'
                          ' print(value)\n'
                          ' return value\n'
                          'print("|".join(iterable=mark(["a"])))\n',
 'join_bad_arity_no_pull': 'def word(value):\n'
                           ' print("pull")\n'
                           ' return str(value)\n'
                           'print("|".join(map(word,[1,2]),7))\n',
 'join_keyword_generator_no_body': 'from itertools import repeat\n'
                                   'def word(value):\n'
                                   ' print("body")\n'
                                   ' return value\n'
                                   'print("|".join(iterable=(word(value)for '
                                   'value in repeat("a",2))))\n',
 'join_function_receiver_generator': 'from itertools import repeat\n'
                                     'def separator():\n'
                                     ' print("separator")\n'
                                     ' return "|"\n'
                                     'print(separator().join(value for value '
                                     'in repeat("a",2)))\n',
 'unicode_join_map': 'from itertools import chain\n'
                     'print("・".join(map(str,chain([1,2],[3]))))\n',
 'unicode_join_characters': 'from itertools import chain\n'
                            'print("・".join(chain("あβ","😀")))\n',
 'join_mixed_receivers_text': 'from itertools import chain\n'
                              'flag=int(input())\n'
                              'separator="|"if flag else b"/"\n'
                              'parts=["a","b"]if flag else[b"a",b"b"]\n'
                              'print(separator.join(chain(parts)))\n',
 'join_mixed_receivers_bytes': 'from itertools import chain\n'
                               'flag=int(input())\n'
                               'separator="|"if flag else b"/"\n'
                               'parts=["a","b"]if flag else[b"a",b"b"]\n'
                               'print(separator.join(chain(parts)))\n'}
INPUTS={'join_mixed_receivers_text': '1\n', 'join_mixed_receivers_bytes': '0\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class TextJoinExecution(unittest.TestCase):
    cases=CASES
    inputs=INPUTS
    check=iterator_tests.IteratorExecutionTests.check
    def test_join_int_map(self):self.check('join_int_map')
    def test_join_saved_map(self):self.check('join_saved_map')
    def test_join_list_iterator(self):self.check('join_list_iterator')
    def test_join_tuple(self):self.check('join_tuple')
    def test_join_text_iterator(self):self.check('join_text_iterator')
    def test_join_empty_map_noncallable(self):self.check('join_empty_map_noncallable')
    def test_join_callback_effects(self):self.check('join_callback_effects')
    def test_join_wrong_first_consumes_all(self):self.check('join_wrong_first_consumes_all')
    def test_join_immediate_generator(self):self.check('join_immediate_generator')
    def test_join_nested_generator(self):self.check('join_nested_generator')
    def test_join_receiver_captured(self):self.check('join_receiver_captured')
    def test_join_live_source_list(self):self.check('join_live_source_list')
    def test_join_empty_list(self):self.check('join_empty_list')
    def test_join_empty_tuple(self):self.check('join_empty_tuple')
    def test_join_noniterable(self):self.check('join_noniterable')
    def test_join_text_bytes_error(self):self.check('join_text_bytes_error')
    def test_join_object_error(self):self.check('join_object_error')
    def test_join_bytes_list(self):self.check('join_bytes_list')
    def test_join_bytes_tuple(self):self.check('join_bytes_tuple')
    def test_join_bytes_iterator(self):self.check('join_bytes_iterator')
    def test_join_bytes_text_error(self):self.check('join_bytes_text_error')
    def test_join_bytes_integers_error(self):self.check('join_bytes_integers_error')
    def test_join_bytes_generator(self):self.check('join_bytes_generator')
    def test_join_dict_keys(self):self.check('join_dict_keys')
    def test_join_no_arguments(self):self.check('join_no_arguments')
    def test_join_excess_arguments(self):self.check('join_excess_arguments')
    def test_join_keyword_argument(self):self.check('join_keyword_argument')
    def test_join_bad_arity_no_pull(self):self.check('join_bad_arity_no_pull')
    def test_join_keyword_generator_no_body(self):self.check('join_keyword_generator_no_body')
    def test_join_function_receiver_generator(self):self.check('join_function_receiver_generator')
    def test_unicode_join_map(self):self.check('unicode_join_map')
    def test_unicode_join_characters(self):self.check('unicode_join_characters')
    def test_join_mixed_receivers_text(self):self.check('join_mixed_receivers_text')
    def test_join_mixed_receivers_bytes(self):self.check('join_mixed_receivers_bytes')

class TextJoinRaisedErrors(unittest.TestCase):
    def test_original_explicit_raise_witnesses_have_complete_errors(self):
        import test_native_explicit_raise as raise_tests
        for name in ('join_later_callback_error_wins', 'join_transient_callback_stop', 'join_generator_callback_stop', 'join_bad_generator_late_error'):
            with self.subTest(name=name):
                raise_tests.NativeRaiseExecutionTests.exercise(self,CASES[name],'')
