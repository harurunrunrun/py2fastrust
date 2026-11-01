"""Lambda writes share the definite-binding environment used by source blocks."""
import unittest
import test_native_explicit_raise as raised
from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames

CASES={'local_assignment': 'print(list(map(lambda x:(copy:=x+1),[1,2])))\n',
 'parameter_retarget': 'print(list(map(lambda x:((x:=x+1),x),[1,2])))\n',
 'unbound_before_assignment': 'print(list(map(lambda '
                              'x:(copy,(copy:=x)),[1,2])))\n',
 'default_parameter_retarget': 'print(list(map(lambda '
                               'x,y=4:(y:=y+x),[1,2])))\n',
 'mutable_local': 'print(list(map(lambda '
                  'x:((cache:=[x]),cache.append(x+1),len(cache))[2],[1,2])))\n',
 'nested_lexical': 'print(list(map(lambda x:(lambda '
                   'y:(saved:=x+y))(2),[1,2])))\n',
 'local_retarget_then_read': 'operation=lambda '
                             'x:((value:=x),(value:=value+2),value)\n'
                             'print(operation(1),operation(4))\n',
 'error_before_store': 'print(list(map(lambda x:(x:=int("bad")),[1,2])))\n'}

class LambdaBindingEnvironment(unittest.TestCase):
    exercise=raised.NativeRaiseExecutionTests.exercise
    def test_local_assignment(self):self.exercise(CASES['local_assignment'],"")
    def test_parameter_retarget(self):self.exercise(CASES['parameter_retarget'],"")
    def test_unbound_before_assignment(self):self.exercise(CASES['unbound_before_assignment'],"")
    def test_default_parameter_retarget(self):self.exercise(CASES['default_parameter_retarget'],"")
    def test_mutable_local(self):self.exercise(CASES['mutable_local'],"")
    def test_nested_lexical(self):self.exercise(CASES['nested_lexical'],"")
    def test_local_retarget_then_read(self):self.exercise(CASES['local_retarget_then_read'],"")
    def test_error_before_store(self):self.exercise(CASES['error_before_store'],"")
    def test_assignment_expression_selects_proved_typed_binding_storage(self):
        for name in CASES:
            unit=build_program(CASES[name],'lambda_writes.py').main
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    self.assertTrue(select_frames(unit,integer=mode).required)
