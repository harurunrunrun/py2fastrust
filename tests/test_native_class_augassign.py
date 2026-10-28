"""Indexed scalar updates retain Python target evaluation and mutation order."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from py2fastrust import TranspileOptions,transpile
import test_native_lambda_callbacks as helpers


CASES={
    "scalar_rhs_division_error":('''class Box:
 def __init__(self):self.values=[10]
 def update(self,value):self.values[0]+=12//value
box=Box()
print("before",box.values)
box.update(int(input()))
print("after",box.values)
''',("0\n","2\n")),
    "scalar_arithmetic_condition_and_field":('''class Counter:
 def __init__(self):
  self.values=[3,7,11]
  self.offset=4
 def update(self,index,delta):
  self.values[index]+=delta*(self.offset if delta>0 else -self.offset)
  self.values[index]^=(delta>0 and 3)or 5
box=Counter()
box.update(int(input()),int(input()))
print(box.values)
''',("0\n2\n","-1\n-3\n","-3\n0\n","3\n1\n")),
    "owner_index_once_before_get":('''class Box:
 def __init__(self):self.values=[8,12]
def owner(box):
 print("owner")
 return box.values
def position(value):
 print("index",value)
 return value
box=Box()
owner(box)[position(int(input()))]+=box.missing
print(box.values)
''',("0\n","2\n","-3\n")),
    "effectful_rhs_negative_index":('''class Box:
 def __init__(self):self.values=[10,20,30]
box=Box()
box.values[-1]+=box.values.pop()
print(box.values)
''',("",)),
    "getitem_error_precedes_rhs_call":('''class Box:
 def __init__(self):self.values=[8]
def right():
 print("rhs must follow get")
 return 5
box=Box()
box.values[int(input())]+=right()
print(box.values)
''',("0\n","1\n")),
    "container_read_rhs":('''class Box:
 def __init__(self):self.values=[3,7,9]
box=Box()
box.values[-1]+=box.values[0]
box.values[1]*=len(box.values)
print(box.values)
''',("",)),
    "captured_row_survives_parent_mutation":('''class Box:
 def __init__(self):self.rows=[[1,2],[5,8]]
def change(box):
 removed=box.rows.pop(0)
 print("removed",removed)
 return removed[1]
box=Box()
row=box.rows[0]
box.rows[0][0]+=change(box)
print(box.rows,row)
''',("",)),
    "shortcircuit_and_conditional_errors":('''class Box:
 def __init__(self):self.values=[10]
 def update(self,value):
  self.values[0]+=(value and 12//value)or(3 if value==0 else 20//(value+2))
box=Box()
box.update(int(input()))
print(box.values)
''',("0\n","2\n","-2\n")),
    "primitive_unbound_rhs_order":('''class Box:
 def __init__(self):self.values=[10]
if int(input()):delta=4
box=Box()
box.values[int(input())]+=delta
print(box.values)
''',("1\n0\n","0\n0\n","0\n2\n")),
    "field_getter_failure_before_commit":('''class Box:
 def __init__(self):self.values=[10]
 def update(self,value):
  self.values[0]//=value+self.missing
box=Box()
print("before",box.values)
box.update(int(input()))
''',("0\n","2\n")),
    "mutable_element_keeps_augmented_alias":('''class Box:
 def __init__(self):self.rows=[[2],[5]]
box=Box()
row=box.rows[0]
box.rows[0]+=[7,9]
box.rows[0]*=2
print(box.rows,row,box.rows[0]is row)
''',("",)),
}


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeClassAugAssignTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise=helpers.NativeLambdaCallbackTests.exercise

    def test_scalar_arithmetic_condition_and_field(self):
        self.exercise(*CASES["scalar_arithmetic_condition_and_field"])

    def test_scalar_rhs_division_error(self):
        self.exercise(*CASES["scalar_rhs_division_error"])

    def test_scalar_rhs_error_preserves_element_and_releases_borrow(self):
        # Inspect the generated method's Result directly: an uncaught Python
        # exception cannot otherwise expose its surviving caller-owned list.
        from py2fastrust.rust_pruning import _lex,_parse
        source=CASES["scalar_rhs_division_error"][0]
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            tokens,comments,pairs=_lex(result.rust_source)
            main=next(item for item in _parse(result.rust_source,tokens,comments,pairs)
                      if item.kind=="fn"and item.name=="main")
            zero="Int::from_i128(0)"if mode=="bigint"else f"0_{mode}"
            harness=('fn main(){let scope=ClassScope::new();'
                     'let object=class_construct_0(scope.clone()).unwrap();'
                     f'let error=class_function_2(scope,object.clone(),{zero}).unwrap_err();'
                     'assert!(error.message.starts_with("ZeroDivisionError:"));'
                     'let values=class_get_0_0(&object).unwrap();'
                     'let mut values=values.borrow_mut();'
                     'println!("{}",ClassDisplay::class_str(&values[0]));'
                     'values.clear();assert!(values.is_empty());}')
            rust=result.rust_source[:main.start]+harness+result.rust_source[main.end:]
            for optimize in (False,True):
                path=Path(self.directory.name)/f"error_state_{mode}_{optimize}.rs"
                path.write_text(rust)
                binary=path.with_suffix("")
                built=subprocess.run(["rustc","--edition=2021","--crate-name","state",
                    *(["-O"]if optimize else[]),str(path),"-o",str(binary)],
                    text=True,capture_output=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,
                    env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout,"10\n")

    def test_owner_index_once_before_get(self):
        self.exercise(*CASES["owner_index_once_before_get"])

    def test_effectful_rhs_keeps_negative_index_renormalization(self):
        source,inputs=CASES["effectful_rhs_negative_index"]
        self.exercise(source,inputs)
        result=transpile(source)
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn("fn class_list_get",result.rust_source)
        self.assertIn("fn class_list_set",result.rust_source)

    def test_getitem_error_precedes_rhs_call(self):
        self.exercise(*CASES["getitem_error_precedes_rhs_call"])

    def test_container_read_rhs_has_no_overlapping_borrow(self):
        self.exercise(*CASES["container_read_rhs"])

    def test_captured_row_survives_parent_mutation(self):
        self.exercise(*CASES["captured_row_survives_parent_mutation"])

    def test_shortcircuit_and_conditional_errors(self):
        self.exercise(*CASES["shortcircuit_and_conditional_errors"])

    def test_primitive_unbound_rhs_order(self):
        self.exercise(*CASES["primitive_unbound_rhs_order"])

    def test_field_getter_failure_before_commit(self):
        self.exercise(*CASES["field_getter_failure_before_commit"])

    def test_mutable_element_keeps_augmented_alias(self):
        self.exercise(*CASES["mutable_element_keeps_augmented_alias"])

    def test_scalar_only_update_omits_get_set_helpers(self):
        source='''class Counter:
 def __init__(self):self.values=[3,7]
 def update(self,index,delta):self.values[index]+=delta
box=Counter()
box.update(-1,4)
print(box.values)
'''
        self.exercise(source)
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn("fn class_list_get",result.rust_source)
            self.assertNotIn("fn class_list_set",result.rust_source)


if __name__=="__main__":unittest.main()
