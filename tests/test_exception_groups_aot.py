"""PEP 654 except* lowering against the official CPython 3.14 compiler."""

import shutil
import unittest

from py2fastrust.compiler import Compiler
from py2fastrust.diagnostics import CompilationError
import test_runtime


DESCRIBE = '''
def describe(error):
    if isinstance(error,BaseExceptionGroup):
        return type(error).__name__,error.message,tuple(describe(child) for child in error.exceptions)
    return type(error).__name__,str(error)
'''


class ExceptStarFrontendTests(unittest.TestCase):
    def test_handler_state_is_separate_from_user_locals_and_finally_is_retained(self):
        source = '''
try:
 raise ExceptionGroup("group",[ValueError(1),TypeError(2)])
except* ValueError as matched:
 pass
except* TypeError:
 pass
finally:
 pass
'''
        program = Compiler("groups.py").compile(source)
        operations = program.codes[0].ops
        self.assertEqual(sum(op.op == "BeginExceptStar" for op in operations), 1)
        self.assertEqual(sum(op.op == "SplitExceptStar" for op in operations), 2)
        self.assertEqual([op.args for op in operations if op.op == "RecordExceptStar"],
                         [(False,), (True,), (False,), (True,)])
        self.assertEqual(sum(op.op == "EndExceptStar" for op in operations), 1)
        self.assertTrue(any(op.op == "Delete" and op.args[0].startswith("$tmp") for op in operations))
        self.assertTrue(all(op.line > 0 and op.column > 0 for op in operations))

    def test_forbidden_control_flow_and_mixed_handlers_use_official_validation(self):
        rejected = [
            'def f():\n try: raise ValueError()\n except* Exception:\n  return 1',
            'for x in [1]:\n try: raise ValueError()\n except* Exception:\n  break',
            'for x in [1]:\n try: raise ValueError()\n except* Exception:\n  continue',
            'try: pass\nexcept ValueError: pass\nexcept* TypeError: pass',
            'try: pass\nexcept*: pass',
        ]
        for source in rejected:
            with self.subTest(source=source), self.assertRaises(CompilationError):
                Compiler().compile(source)
        Compiler().compile('try: raise ValueError()\nexcept* Exception:\n for x in [1]:\n  break\n def nested(): return 1')


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ExceptStarAotTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def check_source(self, source):
        return self.run_source(DESCRIBE + source)

    def test_all_matching_handlers_execute_in_order_and_preserve_nested_structure(self):
        self.check_source('''
events=[]
original=ExceptionGroup("outer",[ValueError("v1"),ExceptionGroup("inner",[TypeError("t"),ValueError("v2")]),OSError("o")])
try:
 raise original
except* (ValueError,KeyError) as error:
 events.append(("value",describe(error)))
except* TypeError as error:
 events.append(("type",describe(error)))
except* Exception as error:
 events.append(("rest",describe(error)))
print(events)
print("error" in globals())
''')

    def test_unmatched_naked_exceptions_and_matched_wrapping(self):
        self.check_source('''
original=ValueError("naked")
try:
 try: raise original
 except* TypeError,KeyError: print("unexpected")
except ValueError as error:
 print(error is original,describe(error))
try:
 try: raise original
 except* ValueError as matched:
  print(type(matched).__name__,matched.message,matched.exceptions[0] is original)
  raise
except BaseException as error:
 print(describe(error))
try: raise KeyboardInterrupt("interrupt")
except* BaseException as error:
 print(type(error).__name__,describe(error))
''')

    def test_unmatched_and_bare_reraised_branches_merge_back_into_original_tree(self):
        self.check_source('''
value=ValueError("value")
type_error=TypeError("type")
os_error=OSError("os")
original=ExceptionGroup("outer",[value,ExceptionGroup("inner",[type_error,os_error])])
try:
 try: raise original
 except* ValueError: raise
 except* TypeError: pass
except ExceptionGroup as error:
 print(describe(error))
 print(error.exceptions[0] is value,error.exceptions[1].exceptions[0] is os_error)
try:
 try: raise original
 except* ValueError: raise
 except* TypeError: raise
 except* OSError: raise
except ExceptionGroup as error:
 print(describe(error),error.exceptions[0] is value)
''')

    def test_newly_raised_exceptions_do_not_match_later_handlers_and_merge_in_order(self):
        self.check_source('''
events=[]
try:
 try: raise ExceptionGroup("original",[ValueError("v"),TypeError("t"),OSError("o")])
 except* ValueError as caught:
  events.append("first")
  raise LookupError("new first")
 except* LookupError: events.append("must not catch newly raised")
 except* TypeError as caught:
  events.append("second")
  raise RuntimeError("new second")
except BaseException as error:
 print(events,describe(error))
 print([describe(child.__context__) for child in error.exceptions[:2]])
print("caught" in globals())
''')

    def test_explicit_subgroup_raise_and_modified_metadata_are_new_exceptions(self):
        self.check_source('''
for change in [False,True]:
 try:
  try: raise ExceptionGroup("original",[ValueError("v"),TypeError("t")])
  except* ValueError as caught:
   if change:
    caught.__cause__=RuntimeError("cause")
    raise
   raise caught
 except BaseException as error:
  print(describe(error))
  first=error.exceptions[0]
  print(type(first.__cause__).__name__,type(first.__context__).__name__)
''')

    def test_active_subgroups_alias_cleanup_and_nested_exception_context(self):
        self.check_source('''
import sys
outer=RuntimeError("outer")
def matcher(label,kind):
 print(label,describe(sys.exception()),"matched" in globals())
 return kind
try:
 raise outer
except RuntimeError:
 try:
  raise ExceptionGroup("group",[ValueError("v"),TypeError("t")])
 except* matcher("type1",ValueError) as matched:
  print("body1",sys.exception() is matched)
  try: raise KeyError("nested")
  except KeyError: pass
  print("restored subgroup",sys.exception() is matched)
 except* matcher("type2",TypeError) as matched:
  print("body2",sys.exception() is matched)
 print("outer restored",sys.exception() is outer)
print(sys.exception())
''')

    def test_matcher_errors_abort_later_handlers_and_restore_enclosing_exception(self):
        self.check_source('''
import sys
events=[]
def fail_matcher():
 events.append("matcher")
 print(describe(sys.exception()))
 raise LookupError("bad matcher")
try:
 try: raise ExceptionGroup("original",[ValueError("v"),TypeError("t")])
 except* ValueError:
  events.append("first")
  raise RuntimeError("discarded when matcher fails")
 except* fail_matcher(): pass
 except* Exception: events.append("never")
except LookupError as error:
 print(events,describe(error),describe(error.__context__))
print(sys.exception())
for mode in [0,1,2]:
 try:
  try: raise ValueError("v")
  except* Exception: pass
  except* (42 if mode==0 else ExceptionGroup if mode==1 else (ValueError,42)): pass
 except TypeError as error: print(str(error))
print(sys.exception())
''')

    def test_else_finally_and_finally_return_overrides_merged_errors(self):
        self.check_source('''
events=[]
def run(fail):
 try:
  if fail: raise ExceptionGroup("g",[ValueError("v"),TypeError("t")])
  events.append("body")
 except* ValueError: events.append("caught value")
 else: events.append("else")
 finally: events.append("finally")
run(False)
try: run(True)
except ExceptionGroup as error: print(describe(error))
print(events)
def override():
 try:
  try: raise ExceptionGroup("g",[ValueError("v"),TypeError("t")])
  except* ValueError: raise RuntimeError("new")
 finally: return 29
print(override())
''')

    def test_generator_suspension_throw_and_close_preserve_handler_state(self):
        self.check_source('''
events=[]
def generate():
 try:
  try: raise ExceptionGroup("g",[ValueError("v"),TypeError("t")])
  except* ValueError as error:
   yield describe(error)
  except* TypeError as error:
   yield describe(error)
 finally: events.append("finally")
iterator=generate()
print(next(iterator))
print(iterator.throw(RuntimeError("injected")))
try: next(iterator)
except RuntimeError as error: print(describe(error),describe(error.__context__))
print(events)
def closeable():
 try:
  try: raise ExceptionGroup("g",[ValueError("v"),TypeError("t")])
  except* ValueError:
   try: yield "paused"
   finally: events.append("inner cleanup")
  except* TypeError: events.append("next handler")
 finally: events.append("outer cleanup")
iterator=closeable()
print(next(iterator))
iterator.close()
print(events)
''')

    def test_nested_star_handlers_gc_and_class_annotation_tracking(self):
        self.check_source('''
import gc
events=[]
try:
 raise ExceptionGroup("outer",[ValueError([1]),TypeError([2])])
except* ValueError as outer:
 gc.collect()
 try: raise ExceptionGroup("inner",[KeyError([3]),OSError([4])])
 except* KeyError as inner:
  gc.collect()
  events.append((outer.exceptions[0].args,inner.exceptions[0].args))
 except* OSError: pass
except* TypeError as outer:
 gc.collect()
 events.append(outer.exceptions[0].args)
print(events,"outer" in globals(),"inner" in globals())
class Token:
 def __del__(self): events.append("released")
try: raise ExceptionGroup("temporary",[ValueError(Token())])
except* Exception: pass
gc.collect()
print(events[-1])
class C:
 try: raise ExceptionGroup("annotations",[ValueError(),TypeError()])
 except* ValueError:
  first:int
 except* TypeError:
  second:str
print(C.__annotations__,[name for name in C.__dict__ if name.startswith("$tmp")])
''')

    def test_inner_loop_control_flow_and_nested_functions_are_allowed(self):
        self.check_source('''
try: raise ValueError("v")
except* ValueError:
 for value in range(4):
  if value==0: continue
  if value==2: break
  print(value)
 def nested(): return "nested return"
 print(nested())
print("completed")
''')

    def test_alias_binding_and_cleanup_failures_abort_the_handler_chain(self):
        self.check_source('''
events=[]
class Namespace(dict):
 def __setitem__(self,key,value):
  if key=="caught": events.append(type(value).__name__)
  super().__setitem__(key,value)
  if key=="caught" and ((mode=="bind" and isinstance(value,BaseExceptionGroup)) or (mode!="bind" and value is None)):
   raise LookupError("namespace failure")
class Meta(type):
 @classmethod
 def __prepare__(meta,name,bases): return Namespace()
for mode in ["bind","normal cleanup","error cleanup"]:
 events.clear()
 try:
  class C(metaclass=Meta):
   try: raise ExceptionGroup("group",[ValueError("v"),TypeError("t")])
   except* ValueError as caught:
    events.append("body1")
    if mode=="error cleanup": raise RuntimeError("body failed")
   except* TypeError: events.append("must not continue")
 except LookupError as error:
  print(mode,events,type(error.__context__).__name__)
''')


if __name__ == "__main__":
    unittest.main()
