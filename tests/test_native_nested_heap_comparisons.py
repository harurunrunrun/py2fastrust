"""Fixed tuple heap keys preserve source comparison and identity order."""
import unittest
from unittest.mock import patch

import test_native_class_iterators as execution
from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_class_identity_demand as identities

CASES={'numeric_tie_float_int': 'import heapq\n'
                          "q=[(1.0,'b'),(1,'a'),(2,'c')]\n"
                          'heapq.heapify(q)\n'
                          'print([heapq.heappop(q)[1]for _ in range(3)])\n',
 'numeric_precision': 'import heapq\n'
                      "q=[(9007199254740993,'integer'),(9007199254740992.0,'float')]\n"
                      'heapq.heapify(q)\n'
                      'print([heapq.heappop(q)[1]for _ in range(2)])\n',
 'shared_nan_alias': 'import heapq\n'
                     "value=float('nan')\n"
                     'alias=value\n'
                     "q=[(value,'a'),(alias,'b')]\n"
                     'heapq.heapify(q)\n'
                     'print([heapq.heappop(q)[1]for _ in range(2)])\n',
 'distinct_nan_objects': 'import heapq\n'
                         "left=float('nan')\n"
                         "right=float('nan')\n"
                         "q=[(left,'a'),(right,'b')]\n"
                         'heapq.heapify(q)\n'
                         'print([heapq.heappop(q)[1]for _ in range(2)])\n',
 'fresh_arithmetic_nan_objects': 'import heapq\n'
                                 "value=float('inf')\n"
                                 "q=[(value-value,'a'),(value-value,'b')]\n"
                                 'heapq.heapify(q)\n'
                                 'print([heapq.heappop(q)[1]for _ in range(2)])\n',
 'earlier_tuple_field_skips_source_protocol': 'import heapq\n'
                                              'class Key:\n'
                                              ' def __init__(self,name):self.name=name\n'
                                              ' def __eq__(self,other):\n'
                                              "  print('eq',self.name,other.name)\n"
                                              '  return False\n'
                                              ' def __lt__(self,other):\n'
                                              "  print('lt',self.name,other.name)\n"
                                              '  return self.name<other.name\n'
                                              "q=[(1,Key('left')),(0,Key('right'))]\n"
                                              'heapq.heapify(q)\n'
                                              'print([heapq.heappop(q)[1].name for _ in range(2)])\n',
 'tuple_tie_source_equality_then_order': 'import heapq\n'
                                         'class Key:\n'
                                         ' def __init__(self,name):self.name=name\n'
                                         ' def __eq__(self,other):\n'
                                         "  print('eq',self.name,other.name)\n"
                                         '  return False\n'
                                         ' def __lt__(self,other):\n'
                                         "  print('lt',self.name,other.name)\n"
                                         '  return self.name<other.name\n'
                                         "q=[(0,Key('b')),(0,Key('a'))]\n"
                                         'heapq.heapify(q)\n'
                                         'print([heapq.heappop(q)[1].name for _ in range(2)])\n',
 'source_identity_skips_equality': 'import heapq\n'
                                   'class Key:\n'
                                   ' def __eq__(self,other):\n'
                                   "  print('unexpected equality')\n"
                                   '  return False\n'
                                   ' def __lt__(self,other):\n'
                                   "  print('unexpected less')\n"
                                   '  return False\n'
                                   'shared=Key()\n'
                                   'q=[(0,shared,2),(0,shared,1)]\n'
                                   'heapq.heapify(q)\n'
                                   'print([heapq.heappop(q)[2]for _ in range(2)])\n',
 'rich_results_truth_conversion': 'import heapq\n'
                                  'class Decision:\n'
                                  ' def __init__(self,label,value):self.label=label;self.value=value\n'
                                  ' def __bool__(self):\n'
                                  "  print('truth',self.label,self.value)\n"
                                  '  return self.value\n'
                                  'class Key:\n'
                                  ' def __init__(self,name):self.name=name\n'
                                  ' def __eq__(self,other):\n'
                                  "  print('eq',self.name,other.name)\n"
                                  "  return Decision('equal',False)\n"
                                  ' def __lt__(self,other):\n'
                                  "  print('lt',self.name,other.name)\n"
                                  "  return Decision('less',self.name<other.name)\n"
                                  "q=[(0,Key('b')),(0,Key('a'))]\n"
                                  'heapq.heapify(q)\n'
                                  'print([heapq.heappop(q)[1].name for _ in range(2)])\n',
 'none_object_error_on_tie': 'import heapq\n'
                             'class Key:\n'
                             ' def __lt__(self,other):\n'
                             "  print('left comparison')\n"
                             '  return False\n'
                             'q=[(0,Key())]\n'
                             "print('before',len(q))\n"
                             'heapq.heappush(q,(0,None))\n',
 'none_object_after_earlier_difference': 'import heapq\n'
                                         'class Key:\n'
                                         ' def __lt__(self,other):\n'
                                         "  print('unexpected comparison')\n"
                                         '  return False\n'
                                         'q=[(1,Key()),(0,None)]\n'
                                         'heapq.heapify(q)\n'
                                         'print(heapq.heappop(q)[0],heapq.heappop(q)[0])\n',
 'object_accepts_none': 'import heapq\n'
                        'class Key:\n'
                        ' def __lt__(self,other):\n'
                        "  print('compare to None',other is None)\n"
                        '  return False\n'
                        'q=[(0,None)]\n'
                        'heapq.heappush(q,(0,Key()))\n'
                        'print(len(q))\n',
 'equality_error_before_less': 'import heapq\n'
                               'class Key:\n'
                               ' def __init__(self,name):self.name=name\n'
                               ' def __eq__(self,other):\n'
                               "  print('eq',self.name,other.name,len(q))\n"
                               '  return 1//0\n'
                               ' def __lt__(self,other):\n'
                               "  print('unreachable less')\n"
                               '  return False\n'
                               "q=[(0,Key('old'))]\n"
                               "heapq.heappush(q,(0,Key('new')))\n",
 'ordering_error_after_equality': 'import heapq\n'
                                  'class Key:\n'
                                  ' def __init__(self,name):self.name=name\n'
                                  ' def __eq__(self,other):\n'
                                  "  print('eq',self.name,other.name,len(q))\n"
                                  '  return False\n'
                                  ' def __lt__(self,other):\n'
                                  "  print('lt',self.name,other.name,len(q))\n"
                                  '  return 1//0\n'
                                  "q=[(0,Key('old'))]\n"
                                  "heapq.heappush(q,(0,Key('new')))\n",
 'nested_fixed_tuple_source_keys': 'import heapq\n'
                                   'class Key:\n'
                                   ' def __init__(self,name):self.name=name\n'
                                   ' def __eq__(self,other):\n'
                                   "  print('eq',self.name,other.name)\n"
                                   '  return self.name==other.name\n'
                                   ' def __lt__(self,other):\n'
                                   "  print('lt',self.name,other.name)\n"
                                   '  return self.name<other.name\n'
                                   "q=[((0,(1,Key('b'))),9),((0,(1,Key('a'))),8)]\n"
                                   'heapq.heapify(q)\n'
                                   'print([heapq.heappop(q)[1]for _ in range(2)])\n',
 'less_notimplemented_reverse': 'import heapq\n'
                                'class Left:\n'
                                " def __eq__(self,other):print('left equal');return NotImplemented\n"
                                " def __gt__(self,other):print('left greater');return True\n"
                                'class Right:\n'
                                " def __eq__(self,other):print('right equal');return NotImplemented\n"
                                " def __lt__(self,other):print('right less');return NotImplemented\n"
                                'q=[(0,Left())]\n'
                                'heapq.heappush(q,(0,Right()))\n'
                                'print(len(q))\n'}

CASES.update({'equal_distinct_objects_use_later_field': 'import heapq\n'
                                           'class Key:\n'
                                           ' def __init__(self,name):self.name=name\n'
                                           ' def __eq__(self,other):\n'
                                           "  print('equal',self.name,other.name)\n"
                                           '  return self.name==other.name\n'
                                           ' def __lt__(self,other):\n'
                                           "  print('unexpected less')\n"
                                           '  return False\n'
                                           "q=[(0,Key('same'),2),(0,Key('same'),1)]\n"
                                           'heapq.heapify(q)\n'
                                           'print([heapq.heappop(q)[2]for _ in range(2)])\n',
 'same_length_heap_replacement_keeps_cached_tuple_keys': 'import heapq\n'
                                                         'class Key:\n'
                                                         ' def __init__(self,name):self.name=name\n'
                                                         ' def __eq__(self,other):\n'
                                                         "  print('equal',self.name,other.name,len(q))\n"
                                                         '  q[0]=(99,self)\n'
                                                         '  return False\n'
                                                         ' def __lt__(self,other):\n'
                                                         "  print('less',self.name,other.name,q[0][0])\n"
                                                         '  return self.name<other.name\n'
                                                         "q=[(0,Key('b'))]\n"
                                                         "heapq.heappush(q,(0,Key('a')))\n"
                                                         'print([(number,key.name)for number,key in q])\n'
                                                         'print(heapq.heappop(q)[0],heapq.heappop(q)[0])\n',
 'nested_shared_alias_does_not_call_equality': 'import heapq\n'
                                               'class Key:\n'
                                               " def __eq__(self,other):print('unexpected equality');return "
                                               'False\n'
                                               " def __lt__(self,other):print('unexpected less');return "
                                               'False\n'
                                               'shared=Key()\n'
                                               'inner=(shared,)\n'
                                               'q=[(inner,2),(inner,1)]\n'
                                               'heapq.heapify(q)\n'
                                               'print([heapq.heappop(q)[1]for _ in range(2)])\n',
 'source_mutation_between_equal_and_less': 'import heapq\n'
                                           'class Key:\n'
                                           ' def __init__(self,rank):self.rank=rank\n'
                                           ' def __eq__(self,other):\n'
                                           "  print('equal',self.rank,other.rank)\n"
                                           '  self.rank+=3\n'
                                           '  return False\n'
                                           ' def __lt__(self,other):\n'
                                           "  print('less',self.rank,other.rank)\n"
                                           '  return self.rank<other.rank\n'
                                           'q=[(0,Key(2)),(0,Key(1))]\n'
                                           'heapq.heapify(q)\n'
                                           'print([heapq.heappop(q)[1].rank for _ in range(2)])\n',
 'finite_class_alternatives_and_aliases': 'import heapq\n'
                                          'class Alpha:\n'
                                          ' def __init__(self,name):self.name=name\n'
                                          " def __eq__(self,other):print('alpha "
                                          "eq',self.name,other.name);return self.name==other.name\n"
                                          " def __lt__(self,other):print('alpha "
                                          "lt',self.name,other.name);return self.name<other.name\n"
                                          'class Beta:\n'
                                          ' def __init__(self,name):self.name=name\n'
                                          " def __eq__(self,other):print('beta "
                                          "eq',self.name,other.name);return self.name==other.name\n"
                                          " def __lt__(self,other):print('beta "
                                          "lt',self.name,other.name);return self.name<other.name\n"
                                          'def choose(flag):\n'
                                          " if flag:return Alpha('alpha')\n"
                                          " return Beta('beta')\n"
                                          'for flag in (False,True):\n'
                                          ' shared=choose(flag)\n'
                                          ' q=[(0,shared,3),(0,shared,2),(0,choose(not flag),1)]\n'
                                          ' heapq.heapify(q)\n'
                                          ' print([heapq.heappop(q)[2]for _ in range(3)])\n',
 'all_min_and_max_heap_operations': 'import heapq\n'
                                    'class Key:\n'
                                    ' def __init__(self,rank):self.rank=rank\n'
                                    " def __eq__(self,other):print('eq',self.rank,other.rank);return "
                                    'self.rank==other.rank\n'
                                    " def __lt__(self,other):print('lt',self.rank,other.rank);return "
                                    'self.rank<other.rank\n'
                                    'q=[(0,Key(3)),(0,Key(1))]\n'
                                    'heapq.heapify(q)\n'
                                    'heapq.heappush(q,(0,Key(2)))\n'
                                    'print(heapq.heappushpop(q,(0,Key(4)))[1].rank)\n'
                                    'print(heapq.heapreplace(q,(0,Key(5)))[1].rank)\n'
                                    'print([heapq.heappop(q)[1].rank for _ in range(3)])\n'
                                    'q=[(0,Key(3)),(0,Key(1))]\n'
                                    'heapq.heapify_max(q)\n'
                                    'heapq.heappush_max(q,(0,Key(2)))\n'
                                    'print(heapq.heappushpop_max(q,(0,Key(4)))[1].rank)\n'
                                    'print(heapq.heapreplace_max(q,(0,Key(5)))[1].rank)\n'
                                    'print([heapq.heappop_max(q)[1].rank for _ in range(3)])\n'})

CASES.update({'lambda_comparator_site_uses_own_execution_scope': 'import heapq\n'
                                                    'class Key:\n'
                                                    ' def __lt__(self,other):return False\n'
                                                    'operation=lambda:heapq.heapify([(0,Key()),(0,Key())])\n'
                                                    'print(operation())\n',
 'generator_function_comparator_site_is_retained': 'import heapq\n'
                                                   'class Key:\n'
                                                   ' def __lt__(self,other):return False\n'
                                                   'def values():\n'
                                                   ' q=[(0,Key()),(0,Key())]\n'
                                                   ' heapq.heapify(q)\n'
                                                   ' yield len(q)\n'
                                                   'print(next(values()))\n',
 'retained_expression_comparator_site_is_retained': 'import heapq\n'
                                                    'class Key:\n'
                                                    ' def __lt__(self,other):return False\n'
                                                    'values=(heapq.heapify([(0,Key()),(0,Key())])for _ in '
                                                    'range(2))\n'
                                                    'print(next(values),next(values))\n'})

CASES.update({'assigned_python_comparator': 'import heapq\n'
                               'class Key:\n'
                               " def compare(self,other):print('alias less');return True\n"
                               ' __lt__=compare\n'
                               'q=[(0,Key()),(0,Key())]\n'
                               'heapq.heapify(q)\n'
                               'print(len(q))\n',
 'noncallable_equality_slot': 'import heapq\n'
                              'class Key:\n'
                              ' __eq__=None\n'
                              " def __lt__(self,other):print('unreachable less');return False\n"
                              'q=[(0,Key()),(0,Key())]\n'
                              'heapq.heapify(q)\n'
                              "print('unreachable')\n",
 'assigned_reflected_comparator': 'import heapq\n'
                                  'class Parent:\n'
                                  " def greater(self,other):print('reflected');return True\n"
                                  ' __gt__=greater\n'
                                  'class Incoming:\n'
                                  " def __lt__(self,other):print('left');return NotImplemented\n"
                                  'q=[(0,Parent())]\n'
                                  'heapq.heappush(q,(0,Incoming()))\n'
                                  'print(len(q))\n',
 'builtin_type_comparator_slot': 'import heapq\n'
                                 'class Key:\n'
                                 ' __lt__=bool\n'
                                 'q=[(0,Key()),(0,Key())]\n'
                                 'heapq.heapify(q)\n'
                                 'print(len(q))\n',
 'unvisited_noncallable_reflected_slot': 'import heapq\n'
                                         'class Key:\n'
                                         ' __gt__=None\n'
                                         " def __lt__(self,other):print('left decides');return False\n"
                                         'q=[(0,Key())]\n'
                                         'heapq.heappush(q,(0,Key()))\n'
                                         'print(len(q))\n',
 'deleted_equality_slot': 'import heapq\n'
                          'class Key:\n'
                          " def __eq__(self,other):print('stale eq');return False\n"
                          ' del __eq__\n'
                          " def __lt__(self,other):print('less');return False\n"
                          'q=[(0,Key()),(0,Key())]\n'
                          'heapq.heapify(q)\n'
                          'print(len(q))\n',
 'unvisited_static_reflected_slot': 'import heapq\n'
                                    'class Key:\n'
                                    ' @staticmethod\n'
                                    " def __gt__(other):print('unvisited');return True\n"
                                    " def __lt__(self,other):print('left decides');return False\n"
                                    'q=[(0,Key())]\n'
                                    'heapq.heappush(q,(0,Key()))\n'
                                    'print(len(q))\n'})

class NestedHeapTests(unittest.TestCase):
    cases=CASES
    check=execution.IteratorExecutionTests.check

    def test_earlier_tuple_field_skips_source_protocol(self):
        self.check('earlier_tuple_field_skips_source_protocol')

    def test_tuple_tie_source_equality_then_order(self):
        self.check('tuple_tie_source_equality_then_order')

    def test_source_identity_skips_equality(self):
        self.check('source_identity_skips_equality')

    def test_rich_results_truth_conversion(self):
        self.check('rich_results_truth_conversion')

    def test_none_object_error_on_tie(self):
        self.check('none_object_error_on_tie')

    def test_none_object_after_earlier_difference(self):
        self.check('none_object_after_earlier_difference')

    def test_object_accepts_none(self):
        self.check('object_accepts_none')

    def test_equality_error_before_less(self):
        self.check('equality_error_before_less')

    def test_ordering_error_after_equality(self):
        self.check('ordering_error_after_equality')

    def test_nested_fixed_tuple_source_keys(self):
        self.check('nested_fixed_tuple_source_keys')

    def test_less_notimplemented_reverse(self):
        self.check('less_notimplemented_reverse')

    def test_float_payload_identity_and_exact_numeric_comparisons(self):
        for name in ('distinct_nan_objects','fresh_arithmetic_nan_objects','numeric_precision','numeric_tie_float_int','shared_nan_alias'):
            with self.subTest(name=name):self.check(name)

    def test_equal_distinct_objects_use_later_field(self):
        self.check('equal_distinct_objects_use_later_field')

    def test_same_length_heap_replacement_keeps_cached_tuple_keys(self):
        self.check('same_length_heap_replacement_keeps_cached_tuple_keys')

    def test_nested_shared_alias_does_not_call_equality(self):
        self.check('nested_shared_alias_does_not_call_equality')

    def test_source_mutation_between_equal_and_less(self):
        self.check('source_mutation_between_equal_and_less')

    def test_finite_class_alternatives_and_aliases(self):
        self.check('finite_class_alternatives_and_aliases')

    def test_all_min_and_max_heap_operations(self):
        self.check('all_min_and_max_heap_operations')

    def test_lambda_comparator_site_uses_own_execution_scope(self):
        self.check('lambda_comparator_site_uses_own_execution_scope')

    def test_generator_function_comparator_site_is_retained(self):
        self.check('generator_function_comparator_site_is_retained')

    def test_retained_expression_comparator_site_is_retained(self):
        self.check('retained_expression_comparator_site_is_retained')

    def test_deleted_and_unregistered_rich_slots_remain_positioned_boundaries(self):
        names=('assigned_python_comparator','noncallable_equality_slot','assigned_reflected_comparator','builtin_type_comparator_slot','unvisited_noncallable_reflected_slot','deleted_equality_slot')
        for name in names:
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(CASES[name],TranspileOptions(integer=mode,filename='nested_slot_case.py',license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code=='E006'and d.line>0 and ('__eq__'in d.message or'__lt__'in d.message or'__gt__'in d.message)for d in result.diagnostics),result.diagnostics)

    def test_unvisited_static_reflected_slot_is_not_resolved(self):
        self.check('unvisited_static_reflected_slot')

class ImplicitHeapIdentityTests(unittest.TestCase):
    def model(self,source):
        recorded=[];prepare=identities.prepare
        def capture(model):prepare(model);recorded.append(model)
        with patch('py2fastrust.native_class_identity_demand.prepare',side_effect=capture):
            result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(recorded)
        return recorded[-1]

    def test_empty_value_class_keeps_implicit_identity_token(self):
        model=self.model(CASES['none_object_error_on_tie'])
        owner=next(owner for owner in model.classes.values()if owner.node.name=='Key')
        self.assertIn(owner.index,model.value_classes.selected)
        self.assertTrue(identities.token(model,owner))
        self.assertIn('heap element comparison',model.class_identity_demand.reasons[owner.index])
        self.assertTrue(any(owner.index in entry[3]for entry in identities.snapshot(model)))

    def test_site_replacement_is_stable_and_late_changes_fail_closed(self):
        from py2fastrust.native_classes import InstanceType,ClassUnsupported
        model=self.model(CASES['none_object_error_on_tie'])
        key,(plan,node,owners,reason)=next(iter(model.implicit_class_identity_observers.items()))
        owner=next(owner for owner in model.classes.values()if owner.index in owners)
        kinds=[InstanceType(model.class_key(owner))]
        before=model.snapshot()
        identities.observe_implicit(model,plan,node,key[2],kinds,reason)
        self.assertEqual(model.snapshot(),before)
        identities.observe_implicit(model,plan,node,key[2],(),reason)
        with self.assertRaisesRegex(ClassUnsupported,'observations changed'):
            identities.elided(model,owner)
        identities.observe_implicit(model,plan,node,key[2],kinds,reason)
        self.assertTrue(identities.token(model,owner))
        with self.assertRaisesRegex(ClassUnsupported,'registered source instance kind'):
            identities.observe_implicit(model,plan,node,key[2],['int'],reason)

    def test_unreached_nested_heap_does_not_demand_identity(self):
        source="import heapq\nclass Key:pass\ndef unused():\n shared=Key()\n q=[(0,shared),(0,shared)]\n heapq.heapify(q)\nprint('ready')\n"
        model=self.model(source)
        self.assertEqual(identities.snapshot(model),())

    def test_omitted_normal_statement_cannot_retain_a_provisional_demand(self):
        import ast
        from py2fastrust.native_classes import InstanceType
        source="import heapq\nclass Key:\n def __init__(self,value):self.value=value\nshared=Key(7)\nwhile False:\n heapq.heapify([(0,shared),(0,shared)])\nprint(shared.value)\n"
        model=self.model(source)
        owner=next(owner for owner in model.classes.values()if owner.node.name=='Key')
        self.assertIn(owner.index,model.value_classes.selected)
        self.assertTrue(identities.elided(model,owner))
        plan=next(plan for plan in model.plans if model.is_module_plan(plan)and plan.module_name=='__main__')
        node=next(node for node in model.iter_nodes()if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr=='heapify')
        self.assertIsNotNone(model.reached_statements)
        before=model.snapshot()
        identities.observe_implicit(model,plan,node,('provisional_heap',),[InstanceType(model.class_key(owner))],'a provisional original heap call')
        self.assertEqual(identities.snapshot(model),())
        self.assertEqual(model.snapshot(),before)
        self.assertTrue(identities.elided(model,owner))


if __name__=="__main__":unittest.main()
