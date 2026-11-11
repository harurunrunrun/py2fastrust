"""Unused invocation context does not change actual callable ownership."""
import ast
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_call_context_effects as effects
from tests import test_native_module_linking as _modules

PROJECTS={'builtin_iteration_unpack': {'main.py': 'class Marker:pass\n'
                                         'def factory():\n'
                                         ' def combine(rows):\n'
                                         '  total=0\n'
                                         '  for a,b in rows:\n'
                                         '   if a and b:total=total+a*b\n'
                                         '  return total\n'
                                         ' return combine\n'
                                         'callback=factory()\n'
                                         'print(callback([(2,3),(0,9),(4,5)]))\n'},
 'captured_environment_versions': {'main.py': 'def factory(seed):\n'
                                              '    def calculate(value): return seed + value\n'
                                              '    return calculate\n'
                                              'first = factory(13)\n'
                                              'second = factory(29)\n'
                                              'print(first(2), second(3), first(4))\n'},
 'captured_sibling_function': {'main.py': 'def factory(seed):\n'
                                          '    def inner(value): return seed + value\n'
                                          '    def outer(value): return inner(value) * 2\n'
                                          '    return outer\n'
                                          'callback = factory(9)\n'
                                          'print(callback(4))\n'},
 'failed_import_default_generations': {'main.py': 'import state\n'
                                                  'try:\n'
                                                  '    import unstable\n'
                                                  'except StopIteration:\n'
                                                  '    pass\n'
                                                  'import unstable\n'
                                                  'print(state.saved[0](), state.saved[1](), state.saved[0] '
                                                  'is state.saved[1])\n',
                                       'state.py': 'saved = []\nattempts = 0\n',
                                       'unstable.py': 'import state\n'
                                                      'state.attempts += 1\n'
                                                      'seed = 11 * state.attempts\n'
                                                      'def calculate(value=seed): return value + 3\n'
                                                      'state.saved.append(calculate)\n'
                                                      'if state.attempts == 1:\n'
                                                      '    next(iter(()))\n'},
 'foreign_chained_comparison': {'foreign.py': 'limit=1\n'
                                              'class Truth:\n'
                                              ' def __init__(self,value):self.value=value\n'
                                              ' def __bool__(self):return self.value>limit\n'
                                              'class Value:\n'
                                              ' def __init__(self,value):self.value=value\n'
                                              ' def __lt__(self,other):return '
                                              'Truth(other.value-self.value)\n',
                                'main.py': 'import foreign\n'
                                           'def factory():\n'
                                           ' def apply(a,b,c):return a<b<c\n'
                                           ' return apply\n'
                                           'callback=factory()\n'
                                           'foreign.limit=2\n'
                                           'a,b,c=foreign.Value(1),foreign.Value(2),foreign.Value(8)\n'
                                           'print(bool(callback(a,b,c)))\n'},
 'foreign_global_argument_mutation': {'helper.py': 'bias = 11\ndef calculate(value): return bias + value\n',
                                      'main.py': 'import helper\n'
                                                 'callback = helper.calculate\n'
                                                 'def argument():\n'
                                                 '    helper.bias = 23\n'
                                                 '    print("argument")\n'
                                                 '    return 5\n'
                                                 'print(callback(argument()))\n'},
 'foreign_inplace_operator': {'foreign.py': 'offset=7\n'
                                            'class Amount:\n'
                                            ' def __init__(self,value):self.value=value\n'
                                            ' def __iadd__(self,other):\n'
                                            '  self.value+=other+offset\n'
                                            '  return self\n',
                              'main.py': 'import foreign\n'
                                         'def factory():\n'
                                         ' def apply(value,delta):\n'
                                         '  value+=delta\n'
                                         '  return value.value\n'
                                         ' return apply\n'
                                         'callback=factory()\n'
                                         'value=foreign.Amount(2)\n'
                                         'foreign.offset=11\n'
                                         'print(callback(value,3),value.value)\n'},
 'foreign_method_operator_globals': {'helper.py': 'offset = 5\n'
                                                  'class Amount:\n'
                                                  '    def __init__(self, value): self.value = value\n'
                                                  '    def __add__(self, other): return Amount(self.value + '
                                                  'other.value + offset)\n',
                                     'main.py': 'import helper\n'
                                                'def main():\n'
                                                '    def combine(left, right): return left + right\n'
                                                '    callback = combine\n'
                                                '    left = helper.Amount(2)\n'
                                                '    right = helper.Amount(3)\n'
                                                '    helper.offset = 17\n'
                                                '    print(callback(left, right).value)\n'
                                                'main()\n'},
 'foreign_nested_comparison': {'foreign.py': 'offset = 1\n'
                                             'class Value:\n'
                                             '    def __init__(self, value): self.value = value\n'
                                             '    def __lt__(self, other):\n'
                                             '        print("compare", offset)\n'
                                             '        return self.value + offset < other.value\n'
                                             'def factory():\n'
                                             '    def compare(left, right): return left < right\n'
                                             '    return compare\n',
                               'main.py': 'import foreign\n'
                                          'callback = foreign.factory()\n'
                                          'foreign.offset = 3\n'
                                          'print(callback([foreign.Value(1)], [foreign.Value(3)]))\n'},
 'foreign_user_iterable': {'foreign.py': 'seed = 7\n'
                                         'class Items:\n'
                                         '    def __iter__(self): return iter([seed, seed + 1])\n'
                                         'def factory():\n'
                                         '    def total(values):\n'
                                         '        result = 0\n'
                                         '        for value in values: result += value\n'
                                         '        return result\n'
                                         '    return total\n',
                           'main.py': 'import foreign\n'
                                      'callback = foreign.factory()\n'
                                      'foreign.seed = 13\n'
                                      'print(callback(foreign.Items()))\n'},
 'foreign_user_truth': {'foreign.py': 'enabled = False\n'
                                      'class Flag:\n'
                                      '    def __bool__(self): return enabled\n'
                                      'def factory():\n'
                                      '    def choose(flag):\n'
                                      '        if flag: return 11\n'
                                      '        return 29\n'
                                      '    return choose\n',
                        'main.py': 'import foreign\n'
                                   'callback = foreign.factory()\n'
                                   'foreign.enabled = bool(int(input()))\n'
                                   'print(callback(foreign.Flag()))\n'},
 'foreign_user_unpack': {'foreign.py': 'seed = 5\n'
                                       'class Pair:\n'
                                       '    def __iter__(self): return iter([seed, seed + 1])\n'
                                       'def factory():\n'
                                       '    def total(value):\n'
                                       '        left, right = value\n'
                                       '        return left + right\n'
                                       '    return total\n',
                         'main.py': 'import foreign\n'
                                    'callback = foreign.factory()\n'
                                    'foreign.seed = 17\n'
                                    'print(callback(foreign.Pair()))\n'},
 'function_rebound_during_argument': {'main.py': 'def factory():\n'
                                                 '    def calculate(value): return value + 1\n'
                                                 '    return calculate\n'
                                                 'callback = factory()\n'
                                                 'saved = callback\n'
                                                 'def argument():\n'
                                                 '    global callback\n'
                                                 '    callback = factory()\n'
                                                 '    print("argument")\n'
                                                 '    return 8\n'
                                                 'print(saved(argument()), callback(3), saved is '
                                                 'callback)\n'},
 'literal_default_unused_environment': {'main.py': 'def factory():\n'
                                                   '    def calculate(value, scale=3): return value * scale\n'
                                                   '    return calculate\n'
                                                   'first = factory()\n'
                                                   'second = factory()\n'
                                                   'print(first(4), second(5, scale=2), first is second, '
                                                   'first is first)\n'},
 'mutating_method_is_not_pure_parameter_body': {'main.py': 'class Counter:\n'
                                                           '    def __init__(self): self.value = 0\n'
                                                           '    def add(self, amount):\n'
                                                           '        self.value += amount\n'
                                                           '        return self.value\n'
                                                           'counter = Counter()\n'
                                                           'print(counter.add(3), counter.add(4))\n'},
 'nested_factory_body': {'main.py': 'def factory(seed):\n'
                                    '    def outer(value):\n'
                                    '        def inner(extra): return value + extra + seed\n'
                                    '        return inner\n'
                                    '    return outer\n'
                                    'callback = factory(4)(7)\n'
                                    'print(callback(3))\n'},
 'nonliteral_default_effects': {'main.py': 'def mark(value):\n'
                                           '    print("default", value)\n'
                                           '    return value\n'
                                           'def factory(seed):\n'
                                           '    def calculate(value=mark(seed)):\n'
                                           '        return value * 2\n'
                                           '    return calculate\n'
                                           'first = factory(3)\n'
                                           'second = factory(8)\n'
                                           'print(first(), second(), first(7))\n'},
 'pure_foreign_nested': {'helper.py': 'def factory():\n'
                                      '    def calculate(left, right): return left * 10 + right\n'
                                      '    return calculate\n',
                         'main.py': 'import helper\n'
                                    'callback = helper.factory()\n'
                                    'def argument():\n'
                                    '    print("argument")\n'
                                    '    return 4\n'
                                    'print(callback(argument(), 8))\n'},
 'pure_nested_error_location': {'main.py': 'def factory():\n'
                                           '    def calculate(left, right): return left // right\n'
                                           '    return calculate\n'
                                           'callback = factory()\n'
                                           'print("before")\n'
                                           'print(callback(7, int(input())))\n'},
 'pure_nested_pairs': {'main.py': 'def main():\n'
                                  '    def combine(left, right):\n'
                                  '        return left[0] + right[0], left[1] * right[1]\n'
                                  '    callbacks = [combine]\n'
                                  '    print(callbacks[0]((2, 3), (5, 7)))\n'
                                  'main()\n'},
 'pure_parameter_object_operators': {'main.py': 'class Amount:\n'
                                                '    def __init__(self, value): self.value = value\n'
                                                '    def __add__(self, other): return Amount(self.value + '
                                                'other.value)\n'
                                                '    def val(self): return self.value\n'
                                                'def main():\n'
                                                '    def combine(left, right):\n'
                                                '        return left[0] + right[0], left[1] + right[1]\n'
                                                '    callbacks = [combine]\n'
                                                '    result = callbacks[0]((Amount(3), 2), (Amount(7), 5))\n'
                                                '    print(result[0].val(), result[1])\n'
                                                'main()\n'}}


class ContextEffectProofs(unittest.TestCase):
 def compile_pair(self,name,mode='i64'):
  observed=[]
  original=effects.prepare
  def observe(model):
   units=getattr(model.unit,'source_units',(model.unit,))
   before=[ast.dump(unit.tree,include_attributes=True)for unit in units]
   original(model)
   self.assertEqual(before,[ast.dump(unit.tree,include_attributes=True)for unit in units])
   observed.extend((plan, effects.summary(model,plan))for plan in model.plans)
  with tempfile.TemporaryDirectory(prefix='pytors-call-context-')as directory:
   root=Path(directory)
   for filename,source in PROJECTS[name].items():(root/filename).write_text(source)
   main=root/'main.py';options=TranspileOptions(filename=str(main),integer=mode,license='none')
   with patch.object(effects,'prepare',side_effect=observe):result=transpile(main.read_text(),options)
   with patch.object(effects,'prepare',side_effect=lambda model:setattr(model,'call_context_effects',None)):
    baseline=transpile(main.read_text(),options)
  return result,baseline,observed
 def named(self,observed,name):
  return [(plan,summary)for plan,summary in observed if getattr(plan.node,'name',None)==name]
 def test_parameter_callbacks_omit_only_unused_invocation_abi(self):
  for name,function in [('pure_nested_pairs','combine'),('pure_foreign_nested','calculate'),('literal_default_unused_environment','calculate')]:
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,baseline,observed=self.compile_pair(name,mode)
     self.assertTrue(result.success,result.diagnostics);self.assertTrue(baseline.success,baseline.diagnostics)
     selected=[plan for plan,summary in self.named(observed,function)if not summary.incoming_module]
     self.assertTrue(selected);self.assertNotEqual(result.rust_source,baseline.rust_source)
     for plan in selected:
      self.assertNotRegex(result.rust_source,rf'fn class_function_{plan.index}\([^)]*class_lexical_parent')
      # Retained function values keep their original actual-module/environment payload.
      if 'ClassModuleRef'in baseline.rust_source:self.assertIn('ClassModuleRef',result.rust_source)
      self.assertIn('ClassLexicalEnvironment',result.rust_source)
 def test_numeric_callback_acquires_its_foreign_receivers_context(self):
  for mode in ('i64','i128','bigint'):
   result,baseline,observed=self.compile_pair('foreign_method_operator_globals',mode)
   self.assertTrue(result.success,result.diagnostics)
   self.assertTrue(any(not summary.incoming_module for _,summary in self.named(observed,'combine')))
   self.assertTrue(all(summary.incoming_module for _,summary in self.named(observed,'__add__')))
   self.assertNotEqual(result.rust_source,baseline.rust_source)
 def test_globals_capture_defaults_and_inner_environment_retain_context(self):
  for name,function in [('foreign_global_argument_mutation','calculate'),('nonliteral_default_effects','calculate'),('captured_sibling_function','outer'),('nested_factory_body','outer')]:
   result,baseline,observed=self.compile_pair(name)
   self.assertTrue(result.success,result.diagnostics)
   summaries=self.named(observed,function);self.assertTrue(summaries)
   self.assertTrue(all(summary.incoming_module and summary.lexical_parent for _,summary in summaries))
 def test_scalar_lexical_reads_retain_the_parent_without_module_switching(self):
  for mode in ('i64','i128','bigint'):
   result,baseline,observed=self.compile_pair('captured_environment_versions',mode)
   self.assertTrue(result.success,result.diagnostics)
   summaries=self.named(observed,'calculate');self.assertTrue(summaries)
   self.assertTrue(all(not summary.incoming_module and summary.lexical_parent for _,summary in summaries))
 def test_augmented_source_protocol_keeps_ordinary_context(self):
  result,baseline,observed=self.compile_pair('foreign_inplace_operator')
  self.assertTrue(result.success,result.diagnostics)
  summaries=self.named(observed,'apply');self.assertTrue(summaries)
  self.assertTrue(all(summary.incoming_module and summary.lexical_parent for _,summary in summaries))
  self.assertTrue(all('AugAssign'in summary.reason for _,summary in summaries))
 def test_builtin_iteration_and_truth_are_certified_without_source_protocols(self):
  result,baseline,observed=self.compile_pair('builtin_iteration_unpack')
  self.assertTrue(result.success,result.diagnostics)
  self.assertTrue(any(not summary.incoming_module for _,summary in self.named(observed,'combine')))
  self.assertNotEqual(result.rust_source,baseline.rust_source)
 def test_unknown_implicit_protocol_capability_boundaries_are_unchanged(self):
  for name in ('foreign_user_iterable','foreign_user_truth','foreign_user_unpack','foreign_nested_comparison','foreign_chained_comparison','failed_import_default_generations'):
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     result,baseline,_=self.compile_pair(name,mode)
     self.assertFalse(result.success)
     self.assertEqual(result.diagnostics,baseline.diagnostics)
     self.assertTrue(all(d.code=='E006'and d.line>0 and d.column>0 for d in result.diagnostics))
 def test_specialization_queries_use_original_source_identity(self):
  original=SimpleNamespace(index=3)
  instance=SimpleNamespace(index=100,specialization_source=original)
  model=SimpleNamespace(call_context_effects=SimpleNamespace(summaries={3:effects.Summary(False,False,'source')}))
  self.assertIs(effects.source_plan(instance),original)
  self.assertFalse(effects.incoming_module(model,instance));self.assertTrue(effects.unused_parent(model,instance))
  instance.specialization_source=instance
  self.assertTrue(effects.incoming_module(model,instance));self.assertFalse(effects.unused_parent(model,instance))


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ContextEffectExecution(unittest.TestCase):
 def exercise(self,name):_modules.NativeLinkedModuleTests.exercise(self,PROJECTS[name])
 def test_actual_foreign_numeric_and_global_argument_order(self):
  for name in ('foreign_method_operator_globals','foreign_global_argument_mutation'):
   with self.subTest(name=name):self.exercise(name)
 def test_actual_closures_identity_defaults_and_saved_callable(self):
  for name in ('literal_default_unused_environment','nonliteral_default_effects','function_rebound_during_argument'):
   with self.subTest(name=name):self.exercise(name)
 def test_actual_implicit_inplace_and_builtin_iteration(self):
  for name in ('foreign_inplace_operator','builtin_iteration_unpack'):
   with self.subTest(name=name):self.exercise(name)
