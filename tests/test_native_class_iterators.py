"""Lazy compiled iterator states preserve Python pull order and shared identity."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_class_capabilities import frame_storable,shared_tuple_storage
from py2fastrust.native_class_iterators import IteratorType,Iterators
from py2fastrust.native_classes import Model,Cell,merge
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_types import EMPTY,ListType,TupleType
from types import SimpleNamespace

CASES={'bool_callback_and_shortcircuit': 'keep=bool\n'
                                   'values=filter(keep,[0,1,2])\n'
                                   'print(any(values),list(values))\n',
 'builtin_filter_predicate_empty': 'print(list(filter(filter,[])))\n',
 'builtin_filter_predicate_nonempty': 'print(list(filter(filter,[1])))\n',
 'bytes_cursor': 'class Box:\n'
                 ' def choose(self,text):return list(filter(None,text))\n'
                 "print(Box().choose(b'\\x00a\\xff'))\n",
 'callback_append_mutation': 'values=[1,2]\n'
                             'def keep(value):\n'
                             ' if value<4:values.append(value+2)\n'
                             ' return value%2\n'
                             'print(list(filter(keep,values)))\n'
                             'print(values)\n',
 'callback_clear_mutation': 'values=[1,2,3]\n'
                            'def keep(value):\n'
                            ' values.clear()\n'
                            ' return True\n'
                            'print(list(filter(keep,values)))\n'
                            'print(values)\n',
 'callback_exception_line': 'def keep(value):\n'
                            " print('call',value)\n"
                            ' return 1//value\n'
                            'values=filter(keep,[2,0,3])\n'
                            "print('created')\n"
                            'print(list(values))\n',
 'callback_returns_mutable_truth': 'def keep(value):return [value] if value%2 else []\n'
                                   'print(list(filter(keep,[0,1,2,3])))\n',
 'class_none_filter': 'class Box:\n'
                      ' def __init__(self):self.values=[0,1,2,0,3]\n'
                      ' def choose(self):return list(filter(None,self.values))\n'
                      'print(Box().choose())\n',
 'empty_iterator_result_joins': 'values=filter(None,())\n'
                                'items=list(values)\n'
                                "items.append('kept')\n"
                                "print(items,next(values,'done'))\n",
 'enumerated_callback_updates_fields': 'class Box:\n'
                                       ' def __init__(self):self.value=0\n'
                                       'box=Box()\n'
                                       'def update(value):\n'
                                       ' box.value+=value\n'
                                       ' return True\n'
                                       'for index,value in enumerate(filter(update,[1,2,3])):\n'
                                       ' print(index,value,box.value)\n',
 'filter_function_name_shadow': 'def filter(callback,values):return [9]\n'
                                'print(filter(None,[1,2]))\n',
 'invalid_predicate_arity_empty': 'def keep(left,right):return True\n'
                                  'print(list(filter(keep,[])))\n',
 'invalid_predicate_arity_nonempty': 'def keep(left,right):return True\n'
                                     'print(list(filter(keep,[1])))\n',
 'invalid_source_argument_effects': 'def mark(label,value):\n'
                                    ' print(label)\n'
                                    ' return value\n'
                                    "values=filter(mark('callback',None),mark('source',3))\n"
                                    "print('unreachable')\n",
 'iteration_shared_cursor': 'values=filter(None,[0,1,2,3])\n'
                            'for value in values:\n'
                            ' print(value)\n'
                            ' if value==1:break\n'
                            'print(list(values))\n',
 'lambda_filter': 'print(list(filter(lambda value:value>2,[1,4,2,5])))\n',
 'len_callback_in_method': 'class Box:\n'
                           " def __init__(self):self.rows=['','a','bc']\n"
                           ' def choose(self):return list(filter(len,self.rows))\n'
                           'print(Box().choose())\n',
 'min_max_consumers': 'def positive(value):return value>0\n'
                      'print(min(filter(positive,[-1,3,2])),max(filter(positive,[1,5,2])))\n',
 'nested_filters_and_reductions': 'def positive(value):return value>0\n'
                                  'values=filter(lambda '
                                  'value:value%2,filter(positive,[-1,0,1,2,3]))\n'
                                  'print(sum(values),list(values))\n',
 'noncallable_empty': "values=filter(3,[])\nprint('created')\nprint(list(values))\n",
 'noncallable_nonempty': "values=filter(3,[1])\nprint('created')\nprint(list(values))\n",
 'range_cursor_and_resume': 'values=filter(None,range(5,-2,-1))\n'
                            'print(next(values),sum(values),list(values))\n',
 'raw_source_shortcircuit_consumers': 'class Decisions:\n'
                                      ' def evaluate(self,values):return any(values),all(values)\n'
                                      'test=Decisions()\n'
                                      'print(test.evaluate([0,1,2]),test.evaluate([]),test.evaluate(()))\n',
 'reentrant_next_releases_borrows': 'def keep(value):\n'
                                    " if value==1:print('inside',next(values,None))\n"
                                    ' return True\n'
                                    'values=filter(keep,[1,2,3])\n'
                                    'print(list(values))\n',
 'saved_callback_binding': 'def yes(value):\n'
                           " print('yes',value)\n"
                           ' return True\n'
                           'def no(value):\n'
                           " print('no',value)\n"
                           ' return False\n'
                           'predicate=yes\n'
                           'values=filter(predicate,[1,2])\n'
                           'predicate=no\n'
                           'print(list(values))\n',
 'saved_filter_builtin': 'choose=filter\n'
                         'filter=3\n'
                         'values=choose(None,[0,1,2])\n'
                         'print(list(values))\n',
 'separate_captured_counter_instances': 'def make(items):\n'
                                        ' count=0\n'
                                        ' def keep(value):\n'
                                        '  nonlocal count\n'
                                        '  count+=1\n'
                                        '  print(count,value)\n'
                                        '  return value%2\n'
                                        ' return filter(keep,items)\n'
                                        'first=make([1,2])\n'
                                        'second=make([3,4])\n'
                                        'print(next(first),next(second))\n'
                                        'print(list(first),list(second))\n',
 'source_function_filter': 'def odd(value):return value%2\nprint(list(filter(odd,range(7))))\n',
 'stored_empty_tuple': 'values=filter(None,())\nprint(list(values),next(values,99))\n',
 'stored_laziness_and_exhaustion': 'def odd(value):\n'
                                   " print('call',value)\n"
                                   ' return value%2\n'
                                   'def source():\n'
                                   " print('source')\n"
                                   ' return [0,1,2,3]\n'
                                   'values=filter(odd,source())\n'
                                   "print('created')\n"
                                   'print(next(values))\n'
                                   'print(list(values))\n'
                                   'print(list(values))\n',
 'stored_none_alias': 'data=[0,1,2]\n'
                      'values=filter(None,data)\n'
                      'other=values\n'
                      'print(iter(values) is values)\n'
                      'print(next(other),next(values))\n'
                      'print(next(other,99))\n'
                      'data.append(7)\n'
                      'print(list(values))\n',
 'tuple_mutable_identity': 'rows=([1],[],[2])\n'
                           'values=list(filter(None,rows))\n'
                           'values[0].append(9)\n'
                           'print(rows,values)\n',
 'unicode_text_cursor': 'class Box:\n'
                        ' def choose(self,text):return list(filter(None,text))\n'
                        "print(Box().choose('猫🐈é'))\n"}

CASES.update({'finite_source_alternatives': 'def collect(source):\n'
                               ' values=filter(None,source)\n'
                               ' return list(values)\n'
                               "print(collect([0,2]),collect((0,3)),collect(range(-1,2)),collect(b'\\x00\\x02'),collect('ab'))\n",
 'source_union_construction_error_order': 'def choose(flag):\n'
                                          ' if flag:return [1,2]\n'
                                          ' return None\n'
                                          'def keep(value):\n'
                                          " print('predicate',value)\n"
                                          ' return value\n'
                                          'def build(flag):\n'
                                          " print('before',flag)\n"
                                          ' stream=filter(keep,choose(flag))\n'
                                          " print('created')\n"
                                          ' return list(stream)\n'
                                          'print(build(True))\n'
                                          'print(build(False))\n',
 'unicode_union_sources': 'def collect(source):\n'
                          ' values=filter(None,source)\n'
                          ' return list(values)\n'
                          "print(collect('a😀é'),collect(['z']),collect(('漢',)))\n"})

CASES.update({'empty_max': 'values=filter(None,())\nprint(max(values))\n',
 'empty_min': 'values=filter(None,())\nprint(min(values))\n',
 'empty_stop_iteration': 'values=filter(None,())\nprint(next(values))\n',
 'empty_sum_and_shortcircuit': 'values=filter(None,())\n'
                               'print(sum(values),any(values),all(values),list(values),next(values,99))\n',
 'sum_boolean_input_values': 'stream=filter(None,[False,True,True])\nprint(sum(stream,True))\n',
 'sum_boolean_start_and_zero_pulls': 'def total(values,start):\n'
                                     ' stream=filter(None,values)\n'
                                     ' return sum(stream,start)\n'
                                     'print(total([],True),total([],False),total([],3),total([1],True),total([2],False),total([1,2],4))\n',
 'sum_boolean_start_immutable_empty': 'values=filter(None,())\n'
                                      'print(sum(values,True),sum(values,False),sum(values,7))\n'})

REFERENCE="""import json,sys
try:exec(compile(sys.argv[1],sys.argv[2],'exec'),{'__name__':'__main__'})
except BaseException as error:
 frames=[];trace=error.__traceback__
 while trace is not None:
  if trace.tb_frame.f_code.co_filename==sys.argv[2]:frames.append((str(trace.tb_lineno),trace.tb_frame.f_code.co_name))
  trace=trace.tb_next
 print(json.dumps({'message':type(error).__name__+(': '+str(error)if str(error)else''),'frames':frames}),file=sys.stderr);sys.exit(1)
"""


class IteratorProofTests(unittest.TestCase):
    def test_original_nodes_and_scope_tables_are_preserved(self):
        unit=parse_source(CASES['stored_laziness_and_exhaustion'],'iterator.py')
        before=ast.dump(unit.tree,include_attributes=True)
        table=unit.table
        model=Model(unit.tree,unit.filename,'i64',(),unit=unit)
        model.run()
        nodes={id(node)for node in ast.walk(unit.tree)}
        self.assertTrue(model.iterators.records)
        self.assertTrue(all(id(record.node)in nodes for record in model.iterators.records))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertIs(unit.table,table)

    def test_storage_preselection_uses_canonical_solved_shapes(self):
        self.assertTrue(select_frames(parse_source('it=filter(None,[1,2])\nprint(next(it))')).required)
        self.assertFalse(select_frames(parse_source('print(sum(filter(None,[1,2])))')).required)
        def analysis(kind):return SimpleNamespace(scopes={0:SimpleNamespace(expressions={0:kind})})
        self.assertTrue(shared_tuple_storage(analysis(TupleType((ListType('str'),)))))
        self.assertFalse(shared_tuple_storage(analysis(TupleType(('str','int')))))
        self.assertTrue(frame_storable(TupleType((ListType('str'),))))
        self.assertTrue(frame_storable(TupleType((ListType(EMPTY),))))

    def test_uninhabited_elements_do_not_invent_an_observable_value_type(self):
        node=ast.parse('[]').body[0]
        left,right=Cell(EMPTY),Cell('str')
        self.assertEqual(merge(left,right,node).tag,'str')
        self.assertEqual(right.root().tag,'str')
        left,right=Cell(),Cell(EMPTY)
        self.assertEqual(merge(left,right,node).tag,EMPTY)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IteratorExecutionTests(unittest.TestCase):
    def check(self,name):
        source=getattr(self,'cases',CASES)[name];filename='iterator_case.py'
        data=getattr(self,'inputs',{}).get(name,'')
        cp=subprocess.run([sys.executable,'-I','-S','-c',REFERENCE,source,filename],input=data,capture_output=True,text=True,timeout=10)
        failure=json.loads(cp.stderr)if cp.returncode else None
        with tempfile.TemporaryDirectory(prefix='pytors-iterator-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
                    result=transpile(source,TranspileOptions(integer=mode,filename=filename,license='none',
                        string_mode='unicode'if name.startswith('unicode')else'ascii'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                self.assertNotIn('.chars().nth(',result.rust_source)
                rust=Path(directory,mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021','--crate-name','iterator_case',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    with self.subTest(name=name,mode=mode,optimized=optimized):
                        self.assertEqual((actual.returncode,actual.stdout),(cp.returncode,cp.stdout),actual.stderr)
                        if failure:
                            self.assertEqual(actual.stderr.splitlines()[-1],failure['message'])
                            self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in failure['frames']])
                        else:self.assertEqual(actual.stderr,'')

    def test_filter_predicates(self):
        for name in ('class_none_filter', 'source_function_filter', 'lambda_filter', 'callback_returns_mutable_truth'):
            with self.subTest(name=name):self.check(name)

    def test_creation_and_shared_exhaustion(self):
        for name in ('stored_laziness_and_exhaustion', 'stored_none_alias', 'iteration_shared_cursor', 'range_cursor_and_resume'):
            with self.subTest(name=name):self.check(name)

    def test_mutation_during_pulls(self):
        for name in ('callback_append_mutation', 'callback_clear_mutation', 'reentrant_next_releases_borrows', 'enumerated_callback_updates_fields'):
            with self.subTest(name=name):self.check(name)

    def test_captured_binding_lifetimes(self):
        for name in ('saved_callback_binding', 'saved_filter_builtin', 'separate_captured_counter_instances', 'filter_function_name_shadow'):
            with self.subTest(name=name):self.check(name)

    def test_deferred_errors(self):
        for name in ('noncallable_empty', 'noncallable_nonempty', 'callback_exception_line', 'invalid_source_argument_effects'):
            with self.subTest(name=name):self.check(name)

    def test_deferred_signature_errors(self):
        for name in ('invalid_predicate_arity_empty', 'invalid_predicate_arity_nonempty', 'builtin_filter_predicate_empty', 'builtin_filter_predicate_nonempty'):
            with self.subTest(name=name):self.check(name)

    def test_consumers(self):
        for name in ('nested_filters_and_reductions', 'bool_callback_and_shortcircuit', 'min_max_consumers', 'raw_source_shortcircuit_consumers'):
            with self.subTest(name=name):self.check(name)

    def test_payload_storage(self):
        for name in ('unicode_text_cursor', 'bytes_cursor', 'tuple_mutable_identity', 'len_callback_in_method', 'stored_empty_tuple', 'empty_iterator_result_joins'):
            with self.subTest(name=name):self.check(name)

    def test_finite_source_alternatives_and_construction_errors(self):
        for name in ('finite_source_alternatives', 'unicode_union_sources', 'source_union_construction_error_order'):
            with self.subTest(name=name):self.check(name)

    def test_empty_consumers_and_sum_initial_value_types(self):
        for name in ('empty_sum_and_shortcircuit', 'empty_min', 'empty_max', 'empty_stop_iteration', 'sum_boolean_start_and_zero_pulls', 'sum_boolean_start_immutable_empty', 'sum_boolean_input_values'):
            with self.subTest(name=name):self.check(name)


if __name__=='__main__':unittest.main()
