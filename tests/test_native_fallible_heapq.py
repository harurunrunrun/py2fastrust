"""Native heaps preserve rich-call traces, errors and the actual shared list."""
import unittest
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions


KEY='''import heapq
class Key:
 def __init__(self,value,label):self.value=value;self.label=label
 def __lt__(self,other):
  print('less',self.label,other.label)
  return self.value<other.value
'''
SUPPRESS='''class Suppress:
 def __enter__(self):return None
 def __exit__(self,typ,value,trace):return True
'''

CASES={
'source_min_core_operations':KEY+'''items=[Key(4,0),Key(1,1),Key(3,2),Key(2,3)]
alias=items
heapq.heapify(items)
print([x.label for x in items],alias is items)
heapq.heappush(items,Key(0,4))
print(heapq.heappushpop(items,Key(6,5)).label)
print(heapq.heapreplace(items,Key(5,6)).label)
print([heapq.heappop(items).label for _ in range(len(items))])
''',
'source_max_core_operations':KEY+'''items=[Key(4,0),Key(1,1),Key(3,2),Key(2,3)]
heapq.heapify_max(items)
print([x.label for x in items])
heapq.heappush_max(items,Key(7,4))
print(heapq.heappushpop_max(items,Key(0,5)).label)
print(heapq.heapreplace_max(items,Key(5,6)).label)
print([heapq.heappop_max(items).label for _ in range(len(items))])
''',
'tuple_ties_reach_mutable_list_fields':'''import heapq
items=[(2,0,[8,9]),(1,0,[4]),(1,0,[3,8]),(1,0,[3,7]),(1,0,[])]
saved=items[1][2]
heapq.heapify(items)
saved[0]=2
heapq.heappush(items,(1,0,[3,6]))
print([heapq.heappop(items)for _ in range(len(items))])
''',
'nested_builtin_lists_and_tuple_lengths':'''import heapq
items=[[[3]],[[1,4]],[[1,3]],[],[[1]]]
heapq.heapify(items)
print([heapq.heappop(items)for _ in range(len(items))])
rows=[(0,[2]),(0,[1,2]),(0,[])]
heapq.heapify_max(rows)
print([heapq.heappop_max(rows)for _ in range(len(rows))])
''',
'finite_builtin_leaf_alternatives_raise_only_when_reached':SUPPRESS+'''import heapq
items=[(0,[1]),(1,['a'])]
heapq.heapify(items)
print(items)
with Suppress():heapq.heappush(items,(0,['x']))
print(items)
''',
'unorderable_none_is_valid_until_a_comparison':SUPPRESS+'''import heapq
items=[None]
heapq.heapify(items)
print(heapq.heappop(items),items)
heapq.heappush(items,None)
with Suppress():heapq.heappush(items,None)
print(items)
''',
'rich_result_uses_bool_callback':'''import heapq
class Decision:
 def __init__(self,value):self.value=value
 def __bool__(self):print('truth',self.value);return self.value
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):print('less',self.value,other.value);return Decision(self.value<other.value)
items=[Item(4),Item(1),Item(3)]
heapq.heapify(items)
print([heapq.heappop(items).value for _ in range(len(items))])
''',
'rich_result_uses_length_callback':'''import heapq
class Decision:
 def __init__(self,value):self.value=value
 def __len__(self):print('length',self.value);return int(self.value)
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):return Decision(self.value<other.value)
items=[]
heapq.heappush(items,Item(4))
heapq.heappush(items,Item(2))
print([heapq.heappop(items).value for _ in range(len(items))])
''',
'reflected_ordering_is_called_after_not_implemented':'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):print('lt',self.value,other.value);return NotImplemented
 def __gt__(self,other):print('gt',self.value,other.value);return self.value>other.value
items=[Item(3),Item(1),Item(2)]
heapq.heapify(items)
print([heapq.heappop(items).value for _ in range(len(items))])
''',
'same_item_aliases_preserve_mutable_receiver_state':'''import heapq
class Item:
 def __init__(self,value):self.value=value;self.calls=0
 def __lt__(self,other):
  self.calls+=1
  other.calls+=2
  print(self.value,other.value,self.calls,other.calls)
  return self.value<other.value
first=Item(2)
second=Item(1)
items=[first,first,second]
heapq.heapify(items)
print(first.calls,second.calls,items[1] is first)
''',
'comparison_error_leaves_partial_push_and_heapify':SUPPRESS+'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  print('less',self.value,other.value)
  if self.value==0:raise ValueError('stop')
  return self.value<other.value
items=[Item(1),Item(2),Item(3)]
with Suppress():heapq.heappush(items,Item(0))
print([x.value for x in items])
items=[Item(0),Item(3),Item(2),Item(1)]
with Suppress():heapq.heapify(items)
print([x.value for x in items])
''',
'comparison_error_leaves_partial_pop_and_replace':SUPPRESS+'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  print('less',self.value,other.value)
  if self.value==4:raise ValueError('stop')
  return self.value<other.value
items=[Item(1),Item(2),Item(3),Item(4)]
with Suppress():heapq.heappop(items)
print([x.value for x in items])
items=[Item(1),Item(2),Item(3)]
with Suppress():heapq.heapreplace(items,Item(4))
print([x.value for x in items])
''',
'same_length_callback_replacement_uses_current_slots':'''import heapq
changed=False
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  global changed
  print('less',self.value,other.value)
  if not changed:
   changed=True
   items[0]=Item(20)
   items[-1]=Item(10)
  return self.value<other.value
items=[Item(4),Item(2),Item(3),Item(1)]
heapq.heapify(items)
print([x.value for x in items])
''',
'size_change_after_comparison_raises_and_keeps_mutation':SUPPRESS+'''import heapq
changed=False
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  global changed
  if not changed:
   changed=True
   items.append(Item(9))
  return self.value<other.value
items=[Item(3),Item(2),Item(1)]
with Suppress():heapq.heapify(items)
print([x.value for x in items])
''',
'pushpop_false_retains_cleared_heap_without_error':'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):items.clear();print('clear');return False
items=[Item(1)]
print(heapq.heappushpop(items,Item(2)).value,len(items))
''',
'pushpop_true_after_clear_raises_index_error':SUPPRESS+'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):items.clear();print('clear');return True
items=[Item(1)]
with Suppress():heapq.heappushpop(items,Item(2))
print(items)
''',
'reentrant_same_length_heap_replace_is_observed':'''import heapq
entered=False
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  global entered
  print('less',self.value,other.value)
  if not entered:
   entered=True
   print('inner',heapq.heapreplace(items,Item(8)).value)
  return self.value<other.value
items=[Item(1),Item(2),Item(3)]
heapq.heappush(items,Item(0))
print([x.value for x in items])
''',
'asynchronous_source_recursion_in_comparison':'''import heapq
def depth(value):
 if value:return depth(value-1)
 return 0
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):return self.value+depth(3)<other.value
items=[Item(3),Item(1),Item(2)]
heapq.heapify(items)
print([heapq.heappop(items).value for _ in range(len(items))])
''',
'source_comparison_error_has_original_frames':'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):raise ValueError('comparison failed')
heapq.heapify([Item(1),Item(2)])
''',
'truth_callback_error_has_original_frames':'''import heapq
class Decision:
 def __bool__(self):raise ValueError('truth failed')
class Item:
 def __lt__(self,other):return Decision()
heapq.heapify([Item(),Item()])
''',
'bubble_keeps_comparison_operand_then_reloads_swapped_slots':'''import heapq
changed=False
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  global changed
  print('less',self.value,other.value)
  if not changed:
   changed=True
   items[-1]=Item(20)
   items[3]=Item(15)
  return self.value<other.value
items=[Item(1),Item(3),Item(4),Item(5),Item(6),Item(7),Item(8)]
heapq.heappush(items,Item(0))
print([item.value for item in items])
''',
'pushpop_returns_current_root_after_callback_replacement':'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):items[0]=Item(9);return True
items=[Item(1)]
print(heapq.heappushpop(items,Item(2)).value,[item.value for item in items])
''',
'truth_callback_size_change_is_checked_after_truth':SUPPRESS+'''import heapq
changed=False
class Decision:
 def __bool__(self):
  global changed
  if not changed:
   changed=True
   items.append(Item(8))
  return True
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):return Decision()
items=[Item(3),Item(2),Item(1)]
with Suppress():heapq.heapify(items)
print([item.value for item in items])
''',
'comparison_error_precedes_size_change_error':'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  items.append(Item(9))
  raise ValueError('original comparison failure')
items=[Item(3),Item(2),Item(1)]
heapq.heapify(items)
''',
'max_comparison_failure_keeps_partial_native_heap':SUPPRESS+'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):
  print(self.value,other.value)
  if self.value==4:raise ValueError('stop')
  return self.value<other.value
items=[Item(1),Item(2),Item(3),Item(4)]
with Suppress():heapq.heapify_max(items)
print([item.value for item in items])
''',
'empty_pop_retains_original_source_call_frames':'''import heapq
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):return self.value<other.value
def pop(items):return heapq.heappop(items)
print(pop([Item(1)]).value)
print(pop([]))
''',
}


LARGE='''import heapq
trace=[]
class Item:
 def __init__(self,value):self.value=value
 def __lt__(self,other):trace.append((self.value,other.value));return self.value<other.value
items=[Item((index*37)%3511)for index in range(SIZE)]
heapq.heapify(items)
print(len(trace),trace[:12],trace[-12:])
print(sum((index+1)*(left+3)*(right+5)for index,(left,right)in enumerate(trace))%1000000007)
print([item.value for item in items[:12]])
'''
CASES['heapify_accelerator_small_schedule']=LARGE.replace('SIZE','2500')
CASES['heapify_accelerator_cache_schedule']=LARGE.replace('SIZE','2501')
CASES['former_nested_source_boundary']='''import heapq
class Item:
 def __lt__(self,other):return True
heapq.heapify([(0,Item()),(0,Item())])
'''


class FallibleHeapExecutionTests(iterator_tests.IteratorExecutionTests):
 cases=CASES
 def test_rich_and_builtin_fallible_heap_contracts(self):
  for name in CASES:
   with self.subTest(name=name):self.check(name)


for _name in tuple(vars(iterator_tests.IteratorExecutionTests)):
 if _name.startswith('test_'):setattr(FallibleHeapExecutionTests,_name,None)


class FallibleHeapGuards(unittest.TestCase):
 def test_unsupported_live_nested_source_and_float_identity_are_explicit(self):
  sources=['''import heapq
class Item:
 def __lt__(self,other):return True
heapq.heapify([([Item()],),([Item()],)])
''',"import heapq\nheapq.heapify([(0,float('nan')),(0,float('nan'))])\n"]
  for source in sources:
   result=transpile(source,TranspileOptions(license='none'))
   self.assertFalse(result.success)
   self.assertTrue(any('comparison'in diagnostic.message or'identity'in diagnostic.message for diagnostic in result.diagnostics),result.diagnostics)

 def test_total_primitive_path_keeps_its_existing_helpers(self):
  for values in ['[3,1,2]','[(3,4),(1,2)]','[3.0,1.0,2.0]']:
   result=transpile('class Marker:pass\nimport heapq\na='+values+'\nheapq.heapify(a)\nprint(a)\n',TranspileOptions(license='none'))
   self.assertTrue(result.success,result.diagnostics)
   self.assertNotIn('native_fallible_heap',result.rust_source)
