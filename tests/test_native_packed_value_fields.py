"""Packed value slots preserve initialization errors, aliases and field state."""
import re,shutil,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_packed_value_fields import prepare
import test_native_class_iterators as helpers

CASES={'branch_complete_and_prior_read_0': 'class Pair:\n'
                                     ' def __init__(this,n):\n'
                                     '  this.modulus=17\n'
                                     '  if n==0:this.value=0\n'
                                     '  else:this.value=n%this.modulus\n'
                                     ' def result(this):return '
                                     'this.modulus,this.value\n'
                                     'print(Pair(0).result(),Pair(23).result())\n',
 'primitive_fields_all_modes_0': 'class Flags:\n'
                                 ' def __init__(self):\n'
                                 '  self.ready=True\n'
                                 '  self.ratio=1.25\n'
                                 '  self.empty=None\n'
                                 ' def read(self):return '
                                 'self.ready,self.ratio,self.empty\n'
                                 'print(Flags().read())\n',
 'branch_return_none_complete_0': 'class Pair:\n'
                                  ' def __init__(self,n):\n'
                                  '  self.left=n\n'
                                  '  if n:\n'
                                  '   self.right=self.left+3\n'
                                  '   return None\n'
                                  '  self.right=7\n'
                                  ' def result(self):return '
                                  'self.left+self.right\n'
                                  'print(Pair(0).result(),Pair(2).result())\n',
 'constructor_side_effects_error_0': 'events=[]\n'
                                     'class Pair:\n'
                                     ' def __init__(self,n):\n'
                                     '  events.append(n)\n'
                                     '  self.left=n+1\n'
                                     '  self.right=20//n\n'
                                     ' def result(self):return '
                                     'self.left+self.right\n'
                                     'print(Pair(4).result(),events)\n'
                                     'print(Pair(int(input())).result())\n',
 'constructor_side_effects_error_1': 'events=[]\n'
                                     'class Pair:\n'
                                     ' def __init__(self,n):\n'
                                     '  events.append(n)\n'
                                     '  self.left=n+1\n'
                                     '  self.right=20//n\n'
                                     ' def result(self):return '
                                     'self.left+self.right\n'
                                     'print(Pair(4).result(),events)\n'
                                     'print(Pair(int(input())).result())\n',
 'assert_before_initialization_0': 'class Pair:\n'
                                   ' def __init__(self,n):\n'
                                   '  assert n>=0\n'
                                   '  self.left=n\n'
                                   '  self.right=self.left+1\n'
                                   ' def result(self):return '
                                   'self.left+self.right\n'
                                   'print(Pair(int(input())).result())\n',
 'assert_before_initialization_1': 'class Pair:\n'
                                   ' def __init__(self,n):\n'
                                   '  assert n>=0\n'
                                   '  self.left=n\n'
                                   '  self.right=self.left+1\n'
                                   ' def result(self):return '
                                   'self.left+self.right\n'
                                   'print(Pair(int(input())).result())\n',
 'missing_field_branch_0': 'class Pair:\n'
                           ' def __init__(self,n):\n'
                           '  self.left=n\n'
                           '  if n:self.right=9\n'
                           ' def result(self):return self.left+self.right\n'
                           'print(Pair(int(input())).result())\n',
 'missing_field_branch_1': 'class Pair:\n'
                           ' def __init__(self,n):\n'
                           '  self.left=n\n'
                           '  if n:self.right=9\n'
                           ' def result(self):return self.left+self.right\n'
                           'print(Pair(int(input())).result())\n',
 'preinitialization_read_0': 'class Pair:\n'
                             ' def __init__(self,n):\n'
                             '  self.left=self.right+n\n'
                             '  self.right=7\n'
                             ' def result(self):return self.left\n'
                             'print(Pair(3).result())\n',
 'preinitialization_condition_0': 'class Flags:\n'
                                  ' def __init__(self):\n'
                                  '  if self.ready:self.value=1\n'
                                  '  else:self.value=2\n'
                                  '  self.ready=True\n'
                                  ' def read(self):return self.value\n'
                                  'print(Flags().read())\n',
 'class_default_fallback_0': 'class Pair:\n'
                             ' value=7\n'
                             ' def __init__(self,n):\n'
                             '  self.left=self.value\n'
                             '  self.value=n\n'
                             ' def result(self):return self.left,self.value\n'
                             'print(Pair(3).result())\n',
 'reachable_field_deletion_0': 'class Pair:\n'
                               ' def __init__(self,n):self.value=n\n'
                               ' def clear(self):del self.value\n'
                               ' def read(self):return self.value\n'
                               'owner=Pair(3)\n'
                               'owner.clear()\n'
                               'print(owner.read())\n',
 'factory_adds_missing_field_0': 'class Pair:\n'
                                 ' def __init__(self,n):self.left=n\n'
                                 ' def result(self):return '
                                 'self.left+self.right\n'
                                 'def make(n):\n'
                                 ' owner=Pair(n)\n'
                                 ' owner.right=7\n'
                                 ' return owner\n'
                                 'print(make(3).result())\n',
 'factory_updates_complete_fields_0': 'class Pair:\n'
                                      ' def __init__(self,n):\n'
                                      '  self.left=n\n'
                                      '  self.right=self.left+1\n'
                                      ' def result(self):return '
                                      'self.left+self.right\n'
                                      'def make(n):\n'
                                      ' owner=Pair(0)\n'
                                      ' owner.left=n\n'
                                      ' owner.right=n+2\n'
                                      ' return owner\n'
                                      'print(make(3).result(),Pair(5).result())\n',
 'early_return_missing_field_0': 'class Pair:\n'
                                 ' def __init__(self,n):\n'
                                 '  self.left=n\n'
                                 '  if n:return None\n'
                                 '  self.right=7\n'
                                 ' def result(self):return '
                                 'self.left+self.right\n'
                                 'print(Pair(int(input())).result())\n',
 'early_return_missing_field_1': 'class Pair:\n'
                                 ' def __init__(self,n):\n'
                                 '  self.left=n\n'
                                 '  if n:return None\n'
                                 '  self.right=7\n'
                                 ' def result(self):return '
                                 'self.left+self.right\n'
                                 'print(Pair(int(input())).result())\n',
 'loop_initialization_declines_0': 'class Pair:\n'
                                   ' def __init__(self,count):\n'
                                   '  for i in range(count):self.value=i+4\n'
                                   ' def read(self):return self.value\n'
                                   'print(Pair(int(input())).read())\n',
 'loop_initialization_declines_1': 'class Pair:\n'
                                   ' def __init__(self,count):\n'
                                   '  for i in range(count):self.value=i+4\n'
                                   ' def read(self):return self.value\n'
                                   'print(Pair(int(input())).read())\n',
 'explicit_initializer_reentry_0': 'class Pair:\n'
                                   ' def __init__(self,n):self.value=n\n'
                                   ' def read(self):return self.value\n'
                                   'owner=Pair(2)\n'
                                   'owner.__init__(7)\n'
                                   'print(owner.read())\n',
 'initializer_alias_declines_0': 'class Pair:\n'
                                 ' def __init__(self,n):\n'
                                 '  alias=self\n'
                                 '  alias.value=n\n'
                                 ' def read(self):return self.value\n'
                                 'print(Pair(3).read())\n',
 'annotation_target_receiver_read_0': 'class Number:\n'
                                      ' def __init__(self):\n'
                                      '  self.later.real: int\n'
                                      '  self.later=7\n'
                                      ' def read(self):return self.later\n'
                                      'print(Number().read())\n',
 'augmented_first_read_before_rhs_0': 'def later():\n'
                                      " print('rhs')\n"
                                      ' return 1\n'
                                      'class Number:\n'
                                      ' def __init__(self):\n'
                                      '  self.value+=later()\n'
                                      '  self.value=7\n'
                                      ' def read(self):return self.value\n'
                                      'print(Number().read())\n'}
INPUTS={'assert_before_initialization_0': '-1\n',
 'assert_before_initialization_1': '2\n',
 'constructor_side_effects_error_0': '0\n',
 'constructor_side_effects_error_1': '5\n',
 'early_return_missing_field_0': '0\n',
 'early_return_missing_field_1': '1\n',
 'loop_initialization_declines_0': '0\n',
 'loop_initialization_declines_1': '1\n',
 'missing_field_branch_0': '0\n',
 'missing_field_branch_1': '1\n'}
BOUNDARIES={'raw_allocator_boundary_0': 'class Pair:\n'
                             ' def __init__(self,n):self.value=n\n'
                             ' def read(self):return self.value\n'
                             'owner=object.__new__(Pair)\n'
                             'print(owner.read())\n',
 'reflective_allocator_boundary_0': 'class Pair:\n'
                                    ' def __init__(self,n):self.value=n\n'
                                    ' def read(self):return self.value\n'
                                    "allocate=getattr(object,'__new__')\n"
                                    'owner=allocate(Pair)\n'
                                    'print(owner.read())\n'}

class PackedFieldProofs(unittest.TestCase):
 def compile(self,name,mode='i64',disabled=False):
  owners=[]
  def capture(model):
   prepare(model)
   owners.extend(dict(index=owner.index,fields=list(owner.fields),packed=owner.index in model.packed_value_fields.selected,initializer=owner.methods.get('__init__').index if owner.methods.get('__init__')is not None else None,model=model,definition=owner)for owner in model.classes.values()if owner.used)
   if disabled:model.packed_value_fields.selected.clear()
  with patch('py2fastrust.native_packed_value_fields.prepare',side_effect=capture):
   product=transpile(CASES[name],TranspileOptions(integer=mode,license='none'))
  self.assertTrue(product.success,product.diagnostics)
  return product,owners
 def test_renamed_receiver_and_all_normal_branches_use_raw_slots(self):
  for mode in ('i64','i128'):
   product,owners=self.compile('branch_complete_and_prior_read_0',mode)
   packed=[owner for owner in owners if owner['packed']]
   self.assertEqual(len(packed),1)
   owner=packed[0]
   for index in range(len(owner['fields'])):
    from py2fastrust.native_constant_field_projection import selected
    projected=selected(owner['model'],owner['definition'],index)
    if projected:
     self.assertEqual(owner['model'].constant_field_projection.fields[owner['index'],index].low,17)
     self.assertNotIn(f'field_{index}:std::cell::Cell<NativeInt>',product.rust_source)
    else:self.assertIn(f'field_{index}:std::cell::Cell<NativeInt>',product.rust_source)
    getter=re.search(r'fn class_get_'+str(owner['index'])+'_'+str(index)+r'\([^\n]+',product.rust_source).group()
    self.assertIn('{Ok(',getter)
    self.assertNotIn('ok_or_else',getter)
 def test_only_copy_primitive_modes_are_packed(self):
  product,owners=self.compile('branch_complete_and_prior_read_0','bigint')
  self.assertFalse(any(owner['packed']for owner in owners))
  for mode in ('i64','i128','bigint'):
   product,owners=self.compile('primitive_fields_all_modes_0',mode)
   self.assertTrue(any(owner['packed']for owner in owners))
   owner=next(owner for owner in owners if owner['packed'])
   from py2fastrust.native_constant_field_projection import selected
   for index,rust_type in enumerate(('bool','f64','()')):
    if selected(owner['model'],owner['definition'],index):
     self.assertEqual(rust_type,'bool')
     self.assertIs(owner['model'].constant_field_projection.fields[owner['index'],index].low,True)
     self.assertNotIn(f'field_{index}:std::cell::Cell<bool>',product.rust_source)
    else:self.assertIn('std::cell::Cell<'+rust_type+'>',product.rust_source)
 def test_missing_read_delete_namespace_and_reentry_keep_old_layout(self):
  names=('missing_field_branch_0','preinitialization_read_0',
         'preinitialization_condition_0','class_default_fallback_0',
         'reachable_field_deletion_0','factory_adds_missing_field_0',
         'early_return_missing_field_0','loop_initialization_declines_0',
         'explicit_initializer_reentry_0','initializer_alias_declines_0',
         'annotation_target_receiver_read_0','augmented_first_read_before_rhs_0')
  for name in names:
   for mode in ('i64','i128','bigint'):
    with self.subTest(name=name,mode=mode):
     current,owners=self.compile(name,mode)
     old,_=self.compile(name,mode,disabled=True)
     self.assertFalse(any(owner['packed']for owner in owners))
     self.assertEqual(current.rust_source,old.rust_source)
 def test_fresh_factory_updates_preserve_initialized_layout(self):
  for name in ('factory_updates_complete_fields_0','branch_return_none_complete_0'):
   product,owners=self.compile(name)
   self.assertTrue(any(owner['packed']for owner in owners))
 def test_data_literals_are_sealed_inside_initializer_calling_constructors(self):
  from py2fastrust.rust_pruning import _lex,_parse
  product,owners=self.compile('branch_complete_and_prior_read_0')
  tokens,comments,pairs=_lex(product.rust_source)
  items=_parse(product.rust_source,tokens,comments,pairs)
  for owner in owners:
   if not owner['packed']:continue
   schema='ClassData_'+str(owner['index']);allocations=[]
   for index,token in enumerate(tokens[:-1]):
    if token.text!=schema or tokens[index+1].text!='{':continue
    if index and tokens[index-1].text in {'struct','impl','for','->'}:continue
    item=next((item for item in items if item.kind=='fn'and item.start<=token.start<item.end),None)
    self.assertIsNotNone(item)
    self.assertEqual(item.name,'class_construct_'+str(owner['index']))
    allocations.append(item)
   self.assertEqual(len(allocations),1)
   body=product.rust_source[allocations[0].start:allocations[0].end]
   self.assertLess(body.index('class_function_'+str(owner['initializer'])),body.rindex('Ok(object)'))
 def test_raw_and_reflective_allocation_keep_exact_diagnostics(self):
  for source in BOUNDARIES.values():
   for mode in ('i64','i128','bigint'):
    current=transpile(source,TranspileOptions(integer=mode,license='none'))
    with patch('py2fastrust.native_packed_value_fields.prepare',side_effect=lambda model:setattr(model,'packed_value_fields',type('Unpacked',(),{'selected':set()})())):
     old=transpile(source,TranspileOptions(integer=mode,license='none'))
    self.assertFalse(current.success)
    self.assertEqual([str(d)for d in current.diagnostics],[str(d)for d in old.diagnostics])
    self.assertTrue(all(d.code=='E006'for d in current.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class PackedFieldExecution(unittest.TestCase):
 cases=CASES
 inputs=INPUTS
 check=helpers.IteratorExecutionTests.check
 def test_branch_complete_and_prior_read_0(self):self.check('branch_complete_and_prior_read_0')
 def test_primitive_fields_all_modes_0(self):self.check('primitive_fields_all_modes_0')
 def test_branch_return_none_complete_0(self):self.check('branch_return_none_complete_0')
 def test_constructor_side_effects_error_0(self):self.check('constructor_side_effects_error_0')
 def test_constructor_side_effects_error_1(self):self.check('constructor_side_effects_error_1')
 def test_assert_before_initialization_0(self):self.check('assert_before_initialization_0')
 def test_assert_before_initialization_1(self):self.check('assert_before_initialization_1')
 def test_missing_field_branch_0(self):self.check('missing_field_branch_0')
 def test_missing_field_branch_1(self):self.check('missing_field_branch_1')
 def test_preinitialization_read_0(self):self.check('preinitialization_read_0')
 def test_preinitialization_condition_0(self):self.check('preinitialization_condition_0')
 def test_class_default_fallback_0(self):self.check('class_default_fallback_0')
 def test_reachable_field_deletion_0(self):self.check('reachable_field_deletion_0')
 def test_factory_adds_missing_field_0(self):self.check('factory_adds_missing_field_0')
 def test_factory_updates_complete_fields_0(self):self.check('factory_updates_complete_fields_0')
 def test_early_return_missing_field_0(self):self.check('early_return_missing_field_0')
 def test_early_return_missing_field_1(self):self.check('early_return_missing_field_1')
 def test_loop_initialization_declines_0(self):self.check('loop_initialization_declines_0')
 def test_loop_initialization_declines_1(self):self.check('loop_initialization_declines_1')
 def test_explicit_initializer_reentry_0(self):self.check('explicit_initializer_reentry_0')
 def test_initializer_alias_declines_0(self):self.check('initializer_alias_declines_0')
 def test_annotation_target_receiver_read_0(self):self.check('annotation_target_receiver_read_0')
 def test_augmented_first_read_before_rhs_0(self):self.check('augmented_first_read_before_rhs_0')
