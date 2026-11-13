"""A failed producer has no iterable result; later inference may widen it."""
import unittest
import test_native_class_iterators as iterator_tests


FACTORY='''class Payload:
 def __init__(self,value):self.a=value;self.b=value+1
 def values(self):return [self.a,self.b]
class Factory:
 def __init__(self,value):self.payload=Payload(value)
 def choose(self,flag):
  if flag:return None
  return self.payload
factory=Factory(8)
value=factory.choose(False)
'''

CASES={
'widened_source_method_spread':FACTORY+'''print(*value.values())
''',
'widened_source_method_materializers':FACTORY+'''print(list(value.values()),tuple(value.values()))
print(sum(value.values()),min(value.values()))
''',
'widened_source_method_reducers':FACTORY+'''print(max(value.values()),any(value.values()),all(value.values()))
print(sum(1 for item in value.values()),list(value.values()).count(8))
''',
'failed_lookup_spread':'''def owner():print('owner');return None
print(*owner().missing())
''',
'failed_lookup_list':'''def owner():print('owner');return None
print(list(owner().missing()))
''',
'failed_lookup_tuple':'''def owner():print('owner');return None
print(tuple(owner().missing()))
''',
'failed_lookup_sorted':'''def owner():print('owner');return None
print(sorted(owner().missing()))
''',
'failed_lookup_sum':'''def owner():print('owner');return None
print(sum(owner().missing()))
''',
'failed_lookup_forward_cursor':'''def owner():print('owner');return None
cursor=iter(owner().missing())
print(next(cursor))
''',
'failed_lookup_reverse_cursor':'''def owner():print('owner');return None
cursor=reversed(owner().missing())
print(next(cursor))
''',
'actual_field_and_none_alternatives':'''class Payload:
 def __init__(self,value):self.data=value
for flag in [True,False]:
 value=Payload(7)if flag else None
 print(value.data)
''',
'ordinary_numeric_array_materialization':'''from array import array
values=array('i',[3,1,4,1])
print(*values.tolist())
''',
'ordinary_integer_print':'''values=[3,1,4,1]
print(*values,sep=':')
''',
}

for _name,_expression in (
 ('min','min(owner().missing())'),('max','max(owner().missing())'),
 ('any','any(owner().missing())'),('all','all(owner().missing())'),
 ('count_generator','sum(1 for value in owner().missing())'),
 ('list_count','list(owner().missing()).count(2)'),('length','len(list(owner().missing()))')):
 CASES['failed_lookup_'+_name]='def owner():print("owner");return None\nprint('+_expression+')\n'


class BottomIterableExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_bottom_producers_and_fair_widening(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)

for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(BottomIterableExecutionTests,_name,None)


if __name__=='__main__':unittest.main()
