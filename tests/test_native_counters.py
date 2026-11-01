"""Counter class identity and typed counting over canonical collections imports."""
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_module_capabilities import needs_linked_members
from tests import test_native_module_linking as linked_helpers


class CounterCapabilityTests(unittest.TestCase):
    def test_existing_deque_only_imports_keep_their_ordinary_adapter(self):
        for source in ['from collections import deque\nq=deque([1,2])\n',
                       'import collections as library\nq=library.deque([1,2])\n']:
            program=build_program(source,'main.py')
            self.assertFalse(needs_linked_members(program))
            result=transpile(source)
            self.assertTrue(result.success,result.diagnostics)

    def test_counter_exports_are_selected_from_canonical_import_metadata(self):
        source='import collections as library\nConstructor=library.Counter\nc=Constructor([1,2,1])\n'
        program=build_program(source,'main.py')
        self.assertTrue(needs_linked_members(program))
        with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback entered')):
            result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)

    def test_elements_has_a_specific_remaining_protocol_diagnostic(self):
        result=transpile('from collections import Counter\nc=Counter([1,2])\nprint(list(c.elements()))\n')
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertEqual(result.diagnostics[0].line,3)
        self.assertIn('Counter.elements',result.diagnostics[0].message)
        self.assertIn('lazy repeated-key cursor',result.diagnostics[0].message)

    def test_nonintegral_counts_keep_a_positioned_protocol_diagnostic(self):
        result=transpile('from collections import Counter\nc=Counter(a=0.5)\n')
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertEqual(result.diagnostics[0].line,2)
        self.assertIn('non-integral count',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class CounterExecutionTests(unittest.TestCase):
    exercise=linked_helpers.NativeLinkedModuleTests.exercise

    def test_iterable_counts(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter([3,1,3,2,1,3])
print(c[3],c[9],len(c),9 in c,c)
"""})

    def test_empty_then_increment(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter()
for word in ['a','b','a']:c[word]+=1
print(c,c['missing'],len(c))
"""})

    def test_numeric_key_retention(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter([True,1,False,0,1])
print(c,c[True],c[0],len(c))
"""})

    def test_constructor_mapping_keywords(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter({'a':2,'b':-1},a=3,z=0)
print(c,c['a'],c['b'],c['z'])
"""})

    def test_counter_class_field(self):
        self.exercise({'main.py':"""from collections import Counter
class Frequencies:
 def __init__(self):self.counts=Counter()
 def add(self,key):self.counts[key]+=1
f=Frequencies()
f.add('x')
f.add('x')
print(f.counts,f.counts['y'])
"""})

    def test_copy_counter_preserves_missing(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter('abb')
d=c.copy()
d['z']+=3
print(c,d,d['missing'],c is d)
"""})

    def test_captured_constructor_alias(self):
        self.exercise({'main.py':"""import collections as library
make=library.Counter
c=make('banana')
print(c,sorted(c.items()),c.get('z'),c.get('z',9),len(c))
"""})

    def test_update_iterable_and_mapping(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter([1,2,1])
c.update([2,3,3])
c.update({1:4,3:-2})
print(c,c.total())
"""})

    def test_most_common_ties_limits(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter(['b','a','c','a','b','d'])
print(c.most_common(),c.most_common(2),c.most_common(0),c.most_common(-1),c.most_common(99))
"""})

    def test_subtract_counts(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter('aab')
c.subtract('bcc')
c.subtract({'a':3})
print(c,c.total(),c.most_common())
"""})

    def test_none_sources(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter(None,x=3)
c.update(None)
c.subtract(None)
print(c,c.total())
"""})

    def test_mixed_optional_sources(self):
        self.exercise({'main.py':"""from collections import Counter
def source(mode):
 if mode==0:return None
 if mode==1:return {1:3,2:-2}
 return [1,2,1]
for mode in [0,1,2]:
 c=Counter(source(mode))
 c.update(source(2))
 c.subtract(source(1))
 print(c)
"""})

    def test_bool_counts(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter(a=True,b=False)
print(c,c.most_common(),c.total())
c.update(a=False,b=True,z=True)
print(c,c.most_common(2),c.total())
e=Counter()
e.update({'a':True,'b':False})
print(e,e.total())
"""})

    def test_self_update_subtract(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter('abbccc')
alias=c
c.update(alias)
print(c)
c.subtract(alias)
print(c,c.total())
"""})

    def test_all_topk_stable_order(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter({i:(i*17%13)-6 for i in range(60)})
for limit in range(-2,65):print(c.most_common(limit))
"""})

    def test_counter_isinstance(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter([1,2,1])
print(isinstance(c,Counter),isinstance(c,dict),isinstance({},Counter),isinstance([],Counter))
"""})

    def test_union_values_classinfo(self):
        self.exercise({'main.py':"""from collections import Counter
def value(flag):
 if flag:return Counter([1,2,1])
 return {1:2}
for flag in [False,True]:
 item=value(flag)
 print(isinstance(item,Counter),isinstance(item,dict))
"""})

    def test_classinfo_evaluates_once(self):
        self.exercise({'main.py':"""from collections import Counter
def value():
 print('value')
 return Counter([1])
def kind():
 print('kind')
 return Counter
print(isinstance(value(),kind()))
"""})

    def test_counter_as_unhashable_key(self):
        self.exercise({'main.py':"""from collections import Counter
d={1:2}
c=Counter([1])
print(d[c])
"""})

    def test_empty_counter_and_most_common(self):
        self.exercise({'main.py':"""from collections import Counter
c=Counter()
print(c,c.most_common(),c.most_common(0),c.most_common(3),c.total(),c['x'])
"""})

    def test_user_collections_module_is_not_replaced_by_the_native_counter(self):
        self.exercise({'main.py':'import collections\nprint(collections.Counter([2,3,4]))\n',
                       'collections.py':'def Counter(values):return len(values)+10\n'})

    def test_counter_none_union(self):
        self.exercise({'main.py':"""from collections import Counter
def choose(flag):
 if flag:return Counter([1,2,1])
 return None
for flag in [False,True]:
 value=choose(flag)
 print(value,(value,))
"""})

    def test_counter_dict_union(self):
        self.exercise({'main.py':"""from collections import Counter
def choose(flag):
 if flag:return Counter([1,2,1])
 return {1:2}
for flag in [False,True]:
 value=choose(flag)
 print(value,(value,))
"""})

    def test_counter_nested_union_rows(self):
        self.exercise({'main.py':"""from collections import Counter
rows=[Counter('aab'),None,Counter()]
print(rows,tuple(rows))
"""})
