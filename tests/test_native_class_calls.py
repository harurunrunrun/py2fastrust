"""Direct calls and compiled-future calls preserve one Python call contract."""
import shutil
import unittest

from py2fastrust import transpile,TranspileOptions
import test_native_lambda_callbacks as helpers
import test_native_classes as class_helpers


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeClassCallTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise
    compile=class_helpers.NativeClassTests.compile
    compare=class_helpers.NativeClassTests.compare

    def test_acyclic_methods_and_constructors_have_direct_calls(self):
        source='''class Counter:
 def __init__(self,value):self.values=[value]
 def read(self):return self.values
 def add(self,amount):self.values[0]+=amount
def update(counter,amount):
 counter.add(amount)
 return counter.read()
c=Counter(int(input()))
alias=c.read()
print(update(c,3),alias,c.read() is alias)
'''
        self.exercise(source,("2\n","-5\n"))
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn("Box::pin",result.rust_source)
            self.assertNotIn("dyn Future",result.rust_source)
            self.assertIn("class_sync_call",result.rust_source)

    def test_direct_nested_call_exception_frames_and_argument_order(self):
        self.exercise('''def mark(value):
 print(value)
 return value
class Divider:
 def __init__(self,offset):self.offset=offset
 def divide(self,x,y):return (x+self.offset)//y
 def outer(self,x,y):return self.divide(mark(x),mark(y))
value=int(input())
print("start")
print(Divider(mark(2)).outer(mark(8),mark(value)))
''',("2\n","0\n"))

    def test_recursive_and_direct_callees_share_error_frames(self):
        self.exercise('''class Chain:
 def leaf(self,value):return 30//value
 def walk(self,count):
  if count:return self.leaf(count)+self.walk(count-1)
  return self.leaf(count)
print("start")
print(Chain().walk(int(input())))
''',("0\n","3\n"))

    def test_constructor_recursion_remains_on_the_compiled_stack(self):
        self.exercise('''class Node:
 def __init__(self,count):
  self.total=count
  if count:
   child=Node(count-1)
   self.total+=child.total
print(Node(int(input())).total)
''',("0\n","12\n"))

    def test_statically_long_call_chains_keep_a_bounded_native_suffix(self):
        functions=[]
        for index in range(40):
            body="10//value"if index==39 else f"f{index+1}(value)+1"
            functions.append(f"def f{index}(value):return {body}\n")
        source="class Scope:pass\n"+"".join(functions)+"print(f0(int(input())))\n"
        self.exercise(source,("2\n","0\n"))
        result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn("Box::pin",result.rust_source)
        self.assertIn("class_sync_call",result.rust_source)

    def test_low_recursion_limit_still_prevents_direct_callee_effects(self):
        methods=[]
        for index in range(20):
            body='print("must not run");return 1'if index==19 else f'return self.step{index+1}()'
            methods.append(f' def step{index}(self):{body}\n')
        source=('import sys\nclass Chain:\n'+''.join(methods)+
                'sys.setrecursionlimit(10)\nprint("ready")\nprint(Chain().step0())\n')
        result=self.compare(source)
        self.assertEqual(result.stdout,"ready\n")
        self.assertNotEqual(result.returncode,0)
        self.compare('''import sys
class Chain:
 def lower(self):
  sys.setrecursionlimit(1)
  print("must not run")
print("ready")
Chain().lower()
''')


if __name__=="__main__":unittest.main()
