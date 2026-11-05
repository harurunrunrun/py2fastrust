"""Physical length shortcuts require the original official callable binding."""
import ast
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_physical_list_builtins as builtins
from tests import test_native_classes as _classes


MATRIX='''class Score:
 def __init__(self):self.value=0
 def add(self,value):self.value+=value
 def read(self):return self.value
def custom(value):
 print('custom')
 value[0][0]=9
 return 1
def solve():
 score=Score()
 grid=[[1],[2]]
 result=[len(grid)for len in [custom]]
 score.add(grid[0][0])
 print(result[0],score.read())
solve()
'''
RECORD='''def custom(record):
 print('custom',record[0])
 record[0]+=2
 return 99
def solve():
 record=[7,'shelf']
 result=[len(record)for len in [custom]]
 print(result,record[0],record[1].upper())
solve()
'''
FIELD='''def custom(record):
 print('custom',record[0])
 record[0]+=2
 return 99
class Ledger:
 def __init__(self):self.record=[7,'shelf']
 def run(self):
  result=[len(self.record)for len in [custom]]
  print(result,self.record[0],self.record[1].upper())
Ledger().run()
'''
ACTUAL_BUILTIN='''def solve():
 record=[7,'a b']
 sizes=[len(record)for len in [len]]
 print(sizes,record[1].split())
solve()
'''
PLAIN='''def solve():
 record=[7,'shelf']
 print(len(record),record[0],record[1].upper())
solve()
'''


class PhysicalListBuiltinProofTests(unittest.TestCase):
    def observe(self,source):
        original_static=builtins.static_builtin
        original_effect=builtins.readonly_length
        statics=[];effects=[]
        def static(model,plan,node,name):
            before=ast.dump(model.unit.tree,include_attributes=True)
            result=original_static(model,plan,node,name)
            self.assertEqual(ast.dump(model.unit.tree,include_attributes=True),before)
            if isinstance(node,ast.Name)and node.id=='len':statics.append(result)
            return result
        def effect(model,plan,node):
            result=original_effect(model,plan,node)
            if isinstance(node,ast.Name)and node.id=='len':effects.append(result)
            return result
        with patch.object(builtins,'static_builtin',static),patch.object(builtins,'readonly_length',effect):
            result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'native')
        return statics,effects

    def test_comprehension_source_callable_is_not_a_builtin_length_shortcut(self):
        for source in(MATRIX,RECORD,FIELD):
            with self.subTest(source=source):
                statics,effects=self.observe(source)
                self.assertIn(False,statics)
                self.assertTrue(effects)
                self.assertFalse(any(effects))

    def test_actual_builtin_payload_keeps_readonly_effect_without_lookup_elision(self):
        statics,effects=self.observe(ACTUAL_BUILTIN)
        self.assertIn(False,statics)
        self.assertIn(True,effects)

    def test_unshadowed_builtin_length_keeps_the_original_shortcut(self):
        statics,effects=self.observe(PLAIN)
        self.assertIn(True,statics)
        self.assertIn(True,effects)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class PhysicalListBuiltinExecutionTests(unittest.TestCase):
    compile=_classes.NativeClassTests.compile
    compare=_classes.NativeClassTests.compare

    def test_source_callable_mutates_nested_local_list(self):self.compare(MATRIX)
    def test_source_callable_mutates_fixed_local_record(self):self.compare(RECORD)
    def test_source_callable_mutates_class_field(self):self.compare(FIELD)
    def test_actual_builtin_alias_preserves_later_typed_split(self):self.compare(ACTUAL_BUILTIN)
    def test_canonical_builtin_length(self):self.compare(PLAIN)
