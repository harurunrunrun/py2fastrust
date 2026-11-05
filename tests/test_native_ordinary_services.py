"""Original IO service demand and the resulting ordinary helper ABI."""
import ast
from dataclasses import replace
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions, native
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import (analyze, Analysis, SemanticGraph,
    ScopeFacts, Value, Variable, ShapeConstraint, TupleValue, CallFact)
from py2fastrust.references import BuiltinIdentity
from py2fastrust.native_service_demands import Registry, NONE, UNKNOWN
from py2fastrust.native_classes import InstanceType

SOURCES = {'argument_effect_error_order': 'def mark(x):\n'
                                '    print("arg",x)\n'
                                '    return x\n'
                                'def divide(a,b):\n'
                                '    return a//b\n'
                                'def outer():\n'
                                '    return divide(mark(8),mark(0))\n'
                                'print(outer())\n',
 'captured_input_alias': 'read=input\n'
                         'def read_one():\n'
                         '    return int(read())\n'
                         'def pure(x):\n'
                         '    return x+2\n'
                         'print(pure(read_one()))\n',
 'input_transitive': 'def read_one():\n'
                     '    return int(input())\n'
                     'def combine():\n'
                     '    return read_one()*10+read_one()\n'
                     'print(combine())\n',
 'output_transitive': 'def emit(x):\n'
                      '    print("seen",x)\n'
                      '    return x+1\n'
                      'def route(x):\n'
                      '    return emit(x)*2\n'
                      'print(route(int(input())))\n',
 'pure_no_input': 'def distance(a,b):\n    return abs(a-b)\nprint(distance(17,5))\n',
 'pure_transitive_program_input': 'def square(x):\n'
                                  '    return x*x\n'
                                  'def advance(x):\n'
                                  '    return square(x)+1\n'
                                  'print(advance(int(input())))\n',
 'sequential_source_redefinition': 'def step(x):\n'
                                   '    return x+1\n'
                                   'def path(x):\n'
                                   '    return step(x)\n'
                                   'print(path(3))\n'
                                   'def step(x):\n'
                                   '    print("later",x)\n'
                                   '    return x+2\n'
                                   'print(path(3))\n'}

PROTOCOLS = {'hash_key': 'class Key:\n'
             '    def __hash__(self):\n'
             '        print("hash")\n'
             '        return 1\n'
             '    def __eq__(self, other):\n'
             '        print("equal")\n'
             '        return True\n'
             'def build(key):\n'
             '    return {key: 3}, {key}\n'
             'a, b = build(Key())\n'
             'print(len(a), len(b))\n',
 'loop_unpack': 'class Row:\n'
                '    def __iter__(self):\n'
                '        print("row")\n'
                '        return iter((5, 6))\n'
                'def consume(rows):\n'
                '    for first, second in rows:\n'
                '        pass\n'
                '    return 0\n'
                'print(consume([Row()]))\n',
 'opaque_parameter_drop': 'class Token:\n'
                          '    def __del__(self):\n'
                          '        print("drop")\n'
                          'def ignore(value):\n'
                          '    return 3\n'
                          'print(ignore(Token()))\n',
 'slice_store_rhs': 'class Items:\n'
                    '    def __iter__(self):\n'
                    '        print("items")\n'
                    '        return iter((7, 8))\n'
                    'def replace(row, values):\n'
                    '    row[:] = values\n'
                    '    return row\n'
                    'print(replace([1], Items()))\n',
 'starred_arguments': 'class Args:\n'
                      '    def __iter__(self):\n'
                      '        print("expand")\n'
                      '        return iter((4, 5))\n'
                      'def add(a, b):\n'
                      '    return a + b\n'
                      'def call(values):\n'
                      '    return add(*values)\n'
                      'print(call(Args()))\n',
 'unpack_rhs': 'class Pair:\n'
               '    def __iter__(self):\n'
               '        print("unpack")\n'
               '        return iter((2, 3))\n'
               'def consume(values):\n'
               '    first, second = values\n'
               '    return 0\n'
               'print(consume(Pair()))\n'}


def facts_for(source):
    unit = build_program(source, "services.py").main
    analysis = analyze(unit)
    functions = {node: None for node in unit.tree.body if isinstance(node, ast.FunctionDef)}
    return unit, analysis, functions


class OrdinaryServiceProofTests(unittest.TestCase):
    def test_missing_unknown_unbound_and_may_callee_identity(self):
        unit, analysis, functions = facts_for(SOURCES['pure_no_input'])
        function = next(iter(functions))
        registry = Registry(unit, analysis, functions)
        self.assertEqual(registry.demand(function), NONE)
        key = next(key for key in analysis.scopes if key[0] == unit.ordinal(function))
        scope = analysis.scopes[key]
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call))
        site = unit.ordinal(call)
        before = scope.calls[site]
        for identity in (None, Value(unknown=True), Value(unbound=True),
                Value(frozenset({BuiltinIdentity('abs'), BuiltinIdentity('input')}))):
            calls = {} if identity is None else {site: replace(before, identity=identity)}
            changed = replace(scope, calls=calls)
            scopes = dict(analysis.scopes)
            scopes[key] = changed
            demand = Registry(unit, replace(analysis, scopes=scopes), functions).demand(function)
            self.assertTrue(demand.input)
            self.assertTrue(demand.output)

    def test_actual_transitive_redefinition_joins_all_reached_contexts(self):
        unit, analysis, functions = facts_for(SOURCES['sequential_source_redefinition'])
        registry = Registry(unit, analysis, functions)
        path = next(node for node in functions if node.name == 'path')
        steps = [node for node in functions if node.name == 'step']
        self.assertNotEqual(unit.ordinal(steps[0]), unit.ordinal(steps[1]))
        self.assertEqual(registry.demand(steps[0]), NONE)
        self.assertTrue(registry.demand(steps[1]).output)
        self.assertTrue(registry.demand(path).output)

    def test_set_dictionary_and_unpack_unknown_protocols_are_not_no_io(self):
        for name, function_name in [('hash_key', 'build'), ('unpack_rhs', 'consume'),
                ('slice_store_rhs', 'replace'), ('loop_unpack', 'consume')]:
            unit = build_program(PROTOCOLS[name], "protocols.py").main
            function = next(node for node in unit.tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == function_name)
            registry = Registry(unit, None, {})
            demand = registry.body(unit.ordinal(function), function.body, ScopeFacts({}, {}, {}))
            self.assertTrue(demand.input, name)
            self.assertTrue(demand.output, name)
            self.assertFalse(demand.complete, name)

    def test_closed_hash_and_unpack_builtin_payloads_remain_no_io(self):
        for name, function_name, argument in [('hash_key', 'build', Value(frozenset({'int'}))),
                ('unpack_rhs', 'consume', Value(frozenset({TupleValue((
                    Value(frozenset({'int'})), Value(frozenset({'int'}))))})))]:
            unit = build_program(PROTOCOLS[name], "protocols.py").main
            function = next(node for node in unit.tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == function_name)
            values = {unit.ordinal(node): argument if isinstance(node, ast.Name) else Value(frozenset({'int'}))
                      for node in ast.walk(function) if isinstance(node, ast.expr)}
            registry = Registry(unit, None, {})
            self.assertEqual(registry.body(unit.ordinal(function), function.body,
                                          ScopeFacts({}, {}, {}, values=values)), NONE)

    def test_starred_expansion_requires_its_own_closed_payload(self):
        unit = build_program(PROTOCOLS['starred_arguments'], "protocols.py").main
        functions = {node.name: node for node in unit.tree.body if isinstance(node, ast.FunctionDef)}
        function = functions['call']
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call))
        definition = unit.ordinal(functions['add'])
        from py2fastrust.native_constraints import FunctionValue
        identity = Value(frozenset({FunctionValue(definition, ())}))
        scope = ScopeFacts({}, {}, {}, calls={unit.ordinal(call): CallFact(identity,
            (Value(frozenset({'int'})), Value(frozenset({'int'}))), ())})
        registry = Registry(unit, None, {})
        registry.nodes[definition] = functions['add']
        registry.edges[unit.ordinal(function)] = set()
        demand = registry.body(unit.ordinal(function), function.body, scope)
        self.assertTrue(demand.input)
        self.assertTrue(demand.output)

    def test_opaque_unused_parameter_retains_lifetime_services(self):
        unit = build_program(PROTOCOLS['opaque_parameter_drop'], "protocols.py").main
        function = next(node for node in unit.tree.body if isinstance(node, ast.FunctionDef))
        graph = SemanticGraph(unit)
        analysis = Analysis(graph, {(unit.ordinal(function), (InstanceType('Token'),)):
                                    ScopeFacts({}, {}, {})}, 1)
        self.assertEqual(Registry(unit, analysis, {function: None}).demand(function), UNKNOWN)

    def test_missing_analysis_foreign_unit_and_unregistered_node_fail_closed(self):
        unit, analysis, functions = facts_for(SOURCES['pure_no_input'])
        function = next(iter(functions))
        self.assertEqual(Registry(unit, None, functions).demand(function), UNKNOWN)
        other = build_program(SOURCES['pure_no_input'], "other.py").main
        self.assertEqual(Registry(other, analysis, {}).demand(next(node for node in other.tree.body
                                        if isinstance(node, ast.FunctionDef))), UNKNOWN)
        self.assertEqual(Registry(unit, analysis, functions).demand(other.tree.body[0]), UNKNOWN)

    def test_lower_bounds_and_ungrounded_symbolic_cycles_are_not_closed_data(self):
        unit, analysis, functions = facts_for(SOURCES['pure_no_input'])
        variable = Variable(('unresolved',), 'element')
        analysis = replace(analysis, heap={variable: Value(frozenset({variable}))})
        registry = Registry(unit, analysis, functions)
        self.assertFalse(registry.data(Value(frozenset({ShapeConstraint('int')}))))
        self.assertFalse(registry.data(Value(frozenset({variable}))))
        self.assertFalse(registry.data(Value(unknown=True)))
        self.assertFalse(registry.data(Value(unbound=True)))


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class OrdinaryServiceExecutionTests(unittest.TestCase):
    def exercise(self, name, inputs, expected_services):
        source = SOURCES[name]
        expected = [subprocess.run([sys.executable, '-I', '-c', source], input=data,
                    capture_output=True, text=True, timeout=10) for data in inputs]
        original = native._Specializations.get
        for integer in ('i64', 'i128', 'bigint'):
            variants = {}
            def capture(owner, *args, **kwargs):
                variant = original(owner, *args, **kwargs)
                variants[variant.rust_name] = variant
                return variant
            with patch.object(native._Specializations, 'get', capture):
                result = transpile(source, TranspileOptions(filename='services.py', integer=integer, license='none'))
            self.assertTrue(result.success, result.diagnostics)
            self.assertTrue(variants)
            for variant in variants.values():
                wanted = expected_services[variant.node.name]
                header = next(line for line in result.rust_source.splitlines()
                              if line.startswith('fn ' + variant.rust_name + '('))
                self.assertEqual('native_input:' in header, wanted[0], header)
                self.assertEqual('native_output:' in header, wanted[1], header)
                self.assertEqual((variant.services.input, variant.services.output), wanted)
            for optimized in (False, True):
                with tempfile.TemporaryDirectory(prefix='pytors-services-') as directory:
                    path = Path(directory, 'main.rs')
                    binary = Path(directory, 'main')
                    path.write_text(result.rust_source)
                    built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []),
                        str(path), '-o', str(binary)], capture_output=True, text=True, timeout=120)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    for data, reference in zip(inputs, expected):
                        actual = subprocess.run([str(binary)], input=data, capture_output=True,
                            text=True, timeout=10, env={'PATH': '/no-python', 'PYTHONPATH': '/no-python'})
                        self.assertEqual((actual.stdout, actual.returncode), (reference.stdout, reference.returncode))
                        self.assertEqual(actual.stderr.rstrip().splitlines()[-1:] if actual.stderr else [],
                                         reference.stderr.rstrip().splitlines()[-1:] if reference.stderr else [])
                        self.assertEqual(re.findall(r'line (\d+), in ([^\n]+)', actual.stderr),
                                         re.findall(r'line (\d+), in ([^\n]+)', reference.stderr))

    def test_pure_transitive_helpers_use_only_python_arguments(self):
        self.exercise('pure_transitive_program_input', ('3\n', '-4\n'),
                      {'square': (False, False), 'advance': (False, False)})

    def test_output_service_propagates_without_input_transport(self):
        self.exercise('output_transitive', ('4\n',), {'emit': (False, True), 'route': (False, True)})

    def test_input_implicitly_retains_output_flush_service(self):
        self.exercise('input_transitive', ('2\n7\n',), {'read_one': (True, True), 'combine': (True, True)})

    def test_captured_input_alias_does_not_contaminate_pure_sibling(self):
        self.exercise('captured_input_alias', ('9\n',), {'read_one': (True, True), 'pure': (False, False)})

    def test_service_erasure_keeps_argument_effects_and_error_frames(self):
        self.exercise('argument_effect_error_order', ('',),
                      {'mark': (False, True), 'divide': (False, False), 'outer': (False, True)})
