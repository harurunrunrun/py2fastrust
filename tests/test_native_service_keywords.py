"""Named keyword labels are structural; values retain their IO effects."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions, native
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze, ScopeFacts
from py2fastrust.native_service_demands import Registry, NONE

SOURCES = {'expanded_argument_effect_control': 'def square(x):\n'
                                     '    return x*x\n'
                                     'def arguments(x):\n'
                                     '    print("expanded",x)\n'
                                     '    return {"x":x}\n'
                                     'def route(x):\n'
                                     '    return square(**arguments(x))\n'
                                     'print(route(int(input())))\n',
 'expanded_mapping_control': 'def square(x):\n'
                             '    return x*x\n'
                             'def route(x):\n'
                             '    options={"x":x}\n'
                             '    return square(**options)\n'
                             'print(route(int(input())))\n',
 'keyword_defaults_alias': 'def mix(a=3,*,b=5):\n'
                           '    return a*10+b\n'
                           'chosen=mix\n'
                           'def route(x):\n'
                           '    return chosen(b=x)+chosen(a=x)\n'
                           'print(route(int(input())))\n',
 'keyword_value_effect_order': 'def mix(a,*,b):\n'
                               '    return a*10+b\n'
                               'def mark(x):\n'
                               '    print("mark",x)\n'
                               '    return x\n'
                               'def route(x):\n'
                               '    return mix(b=mark(x+1),a=mark(x))\n'
                               'print(route(int(input())))\n',
 'positional_and_keyword': 'def square(x):\n'
                           '    return x*x\n'
                           'def route(x):\n'
                           '    return square(x)+square(x=x)\n'
                           'print(route(int(input())))\n',
 'print_keyword_output_only': 'def emit(x):\n'
                              '    print(x,end="!")\n'
                              '    return x+1\n'
                              'print(emit(int(input())))\n'}


def demands(source):
    unit = build_program(source, 'keywords.py').main
    analysis = analyze(unit)
    functions = {node: None for node in unit.tree.body if isinstance(node, ast.FunctionDef)}
    registry = Registry(unit, analysis, functions)
    return {node.name: registry.demand(node) for node in functions}


class NamedKeywordServiceTests(unittest.TestCase):
    def test_positional_and_named_source_calls_both_have_no_services(self):
        actual = demands(SOURCES['positional_and_keyword'])
        self.assertEqual(actual['square'], NONE)
        self.assertEqual(actual['route'], NONE)
        actual = demands(SOURCES['keyword_defaults_alias'])
        self.assertEqual(actual['mix'], NONE)
        self.assertEqual(actual['route'], NONE)

    def test_keyword_values_and_print_keep_their_output_service(self):
        actual = demands(SOURCES['keyword_value_effect_order'])
        self.assertTrue(actual['mark'].output)
        self.assertFalse(actual['mark'].input)
        self.assertTrue(actual['route'].output)
        self.assertFalse(actual['route'].input)
        actual = demands(SOURCES['print_keyword_output_only'])
        self.assertTrue(actual['emit'].output)
        self.assertFalse(actual['emit'].input)

    def test_mapping_expansion_has_no_implicit_no_io_certificate(self):
        source = SOURCES['expanded_mapping_control']
        unit = build_program(source, 'keywords.py').main
        route = next(node for node in unit.tree.body if isinstance(node, ast.FunctionDef) and node.name == 'route')
        registry = Registry(unit, None, {})
        actual = registry.body(unit.ordinal(route), route.body, ScopeFacts({}, {}, {}))
        self.assertTrue(actual.input)
        self.assertTrue(actual.output)
        self.assertFalse(actual.complete)
        self.assertTrue(any('mapping argument expansion' in item[1] for item in registry.reasons[unit.ordinal(route)]))

    @unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
    def test_named_calls_have_minimal_signatures_and_preserve_value_order(self):
        for name, stdin in [('positional_and_keyword', '3\n'), ('keyword_value_effect_order', '4\n')]:
            source = SOURCES[name]
            expected = subprocess.run([sys.executable, '-I', '-c', source], input=stdin,
                                      text=True, capture_output=True, timeout=10)
            for integer in ('i64', 'i128', 'bigint'):
                captured = {}
                original = native._Specializations.get
                def capture(owner, *args, **kwargs):
                    variant = original(owner, *args, **kwargs)
                    captured[variant.rust_name] = variant
                    return variant
                with patch.object(native._Specializations, 'get', capture):
                    result = transpile(source, TranspileOptions(integer=integer, filename='keywords.py', license='none'))
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(captured)
                for name, variant in captured.items():
                    header = next(line for line in result.rust_source.splitlines() if line.startswith('fn ' + name + '('))
                    self.assertEqual('native_input:' in header, variant.services.input, header)
                    self.assertEqual('native_output:' in header, variant.services.output, header)
                    self.assertFalse(variant.services.input, header)
                for optimized in (False, True):
                    with tempfile.TemporaryDirectory(prefix='pytors-keywords-') as directory:
                        path, binary = Path(directory, 'main.rs'), Path(directory, 'main')
                        path.write_text(result.rust_source)
                        built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []),
                                                str(path), '-o', str(binary)], text=True, capture_output=True, timeout=120)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        actual = subprocess.run([str(binary)], input=stdin, text=True, capture_output=True, timeout=10)
                        self.assertEqual((actual.stdout, actual.stderr, actual.returncode),
                                         (expected.stdout, expected.stderr, expected.returncode))
