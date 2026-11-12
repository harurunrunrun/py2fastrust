"""Constant values never replace independent presence/observer certificates."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_constant_field_projection as projection
from py2fastrust.native_class_identity_demand import elided
from py2fastrust.native_packed_value_fields import selected as packed
from py2fastrust.references import BuiltinIdentity
from py2fastrust.native_module_calls import BuiltinRef
from py2fastrust.rust_pruning import _lex,_parse
import test_native_lambda_callbacks as helpers

CASES={'literal_and_dynamic_fields': ['class Scale:\n'
                                ' def __init__(self,value):self.base=97;self.value=value\n'
                                ' def read(self):return self.value%self.base\n'
                                'item=Scale(int(input()))\n'
                                'print(item.base,item.read())\n',
                                ['102\n', '-4\n']],
 'boolean_only_all_integer_modes': ['class Toggle:\n'
                                    ' def __init__(self):self.enabled=True\n'
                                    ' def read(self):return int(self.enabled)\n'
                                    'first=Toggle()\n'
                                    'second=Toggle()\n'
                                    'print(first.enabled,second.read())\n',
                                    ['']],
 'constructor_rhs_effects': ['def choose():\n'
                             " print('choose')\n"
                             ' return 97\n'
                             'class Scale:\n'
                             ' def __init__(self,value):self.base=choose();self.value=value\n'
                             ' def read(self):return self.base+self.value\n'
                             'print(Scale(2).read(),Scale(3).read())\n',
                             ['']],
 'constructor_failure_after_constant': ['class Scale:\n'
                                        ' def __init__(self,value):\n'
                                        '  self.base=97\n'
                                        "  print('before',value)\n"
                                        '  self.value=1//value\n'
                                        'item=Scale(int(input()))\n'
                                        'print(item.base,item.value)\n',
                                        ['0\n', '2\n']],
 'constructor_read_before_store': ['class Scale:\n'
                                   ' def __init__(self):\n'
                                   '  self.previous=self.base\n'
                                   '  self.base=97\n'
                                   'item=Scale()\n'
                                   'print(item.previous)\n',
                                   ['']],
 'conditional_missing_field': ['class Scale:\n'
                               ' def __init__(self,enabled):\n'
                               '  if enabled:self.base=97\n'
                               'item=Scale(int(input())!=0)\n'
                               'print(item.base)\n',
                               ['0\n', '1\n']],
 'same_value_write_after_publication': ['class Scale:\n'
                                        ' def __init__(self):self.base=97\n'
                                        'item=Scale()\n'
                                        'alias=item\n'
                                        'alias.base=97\n'
                                        'print(item.base)\n',
                                        ['']],
 'different_value_write_after_publication': ['class Scale:\n'
                                             ' def __init__(self):self.base=97\n'
                                             'item=Scale()\n'
                                             'alias=item\n'
                                             'alias.base=101\n'
                                             'print(item.base)\n',
                                             ['']],
 'field_deletion': ['class Scale:\n'
                    ' def __init__(self):self.base=97\n'
                    'item=Scale()\n'
                    'del item.base\n'
                    'print(item.base)\n',
                    ['']],
 'same_constant_fresh_factory': ['class Scale:\n'
                                 ' def __init__(self,value=0):self.base=97;self.value=value\n'
                                 ' @classmethod\n'
                                 ' def raw(cls,value):\n'
                                 '  item=cls()\n'
                                 '  item.base=97\n'
                                 '  item.value=value\n'
                                 '  return item\n'
                                 'first=Scale(2)\n'
                                 'second=Scale.raw(3)\n'
                                 'print(first.base,first.value,second.base,second.value)\n',
                                 ['']],
 'different_constructor_contexts': ['class Scale:\n'
                                    ' def __init__(self,base,value):self.base=base;self.value=value\n'
                                    ' def read(self):return self.value%self.base\n'
                                    'left=Scale(17,39)\n'
                                    'right=Scale(23,39)\n'
                                    'print(left.base,right.base,left.read(),right.read())\n',
                                    ['']],
 'same_literal_constructor_default': ['class Scale:\n'
                                      ' def __init__(self,base=97):self.base=base\n'
                                      'print(Scale().base,Scale(97).base)\n',
                                      ['']],
 'effectful_constructor_default': ['def make_default():\n'
                                   " print('default')\n"
                                   ' return 97\n'
                                   'class Scale:\n'
                                   ' def __init__(self,base=make_default()):self.base=base\n'
                                   'print(Scale().base,Scale().base)\n',
                                   ['']],
 'class_namespace_fallback': ['class Scale:\n'
                              ' base=97\n'
                              ' def __init__(self,enabled):\n'
                              '  if enabled:self.base=97\n'
                              'print(Scale(0).base,Scale(1).base,Scale.base)\n',
                              ['']],
 'instance_identity_observer': ['class Scale:\n'
                                ' def __init__(self):self.base=97\n'
                                'item=Scale()\n'
                                'print(id(item)==id(item),item.base)\n',
                                ['']],
 'actual_class_metadata_isinstance': ['class Scale:\n'
                                      ' def __init__(self):self.base=97\n'
                                      'item=Scale()\n'
                                      'print(isinstance(item,Scale),item.base)\n',
                                      ['']],
 'optional_receiver_error': ['class Scale:\n'
                             ' def __init__(self):self.base=97\n'
                             'item=Scale() if int(input()) else None\n'
                             'print(item.base)\n',
                             ['0\n', '1\n']],
 'unbound_receiver_error': ['class Scale:\n'
                            ' def __init__(self):self.base=97\n'
                            'def main():\n'
                            ' if int(input()):item=Scale()\n'
                            ' print(item.base)\n'
                            'main()\n',
                            ['0\n', '1\n']],
 'inplace_heap_invariant_declines': ['store=[97]\n'
                                     'alias=store\n'
                                     'alias *= 0\n'
                                     'alias.append(101)\n'
                                     'class Scale:\n'
                                     ' def __init__(self):self.base=store[-1]\n'
                                     'print(Scale().base)\n',
                                     ['']]}

CALLEES={'comprehension_source_shadow_isinstance': 'class Stamp:\n'
                                           ' def __init__(self):self.number=37\n'
                                           'def inspect(value,kind):\n'
                                           " print('callback')\n"
                                           ' return value.number==37\n'
                                           'item=Stamp()\n'
                                           'print([isinstance(item,Stamp) for isinstance in [inspect]])\n',
 'comprehension_mixed_source_builtin_isinstance': 'class Stamp:\n'
                                                  ' def __init__(self):self.number=37\n'
                                                  'def inspect(value,kind):\n'
                                                  " print('callback')\n"
                                                  ' return value.number==37\n'
                                                  'item=Stamp()\n'
                                                  'print([isinstance(item,Stamp) for isinstance in '
                                                  '[inspect,isinstance]])\n',
 'captured_canonical_getattr': 'class Stamp:\n'
                               ' def __init__(self):self.number=37\n'
                               'read=getattr\n'
                               'item=Stamp()\n'
                               "print(read(item,'number'))\n"}


class ConstantFieldProjectionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def capture(self,source,mode='i64'):
        records=[];prepare=projection.prepare
        def record(model):
            prepare(model);records.append(model.constant_field_projection)
        with patch.object(projection,'prepare',record):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(len(records),1)
        return result,records[0]

    def items(self,source):
        tokens,comments,pairs=_lex(source)
        return {(item.kind,item.name):source[item.start:item.end]
                for item in _parse(source,tokens,comments,pairs)}

    def unprojected(self,source,mode):
        def disable(model):model.constant_field_projection=SimpleNamespace(fields={})
        with patch.object(projection,'prepare',disable):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        return result

    def test_physical_slot_is_separate_from_logical_fields_and_metadata(self):
        for mode in ('i64','i128'):
            result,registry=self.capture(CASES['literal_and_dynamic_fields'][0],mode)
            owner=next(owner for owner in registry.model.classes.values()if owner.node.name=='Scale')
            index=list(owner.fields).index('base');dynamic=list(owner.fields).index('value')
            self.assertIn((owner.index,index),registry.fields)
            self.assertNotIn((owner.index,dynamic),registry.fields)
            self.assertTrue(packed(registry.model,owner))
            self.assertTrue(elided(registry.model,owner))
            items=self.items(result.rust_source)
            data=items['struct','ClassData_'+str(owner.index)]
            self.assertNotIn('field_'+str(index)+':',data)
            self.assertIn('field_'+str(dynamic)+':',data)
            previous=self.items(self.unprojected(CASES['literal_and_dynamic_fields'][0],mode).rust_source)
            before=previous['struct','ClassData_'+str(owner.index)]
            def metadata(body):
                return [part for part in body.split('{',1)[1].rsplit('}',1)[0].split(',')
                        if part and not part.startswith('field_')]
            self.assertEqual(metadata(before),metadata(data))
            getter=items['fn','class_get_'+str(owner.index)+'_'+str(index)]
            self.assertNotIn('.field_'+str(index),getter)
            self.assertIn('97_i128',getter)
            self.assertIn('value.as_ref()',getter)

    def test_boolean_only_slots_project_in_every_integer_mode(self):
        for mode in ('i64','i128','bigint'):
            result,registry=self.capture(CASES['boolean_only_all_integer_modes'][0],mode)
            owner=next(owner for owner in registry.model.classes.values()if owner.node.name=='Toggle')
            self.assertIn((owner.index,0),registry.fields)
            self.assertNotIn('field_0:',self.items(result.rust_source)['struct','ClassData_'+str(owner.index)])

    def test_reference_backed_integer_owner_keeps_original_storage(self):
        source=CASES['literal_and_dynamic_fields'][0]
        result,registry=self.capture(source,'bigint')
        self.assertFalse(registry.fields)
        self.assertEqual(result.rust_source,self.unprojected(source,'bigint').rust_source)

    def test_missing_presence_or_class_fallback_keeps_exact_native_code(self):
        for key in ('constructor_read_before_store','conditional_missing_field','class_namespace_fallback'):
            for mode in ('i64','i128'):
                source=CASES[key][0];result,registry=self.capture(source,mode)
                self.assertFalse(registry.fields,key)
                self.assertEqual(result.rust_source,self.unprojected(source,mode).rust_source,key)

    def test_published_mutations_deletion_and_observation_keep_storage(self):
        for key in ('different_value_write_after_publication',
                    'field_deletion','instance_identity_observer','inplace_heap_invariant_declines'):
            source=CASES[key][0];result,registry=self.capture(source)
            self.assertFalse(registry.fields,key)
            self.assertEqual(result.rust_source,self.unprojected(source,'i64').rust_source,key)

    def test_same_value_shared_writes_keep_identity_and_remove_only_the_constant_slot(self):
        source, inputs=CASES['same_value_write_after_publication']
        for mode in ('i64','i128'):
            result,registry=self.capture(source,mode)
            self.assertTrue(registry.fields)
            owner=next(owner for owner in registry.model.classes.values()if owner.node.name=='Scale')
            self.assertNotIn(owner.index,registry.model.value_classes.selected)
        self.exercise(source,inputs)

    def test_unproved_effectful_default_keeps_storage_and_default_code(self):
        source=CASES['effectful_constructor_default'][0]
        result,registry=self.capture(source)
        self.assertFalse(registry.fields)
        self.assertEqual(result.rust_source,self.unprojected(source,'i64').rust_source)

    def test_actual_shadow_and_mixed_builtin_callee_identities(self):
        for name in ('comprehension_source_shadow_isinstance','comprehension_mixed_source_builtin_isinstance'):
            _,registry=self.capture(CALLEES[name])
            seen=[]
            for plan in registry.scalars.plans.values():
                for node in registry.values.own_nodes(plan):
                    if(isinstance(node,ast.Call)and isinstance(node.func,ast.Name)
                            and node.func.id=='isinstance'):
                        names={item.name for item in registry.canonical(plan,node)
                               if isinstance(item,BuiltinIdentity)
                               or isinstance(item,BuiltinRef)and item.module=='builtins'}
                        seen.append(names)
            self.assertTrue(seen)
            self.assertEqual(seen,[set()]if name.endswith('shadow_isinstance')else[{'isinstance'}])

    def test_original_rhs_effects_and_constructor_errors(self):
        self.exercise(*CASES['constructor_rhs_effects'])
        self.exercise(*CASES['constructor_failure_after_constant'])

    def test_original_missing_field_read_before_initialization(self):
        self.exercise(*CASES['constructor_read_before_store'])
        self.exercise(*CASES['conditional_missing_field'])

    def test_original_optional_and_unbound_owner_errors(self):
        self.exercise(*CASES['optional_receiver_error'])
        self.exercise(*CASES['unbound_receiver_error'])

    def test_original_factory_defaults_and_actual_class_metadata(self):
        self.exercise(*CASES['same_constant_fresh_factory'])
        self.exercise(*CASES['same_literal_constructor_default'])
        self.exercise(*CASES['actual_class_metadata_isinstance'])

    def test_original_boolean_data_and_shadowed_source_calls(self):
        self.exercise(*CASES['boolean_only_all_integer_modes'])
        self.exercise(CALLEES['comprehension_source_shadow_isinstance'])
        self.exercise(CALLEES['comprehension_mixed_source_builtin_isinstance'])
