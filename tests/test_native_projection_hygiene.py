"""Finite-value projections keep distinct operands in nested typed matches."""
import shutil
import unittest

from py2fastrust.native import _Unsupported
from py2fastrust.native_types import NullableType,union_type
from py2fastrust.native_unions import project
from tests import test_native_finite_unions as support


class ProjectionContextTests(unittest.TestCase):
    def test_distinct_operands_and_context_restored_after_unsupported(self):
        kind=NullableType(union_type("int","str"))
        pairs=[]
        def pair(a,x,b,y):
            pairs.append((a,x,b,y))
            return f"({x})==({y})"
        def render():
            return project(kind,"left",lambda a,x:project(kind,"right",lambda b,y:pair(a,x,b,y)))
        before=render()
        for a,x,b,y in pairs:
            if a!="none"and b!="none":self.assertNotEqual(x,y)
        def unsupported(kind,code):raise _Unsupported
        with self.assertRaises(_Unsupported):
            project(kind,"value",unsupported)
        self.assertEqual(render(),before)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ProjectionParityTests(unittest.TestCase):
    compare=support.FiniteUnionTests.compare

    def test_unequal_nullable_scalar_payloads(self):
        self.compare('''def pick(n):
 if n:return n+4
 return None
a=pick(int(input()))
b=pick(int(input()))
print(a,b,a==b,a!=b,a==a,b==b)
''',("1\n2\n","1\n1\n","0\n1\n","1\n0\n","0\n0\n"))

    def test_unequal_finite_scalar_payloads(self):
        self.compare('''def pick(n):
 if n%2:return str(n)
 return n+1
a=pick(int(input()))
b=pick(int(input()))
print(a,b,a==b,a!=b,a==a,b==b)
''',("1\n3\n","2\n4\n","1\n1\n","1\n2\n","2\n1\n"))

    def test_unequal_nested_tuple_payloads(self):
        self.compare('''def row(n):
 if n:return (n+4,"x")
 return (None,3)
a=row(int(input()))
b=row(int(input()))
print(a,b,a==b,a!=b,a==a,b==b)
''',("1\n2\n","1\n1\n","0\n1\n","1\n0\n","0\n0\n"))

    def test_nullable_tuple_and_finite_fields(self):
        self.compare('''def pick(n):
 if n%3==0:return (n+1,None)
 if n%3==1:return (str(n),())
 return None
a=pick(int(input()))
b=pick(int(input()))
print(a,b,a==b,a!=b,a==a,b==b)
''',("0\n3\n","1\n4\n","0\n1\n","2\n1\n","2\n2\n"))


if __name__=="__main__":unittest.main()
