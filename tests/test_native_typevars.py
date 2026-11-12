"""Closed TypeVar factories preserve validation, distinct names and effects."""
import shutil
import typing
import unittest
import tempfile
from pathlib import Path
import test_native_class_iterators as helpers

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_typing_metadata import semantic_key


CASES={
 'factory_display':'from typing import TypeVar\nprint(TypeVar,repr(TypeVar),bool(TypeVar),isinstance(1,TypeVar),isinstance(TypeVar,TypeVar))\n',
 'annotations':'from typing import TypeVar\nT=TypeVar("T")\ndef identity(x:T)->T:return x\nprint(identity(3),identity("x"))\n',
 'saved_factory':'import typing\nfactory=typing.TypeVar\nT=factory(name="T",bound=int,default=42)\ndef plus(x:T):return x+1\nprint(plus(7))\n',
 'constraint_defaults':'from typing import TypeVar,cast,Tuple\nT=TypeVar("T",int,str,covariant=True)\nU=TypeVar("U",bound=T,default=T)\nprint(cast(Tuple[T,U],(3,"x")))\n',
 'distinct_same_names':'from typing import TypeVar,Tuple,cast\nT=TypeVar("T")\nU=TypeVar("T")\nAlias=Tuple[T,U]\nprint(cast(Alias[int,str],(3,"x")))\n',
 'same_parameter_repeated':'from typing import TypeVar,Tuple,cast\nT=TypeVar("T")\nAlias=Tuple[T,T]\nprint(cast(Alias[int,str],(3,"x")))\n',
 'distinct_in_branches':'from typing import TypeVar,Tuple,cast\nT=TypeVar("T")\nU=TypeVar("T")\nif int(input()):\n Alias=Tuple[T,T]\nelse:\n Alias=Tuple[T,U]\nprint(cast(Alias[int,str],(3,"x")))\n',
 'constraint_effects':'from typing import TypeVar\ndef note(tag,value):\n print(tag,end="|")\n return value\nT=TypeVar("T",note("first",int),note("second",str))\nprint("done")\n',
 'validation_after_effects':'from typing import TypeVar\ndef note(tag,value):\n print(tag,end="|")\n return value\nT=TypeVar(note("name",int),note("constraint",str),bound=note("bound",int))\nprint("late")\n',
 'binding_after_effects':'from typing import TypeVar\ndef note(tag,value):\n print(tag,end="|")\n return value\nT=TypeVar("T",name=note("duplicate",int))\nprint("late")\n',
 'single_constraint':'from typing import TypeVar\nprint("before")\nT=TypeVar("T",int)\nprint("late")\n',
 'constraint_and_bound':'from typing import TypeVar\nT=TypeVar("T",int,str,bound=int)\nprint("late")\n',
 'bad_variance':'from typing import TypeVar\nT=TypeVar("T",covariant=True,contravariant=True)\nprint("late")\n',
 'missing_name':'from typing import TypeVar\nT=TypeVar()\nprint("late")\n',
 'unexpected_keyword':'from typing import TypeVar\nT=TypeVar("T",unexpected=1)\nprint("late")\n',
 'shadowed_factory':'from typing import TypeVar\nsaved=TypeVar\ndef TypeVar(name):\n print(name)\n return 9\nT=saved("T")\nprint(TypeVar("ordinary"))\n',
}


class TypeVarProtocolTests(unittest.TestCase):
    def test_distinct_host_type_variables_have_distinct_semantic_keys(self):
        first=typing.TypeVar('T');second=typing.TypeVar('T')
        self.assertNotEqual(semantic_key(first),semantic_key(second))
        self.assertEqual(semantic_key(first),semantic_key(first))
        self.assertNotEqual(semantic_key(tuple[first,first]),semantic_key(tuple[first,second]))

    def test_deterministic_conversion_and_identity_restrictions(self):
        source=CASES['distinct_same_names']
        first=transpile(source);second=transpile(source)
        self.assertTrue(first.success,first.diagnostics)
        self.assertEqual(first.rust_source,second.rust_source)
        for source in (
            'from typing import TypeVar\ndef make():return TypeVar("T")\nx=make()\n',
            'from typing import TypeVar\nfor i in range(2):T=TypeVar("T")\n',
            'from typing import TypeVar\nvalues=[TypeVar("T") for _ in range(2)]\n',
            'from typing import TypeVar\nT=TypeVar("T")\nprint(T)\n',
            'from typing import TypeVar\nT=TypeVar("T")\nprint(T is T)\n',
            'from typing import TypeVar\nT=TypeVar(input())\n'):
            result=transpile(source)
            self.assertFalse(result.success,source)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('metadata',str(result.diagnostics[0]))

    def test_failed_import_retry_and_expanded_call_guards(self):
        with tempfile.TemporaryDirectory(prefix='pytors-typevar-retry-')as directory:
            folder=Path(directory)
            (folder/'state.py').write_text('saved=[]\ndef save(value):saved.append(value)\n')
            (folder/'factory.py').write_text('from typing import TypeVar\nfrom state import save\nT=TypeVar("T")\nsave(T)\nraise ValueError("retry")\n')
            source='from state import saved\ntry:\n import factory\nexcept ValueError:\n pass\ntry:\n import factory\nexcept ValueError:\n pass\nprint(len(saved))\n'
            result=transpile(source,TranspileOptions(filename=str(folder/'main.py'),module_paths=(folder,)))
            self.assertFalse(result.success)
            # Exception handlers are currently an earlier native boundary;
            # once supported, the TypeVar uniqueness gate must still reject
            # repeated failed module generations instead of merging them.
            self.assertTrue(any(text in str(result.diagnostics[0])for text in
                                ('failed module initialization can be retried','exception-handler routing')))
            (folder/'ordinary.py').write_text('value=3\n')
            source='from typing import TypeVar\nT=TypeVar("T")\ndef load():\n import ordinary\n return ordinary.value\nprint(load())\n'
            result=transpile(source,TranspileOptions(filename=str(folder/'main.py'),module_paths=(folder,)))
            self.assertFalse(result.success)
            self.assertIn('failed module initialization can be retried',str(result.diagnostics[0]))
        for source in ('from typing import TypeVar\nT=TypeVar(name="T",*())\n',
                       'from typing import TypeVar\nvalues=list(map(TypeVar,["T","T"]))\n'):
            result=transpile(source)
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TypeVarExecutionTests(unittest.TestCase):
    cases=CASES
    inputs={'distinct_in_branches':'0\n'}
    check=helpers.IteratorExecutionTests.check

    def test_module_factories_and_aliases(self):
        for name in ('factory_display','annotations','saved_factory','constraint_defaults','distinct_same_names','distinct_in_branches','shadowed_factory'):
            with self.subTest(name=name):self.check(name)

    def test_metadata_resubscription_and_constructor_errors(self):
        for name in ('same_parameter_repeated','single_constraint','constraint_and_bound','bad_variance','missing_name','unexpected_keyword'):
            with self.subTest(name=name):self.check(name)

    def test_argument_evaluation_before_errors(self):
        for name in ('constraint_effects','validation_after_effects','binding_after_effects'):
            with self.subTest(name=name):self.check(name)
