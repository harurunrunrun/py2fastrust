"""Closed builtin integer mapping/set folds retain call and arithmetic policy."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions, native_typed_continuations
from py2fastrust import native_integer_mapping_folds as folds
from wrapping_reference import execute

SOURCES = {'captured_sum_alias': 'combine=sum\n'
                       'def total(values, start):\n'
                       ' return combine(values,start=start)\n'
                       'print(total({-1,2,6},3))\n',
 'dictionary_keys_values': 'counts={3:7,-2:11,4:-5}\n'
                           'print(sum(counts),sum(counts.keys(),2),sum(counts.values(),-3))\n',
 'dictionary_string_keys_values': 'def total(counts):\n'
                                  ' return sum(counts.values(),start=4)\n'
                                  'print(total({"red":7,"blue":-2}))\n',
 'empty_and_nonempty_set_boolean': 'def total(values,start):\n'
                                   ' return sum(values,start)\n'
                                   'print(total(set(),False),total(set(),True),total({False},False),total({1},False),total({True},True))\n',
 'empty_and_nonempty_view_boolean': 'def total(values,start):\n'
                                    ' return sum(values,start=start)\n'
                                    'a={}\n'
                                    'b={1:False}\n'
                                    'c={2:7}\n'
                                    'print(total(a.values(),True),total(b.values(),False),total(c.values(),True))\n',
 'empty_dictionary_boolean': 'items={}\n'
                             'print(sum(items,True),sum(items.values(),False))\n',
 'float_fold_control': 'values={1.5,2.25}\nprint(sum(values))\n',
 'function_local_containers': 'def calculate(n,offset):\n'
                              ' values=[0]*(n+2)\n'
                              ' seen=set()\n'
                              ' counts={}\n'
                              ' for i in range(n):\n'
                              '  key=(i+offset)%7\n'
                              '  seen.add(key)\n'
                              '  counts[key]=counts.get(key,0)+1\n'
                              '  values[i]=i*i\n'
                              ' return '
                              'sum(values)+sum(seen)+sum(counts.values())\n'
                              'print(calculate(int(input()),3),calculate(0,7),calculate(8,-9))\n',
 'integer_width_boundaries': 'def total(values,start):\n'
                             ' return sum(values,start)\n'
                             'maximum=(1<<63)-1\n'
                             'values={maximum,1}\n'
                             'print(total(values,1))\n'
                             'mapping={0:(1<<127)-1,1:2}\n'
                             'print(total(mapping.values(),1))\n',
 'invalid_string_start': 'values={1,2}\nprint(sum(values,"prefix"))\n',
 'iterable_and_start_order': 'def values():\n'
                             ' print("values")\n'
                             ' return {4,8}\n'
                             'def begin():\n'
                             ' print("start")\n'
                             ' return 3\n'
                             'print(sum(values(),begin()))\n',
 'non_integer_key_control': 'values={(1,2),(3,4)}\nprint(sum(values))\n',
 'non_integer_value_control': 'values={1:None}\nprint(sum(values.values()))\n',
 'parameter_mappings': 'def total(values):\n'
                       ' return sum(values)\n'
                       'print(total({1,3,7}),total({2:8,4:9}))\n',
 'set_boolean_start': 'print(sum({False,True}),sum({True},True),sum(set(),True),sum(set(),False))\n',
 'set_integer_start': 'def total(values, start):\n'
                      ' return sum(values,start=start)\n'
                      'a={-8,2,9,2}\n'
                      'print(total(a,7),sum(a),sum(set(),-3))\n',
 'set_live_start_mutation': 'items={1,2}\n'
                            'def begin():\n'
                            ' items.add(5)\n'
                            ' print("start")\n'
                            ' return 10\n'
                            'print(sum(items,begin()))\n',
 'source_sum_shadow': 'def sum(values,start):\n'
                      ' print("source",len(values),start)\n'
                      ' return 17\n'
                      'print(sum({1,2},True))\n',
 'start_error_order': 'def values():\n'
                      ' print("iterable")\n'
                      ' return {1,2}\n'
                      'def begin():\n'
                      ' print("start")\n'
                      ' return 1//int(input())\n'
                      'print(sum(values(),begin()))\n',
 'view_insertion_alias': 'items={1:4,2:7}\n'
                         'alias=items\n'
                         'view=alias.values()\n'
                         'alias[3]=9\n'
                         'print(sum(view),sum(items))\n',
 'view_live_start_mutation': 'items={1:2,2:3}\n'
                             'view=items.values()\n'
                             'def begin():\n'
                             ' items[1]=11\n'
                             ' items[3]=7\n'
                             ' print("start")\n'
                             ' return -2\n'
                             'print(sum(view,begin()))\n'}


class IntegerMappingFoldProofTests(unittest.TestCase):
    def test_only_actual_registered_mapping_generation_is_a_fold_owner(self):
        models = []
        original = native_typed_continuations.prepare
        def capture(model):
            original(model)
            models.append(model)
        for filename in ('first.py', 'second.py'):
            with patch.object(native_typed_continuations, 'prepare', capture):
                result = transpile(SOURCES['function_local_containers'],
                                   TranspileOptions(filename=filename, license='none'))
            self.assertTrue(result.success, result.diagnostics)
        first, second = models[0], models[-1]
        self.assertIsNot(first, second)
        for record in first.mappings.records:
            self.assertTrue(folds.registered(first, record.kind))
            self.assertFalse(folds.registered(second, record.kind))
        for record in first.mappings.views.records:
            self.assertTrue(folds.registered(first, record.kind))
            self.assertFalse(folds.registered(second, record.kind))
        self.assertFalse(folds.registered(first, 'int'))

    def test_non_integer_protocol_controls_remain_positioned_diagnostics(self):
        for name in ('invalid_string_start', 'float_fold_control',
                     'non_integer_value_control', 'non_integer_key_control'):
            result = transpile(SOURCES[name], TranspileOptions(filename='unsupported.py', license='none'))
            self.assertFalse(result.success, name)
            self.assertTrue(result.diagnostics, name)
            self.assertTrue(all(item.line > 0 for item in result.diagnostics), name)


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class IntegerMappingFoldExecutionTests(unittest.TestCase):
    def exercise(self, names, *, inputs=None, wrapping=False):
        for name in names:
            source = SOURCES[name]
            data = ('',) if inputs is None else inputs
            for integer in ('i64', 'i128', 'bigint'):
                if wrapping:
                    expected = [(execute(source, integer, stdin).stdout, '', 0) for stdin in data]
                else:
                    expected = []
                    for stdin in data:
                        result = subprocess.run([sys.executable, '-I', '-S', '-c', source],
                            input=stdin, text=True, capture_output=True, timeout=10)
                        expected.append((result.stdout, result.stderr, result.returncode))
                selected = []
                original = folds.emit
                def capture(*args, **kwargs):
                    code = original(*args, **kwargs)
                    if code is not None:
                        selected.append(code)
                    return code
                with patch.object(folds, 'emit', capture):
                    result = transpile(source, TranspileOptions(integer=integer, filename='folds.py', license='none'))
                self.assertTrue(result.success, result.diagnostics)
                self.assertTrue(selected, (name, integer))
                self.assertTrue(all('.entries.iter()' in code for code in selected))
                self.assertNotIn('enum Value', result.rust_source)
                for optimized in (False, True):
                    with tempfile.TemporaryDirectory(prefix='pytors-integer-folds-') as directory:
                        path, binary = Path(directory, 'main.rs'), Path(directory, 'main')
                        path.write_text(result.rust_source)
                        built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if optimized else []),
                            str(path), '-o', str(binary)], capture_output=True, text=True, timeout=120)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        for stdin, wanted in zip(data, expected):
                            actual = subprocess.run([str(binary)], input=stdin, capture_output=True,
                                text=True, timeout=10, env={'PATH':'/pytors-no-python','PYTHONPATH':'/pytors-no-python'})
                            self.assertEqual((actual.stdout, actual.stderr, actual.returncode), wanted, (name, integer, optimized))

    def test_unchanged_function_local_container_program(self):
        self.exercise(('function_local_containers',), inputs=('0\n', '1\n', '17\n'))

    def test_runtime_empty_boolean_start_and_nonempty_integer_results(self):
        self.exercise(('empty_and_nonempty_set_boolean', 'empty_and_nonempty_view_boolean'))

    def test_start_effects_finish_before_borrowing_set_or_live_view(self):
        self.exercise(('set_live_start_mutation', 'view_live_start_mutation'))

    def test_per_operator_integer_width_policy(self):
        self.exercise(('integer_width_boundaries',), wrapping=True)
