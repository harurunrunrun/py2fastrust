"""Independent class comprehension scope, iteration and materialization proofs."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,shape
from py2fastrust.native_types import ListType
from py2fastrust.native_stream_plans import ProducerKind


class ClassComprehensionMetadataTests(unittest.TestCase):
    def test_comprehension_bindings_do_not_enter_the_enclosing_frame(self):
        source='class Marker:pass\nx=[2,3]\ny=[x*2 for x in x if x>2]\nprint(x,y)\n'
        unit=build_program(source,'scope.py').main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        comprehension=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.ListComp))
        record=model.comprehensions[(0,id(comprehension))]
        self.assertEqual(shape(record.bindings['x']),'int')
        self.assertTrue(all(shape(value)==ListType('int')for value in model.module.locals['x']))
        self.assertEqual(record.sources[0].kind,ProducerKind.VALUE)
        self.assertEqual(shape(model.records[(0,id(comprehension))]),ListType('int'))
        self.assertEqual(unit.source,source)

    def test_unsupported_comprehension_forms_remain_explicit_errors(self):
        for expression in ['{i for i in range(3)}','{i:i for i in range(3)}',
                           '(i for i in range(3))','[x for *x, in [(1,2)]]']:
            for mode in ('i64','i128','bigint'):
                with self.subTest(expression=expression,mode=mode):
                    result=transpile('class Marker:pass\nvalues='+expression+'\n',TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn('comprehension',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ClassComprehensionExecutionTests(unittest.TestCase):
    def compare(self,source,data='',string_mode='ascii'):
        source='class Marker:pass\n'+source
        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,text=True,capture_output=True,timeout=10)
        with tempfile.TemporaryDirectory(prefix='pytors-class-comprehension-')as directory:
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback entered')):
                    result=transpile(source,TranspileOptions(integer=mode,filename='comprehensions.py',string_mode=string_mode))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','fn step(','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                path=Path(directory)/(mode+'.rs');path.write_text(result.rust_source)
                for release in (False,True):
                    with self.subTest(mode=mode,release=release):
                        binary=path.with_name(mode+str(release))
                        built=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                        self.assertEqual(built.returncode,0,built.stderr)
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,
                            env={**os.environ,'PATH':'/pytors-no-runtime-dependencies'})
                        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+expected.stderr)
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(':')[0],expected.stderr.splitlines()[-1].split(':')[0])

    def test_outermost_source_and_shadowed_target_do_not_leak(self):
        self.compare('''x=[2,3,4]
print([x*x for x in x if x%2],x)
i=91
print([i+1 for i in range(3)],i)
print([j for j in range(0)])
''')

    def test_comp_target_spellings_do_not_rebind_builtins_or_source_definitions(self):
        self.compare('''print([range for range in range(3)])
def values():return range(2)
print([values for values in values()])
def f():return [range for range in range(4)]
print(f())
''')

    def test_comprehension_targets_do_not_change_a_called_functions_globals(self):
        self.compare('''def convert(text):return int(text)
print([convert('7') for int in range(2)])
print([sum([convert('5') for int in range(2)]) for int in range(3)])
class Number:
 def __init__(self,text):self.value=int(text)
print([Number('4').value for int in range(2)])
def f():return [convert('8') for int in range(2)]
print(f())
''')

    def test_special_global_spellings_remain_comprehension_local(self):
        self.compare('''global_value=27
print([global_value for global_value in range(2)],global_value)
print([__name__ for __name__ in range(2)],__name__)
print([__builtins__ for __builtins__ in range(2)])
''')

    def test_fresh_nested_allocations_and_shared_element_aliases(self):
        self.compare('''class Rows:
 def __init__(self,count):self.values=[[] for _ in range(count)]
 def add(self,index,value):self.values[index].append(value)
r=Rows(3)
alias=r.values[1]
r.add(1,7)
print(r.values,alias,r.values[0] is r.values[1])
base=[4]
rows=[base for _ in range(3)]
rows[0].append(8)
print(base,rows,rows[1] is base)
rows=[[i+j for j in range(2)] for i in range(3)]
rows[0].append(9)
print(rows,rows[0] is rows[1])
''')

    def test_allocated_instances_are_distinct_and_keep_field_storage(self):
        self.compare('''class Point:
 def __init__(self,value):self.value=value
points=[Point(i) for i in range(3)]
points[0].value=19
print(points[0].value,points[1].value,points[0] is points[1])
''')

    def test_nested_sources_filters_and_element_evaluate_in_order(self):
        self.compare('''def mark(value):
 print(value,end='|')
 return value
answer=[mark(i*10+j) for i in range(mark(3)) if mark(i)%2 for j in range(mark(i+2)) if mark(j+5)%2]
print(answer)
''')

    def test_nested_comprehension_restores_outer_binding_scope(self):
        self.compare('''x=99
print([sum([x+j for x in range(3)]) for j in range(4)],x)
print([sum([x for x in range(x+1)]) for x in range(4)],x)
''')

    def test_repeated_target_names_keep_the_types_of_each_lexical_binding(self):
        self.compare('''x=99
print([x for x in range(3) if x>0 for x in ('a','b')],x)
print([str(x) for x in range(3) for x in (True,False) if x],x)
''')

    def test_method_arguments_and_fields_are_visible_inside_comprehensions(self):
        self.compare('''class Affine:
 def __init__(self,offset):
  self.offset=offset
 def apply(self,values):
  return [value*2+self.offset for value in values if value>=0]
a=Affine(7)
print(a.apply([2,-1,4]))
''')

    def test_private_names_follow_the_enclosing_class_lexical_context(self):
        self.compare('''class Values:
 def __init__(self):self.__offset=3
 def calculate(self):
  return [__value+self.__offset+sum([__value for __value in range(2)]) for __value in range(3)]
print(Values().calculate())
''')

    def test_forward_target_read_raises_before_outer_same_name_is_used(self):
        self.compare('''y=99
print('before')
print([y for x in range(1) for y in [y]])
''')

    def test_zero_trip_does_not_evaluate_later_sources_filters_or_element(self):
        self.compare('''def fail():
 print('wrong')
 return 1//0
print([fail() for x in range(0) if fail() for y in range(fail())])
print('done')
''')

    def test_list_iteration_observes_mutations_without_holding_a_borrow(self):
        self.compare('''class Growing:
 def __init__(self):
  self.values=[0]
 def next(self,value):
  if value<3:self.values.append(value+1)
  return value*2
g=Growing()
print([g.next(value) for value in g.values],g.values)
''')

    def test_fixed_unpacking_and_numeric_tuple_join(self):
        self.compare('''print([a+b for a,b in [(1,2),(3,4)]])
print([str(value) for value in (1,'a',False)])
''')

    def test_list_unpacking_errors_keep_prior_element_side_effects(self):
        self.compare('''def row(count):
 print('row',count)
 return list(range(count))
def mark(value):
 print('element',value)
 return value
print([mark(a+b) for a,b in (row(2),row(int(input())))])
''',data='1\n')

    def test_enumerate_arguments_and_counter_order(self):
        self.compare('''class Values:
 def __init__(self):self.values=[4,5]
 def start(self):
  print('start')
  self.values.append(6)
  return 7
v=Values()
print([i*10+value for i,value in enumerate(v.values,v.start())])
print([a+b+c for a,(b,c) in enumerate(enumerate(range(3),2),5)])
''')

    def test_map_integer_conversion_is_lazy_and_errors_follow_prior_elements(self):
        self.compare('''def mark(value):
 print('element',value)
 return value
print([mark(value) for value in map(int,['1','bad','3'])])
''')

    def test_text_bytes_and_unicode_iteration(self):
        self.compare("print([c for c in 'abc'],[n for n in b'AZ'])\n")
        self.compare("print([c for c in 'aé𐐀'],[len(c) for c in 'aé𐐀'])\n",string_mode='unicode')


if __name__=='__main__':unittest.main()
