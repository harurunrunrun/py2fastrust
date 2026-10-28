"""Independent cleanup boundaries for shadowing, inferred types and control flow."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from py2fastrust.rust_cleanup import cleanup_rust_source_with_report


_GUARD = '''#![allow(unused_variables,unused_assignments,unused_mut,non_snake_case)]
struct Guard(&'static str);
impl Drop for Guard {fn drop(&mut self){print!("drop:{}|",self.0);}}
'''
_ALLOW = '#![allow(unused_variables,unused_assignments,non_camel_case_types)]\n'


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class RustCleanupBoundaryTests(unittest.TestCase):
    def assert_preserved(self, source, expected_stdout):
        """Check both build profiles, including an independently compiled input."""
        cleaned = cleanup_rust_source_with_report(source).source
        with tempfile.TemporaryDirectory(prefix="pytors-cleanup-boundary-") as directory:
            for optimize in (False, True):
                with self.subTest(optimized=optimize):
                    executions = []
                    for label, text in (("original", source), ("cleaned", cleaned)):
                        path = Path(directory) / (label + ("_release" if optimize else "_debug") + ".rs")
                        path.write_text(text, encoding="utf-8")
                        binary = path.with_suffix("")
                        built = subprocess.run(
                            ["rustc", "--crate-name", "cleanup_boundary", "--edition=2021",
                             *(["-O"] if optimize else []), str(path), "-o", str(binary)],
                            capture_output=True, text=True, timeout=90,
                        )
                        self.assertEqual(built.returncode, 0, f"{label}: {built.stderr}\n{text}")
                        actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                        executions.append((actual.stdout, actual.stderr, actual.returncode))
                    self.assertEqual(executions[0], (expected_stdout, "", 0))
                    self.assertEqual(executions[1], executions[0], cleaned)

    def test_hidden_pattern_bindings_preserve_noncopy_move_and_drop_order(self):
        # The earlier i64 name must not supply the type of a pattern/parameter
        # that shadows it. Removing `discarded=value` changes Guard drop order.
        bodies = {
            "let_pattern": '''fn main(){
 let value:i64=0;
 let Some(value)=Some(Guard("value")) else {return};
 let middle=Guard("middle");let discarded=value;print!("body|");
}
''',
            "for_pattern": '''fn main(){
 let value:i64=0;
 for (value,) in [(Guard("value"),)] {
  let middle=Guard("middle");let discarded=value;print!("body|");
 }
}
''',
            "closure_parameter": '''fn main(){
 let value:i64=0;
 (|value:Guard|{
  let middle=Guard("middle");let discarded=value;print!("body|");
 })(Guard("value"));
}
''',
            "match_pattern": '''fn main(){
 let value:i64=0;
 match Some(Guard("value")) {
  Some(value)=>{let middle=Guard("middle");let discarded=value;print!("body|");},
  None=>{},
 }
}
''',
            "if_let_pattern": '''fn main(){
 let value:i64=0;
 if let Some(value)=Some(Guard("value")) {
  let middle=Guard("middle");let discarded=value;print!("body|");
 }
}
''',
        }
        for name, body in bodies.items():
            with self.subTest(binding=name):
                self.assert_preserved(_GUARD + body, "body|drop:value|drop:middle|")

    def test_trait_generic_parameter_does_not_inherit_an_unrelated_copy_alias(self):
        self.assert_preserved(_GUARD + '''type T=i64;
trait Consume<T> {
 fn consume(value:T){
  let middle=Guard("middle");let held:T=value;print!("body|");
 }
}
impl Consume<Guard> for () {}
fn main(){<()as Consume<Guard>>::consume(Guard("value"));}
''', "body|drop:value|drop:middle|")

    def test_operand_cast_does_not_determine_the_complete_binary_result_type(self):
        # `as` binds to the right operand. The complete result is respectively
        # a Non-Copy Guard and bool, so an i64 wildcard would not compile.
        cases = (
            (_GUARD + '''struct Left;
impl std::ops::Add<i64> for Left {
 type Output=Guard;
 fn add(self,rhs:i64)->Guard{print!("add|");Guard("result")}
}
fn main(){let discarded=Left+1_i64 as i64;print!("body|");}
''', "add|body|drop:result|"),
            (_ALLOW + '''fn side()->i64{print!("side|");7}
fn main(){let discarded=side()==1_i64 as i64;print!("body|");}
''', "side|body|"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assert_preserved(source, expected)

    def test_inferred_primitive_type_names_respect_alias_and_generic_scopes(self):
        # A literal suffix refers to the builtin primitive. Reconstructing its
        # type using an unqualified identifier can instead resolve an alias.
        bodies = {
            "integer_alias": '''type i64=u64;
fn side()->std::primitive::i64{print!("side|");7}
fn main(){let mut discarded=side();discarded=1_i64;print!("body|");}
''',
            "generic_parameter": '''fn side()->std::primitive::i64{print!("side|");7}
fn run<i64>(){let mut discarded=side();discarded=1_i64;print!("body|");}
fn main(){run::<String>();}
''',
            "boolean_alias": '''type bool=u64;
fn side()->std::primitive::bool{print!("side|");true}
fn main(){let mut discarded=side();discarded=false;print!("body|");}
''',
        }
        for name, body in bodies.items():
            with self.subTest(type_scope=name):
                self.assert_preserved(_ALLOW + body, "side|body|")

    def test_diverging_copy_initializers_preserve_control_transfer(self):
        prefix = '#![allow(unused_variables,unreachable_code)]\n'
        cases = (
            ('fn main(){let ignored:i64=return;print!("body|");}\n', ""),
            ('fn main(){for _ in 0..3{let ignored:i64=break;print!("loop|");}print!("body|");}\n', "body|"),
            ('fn main(){for _ in 0..3{let ignored:i64=continue;print!("loop|");}print!("body|");}\n', "body|"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assert_preserved(prefix + source, expected)


if __name__ == "__main__":
    unittest.main()
