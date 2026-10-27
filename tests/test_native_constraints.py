"""Allocation field variables and CFG carriers share one pure fixed point."""
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_constraints import analyze
from py2fastrust.native_types import EMPTY,ListType,TupleType,NullableType,join_types
from py2fastrust.native_key_types import SetType,DictType


class ConstraintModelTests(unittest.TestCase):
    def facts(self,source):
        unit=build_program(source,"constraints.py").main
        return unit,analyze(unit)

    def test_allocation_variables_solve_before_first_observation(self):
        unit,result=self.facts('a=[]\ns=set()\nd={}\nfor i in range(int(input())):\n a.append((i,"s"))\n s.add((i,"s"))\n d[(i,"s")]=True\n')
        allocations=result.scope().allocations
        pair=TupleType(("int","str"))
        self.assertEqual(allocations[unit.ordinal(unit.tree.body[0].value)],ListType(pair))
        self.assertEqual(allocations[unit.ordinal(unit.tree.body[1].value)],SetType(pair))
        self.assertEqual(allocations[unit.ordinal(unit.tree.body[2].value)],DictType(pair,"bool"))
        self.assertGreaterEqual(result.iterations,2)

    def test_unconstrained_bottom_is_not_none_or_integer(self):
        unit,result=self.facts('a=[]\ns=set()\nd={}\n')
        self.assertEqual(list(result.scope().allocations.values()),[ListType(EMPTY),SetType(EMPTY),DictType(EMPTY,EMPTY)])
        self.assertNotEqual(EMPTY,"none")
        self.assertEqual(join_types(EMPTY,"str"),"str")

    def test_break_edges_do_not_pollute_loop_back_edges(self):
        unit,result=self.facts('x=None\nfor i in range(4):\n if i==2:\n  x=(i,)\n  break\n x="s"\n continue\n')
        header=result.scope().headers[unit.ordinal(unit.tree.body[1])]
        self.assertEqual(header['x'].kind,NullableType("str"))
        self.assertFalse(header['x'].maybe_unbound)

    def test_opaque_class_leaf_and_attribute_target_remain_extensible(self):
        from dataclasses import dataclass
        from py2fastrust.native_constraints import Solver,SemanticGraph,value
        @dataclass(frozen=True)
        class Leaf:
            _native_kind_tag="instance_test_leaf"
        unit=build_program('obj.field=1\n',"fields.py").main
        graph=SemanticGraph(unit)
        self.assertEqual(graph.body[0].data[0][0],"attribute")
        self.assertEqual(Solver(graph).kind(value(Leaf())),Leaf())

    def test_call_facts_preserve_captured_identities_and_receiver_origins(self):
        from py2fastrust.native_constraints import MethodValue,Allocation
        from py2fastrust.references import BuiltinIdentity
        source='r=range\na=[]\nb=a.copy()\nfor x in r(3):a.append(x)\n'
        unit,result=self.facts(source)
        facts=result.scope()
        range_call=unit.ordinal(unit.tree.body[3].iter)
        self.assertEqual(facts.calls[range_call].identity.alternatives,frozenset({BuiltinIdentity("range")}))
        copy_call=unit.ordinal(unit.tree.body[2].value)
        identity=next(iter(facts.calls[copy_call].identity.alternatives))
        self.assertIsInstance(identity,MethodValue)
        self.assertEqual(identity.name,"copy")
        self.assertTrue(any(isinstance(part,Allocation) for part in identity.receiver.alternatives))

    def test_recursive_field_dependency_retains_other_lower_bounds(self):
        from py2fastrust.native_constraints import Solver,SemanticGraph,Variable,value
        unit=build_program('a=[]\n',"cycle.py").main
        solver=Solver(SemanticGraph(unit));field=Variable((None,1),"element")
        solver.constrain(field,value(field).join(value("int")))
        self.assertEqual(solver.kind(value(field)),"int")

    def test_nonconverging_constraint_graph_has_positioned_diagnostic(self):
        from py2fastrust.native_constraints import ConstraintFailure
        source='print(1)\nfor i in range(2):print(i)\n'
        unit=build_program(source,"failure.py").main
        for mode in ("i64","i128","bigint"):
            with patch('py2fastrust.native_constraints.analyze',side_effect=ConstraintFailure(unit.tree.body[1])):
                result=transpile(source,TranspileOptions(integer=mode,filename="failure.py"))
            self.assertFalse(result.success)
            self.assertIsNone(result.rust_source)
            self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].line,result.diagnostics[0].filename),("E006",2,"failure.py"))

    def test_analysis_never_calls_emitters_or_executes_input(self):
        from py2fastrust.native import _Generator
        from py2fastrust.native_scalar import ScalarGenerator
        from py2fastrust.native_bigint import BigIntGenerator
        unit=build_program('a=[]\nfor i in range(int(input())):a.append(input())\n',"pure.py").main
        with patch.object(_Generator,'expression',side_effect=AssertionError('emitter probe')),patch.object(ScalarGenerator,'expression',side_effect=AssertionError('emitter probe')),patch.object(BigIntGenerator,'expression',side_effect=AssertionError('emitter probe')),patch('builtins.input',side_effect=AssertionError('source execution')):
            result=analyze(unit)
        self.assertEqual(next(iter(result.scope().allocations.values())),ListType("str"))


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ConstraintExecutionTests(unittest.TestCase):
    def compare(self,source,inputs=("0\n","1\n","5\n"),*,release=False,check=None,string_mode="unicode"):
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode,filename="constraints.py",string_mode=string_mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            self.assertNotIn('struct Runtime',result.rust_source)
            if check:check(result.rust_source)
            for optimized in (False,True) if release else (False,):
                with self.subTest(mode=mode,optimized=optimized):
                    with tempfile.TemporaryDirectory(prefix="pytors-constraints-") as directory:
                        path=Path(directory,"main.rs");path.write_text(result.rust_source)
                        binary=path.with_suffix('')
                        compiled=subprocess.run(['rustc','--edition=2021',*(['-O'] if optimized else []),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                        self.assertEqual(compiled.returncode,0,compiled.stderr)
                        for data in inputs:
                            expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=5)
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5)
                            self.assertEqual(actual.returncode,expected.returncode,(data,actual.stderr,expected.stderr))
                            self.assertEqual(actual.stdout,expected.stdout,(data,actual.stderr))
                            if expected.returncode:self.assertEqual(actual.stderr.strip().splitlines()[-1],expected.stderr.strip().splitlines()[-1].split('. Did you mean:')[0])

    def test_unproved_mutable_exit_transfer_is_rejected_before_codegen(self):
        # A shape-changing mutable payload needs a shared carrier/handle proof.
        # Until that ABI is available it must not be copied or moved twice.
        source='a=[1]\nfor i in range(int(input())):\n print(a)\n if i==2:\n  a="end"\n  break\nprint(a)\n'
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode,filename="moves.py"))
            self.assertFalse(result.success)
            self.assertIsNone(result.rust_source)
            self.assertEqual(result.diagnostics[0].code,"E006")

    def test_conditionally_assigned_mutable_carrier_survives_later_iterations(self):
        self.compare('for i in range(int(input())):\n if i==0:a=[i]\nprint(a)\n',("0\n","1\n","5\n"),release=True)

    def test_known_zero_loop_uses_guarded_bottom_carrier(self):
        self.compare('for a in []:\n b=a\nprint(b)\n',("",),release=True)

    def test_clear_epochs_keep_old_copies_and_solve_later_loop_constraints(self):
        self.compare('a=[1]\nb=a.copy()\na.clear()\nprint(a,b)\nfor i in range(int(input())):a.append((i,"s"))\nprint(a,b)\n')

    def test_zero_iterations_preserve_non_numeric_entry_value(self):
        self.compare('x="before"\nfor i in range(int(input())):x=i\nprint(x)\n',release=True)

    def test_exit_and_header_moves_transfer_owned_container_once(self):
        self.compare('a=[]\nfor i in range(int(input())):\n if i%2:a=[i]\n else:a=[i+1]\nprint(a)\n',release=True)

    def test_promoted_exact_empty_dictionary_loop_acceptance(self):
        self.compare('D={}\nfor i in range(3):\n D[(i,i)]=i\n',("",),release=True)
        self.compare('D={}\nfor i in range(3):\n D[(i,i)]=i\nprint(len(D),D[(2,2)])\n',("",))

    def test_promoted_exact_conditional_empty_list_has_python_unbound_error(self):
        self.compare('if int(input()):\n A=[]\nprint(len(A))\n',("0\n","1\n"),release=True)

    def test_ascii_and_unicode_modes_share_the_same_container_constraints(self):
        source='a=[]\nfor i in range(int(input())):a.append(input().strip())\nprint(a)\nif len(a):print(len(a[0]),a[0][0])\n'
        for string_mode in ("ascii","unicode"):
            self.compare(source,("0\n","1\n word \n","2\n alpha \nbeta\n"),string_mode=string_mode)

    def test_empty_lists_sets_dicts_observed_before_loop_insertion(self):
        self.compare('''a=[]
s=set()
d={}
print(a,len(s),len(d),bool(a))
for i in range(int(input())):
 a.append((i,"word"))
 s.add((i,"word"))
 d[(i,"word")]=i%2==0
print(a,len(s),len(d),(0,"word") in s,d.get((0,"word"),False))
''',release=True)

    def test_unconstrained_bottom_operations_do_not_guess_integer_elements(self):
        self.compare('''a=[]
s=set()
d={}
print(a,len(a),bool(a),sum(a),any(a),all(a))
print(len(s),len(d),1 in s,"s" in d,d.get(1),d.get("s",7))
for value in a:
 print(value)
''',("",),check=lambda rust:self.assertRegex(rust,r'native_var_\d+: Vec<NativeEmpty>'))

    def test_field_dependencies_and_function_created_empty_values(self):
        self.compare('''def make():
 return []
def add(n):
 return (n,"item")
a=make()
b=[]
for i in range(int(input())):
 a.append(add(i))
 b.append(a[i])
print(a,b,b.copy())
''')

    def test_empty_containers_inside_specialized_function(self):
        self.compare('''def build(n):
 a=[]
 s=set()
 d={}
 for i in range(n):
  a.append((i,"a"))
  s.add((i,"a"))
  d[(i,"a")]=i
 print(len(s),len(d))
 return a
print(build(int(input())))
''')

    def test_nested_loops_and_break_continue_else_constraints(self):
        self.compare('''a=[]
s=set()
d={}
n=int(input())
for i in range(n):
 for j in range(n):
  if (i+j)%3==0:
   a.append((i,j))
   continue
  s.add((i,j))
  if j==2:
   d[(i,j)]="break"
   break
 else:
  d[(i,-1)]="else"
print(a,len(s),len(d),d.get((0,-1),"missing"))
''')

    def test_finite_loop_headers_and_break_only_result_shape(self):
        self.compare('''x=None
for i in range(int(input())):
 print(x,bool(x))
 if i==3:
  x=("break",i)
  break
 if i%2:
  x="word"
  continue
 x=None
print(x,x is None)
''',release=True)

    def test_while_headers_keep_none_bool_int_string_alternatives(self):
        self.compare('''n=int(input())
i=0
x=None
a=[]
while i<n:
 print(x,bool(x))
 if i%3==0:x="s"
 elif i%3==1:x=False
 else:x=i
 a.append((i,x is None))
 i+=1
print(x,a)
''')

    def test_maybe_unbound_scalar_header_retains_python_errors(self):
        self.compare('''for i in range(int(input())):
 print(value)
 value=None
print(value)
''')

    def test_maybe_unbound_mutable_loop_results_borrow_without_copy(self):
        self.compare('''def f(n):
 for i in range(n):
  a=[]
  a.append((i,"value"))
 print(len(a),a)
f(int(input()))
''')

    def test_scalar_key_literals_share_proved_representation(self):
        self.compare('''n=int(input())
d={True:"first",0:"zero"}
s={"word"}
for i in range(n):
 d[i]="later"
 s.add("word")
for key,item in d.items():
 print(key,item)
print(len(s),len(d),True in d,d.get(1,"missing"))
''')

    def test_none_string_dictionary_values_and_default_join(self):
        self.compare('''d={}
for i in range(int(input())):
 d[(i,True)]=None if i%2 else "word"
print(len(d),d.get((0,True)),d.get((1,True),"missing"))
for key,item in d.items():
 print(key,item,item is None)
''')

    def test_source_input_and_function_effects_execute_once(self):
        self.compare('''def row(n):
 print("row",n)
 return (n,input())
a=[]
for i in range(int(input())):
 a.append(row(i))
print(a,input())
''',("0\nend\n","1\nword\nend\n","3\na\nb\nc\nend\n"))

    def test_independent_random_branch_dictionary_and_set_programs(self):
        rng=random.Random(702813)
        rows=[(rng.randrange(-5,6),rng.randrange(2),rng.choice(('a','b','文字'))) for _ in range(24)]
        source='rows='+repr(rows)+'''\ncounts={}
seen=set()
out=[]
for a,b,word in rows:
 key=(a,bool(b),word)
 if key in seen:
  counts[key]=counts.get(key,0)+1
  continue
 seen.add(key)
 counts[key]=1
 out.append(key)
for key in out:
 print(key,counts[key])
print(len(seen),len(counts))
'''
        self.compare(source,("",),release=True)
