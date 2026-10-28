"""Typed escaping lambdas retain original scopes, cells, defaults and identity."""
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
from py2fastrust.native_classes import Model
from py2fastrust.native_frame_selection import select_frames

CASES={'module_fold': ('op=lambda a,b:a+b\nvalue=0\nfor item in [2,3,5]:value=op(value,item)\nprint(value)\n', ('',)), 'factory_captures': ('def factory(offset):\n return lambda value:offset+value\nfirst=factory(3)\nsecond=factory(10)\nprint(first(2),second(2),first(5),first is second)\n', ('',)), 'definition_time_default_effect': ("def mark(value):\n print('default',value)\n return value\ncall=lambda value=mark(3):value\nprint(call(),call(8),call())\n", ('',)), 'fresh_mutable_defaults': ('def factory():\n return lambda value,items=[]:(items.append(value),items)[1]\nfirst=factory()\nsecond=factory()\nprint(first(1),first(2),second(9))\nprint(first(3),second(8))\n', ('',)), 'loop_default_instances': ('functions=[]\nfor index in range(3):\n functions.append(lambda value=index:value)\nprint(functions[0](),functions[1](),functions[2]())\nprint(functions[0] is functions[1],functions[0] is functions[0])\n', ('',)), 'module_late_loop_binding': ('functions=[]\nfor index in range(3):functions.append(lambda:index)\nprint(functions[0](),functions[1](),functions[2]())\nprint(functions[0] is functions[1])\n', ('',)), 'factory_late_loop_binding': ('def factory():\n functions=[]\n for value in range(3):functions.append(lambda:value)\n return functions\nfunctions=factory()\nprint(functions[0](),functions[1](),functions[2]())\n', ('',)), 'comprehension_late_cells': ('functions=[lambda:value for value in range(3)]\nprint(functions[0](),functions[1](),functions[2]())\n', ('',)), 'comprehension_defaults': ('functions=[lambda value=value:value for value in range(3)]\nprint(functions[0](),functions[1](),functions[2]())\n', ('',)), 'class_stored_callback': ('class Fold:\n def __init__(self,operation):self.operation=operation\n def apply(self,left,right):return self.operation(left,right)\nfold=Fold(lambda left,right:left+right)\nprint(fold.apply(3,7),fold.apply(5,8))\n', ('',)), 'callee_before_argument_write': ('call=lambda value:value+1\ndef replace():\n global call\n call=lambda value:value+100\n return 3\nprint(call(replace()),call(3))\n', ('',)), 'nested_lambda': ('make=lambda left:lambda right:left+right\nfirst=make(2)\nsecond=make(9)\nprint(first(3),second(3),first(8))\n', ('',)), 'recursive_lambda': ('count=lambda value:1+count(value-1) if value else 0\nprint(count(5),count(0))\n', ('',)), 'unused_default_reads_input': ("unused=lambda value=int(input()):value\nprint('created')\n", ('4\n', 'broken\n')), 'callable_argument': ('def fold(values,operation,start):\n for value in values:start=operation(start,value)\n return start\nadd=lambda left,right:left+right\nmultiply=lambda left,right:left*right\nprint(fold([2,3,4],add,0),fold([2,3,4],multiply,1))\n', ('',)), 'signature_effect_order': ("def mark(value):\n print('argument',value)\n return value\ncall=lambda value,*,other=2:value+other\nprint(call(mark(1),mark(2)))\n", ('',)), 'sibling_nonlocal_reader': ('def factory():\n value=1\n def store(other):\n  nonlocal value\n  value=other\n return store,lambda:value\nstore,read=factory()\nprint(read())\nstore(7)\nprint(read())\n', ('',)), 'saved_function_default': ('call=lambda value:value+1\nsaved=lambda value,operation=call:operation(value)\ncall=lambda value:value+100\nprint(saved(3),call(3))\n', ('',)), 'default_before_factory_rebind': ('def factory(value):\n call=lambda copied=value:copied\n value=20\n return call\nprint(factory(3)(),factory(9)())\n', ('',)), 'immediate_factory_returns_lambda': ('call=(lambda left:lambda right:left+right)(3)\nprint(call(4),call(8))\n', ('',)), 'nested_comprehension_defaults': ('functions=[lambda left=left,right=right:left*10+right for left in range(3) if left!=1 for right in range(2)]\nprint(functions[0](),functions[1](),functions[2](),functions[3]())\n', ('',)), 'fresh_comprehension_environments': ('def create(start):\n return [lambda:value for value in range(start,start+2)]\nfirst=create(2)\nsecond=create(9)\nprint(first[0](),first[1](),second[0](),second[1]())\n', ('',)), 'nested_comprehension_cell_lifetimes': ('rows=[[lambda:left+right for right in range(2)]for left in range(2)]\nprint(rows[0][0](),rows[0][1](),rows[1][0](),rows[1][1]())\n', ('',)), 'lambda_created_in_default': ('make=lambda operation=(lambda value:value+3):operation\noperation=make()\nprint(operation(4),operation(7))\n', ('',)), 'lambda_and_function_alternatives': ('def add(value):return value+1\ncall=add if int(input())else lambda value:value+10\nprint(call(3))\n', ('0\n', '1\n')), 'unbound_late_capture': ('def factory(flag):\n if flag:value=7\n return lambda:value\ncall=factory(int(input()))\nprint(call())\n', ('0\n', '1\n')), 'empty_comprehension_default_not_evaluated': ('functions=[lambda value=int(input()):value for item in range(0)]\nprint(len(functions))\n', ('',)), 'lambda_defaults_preserve_order': ('def mark(value):\n print(value)\n return value\ncall=lambda first=mark(1),*,second=mark(2):first+second\nprint(call(),call(second=8))\n', ('',)), 'pure_callback_inside_captured_class': ('class Apply:\n def __init__(self,operation):self.operation=operation\n def run(self,value):return self.operation(value)\ndef make():\n holder=Apply(lambda value:value+1)\n def call(value):return holder.run(value)\n return call\nfirst=make()\nsecond=make()\nprint(first(3),second(7),first(8))\n', ('',)), 'no_free_factory_identity': ('def make():return lambda:7\nfirst=make()\nsecond=make()\nprint(first(),second(),first is second,first is first)\n', ('',)), 'default_capture_without_free_owner': ('def make(value):\n return lambda current=value:current\nfirst=make(3)\nsecond=make(8)\nprint(first(),second(),first is second)\n', ('',)), 'grandparent_capture': ('def outer(start):\n def middle(extra):\n  return lambda value:start+extra+value\n return middle\nmake=outer(3)\nfirst=make(7)\nsecond=make(10)\nprint(first(1),second(1),first(4))\n', ('',))}

REFERENCE="import json,sys\ntry:exec(compile(sys.argv[1],sys.argv[2],'exec'),{'__name__':'__main__'})\nexcept BaseException as error:\n frames=[];trace=error.__traceback__\n while trace is not None:\n  if trace.tb_frame.f_code.co_filename==sys.argv[2]:frames.append((str(trace.tb_lineno),trace.tb_frame.f_code.co_name))\n  trace=trace.tb_next\n print(json.dumps({'message':type(error).__name__+': '+str(error),'frames':frames}),file=sys.stderr);sys.exit(1)\n"

class LambdaPlanTests(unittest.TestCase):
    def test_original_lambda_nodes_and_official_scopes_are_plan_identity(self):
        source=CASES['nested_comprehension_defaults'][0]
        unit=build_program(source,'lambda_cells.py').main
        before=ast.dump(unit.tree,include_attributes=True)
        nodes={id(node):node for node in ast.walk(unit.tree)if isinstance(node,ast.Lambda)}
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        self.assertEqual({id(plan.node)for plan in model.lambda_cells.plans.values()},set(nodes))
        for definition,plan in model.lambda_cells.plans.items():
            self.assertIs(plan.node,nodes[id(plan.node)])
            self.assertEqual(definition,unit.ordinal(plan.node))
            self.assertEqual(model.lexical.scope(plan),unit.scope_for(plan.node).ordinal)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        unit.check_identity(source,unit.filename)

    def test_preselection_preserves_existing_eager_lambda_consumers(self):
        sources=("print((lambda value:value+1)(3))\n",
                 "values=[3,1,2]\nvalues.sort(key=lambda value:-value)\nprint(values)\n",
                 "print(sorted([3,1,2],key=lambda value:-value))\n")
        for source in sources:
            unit=build_program(source,'eager_lambda.py').main
            self.assertFalse(select_frames(unit).required)
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.native_classes.try_generate_classes',side_effect=AssertionError('unnecessary frame path')),patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=unit.filename))
                self.assertTrue(result.success,result.diagnostics)

    def test_escaping_lambda_is_selected_before_emitter(self):
        for name in ('module_fold','immediate_factory_returns_lambda','factory_captures'):
            unit=build_program(CASES[name][0],'lambda_cells.py').main
            selection=select_frames(unit)
            self.assertTrue(selection.required)
            self.assertIn('escaping lambda instances',selection.reasons)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class LambdaExecutionTests(unittest.TestCase):
    def compare(self,source,inputs):
        filename='lambda_cells.py';expected=[]
        for data in inputs:
            cp=subprocess.run([sys.executable,'-I','-S','-c',REFERENCE,source,filename],input=data,capture_output=True,text=True,timeout=10)
            expected.append((cp.returncode,cp.stdout,json.loads(cp.stderr)if cp.returncode else None))
        with tempfile.TemporaryDirectory(prefix='pytors-lambda-cells-')as directory:
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
                                self.assertEqual(actual.stderr.splitlines()[-1],reference[2]['message'])
                                self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in reference[2]['frames']])


def _case(name):
    def test(self):self.compare(*CASES[name])
    return test

for _name in CASES:setattr(LambdaExecutionTests,'test_'+_name,_case(_name))

if __name__=='__main__':unittest.main()
