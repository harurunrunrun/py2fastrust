"""Scalar integer list loans preserve values, aliases, and failure order."""
import shutil
import unittest

from py2fastrust import TranspileOptions,transpile
import test_native_lambda_callbacks as helpers


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class IntegerListPlaceTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_all_alias_directions_and_integer_immutability(self):
        source='''class Box:
 def __init__(self):self.a=[23,-15,37]
box=Box()
left=box.a
right=left
saved=left[0]
left[0]^=right[1]
left[2]|=right[0]
left[1]&=right[2]
left[-1]^=right[-1]
left[0]|=right[0]
left[1]&=right[1]
other=[-31,7,99]
left[0]^=other[-1]
print(left,right,other,saved)
'''
        self.exercise(source)
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('class_list_integer_bitop(',result.rust_source)

    def test_captured_lists_and_large_signed_operands(self):
        # Reading the old integer before an update must retain its old value.
        self.exercise('''class Box:
 def __init__(self):self.a=list(map(int,input().split()))
box=Box()
a=box.a
def pick():return a[0]
saved=pick()
a[0]^=a[1]
a[1]|=a[2]
a[2]&=a[0]
print(a,saved,pick())
''',('23 -15 37\n','0 0 -1\n'))
        # Larger values only have CPython semantics in arbitrary precision.
        from pathlib import Path
        import os,subprocess,sys
        source='''class Box:
 def __init__(self):self.a=list(map(lambda word:int(word,16),input().split()))
box=Box()
a=box.a
old=a[0]
a[0]^=a[1]
a[1]|=a[2]
a[2]&=a[0]
print([hex(value)for value in a],hex(old))
'''
        result=transpile(source,TranspileOptions(integer='bigint'))
        self.assertTrue(result.success,result.diagnostics)
        for optimized in (False,True):
            path=Path(self.directory.name)/f'big_place_{optimized}.rs';path.write_text(result.rust_source)
            binary=path.with_suffix('')
            built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(path),'-o',str(binary)],text=True,capture_output=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            for a,b,c in ((2**5000+3,2**4096-1,2**6200+5),(-2**5000-3,2**4096-1,-2**6200+5),(2**4096-1,2**4096-1,0)):
                data=f'{a:x} {b:x} {c:x}\n'
                expected=subprocess.run([sys.executable,'-I','-c',source],input=data,text=True,capture_output=True,timeout=10)
                actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python'})
                self.assertEqual(expected.returncode,0,expected.stderr)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout,expected.stdout)

    def test_get_error_before_rhs_index_and_same_object_checks(self):
        self.exercise('''class Box:
 def __init__(self):self.a=[3,7]
box=Box()
a=box.a
i,j=map(int,input().split())
a[i]^=a[1//j]
print(a)
''',('0 1\n','0 0\n','3 0\n','0 -1\n','0 2\n'))

    def test_callbacks_resize_before_store_and_are_never_loaned(self):
        self.exercise('''class Box:
 def __init__(self):self.a=[3,7,11]
box=Box()
a=box.a
def position():
 print("resize",a.pop())
 return 0
a[-1]^=a[position()]
print(a)
''')

    def test_target_owner_and_index_are_evaluated_once(self):
        self.exercise('''class Box:
 def __init__(self):self.a=[3,7,11]
box=Box()
right=box.a
def owner():
 print("owner")
 return right
def index():
 print("index")
 return -1
owner()[index()]^=right[0]
print(right)
''')


if __name__=='__main__':unittest.main()
