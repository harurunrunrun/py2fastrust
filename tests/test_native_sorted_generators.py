"""Canonical sorted consumes original generator expressions directly."""
import shutil
import unittest
import test_native_class_iterators as iterator_tests

CASES={'integer_order': 'print(sorted(v * 3 for v in [3,1,2]))\n',
 'empty_generator': 'print(sorted(v for v in []))\n',
 'filtered_nested': 'print(sorted(a-b for a in range(4) for b in range(3) if '
                    '(a+b)%2))\n',
 'string_prefix_style': 'words=["pear","apple","apricot"]\n'
                        'print(sorted(word.strip() for word in words))\n',
 'canonical_alias': 'order=sorted\n'
                    'sorted=3\n'
                    'print(order(v+1 for v in [2,0,1]))\n',
 'key_argument_capture': 'def key(v):\n'
                         ' print("key",v)\n'
                         ' return -v\n'
                         'def later():\n'
                         ' print("later")\n'
                         ' return key\n'
                         'def item(v):\n'
                         ' print("item",v)\n'
                         ' return v\n'
                         'print(sorted((item(v) for v in '
                         '[2,1,3]),key=later()))\n',
 'tuple_key_stability': 'print(sorted(((v%2,v) for v in [3,2,1,4]),key=lambda '
                        'pair:pair[0]))\n',
 'reverse': 'print(sorted((v for v in [2,1,3]),reverse=True))\n',
 'reverse_effect_order': 'def item(v):\n'
                         ' print("item",v)\n'
                         ' return v\n'
                         'def rev():\n'
                         ' print("reverse")\n'
                         ' return True\n'
                         'print(sorted((item(v) for v in '
                         '[2,1]),reverse=rev()))\n',
 'mutable_items_keep_identity': 'a=[3]\n'
                                'b=[1]\n'
                                'rows=sorted((v for v in [a,b]),key=lambda '
                                'item:item[0])\n'
                                'rows[1].append(7)\n'
                                'print(a,b,rows,rows[1] is a)\n',
 'later_argument_source_growth': 'rows=[2,1]\n'
                                 'def later():\n'
                                 ' rows.append(3)\n'
                                 ' return None\n'
                                 'print(sorted((v for v in '
                                 'rows),key=later()),rows)\n',
 'body_error': 'print(sorted(8//v for v in [2,0,1]))\n',
 'key_error_after_all_items': 'def item(v):\n'
                              ' print("item",v)\n'
                              ' return v\n'
                              'def key(v):\n'
                              ' print("key",v)\n'
                              ' return 1//v\n'
                              'print(sorted((item(v) for v in '
                              '[1,0,2]),key=key))\n',
 'body_stopiteration_pep479': 'def item(v):\n'
                              ' print("item",v)\n'
                              ' raise StopIteration("body")\n'
                              'print(sorted(item(v) for v in [1,2]))\n',
 'key_stopiteration_propagates': 'def key(v):\n'
                                 ' print("key",v)\n'
                                 ' raise StopIteration("key")\n'
                                 'print(sorted((v for v in [2,1]),key=key))\n',
 'unused_key_empty': 'print(sorted((v for v in []),key=3))\n',
 'noncallable_key': 'def item(v):\n'
                    ' print("item",v)\n'
                    ' return v\n'
                    'print(sorted((item(v) for v in [2,1]),key=3))\n',
 'invalid_keyword': 'def item(v):\n'
                    ' print("item",v)\n'
                    ' return v\n'
                    'print(sorted((item(v) for v in [2,1]),unknown=3))\n',
 'extra_positional': 'def item(v):\n'
                     ' print("item",v)\n'
                     ' return v\n'
                     'print(sorted((item(v) for v in [2,1]),3))\n',
 'source_creation_precedes_arguments': 'def source():\n'
                                       ' print("source")\n'
                                       ' return [2,1]\n'
                                       'def later():\n'
                                       ' print("later")\n'
                                       ' return None\n'
                                       'print(sorted((v for v in '
                                       'source()),key=later()))\n'}

CASES.update({'body_builtin_stopiteration_pep479': 'def item(v):\n'
                                      ' print("item",v)\n'
                                      ' return next(iter([]))\n'
                                      'print(sorted(item(v) for v in [1,2]))\n',
 'key_builtin_stopiteration_propagates': 'def key(v):\n'
                                         ' print("key",v)\n'
                                         ' return next(iter([]))\n'
                                         'print(sorted((v for v in '
                                         '[2,1]),key=key))\n'})

CASES.update({'captured_text_reader': 'import sys\n'
                         'def main():\n'
                         ' read=sys.stdin.readline\n'
                         ' print(sorted(read().strip() for _ in range(2)))\n'
                         'main()\n',
 'captured_byte_reader': 'import sys\n'
                         'def main():\n'
                         ' read=sys.stdin.buffer.readline\n'
                         ' print(sorted(read().strip() for _ in range(2)))\n'
                         'main()\n',
 'captured_reader_function': 'import sys\n'
                             'def main():\n'
                             ' read=sys.stdin.readline\n'
                             ' def get():return read()\n'
                             ' print(sorted(get() for _ in range(2)))\n'
                             'main()\n',
 'captured_stream_alias': 'import sys\n'
                          'def main():\n'
                          ' stream=sys.stdin\n'
                          ' print(sorted(stream.readline() for _ in '
                          'range(2)))\n'
                          'main()\n',
 'captured_read_all': 'import sys\n'
                      'def main():\n'
                      ' read=sys.stdin.read\n'
                      ' print(sorted(read() for _ in range(2)))\n'
                      'main()\n',
 'captured_reader_later_rebind': 'import sys\n'
                                 'def main():\n'
                                 ' read=sys.stdin.readline\n'
                                 ' def later():\n'
                                 '  nonlocal read\n'
                                 '  read=sys.stdin.read\n'
                                 '  return None\n'
                                 ' print(sorted((read() for _ in '
                                 'range(2)),key=later()))\n'
                                 'main()\n'})

@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class SortedGenerators(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_integer_order(self):
        self.check('integer_order')

    def test_empty_generator(self):
        self.check('empty_generator')

    def test_filtered_nested(self):
        self.check('filtered_nested')

    def test_string_prefix_style(self):
        self.check('string_prefix_style')

    def test_canonical_alias(self):
        self.check('canonical_alias')

    def test_key_argument_capture(self):
        self.check('key_argument_capture')

    def test_tuple_key_stability(self):
        self.check('tuple_key_stability')

    def test_reverse(self):
        self.check('reverse')

    def test_reverse_effect_order(self):
        self.check('reverse_effect_order')

    def test_mutable_items_keep_identity(self):
        self.check('mutable_items_keep_identity')

    def test_later_argument_source_growth(self):
        self.check('later_argument_source_growth')

    def test_body_error(self):
        self.check('body_error')

    def test_key_error_after_all_items(self):
        self.check('key_error_after_all_items')

    def test_body_stopiteration_pep479(self):
        self.check_unimplemented_raise('body_stopiteration_pep479')

    def test_key_stopiteration_propagates(self):
        self.check_unimplemented_raise('key_stopiteration_propagates')

    def test_unused_key_empty(self):
        self.check('unused_key_empty')

    def test_noncallable_key(self):
        self.check('noncallable_key')

    def test_invalid_keyword(self):
        self.check('invalid_keyword')

    def test_extra_positional(self):
        self.check('extra_positional')

    def test_source_creation_precedes_arguments(self):
        self.check('source_creation_precedes_arguments')


    def check_unimplemented_raise(self,name):
        from py2fastrust import transpile, TranspileOptions
        for mode in ("i64","i128","bigint"):
            result=transpile(CASES[name],TranspileOptions(integer=mode,license="none"))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=="E006" and "raise" in d.message for d in result.diagnostics),result.diagnostics)

    def test_body_builtin_stopiteration_pep479(self):
        self.check('body_builtin_stopiteration_pep479')

    def test_key_builtin_stopiteration_propagates(self):
        self.check('key_builtin_stopiteration_propagates')


    def test_captured_text_reader(self):
        self.check('captured_text_reader')

    def test_captured_byte_reader(self):
        self.check('captured_byte_reader')

    def test_captured_reader_function(self):
        self.check('captured_reader_function')

    def test_captured_stream_alias(self):
        self.check('captured_stream_alias')

    def test_captured_read_all(self):
        self.check('captured_read_all')

    def test_captured_reader_later_rebind(self):
        from py2fastrust import transpile, TranspileOptions
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['captured_reader_later_rebind'],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code=='E006' and 'callable' in d.message and 'read_text' in d.message for d in result.diagnostics),result.diagnostics)

