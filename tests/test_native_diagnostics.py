"""Native failures explain the rejected operation and its missing implementation."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native import _Unsupported,_direct_diagnostic,_Expression
from py2fastrust.native_diagnostics import kind_name
from py2fastrust.native_types import ListType,NullableType,TupleType


class NativeDiagnosticTests(unittest.TestCase):
    def reject(self,source,mode="i64"):
        with patch('py2fastrust.codegen.generate',side_effect=AssertionError('general execution backend')):
            result=transpile(source,TranspileOptions(integer=mode,filename='solution.py'))
        self.assertFalse(result.success,result.rust_source)
        self.assertIsNone(result.rust_source)
        self.assertEqual(len(result.diagnostics),1)
        diagnostic=result.diagnostics[0]
        self.assertEqual((diagnostic.filename,diagnostic.code),('solution.py','E006'))
        self.assertGreaterEqual(diagnostic.line,1)
        self.assertGreaterEqual(diagnostic.column,1)
        self.assertIn('Cannot lower ',diagnostic.message)
        self.assertIn('Source:',diagnostic.message)
        self.assertNotIn('construct or type combination',diagnostic.message)
        self.assertNotRegex(diagnostic.message,r'\((?:Call|Compare|ListComp)\)$')
        return diagnostic

    def test_concrete_signature_default_and_closure_causes(self):
        sources=(
            ('def f(*items):return sum(items)\nprint(f(1))\n',('signature','items','packing','tuple')),
            ('def f(**items):return 1\nprint(f(a=1))\n',('signature','items','packing','dictionary')),
            ('def f(x=[]):return len(x)\nprint(f())\n',('default','shared mutable','definition-time','identity')),
            ('def f(x=input()):return x\nprint(f())\n',('default','definition-time','effects/exceptions','capture')),
            ('def outer(x):\n def inner():return x\n return inner\nf=outer(3)\nprint(f())\n',('nested function','inner','closure','lifetime')),
            ('def outer(x):\n def inner():return x\n return inner\nprint(outer(3)())\n',("call 'outer(3)'",'computed callee','callable-object/closure')),
        )
        for mode in ('i64','i128','bigint'):
            for source,tokens in sources:
                with self.subTest(mode=mode,source=source):
                    with patch('builtins.input',side_effect=AssertionError('submitted input executed')):
                        diagnostic=self.reject(source,mode)
                    for token in tokens:self.assertIn(token,diagnostic.message)

    def test_argument_binding_errors_are_not_reported_as_unsupported_call_syntax(self):
        source='def f(x):return x\nprint(f(1,2))\n'
        diagnostic=self.reject(source)
        self.assertEqual((diagnostic.line,diagnostic.column),(2,7))
        self.assertIn("call 'f'",diagnostic.message)
        self.assertIn('argument binding is invalid',diagnostic.message)
        self.assertIn('too many positional arguments',diagnostic.message)
        self.assertIn('Python TypeError',diagnostic.message)
        self.assertIn('argument 1=int',diagnostic.message)
        expanded=self.reject('def f(x):return x\nprint(f(*[1]))\n')
        self.assertIn('positional iterator expansion',expanded.message)
        self.assertIn('syntax itself is valid',expanded.message)
        self.assertNotIn('argument binding is invalid',expanded.message)
        syntax=transpile('def f(x):return x\nf(x=1,x=2)\n')
        self.assertFalse(syntax.success)
        self.assertEqual(syntax.diagnostics[0].code,'E001')

    def test_named_member_cause_and_implemented_bigint_deque(self):
        diagnostic=self.reject('s=input()\nprint(s.replace("a","b"))\n')
        self.assertEqual((diagnostic.line,diagnostic.column),(2,7))
        self.assertIn("call 's.replace'",diagnostic.message)
        self.assertIn('receiver=str',diagnostic.message)
        self.assertIn('adapter',diagnostic.message)
        supported=transpile('from collections import deque\nq=deque([1])\nprint(q)\n',TranspileOptions(integer='bigint'))
        self.assertTrue(supported.success,supported.diagnostics)
        self.assertEqual(supported.backend,'native')

    def positive(self,source):
        import test_native_union_ordering as helpers
        class Check(helpers.NativeUnionOrderingTests):pass
        Check.setUpClass()
        try:Check().exercise(source,("",))
        finally:Check.tearDownClass()

    def test_shared_aliases_and_unproved_expression_storage_are_distinct(self):
        source='values=[1]\nalias=values\nalias.append(2)\nprint(values)\n'
        self.positive(source)
        expression=self.reject('n=int(input())\nx=[1] if n else None\nprint(x)\n')
        self.assertIn('conditional expression',expression.message)
        self.assertIn('mutable branch',expression.message)
        self.assertIn('alternative 1=list[int]',expression.message)
        self.assertIn('alternative 2=None',expression.message)

    def test_comprehension_context_reports_element_shape_and_selected_class_path(self):
        forms=(
            ('{1 for i in range(n)}','set comprehension','set[int]'),
            ('{i:[] for i in range(n)}','dictionary comprehension','dict[unresolved, list[unresolved element]]'),
            ('(i for i in range(n))','generator expression','iterator[unresolved]'),
        )
        for expression,label,shape in forms:
            source='class Item:pass\nn=3\nvalues='+expression+'\n'
            for mode in ('i64','i128','bigint'):
                with self.subTest(expression=expression,mode=mode):
                    diagnostic=self.reject(source,mode)
                    self.assertEqual((diagnostic.line,diagnostic.column),(3,8))
                    self.assertIn(label,diagnostic.message)
                    self.assertIn('class-aware',diagnostic.message)
                    self.assertIn('no comprehension scope/iteration/materialization',diagnostic.message)
                    self.assertIn(shape,diagnostic.message)
                    self.assertIn('allocated element',diagnostic.message)

    def test_sequence_failures_name_iteration_conversion_and_borrow_proofs(self):
        cases=(
            ('xs=[1]\nxs.extend((2,3))\nprint(xs)\n',('list.extend','other iterable','iterable=tuple[int, int]','ordered iterable consumption')),
            ('xs=[1,2]\nfor x in xs:\n xs.append(3)\n',('sequence \'xs\'','active iteration/read','receiver=list[int]','alias-preserving mutation')),
            ('xs=[1]\nprint(xs.pop("0"))\n',("call 'xs.pop'",'__index__','index/bound=str','TypeError')),
        )
        for source,tokens in cases:
            with self.subTest(source=source):
                diagnostic=self.reject(source)
                for token in tokens:self.assertIn(token,diagnostic.message)
        for statement in ('xs[0]=2','xs.append(2)'):
            source='def f(xs):\n '+statement+'\n return 0\nxs=[1]\nprint(f(xs))\n'
            self.positive(source)

    def test_class_path_names_first_class_function_value_capture_boundary(self):
        diagnostic=self.reject('class Item:pass\ndef score(x):return x\nxs=[2,1]\nxs.sort(key=score)\n')
        self.assertEqual((diagnostic.line,diagnostic.column),(4,13))
        self.assertIn("name 'score'",diagnostic.message)
        self.assertIn('first-class value',diagnostic.message)
        self.assertIn('callable/class-object identity',diagnostic.message)

    def test_type_context_is_bounded_without_resolving_or_mutating_types(self):
        self.assertEqual(kind_name(TupleType(('int',)*30)),'tuple[int, int, int, int, int, int, ...]')
        from py2fastrust.native_classes import Cell
        child=Cell('int');parent=Cell('str');child.parent=parent
        self.assertEqual(kind_name(child),'str')
        self.assertIs(child.parent,parent)
        instance=Cell('object',('Example',))
        self.assertEqual(kind_name(instance),'Example')
        self.assertEqual(kind_name(Cell('list',(instance,))),'list[Example]')

    def test_class_truth_override_names_the_missing_special_method_protocol(self):
        for method,body in (('__bool__','False'),('__len__','0')):
            source=f'class Flag:\n def {method}(self):return {body}\nflag=Flag()\nif flag:print(1)\n'
            diagnostic=self.reject(source)
            self.assertIn('Flag.'+method,diagnostic.message)
            self.assertIn('truth-value protocol dispatch',diagnostic.message)
            self.assertIn(method,diagnostic.message)

    def test_finite_ordering_guard_explains_the_actual_required_comparator(self):
        from py2fastrust.native_comparisons import ordering
        source='left < right\n';node=ast.parse(source).body[0].value
        cases=(
            (64,ListType('int'),ListType('int'),'mutable-container/alternative ordering','list[int]'),
            (64,TupleType(('float',)),TupleType(('float',)),'identity-aware equality','tuple[float]'),
            (0,'int','float','arbitrary-precision-integer/binary64','right=float'),
        )
        for bits,left,right,reason,kind in cases:
            with self.subTest(left=left,right=right):
                with self.assertRaises(_Unsupported)as caught:
                    ordering(SimpleNamespace(bits=bits),_Expression('left',left),_Expression('right',right),ast.Lt(),node)
                diagnostic=_direct_diagnostic(source,'compare.py',caught.exception)
                self.assertEqual((diagnostic.line,diagnostic.column),(1,1))
                self.assertIn(reason,diagnostic.message)
                self.assertIn(kind,diagnostic.message)
                self.assertIn('Required proof:',diagnostic.message)
                self.assertIn("Source: 'left < right'",diagnostic.message)

    def test_exception_metadata_is_optional_and_legacy_subclasses_keep_their_node(self):
        source='1 + "x"\n';node=ast.parse(source).body[0].value
        class LegacyUnsupported(_Unsupported):
            def __init__(self,node):self.node=node
        diagnostic=_direct_diagnostic(source,'legacy.py',LegacyUnsupported(node))
        self.assertEqual((diagnostic.line,diagnostic.column),(1,1))
        self.assertIn("operator '+'",diagnostic.message)
        self.assertIn('left=int',diagnostic.message)
        self.assertIn('right=str',diagnostic.message)
        explicit=_Unsupported('the required protocol has no native adapter',node=node,
                              operation='custom key equality',types=(('key',NullableType(ListType(TupleType(('int','str'))))),),
                              proof='hash/equality behavior')
        diagnostic=_direct_diagnostic(source,'explicit.py',explicit)
        self.assertIn('custom key equality',diagnostic.message)
        self.assertIn('key=list[tuple[int, str]] | None',diagnostic.message)
        self.assertIn('Required proof: hash/equality behavior',diagnostic.message)
        positional=_Unsupported(node)
        self.assertIs(positional.node,node)
        self.assertIsNone(positional.reason)
        self.assertEqual(positional.args,(node,))
        positioned=_direct_diagnostic(source,'positional.py',positional)
        self.assertIn("operator '+'",positioned.message)
        self.assertEqual(kind_name(None),'unresolved')

    def test_formatting_never_executes_the_submitted_source(self):
        with tempfile.TemporaryDirectory(prefix='pytors-diagnostic-effects-')as directory:
            marker=Path(directory,'executed')
            source=f'@__import__("pathlib").Path({str(marker)!r}).write_text("bad")\ndef f():return 1\nprint(f())\n'
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertFalse(marker.exists())

    def test_cli_failure_contains_the_same_specific_reason_and_location(self):
        with tempfile.TemporaryDirectory(prefix='pytors-diagnostic-cli-')as directory:
            source=Path(directory,'main.py');source.write_text('def f(x=[]):return len(x)\nprint(f())\n')
            target=Path(directory,'main.rs')
            command=[sys.executable,'-m','py2fastrust',str(source),'-o',str(target)]
            actual=subprocess.run(command,capture_output=True,text=True,timeout=10)
            expected=transpile(source.read_text(),TranspileOptions(filename=str(source)))
            self.assertEqual(actual.returncode,2,actual.stderr)
            self.assertEqual(actual.stdout,'')
            self.assertEqual(actual.stderr,str(expected.diagnostics[0])+'\n')
            self.assertIn('shared mutable object',actual.stderr)
            self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
