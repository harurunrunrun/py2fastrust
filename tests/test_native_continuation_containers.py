"""Compiled recursive calls retain typed container identity and local storage."""
import shutil,unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions,transpile
from py2fastrust import native_typed_continuations as continuations
import test_native_lambda_callbacks as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ContinuationContainerTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def selected(self,source):
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('enum ClassNativeState',result.rust_source)
            self.assertNotIn('Box::pin',result.rust_source)
            self.assertNotIn('dyn Future',result.rust_source)
            self.assertNotIn('enum Value',result.rust_source)

    def test_deep_list_argument_recursion_uses_typed_calls(self):
        source='''import sys
sys.setrecursionlimit(20000)
def total(values,depth):
 if depth==0:return values[0]
 return values[0]+total(values,depth-1)
values=[3]
print(total(values,int(input())),values)
'''
        self.exercise(source,('0\n','5\n','12000\n'))
        self.selected(source)

    def test_native_stack_segments_are_reused_after_deep_returns(self):
        source='''import sys
sys.setrecursionlimit(20000)
def total(values,depth):
 if depth==0:return values[0]
 return total(values,depth-1)+1
depth=int(input())
print(total([3],depth),total([7],0),total([5],depth))
'''
        self.exercise(source,('0\n','80\n','12000\n'))
        self.selected(source)
        result=transpile(source,TranspileOptions(license='none'))
        self.assertIn('_direct(',result.rust_source)
        self.assertIn('class_native_enter()',result.rust_source)

    def test_mutating_list_argument_preserves_external_aliases(self):
        source='''def walk(values,depth):
 if depth==0:
  values.append(7)
  return values[0]
 before=values[0]
 result=walk(values,depth-1)
 values[0]+=1
 return before+result
values=[2]
alias=values
print(walk(values,int(input())),values,alias is values)
'''
        self.exercise(source,('0\n','3\n'))
        self.selected(source)

    def test_list_results_are_shared_after_return(self):
        source='''def build(depth):
 if depth==0:return []
 values=build(depth-1)
 values.append(depth)
 return values
values=build(int(input()))
alias=values
values.append(9)
print(values,alias is values)
'''
        self.exercise(source,('0\n','5\n'))
        self.selected(source)

    def test_private_vector_local_survives_a_child_call(self):
        source='''def build(depth):
 values=[depth]
 if depth:
  child=build(depth-1)
  values[0]=values[0]+child[0]
 return values
print(build(int(input())))
'''
        self.exercise(source,('0\n','5\n'))
        self.selected(source)
        result=transpile(source,TranspileOptions(license='none'))
        self.assertIn('Option<Vec<NativeInt>>',result.rust_source)

    def test_tuple_arguments_and_results_keep_list_identity(self):
        source='''def visit(context,depth):
 values,offset=context
 values.append(depth+offset)
 if depth:return visit(context,depth-1)
 return context
values=[1]
result=visit((values,4),int(input()))
print(result[0],result[1],result[0]is values)
'''
        self.exercise(source,('0\n','3\n'))
        self.selected(source)

    def test_tuple_unpack_after_a_recursive_return(self):
        source='''def visit(pair,depth):
 if depth==0:return pair
 first,second=visit(pair,depth-1)
 return first+second,second+1
print(visit((2,3),int(input())))
'''
        self.exercise(source,('0\n','4\n'))
        self.selected(source)

    def test_recursive_index_errors_keep_source_frames(self):
        source='''def read(values,depth,index):
 if depth==0:return values[index]
 return read(values,depth-1,index)+1
print(read([4],int(input()),int(input())))
'''
        self.exercise(source,('0\n0\n','2\n0\n','2\n1\n','80\n1\n'))
        self.selected(source)

    def test_source_branches_keep_the_active_frame_in_place(self):
        source='''def visit(values,depth):
 result=0
 for index in range(5):
  if index==1:continue
  if index==4:break
  if index%2:result+=values[0]
  else:result-=values[0]
 if depth:return result+visit(values,depth-1)
 return result
print(visit([3],int(input())))
'''
        self.exercise(source,('0\n','4\n'))
        self.selected(source)
        result=transpile(source,TranspileOptions(license='none'))
        self.assertIn('let mut pc=pc;loop{',result.rust_source)

    def test_constructor_list_arguments_allow_recursive_methods(self):
        from test_native_typed_continuations import SOURCES
        source,inputs=SOURCES['used_class_recursive_prefix']
        self.exercise(source,tuple(inputs)+('','4 7 9\n'))
        self.selected(source)

    def test_unproved_nested_list_transport_preserves_prior_product(self):
        source='''def visit(rows,depth):
 if depth==0:return rows[0][0]
 return visit(rows,depth-1)+rows[0][0]
print(visit([[3]],2))
'''
        current=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(current.success,current.diagnostics)
        with patch.object(continuations,'prepare',lambda model:setattr(model,'typed_continuations',None)):
            prior=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(prior.success,prior.diagnostics)
        self.assertEqual(current.rust_source,prior.rust_source)
        self.exercise(source)


if __name__=='__main__':unittest.main()
