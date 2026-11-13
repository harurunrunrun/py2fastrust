"""Finite sequence alternatives keep pending elements and runtime iteration errors."""
import shutil,unittest
import test_native_annotations_assertions as support

FACTORY='''class Factory:
    def build(self,missing,size):
        if missing:return None
        result=[]
        for index in range(size):result.append(index+1)
        return result
'''
CASES={
'module_assert_checks_none_and_empty_before_iteration':(FACTORY+'''missing,size=map(int,input().split())
items=Factory().build(missing,size)
assert items,'empty batch'
total=0
for item in items:total+=item
print(total)
''',('0 4\n','0 0\n','1 4\n')),
'function_assert_keeps_success_and_failure_edges':(FACTORY+'''def consume(missing,size):
    items=Factory().build(missing,size)
    assert items,'empty batch'
    total=0
    for item in items:total+=item
    return total
missing,size=map(int,input().split())
print(consume(missing,size))
''',('0 3\n','0 0\n','1 3\n')),
'no_assert_preserves_actual_none_typeerror':(FACTORY+'''missing=int(input())
total=0
for item in Factory().build(missing,3):total+=item
print(total)
''',('0\n','1\n')),
'loop_returns_merge_none_and_pending_list':('''class Factory:
    def build(self,size):
        result=[]
        for index in range(size):
            if index==2:return None
            result.append(index+10)
        return result
items=Factory().build(int(input()))
assert items,'no result'
for item in items:print(item)
''',('0\n','1\n','2\n','3\n')),
'finite_tuple_range_and_none_producers':('''class Factory:
    def build(self,kind,size):
        if kind==0:return None
        if kind==1:return tuple(range(size))
        return range(size)
kind,size=map(int,input().split())
items=Factory().build(kind,size)
assert items,'empty result'
total=0
for item in items:total+=item
print(total)
''',('0 3\n','1 3\n','2 3\n','1 0\n','2 0\n')),
'list_iteration_keeps_live_mutation':(FACTORY+'''missing=int(input())
items=Factory().build(missing,3)
for item in items:
    if item<3:items.append(item+3)
    print(item)
print(items)
''',('0\n','1\n')),
'rebinding_keeps_the_captured_original_source':(FACTORY+'''missing=int(input())
items=Factory().build(missing,3)
for item in items:
    items=None
    print(item)
print(items is None)
''',('0\n','1\n')),
'assert_callback_rebinds_the_later_iterable':(FACTORY+'''items=Factory().build(int(input()),2)
def observe():
    global items
    items=None
    print('observed')
    return True
assert observe(),'failed'
for item in items:print(item)
''',('0\n','1\n')),
'assert_callback_installs_a_new_live_list':(FACTORY+'''items=Factory().build(int(input()),2)
def observe():
    global items
    items=[8,9]
    print('observed')
    return True
assert observe(),'failed'
for item in items:print(item)
''',('0\n','1\n')),
'failure_message_effects_are_conditional':(FACTORY+'''items=Factory().build(int(input()),2)
def message():
    global items
    items=[8,9]
    print('message')
    return 'missing result'
assert items,message()
for item in items:print(item)
''',('0\n','1\n')),
'generator_body_observes_assert_before_the_loop':(FACTORY+'''def stream(missing,size):
    items=Factory().build(missing,size)
    assert items,'empty stream'
    for item in items:yield item*2
missing,size=map(int,input().split())
print(list(stream(missing,size)))
''',('0 3\n','0 0\n','1 3\n')),
}

BOUNDARIES={
'list_iteration_keeps_live_mutation':(10,'items.append','None | list[int]'),
}

CASES.update({
'live_mutation_through_a_known_owner_alias':('''class Factory:
    def __init__(self):self.buffer=[1,2,3]
    def build(self,missing):return None if missing else self.buffer
factory=Factory()
for item in factory.build(int(input())):
    if item<3:factory.buffer.append(item+3)
    print(item)
print(factory.buffer)
''',('0\n','1\n')),
'pure_none_iteration_raises_before_body_or_else':('''class Worker:
    def run(self):
        for item in None:print('body',item)
        else:print('else')
        print('after')
Worker().run()
''',('',)),
'pure_scalar_iteration_keeps_its_actual_type_error':('''class Worker:
    def run(self,value):
        for item in value:print(item)
flag=int(input())
Worker().run(None if flag else 1.5)
''',('0\n','1\n')),
'enumerate_captures_source_before_start_effects':(FACTORY+'''items=Factory().build(int(input()),2)
def begin():
    global items
    items=None
    print('start')
    return 4
for position,item in enumerate(items,begin()):print(position,item)
print(items is None)
''',('0\n','1\n')),
'generator_none_elements_are_real_values':('''class Factory:
    def build(self,missing,size):return None if missing else [None]*size
def stream(missing,size):
    items=Factory().build(missing,size)
    assert items,'empty values'
    for item in items:yield item
missing,size=map(int,input().split())
print(list(stream(missing,size)))
''',('0 2\n','0 0\n','1 2\n')),
'generator_reused_local_retains_real_none_and_integer_values':('''class Factory:
    def build(self,missing):return None if missing else [None,None]
def stream(missing):
    items=Factory().build(missing)
    assert items,'empty values'
    for item in items:yield item
    for item in range(2):yield item
print(list(stream(int(input()))))
''',('0\n','1\n')),
'generator_reused_loop_local_keeps_all_stored_types':(FACTORY+'''def stream(missing):
    items=Factory().build(missing,2)
    assert items,'empty values'
    for item in items:yield item
    for item in ('a','b'):yield item
print(list(stream(int(input()))))
''',('0\n','1\n')),
'generator_zero_trip_target_stays_unbound':(FACTORY+'''def stream(size):
    items=Factory().build(False,size)
    for item in items:pass
    yield item
print(list(stream(int(input()))))
''',('0\n','2\n')),
'generator_actual_callable_retention_stays_guarded':(FACTORY+'''def callback():return 7
def stream():
    items=Factory().build(False,2)
    for item in items:yield item
    item=callback
    yield item()
print(list(stream()))
''',('',)),
})
BOUNDARIES['generator_actual_callable_retention_stays_guarded']=(8,'source generator','owned source generator frame payload')

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FiniteSequenceUnionTests(unittest.TestCase):
    compare=support.AnnotationAndAssertionExecutionTests.compare


def _case(name):
    def test(self):self.compare(*CASES[name])
    return test

for _name in CASES:
    if _name not in BOUNDARIES:setattr(FiniteSequenceUnionTests,'test_'+_name,_case(_name))


class FiniteSequenceBoundaryTests(unittest.TestCase):
    def test_remaining_protocol_boundaries_are_positioned(self):
        from py2fastrust import transpile,TranspileOptions
        for name,(line,operation,protocol)in BOUNDARIES.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(CASES[name][0],TranspileOptions(integer=integer,filename='sequence_boundary.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(item.code=='E006'and item.line==line
                        and operation in item.message and protocol in item.message
                        for item in result.diagnostics),result.diagnostics)

