"""Official Python PEG CST lowering without a secondary syntax parser."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = '''\
import sys
def static_twice(value):
    return value * 2
source = sys.stdin.read()
exec(source)
if "dynamic_result" in globals():
    print(static_twice(dynamic_result))
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class CstLowerTests(unittest.TestCase):
    maxDiff = None
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-cst-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="cst_wrapper.py"))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(
            ["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=120,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run(
            [sys.executable, "-I", "-c", WRAPPER], input=source,
            capture_output=True, text=True, timeout=15,
        )
        actual = subprocess.run(
            [str(self.binary)], input=source, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(
                actual.stderr.strip().splitlines()[-1].split(":")[0],
                expected.stderr.strip().splitlines()[-1].split(":")[0],
            )
        return actual

    def test_expression_precedence_tuple_grouping_slices_and_yields(self):
        expressions = [
            '1 + 2 * 3 ** 2', '-2 ** 2', '2 ** -2', '10 - 3 - 2',
            '32 >> 1 + 1', '3 | 4 & 2 ^ 1', 'not 1 < 2', '1 < 2 <= 3 != 4',
            '1 is not None', '1 not in [2, 3]', '0 or 2 and 4',
            '1 if 0 else 2 if 1 else 3', '()', '(1)', '(1,)', '1,2,3',
            '[1, *range(2), 3]', 'sorted({1, *range(2)})', '{1:2, **{3:4}}',
            '[0,1,2,3,4][::2]', '[0,1,2,3,4][1:4:2]',
            '(lambda a, /, b=2, *, c=3: (a,b,c))(1,c=4)',
            '(lambda *args, **kw: (args,kw))(*(1,2), key=3)',
        ]
        self.compare('expressions='+repr(expressions)+'\nfor text in expressions:\n print(eval(text))\n')
        self.compare('''
            def generator():
                value = yield 1
                yield from [value, 3]
            iterator = generator()
            print(next(iterator), iterator.send(8), next(iterator))
            print([value for value in range(5) if value if value > 1])
            print({key:value for key in range(3) for value in [key+1]})
            print(sum(value for value in range(4)))
        ''')

    def test_target_forms_annotations_and_argument_evaluation(self):
        self.compare('''
            class C:
                pass
            item = C()
            array = [0, 1, 2, 3]
            (a, *b), item.value = [1, 2, 3], 4
            array[1:3] = b
            item.value += 2
            del array[::2], item.value
            print(a, b, array, hasattr(item,"value"))
            class Index:
                def __getitem__(self, key):
                    print(key)
                    return 9
            index = Index()
            index[1,], index[()], index[1:2, ...], index[*[1,2]]
            events = []
            def mark(label, value):
                events.append(label)
                return value
            def fn(*args, **kwargs):
                return args, kwargs
            print(fn(key=mark("keyword",1), *mark("star",[2])))
            print(fn(mark("argument",3), **mark("mapping",{"extra":4})))
            print(events)
            x: int
            (y): str
            class Typed:
                first: int
                if True:
                    second: list[int]
            print(__annotate__(1), Typed.__annotations__)
        ''')

    def test_definitions_parameters_decorators_and_type_parameter_syntax(self):
        self.compare('''
            events=[]
            def decorate(fn):
                events.append(fn.__name__)
                return fn
            @decorate
            def fn(a: int, b=2, /, c=3, *items: tuple[int], key, other=4, **kwargs: dict[str,int])->tuple:
                return a,b,c,items,key,other,kwargs
            print(fn(1,5,6,7,key=8,extra=9), fn.__annotations__, events)
            type Alias[T: (int,str) = int, *Ts = *tuple[str,bytes]] = tuple[T,*Ts]
            print(Alias.__type_params__, Alias.__value__)
            class Generic[T]:
                field:T
            print(Generic.__annotations__)
        ''')

    def test_match_patterns_namespaces_and_control_flow(self):
        self.compare('''
            class Point:
                __match_args__=("x","y")
                def __init__(self,x,y):
                    self.x,self.y=x,y
            def match(value):
                match value:
                    case {"x": x, **rest} if x:
                        return "mapping", x, rest
                    case Point(1, y=other):
                        return "class", other
                    case [1|2, *tail] as whole:
                        return "sequence", tail, whole
                    case -3:
                        return "literal"
                    case _:
                        return "default"
            for value in [{"x":4,"y":5}, Point(1,7), [2,3,4], -3, 8]:
                print(match(value))
            for number in range(3):
                try:
                    if number == 0:
                        continue
                    if number == 2:
                        break
                finally:
                    print("finally",number)
            try:
                raise ExceptionGroup("g",[ValueError("v"),TypeError("t")])
            except* ValueError as caught:
                print(caught.message)
            except* TypeError:
                print("type")
        ''')

    def test_future_flags_single_mode_and_formatted_fields(self):
        self.compare(r'''
            import __future__
            namespace={}
            exec(compile("from __future__ import annotations\ndef fn(x: Missing): pass", "future.py", "exec"), namespace)
            print(namespace["fn"].__annotations__)
            flags=__future__.barry_as_FLUFL.compiler_flag
            print(eval(compile("1 <> 2", "future.py", "eval", flags)))
            exec(compile("1+2", "interactive.py", "single"))
            value=4
            print(f"\x7b1\x7d:{value=:5}")
            template=t"{ value = :>{2}}"
            print(template.strings, template.interpolations[0].expression,
                  template.interpolations[0].conversion, template.interpolations[0].format_spec)
            print(t"{(lambda x:x+1)(value)}".values)
        ''')

    def test_complex_literal_patterns_and_duplicate_key_validation(self):
        self.compare(r'''
            def classify(value):
                match value:
                    case -2j:
                        return "negative imaginary"
                    case 1+2j:
                        return "positive"
                    case -1-2j:
                        return "negative"
                    case {1+2j: bound}:
                        return "mapping", bound
                    case _:
                        return "other"
            for value in [-2j, 1+2j, -1-2j, {1+2j:3}, 4j]:
                print(classify(value))
            sources = [
                "match {}:\n case {1+0j:x,1:y}:pass",
                "match {}:\n case {1+2j:x,1.0+2.0j:y}:pass",
                "match {}:\n case {-0j:x,0:y}:pass",
            ]
            for source in sources:
                try:
                    compile(source, "duplicate.py", "exec")
                except SyntaxError:
                    print("duplicate")
                else:
                    print("accepted")
        ''')

    def test_syntax_error_subclasses_come_from_the_official_token_stream(self):
        sources = [" x=1\n", "if True:\npass\n", "def f():\n",
                   "if True:\n\tpass\n        pass\n", "x=1+\n"]
        self.compare("sources=" + repr(sources) + '''
for source in sources:
 try:
  compile(source,"indent.py","exec")
 except SyntaxError as error:
  print(type(error).__name__)
 else:
  print("accepted")
''')

    def test_semantic_validation_for_targets_and_definition_bindings(self):
        sources = [
            '__debug__=1', 'del __debug__', 'object.__debug__=1', 'del object.__debug__',
            '(a,__debug__)=1,2', '(object.__debug__:=1)',
            'def fn(__debug__): pass', 'def __debug__(): pass', 'class __debug__:pass',
            'import sys as __debug__', 'from sys import argv as __debug__',
            'type __debug__=int', 'type Alias[__debug__]=int',
            'match 1:\n case __debug__: pass',
            'match [1,2]:\n case [x,x]:pass',
            'match {}:\n case {1:x, True:y}:pass',
            '[1 for __debug__ in []]', '(lambda **__debug__:0)',
            'fn(x=1,x=2)', 'a,*b,*c=[1,2,3]',
            'from __future__ import imaginary_feature',
        ]
        self.compare('sources='+repr(sources)+'''\nfor source in sources:
 try:
  compile(source,"invalid.py","exec")
 except (SyntaxError,ValueError):
  print("invalid")
 else:
  print("accepted")
''')
