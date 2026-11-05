"""Private recursive vectors preserve original matrix places and effects."""
import ast
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_owned_matrix_places as places
from py2fastrust.frontend import parse_source
from py2fastrust.native_frame_selection import select_frames
from tests import test_native_classes as _classes


GRID='''def solve(n,m):
 dp=[[0]*(m+1)for _ in range(n+1)]
 for i in range(1,n+1):
  for j in range(1,m+1):dp[i][j]=dp[i-1][j]+dp[i][j-1]+1
 print(dp[n][m],len(dp),len(dp[0]))
solve(3,4)
'''
USED='''class Score:
 def __init__(self):self.value=0
 def add(self,value):self.value+=value
 def mark(self,label,value):
  print(label)
  return value
 def read(self):return self.value
'''
RAGGED=USED+'''def solve():
 score=Score()
 dp=[[],[1],[2,3]]
 for i in range(len(dp)):
  for j in range(len(dp[i])):
   dp[i][j]+=i+j
   score.add(dp[i][j])
 print(len(dp[0]),dp[-1][-1],score.read())
solve()
'''
THREE='''def solve():
 grid=[[[i+j+k for k in range(3)]for j in range(2)]for i in range(2)]
 grid[-1][0][-1]+=grid[0][1][1]
 print(grid[1][0][2],len(grid),len(grid[0]),len(grid[0][0]))
solve()
'''
TEXT=USED+'''def solve():
 score=Score()
 grid=[['x'for _ in range(2)]for _ in range(2)]
 grid[0][1]+='ab'
 score.add(len(grid[0][1]))
 print(grid[0][1],score.read())
solve()
'''
NEGATIVES=(
'''def solve():
 row=[0]
 grid=[row]*3
 grid[0][0]=7
 print(grid[1][0],grid[0] is grid[1])
solve()
''',
'''def solve():
 grid=[[0],[1]]
 saved=grid[0]
 grid[0]=[2]
 saved[0]=7
 print(grid[0][0],saved[0])
solve()
''',
'''def solve():
 grid=[[0],[1]]
 grid[0].append(3)
 print(grid[0][1],len(grid[0]))
solve()
''',
'''def solve():
 grid=[[0],[1]]
 def change():
  grid[0].append(3)
  return 0
 grid[0][change()]=2
 print(grid[0][0],len(grid[0]))
solve()
''',
'''def solve():
 grid=[[0],[1]]
 print(grid[0] is grid[1],grid[0][0])
solve()
''')
POLYMORPHIC='''def solve(value):
 grid=[[value for _ in range(2)]for _ in range(2)]
 print(grid[0][0])
solve(3)
solve('text')
'''


class OwnedMatrixProofTests(unittest.TestCase):
    def inspect(self,source,mode='i64'):
        original=places.prepare;found=[]
        def observe(emitter,candidates):
            before=ast.dump(emitter.model.unit.tree,include_attributes=True)
            result=original(emitter,candidates)
            self.assertEqual(ast.dump(emitter.model.unit.tree,include_attributes=True),before)
            found.extend(result.values())
            return result
        with patch.object(places,'prepare',observe):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'native')
        return result,found

    def test_classless_grid_has_recursive_vectors_in_every_integer_mode(self):
        for mode in('i64','i128','bigint'):
            with self.subTest(mode=mode):
                result,found=self.inspect(GRID,mode)
                self.assertTrue(found)
                self.assertIn('Option<Vec<Vec<NativeInt>>>',result.rust_source)
                self.assertIn('private recursive vector matrix places',select_frames(parse_source(GRID),integer=mode).reasons)

    def test_ragged_empty_rows_are_fresh_vectors(self):
        result,found=self.inspect(RAGGED)
        self.assertTrue(found)
        self.assertIn('Option<Vec<Vec<NativeInt>>>',result.rust_source)
        self.assertIn('<Vec<NativeInt>>::new()',result.rust_source)

    def test_three_dimensions_use_the_same_recursive_layout(self):
        result,found=self.inspect(THREE)
        self.assertTrue(found)
        self.assertIn('Option<Vec<Vec<Vec<NativeInt>>>>',result.rust_source)

    def test_scalar_text_length_is_not_a_row_length(self):
        result,found=self.inspect(TEXT)
        self.assertTrue(found)
        self.assertIn('Option<Vec<Vec<NativeText>>>',result.rust_source)

    def test_alias_resize_capture_row_replacement_and_identity_keep_existing_abi(self):
        from py2fastrust.native_classes import try_generate_classes
        for source in NEGATIVES:
            with self.subTest(source=source):
                # Probe the frame-layer ownership proof directly on the exact
                # official source; no extra class changes frontend selection.
                unit=parse_source(source,'matrix-negative.py')
                before=ast.dump(unit.tree,include_attributes=True)
                nodes=tuple(ast.walk(unit.tree))
                self.assertFalse(any(isinstance(node,ast.ClassDef)for node in nodes))
                original=places.prepare;found=[];diagnostics=[]
                def observe(emitter,candidates):
                    self.assertIs(emitter.model.unit,unit)
                    selected=original(emitter,candidates)
                    found.extend(selected.values())
                    return selected
                with patch.object(places,'prepare',observe):
                    rust=try_generate_classes(source,unit.filename,'i64',unit=unit,
                                              diagnostic_out=diagnostics)
                self.assertIsNotNone(rust,diagnostics)
                self.assertFalse(found)
                with patch.object(places,'prepare',return_value={}):
                    baseline=try_generate_classes(source,unit.filename,'i64',unit=unit)
                self.assertEqual(rust,baseline)
                self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
                self.assertEqual(tuple(ast.walk(unit.tree)),nodes)
                # Public selection is checked independently on that same
                # unmodified negative program, rather than forced by source.
                result=transpile(source,TranspileOptions(license='none'))
                self.assertTrue(result.success,result.diagnostics)
                with patch.object(places,'requires_frames',return_value=False):
                    public_baseline=transpile(source,TranspileOptions(license='none'))
                self.assertEqual(result.rust_source,public_baseline.rust_source)

    def test_flat_and_polymorphic_programs_keep_ordinary_selection(self):
        flat='def solve():\n a=[0]*3\n a[0]=7\n print(a[0])\nsolve()\n'
        for source in(flat,POLYMORPHIC):
            result=transpile(source,TranspileOptions(license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('private recursive vector matrix places',select_frames(parse_source(source)).reasons)
            with patch.object(places,'requires_frames',return_value=False):
                baseline=transpile(source,TranspileOptions(license='none'))
            self.assertEqual(result.rust_source,baseline.rust_source)

    def test_length_aliases_do_not_select_an_unproved_physical_place(self):
        sources=(
            'def solve(len=len):\n grid=[[1,2],[3,4]]\n print(len(grid),grid[0][0])\nsolve()\n',
            'def solve():\n length=len\n grid=[[1,2],[3,4]]\n print(length(grid),grid[0][0])\nsolve()\n',
            'import builtins\ndef solve():\n len=builtins.len\n grid=[[1,2],[3,4]]\n print(len(grid),grid[0][0])\nsolve()\n',
            'import builtins\nlen=builtins.len\ndef solve():\n grid=[[1,2],[3,4]]\n print(len(grid),grid[0][0])\nsolve()\n')
        for source in sources:
            with self.subTest(source=source):
                result=transpile(source,TranspileOptions(license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertNotIn('private recursive vector matrix places',select_frames(parse_source(source)).reasons)
                with patch.object(places,'requires_frames',return_value=False):
                    baseline=transpile(source,TranspileOptions(license='none'))
                self.assertEqual(result.rust_source,baseline.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class OwnedMatrixExecutionTests(unittest.TestCase):
    compile=_classes.NativeClassTests.compile
    compare=_classes.NativeClassTests.compare

    def test_grid(self):self.compare(GRID)
    def test_ragged_empty_rows(self):self.compare(RAGGED)
    def test_three_dimensions(self):self.compare(THREE)
    def test_scalar_text_length(self):self.compare(TEXT)
    def test_polymorphic_ordinary_program(self):self.compare(POLYMORPHIC)

    def test_records_vectors_and_matrices_compose(self):
        self.compare('''class Summary:
 def __init__(self,label):self.state=[0,label]
 def calculate(self,n,m):
  values=[i+1 for i in range(n)]
  pair=[1,'items']
  grid=[[0]*m for _ in range(n)]
  for i,value in enumerate(values):
   for j in range(m):grid[i][j]=value+j+pair[0]
   if m:self.state[0]+=grid[i][-1]
   pair[0]+=1
  self.state[1]=self.state[1].upper()
  print(self.state[0],self.state[1],pair[0],pair[1],len(grid),len(grid[0])if n else 0)
n,m=map(int,input().split())
Summary('totals').calculate(n,m)
''',data='3 4\n')

    def test_inline_comprehension_callable_named_len_keeps_mutation_and_lookup(self):
        self.compare(USED+'''def custom(value):
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
''')

    def test_reversed_leaf_repetition_evaluates_count_first(self):
        self.compare(USED+'''def solve():
 score=Score()
 grid=[score.mark('count',2)*[score.mark('leaf',3)]for _ in range(2)]
 grid[0][1]+=1
 score.add(grid[0][1])
 print(grid[1][0],score.read())
solve()
''')

    def test_store_rhs_and_prefix_errors_keep_python_order(self):
        for assignment in("grid[score.mark('row',i)][score.mark('column',j)]=score.mark('rhs',7)",
                           "grid[score.mark('row',i)][score.mark('column',j)]+=score.mark('rhs',7)"):
            for i,j in((2,0),(0,2),(-1,-1)):
                self.compare(USED+'''def solve(i,j):
 score=Score()
 grid=[[0]*2 for _ in range(2)]
 '''+assignment+'''
 score.add(grid[0][0])
 print(score.read())
solve('''+str(i)+','+str(j)+')\n')
