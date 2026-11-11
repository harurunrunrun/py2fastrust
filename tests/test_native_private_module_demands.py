"""Private arithmetic keeps its actual module whenever a global is read."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_private_module_demands as demands
from py2fastrust.native_call_context_effects import source_plan
import test_native_lambda_callbacks as helpers


BASE = '''class Context:
 stack = []
 def __init__(self, value): self.value = value
 def __enter__(self): self.stack.append(self.value)
 def __exit__(self, kind, value, trace): self.stack.pop()
 @classmethod
 def current(cls): return cls.stack[-1]
class Quantity:
 def __init__(self, value): self.value = value + Context.current()
 def __mul__(self, factor): return Quantity(self.value * factor)
'''
MAIN = '''from arithmetic import Context, Quantity
OFFSET = 900
with Context(int(input())):
 value = Quantity(2)
 print((value * 3).value)
'''


class PrivateCallPointContracts(unittest.TestCase):
    def fixture(self):
        model = SimpleNamespace(call_edges={1:{2}},
            call_edges_by_site={(1,11):{2},(1,12):{2}})
        mode = SimpleNamespace(calls={11:{2}})
        state = SimpleNamespace(modes={('function',1):mode},plans={2:object()})
        return model,state,mode

    def test_one_witnessed_call_cannot_certify_another_call_to_the_same_function(self):
        model,state,mode = self.fixture()
        with patch('py2fastrust.native_call_context_effects.incoming_module', return_value=True):
            self.assertFalse(demands.calls_closed(model,state,1,{2}))
            mode.calls[12] = {2}
            self.assertTrue(demands.calls_closed(model,state,1,{2}))

    def test_an_independent_ordinary_certificate_can_cover_the_other_call(self):
        model,state,_ = self.fixture()
        with patch('py2fastrust.native_call_context_effects.incoming_module', return_value=False):
            self.assertTrue(demands.calls_closed(model,state,1,set()))

    def test_an_unaccounted_original_edge_is_never_assumed_private(self):
        model,state,mode = self.fixture()
        model.call_edges[1].add(3)
        mode.calls[12] = {2}
        self.assertFalse(demands.calls_closed(model,state,1,{2}))


class PrivateDemandEvidence(unittest.TestCase):
    def convert(self, library):
        seen = []
        original = demands.prepare
        def observe(model):
            original(model)
            seen.append(model)
            # An analysis probe cannot register an actual emitted capability.
            self.assertEqual(model.operand_demands.accesses, [])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'arithmetic.py').write_text(library)
            with patch.object(demands, 'prepare', observe):
                result = transpile(MAIN, TranspileOptions(filename=str(root / 'main.py'), license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(seen)
        model = seen[-1]
        entries = {source_plan(abi.plan).node.name: index in model.private_module_demands
                   for index, abi in model.source_state.abis.items()}
        return result, entries

    def test_receiver_and_real_scalar_witness_supply_the_arithmetic_context(self):
        _, entries = self.convert(BASE)
        self.assertTrue(entries['__mul__'])
        self.assertTrue(entries['current'])

    def test_a_global_read_retains_the_actual_defining_module(self):
        library = 'OFFSET = 11\n' + BASE.replace(
            'Quantity(self.value * factor)', 'Quantity(self.value * factor + OFFSET)')
        _, entries = self.convert(library)
        self.assertFalse(entries['__mul__'])

    def test_a_transitive_global_read_also_retains_the_defining_module(self):
        library = 'OFFSET = 11\n' + BASE.replace(
            'return cls.stack[-1]', 'return cls.stack[-1] + OFFSET')
        _, entries = self.convert(library)
        self.assertFalse(entries['current'])
        self.assertFalse(entries['__mul__'])


@unittest.skipUnless(helpers.shutil.which('rustc'), 'rustc is required')
class PrivateDemandExecution(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    def exercise(self, library, inputs):
        root = Path(self.directory.name) / hashlib.sha256(library.encode()).hexdigest()
        root.mkdir()
        main = root / 'main.py'
        main.write_text(MAIN)
        (root / 'arithmetic.py').write_text(library)
        expected = [subprocess.run([sys.executable, '-B', str(main)],
                    input=data, text=True, capture_output=True, timeout=10) for data in inputs]
        for mode in ('i64', 'i128', 'bigint'):
            converted = transpile(MAIN, TranspileOptions(filename=str(main), integer=mode, license='none'))
            self.assertTrue(converted.success, converted.diagnostics)
            for optimized in (False, True):
                rust = root / (mode + ('_opt' if optimized else '_debug') + '.rs')
                rust.write_text(converted.rust_source)
                binary = rust.with_suffix('')
                built = subprocess.run(['rustc', '--edition=2021', '--crate-name', 'private_context',
                    *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                    text=True, capture_output=True, timeout=120)
                self.assertEqual(built.returncode, 0, built.stderr)
                for data, reference in zip(inputs, expected):
                    actual = subprocess.run([str(binary)], input=data, text=True,
                        capture_output=True, timeout=10, env={**os.environ, 'PATH': '/no-python'})
                    self.assertEqual((actual.stdout, actual.returncode),
                                     (reference.stdout, reference.returncode), actual.stderr)
                    frames = r'File "[^"]+", line (\d+), in ([^\n]+)'
                    self.assertEqual(re.findall(frames, actual.stderr), re.findall(frames, reference.stderr))
                    self.assertEqual(actual.stderr.splitlines()[-1:] , reference.stderr.splitlines()[-1:])

    def test_cross_module_arithmetic_and_original_error(self):
        self.exercise(BASE, ('7\n', '-2\n', 'bad\n'))

    def test_cross_module_global_must_not_read_the_callers_namespace(self):
        library = 'OFFSET = 11\n' + BASE.replace(
            'Quantity(self.value * factor)', 'Quantity(self.value * factor + OFFSET)')
        self.exercise(library, ('7\n', '-2\n'))


if __name__ == '__main__':
    unittest.main()
