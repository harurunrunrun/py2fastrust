"""Physical variants keep the solved source ranks and all depth safeguards."""
from types import SimpleNamespace
import unittest as testing
from unittest.mock import patch

from py2fastrust import native_finite_depth_calls as finite


RUNTIME = '''use std::cell::RefCell;
struct ClassControl{depth:usize,limit:usize}
struct ClassScope{control:RefCell<ClassControl>}
struct ClassSyncDepth<'a>(&'a ClassScope);
impl Drop for ClassSyncDepth<'_>{fn drop(&mut self){self.0.control.borrow_mut().depth-=1;}}
fn class_sync_call<T>(scope:&ClassScope,call:impl FnOnce()->Result<T,String>)->Result<T,String>{
{let mut control=scope.control.borrow_mut();if control.depth>=control.limit{return Err("RecursionError".into());}control.depth+=1;}
let _depth=ClassSyncDepth(scope);
call().map_err(|error|error)
}
'''


def model(heights=(10, 9, 8)):
    plans = [SimpleNamespace(index=index, reachable=True) for index in range(len(heights))]
    result = SimpleNamespace(plans=plans, classes={},
                             native_call_heights=dict(enumerate(heights)))
    result.source_state = SimpleNamespace(bridges={1: object()},
        abis={plan.index: SimpleNamespace(plan=plan) for plan in plans}, producers={})
    return result


def source(prefix='class_state_function_', extra=''):
    bodies = []
    for index in range(3):
        if index == 2:
            invocation = 'Ok::<i64,String>(1)'
        else:
            invocation = prefix + str(index + 1) + '(scope)'
        calls = ''.join('let value_' + str(item) + '=class_sync_call(scope,||' + invocation + ')?;'
                        for item in range(8))
        bodies.append('fn ' + prefix + str(index) + '(scope:&ClassScope)->Result<i64,String>{'
                      + calls + 'Ok(value_0)}')
    return (RUNTIME + '\n'.join(bodies) + extra +
            'fn main(){let scope=ClassScope{control:RefCell::new(ClassControl{depth:0,limit:1000})};'
            'scope.control.borrow_mut().depth=1;let _=' + prefix + '0(&scope);}')


def apply(text, solved):
    # This suite tests the physical half only; real source prerequisites are
    # independently retained and covered by existing actual source tests.
    with patch.object(finite, '_model_proof', return_value={'max_source_height': 10}):
        result = finite.apply(text, solved)
    return result, solved.finite_depth_calls


class PhysicalSourceRanks(testing.TestCase):
    def test_registered_state_entries_cut_at_their_actual_source_activation(self):
        original = source()
        result, info = apply(original, model())
        self.assertTrue(info['eligible'], info)
        self.assertLess(info['certified_depth'], finite.MAX_CERTIFIED_DEPTH)
        self.assertEqual(info['synthetic_span'], 8)
        self.assertEqual(info['certified_source_transitions'], 2)
        self.assertNotIn('let _depth=ClassSyncDepth(scope)', result)
        self.assertIn('call().map_err(|error|error)', result)
        for index in range(3):
            self.assertEqual(result.count('fn class_state_function_' + str(index)), 1)

    def test_normal_source_mapping_uses_the_same_rank_and_counter_checks(self):
        result, info = apply(source('class_function_'), model())
        self.assertTrue(info['eligible'], info)
        self.assertEqual(info['synthetic_span'], 8)
        self.assertNotIn('let _depth=ClassSyncDepth(scope)', result)

    def test_unregistered_or_foreign_private_plan_keeps_every_guard(self):
        original = source()
        solved = model()
        solved.source_state.bridges = {}
        result, info = apply(original, solved)
        self.assertFalse(info['eligible'])
        self.assertIn('registered solved plan', info['reason'])
        self.assertEqual(result, original)
        solved = model()
        solved.source_state.abis[1] = SimpleNamespace(plan=SimpleNamespace(index=1, reachable=True))
        result, info = apply(original, solved)
        self.assertFalse(info['eligible'])
        self.assertEqual(result, original)

    def test_address_escape_unknown_symbols_and_nondecreasing_rank_still_decline(self):
        for extra, reason in (
            ('fn retained(){let _value=class_state_function_1;}', 'address escapes'),
            ('fn class_state_function_99(){}', 'registered solved plan'),
            ('fn class_construct_99(){}', 'registered source owner')):
            with self.subTest(reason=reason):
                original = source(extra=extra)
                result, info = apply(original, model())
                self.assertFalse(info['eligible'])
                self.assertIn(reason, info['reason'])
                self.assertEqual(result, original)
        original = source()
        result, info = apply(original, model((8, 9, 7)))
        self.assertFalse(info['eligible'])
        self.assertIn('does not decrease', info['reason'])
        self.assertEqual(result, original)

    def test_constructor_wrappers_stay_out_of_function_rank_mapping(self):
        solved = model()
        initializer = solved.plans[1]
        solved.classes['Owner'] = SimpleNamespace(index=4, used=True,
                                                   methods={'__init__': initializer})
        constructor = ('fn class_state_construct_4(scope:&ClassScope)->Result<i64,String>{'
                       'class_state_function_1(scope)}')
        original = source(extra=constructor)
        result, info = apply(original, solved)
        self.assertTrue(info['eligible'], info)
        self.assertIn('fn class_state_construct_4', result)
        # Owner index4 has no semantic call rank; treating it as a source
        # function activation would reject this otherwise closed constructor.
        self.assertNotIn(4, solved.native_call_heights)

    def test_source_proof_and_physical_depth_limit_are_not_bypassed(self):
        original = source()
        solved = model()
        with patch.object(finite, '_model_proof', side_effect=finite.Unproved('observer retained')):
            result = finite.apply(original, solved)
        self.assertEqual(result, original)
        self.assertEqual(solved.finite_depth_calls['reason'], 'observer retained')
        with patch.object(finite, 'MAX_CERTIFIED_DEPTH', 8):
            result, info = apply(original, model())
        self.assertFalse(info['eligible'])
        self.assertIn('physical depth', info['reason'])
        self.assertEqual(result, original)


if __name__ == '__main__':
    testing.main()
