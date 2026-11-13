"""Official complex literals retain primitive bits and shutdown ownership."""
import ast
from dataclasses import asdict
import json
import math
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions, transpile
from py2fastrust.frontend import build_program
from py2fastrust.literal_semantics import Literal
from py2fastrust.native_constraints import Solver
import test_native_integer_digit_limits as digits

CASES = {'imaginary_tokens': ('print(1j,2J,1_2.3_4j,1e3j,0.0000001j)\n', ('',)),
 'signed_zero_tokens': ('print(0j,-0j,+0j,--0j,0.0-0j,-0.0+0j)\n', ('',)),
 'overflow_and_subnormal_tokens': ('print(1e400j,-1e400j,5e-324j,1e-400j)\n', ('',)),
 'complex_expression_components': ('print(1+2j,1-2j,-(1+2j),+(1-2j))\n', ('',)),
 'imaginary_value_does_not_wrap': ('print(9223372036854775808j)\n'
                                   'print(9223372036854775808+0j)\n'
                                   'print(170141183460469231731687303715884105728j)\n',
                                   ('',)),
 'function_literal_defaults': ('def show(z=-0j,w=3j):print(z,w)\nshow()\nshow(1+2j)\n', ('',)),
 'function_literal_returns': ('def choose(flag):\n'
                              ' if flag:return -3j\n'
                              ' return 0j\n'
                              'print(choose(0),choose(1),choose(1)**2)\n',
                              ('',)),
 'finite_unary_none': ('value=1j if int(input())else None\nprint(-value)\n', ('0\n', '1\n')),
 'finite_numeric_unary': ('for value in [1j,2,-3.5]:\n print(+value,-value)\n', ('',)),
 'invert_complex_error': ('print("before")\nprint(~1j)\n', ('',)),
 'not_complex': ('for value in [0j,1j,1e400j]:\n'
                 ' print(bool(value),not value,str(value),repr(value))\n',
                 ('',)),
 'class_fields_and_aliases': ('class Box:\n'
                              ' def __init__(self):self.value=-0j\n'
                              ' def add(self,value):self.value+=value\n'
                              'box=Box()\n'
                              'alias=box\n'
                              'box.add(1+2j)\n'
                              'print(box.value,alias.value)\n',
                              ('',)),
 'signed_branch_cut_literal': ('print((0.0-(1+0j))**0.5)\nprint((-1-0j)**0.5)\n', ('',)),
 'literal_power': ('print(1j**2,pow(2,1j),pow(1+2j,3))\n', ('',)),
 'finite_complex_none': ('value=1+2j if int(input())else None\nprint(value,bool(value))\n',
                         ('0\n', '1\n')),
 'abs_complex_values': ('for value in [0j,3+4j,-3-4j,1e400j]:\n print(abs(value))\n', ('',)),
 'abs_complex_finite_overflow': ('print(abs(1e308+1e308j))\nprint(abs(1.7e308+1.7e308j))\n', ('',)),
 'abs_complex_nan': ('value=1e400j-1e400j\nprint(abs(value),abs(value+1e400j))\n', ('',)),
 'atexit_default_capture': ('import atexit\n'
                            'value=0.0-(1+0j)\n'
                            'def finish(z=value):print("end",z**0.5)\n'
                            'atexit.register(finish)\n'
                            'value=9j\n'
                            'print("body",value)\n',
                            ('',)),
 'atexit_arguments_keywords': ('import atexit\n'
                               'def finish(value,*,label):print(label,value)\n'
                               'value=1+2j\n'
                               'atexit.register(finish,value,label="saved")\n'
                               'value=8j\n'
                               'print("body",value)\n',
                               ('',)),
 'atexit_closure': ('import atexit\n'
                    'def make():\n'
                    ' value=1+2j\n'
                    ' def finish():print("end",value)\n'
                    ' atexit.register(finish)\n'
                    ' value=-3j\n'
                    'make()\n'
                    'print("body")\n',
                    ('',)),
 'atexit_shared_list_payload': ('import atexit\n'
                                'values=[1j]\n'
                                'def finish(saved=values):print("end",saved)\n'
                                'atexit.register(finish)\n'
                                'values.append(-0j)\n'
                                'print("body",values)\n',
                                ('',)),
 'atexit_bound_instance': ('import atexit\n'
                           'class Box:\n'
                           ' def __init__(self):self.value=-0j\n'
                           ' def finish(self):print("end",self.value)\n'
                           'box=Box()\n'
                           'atexit.register(box.finish)\n'
                           'box.value=1+2j\n'
                           'print("body")\n',
                           ('',)),
 'atexit_callback_returns_complex': ('import atexit\n'
                                     'def finish(value):\n'
                                     ' print("end",value)\n'
                                     ' return value\n'
                                     'atexit.register(finish,1+2j)\n'
                                     'print("body")\n',
                                     ('',)),
 'demanded_float_complex_literal': ('import heapq\n'
                                    'nan=float("nan")\n'
                                    'rows=[(nan,2),(nan,1)]\n'
                                    'heapq.heapify(rows)\n'
                                    'print([row[1]for row in rows])\n'
                                    'print(0j,-0j,1e400j,1.0+2j)\n',
                                    ('',)),
 'demanded_float_abs_complex': ('import heapq\n'
                                'nan=float("nan")\n'
                                'rows=[(nan,2),(nan,1)]\n'
                                'heapq.heapify(rows)\n'
                                'value=3+4j\n'
                                'print(abs(value),[row[1]for row in rows])\n',
                                ('',)),
 'demanded_float_atexit_complex': ('import atexit,heapq\n'
                                   'nan=float("nan")\n'
                                   'rows=[(nan,2),(nan,1)]\n'
                                   'heapq.heapify(rows)\n'
                                   'def finish(value):print("end",value)\n'
                                   'atexit.register(finish,-0j)\n'
                                   'print("body",[row[1]for row in rows])\n',
                                   ('',)),
 'custom_unary_mixed': ('events=[]\n'
                        'class Change:\n'
                        ' def __pos__(self):\n'
                        '  events.append("pos")\n'
                        '  return -3j\n'
                        ' def __neg__(self):\n'
                        '  events.append("neg")\n'
                        '  return 2j\n'
                        'for value in [1j,Change()]:\n'
                        ' print(+value,-value)\n'
                        'print(events)\n',
                        ('',)),
 'abs_bool_int_float': ('print(abs(True),abs(-3),abs(-4.5))\n', ('',)),
 'original_root_callback_complex_default': ('import atexit\n'
                                            'value = 0.0 - (1 + 0j)\n'
                                            'def finish(z=value):\n'
                                            '    print("end", z ** 0.5)\n'
                                            'atexit.register(finish)\n'
                                            'print("body", value)\n',
                                            ('',))}

BOUNDARIES = {'complex_equality_boundary': 'print(1j==1j)\n',
 'complex_id_boundary': 'print(id(1j))\n',
 'complex_constructor_boundary': 'print(complex(1,2))\n',
 'complex_nonempty_format_boundary': 'print(format(1j,".2f"))\n'}

CASES['abs_mixed_nan_infinity'] = ('value=(1e400j-1e400j)+1e400\nprint(abs(value),value)\n', ('',))

BOUNDARIES['complex_list_equality_boundary'] = 'print([1j]==[1j])\n'

BOUNDARIES['complex_tuple_equality_boundary'] = 'print((1j,)==(1j,))\n'

CASES['demanded_float_callback_branch_cut'] = ('import atexit,heapq\nnan=float("nan")\nrows=[(nan,2),(nan,1)]\nheapq.heapify(rows)\nvalue=0.0-(1+0j)\ndef finish(saved=value):print("end",saved**0.5)\natexit.register(finish)\nprint("body",[row[1]for row in rows])\n', ('',))


class ComplexLiteralExecutionTests(unittest.TestCase):
    compare = digits.IntegerDigitLimitExecutionTests.compare


def _case(name):
    def test(self):
        source, inputs = CASES[name]
        self.compare(source, inputs, ('i64', 'i128', 'bigint'), 'ascii')
    return test


for _name in CASES:
    setattr(ComplexLiteralExecutionTests, 'test_' + _name, _case(_name))


class ComplexLiteralProofTests(unittest.TestCase):
    def test_official_constant_components_use_raw_binary64(self):
        node=ast.parse('-0j',mode='eval').body
        self.assertIsInstance(node,ast.UnaryOp)
        literal=Literal.from_ast(node.operand)
        self.assertEqual(literal.kind,'complex')
        self.assertEqual(literal.value,0j)
        zero=Literal.from_value(complex(-0.0,-0.0))
        code=zero.rust_atom(lambda _:self.fail('integer normalization used'),repr)
        self.assertEqual(code,'NativeComplex{real:-0.0_f64,imag:-0.0_f64}')
        overflow=Literal.from_ast(ast.parse('1e400j',mode='eval').body)
        self.assertTrue(math.isinf(overflow.value.imag))
        self.assertIn('f64::INFINITY',overflow.rust_atom(lambda _:self.fail('integer normalization used'),repr))

    def test_abs_and_unary_facts_are_distinct(self):
        for kind,wanted in [('bool','int'),('int','int'),('float','float'),('complex','float')]:
            self.assertEqual(Solver.computed('abs',(kind,)),wanted)
        self.assertEqual(Solver.computed('unary:USub',('complex',)),'complex')
        self.assertEqual(Solver.computed('unary:UAdd',('complex',)),'complex')

    def test_frontend_and_result_metadata_remain_json_safe(self):
        source='print(-0j,1e400j)\n'
        program=build_program(source,'literal.py')
        self.assertTrue(any(type(node.value)is complex for node in ast.walk(program.main.tree)if isinstance(node,ast.Constant)))
        json.dumps([asdict(item)for item in program.source_map],allow_nan=False)
        with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
            result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        data=json.dumps({'rust_source':result.rust_source,'diagnostics':[asdict(item)for item in result.diagnostics],'source_map':[asdict(item)for item in result.source_map]},allow_nan=False)
        self.assertIn('NativeComplex',json.loads(data)['rust_source'])

    def test_browser_bridge_serializes_complex_success(self):
        bridge_path=Path(__file__).resolve().parents[1]/'web'/'bridge.py'
        spec=importlib.util.spec_from_file_location('literal_bridge',bridge_path)
        bridge=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        with tempfile.TemporaryDirectory(prefix='pytors-literal-bridge-')as directory:
            bridge.WORK_DIRECTORY=Path(directory)
            bridge._initialized=True
            previous=Path.cwd()
            try:
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
                    data=json.loads(bridge.convert(json.dumps({'source':'print(-0j,1e400j)\n','options':{'license':'none'}})))
            finally:os.chdir(previous)
        self.assertEqual(data['diagnostics'],[])
        self.assertIn('NativeComplex',data['rust_source'])

    def test_unrepresented_observers_and_constructors_remain_positioned(self):
        fragments={'complex_equality_boundary':'comparison','complex_id_boundary':"'id'",
                   'complex_constructor_boundary':"'complex'",'complex_nonempty_format_boundary':'format',
                   'complex_list_equality_boundary':'complex','complex_tuple_equality_boundary':'complex'}
        for name,source in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM used')):
                        result=transpile(source,TranspileOptions(integer=integer,license='none'))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertIn(fragments[name],result.diagnostics[0].message)
                    self.assertEqual(result.diagnostics[0].line,1)
