"""Canonical properties retain callbacks, descriptor priority and source order."""
import unittest

import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions


CASES={
'decorated_getter_and_shared_result':'''class Box:
 def __init__(self):self.values=[2,3]
 @property
 def value(self):return self.values
box=Box()
other=box.value
other.append(7)
print(box.value,other is box.value)
''',
'constructor_callbacks_and_ignored_setter_result':'''def get(obj):print('get');return obj.value
def put(obj,value):print('set',value);obj.value=value;return 99
def remove(obj):print('delete');obj.value=-1;return 88
class Box:
 def __init__(self):self.value=3
 item=property(get,put,remove,'documentation')
box=Box()
print(box.item)
box.item=8
print(box.item)
del box.item
print(box.item)
''',
'readonly_write':'''class Box:
 @property
 def item(self):return 3
def rhs():print('rhs');return 9
Box().item=rhs()
''',
'readonly_delete':'''class Box:
 @property
 def item(self):return 3
del Box().item
''',
'missing_getter':'''class Box:item=property()
print(Box().item)
''',
'missing_getter_stops_call_arguments':'''class Box:item=property()
def argument():print('unexpected');return 3
Box().item(argument())
''',
'getter_error_keeps_source_frames':'''class Box:
 @property
 def item(self):
  print('getter')
  return 1//0
print(Box().item)
''',
'store_rhs_before_receiver':'''def get(obj):return obj.value
def put(obj,value):print('setter',value);obj.value=value
class Box:
 def __init__(self):self.value=0
 item=property(get,put)
box=Box()
def owner():print('owner');return box
def rhs():print('rhs');return 4
owner().item=rhs()
print(box.item)
''',
'augmented_receiver_capture':'''def get(obj):print('get');return obj.value
def put(obj,value):print('set');obj.value=value
class Box:
 def __init__(self,value):self.value=value
 item=property(get,put)
box=Box(4)
original=box
def rhs():
 global box
 print('rhs')
 box=Box(20)
 return 3
box.item+=rhs()
print(original.item,box.item)
''',
'getter_returns_actual_callable_before_argument':'''def callback(value):print('callback',value);return value+2
class Box:
 @property
 def item(self):print('getter');return callback
def argument():print('argument');return 7
print(Box().item(argument()))
''',
'class_descriptor_identity_and_alias':'''def get(obj):return 1
shared=property(get)
class Box:
 first=shared
 second=shared
print(Box.first is shared,Box.first is Box.second,Box.second==shared)
Box().first=2
''',
'shared_descriptor_publication_in_other_class':'''def get(obj):return 1
shared=property(get)
class First:a=shared
class Second:z=shared
First().a=2
''',
'getter_returning_real_none':'''class Box:
 @property
 def item(self):return None
print(Box().item is None)
''',
'decorator_expression_precedes_function_defaults':'''def decorator():print('decorator');return property
def default():print('default');return [7]
class Box:
 @decorator()
 def item(self,value=default()):return value
box=Box()
value=box.item
value.append(9)
print(box.item)
''',
'constructor_in_initializer_cannot_shadow_property':'''class Box:
 def __init__(self):self.item=9
 @property
 def item(self):return 3
Box()
''',
'noncallable_setter_is_not_readonly':'''class Box:item=property(None,3)
Box().item=7
''',
'noncallable_deleter_is_not_readonly':'''class Box:item=property(None,None,3)
del Box().item
''',
'decorated_descriptor_class_body_alias':'''class Box:
 @property
 def first(self):return 7
 second=first
print(Box.first is Box.second,Box().first,Box().second)
Box().first=3
''',
'closure_callbacks_remain_separate':'''def make(offset):
 calls=[0]
 def get(obj):
  calls[0]+=1
  return offset+calls[0]+obj.value
 return property(get)
class First:
 def __init__(self):self.value=3
 item=make(10)
class Second:
 def __init__(self):self.value=4
 item=make(20)
print(First().item,Second().item,First().item)
print(First.item is Second.item)
''',
'callback_definition_defaults_remain_separate':'''def make(value):
 def get(obj,extra=[value]):return extra
 return property(get)
class First:item=make(3)
class Second:item=make(8)
left=First().item
right=Second().item
left.append(9)
print(First().item,Second().item,left is First().item,left is right)
''',
'shadowed_property_constructor_is_a_source_call':'''def property(getter):print('source');return 9
def get(obj):return 3
class Box:item=property(get)
print(Box().item)
''',
'aliased_canonical_constructor':'''make=property
def get(obj):return obj.value+2
class Box:
 value=7
 item=make(fget=get)
print(Box().item)
''',
'lexical_class_cell_survives_public_rebinding':'''class Box:
 @property
 def kind(self):return __class__
Alias=Box
Box=3
print(Alias().kind is Alias)
''',
'shared_getter_retains_original_lexical_class':'''class First:
 @property
 def kind(self):return __class__
shared=First.kind
class Second:kind=shared
print(Second().kind is First)
''',
'constructor_excess_arguments_keep_effects':'''def mark(value):print(value);return value
property(mark(1),mark(2),mark(3),mark(4),mark(5))
''',
'constructor_duplicate_argument_keeps_effects':'''def mark(value):print(value);return value
property(mark(1),fget=mark(2))
''',
'constructor_unknown_keyword_keeps_effects':'''def mark(value):print(value);return value
property(unknown=mark(1))
''',
}


CASES['descriptor_in_instance_field_stays_plain_value']='''def get(obj):print('getter');return 7
shared=property(get)
class Box:
 def __init__(self):self.descriptor=shared
box=Box()
print(box.descriptor is shared,bool(box.descriptor))
'''
CASES['constructor_total_argument_priority']='''def mark(value):print(value);return value
property(mark(1),mark(2),mark(3),mark(4),unknown=mark(5))
'''
CASES['constructor_duplicate_precedes_unknown_keyword']='''def mark(value):print(value);return value
property(mark(1),unknown=mark(2),fget=mark(3))
'''

CASES['descriptor_container_values_preserve_identity']='''first=property()
second=property()
values=[first,second,first]
print(values[0] is values[2],values[0]==values[1],tuple(values)[1] is second)
'''

CASES['ordinary_property_name_source_function']='''def property(value):return value+7
def run():return property(3)
print(run()+1)
'''
CASES['ordinary_property_name_source_lambda']='''property=lambda value:value+7
def run():return property(3)
print(run()+1)
'''
CASES['method_property_name_source_callback_rebinding']='''def property(value):return value+7
def change():
 global property
 property=lambda value:value+20
class Box:
 def run(self):
  first=property(3)
  change()
  return first+property(4)
print(Box().run())
'''
CASES['property_builtin_fallback_before_source_publication']='''def run():return property(None)
print(bool(run()))
def property(value):return False
print(bool(run()))
'''

CASES['generator_getter_is_lazy_and_keeps_receiver']='''class Box:
 def __init__(self):self.values=[2,3]
 @property
 def stream(self):
  print('getter body')
  for value in self.values:yield value
box=Box()
values=box.stream
print('created')
print(next(values),list(values))
'''
CASES['generator_setter_result_is_discarded_without_running']='''def get(obj):return obj.value
def put(obj,value):
 print('unexpected setter body')
 obj.value=value
 yield value
class Box:
 def __init__(self):self.value=2
 item=property(get,put)
box=Box()
box.item=8
print(box.item)
'''

CASES['alias_name_follows_insertion_order_not_last_store']='''def get(obj):return 7
shared=property(get)
class Box:
 first=shared
 second=shared
 first=shared
Box().first=3
'''
CASES['getter_returned_callable_captured_before_argument_rebinding']='''def first(value):return value+7
def second(value):return value+20
callback=first
class Box:
 @property
 def function(self):
  print('getter')
  return callback
def argument():
 global callback
 callback=second
 print('argument')
 return 3
box=Box()
print(box.function(argument()))
print(box.function(4))
'''

class PropertyExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_canonical_property_semantics(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(PropertyExecutionTests,_name,None)


class PropertyBoundaryTests(unittest.TestCase):
 def test_unsupported_property_update_metadata_and_mutation_are_named(self):
  cases=(
   ('class Box:\n @property\n def item(self):return 3\n @item.setter\n def item(self,value):pass\n','versioned'),
   ('class Box:\n @property\n def item(self):return 3\n @item.deleter\n def item(self):pass\n','versioned'),
   ('class Box:\n @property\n def item(self):return 3\nprint(Box.item.fget)\n','property'),
   ('class Box:\n @property\n def item(self):return 3\nBox.item=8\n','descriptor'),
   ('class Box:\n def __getattribute__(self,name):return 3\n @property\n def item(self):return 7\nprint(Box().item)\n','__getattribute__'),
   ('class Box:\n @property\n def item(self):return 3\nbox=Box()\nbox.__dict__["item"]=8\n','dictionary'),
   ('def get(obj):return 3\np=property(get)\np.fget=get\n','metadata'),
   ('def get(obj):return 3\np=property(get)\ndel p.__name__\n','metadata'),
   ('def get(obj):return 3\nclass Box:item=property(get)\ndel Box.item\n','property'),
   ('def get(obj):return 3\nclass Box:\n item=property(get)\n del item\n','property'),
   ('def get(obj):return 3\np=property(get)\nclass Box:a=(b:=p)\nBox().a=2\n','insertion order'),
   ('class First:\n @property\n def item(self):return 3\nclass Second:\n @property\n def item(self):return 4\ndef read(obj):return obj.item\nprint(read(First()),read(Second()))\n','finite receiver'),
   ('class Box:\n @property\n def __len__(self):return lambda:3\nprint(len(Box()))\n','descriptor'),

  )
  for source,fragment in cases:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none',filename='property_boundary.py'))
    self.assertFalse(result.success)
    self.assertIn(fragment,result.diagnostics[0].message)
    self.assertGreater(result.diagnostics[0].line,0)

class PropertyBindingTests(unittest.TestCase):
 def test_constructor_argument_errors_match_cpython_before_emission(self):
  from py2fastrust.native_properties import bind
  keywords=((),(('unknown',1),),(('fget',1),),(('fset',1),),(('doc',1),),
            (('unknown',1),('fget',1)),(('fset',1),('fget',1)),
            (('unknown',1),('other',1)),(('fget',1),('unknown',1),('fset',1)))
  for count in range(7):
   for named in keywords:
    with self.subTest(positional=count,keywords=named):
     positional=[None]*count
     try:property(*positional,**dict(named))
     except TypeError as error:expected='TypeError: '+str(error)
     else:expected=None
     self.assertEqual(bind(positional,named,None)[1],expected)

class PropertyLifetimeBoundaries(unittest.TestCase):
 def test_cycles_retaining_descriptor_payloads_are_diagnosed(self):
  sources=(
   'def make():\n def get(obj):return descriptor is not None\n descriptor=property(get)\n return descriptor\nclass Box:item=make()\nprint(Box().item)\n',
   'def make():\n values=[]\n descriptor=property(None,None,None,values)\n values.append(descriptor)\n return descriptor\nmake()\n',
   'def make():\n kind=None\n def get(obj):return kind is not None\n def bind(value):\n  nonlocal kind\n  kind=value\n return property(get),bind\nshared,bind=make()\nclass Box:item=shared\nbind(Box)\nprint(Box().item)\n',
  )
  for source in sources:
   with self.subTest(source=source):
    result=transpile(source,TranspileOptions(license='none',filename='property_cycle.py'))
    self.assertFalse(result.success)
    self.assertTrue(any('cycle'in diagnostic.message.lower()for diagnostic in result.diagnostics),result.diagnostics)

class PropertyModuleExecutionTests(unittest.TestCase):
 def exercise(self,files):
  import test_native_module_linking as support
  support.NativeLinkedModuleTests.exercise(self,files)
 def test_definition_module_and_mutable_global_callbacks(self):
  self.exercise({
   'main.py':'import library\nbox=library.Box()\nprint(box.item)\nlibrary.offset=20\nbox.item=27\nprint(box.base,box.item)\ndel box.item\nprint(box.base,library.events,library.shared is library.Box.item)\n',
   'library.py':'''offset=7
events=[]
def get(obj):
 events.append('get')
 return obj.base+offset
def put(obj,value):
 events.append('set')
 obj.base=value-offset
def remove(obj):
 events.append('delete')
 obj.base=0
shared=property(get,put,remove)
class Box:
 def __init__(self):self.base=1
 item=shared
'''})
 def test_cross_module_shared_descriptor_name_and_identity(self):
  self.exercise({
   'main.py':'import library\nshared=library.shared\nclass Local:\n def __init__(self):self.base=10\n other=shared\nprint(Local().other,library.Remote().item,Local.other is library.Remote.item)\nlibrary.Remote().item=3\n',
   'library.py':'def make(offset):\n def get(obj):return obj.base+offset\n return property(get)\nshared=make(7)\nclass Remote:\n def __init__(self):self.base=2\n item=shared\n'})


if __name__=='__main__':unittest.main()
