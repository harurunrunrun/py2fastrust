"""Independent ownership invariants for emitted exception trace states."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile

SOURCE = '''class Suppress:
 def __enter__(self):return self
 def __exit__(self,a,b,c):return True
class Raiser:
 def __init__(self,error):self.error=error
 def __enter__(self):return self
 def __exit__(self,a,b,c):raise self.error
def touch(error):raise error
def make():
 first=ValueError("first")
 second=TypeError("second")
 with Suppress():
  with Raiser(second):raise first
 with Suppress():touch(first)
 return second
raise make()
'''

HARNESS = r'''
#[cfg(test)]
mod independent_exception_ownership_review {
 use super::*;
 #[derive(Debug)] struct Payload(&'static str);
 impl ClassExceptionPayload for Payload {
  fn class_kind(&self)->ClassExceptionKind{ClassExceptionKind::ValueError}
  fn class_name(&self)->&'static str{"ValueError"}
  fn class_str(&self)->String{self.0.to_owned()}
  fn class_repr(&self)->String{format!("ValueError({:?})",self.0)}
 }
 type State=Rc<RefCell<Option<NativeError>>>;
 fn raised(scope:&ClassScope,label:&'static str,line:usize)->(State,NativeError){
  let state=class_exception_state_new(scope);
  let error=class_exception_raise(Rc::new(Payload(label)),state.clone(),line,("kernel","origin"));
  (state,error)
 }
 fn pair(scope:&ClassScope)->(State,State,NativeError,NativeError){
  let(a,mut first)=raised(scope,"first",11);
  let(b,mut second)=raised(scope,"second",22);
  // Distinct copies of the same target are distinct owned Rc edges.
  first.context=Some(Box::new(second.clone()));
  first.cause=Some(Box::new(second.clone()));
  class_exception_sync(&first);
  second.context=Some(Box::new(first.clone()));
  class_exception_sync(&second);
  (a,b,first,second)
 }
 #[test] fn unraised_state_dies_without_collection(){
  let scope=ClassScope::new();let state=class_exception_state_new(&scope);
  let weak=Rc::downgrade(&state);drop(state);assert!(weak.upgrade().is_none());
 }
 #[test] fn own_snapshot_has_no_self_root(){
  let scope=ClassScope::new();let(state,error)=raised(&scope,"one",1);
  assert!(state.borrow().as_ref().unwrap().origin.is_none());
  let weak=Rc::downgrade(&state);drop(error);drop(state);
  assert!(weak.upgrade().is_none());
 }
 #[test] fn external_error_retains_identity_and_latest_frames(){
  let scope=ClassScope::new();let(state,error)=raised(&scope,"one",1);
  let weak=Rc::downgrade(&state);drop(state);
  assert_eq!(scope.control.borrow_mut().gc.collect(),0);
  assert!(weak.upgrade().is_some());
  let mut current=class_exception_current(&error);
  current.class_exception_push_frame((9,("kernel","later")));
  let latest=class_exception_current(&error);
  assert_eq!(latest.frames,vec![(9,("kernel","later"))]);
  assert!(class_exception_same_origin(&error,&latest));
  drop(latest);drop(current);drop(error);assert!(weak.upgrade().is_none());
 }
 #[test] fn context_retains_dropped_local_state(){
  let scope=ClassScope::new();let(a,first)=raised(&scope,"first",1);
  let(b,mut second)=raised(&scope,"second",2);
  class_exception_attach_context(&mut second,first.clone());
  let weak=Rc::downgrade(&a);drop(a);drop(first);
  scope.control.borrow_mut().gc.collect();assert!(weak.upgrade().is_some());
  let retained=class_exception_current(second.context.as_ref().unwrap());
  assert_eq!(class_exception_message(&retained),"ValueError: first");
  drop(retained);drop(second);drop(b);scope.control.borrow_mut().gc.collect();
  assert!(weak.upgrade().is_none());
 }
 #[test] fn rootless_context_and_duplicate_cause_edges_are_collected(){
  let scope=ClassScope::new();let(a,b,first,second)=pair(&scope);
  let wa=Rc::downgrade(&a);let wb=Rc::downgrade(&b);
  drop(a);drop(b);drop(first);drop(second);
  assert!(wa.upgrade().is_some());assert!(wb.upgrade().is_some());
  assert_eq!(scope.control.borrow_mut().gc.collect(),2);
  assert!(wa.upgrade().is_none());assert!(wb.upgrade().is_none());
 }
 #[test] fn live_external_error_roots_entire_cycle(){
  let scope=ClassScope::new();let(a,b,first,second)=pair(&scope);
  let wa=Rc::downgrade(&a);let wb=Rc::downgrade(&b);
  drop(a);drop(b);drop(second);
  assert_eq!(scope.control.borrow_mut().gc.collect(),0);
  assert!(wa.upgrade().unwrap().borrow().is_some());
  assert!(wb.upgrade().unwrap().borrow().is_some());
  drop(first);scope.control.borrow_mut().gc.collect();
  assert!(wa.upgrade().is_none());assert!(wb.upgrade().is_none());
 }
 #[test] fn borrowed_state_stays_live_until_guard_and_owner_drop(){
  let scope=ClassScope::new();let(a,b,first,second)=pair(&scope);
  let wa=Rc::downgrade(&a);let wb=Rc::downgrade(&b);
  let guard=a.borrow_mut();drop(b);drop(first);drop(second);
  assert_eq!(scope.control.borrow_mut().gc.collect(),0);
  assert!(guard.is_some());assert!(wb.upgrade().is_some());
  drop(guard);drop(a);scope.control.borrow_mut().gc.collect();
  assert!(wa.upgrade().is_none());assert!(wb.upgrade().is_none());
 }
 #[test] fn true_cause_survives_automatic_context_cycle_cut(){
  let scope=ClassScope::new();let(a,mut first)=raised(&scope,"first",1);
  let(b,mut second)=raised(&scope,"second",2);
  first.context=Some(Box::new(second.clone()));
  first.cause=Some(Box::new(second.clone()));class_exception_sync(&first);
  class_exception_attach_context(&mut second,first);
  let current=class_exception_current(&second);
  let context=class_exception_current(current.context.as_ref().unwrap());
  assert!(context.context.is_none());assert!(context.cause.is_some());
  assert!(class_exception_same_origin(context.cause.as_ref().unwrap(),&second));
  // The cause can lead back to an already rendered origin; rendering must end.
  class_exception_render_error(&second);
  drop(current);drop(context);drop(second);drop(a);drop(b);
  scope.control.borrow_mut().gc.collect();
 }
 #[test] fn registration_threshold_bounds_rootless_cycle_growth(){
  let scope=ClassScope::new();let mut last=None;
  for _ in 0..10000{
   let(a,b,first,second)=pair(&scope);last=Some((Rc::downgrade(&a),Rc::downgrade(&b)));
   drop(a);drop(b);drop(first);drop(second);
  }
  assert!(scope.control.borrow().gc.nodes.len()<128);
  scope.control.borrow_mut().gc.collect();
  assert!(scope.control.borrow().gc.nodes.is_empty());
  let(a,b)=last.unwrap();assert!(a.upgrade().is_none());assert!(b.upgrade().is_none());
 }
}
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExceptionTraceOwnershipTests(unittest.TestCase):
    def test_emitted_trace_state_ownership_in_debug_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text(SOURCE)
            # Run the unchanged source with CP first. Trace source decoration
            # differs by Python patch version; its final error is stable.
            reference = subprocess.run(
                [sys.executable, "-S", str(source)], text=True,
                capture_output=True, timeout=15,
            )
            self.assertEqual(reference.returncode, 1, reference.stderr)
            self.assertEqual(reference.stdout, "")
            self.assertEqual(reference.stderr.rstrip().splitlines()[-1], "TypeError: second")
            result = transpile(SOURCE, TranspileOptions(
                filename=str(source), integer="i64", license="none",
            ))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native")
            rust = root / "ownership.rs"
            # The emitted runtime stays intact; only an independent test
            # module is appended to observe internal Rc/Weak lifetimes.
            rust.write_text(result.rust_source + HARNESS)
            for optimized in (False, True):
                with self.subTest(optimized=optimized):
                    binary = root / ("release" if optimized else "debug")
                    build = subprocess.run(
                        ["rustc", "--edition=2021", "--test", "--crate-name",
                         "exception_ownership_review", *(["-O"] if optimized else []),
                         str(rust), "-o", str(binary)],
                        text=True, capture_output=True, timeout=180,
                    )
                    self.assertEqual(build.returncode, 0, build.stderr)
                    actual = subprocess.run(
                        [str(binary), "--test-threads=1"], input="", text=True,
                        capture_output=True, timeout=30,
                        env={**os.environ, "PATH": "/no-python", "PYTHONPATH": "/no-python"},
                    )
                    self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
                    self.assertIn("9 passed; 0 failed", actual.stdout)


if __name__ == "__main__":
    unittest.main()
