"""Builtin collectors execute original generator scopes as direct native loops."""
import unittest
import test_native_class_iterators as iterator_tests

CASES={'all_stops_before_error': 'class Marker:pass\nprint(all(10//value==5 for value in [1,0]))\n',
 'any_stops_before_error': 'class Marker:pass\nprint(any(10//value==10 for value in [1,0]))\n',
 'body_error_frames': 'class Marker:pass\n'
                      'def divide(value):\n'
                      ' print(value)\n'
                      ' return 10//value\n'
                      'print(sum(divide(value) for value in [1,0]))\n',
 'eager_list_collector': 'class Marker:pass\n'
                         'values=[1,2,3]\n'
                         'print(list(value*2 for value in values))\n',
 'empty_max_error': 'class Marker:pass\nprint(max(value for value in range(0)))\n',
 'filter_error_frames': 'class Marker:pass\nprint(sum(value for value in [1,0] if 10//value))\n',
 'first_source_and_later_arguments': 'class Marker:pass\n'
                                     'def source():\n'
                                     ' print("source")\n'
                                     ' return [1,2]\n'
                                     'def mark(value):\n'
                                     ' print("body",value)\n'
                                     ' return value\n'
                                     'def later():\n'
                                     ' print("later")\n'
                                     ' return 10\n'
                                     'print(sum((mark(value) for value in source()),later()))\n',
 'first_source_error_no_generator_frame': 'class Marker:pass\n'
                                          'def bad():return 1//0\n'
                                          'print(sum(value for value in bad()))\n',
 'first_source_retains_handle': 'class Box:\n'
                                ' def __init__(self):self.values=[1,2]\n'
                                'box=Box()\n'
                                'def later():\n'
                                ' box.values=[9]\n'
                                ' print("later")\n'
                                ' return 10\n'
                                'print(sum((value for value in box.values),later()),box.values)\n',
 'free_variable_delete': 'class Marker:pass\n'
                         'def run():\n'
                         ' value=3\n'
                         ' del value\n'
                         ' return sum(value for unused in range(1))\n'
                         'print(run())\n',
 'generator_stop_iteration_conversion': 'class Marker:pass\n'
                                        'source=iter([1])\n'
                                        'print(sum(next(source) for unused in range(3)))\n',
 'max_min_collectors': 'class Marker:pass\n'
                       'print(max(a+b for a in range(3) for b in range(4)))\n'
                       'print(min(value*value for value in [-3,-1,2]))\n',
 'nested_clauses_filters': 'class Marker:pass\n'
                           'print(sum(a*b for a in range(4) if a%2 for b in range(3) if b>a-2))\n',
 'nested_generator_consumers': 'class Marker:pass\n'
                               'print(sum(sum(a*b for b in range(3)) for a in range(4)))\n',
 'recursive_callback_future': 'class Marker:pass\n'
                              'def fib(value):\n'
                              ' if value<2:return value\n'
                              ' return fib(value-1)+fib(value-2)\n'
                              'print(sum(fib(value) for value in range(8)))\n',
 'sum_class_field': 'class Box:\n'
                    ' def __init__(self):self.scale=3\n'
                    'box=Box()\n'
                    'print(sum(value*box.scale for value in range(5)))\n'}

CASES.update({'builtin_alias_consumer': 'class Marker:pass\n'
                           'reduce=sum\n'
                           'sum=7\n'
                           'print(reduce(value for value in [1,2,3]),sum)\n',
 'empty_min_error': 'class Marker:pass\nprint(min(value for value in ()))\n',
 'empty_next_error': 'class Marker:pass\nprint(next(value for value in ()))\n',
 'empty_sum_boolean_start': 'class Marker:pass\n'
                            'print(sum((value for value in ()),True),sum(value for value in ()))\n',
 'method_varargs_generator': 'class Values:\n'
                             ' def collect(self,*values):return list(value+1 for value in values)\n'
                             'item=Values()\n'
                             'print(item.collect(1,2),item.collect())\n',
 'next_default_and_short_circuit': 'class Marker:pass\n'
                                   'source=iter([1,2,3])\n'
                                   'print(next((a+b for a in source for b in '
                                   '[10,20]),99),next(source))\n'
                                   'print(next((value for value in ()),99))\n',
 'unicode_generator_text': 'class Marker:pass\nprint(max(value+value for value in "猫😀é"))\n',
 'varargs_generator_sources': 'def total(*values):return sum(value*2 for value in values)\n'
                              'print(total(),total(1,2),total(3,4,5))\n'})

class ImmediateGeneratorTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_empty_next_text_aliases_and_varargs(self):
        for name in ('empty_sum_boolean_start','empty_min_error','next_default_and_short_circuit','empty_next_error','unicode_generator_text','builtin_alias_consumer','varargs_generator_sources','method_varargs_generator'):
            with self.subTest(name=name):self.check(name)

    def test_collectors_and_short_circuit(self):
        for name in ('sum_class_field','nested_clauses_filters','any_stops_before_error','all_stops_before_error','eager_list_collector','max_min_collectors','empty_max_error'):
            with self.subTest(name=name):self.check(name)

    def test_construction_and_late_body_order(self):
        for name in ('first_source_retains_handle','first_source_and_later_arguments','nested_generator_consumers'):
            with self.subTest(name=name):self.check(name)

    def test_error_locations_and_original_free_cells(self):
        for name in ('body_error_frames','filter_error_frames','first_source_error_no_generator_frame','free_variable_delete','generator_stop_iteration_conversion'):
            with self.subTest(name=name):self.check(name)

    def test_recursive_callback_uses_compiled_future(self):
        self.check('recursive_callback_future')

if __name__=='__main__':unittest.main()
