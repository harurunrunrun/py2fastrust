"""Actual callable captures and typed transfer coverage share source binding."""
from pathlib import Path
from types import SimpleNamespace
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_typed_continuations as continuations
from py2fastrust import native_captured_invocations as captured
from py2fastrust.native_class_calls import entry_result, synchronous
from py2fastrust.rust_pruning import _lex
from test_native_typed_continuations import frames

# Exact original project bytes, frozen independently before their conversion.
PROJECTS = {'imported_recursive_function': {'arithmetic.py': 'offset = 3\n'
                                                  'def total(n):\n'
                                                  '    if n == 0:\n'
                                                  '        return offset\n'
                                                  '    return total(n - 1) + n\n',
                                 'main.py': 'import arithmetic\n'
                                            'from arithmetic import total\n'
                                            'print(total(int(input())))\n'
                                            'arithmetic.offset = 9\n'
                                            'print(total(2))\n'},
 'imported_capture_before_argument_module_write': {'arithmetic.py': 'offset = 2\n'
                                                                    'def total(n):\n'
                                                                    '    if n == 0:\n'
                                                                    '        return offset\n'
                                                                    '    return total(n - 1) + '
                                                                    'offset\n',
                                                   'main.py': 'import arithmetic\n'
                                                              'saved = arithmetic.total\n'
                                                              'def argument():\n'
                                                              '    arithmetic.offset = 7\n'
                                                              '    arithmetic.total = replacement\n'
                                                              '    return 3\n'
                                                              'def replacement(n):\n'
                                                              '    return 100 + n\n'
                                                              'print(saved(argument()), '
                                                              'arithmetic.total(2))\n'},
 'finite_recursive_functions': {'main.py': 'def squares(n):\n'
                                           '    if n == 0:\n'
                                           '        return 0\n'
                                           '    return squares(n - 1) + n * n\n'
                                           'def triangles(n):\n'
                                           '    if n == 0:\n'
                                           '        return 0\n'
                                           '    return triangles(n - 1) + n\n'
                                           'selected = squares if int(input()) else triangles\n'
                                           'print(selected(5), selected(0))\n'},
 'implicit_map_recursive_callback': {'main.py': 'def digit_sum(n):\n'
                                                '    if n < 10:\n'
                                                '        return n\n'
                                                '    return digit_sum(n // 10) + n % 10\n'
                                                'callback = digit_sum\n'
                                                'print(list(map(callback, [0, 123, 809])))\n'},
 'unrelated_used_cleanup': {'kernel.py': 'offset = 2\n'
                                         'def total(n):\n'
                                         '    if n == 0:\n'
                                         '        return offset\n'
                                         '    return total(n - 1) + n\n',
                            'main.py': 'import kernel\n'
                                       'events = []\n'
                                       'class Context:\n'
                                       '    def __enter__(self):\n'
                                       '        events.append("enter")\n'
                                       '        return self\n'
                                       '    def __exit__(self, kind, error, trace):\n'
                                       '        events.append("exit")\n'
                                       '        return False\n'
                                       'def cleanup(n):\n'
                                       '    if n:\n'
                                       '        return cleanup(n - 1)\n'
                                       '    with Context():\n'
                                       '        events.append("body")\n'
                                       '    return None\n'
                                       'print(kernel.total(4))\n'
                                       'cleanup(2)\n'
                                       'print(events)\n'},
 'imported_default_binding': {'kernel.py': 'step = 2\n'
                                           'def total(n, amount=step):\n'
                                           '    if n == 0:\n'
                                           '        return amount\n'
                                           '    return total(n - 1) + amount\n',
                              'main.py': 'import kernel\n'
                                         'saved = kernel.total\n'
                                         'kernel.step = 99\n'
                                         'print(saved(3), saved(2, amount=5))\n'},
 'target_original': {'kernel.py': 'slots = [0]\n'
                                  '\n'
                                  'def recurse(n):\n'
                                  '    if n == 0:\n'
                                  '        return 0\n'
                                  '    for slots[recurse(n - 1)] in range(1):\n'
                                  '        pass\n'
                                  '    return 0\n',
                     'main.py': 'from kernel import recurse\n\nprint(recurse(int(input())))\n'},
 'assign_before_target': {'kernel.py': 'slots = [0]\n'
                                       'def recurse(n):\n'
                                       '    depth = n\n'
                                       '    if depth == 0:\n'
                                       '        return 0\n'
                                       '    for slots[recurse(depth - 1)] in range(1):\n'
                                       '        pass\n'
                                       '    return 0\n',
                          'main.py': 'from kernel import recurse\nprint(recurse(int(input())))\n'},
 'implicit_reentry_cycle': {'main.py': 'def relay(value):\n'
                                       '    return accumulate(value)\n'
                                       'def accumulate(n):\n'
                                       '    if n == 0:\n'
                                       '        return 1\n'
                                       '    return list(map(relay, [n - 1]))[0] + n\n'
                                       'print(accumulate(int(input())))\n'}}


class CapturedInvocationProjects(unittest.TestCase):
    def project(self, name):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        for filename, source in PROJECTS[name].items():
            (directory / filename).write_text(source)
        source = directory / 'main.py'
        # Execute the unchanged original file before its first conversion.
        expected = subprocess.run([sys.executable, '-S', str(source)], input='4\n',
                                  text=True, capture_output=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        return directory, source, expected

    def capture(self, source, integer='i64'):
        models = []
        original = continuations.prepare
        def prepare(model):
            original(model)
            models.append(model)
        with patch.object(continuations, 'prepare', prepare):
            result = transpile(source.read_text(), TranspileOptions(
                filename=str(source), integer=integer, license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertTrue(models)
        return result, models[-1]


class CapturedInvocationProofTests(CapturedInvocationProjects):
    def test_captured_module_regions_have_owned_physical_result_entries(self):
        _, source, _ = self.project('imported_recursive_function')
        for mode in ('i64', 'i128', 'bigint'):
            with self.subTest(integer=mode):
                result, model = self.capture(source, mode)
                registry = model.typed_continuations
                self.assertTrue(registry.captured)
                self.assertTrue(registry.plans)
                self.assertNotIn('->ClassFuture<', result.rust_source)
                for plan in registry.plans.values():
                    self.assertTrue(entry_result(model, plan))
                    self.assertFalse(synchronous(model, plan))
                    abi = registry.region_proof.abis[plan.index]
                    self.assertTrue(abi.actual_scope)
                    self.assertIsNone(abi.lexical_environment)
                    self.assertFalse(abi.constructor_role)

    def test_selected_source_edges_are_actual_transfers_not_entry_reentry(self):
        _, source, _ = self.project('imported_recursive_function')
        result, model = self.capture(source)
        registry = model.typed_continuations
        expected = {(caller, site, target)
                    for (caller, site), targets in model.call_edges_by_site.items()
                    for target in targets if caller in registry.plans and target in registry.plans}
        actual = {(site.caller.index, id(site.node), site.callee.index) for site in registry.sites}
        self.assertEqual(actual, expected)
        self.assertTrue(all(site.owned_child for site in registry.sites))
        tokens, _, pairs = _lex(result.rust_source)
        name = next(i for i, token in enumerate(tokens) if token.text == 'class_native_region'
                    and i and tokens[i - 1].text == 'fn')
        opening = next(i for i in range(name, len(tokens)) if tokens[i].text == '{')
        body = result.rust_source[tokens[opening].end:tokens[pairs[opening]].start]
        for builder in registry.builders.values():
            self.assertNotRegex(body, r'\b' + re.escape(builder.emitter.function_name(builder.plan)) + r'\s*\(')

    def test_default_binding_keeps_original_signature_and_captured_storage(self):
        _, source, _ = self.project('imported_default_binding')
        result, model = self.capture(source)
        self.assertTrue(model.typed_continuations.captured)
        self.assertNotIn('->ClassFuture<', result.rust_source)
        self.assertIn('class_default_', result.rust_source)

    def test_used_cleanup_component_does_not_disable_independent_region(self):
        _, source, _ = self.project('unrelated_used_cleanup')
        result, model = self.capture(source)
        registry = model.typed_continuations
        self.assertTrue(registry.plans)
        self.assertTrue(registry.captured)
        selected = {getattr(plan.node, 'name', '') for plan in registry.plans.values()}
        self.assertIn('total', selected)
        self.assertNotIn('cleanup', selected)
        self.assertIn('ClassFuture<', result.rust_source)
        self.assertIn('class_with_', result.rust_source)

    def test_recursive_targets_after_ordinary_assignment_keep_prior_abi(self):
        for name in ('target_original', 'assign_before_target'):
            _, source, _ = self.project(name)
            for mode in ('i64', 'i128', 'bigint'):
                with self.subTest(source=name, integer=mode):
                    result, model = self.capture(source, mode)
                    self.assertFalse(model.typed_continuations.plans)
                    reasons = model.typed_continuations.region_proof.reasons.values()
                    self.assertTrue(any('typed place' in reason for reason in reasons))
                    with patch.object(captured, 'install_regions', lambda registry: False):
                        old = transpile(source.read_text(), TranspileOptions(
                            filename=str(source), integer=mode, license='none'))
                    self.assertTrue(old.success, old.diagnostics)
                    self.assertEqual(result.rust_source, old.rust_source)

    def test_implicit_callback_cycle_and_finite_payload_keep_existing_convention(self):
        for name in ('implicit_reentry_cycle', 'implicit_map_recursive_callback',
                     'finite_recursive_functions', 'imported_capture_before_argument_module_write'):
            _, source, _ = self.project(name)
            result, model = self.capture(source)
            self.assertFalse(model.typed_continuations.plans)
            with patch.object(captured, 'install_regions', lambda registry: False):
                old = transpile(source.read_text(), TranspileOptions(filename=str(source), license='none'))
            self.assertTrue(old.success, old.diagnostics)
            self.assertEqual(result.rust_source, old.rust_source)


class ErrorLayoutInteropTests(unittest.TestCase):
    SOURCE = ('struct NativeErrorData{message:String,line:usize,function:&\'static str,frames:Vec<()>}'
              'fn pass(mut error:NativeErrorData)->NativeErrorData{error}'
              'fn borrowed(error:&NativeErrorData)->&NativeErrorData{error}'
              'fn borrowed_mut(error:&mut NativeErrorData)->&mut NativeErrorData{error}'
              'impl NativeErrorData{fn touch(&self){}}'
              'fn make(flag:bool)->NativeErrorData{if flag{NativeErrorData{message:String::new(),line:1,function:"f",frames:Vec::new()}}'
              'else{NativeErrorData{message:String::new(),line:2,function:"g",frames:Vec::new()}}}'
              'fn main(){let result:Result<(),NativeError>=Ok(());if let Err(error)=result {}}')

    def test_cleanup_layout_leaves_return_types_and_impl_blocks_intact(self):
        from py2fastrust.native_context_managers import runtime
        source = runtime(self.SOURCE, SimpleNamespace(context_managers=SimpleNamespace(used=True)))
        self.assertIn('->NativeErrorData{error}', source)
        self.assertIn('->&NativeErrorData{error}', source)
        self.assertIn('->&mut NativeErrorData{error}', source)
        self.assertIn('impl NativeErrorData{fn touch(&self){}}', source)
        self.assertIn('frames:Vec<()>,context:Option<Box<NativeError>>', source)
        self.assertIn('frames:Vec::new(),context:None', source)
        self.assertEqual(source.count('frames:Vec::new(),context:None'), 2)

    def test_exception_payload_layout_leaves_return_types_and_impl_blocks_intact(self):
        from py2fastrust.native_exception_runtime import runtime
        model = SimpleNamespace(exceptions=SimpleNamespace(used=True, records={}),
                                context_managers=SimpleNamespace(used=False), filename='source.py')
        source = runtime(self.SOURCE, model)
        self.assertIn('->NativeErrorData{error}', source)
        self.assertIn('->&NativeErrorData{error}', source)
        self.assertIn('->&mut NativeErrorData{error}', source)
        self.assertIn('impl NativeErrorData{fn touch(&self){}}', source)
        self.assertIn('frames:Vec::new(),exception_kind:None', source)
        self.assertEqual(source.count('frames:Vec::new(),exception_kind:None'), 2)


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class CapturedInvocationExecutionTests(CapturedInvocationProjects):
    def exercise(self, name):
        directory, source, expected = self.project(name)
        for mode in ('i64', 'i128', 'bigint'):
            result, model = self.capture(source, mode)
            self.assertTrue(model.typed_continuations.captured)
            self.assertLess(len(result.rust_source.encode()), 512 * 1024)
            for optimized in (False, True):
                with self.subTest(source=name, integer=mode, optimized=optimized):
                    rust = directory / (mode + ('_O' if optimized else '') + '.rs')
                    binary = rust.with_suffix('.bin')
                    rust.write_text(result.rust_source)
                    build = subprocess.run(['rustc', '--edition=2021', '--crate-name', 'captured_calls',
                                            *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                                           text=True, capture_output=True, timeout=180)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    actual = subprocess.run([str(binary)], input='4\n', text=True,
                                            capture_output=True, timeout=20)
                    self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                    self.assertEqual(actual.stdout, expected.stdout)
                    self.assertEqual(frames(actual.stderr), frames(expected.stderr))
                    self.assertEqual(actual.stderr.rstrip().splitlines()[-1:],
                                     expected.stderr.rstrip().splitlines()[-1:])

    def test_imported_module_updates_are_observed_by_original_callable(self):
        self.exercise('imported_recursive_function')

    def test_defaults_remain_bound_to_the_original_definition(self):
        self.exercise('imported_default_binding')

    def test_unrelated_recursive_cleanup_remains_interoperable(self):
        self.exercise('unrelated_used_cleanup')
