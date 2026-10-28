"""One builtin sequence operation across owned and shared physical storage."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_sequence_plans import sequence_method
from py2fastrust.native_types import ListType,TupleType
from tests import test_native_classes as support


class SequencePlanTests(unittest.TestCase):
    def test_canonical_receiver_types_share_signatures_and_argument_roles(self):
        for kind in ("list_int",ListType("str"),ListType(TupleType(("int","str")))):
            method=sequence_method(kind,"sort")
            node=ast.parse("xs.sort(reverse=direction(),key=key())").body[0].value
            from py2fastrust.call_semantics import normalize_call
            call=method.signature.plan(normalize_call(node),implicit_count=1)
            self.assertEqual(call.argument_parameters,("reverse","key"))
            self.assertTrue(method.mutates)
        self.assertIsNone(sequence_method("str","sort"))


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class SequenceStorageExecutionTests(unittest.TestCase):
    compile=support.NativeClassTests.compile
    compare=support.NativeClassTests.compare

    def paired(self,source):
        self.compare(source)
        self.compare("class Scope:\n pass\n"+source)

    def test_sort_reverse_append_and_typed_search_share_operations(self):
        self.paired('''xs=[(3,2),(1,4),(1,2)]
print(xs.sort(),xs)
print(xs.reverse(),xs)
print(xs.append((8,9)),xs)
print(xs.count((1,4)),xs.index((1,2)),xs.pop(),xs)
''')

    def test_copy_and_self_extension_keep_independent_containers(self):
        self.paired('''xs=[3,1,2]
ys=xs.copy()
print(xs.extend(xs),xs,ys)
print(xs.clear(),xs,ys)
print(xs.append(9),xs,ys)
''')

    def test_empty_typed_container_uses_allocation_element_facts(self):
        self.paired('''xs=[]
print(xs.append("b"))
print(xs.append("a"))
print(xs.sort(reverse=True),xs)
print(xs.pop(),xs.count("b"),xs.index("b"))
''')

    def test_shared_receiver_identity_is_captured_before_arguments(self):
        self.compare('''class Box:
 def __init__(self):
  self.values=[3,1]
 def replace(self):
  self.values=[99]
  return 7
box=Box()
old=box.values
print(box.values.append(box.replace()),old,box.values)
''')

    def test_shared_search_arguments_mutate_contents_before_borrow(self):
        self.compare('''class Box:
 def __init__(self):
  self.values=[1,2,1]
box=Box()
print(box.values.count(box.values.pop()),box.values)
print(box.values.index(box.values.pop()),box.values)
''')

    def test_sort_evaluates_keyword_producers_before_contents_borrow(self):
        self.compare('''class Box:
 def __init__(self):
  self.values=[3,1,2]
 def key(self):
  print("key")
  self.values=[99]
  return None
 def direction(self):
  print("direction")
  return True
box=Box()
old=box.values
print(box.values.sort(reverse=box.direction(),key=box.key()))
print(old,box.values)
''')

    def test_shared_nullable_elements_keep_python_equality(self):
        self.compare('''class Box:
 def __init__(self):
  self.values=[1,None,"x",False]
box=Box()
print(box.values.count(False),box.values.index(None))
print(box.values.append("y"),box.values.pop(),box.values)
copy=box.values.copy()
print(copy==box.values,copy is box.values)
''')

    def test_user_method_with_builtin_name_retains_class_identity(self):
        self.compare('''class Sorter:
 def sort(self,reverse=3):
  return reverse+9
item=Sorter()
print(item.sort(),item.sort(reverse=4))
''')

    def test_owned_matrix_row_receiver_keeps_index_before_arguments(self):
        source='''def index():
 print("index",end="|")
 return int(input())
rows=[[3,1],[2,5]]
rows[index()].append(int(input()))
rows[0].sort()
print(rows[0][0],rows[0][-1],rows[1][0])
'''
        for data in ("0\n7\n","2\nbad\n"):
            self.compare(source,modes=("i64","i128"),data=data)

    def test_empty_sort_and_clear_epochs_do_not_guess_an_element_type(self):
        self.paired('''xs=[]
print(xs.sort(),xs.copy(),xs.count(1))
xs=[1,2]
xs.clear()
xs.append("word")
print(xs)
''')

    def test_borrowed_immutable_arguments_are_captured_without_consuming_names(self):
        self.paired('''words=[]
word="same"
words.append(word)
print(word,words)
pairs=[]
pair=(3,"word")
pairs.append(pair)
print(pair,pairs)
raw=[]
value=b"bytes"
raw.append(value)
print(value,raw)
''')

    def test_extension_coerces_destination_without_changing_source_values(self):
        self.paired('''xs=[1]
ys=[True,False]
print(xs.extend(ys),xs,ys)
nullable=[None]
words=["one","two"]
print(nullable.extend(words),nullable,words)
''')


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class SequenceSortConversionOrderTests(unittest.TestCase):
    def profiles(self,source,data=""):
        expected=subprocess.run([sys.executable,"-I","-c",source],input=data,capture_output=True,text=True,timeout=10)
        with tempfile.TemporaryDirectory(prefix="pytors-sort-conversion-")as directory:
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=mode,filename="sort-order.py"))
                self.assertTrue(result.success,result.diagnostics)
                path=Path(directory)/(mode+".rs");path.write_text(result.rust_source)
                for release in (False,True):
                    with self.subTest(mode=mode,release=release):
                        binary=path.with_name(mode+("_release"if release else"_debug"))
                        built=subprocess.run(["rustc","--edition=2021",*(["-O"]if release else[]),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                        self.assertEqual(built.returncode,0,built.stderr)
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,
                                              env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                        self.assertEqual(actual.stdout,expected.stdout)
                        if actual.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                             expected.stderr.splitlines()[-1].split(":")[0])

    def test_owned_reverse_uses_one_truth_conversion_before_sort(self):
        source='''def key_none():
 print("key",end="|")
 return None
a=[2,1]
print(a.sort(reverse=a),a)
empty=[]
print(empty.sort(reverse=empty),empty)
direction=[0]
separate=[2,1]
print(separate.sort(reverse=direction),separate,direction)
with_key=[1,2]
print(with_key.sort(key=key_none(),reverse=with_key),with_key)
direction=[]
ascending=[2,1]
print(ascending.sort(reverse=direction,key=key_none()),ascending,direction)
'''
        self.profiles(source)

    def test_shared_self_and_separate_aliases_are_read_after_keyword_effects(self):
        source='''class Helper:
 def clear(self,values):
  print("key",end="|")
  values.clear()
  return None
helper=Helper()
a=[2,1]
print(a.sort(reverse=a),a)
empty=[]
print(empty.sort(reverse=empty),empty)
direction=[0]
alias=direction
separate=[2,1]
print(separate.sort(reverse=alias),separate,direction)
after_effect=[2,1]
print(after_effect.sort(reverse=alias,key=helper.clear(direction)),after_effect,direction)
self_effect=[2,1]
print(self_effect.sort(reverse=self_effect,key=helper.clear(self_effect)),self_effect)
'''
        self.profiles(source)

    def test_callable_key_path_captures_reverse_before_decorating_values(self):
        self.profiles('''def score(value):
 print(value,end="|")
 return value%2
a=[1,2,3,4]
print(a.sort(key=score,reverse=a),a)
direction=[]
b=[1,2,3,4]
print(b.sort(reverse=direction,key=score),b)
''')

    def test_mutable_reverse_contents_are_observed_after_later_arguments(self):
        source='''direction=[None]
a=[2,1]
print(a.sort(reverse=direction,key=direction.pop()),a,direction)
direction=[None,None]
b=[2,1]
print(b.sort(reverse=direction,key=direction.pop()),b,direction)
direction=[1]
c=[2,1]
print(c.sort(reverse=direction,key=direction.clear()),c,direction)
self_clear=[2,1]
print(self_clear.sort(reverse=self_clear,key=self_clear.clear()),self_clear)
'''
        self.profiles(source)
        self.profiles("class Marker:\n pass\n"+source)

    def test_unbound_reverse_argument_is_read_before_keyword_effects(self):
        source='''def key_none():
 print("key",end="|")
 return None
if int(input()):
 direction=[1]
a=[2,1]
print(a.sort(reverse=direction,key=key_none()),a)
'''
        for data in ("0\n","1\n"):
            self.profiles(source,data)
            self.profiles("class Marker:\n pass\n"+source,data)

    def test_unproved_user_truth_protocol_is_an_explicit_diagnostic(self):
        source='''class Direction:
 def __bool__(self):
  print("truth")
  return False
a=[2,1]
a.sort(reverse=Direction())
print(a)
'''
        for mode in ("i64","i128","bigint"):
            with self.subTest(mode=mode):
                result=transpile(source,TranspileOptions(integer=mode,filename="truth-protocol.py"))
                self.assertFalse(result.success)
                self.assertIsNone(result.rust_source)
                self.assertEqual(result.diagnostics[0].code,"E006")
                self.assertGreater(result.diagnostics[0].line,0)


if __name__=="__main__":unittest.main()
