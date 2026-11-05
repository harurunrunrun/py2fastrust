"""Readonly owned argument places preserve binding and mutable value semantics."""
import ast
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust.frontend import parse_source
from py2fastrust.native_classes import Emitter
from py2fastrust import native_primitive_parameter_places as places

SOURCES = {'argument_defaults_keywords_order': 'def seed():\n'
                                     ' print("default")\n'
                                     ' return (3,5)\n'
                                     'def mark(value):\n'
                                     ' print("argument",value)\n'
                                     ' return (value,value+1)\n'
                                     'class Calculator:\n'
                                     ' def '
                                     'evaluate(self,payload=seed(),*,scale=2):return '
                                     'payload[0]*scale+payload[1]\n'
                                     'calculator=Calculator()\n'
                                     'print(calculator.evaluate(scale=4,payload=mark(7)),calculator.evaluate())\n',
 'capture_nonlocal_rebinding': 'class Calculator:\n'
                               ' def evaluate(self,payload):\n'
                               '  def change():\n'
                               '   nonlocal payload\n'
                               '   payload=(13,17)\n'
                               '  change()\n'
                               '  return payload[0]+payload[1]\n'
                               'print(Calculator().evaluate((4,7)))\n',
 'classmethod_reference_and_tuple': 'class Factory:\n'
                                    ' base=5\n'
                                    ' @classmethod\n'
                                    ' def evaluate(cls,payload):return '
                                    'cls.base+payload[0]+payload[1]\n'
                                    'print(Factory.evaluate((2,3)),Factory().evaluate((4,5)))\n',
 'comprehension_walrus_rebinding': 'class Calculator:\n'
                                   ' def evaluate(self,payload):\n'
                                   '  values=[(payload:=(i,i+1)) for i in '
                                   'range(2)]\n'
                                   '  return values,payload\n'
                                   'print(Calculator().evaluate((4,7)))\n',
 'constructor_mutable_self': 'class Accumulator:\n'
                             ' def __init__(self,payload):\n'
                             '  self.value=payload[0]+payload[1]\n'
                             ' def add(self,amount):\n'
                             '  self.value+=amount\n'
                             '  return self.value\n'
                             'a=Accumulator((3,4))\n'
                             'print(a.add(5),a.add(2))\n',
 'exception_binding_and_clear': 'class Calculator:\n'
                                ' def evaluate(self,payload):\n'
                                '  try:\n'
                                '   raise ValueError("changed")\n'
                                '  except ValueError as payload:\n'
                                '   print(str(payload))\n'
                                '  return payload\n'
                                'Calculator().evaluate((4,7))\n',
 'fixed_tuple_repeated_reads': 'class Calculator:\n'
                               ' def evaluate(self,payload):\n'
                               '  return '
                               'payload[0]+payload[1],payload[0]*payload[1]\n'
                               'print(Calculator().evaluate((4,7)))\n',
 'list_closed_scalar_loop': 'class Calculator:\n'
                            ' def evaluate(self,values):\n'
                            '  for i in range(len(values)):\n'
                            '   values[i]+=i+1\n'
                            '  return values[0],values[-1]\n'
                            'values=[2,4,6]\n'
                            'print(Calculator().evaluate(values),values)\n',
 'list_mutation_not_rebinding': 'class Calculator:\n'
                                ' def evaluate(self,values):\n'
                                '  values.append(3)\n'
                                '  return values[0],len(values)\n'
                                'values=[8]\n'
                                'print(Calculator().evaluate(values),values)\n',
 'list_reentrant_source_mutation': 'def change(values):\n'
                                   ' values[0]+=10\n'
                                   ' return 1\n'
                                   'class Calculator:\n'
                                   ' def evaluate(self,values):\n'
                                   '  values[change(values)]+=values[0]\n'
                                   '  return values[0],values[1]\n'
                                   'values=[2,4]\n'
                                   'print(Calculator().evaluate(values),values)\n',
 'namespace_observer': 'class Calculator:\n'
                       ' def evaluate(self,payload):return '
                       'locals()["payload"][0]+payload[1]\n'
                       'print(Calculator().evaluate((4,7)))\n',
 'observable_drop_payload': 'class Token:\n'
                            ' def __init__(self,value):self.value=value\n'
                            ' def __del__(self):print("drop",self.value)\n'
                            'class Reader:\n'
                            ' def evaluate(self,payload):return '
                            'payload[0].value\n'
                            'print(Reader().evaluate((Token(7),)))\n',
 'parameter_delete_before_effect': 'def mark():\n'
                                   ' print("later")\n'
                                   ' return 3\n'
                                   'class Calculator:\n'
                                   ' def evaluate(self,payload):\n'
                                   '  del payload\n'
                                   '  return payload[0]+mark()\n'
                                   'Calculator().evaluate((4,7))\n',
 'parameter_rebinding': 'class Calculator:\n'
                        ' def evaluate(self,payload):\n'
                        '  payload=(payload[1],payload[0])\n'
                        '  return payload[0],payload[1]\n'
                        'print(Calculator().evaluate((4,7)))\n',
 'private_parameter_and_shadowed_comp': 'class Calculator:\n'
                                        ' def evaluate(self,__payload):\n'
                                        '  items=[__payload[0]+i for i in '
                                        'range(3)]\n'
                                        '  return items,__payload[1]\n'
                                        'print(Calculator().evaluate((4,7)))\n',
 'readonly_argument_division_error': 'def mark(value):\n'
                                     ' print("argument",value)\n'
                                     ' return(value,2)\n'
                                     'class Calculator:\n'
                                     ' def evaluate(self,payload):\n'
                                     '  print("entered")\n'
                                     '  return 12//payload[0]+payload[1]\n'
                                     'print(Calculator().evaluate(mark(int(input()))))\n',
 'readonly_argument_index_error': 'def position():\n'
                                  ' print("index")\n'
                                  ' return int(input())\n'
                                  'class Calculator:\n'
                                  ' def evaluate(self,payload):\n'
                                  '  return payload[position()]\n'
                                  'print(Calculator().evaluate((3,5)))\n',
 'recursive_result_not_nosuspend': 'class Walker:\n'
                                   ' def walk(self,n,payload):\n'
                                   '  if n==0:return payload[0]+payload[1]\n'
                                   '  return '
                                   'self.walk(n-1,payload)+payload[0]\n'
                                   'print(Walker().walk(int(input()),(3,5)))\n',
 'value_carrier_tuple': 'class Coefficient:\n'
                        ' def __init__(self,value):self.value=value\n'
                        'class Calculator:\n'
                        ' def evaluate(self,payload):\n'
                        '  return '
                        'payload[0].value+payload[1],payload[0].value*payload[1]\n'
                        'print(Calculator().evaluate((Coefficient(4),7)))\n',
 'value_parameter_scalar_fields': 'class Packet:\n'
                                  ' def __init__(self,value):self.value=value\n'
                                  'class Reader:\n'
                                  ' def evaluate(self,packet):return '
                                  'packet.value+packet.value\n'
                                  'print(Reader().evaluate(Packet(9)))\n',
 'with_binding_replacement': 'class Context:\n'
                             ' def __enter__(self):return (13,17)\n'
                             ' def __exit__(self,kind,error,trace):return '
                             'False\n'
                             'class Calculator:\n'
                             ' def evaluate(self,payload):\n'
                             '  with Context() as payload:\n'
                             '   print(payload[0])\n'
                             '  return payload[1]\n'
                             'print(Calculator().evaluate((4,7)))\n'}


def inspect_source(name, integer='i64'):
    source=SOURCES[name]
    observed=[]
    original=Emitter.generate
    def capture(emitter):
        units=getattr(emitter.model.unit,'source_units',(emitter.model.unit,))
        before=[ast.dump(unit.tree,include_attributes=True)for unit in units]
        code=original(emitter)
        assert before==[ast.dump(unit.tree,include_attributes=True)for unit in units]
        observed.append((emitter,code))
        return code
    with patch.object(Emitter,'generate',capture):
        result=transpile(source,TranspileOptions(filename='owned_parameters.py',integer=integer,license='none'))
    return result,observed


class ReadonlyOwnedParameterProofs(unittest.TestCase):
    def test_tuple_loads_use_owned_argument_without_optional_local(self):
        for integer in ('i64','i128','bigint'):
            result,observed=inspect_source('fixed_tuple_repeated_reads',integer)
            self.assertTrue(result.success,result.diagnostics)
            methods=[(emitter,code)for emitter,code in observed if getattr(emitter.plan.node,'name',None)=='evaluate']
            self.assertTrue(methods)
            for emitter,code in methods:
                name=next(name for name in emitter.plan.runtime_parameters if emitter.model.display_name(name)=='payload')
                self.assertNotIn(name,emitter.primitive_parameters)
                place=emitter.readonly_owned_parameters[name]
                self.assertIn(place.code,code)
                self.assertNotIn("UnboundLocalError: cannot access local variable 'payload'",code)
                for(other,kind),slot in emitter.slots.items():
                    if other==name and kind==place.kind:
                        self.assertNotIn('let mut '+slot+':',code)
                        self.assertNotIn(slot+'=Some(',code)

    def test_list_mutation_is_not_binding_replacement_and_loop_place_is_defined(self):
        for name in ('list_mutation_not_rebinding','list_closed_scalar_loop'):
            result,observed=inspect_source(name)
            self.assertTrue(result.success,result.diagnostics)
            methods=[(emitter,code)for emitter,code in observed if getattr(emitter.plan.node,'name',None)=='evaluate']
            self.assertTrue(methods)
            for emitter,code in methods:
                parameter=next(name for name in emitter.plan.runtime_parameters if emitter.model.display_name(name)=='values')
                self.assertIn(parameter,emitter.readonly_owned_parameters)
                self.assertNotIn(parameter,emitter.primitive_parameters)
                self.assertNotIn("UnboundLocalError: cannot access local variable 'values'",code)
                if name=='list_closed_scalar_loop':
                    self.assertIn(emitter.readonly_owned_parameters[parameter].code+'.borrow_mut()',code)

    def test_all_original_binding_and_capture_producers_decline(self):
        for name in ('parameter_rebinding','parameter_delete_before_effect','capture_nonlocal_rebinding',
                     'comprehension_walrus_rebinding','with_binding_replacement','exception_binding_and_clear'):
            unit=parse_source(SOURCES[name],'owned_producers.py')
            node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.FunctionDef)and node.name=='evaluate')
            scope=unit.scope_for(node).ordinal
            self.assertFalse(places.readonly_parameter(unit,unit.bindings,scope,'payload'),name)
        unit=parse_source(SOURCES['list_mutation_not_rebinding'],'owned_mutation.py')
        node=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.FunctionDef)and node.name=='evaluate')
        self.assertTrue(places.readonly_parameter(unit,unit.bindings,unit.scope_for(node).ordinal,'values'))

    def test_physical_borrowed_parameters_keep_their_original_storage(self):
        guarded=0
        from py2fastrust.native_classes import shape
        from py2fastrust.native_value_classes import borrowed_self
        from py2fastrust.native_owned_object_places import receiver
        for name in ('value_parameter_scalar_fields','classmethod_reference_and_tuple','constructor_mutable_self'):
            result,observed=inspect_source(name)
            self.assertTrue(result.success,result.diagnostics)
            for emitter,code in observed:
                for index,parameter in enumerate(emitter.plan.runtime_parameters):
                    for registry_name in ('value_parameter_borrows','class_reference_borrows'):
                        registry=getattr(emitter.model,registry_name,None)
                        if(emitter.plan.index,index)in getattr(registry,'parameters',{}):
                            guarded+=1
                            self.assertNotIn(parameter,emitter.readonly_owned_parameters)
                    if borrowed_self(emitter.model,emitter.plan,parameter,shape(emitter.plan.arguments[parameter]))or receiver(emitter.model,emitter.plan,parameter):
                        guarded+=1
                        self.assertNotIn(parameter,emitter.readonly_owned_parameters)
        self.assertGreater(guarded,0)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ReadonlyOwnedParameterExecution(unittest.TestCase):
    def exercise(self,names,inputs=('',),trace=False):
        for name in names:
            source=SOURCES[name]
            references=[subprocess.run([sys.executable,'-I','-S','-c',source],input=data,capture_output=True,text=True,timeout=10)for data in inputs]
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(filename='owned_parameters.py',integer=integer,license='none'))
                self.assertTrue(result.success,result.diagnostics)
                for optimized in (False,True):
                    with tempfile.TemporaryDirectory(prefix='pytors-owned-parameter-')as directory:
                        path,binary=Path(directory,'main.rs'),Path(directory,'main')
                        path.write_text(result.rust_source)
                        built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                        self.assertEqual(built.returncode,0,built.stderr)
                        for data,reference in zip(inputs,references):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={'PATH':'/no-python','PYTHONPATH':'/no-python'})
                            self.assertEqual((actual.stdout,actual.returncode),(reference.stdout,reference.returncode),(name,integer,optimized,data))
                            if trace:
                                final=lambda value:value.rstrip().splitlines()[-1:]if value.strip()else[]
                                self.assertEqual(final(actual.stderr),final(reference.stderr))
                                self.assertEqual(re.findall(r'line (\d+), in ([^\n]+)',actual.stderr),re.findall(r'line (\d+), in ([^\n]+)',reference.stderr))
                            else:self.assertEqual(actual.stderr,reference.stderr)

    def test_tuple_value_carriers_and_argument_capture(self):
        self.exercise(('fixed_tuple_repeated_reads','value_carrier_tuple','argument_defaults_keywords_order'))

    def test_mutable_alias_and_closed_loop_borrows(self):
        self.exercise(('list_mutation_not_rebinding','list_closed_scalar_loop','list_reentrant_source_mutation'))

    def test_readonly_parameters_keep_error_frames_and_argument_order(self):
        self.exercise(('readonly_argument_division_error','readonly_argument_index_error'),inputs=('0\n','3\n'),trace=True)
