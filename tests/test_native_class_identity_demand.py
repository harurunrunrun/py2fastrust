"""Original-source identity observations constrain private value carrier elision."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_class_identity_demand as demand
import test_native_lambda_callbacks as helpers


CASES = {'numeric_reduction': ('class Amount:\n def __init__(self,value=0):self.value=value\n def add(self,other):return Amount(self.value+other.value)\ndef main():\n rows=[Amount(i)for i in range(7)]\n total=Amount()\n for item in rows:total=total.add(item)\n print(total.value)\nmain()\n', ('',)), 'constructor_effects': ("class Entry:\n def __init__(self,value):\n  print('construct',value)\n  self.value=value\nresult=Entry(4)\nprint(result.value)\n", ('',)), 'copy_bool_float_none': ('class Flags:\n def __init__(self,flag,value):\n  self.flag=flag\n  self.value=value\n  self.extra=None\n def read(self):return self.value if self.flag else -self.value\nleft=Flags(True,2.5)\nright=Flags(False,1.25)\nprint(left.read()+right.read(),left.extra)\n', ('',)), 'metadata_isinstance': ('class Amount:\n def __init__(self,value):self.value=value\nclass Other:\n def __init__(self,value):self.value=value\nleft=Amount(7)\nright=Other(9)\nprint(isinstance(left,Amount),isinstance(left,Other),isinstance(right,Other),left.value+right.value)\n', ('',)), 'other_owner_observes_id': ('class Numeric:\n def __init__(self,value):self.value=value\nclass Observed:\n def __init__(self,value):self.value=value\nnumber=Numeric(8)\nleft=Observed(2)\nnumber=Numeric(number.value+3)\nright=Observed(2)\nprint(number.value,id(left)!=id(right),id(left)==id(left))\n', ('',)), 'retained_id_unused': ('class Amount:\n def __init__(self,value):self.value=value\nsaved=id\nleft=Amount(2)\nright=Amount(5)\nprint(left.value+right.value)\n', ('',)), 'nested_default_representation': ("class Entry:\n def __init__(self,value):self.value=value\nitem=Entry(3)\ntext=str([(item,[item])])\nprint(text.count('Entry object at 0x'))\n", ('',)), 'container_identity_comparisons': ('class Entry:\n def __init__(self,value):self.value=value\nleft=Entry(3)\nright=Entry(3)\nprint([left]==[left],[left]==[right],left in [left],right in [left])\n', ('',)), 'bound_method_identity': ('class Entry:\n def __init__(self,value):self.value=value\n def read(self):return self.value\nitem=Entry(3)\nsaved=item.read\nprint(saved(),saved==item.read,saved is item.read)\n', ('',)), 'saved_classmethod_identity': ('class Amount:\n def __init__(self,value=0):self.value=value\n @classmethod\n def make(cls,value=0):return cls(value)\nsaved=Amount.make\nleft=Amount(3)\nprint(saved==Amount.make,saved is Amount.make,saved(8).value+left.value)\n', ('',)), 'default_value_carrier': ('class Bucket:\n def __init__(self,value):self.value=value\ndef read(value=Bucket(7)):return value.value\nprint(read(),read(Bucket(9)))\n', ('',)), 'evaluated_keyword_default_id': ('class Numeric:\n def __init__(self,value):self.value=value\nclass Observed:\n def __init__(self,value):self.value=value\nleft=Observed(3)\nnumber=Numeric(4)\nidentify=id\ndef same(*,expected=identify(left)):return expected==identify(left)\nnumber=Numeric(number.value+2)\nprint(same(),number.value)\n', ('',)), 'classmethod_mixed_union_internal': ('class Number:\n def __init__(self,value):self.value=value\n @classmethod\n def total(cls,enabled):\n  value=cls(7)if enabled else 4\n  if isinstance(value,int):return value+1\n  return value.value+2\nprint(Number.total(int(input())!=0))\n', ('0\n', '1\n')), 'nested_internal_packets': ('class Number:\n def __init__(self,value):self.value=value\ndef total(rows):\n result=0\n for row in rows:\n  for pair in row:result+=pair[0].value+pair[1].value\n return result\nrows=[[(Number(i),Number(i+1))for i in range(3)]]\nprint(total(rows))\n', ('',)), 'error_path_container_representation': ("class Number:\n def __init__(self,value):self.value=value\nclass Entry:\n def __init__(self,value):self.value=value\nnumber=Number(7)\nitem=Entry(4)\nif int(input())==0:\n print(str((item,[item])).count('Entry object at 0x'))\n raise ValueError('closed')\nprint(number.value+item.value)\n", ('0\n', '1\n'))}


class NativeClassIdentityDemandTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise

    def capture(self,source,mode,**options):
        registries=[]
        prepare=demand.prepare
        def record(model):
            prepare(model)
            registries.append(model.class_identity_demand)
        with patch.object(demand,'prepare',record):
            result=transpile(source,TranspileOptions(integer=mode,license='none',**options))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(len(registries),1)
        return result,registries[0]

    def test_unobserved_ids_leave_neither_carrier_nor_tls_allocator(self):
        for mode in ('i64','i128','bigint'):
            result,registry=self.capture(CASES['numeric_reduction'][0],mode)
            if mode!='bigint':
                self.assertEqual(registry.elided,registry.values.selected)
                self.assertTrue(registry.elided)
                self.assertIn('type ClassHandle_0=ClassData_0;',result.rust_source)
                self.assertNotIn('impl ClassDisplay for ClassHandle_0',result.rust_source)
            self.assertNotIn('class_value_identity',result.rust_source)
            self.assertNotIn('class_value_next_id',result.rust_source)
            self.assertNotIn('CLASS_VALUE_NEXT_ID',result.rust_source)
            self.assertIn('fn class_construct_0(',result.rust_source)

    def test_observer_on_another_owner_preserves_whole_sequence(self):
        for mode in ('i64','i128'):
            result,registry=self.capture(CASES['other_owner_observes_id'][0],mode)
            self.assertTrue(registry.values.selected)
            self.assertFalse(registry.elided)
            self.assertIn('class_value_identity:usize',result.rust_source)
            self.assertIn('class_value_next_id()',result.rust_source)
            self.assertIn('shared identity sequence',' '.join(registry.reasons.values()))

    def test_saved_observer_preserves_sequence_without_a_call(self):
        for mode in ('i64','i128'):
            result,registry=self.capture(CASES['retained_id_unused'][0],mode)
            self.assertTrue(registry.values.selected)
            self.assertFalse(registry.elided)
            self.assertIn('class_value_next_id()',result.rust_source)

    def test_classmethod_receiver_identity_keeps_actual_metadata(self):
        for mode in ('i64','i128'):
            result,registry=self.capture(CASES['saved_classmethod_identity'][0],mode)
            self.assertTrue(registry.elided)
            self.assertNotIn('class_value_identity',result.rust_source)
            self.assertIn('class_definition:',result.rust_source)
            self.assertIn('ClassClassRef',result.rust_source)
            self.assertIn('Rc::ptr_eq(&left.bound.receiver,&right.bound.receiver)',result.rust_source)

    def test_no_pruning_does_not_restore_identity_storage(self):
        for mode in ('i64','i128','bigint'):
            result,registry=self.capture(CASES['numeric_reduction'][0],mode,optimize=False)
            self.assertNotIn('class_value_identity',result.rust_source)
            self.assertNotIn('class_value_next_id',result.rust_source)

    def test_original_numeric_reduction(self):
        self.exercise(*CASES['numeric_reduction'])

    def test_original_constructor_effects(self):
        self.exercise(*CASES['constructor_effects'])

    def test_original_copy_bool_float_none(self):
        self.exercise(*CASES['copy_bool_float_none'])

    def test_original_metadata_isinstance(self):
        self.exercise(*CASES['metadata_isinstance'])

    def test_original_other_owner_observes_id(self):
        self.exercise(*CASES['other_owner_observes_id'])

    def test_original_retained_id_unused(self):
        self.exercise(*CASES['retained_id_unused'])

    def test_original_nested_default_representation(self):
        self.exercise(*CASES['nested_default_representation'])

    def test_original_container_identity_comparisons(self):
        self.exercise(*CASES['container_identity_comparisons'])

    def test_original_bound_method_identity(self):
        self.exercise(*CASES['bound_method_identity'])

    def test_original_default_value_carrier(self):
        self.exercise(*CASES['default_value_carrier'])

    def test_original_evaluated_keyword_default_id(self):
        self.exercise(*CASES['evaluated_keyword_default_id'])

    def test_original_saved_classmethod_identity(self):
        self.exercise(*CASES['saved_classmethod_identity'])

    def test_original_classmethod_mixed_union_internal(self):
        self.exercise(*CASES['classmethod_mixed_union_internal'])

    def test_original_nested_internal_packets(self):
        self.exercise(*CASES['nested_internal_packets'])

    def test_original_error_path_container_representation(self):
        self.exercise(*CASES['error_path_container_representation'])

