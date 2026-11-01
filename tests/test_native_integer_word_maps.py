"""Canonical integer maps retain eager split snapshots and lazy parsing."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'sorted_decimal_words': 'class Box:\n'
                         ' def run(self,text):return '
                         'sorted(map(int,text.split()))\n'
                         'print(Box().run("938100231 -123456789 123456789 0 '
                         '+123456789 1_234_567"))\n',
 'sorted_byte_words': 'class Box:\n'
                      ' def run(self,text):return '
                      'sorted(map(int,text.split()))\n'
                      'print(Box().run(b"938100231 -123456789 +123456789 '
                      '1_234_567"))\n',
 'saved_cursor_alias': 's=map(int,"20 3 11".split())\n'
                       'alias=s\n'
                       'print(next(alias),next(s),list(alias),list(s))\n',
 'canonical_callback_alias': 'parse=int\n'
                             'int=17\n'
                             's=map(parse,"21 4 9".split())\n'
                             'print(sorted(s))\n',
 'canonical_map_alias': 'make=map\n'
                        'map=17\n'
                        's=make(int,"21 4 9".split())\n'
                        'print(sorted(s))\n',
 'later_key_before_parse_error': 'def later():\n'
                                 ' print("key argument")\n'
                                 ' return None\n'
                                 'print(sorted(map(int,"2 bad '
                                 '1".split()),key=later()))\n',
 'all_words_before_key_callbacks': 'def key(v):\n'
                                   ' print("key",v)\n'
                                   ' return -v\n'
                                   'print(sorted(map(int,"2 1 '
                                   '3".split()),key=key))\n',
 'lazy_malformed_word': 's=map(int,"2 bad 1".split())\n'
                        'print("created",next(s))\n'
                        'print(next(s))\n',
 'lazy_empty_bytes': 's=map(int,b"".split())\nprint("created",list(s))\n',
 'empty_text': 's=map(int," \t\r\n".split())\nprint(list(s),next(s,9))\n',
 'explicit_separator': 's=map(int,"2,-7,10".split(","))\nprint(list(s))\n',
 'explicit_byte_separator': 's=map(int,b"2--7--10".split(b"--"))\n'
                            'print(list(s))\n',
 'maxsplit_remainder': 's=map(int,"1  2 3".split(maxsplit=1))\n'
                       'print("created",next(s))\n'
                       'print(next(s))\n',
 'none_separator_and_zero': 's=map(int,"  12  ".split(None,0))\n'
                            'print(list(s))\n',
 'reverse_split_order': 's=map(int,"2,7,10".rsplit(",",1))\n'
                        'print("created")\n'
                        'print(next(s))\n',
 'reverse_split_bytes': 's=map(int,b"2,7,10".rsplit(b","))\nprint(list(s))\n',
 'empty_separator_eager': 's=map(int,"2 1".split(""))\nprint("unreachable")\n',
 'invalid_separator_eager': 's=map(int,"2 1".split(3))\nprint("unreachable")\n',
 'invalid_maxsplit_eager': 's=map(int,"2 1".split(maxsplit=None))\n'
                           'print("unreachable")\n',
 'split_arguments_order': 'def sep():\n'
                          ' print("sep")\n'
                          ' return ","\n'
                          'def limit():\n'
                          ' print("limit")\n'
                          ' return -1\n'
                          's=map(int,"2,1,3".split(sep=sep(),maxsplit=limit()))\n'
                          'print("created",list(s))\n',
 'map_strict_argument_order': 'def strict():\n'
                              ' print("strict")\n'
                              ' return True\n'
                              's=map(int,"2 1 3".split(),strict=strict())\n'
                              'print("created",list(s))\n',
 'source_binding_snapshot': 'text="2 1 3"\n'
                            's=map(int,text.split())\n'
                            'text="999"\n'
                            'print(list(s),text)\n',
 'mutable_saved_list_not_snapshotted': 'words="2 1 3".split()\n'
                                       's=map(int,words)\n'
                                       'words[0]="9"\n'
                                       'print(list(s),words)\n',
 'source_function_capture': 'def text():\n'
                            ' print("source")\n'
                            ' return "2 1 3"\n'
                            's=map(int,text().split())\n'
                            'print("created",list(s))\n',
 'source_effect_rebinds_int': 'def text():\n'
                              ' global int\n'
                              ' int=str\n'
                              ' print("source")\n'
                              ' return "2 1 3"\n'
                              's=map(int,text().split())\n'
                              'print("created",list(s))\n',
 'mixed_callback_preserved': 'def convert(parse):return list(map(parse,"2 1 '
                             '3".split()))\n'
                             'print(convert(int),convert(lambda x:x+"!"))\n',
 'nested_consumers': 's=map(int,"2 1 3".split())\n'
                     'print(sum(s),list(s))\n'
                     'print(list(zip(map(int,"2 1 3".split()),range(3))))\n',
 'unicode_decimal_whitespace': 's=map(int,"１２\u3000-٣٤\xa0५६".split())\n'
                               'print(sorted(s))\n',
 'unicode_explicit_separator': 's=map(int,"１２界٣٤界५६".split("界"))\n'
                               'print(list(s))\n'}

CASES.update({'empty_text_escaped': 's=map(int," \\t\\r\\n".split())\n'
                       'print(list(s),next(s,9))\n'})

CASES.update({'ordinary_sorted_default_error': 'print(sorted(map(int,"2 bad 1".split())))\n',
 'ordinary_sorted_none_error': 'print(sorted(map(int,"2 bad '
                               '1".split()),key=None))\n',
 'ordinary_list_error': 'print(list(map(int,"2 bad 1".split())))\n',
 'ordinary_tuple_error': 'print(tuple(map(int,"2 bad 1".split())))\n',
 'ordinary_unpack_error': 'a,b,c=map(int,"2 bad 1".split())\nprint(a,b,c)\n',
 'ordinary_sum_error': 'print(sum(map(int,"2 bad 1".split())))\n',
 'ordinary_max_error': 'print(max(map(int,"2 bad 1".split())))\n',
 'ordinary_for_error': 'for value in map(int,"2 bad 1".split()):print(value)\n',
 'ordinary_comprehension_error': 'print([value for value in map(int,"2 bad '
                                 '1".split())])\n',
 'ordinary_any_error': 'print(any(map(int,"0 bad 1".split())))\n',
 'ordinary_any_short_circuit': 'print(any(map(int,"1 bad 1".split())))\n',
 'ordinary_all_error': 'print(all(map(int,"2 bad 1".split())))\n',
 'ordinary_byte_error': 'print(list(map(int,b"2 bad 1".split())))\n',
 'ordinary_long_invalid': "print(list(map(int,('9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999bad').split())))\n",
 'unicode_ordinary_invalid': 'print(list(map(int,"１２ ٣٤x ५६".split())))\n'})

CASES.update({'unused_map_type_query_no_parse': 's=map(int,"bad".split())\n'
                                   'print("created",isinstance(s,map),iter(s) '
                                   'is s)\n',
 'same_family_distinct_invocations': 'def words(text):return '
                                     'map(int,text.split())\n'
                                     'a=words("2 4")\n'
                                     'b=words("7 9")\n'
                                     'print(next(a),next(b),list(a),list(b))\n',
 'mixed_text_byte_source_family': 'def words(text):return '
                                  'list(map(int,text.split()))\n'
                                  'print(words("2 4"),words(b"7 9"))\n',
 'canonical_builtin_alternative_preserved': 'def custom(parse,source):return '
                                            'iter([99])\n'
                                            'def use(make):return '
                                            'list(make(int,"2 4".split()))\n'
                                            'print(use(map),use(custom))\n',
 'list_append_generator_consumer': 'def words(text):return '
                                   'map(int,text.split())\n'
                                   'print([x*x for x in words("2 4 7")])\n'})

@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class IntegerWordMaps(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_sorted_decimal_words(self):
        self.check('sorted_decimal_words')

    def test_sorted_byte_words(self):
        self.check('sorted_byte_words')

    def test_saved_cursor_alias(self):
        self.check('saved_cursor_alias')

    def test_canonical_callback_alias(self):
        self.check('canonical_callback_alias')

    def test_canonical_map_alias(self):
        self.check('canonical_map_alias')

    def test_later_key_before_parse_error(self):
        self.check('later_key_before_parse_error')

    def test_all_words_before_key_callbacks(self):
        self.check('all_words_before_key_callbacks')

    def test_lazy_malformed_word(self):
        self.check('lazy_malformed_word')

    def test_lazy_empty_bytes(self):
        self.check('lazy_empty_bytes')

    def test_empty_text(self):
        from py2fastrust import transpile
        result=transpile(CASES['empty_text'])
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E001')

    def test_explicit_separator(self):
        self.check('explicit_separator')

    def test_explicit_byte_separator(self):
        self.check('explicit_byte_separator')

    def test_maxsplit_remainder(self):
        self.check('maxsplit_remainder')

    def test_none_separator_and_zero(self):
        self.check('none_separator_and_zero')

    def test_reverse_split_order(self):
        self.check('reverse_split_order')

    def test_reverse_split_bytes(self):
        self.check('reverse_split_bytes')

    def test_empty_separator_eager(self):
        self.check('empty_separator_eager')

    def test_invalid_separator_eager(self):
        self.check('invalid_separator_eager')

    def test_invalid_maxsplit_eager(self):
        self.check('invalid_maxsplit_eager')

    def test_split_arguments_order(self):
        self.check('split_arguments_order')

    def test_map_strict_argument_order(self):
        self.check('map_strict_argument_order')

    def test_source_binding_snapshot(self):
        self.check('source_binding_snapshot')

    def test_mutable_saved_list_not_snapshotted(self):
        self.check('mutable_saved_list_not_snapshotted')

    def test_source_function_capture(self):
        self.check('source_function_capture')

    def test_source_effect_rebinds_int(self):
        self.check('source_effect_rebinds_int')

    def test_mixed_callback_preserved(self):
        self.check('mixed_callback_preserved')

    def test_nested_consumers(self):
        self.check('nested_consumers')

    def test_unicode_decimal_whitespace(self):
        self.check('unicode_decimal_whitespace')

    def test_unicode_explicit_separator(self):
        self.check('unicode_explicit_separator')


    def test_empty_text_escaped(self):
        self.check('empty_text_escaped')

    def test_ordinary_sorted_default_error(self):
        self.check('ordinary_sorted_default_error')

    def test_ordinary_sorted_none_error(self):
        self.check('ordinary_sorted_none_error')

    def test_ordinary_list_error(self):
        self.check('ordinary_list_error')

    def test_ordinary_tuple_error(self):
        self.check('ordinary_tuple_error')

    def test_ordinary_unpack_error(self):
        self.check('ordinary_unpack_error')

    def test_ordinary_sum_error(self):
        self.check('ordinary_sum_error')

    def test_ordinary_max_error(self):
        self.check('ordinary_max_error')

    def test_ordinary_for_error(self):
        self.check('ordinary_for_error')

    def test_ordinary_comprehension_error(self):
        self.check('ordinary_comprehension_error')

    def test_ordinary_any_error(self):
        self.check('ordinary_any_error')

    def test_ordinary_any_short_circuit(self):
        self.check('ordinary_any_short_circuit')

    def test_ordinary_all_error(self):
        self.check('ordinary_all_error')

    def test_ordinary_byte_error(self):
        self.check('ordinary_byte_error')

    def test_ordinary_long_invalid(self):
        self.check('ordinary_long_invalid')

    def test_unicode_ordinary_invalid(self):
        self.check('unicode_ordinary_invalid')


    def test_unused_map_type_query_no_parse(self):
        self.check('unused_map_type_query_no_parse')

    def test_same_family_distinct_invocations(self):
        self.check('same_family_distinct_invocations')

    def test_mixed_text_byte_source_family(self):
        self.check('mixed_text_byte_source_family')

    def test_canonical_builtin_alternative_preserved(self):
        self.check('canonical_builtin_alternative_preserved')

    def test_list_append_generator_consumer(self):
        self.check('list_append_generator_consumer')

