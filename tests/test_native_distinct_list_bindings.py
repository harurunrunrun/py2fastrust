"""Control-flow binding joins must not unify independent list allocations."""
import ast
import unittest

from py2fastrust.native_classes import Model,Cell,shape
from py2fastrust.native_types import ListType,alternatives
import test_native_module_linking as support

class DistinctListBindingFacts(unittest.TestCase):
    def test_distinct_layout_selection_precedes_emission(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_frame_selection import select_frames
        result=select_frames(build_program(CASES['loop_headers_keep_matrix_aliases'],'binding.py').main)
        self.assertIn('distinct mutable list binding layouts',result.reasons)

    def test_uniform_primitive_lists_keep_ordinary_selection(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_list_binding_selection import requires_frames
        from py2fastrust.native_constraints import analyze
        source='def run(n):\n a=[1,2]\n b=[3,4]\n chosen=a\n for i in range(n):chosen=b\n print(chosen,a,b)\nrun(2)\n'
        unit=build_program(source,'binding.py').main
        self.assertFalse(requires_frames(unit,analyze(unit)))

    def test_different_resolved_layouts_preserve_both_producers(self):
        model=Model(ast.parse('pass'),'binding.py','i64',frozenset())
        matrix=Cell('list',(Cell('list',(Cell('int'),)),))
        vector=Cell('list',(Cell('int'),))
        before=(shape(matrix),shape(vector))
        joined=model.namespace.join_values(matrix,vector,ast.Pass(),'selected','loop_header')
        self.assertEqual((shape(matrix),shape(vector)),before)
        self.assertEqual(set(alternatives(shape(joined))),set(before))
        self.assertTrue(model.namespace.is_flow(joined))

    def test_pending_list_elements_are_not_invented(self):
        model=Model(ast.parse('pass'),'binding.py','i64',frozenset())
        pending=Cell('list',(Cell(),));known=Cell('list',(Cell('int'),))
        self.assertIsNone(model.namespace.join_values(pending,known,ast.Pass(),'selected'))
        self.assertIsNone(shape(pending).element)
        self.assertEqual(shape(known),ListType('int'))

CASES={
    'loop_headers_keep_matrix_aliases':'''def choose(count):
 matrix=[[3,5],[7,11]]
 vector=[13,17]
 selected=matrix
 for i in range(count):selected=vector
 print(selected,matrix,vector)
 print(next((i for i in range(len(matrix)) if matrix[i][0]>4),-1))
choose(0)
choose(2)
''',
    'branch_and_loop_binding_changes':'''class Box:
 def __init__(self):self.matrix=[[2,4],[6,8]];self.vector=[3,9]
 def run(self,count):
  selected=self.matrix
  for i in range(count):selected=self.vector
  print(selected,self.matrix,self.vector)
  self.matrix[0][1]+=1
  self.vector[0]+=2
  print(selected,self.matrix,self.vector)
box=Box()
box.run(0)
box.run(1)
''',
    'captured_rows_survive_unrelated_rebindings':'''def produce(rows):
 matrix=[row[:] for row in rows]
 pivots=[0]
 def read():return matrix[0][1]
 return matrix,pivots,read
matrix,indices,read=produce([[2,5],[7,11]])
selected=matrix
for turn in range(3):
 selected=indices
print(matrix,indices,selected,read())
matrix[0][1]=19
print(read(),indices)
''',
}

class DistinctListBindingExecution(unittest.TestCase):
    exercise=support.NativeLinkedModuleTests.exercise

for _name,_source in CASES.items():
    def _test(self,source=_source):self.exercise({'main.py':source})
    setattr(DistinctListBindingExecution,'test_'+_name,_test)
