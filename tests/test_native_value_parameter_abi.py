"""Physical ABI contracts for future headers, references and nested captures."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest

from py2fastrust.native_value_parameter_borrows import apply
import test_native_lambda_callbacks as helpers


ASYNC = '#![allow(dead_code,unused_variables,unused_assignments)]\n#[derive(Clone,Copy)] struct ClassScope;\ntype ClassResult<T> = Result<T,String>;\n#[derive(Clone)] struct ClassHandle_0 { value:i64 }\nasync fn class_function_0(class_scope:ClassScope,class_argument_0:ClassHandle_0)->ClassResult<i64>{\n let mut class_local_0:Option<ClassHandle_0>=None;\n class_local_0=Some(class_argument_0);\n Ok(class_local_0.unwrap().value)\n}\nfn main(){\n let future;\n {let value=ClassHandle_0{value:7};future=class_function_0(ClassScope,value);}\n drop(future);\n}\n'
DROP = '#![allow(dead_code,unused_variables,unused_assignments)]\n#[derive(Clone,Copy)] struct ClassScope;\ntype ClassResult<T> = Result<T,String>;\n#[derive(Clone)] struct ClassData_0 { value:i64 }\ntype ClassHandle_0=ClassData_0;\nimpl Drop for ClassData_0{fn drop(&mut self){println!("drop {}",self.value);}}\nfn class_function_0(class_scope:ClassScope,class_argument_0:ClassHandle_0)->ClassResult<i64>{\n let mut class_local_0:Option<ClassHandle_0>=None;\n class_local_0=Some(class_argument_0);\n Ok(class_local_0.unwrap().value)\n}\nfn main(){println!("{}",class_function_0(ClassScope,ClassHandle_0{value:7}).unwrap());}\n'
COMMON = '#![allow(dead_code,unused_variables,unused_assignments,improper_ctypes_definitions)]\n#[derive(Clone,Copy)] struct ClassScope;\ntype ClassResult<T>=Result<T,String>;\n#[derive(Clone,Copy)] struct ClassHandle_0{value:i64}\n'
FUNCTION = 'fn class_function_0(class_scope:ClassScope,class_argument_0:ClassHandle_0)->ClassResult<i64>{\n let mut class_local_0:Option<ClassHandle_0>=None;\n class_local_0=Some(class_argument_0);\n Ok(class_local_0.unwrap().value)\n}\n'
POINTER = '#![allow(dead_code,unused_variables,unused_assignments,improper_ctypes_definitions)]\n#[derive(Clone,Copy)] struct ClassScope;\ntype ClassResult<T>=Result<T,String>;\n#[derive(Clone,Copy)] struct ClassHandle_0{value:i64}\nfn class_function_0(class_scope:ClassScope,class_argument_0:ClassHandle_0)->ClassResult<i64>{\n let mut class_local_0:Option<ClassHandle_0>=None;\n class_local_0=Some(class_argument_0);\n Ok(class_local_0.unwrap().value)\n}\nfn main(){\n let reader:fn(ClassScope,ClassHandle_0)->ClassResult<i64>=class_function_0;\n println!("{}",reader(ClassScope,ClassHandle_0{value:7}).unwrap());\n}\n'
NESTED = '#![allow(dead_code,unused_variables,unused_assignments,improper_ctypes_definitions)]\n#[derive(Clone,Copy)] struct ClassScope;\ntype ClassResult<T>=Result<T,String>;\n#[derive(Clone,Copy)] struct ClassHandle_0{value:i64}\nfn class_function_0(class_scope:ClassScope,class_argument_0:ClassHandle_0)->ClassResult<i64>{\n let mut class_local_0:Option<ClassHandle_0>=None;\n class_local_0=Some(class_argument_0);\n Ok(class_local_0.unwrap().value)\n}\nfn class_function_1(class_scope:ClassScope,class_argument_0:ClassHandle_0,class_argument_1:i64)->ClassResult<i64>{\n let mut class_local_0:Option<ClassHandle_0>=None;\n class_local_0=Some(class_argument_0);\n Ok(class_local_0.unwrap().value+class_argument_1)\n}\nfn mark(value:i64)->ClassHandle_0{println!("make {}",value);ClassHandle_0{value}}\nfn main(){println!("{}",class_function_1(ClassScope,mark(2),class_function_0(ClassScope,mark(7)).unwrap()).unwrap());}\n'


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeValueParameterABIContractTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)

    def check(self, source, parameters, expected, unchanged):
        registry = SimpleNamespace(parameters=parameters, applied={}, reasons={})
        result = apply(source, SimpleNamespace(value_parameter_borrows=registry))
        self.assertEqual(source == result, unchanged)
        for code in (source, result):
            for optimized in (False, True):
                key = (code, optimized)
                if key not in self.cache:
                    name = hashlib.sha256(repr(key).encode()).hexdigest()
                    path = Path(self.directory.name) / (name + ".rs")
                    path.write_text(code)
                    binary = path.with_suffix("")
                    build = subprocess.run(["rustc", "--edition=2021", "--crate-name", "abi_contract",
                        *(["-O"] if optimized else []), str(path), "-o", str(binary)],
                        capture_output=True, text=True, timeout=120)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    self.cache[key] = binary
                run = subprocess.run([str(self.cache[key])], capture_output=True, text=True,
                    timeout=10, env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout, expected)
                self.assertEqual(run.stderr, "")

    def test_future_and_other_header_qualifiers_retain_owned_abi(self):
        self.check(ASYNC, {(0, 0): 0}, "", True)
        for qualifier in ("const ", "unsafe ", 'extern "C" '):
            invocation = "class_function_0(ClassScope,ClassHandle_0{value:7}).unwrap()"
            if qualifier == "unsafe ":
                invocation = "unsafe{" + invocation + "}"
            source = COMMON + qualifier + FUNCTION + 'fn main(){println!("{}",' + invocation + ');}'
            self.check(source, {(0, 0): 0}, "7\n", True)

    def test_address_taken_rust_function_retains_owned_abi(self):
        self.check(POINTER, {(0, 0): 0}, "7\n", True)

    def test_custom_drop_through_type_alias_retains_owned_abi(self):
        self.check(DROP, {(0, 0): 0}, "drop 7\n7\n", True)

    def test_nested_arguments_keep_original_evaluation_order(self):
        self.check(NESTED, {(0, 0): 0, (1, 0): 0}, "make 2\nmake 7\n9\n", False)


if __name__ == "__main__":
    unittest.main()
