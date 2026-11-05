"""Original producer and heap invariants never discard unknown successful inputs."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_scalar_heap_constants as heaps
from py2fastrust.native_scalar_constant_facts import Graph,Producer,Scalar,UNKNOWN
from py2fastrust.native_classes import Cell,Emitter
from py2fastrust.native_types import ListType
from py2fastrust.rust_pruning import _lex,_parse
import test_native_lambda_callbacks as helpers
from tests import test_native_module_linking as modules


CASES = {'literal_constructor_field': ('class Scale:\n'
                               ' def __init__(self,value):self.base=97;self.value=value\n'
                               ' def read(self):return self.value%self.base\n'
                               'print(Scale(int(input())).read())\n',
                               ('123\n', '-4\n')),
 'source_parameter_return_flow': ('def choose():return 43\n'
                                  'def pass_value(value):return value\n'
                                  'class Scale:\n'
                                  ' def '
                                  '__init__(self,base,value):self.base=base;self.value=value\n'
                                  ' def read(self):return self.value%self.base\n'
                                  'item=Scale(pass_value(choose()),int(input()))\n'
                                  'print(item.base,item.read())\n',
                                  ('100\n',)),
 'one_context': ('class Session:\n'
                 ' stack=[]\n'
                 ' def __init__(self,base):self.base=base\n'
                 ' def __enter__(self):self.stack.append(self.base)\n'
                 ' def __exit__(self,kind,value,trace):self.stack.pop()\n'
                 ' @classmethod\n'
                 ' def current(cls):return cls.stack[-1]\n'
                 'class Residue:\n'
                 ' def __init__(self,value=0):\n'
                 '  self.rule=Session.current()\n'
                 '  self.value=value%self.rule\n'
                 ' @classmethod\n'
                 ' def raw(cls,value):\n'
                 '  result=cls()\n'
                 '  result.value=value\n'
                 '  return result\n'
                 ' def add(self,other):return Residue(self.value+other.value)\n'
                 'with Session(97):\n'
                 ' left=Residue(102)\n'
                 ' right=Residue(195)\n'
                 ' print(left.rule,left.add(right).value)\n',
                 ('',)),
 'nested_different_context_raw': ('class Session:\n'
                                  ' stack=[]\n'
                                  ' def __init__(self,base):self.base=base\n'
                                  ' def __enter__(self):self.stack.append(self.base)\n'
                                  ' def __exit__(self,kind,value,trace):self.stack.pop()\n'
                                  ' @classmethod\n'
                                  ' def current(cls):return cls.stack[-1]\n'
                                  'class Residue:\n'
                                  ' def __init__(self,value=0):\n'
                                  '  self.rule=Session.current()\n'
                                  '  self.value=value%self.rule\n'
                                  ' @classmethod\n'
                                  ' def raw(cls,value):\n'
                                  '  result=cls()\n'
                                  '  result.value=value\n'
                                  '  return result\n'
                                  ' def add(self,other):return '
                                  'Residue(self.value+other.value)\n'
                                  'with Session(17):\n'
                                  ' left=Residue(39)\n'
                                  ' with Session(23):\n'
                                  '  right=Residue.raw(40)\n'
                                  '  print(left.rule,right.rule,left.value,right.value)\n'
                                  ' print(Residue(22).rule)\n',
                                  ('',)),
 'stack_alias_index_mutation': ('class Session:\n'
                                ' stack=[]\n'
                                ' def __init__(self,base):self.base=base\n'
                                ' def __enter__(self):self.stack.append(self.base)\n'
                                ' def __exit__(self,kind,value,trace):self.stack.pop()\n'
                                ' @classmethod\n'
                                ' def current(cls):return cls.stack[-1]\n'
                                'class Residue:\n'
                                ' def __init__(self,value=0):\n'
                                '  self.rule=Session.current()\n'
                                '  self.value=value%self.rule\n'
                                ' @classmethod\n'
                                ' def raw(cls,value):\n'
                                '  result=cls()\n'
                                '  result.value=value\n'
                                '  return result\n'
                                ' def add(self,other):return Residue(self.value+other.value)\n'
                                'with Session(17):\n'
                                ' alias=Session.stack\n'
                                ' alias[-1]=23\n'
                                ' print(Residue(39).rule,Residue(39).value)\n',
                                ('',)),
 'conditional_missing_field': ('class Scale:\n'
                               ' def __init__(self,enabled):\n'
                               '  if enabled:self.base=97\n'
                               'item=Scale(int(input())!=0)\n'
                               'print(item.base)\n',
                               ('0\n', '1\n')),
 'constructor_error_after_write': ('class Scale:\n'
                                   ' def __init__(self,value):\n'
                                   '  self.base=97\n'
                                   "  print('before',value)\n"
                                   '  self.value=1//value\n'
                                   'item=Scale(int(input()))\n'
                                   'print(item.base,item.value)\n',
                                   ('0\n', '2\n')),
 'constructor_scalar_walrus': ('class Carrier:\n'
                               ' def __init__(self):\n'
                               '  value=11\n'
                               '  (value:=13)\n'
                               '  self.modulus=value\n'
                               'item=Carrier()\n'
                               'print(item.modulus)\n',
                               ('',)),
 'with_scalar_binding': ('class Context:\n'
                         ' def __enter__(self):return 13\n'
                         ' def __exit__(self,*args):return False\n'
                         'class Carrier:\n'
                         ' def __init__(self,value):self.modulus=value\n'
                         'value=11\n'
                         'with Context() as value:\n'
                         ' item=Carrier(value)\n'
                         ' print(item.modulus)\n',
                         ('',)),
 'comprehension_scalar_target': ('class Carrier:\n'
                                 ' def __init__(self):\n'
                                 '  self.modulus=[value if True else 11 for value in '
                                 '[13]][0]\n'
                                 'item=Carrier()\n'
                                 'print(item.modulus)\n',
                                 ('',)),
 'nullable_scalar_parameter': ('class Carrier:\n'
                               ' def __init__(self,value):self.modulus=value\n'
                               'def choose(value):\n'
                               ' if value is None:return 11\n'
                               ' return value\n'
                               'first=Carrier(choose(None))\n'
                               'second=Carrier(choose(13))\n'
                               'print(first.modulus,second.modulus)\n',
                               ('',)),
 'shared_list_iadd': ('class Palette:\n'
                      ' values=[11]\n'
                      'class Measure:\n'
                      ' def __init__(self):self.modulus=Palette.values[-1]\n'
                      'alias=Palette.values\n'
                      'alias += [13]\n'
                      'item=Measure()\n'
                      'print(item.modulus)\n',
                      ('',)),
 'shared_list_iadd_callback': ('class Palette:\n'
                               ' values=[11]\n'
                               'class Measure:\n'
                               ' def __init__(self):self.modulus=Palette.values[-1]\n'
                               'def rhs():\n'
                               " print('rhs')\n"
                               ' return [13]\n'
                               'alias=Palette.values\n'
                               'alias += rhs()\n'
                               'item=Measure()\n'
                               'print(item.modulus)\n',
                               ('',))}


class ScalarFactContracts(unittest.TestCase):
    def test_unknown_input_cannot_disappear_beside_a_literal(self):
        graph=Graph(64)
        graph.copy('joined','unmodeled')
        graph.seed('joined','int',11)
        graph.finalize()
        self.assertIs(graph.values['joined'],UNKNOWN)

    def test_unseeded_cycle_is_unknown(self):
        graph=Graph(64)
        graph.copy('left','right');graph.copy('right','left')
        graph.copy('result','left');graph.seed('result','int',11)
        graph.finalize()
        self.assertIs(graph.values['result'],UNKNOWN)

    def test_empty_allocation_requires_an_explicit_certificate(self):
        graph=Graph(64)
        graph.certify_empty_allocation('empty',Producer('source',0,1,0,'empty_list'))
        graph.copy('result','empty');graph.seed('result','int',11)
        graph.finalize()
        self.assertEqual(graph.constant('result'),Scalar('int',11,11))
        self.assertIsNone(graph.values['empty'])

    def test_scalar_kinds_do_not_conflate_python_equal_values(self):
        graph=Graph(64)
        graph.seed('integer','int',1);graph.seed('boolean','bool',True)
        graph.copy('both','integer');graph.copy('both','boolean')
        graph.seed('floating','float',1.0)
        graph.add('bit','BitAnd',('boolean','boolean'))
        graph.finalize()
        self.assertIs(graph.values['both'],UNKNOWN)
        self.assertIs(graph.values['floating'],UNKNOWN)
        self.assertEqual(graph.constant('bit'),Scalar('bool',True,True))

    def test_every_integer_operation_normalizes_at_the_selected_width(self):
        for bits,expected in ((64,-(1<<63)),(128,1<<63),(0,1<<63)):
            graph=Graph(bits)
            graph.seed('maximum','int',(1<<63)-1);graph.seed('one','int',1)
            graph.add('next','Add',('maximum','one'))
            graph.finalize()
            self.assertEqual(graph.constant('next'),Scalar('int',expected,expected))

    def test_expensive_constant_folds_are_unknown(self):
        for bits in (0,64,128):
            graph=Graph(bits)
            graph.seed('base','int',2);graph.seed('huge','int',1000000000)
            graph.add('power','Pow',('base','huge'))
            graph.add('shift','LShift',('base','huge'))
            graph.finalize()
            self.assertIsNone(graph.constant('power'))
            self.assertIsNone(graph.constant('shift'))

    def test_descriptor_list_without_origins_poison_unknown_aliases(self):
        node=ast.parse('values').body[0].value
        registry=heaps.Registry.__new__(heaps.Registry)
        registry.model=SimpleNamespace(records={(0,id(node)):Cell(ListType('int'))})
        registry.graph=Graph(64);registry.heap_unknown=False;registry.heap_nodes=set()
        registry.poison(SimpleNamespace(index=0),node)
        self.assertTrue(registry.heap_unknown)


class ScalarHeapSourceTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def capture(self,source,mode):
        records=[];prepare=heaps.prepare
        def record(model):
            prepare(model);records.append(model.scalar_heap_constants)
        with patch.object(heaps,'prepare',record):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(len(records),1)
        return result,records[0]

    def test_real_constructor_call_and_list_context_invariant(self):
        for mode in ('i64','i128'):
            result,registry=self.capture(CASES['one_context'][0],mode)
            self.assertIsNone(registry.reason)
            self.assertGreaterEqual(sum(fact.low==97 for fact in registry.fields.values()),2)
            self.assertIn('class_scalar_actual.map(',result.rust_source)
            self.assertIn('fn class_construct_',result.rust_source)
            model=registry.model
            session=next(owner for owner in model.classes.values()if owner.node.name=='Session')
            residue=next(owner for owner in model.classes.values()if owner.node.name=='Residue')
            current=session.methods['current'];constructor=residue.methods['__init__']
            calls=[]
            for (caller,_),targets in model.call_edges_by_site.items():
                caller=registry.plans.get(caller)
                if caller is None or registry.source(caller)is not constructor:continue
                calls.extend((caller,registry.plans[index])for index in targets
                             if index in registry.plans and registry.source(registry.plans[index])is current)
            self.assertTrue(calls,'the original constructor must retain the source current() call')
            tokens,comments,pairs=_lex(result.rust_source)
            bodies={item.name:result.rust_source[item.start:item.end]
                    for item in _parse(result.rust_source,tokens,comments,pairs)if item.kind=='fn'}
            for caller,callee in calls:
                name=Emitter.function_name(None,callee)
                self.assertIn(name+'(',bodies[Emitter.function_name(None,caller)])
                # Negative-index lookup is lowered directly to Vec::last in
                # this path; an optional class_list_get helper is not required.
                self.assertIn('.borrow()',bodies[name])
                self.assertIn('IndexError: list index out of range',bodies[name])

    def test_actual_field_read_remains_before_constant_result(self):
        result,registry=self.capture(CASES['literal_constructor_field'][0],'i64')
        self.assertIn('field_0.get()',result.rust_source)
        self.assertIn('class_scalar_actual.map(',result.rust_source)
        self.assertIn('(97_i128 as NativeInt)',result.rust_source)

    def test_other_context_and_alias_changes_keep_unknown_values(self):
        for key in ('nested_different_context_raw','stack_alias_index_mutation'):
            for mode in ('i64','i128'):
                result,registry=self.capture(CASES[key][0],mode)
                owner=next(owner for owner in registry.model.classes.values()if owner.node.name=='Residue')
                index=list(owner.fields).index('rule')
                self.assertNotIn((owner.index,index),registry.fields)

    def test_original_literal_constructor_field(self):
        self.exercise(*CASES['literal_constructor_field'])

    def test_original_source_parameter_return_flow(self):
        self.exercise(*CASES['source_parameter_return_flow'])

    def test_original_one_context(self):
        self.exercise(*CASES['one_context'])

    def test_original_nested_different_context_raw(self):
        self.exercise(*CASES['nested_different_context_raw'])

    def test_original_stack_alias_index_mutation(self):
        self.exercise(*CASES['stack_alias_index_mutation'])

    def test_original_conditional_missing_field(self):
        self.exercise(*CASES['conditional_missing_field'])

    def test_original_constructor_error_after_write(self):
        self.exercise(*CASES['constructor_error_after_write'])

    def test_original_constructor_scalar_walrus(self):
        self.exercise(*CASES['constructor_scalar_walrus'])

    def test_original_with_scalar_binding(self):
        self.exercise(*CASES['with_scalar_binding'])

    def test_original_comprehension_scalar_target(self):
        self.exercise(*CASES['comprehension_scalar_target'])

    def test_original_nullable_scalar_parameter(self):
        self.exercise(*CASES['nullable_scalar_parameter'])

    def test_original_shared_list_iadd(self):
        self.exercise(*CASES['shared_list_iadd'])

    def test_original_shared_list_iadd_callback(self):
        self.exercise(*CASES['shared_list_iadd_callback'])

    def test_original_zero_repeat_mutates_saved_list_alias(self):
        source='''store=[11]
alias=store
alias *= 0
alias.append(13)
class Parcel:
 def __init__(self):self.result=store[-1]
print(Parcel().result)
'''
        self.exercise(source,('',))
        _,registry=self.capture(source,'i64')
        self.assertTrue(registry.heap_unknown)
        self.assertFalse(registry.fields)

    def test_original_context_lookup_still_fails_after_exit(self):
        source=CASES['one_context'][0].split('with Session(97):')[0]+'''with Session(97):
 Residue(102)
print('outside')
Residue(1)
'''
        self.exercise(source,('',))
        _,registry=self.capture(source,'i64')
        self.assertTrue(any(fact.low==97 for fact in registry.fields.values()))

class ScalarImportedProducerTests(unittest.TestCase):
    exercise=modules.NativeLinkedModuleTests.exercise

    def test_import_alias_replaces_an_existing_scalar_binding(self):
        self.exercise({'values.py':'MODULUS=13\n',
                      'main.py':"class Carrier:\n def __init__(self,value):self.modulus=value\nvalue=11\nfrom values import MODULUS as value\nitem=Carrier(value)\nprint(item.modulus)\n"})
