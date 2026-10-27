"""Cell comparisons use contents, preserve rich results, and suspend callbacks."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys,gc\nexec(sys.stdin.read())\n"
# Obtain ordinary cells through the class-creation protocol so this regression
# can also run on the phase-3 branch before the public CellType factory merge.
FACTORY = '''
def make_cell(value=...):
    cells=[]
    class Meta(type):
        def __new__(meta,name,bases,namespace):
            cells.append(namespace.pop('__classcell__'))
            return type.__new__(meta,name,bases,namespace)
    try:
        class C(metaclass=Meta):
            def method(self):return __class__
    except RuntimeError:
        pass
    cell=cells[0]
    if value is not ...:cell.cell_contents=value
    return cell
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc required")
class ProtocolCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-cell-protocol-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        build = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise AssertionError(build.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = FACTORY + textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=40)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=40)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_empty_filled_ordering_and_same_nan_contents(self):
        self.compare('''
            cells=[make_cell(),make_cell(1),make_cell(2)]
            for a in cells:
                for b in cells:
                    print(a==b,a!=b,a<b,a<=b,a>b,a>=b)
            a=make_cell(float('nan'))
            print(a==a,a!=a,a<a,a<=a,a>a,a>=a)
            for op in ['==','!=','<']:
                try:print(op,eval('cells[0]'+op+'3'))
                except TypeError:print(op,'TypeError')
        ''')

    def test_rich_results_callbacks_and_collection_comparisons(self):
        self.compare('''
            result=['rich result']
            events=[]
            class Value:
                def __eq__(self,other):events.append('eq');gc.collect();return result
                def __lt__(self,other):events.append('lt');gc.collect();return result
            value=Value();a=make_cell(value);b=make_cell(value)
            print((a==b)is result,(a<b)is result,events)
            print([make_cell(1)]==[make_cell(1)],(make_cell(1),)<(make_cell(2),))
            class Error:
                def __eq__(self,other):raise LookupError('cell callback')
            try:make_cell(Error())==make_cell(2)
            except LookupError as error:print(str(error))
        ''')

    def test_cycles_and_python_callback_recursion_use_heap_scheduler(self):
        self.compare('''
            a=make_cell();b=make_cell();a.cell_contents=a;b.cell_contents=b
            for operation in [lambda:a==b,lambda:a<b]:
                try:operation()
                except RecursionError:print('native cycle caught')
            class Recursive:
                def __eq__(self,other):return left==right
            left=make_cell(Recursive());right=make_cell(Recursive())
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                try:left==right
                except RecursionError:print(limit,'callback caught')
            calls=[]
            class Finite:
                def __eq__(self,other):
                    calls.append(1)
                    if len(calls)==4:return 'finished'
                    return left==right
            left.cell_contents=Finite();right.cell_contents=Finite()
            print(left==right,len(calls))
        ''')
