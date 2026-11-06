"""Private effect-only class receivers preserve original capture and binding."""
import ast
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest import mock

from py2fastrust import native_aot_callables as calls
from py2fastrust import native_immediate_classmethod as immediate
from py2fastrust.native import _Expression
from py2fastrust.native_module_linking import ClassReferenceType
import test_native_source_state as _source_tests

# Exact new CP-first sources; no adaptation.
SOURCES = {'manager_helper_constructor_integer': 'class Ledger:\n'
                                       '    entries = []\n'
                                       '    def __init__(self, value):\n'
                                       '        self.value = value\n'
                                       '    def __enter__(self):\n'
                                       '        Ledger.entries.append(self.value)\n'
                                       '        return self\n'
                                       '    def __exit__(self, typ, error, trace):\n'
                                       '        Ledger.entries.pop()\n'
                                       '    @classmethod\n'
                                       '    def latest(cls):\n'
                                       '        return cls.entries[-1]\n'
                                       '\n'
                                       'class Sample:\n'
                                       '    def __init__(self):\n'
                                       '        self.value = Ledger.latest()\n'
                                       '    def read(self):\n'
                                       '        return self.value\n'
                                       'def make_sample():\n'
                                       '    return Sample()\n'
                                       'with Ledger(int(input())):\n'
                                       '    print(make_sample().read())\n',
 'manager_helper_constructor_boolean': 'class Switches:\n'
                                       '    active = []\n'
                                       '    def __init__(self, value):\n'
                                       '        self.value = value\n'
                                       '    def __enter__(self):\n'
                                       '        Switches.active.append(self.value)\n'
                                       '        return self\n'
                                       '    def __exit__(self, typ, error, trace):\n'
                                       '        Switches.active.pop()\n'
                                       '    @classmethod\n'
                                       '    def current(cls):\n'
                                       '        return cls.active[-1]\n'
                                       'class Reading:\n'
                                       '    def __init__(self):\n'
                                       '        self.value = Switches.current()\n'
                                       '    def read(self):\n'
                                       '        return self.value\n'
                                       'def measure():\n'
                                       '    return Reading()\n'
                                       'with Switches(bool(int(input()))):\n'
                                       '    print(measure().read())\n'}


class ImmediateOperandContracts(unittest.TestCase):
    def token(self):
        from py2fastrust.native_operand_demands import ClassOperand
        return ClassOperand(ClassReferenceType(3), object())

    def request(self, node):
        return immediate.Request(node.func, object(), direct_definition=4)

    def test_declined_access_keeps_existing_capture_flags(self):
        node = ast.parse('Owner.read()').body[0].value
        request = self.request(node)
        with mock.patch('py2fastrust.native_operand_demands.capture_access', return_value=None) as access:
            self.assertIsNone(immediate.capture_operand(object(), node, request))
        access.assert_called_once()
        self.assertFalse(request.used)
        self.assertFalse(request.direct_used)
        self.assertTrue(request.module)

    def test_only_approved_access_marks_a_direct_private_capture(self):
        node = ast.parse('Owner.read()').body[0].value
        request = self.request(node)
        token = self.token()
        self.assertFalse(hasattr(token, 'code'))
        with mock.patch('py2fastrust.native_operand_demands.capture_access', return_value=('checked_presence;', token)):
            before, captured = immediate.capture_operand(object(), node, request)
        self.assertEqual(before, 'checked_presence;')
        self.assertIs(captured, token)
        self.assertTrue(request.used and request.direct_used)
        self.assertFalse(request.module)

    def test_unprepared_member_never_requests_payload_erasure(self):
        node = ast.parse('Owner.read()').body[0].value
        request = immediate.Request(node.func, object())
        with mock.patch('py2fastrust.native_operand_demands.capture_access') as access:
            self.assertIsNone(immediate.capture_operand(object(), node, request))
        access.assert_not_called()

    def test_opaque_receiver_enters_the_original_source_binder(self):
        node = ast.parse('Owner.read(7, extra=9)').body[0].value
        request = self.request(node)
        request.used = request.direct_used = True
        request.module = False
        token = self.token()
        plan = object()
        provider = SimpleNamespace(plans={4: plan},
            model=SimpleNamespace(cell_for_kind=lambda kind: object()),
            call_context_setup=mock.Mock(return_value=''))
        emitter = SimpleNamespace(model=SimpleNamespace(callable_cells=provider))
        site = calls.CallSite(object(), object())
        argument = _Expression('captured_argument', 'int')
        keyword = _Expression('captured_keyword', 'int')
        with mock.patch.object(calls, 'emit_definition_body', return_value='original_bound_body') as bind:
            result = immediate.invoke(emitter, node, request, site, token,
                                      [argument], [('extra', keyword)], 'int')
        self.assertEqual(result.code, '{original_bound_body}')
        self.assertIs(bind.call_args.args[4][0], token)
        self.assertIs(bind.call_args.args[4][1], argument)
        self.assertEqual(bind.call_args.args[5], [('extra', keyword)])
        self.assertEqual(bind.call_args.args[3], request.direct_definition)
        provider.call_context_setup.assert_called_once_with(emitter, plan)
        self.assertNotIn('class_selected_method', result.code)

    def test_existing_binding_error_never_demands_receiver_value(self):
        node = ast.parse('Owner.read(7)').body[0].value
        request = self.request(node)
        request.used = request.direct_used = True
        request.module = False
        site = calls.CallSite(object(), object(), errors={request.target: 'TypeError: original binding error'})
        emitter = SimpleNamespace(model=SimpleNamespace(callable_cells=object()),
                                  at=lambda code, node: code, rust_type=lambda kind: 'NativeInt')
        with mock.patch.object(calls, 'emit_definition_body') as bind:
            result = immediate.invoke(emitter, node, request, site, self.token(), [], [], 'int')
        bind.assert_not_called()
        self.assertIn('TypeError: original binding error', result.code)

    def test_callee_effects_precede_unchanged_positional_and_keyword_arguments(self):
        node = ast.parse('Owner.read(first(), extra=second())').body[0].value
        request = self.request(node)
        token = self.token()
        events = []
        site = calls.CallSite(object(), object())
        provider = SimpleNamespace(sites={(5, id(node)): site})
        def expression(value):
            self.assertIsNot(value, node.func, 'approved capture must not evaluate the class payload')
            label = value.func.id
            events.append(label)
            return _Expression(label, 'int')
        emitter = SimpleNamespace(plan=SimpleNamespace(index=5),
            model=SimpleNamespace(callable_cells=provider), expression=expression,
            capture=lambda value: ('capture_' + value.code + ';', value), kind=lambda value: 'int')
        @contextmanager
        def capture_callee(emitter, function):
            self.assertIs(function, node.func)
            yield request
        @contextmanager
        def capture_global(emitter, function):
            yield None
        def capture_operand(emitter, call, actual_request):
            events.append('callee')
            request.used = request.direct_used = True
            request.module = False
            return 'checked_presence;', token
        with mock.patch.object(immediate, 'capture_callee', capture_callee), \
             mock.patch.object(immediate, 'capture_operand', capture_operand), \
             mock.patch('py2fastrust.native_global_callable_payload.capture', capture_global), \
             mock.patch('py2fastrust.native_class_binding_contexts.captured_constructor', return_value=None), \
             mock.patch('py2fastrust.native_binding_places.capture') as old_capture, \
             mock.patch.object(immediate, 'invoke', return_value=_Expression('invoked', 'int')) as invoke:
            result = calls.emit_call(emitter, node)
        self.assertEqual(events, ['callee', 'first', 'second'])
        self.assertEqual(result.code, '{checked_presence;capture_first;capture_second;invoked}')
        self.assertIs(invoke.call_args.args[4], token)
        old_capture.assert_not_called()


@unittest.skipUnless(_source_tests.shutil.which('rustc'), 'rustc required')
class ImmediateOperandExecution(unittest.TestCase):
    def exercise(self, name, inputs):
        with mock.patch.dict(_source_tests.SOURCES, SOURCES):
            _source_tests.NativeSourceStateExecutionTests.exercise(self, name, inputs)

    def test_runtime_integer_manager_helper_and_constructor(self):
        self.exercise('manager_helper_constructor_integer', ('7\n', '-5\n'))

    def test_runtime_boolean_manager_helper_and_constructor(self):
        self.exercise('manager_helper_constructor_boolean', ('0\n', '1\n'))
