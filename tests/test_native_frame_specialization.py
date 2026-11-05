"""Native call contexts preserve original callable/heap identity and errors."""
import ast
import shutil
import unittest
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,shape
from py2fastrust.native_frame_specialization import MAX_CONTEXTS,source_plan
import test_native_class_iterators as runtime_tests

CASES={'numeric_method_alternatives': 'class Number:\n'
                                ' def __init__(self,value):self.value=value\n'
                                ' def __mul__(self,rhs):\n'
                                '  if isinstance(rhs,Number):return Number(self.value*rhs.value)\n'
                                '  return Number(self.value*rhs)\n'
                                ' def read(self):return self.value\n'
                                'a=Number(3)\n'
                                'print((a*Number(4)).read(),(a*5).read(),(a*True).read())\n',
 'same_site_caller_contexts': 'def twice(value):return value+value\n'
                              'class Relay:\n'
                              ' def run(self,value):return twice(value)\n'
                              'r=Relay()\n'
                              "print(r.run(7),r.run('ab'),r.run(False))\n",
 'definition_default_effects': 'def seed():\n'
                               " print('default')\n"
                               ' return 4\n'
                               'class Relay:\n'
                               ' def run(self,value=seed()):return value+value\n'
                               'r=Relay()\n'
                               "print(r.run(),r.run('xy'),r.run(),r.run(8))\n",
 'callee_before_argument_rebind': 'def twice(value):return value+value\n'
                                  'def other(value):return value+100\n'
                                  'chosen=twice\n'
                                  'def change():\n'
                                  ' global chosen\n'
                                  " print('argument')\n"
                                  ' chosen=other\n'
                                  ' return 3\n'
                                  'class Runner:\n'
                                  ' def run(self):\n'
                                  '  first=chosen(change())\n'
                                  '  return first,chosen(4)\n'
                                  'print(Runner().run())\n',
 'reflected_numeric_methods': 'class Left:\n'
                              ' def __init__(self,value):self.value=value\n'
                              ' def __mul__(self,rhs):return NotImplemented\n'
                              'class Right:\n'
                              ' def __init__(self,value):self.value=value\n'
                              ' def __rmul__(self,lhs):\n'
                              '  if isinstance(lhs,Left):return self.value*lhs.value\n'
                              '  return self.value*lhs\n'
                              'print(Left(3)*Right(4),5*Right(6))\n',
 'recursive_type_transition': 'def grow(value,n):\n'
                              ' if n==0:return value\n'
                              ' return grow(str(value),n-1)\n'
                              'class Runner:\n'
                              ' def run(self,value):return grow(value,3)\n'
                              'r=Runner()\n'
                              "print(r.run(2),r.run('a'))\n",
 'retained_bound_method': 'class Relay:\n'
                          ' def run(self,value):return value+value\n'
                          'r=Relay()\n'
                          'saved=r.run\n'
                          "print(saved(4),saved('x'),saved==r.run)\n",
 'shared_instance_result_and_field_writes': 'class Box:\n'
                                            ' def __init__(self):self.value=0\n'
                                            ' def replace(self,other,value):\n'
                                            '  other.value=value\n'
                                            '  return other\n'
                                            'a=Box()\n'
                                            'b=Box()\n'
                                            'alias=a\n'
                                            'print(a.replace(alias,7)is a,a.value)\n'
                                            "print(a.replace(b,'word')is b,b.value,a.value)\n"
                                            'print(a.replace(alias,True)is alias,a.value,b.value)\n',
 'specialized_error_frames': 'class Divider:\n'
                             ' def run(self,value):\n'
                             "  print('run',value)\n"
                             '  return 12//value\n'
                             'd=Divider()\n'
                             'print(d.run(3))\n'
                             'print(d.run(False))\n',
 'bool_and_int_context_tests': 'class Judge:\n'
                               ' def run(self,value):return '
                               'isinstance(value,bool),isinstance(value,int),value+value\n'
                               'j=Judge()\n'
                               'print(j.run(3),j.run(True),j.run(False))\n',
 'mutable_default_keeps_one_object': 'class History:\n'
                                     ' def run(self,value,seen=[]):\n'
                                     '  seen.append(value)\n'
                                     '  return len(seen),seen[0]\n'
                                     'h=History()\n'
                                     "print(h.run(2),h.run('x'),h.run(3))\n",
 'captured_argument_cell': 'def make(value):\n'
                           ' def read():return value\n'
                           ' return read\n'
                           'class Runner:\n'
                           ' def run(self,value):return make(value)\n'
                           'r=Runner()\n'
                           'a=r.run(2)\n'
                           "b=r.run('text')\n"
                           'print(a(),b(),a is b)\n',
 'returned_mutable_alias': 'def make(value):return [value]\n'
                           'class Runner:\n'
                           ' def run(self,value):return make(value)\n'
                           'r=Runner()\n'
                           'a=r.run(2)\n'
                           "b=r.run('x')\n"
                           'alias=a\n'
                           'alias[0]=7\n'
                           'print(a,b,a is alias,a is b)\n',
 'bounded_context_budget': 'class Item0:pass\n'
                           'class Item1:pass\n'
                           'class Item2:pass\n'
                           'class Item3:pass\n'
                           'class Item4:pass\n'
                           'class Item5:pass\n'
                           'class Item6:pass\n'
                           'class Item7:pass\n'
                           'class Item8:pass\n'
                           'class Item9:pass\n'
                           'class Item10:pass\n'
                           'class Item11:pass\n'
                           'class Item12:pass\n'
                           'class Item13:pass\n'
                           'class Item14:pass\n'
                           'class Item15:pass\n'
                           'class Item16:pass\n'
                           'class Item17:pass\n'
                           'class Reader:\n'
                           ' def read(self,item):return 7\n'
                           'r=Reader()\n'
                           'print(r.read(Item0()),r.read(Item1()),r.read(Item2()),r.read(Item3()),r.read(Item4()),r.read(Item5()),r.read(Item6()),r.read(Item7()),r.read(Item8()),r.read(Item9()),r.read(Item10()),r.read(Item11()),r.read(Item12()),r.read(Item13()),r.read(Item14()),r.read(Item15()),r.read(Item16()),r.read(Item17()))\n',
 'shared_nested_container_fields': 'class Box:\n'
                                   ' def __init__(self):self.items=[1]\n'
                                   ' def change(self,other,value):\n'
                                   '  other.items.append(value)\n'
                                   '  return len(self.items),len(other.items),other.items[-1]\n'
                                   'a=Box()\n'
                                   'b=Box()\n'
                                   'alias=a\n'
                                   'print(a.change(alias,2))\n'
                                   "print(a.change(b,'x'))\n"
                                   'print(a.change(alias,False))\n'
                                   'print(a.items,b.items)\n'}


def inspect(source):
    from py2fastrust.native_linked_frames import LinkedModel
    from py2fastrust.native_module_linking import LinkedProgram
    program=build_program(source,'specialization_case.py')
    linked=LinkedProgram.from_program(program)
    unit=linked.unit
    before=ast.dump(unit.tree,include_attributes=True)
    model=LinkedModel(linked,unit.filename,'i64','ascii').run()
    assert ast.dump(unit.tree,include_attributes=True)==before
    return unit,model


class NativeSpecializationProofTests(unittest.TestCase):
    def test_numeric_alternatives_have_distinct_real_native_arguments(self):
        unit,model=inspect(CASES['numeric_method_alternatives'])
        source=next(owner for owner in model.classes.values()if owner.node.name=='Number').methods['__mul__']
        variants=[plan for plan in model.plans if source_plan(plan)is source and plan is not source]
        self.assertEqual(len(variants),3)
        rhs={shape(plan.arguments['rhs'])for plan in variants}
        from py2fastrust.native_classes import InstanceType
        self.assertEqual(rhs,{'int','bool',shape(source.arguments['self'])})
        self.assertEqual(len({plan.index for plan in model.plans}),len(model.plans))
        for plan in variants:
            self.assertIs(plan.node,source.node)
            self.assertIs(plan.owner,source.owner)
            self.assertIs(plan.signature,source.signature)
            self.assertIs(plan.default_cells,source.default_cells)
            self.assertIsNot(plan.declared,source.declared)
            self.assertIsNot(plan.locals,source.locals)
            self.assertIsNot(plan.result.root(),source.result.root())
            self.assertTrue(all(plan.arguments[name].root()is not source.arguments[name].root()
                                for name in source.arguments))
            self.assertEqual(plan.definition_key,source.definition_key)
            self.assertIs(plan.source_unit,source.source_unit)
            self.assertEqual(model.lexical.scope(plan),model.lexical.scope(source))
        # Runtime callable descriptors still point to one original definition.
        self.assertIs(model.callable_cells.plans[unit.ordinal(source.node)],source)

    def test_same_ast_callsite_uses_its_caller_context(self):
        _,model=inspect(CASES['same_site_caller_contexts'])
        source=next(plan for plan in model.functions.values()if plan.node.name=='twice')
        variants=[plan for plan in model.plans if source_plan(plan)is source and plan is not source]
        self.assertEqual({shape(plan.arguments['value'])for plan in variants},{'int','str','bool'})
        for plan in variants:
            self.assertTrue(any(plan.index in edges for edges in model.call_edges.values()))

    def test_defaults_are_owned_by_original_definition(self):
        _,model=inspect(CASES['definition_default_effects'])
        source=next(owner for owner in model.classes.values()if owner.node.name=='Relay').methods['run']
        variants=[plan for plan in model.plans if source_plan(plan)is source and plan is not source]
        self.assertGreaterEqual(len(variants),2)
        for plan in variants:
            self.assertIs(plan.defaults,source.defaults)
            self.assertIs(plan.default_cells,source.default_cells)
        self.assertIn((source.index,'value'),model.namespace.defaults)
        self.assertTrue(all((plan.index,'value')not in model.namespace.defaults for plan in variants))

    def test_mutable_return_carrier_and_lexical_capture_keep_original_abi(self):
        for name in ('captured_argument_cell','returned_mutable_alias'):
            with self.subTest(name=name):
                _,model=inspect(CASES[name])
                self.assertFalse(model.specializations.instances)

    def test_context_budget_retains_analyzed_native_template(self):
        _,model=inspect(CASES['bounded_context_budget'])
        source=next(owner for owner in model.classes.values()if owner.node.name=='Reader').methods['read']
        variants=[plan for plan in model.plans if source_plan(plan)is source and plan is not source]
        self.assertEqual(len(variants),MAX_CONTEXTS)
        self.assertTrue(source.reachable)
        self.assertTrue(any(source.index in edges for edges in model.call_edges.values()))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeSpecializationExecutionTests(unittest.TestCase):
    cases=CASES
    check=runtime_tests.IteratorExecutionTests.check

    def test_numeric_and_exact_bool_alternatives(self):
        for name in ('numeric_method_alternatives','bool_and_int_context_tests','reflected_numeric_methods'):
            with self.subTest(name=name):self.check(name)

    def test_callsite_defaults_callee_capture_and_retained_identity(self):
        for name in ('same_site_caller_contexts','definition_default_effects',
                     'callee_before_argument_rebind','retained_bound_method'):
            with self.subTest(name=name):self.check(name)

    def test_shared_heap_writes_and_recursion(self):
        for name in ('shared_instance_result_and_field_writes','shared_nested_container_fields',
                     'recursive_type_transition'):
            with self.subTest(name=name):self.check(name)

    def test_specialized_errors_retain_original_source_frames(self):
        self.check('specialized_error_frames')

    def test_captured_defaults_and_mutable_returns_keep_identity(self):
        for name in ('mutable_default_keeps_one_object','captured_argument_cell','returned_mutable_alias'):
            with self.subTest(name=name):self.check(name)
