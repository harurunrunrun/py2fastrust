"""Lazy annotations and assertions retain scope, effects, lifetimes and errors."""
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

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,shape
from py2fastrust.native_frame_selection import select_frames

CASES={'annotation_is_not_a_type_requirement': ('def double(value:bool)->None:\n return value*2\nprint(double(7))\n', ('',)), 'annotations_do_not_run_at_definition': ("def mark():\n print('annotation')\n return int\ndef call(value:mark())->mark():\n return value+1\nprint('defined',call(3))\n", ('',)), 'annotation_callable_scopes_are_unobserved': ('def call(value:(lambda ignored=int(input()):ignored))->(lambda:(yield 1)):\n return value+2\nprint(call(3))\n', ('',)), 'future_annotations_stay_unobserved': ('from __future__ import annotations\ndef call(value:missing())->missing():\n return value+3\nprint(call(4))\n', ('',)), 'annotated_class_methods': ('class Box:\n def __init__(self,value:Missing)->None:self.value=value\n def add(self,other:Unknown)->int:return self.value+other\nbox=Box(3)\nprint(box.add(7))\n', ('',)), 'annotated_recursion': ('def count(value:Missing)->Other:\n if value:return 1+count(value-1)\n return 0\nprint(count(5))\n', ('',)), 'annotated_nested_closure': ('def create(start:Missing)->Unknown:\n def add(value:Other)->Another:return start+value\n return add\nfirst=create(3)\nprint(first(4),first(8))\n', ('',)), 'defaults_run_annotations_do_not': ("def mark(label,value):\n print(label)\n return value\ndef call(value:mark('annotation',1)=mark('default',3))->mark('return',2):\n return value\nprint(call(),call(8))\n", ('',)), 'local_and_module_annotated_assignments': ('value:Missing=3\ndef call():\n item:Unknown=value\n item:str=item+4\n return item\nprint(call(),value)\n', ('',)), 'annotation_only_bindings_have_no_effect': ('value:missing()\ndef call():\n item:missing()\n return 7\nprint(call())\n', ('',)), 'annotation_only_target_primaries_and_indices': ("def primary():\n print('primary')\n return []\ndef offset():\n print('offset')\n return 100\nprimary()[offset()]:missing()\nprimary().absent:missing()\nprint('done')\n", ('',)), 'annotated_target_assignment_order': ("values=[0]\ndef mark(label,value):\n print(label)\n return value\nvalues[mark('index',0)]:missing()=mark('right',7)\nprint(values)\n", ('',)), 'assert_without_message': ("value=int(input())\nassert value\nprint('accepted')\n", ('0\n', '1\n')), 'assert_text_empty_message': ('assert False,input()\n', ('\n', 'detail\n')), 'assert_none_message': ('assert False,None\n', ('',)), 'assert_numeric_message': ('assert False,123\n', ('',)), 'assert_tuple_message': ("assert False,(1,True,'text')\n", ('',)), 'assert_list_message': ('assert False,[1,2]\n', ('',)), 'assert_condition_and_message_effect_order': ("def mark(label,value):\n print(label)\n return value\nassert mark('condition',int(input())),mark('message',7)\nprint('done')\n", ('0\n', '1\n')), 'assert_condition_error_precedes_message': ('assert 1//int(input()),input()\n', ('0\n', '2\nmessage\n')), 'assert_message_error_precedes_assertion_error': ('assert False,int(input())\n', ('bad\n', '7\n')), 'assert_ignores_shadowed_exception_name': ("AssertionError=123\nassert False,'detail'\n", ('',)), 'assert_in_annotated_method': ('class Box:\n def __init__(self,value:Missing)->None:self.value=value\n def checked(self)->int:\n  assert self.value>0,self.value\n  return self.value+1\nprint(Box(int(input())).checked())\n', ('0\n', '2\n')), 'assert_in_shared_closure': ('def create():\n count=0\n def check(value):\n  nonlocal count\n  count+=1\n  assert value,count\n  return count\n return check\ncheck=create()\nprint(check(1))\nprint(check(int(input())))\n', ('0\n', '1\n')), 'assert_failure_binding_does_not_reach_success': ("def create():\n offset=3\n def check(flag):\n  value=offset\n  assert flag,(value:='changed')\n  return value+1\n return check\nprint(create()(int(input())))\n", ('0\n', '1\n')), 'constant_data_global_read': ('LIMIT=3\ndef add(value):return LIMIT+value\nprint(add(4))\n', ('',)), 'latest_data_global_read': ('VALUE=3\ndef read():return VALUE\nprint(read())\nVALUE=8\nprint(read())\n', ('',)), 'annotation_only_borrowed_array_protocol': ('def size(values:(lambda: values.append(99)))->Missing:\n return len(values)\nvalues=[1,2,3]\nprint(size(values),values)\n', ('',)), 'assert_float_message': ('assert False,1.25\n', ('',)), 'assert_empty_list_message': ('assert False,[]\n', ('',)), 'assert_success_skips_unbound_message': ('assert True,missing()\nprint("done")\n', ('',)), 'assert_success_skips_message_exception': ('assert True,1//0\nprint("done")\n', ('',)), 'assert_success_in_method_skips_message': ('class Box:\n def check(self):\n  assert True,missing()\n  return 7\nprint(Box().check())\n', ('',)), 'assert_bytes_message': ("assert False,b'a\\n'\n", ('',)), 'assert_dictionary_message': ('assert False,{1:2,3:4}\n', ('',)), 'borrowed_list_message_preserves_success_value': ('values=[1,2]\nassert int(input()),values\nprint(values)\n', ('0\n', '1\n')), 'borrowed_string_message_preserves_success_value': ("message='detail'\nassert int(input()),message\nprint(message)\n", ('0\n', '1\n')), 'annotated_shared_row_preserves_rhs_alias': ('row=[1]\nrows=[[0]]\nrows[0]:Missing=row\nrow.append(2)\nprint(row,rows)\n', ('',)), 'assert_multiline_input_error_positions': ('assert False,int(\n input()\n)\n', ('bad\n', '7\n', '')), 'ordinary_multiline_input_error_positions': ('value=int(\n input()\n)\nprint(value)\n', ('bad\n', '7\n', '')), 'function_multiline_input_error_positions': ('def read():\n return int(\n  input()\n )\nprint(read())\n', ('bad\n', '7\n', '')), 'class_body_assertion_success': ('def mark():\n print("condition")\n return 1\nclass Box:\n assert mark(),int(input())\n def get(self):return 7\nprint(Box().get())\n', ('',)), 'class_body_assertion_failure': ('class Box:\n assert int(input()),"class failure"\nprint(Box())\n', ('0\n',)), 'class_annotation_only_is_not_evaluated': ('class Box:\n value:missing()\n def get(self):return 9\nprint(Box().get())\n', ('',)), 'instance_annotated_field_assignment': ('class Box:\n def __init__(self,value):self.value:Missing=value\n def get(self):return self.value\nprint(Box(7).get())\n', ('',)), 'unobserved_annotation_retains_free_cell': ('def make():\n values=[1]\n saved=id(values)\n def keep(value:values):return 0\n return keep,saved\nfor iteration in range(20):\n keep,saved=make()\n other=[2]\n print(saved==id(other))\n', ('',)), 'module_annotation_lambda_stays_unobserved': ('value:(lambda unused=int(input()):unused)\nprint("ready")\n', ('',)), 'class_annotation_lambda_stays_unobserved': ('class Box:\n value:(lambda unused=int(input()):unused)\n def get(self):return 3\nprint(Box().get())\n', ('',)), 'annotation_only_metadata_named_target': ('def call(value:int)->str:return value\ncall.__annotations__:Missing\nprint(call(3))\n', ('',))}

REFERENCE="import json,sys\ntry:exec(compile(sys.argv[1],sys.argv[2],'exec'),{'__name__':'__main__'})\nexcept BaseException as error:\n frames=[];trace=error.__traceback__\n while trace is not None:\n  if trace.tb_frame.f_code.co_filename==sys.argv[2]:frames.append((str(trace.tb_lineno),trace.tb_frame.f_code.co_name))\n  trace=trace.tb_next\n message=type(error).__name__+(': '+str(error)if str(error)else'')\n print(json.dumps({'message':message,'frames':frames}),file=sys.stderr);sys.exit(1)\n"

class AnnotationAndAssertionMetadataTests(unittest.TestCase):
    def test_original_annotations_and_official_tables_survive_without_executable_plans(self):
        source=CASES['annotation_callable_scopes_are_unobserved'][0]
        unit=build_program(source,'annotations.py').main
        before=ast.dump(unit.tree,include_attributes=True);table=unit.table
        deferred={unit.ordinal(node)for node in ast.walk(unit.tree)if isinstance(node,ast.Lambda)}
        self.assertTrue(deferred)
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        self.assertFalse(deferred&set(model.lexical.plans))
        self.assertIs(unit.table,table)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        unit.check_identity(source,unit.filename)

    def test_annotation_types_do_not_replace_value_constraints(self):
        source=CASES['annotation_is_not_a_type_requirement'][0]
        unit=build_program(source,'annotations.py').main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        function=model.functions['double']
        self.assertEqual(shape(function.arguments['value']),'int')
        self.assertEqual(shape(function.result),'int')
        self.assertIsInstance(function.node.args.args[0].annotation,ast.Name)
        self.assertIsNone(function.node.returns.value)

    def test_variable_annotations_share_the_official_namespace_scope(self):
        for source in ('first:Missing\nsecond:(lambda:None)\n',
                       'class Box:\n first:Missing\n second:(lambda:None)\n def get(self):return 1\n'):
            unit=build_program(source,'annotations.py').main
            declarations=[node for node in ast.walk(unit.tree)if isinstance(node,ast.AnnAssign)]
            scopes={unit.scope_for(node).ordinal for node in declarations}
            self.assertEqual(len(scopes),1)
            scope=next(iter(scopes));self.assertEqual(unit.scopes[scope].kind,'annotation')
            literal=next(node for node in ast.walk(unit.tree)if isinstance(node,ast.Lambda))
            self.assertEqual(unit.nodes[unit.ordinal(literal)].scope,scope)
            self.assertEqual(unit.scopes[unit.scope_for(literal).ordinal].parent,scope)

    def test_unobserved_module_annotation_lambda_preserves_ordinary_route(self):
        source=CASES['module_annotation_lambda_stays_unobserved'][0]
        unit=build_program(source,'annotations.py').main
        self.assertFalse(select_frames(unit).required)

    def test_deferred_annotations_retain_free_cells_without_evaluating_expressions(self):
        source=CASES['unobserved_annotation_retains_free_cell'][0]
        unit=build_program(source,'annotations.py').main
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        owner=model.functions['make'];scope=model.lexical.scope(owner)
        self.assertIn('values',model.lexical.environments[scope].fields)

    def test_module_data_reads_select_typed_cells_before_lowering(self):
        for name in ('constant_data_global_read','latest_data_global_read'):
            unit=build_program(CASES[name][0],'annotations.py').main
            selection=select_frames(unit)
            self.assertTrue(selection.required)
            self.assertIn('module data binding reads',selection.reasons)

    def test_annotation_metadata_objects_remain_an_explicit_required_boundary(self):
        for attribute in ('__annotations__','__annotate__'):
            for operation in ('print(call.'+attribute+')',
                              'call.'+attribute+' = {}',
                              'del call.'+attribute):
                source='def call(value:Missing)->Other:return value\n'+operation+'\n'
                for integer in ('i64','i128','bigint'):
                    result=transpile(source,TranspileOptions(integer=integer,filename='annotations.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(item.code=='E006'and item.line==2 and attribute in item.message and 'annotation'in item.message.lower()for item in result.diagnostics),result.diagnostics)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class AnnotationAndAssertionExecutionTests(unittest.TestCase):
    def compare(self,source,inputs):
        filename='annotations_assertions.py';expected=[]
        for data in inputs:
            cp=subprocess.run([sys.executable,'-I','-S','-c',REFERENCE,source,filename],input=data,capture_output=True,text=True,timeout=10)
            expected.append((cp.returncode,cp.stdout,json.loads(cp.stderr)if cp.returncode else None))
        with tempfile.TemporaryDirectory(prefix='pytors-annotation-assert-')as directory:
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=filename))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):self.assertNotIn(marker,result.rust_source)
                rust=Path(directory)/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(integer=integer,optimized=optimized,input=data):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                            self.assertEqual((actual.returncode,actual.stdout),reference[:2],actual.stderr)
                            if reference[2]is None:self.assertEqual(actual.stderr,'')
                            else:
                                self.assertTrue(actual.stderr.endswith(reference[2]['message']+'\n'),actual.stderr)
                                self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in reference[2]['frames']])


def _case(name):
    def test(self):self.compare(*CASES[name])
    return test

for _name in CASES:setattr(AnnotationAndAssertionExecutionTests,'test_'+_name,_case(_name))

if __name__=='__main__':unittest.main()
