"""Finite builtin index errors preserve checked get/RHS/store order."""
import unittest
import test_native_class_iterators as iterator_tests

CASES={
'nullable_index_get_then_rhs':'''def index(flag):
 print('index',flag)
 if flag:return 0
 return None
def rhs():print('rhs');return 3
def update(flag):
 a=[2,4]
 a[index(flag)]+=rhs()
 print(a)
update(True)
update(False)
''',
'nullable_store_evaluates_rhs_first':'''def index(flag):
 print('index',flag)
 if flag:return 0
 return None
def rhs():print('rhs');return 3
def update(flag):
 a=[2,4]
 a[index(flag)]=rhs()
 print(a)
update(True)
update(False)
''',
'nullable_bitop_never_evaluates_rhs_after_bad_get':'''def index(flag):
 print('index',flag)
 if flag:return 0
 return None
def update(flag):
 a=[3,5]
 a[index(flag)]^=a[index(True)]
 print(a)
update(True)
update(False)
''',
'valid_integral_aliases':'''a=[3,5]
other=a
index=1
a[index]+=other[0]
a[0]^=other[index]
print(a,other,a is other)
''',
'plain_none_index_error':'''a=[3,5]
a[None]+=2
''',
'plain_float_index_error':'''a=[3,5]
a[1.5]+=2
''',
}


CASES.update({
'local_bad_index_stops_before_rhs':'''def rhs():print('unexpected');return 2
def bad():
 a=[1,2]
 a[None]+=rhs()
bad()
''',
'field_bad_index_stops_before_rhs':'''def rhs():print('unexpected');return 2
class Bad:
 def __init__(self):self.a=[1,2]
 def bad(self):self.a[None]+=rhs()
Bad().bad()
''',
'range_index_is_not_an_integer':'''a=[1,2]
a[range(3)]+=2
''',
})

class ListIndexAlternativeExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_index_alternatives_and_augmented_order(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(ListIndexAlternativeExecutionTests,_name,None)

if __name__=='__main__':unittest.main()
