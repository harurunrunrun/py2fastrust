"""Whole programs checked against a per-operation wrapping reference.

Each integer mode shares one AOT driver for static and runtime-compiled source.
The proved scalar/list subset shares one native driver per fixed-width mode.
Every generated Rust source is compiled both with rustc defaults and with -O.
"""

from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native
from wrapping_reference import UnsupportedReference, execute, normalize


def source(text):
    return textwrap.dedent(text).lstrip("\n")


NATIVE_PROGRAMS = [
    source('''
        a=int(input())
        b=int(input())
        doubled=a+a
        if doubled==0:
            divisor=1
        else:
            divisor=doubled
        print(doubled,(a+1)//divisor,doubled<0)
        total=a
        for i in range(7):
            total+=(a*b+i)
            if total<0:
                total=total//3
            else:
                total=total^b
        if total<0:
            print(total,11)
        else:
            print(total,13)
    '''),
    source('''
        a=int(input())
        b=int(input())
        print(a,b,a+b)
        print((a+b)//b,(a+b)%b)
        print(a//-1,a%-1,1//(a+a))
    '''),
    source('''
        a=int(input())
        b=int(input())
        print(a**3,pow(a,5),pow(a,7,97))
        print((a<<7)+(b>>3),~a,abs(a),-a,+b)
        print((18446744073709551617+1)//3)
        print((170141183460469231731687303715884105727+1)//3)
    '''),
    source('''
        a=int(input())
        b=int(input())
        values=[a,b,a+b]
        values[1]+=(a*a+3)
        total=sum(values,a)
        values[0]^=total
        print(values[0],values[1],values[2],total,values[1]//(b|1))
    '''),
]


def random_programs():
    rng = random.Random(20261027)
    programs = []
    for index in range(3):
        multiplier = rng.choice([3, 17, (1 << 63) - 1, (1 << 127) - 1])
        offset = rng.randrange(-23, 24)
        shift = rng.randrange(1, 8)
        selector = rng.randrange(4)
        programs.append(source(f'''
            a=int(input())
            b=int(input())
            total=0
            for i in range({5+index}):
                a=(a*{multiplier}+b+{offset})^(a>>{shift})
                if (a&3)=={selector}:
                    b=(b+b)+(a>>2)
                else:
                    b=(b-a)//3
                total+=(a^b)+i
            print(a,b,total,total<0)
        '''))
    return programs


NATIVE_PROGRAMS += random_programs()
AOT_PROGRAMS = NATIVE_PROGRAMS + [
    source('''
        a=int(input())
        b=int(input())
        value=a
        value="rebound"
        value=[a,b]
        alias=value
        value+=[a+b]
        def outer(initial):
            running=initial
            def update(step):
                nonlocal running
                running+=step
                alias.append(running)
                return running
            return update
        update=outer(a)
        print(update(b),update(a),value is alias,value)
        print(sum(value,a))
    '''),
    source('''
        a=int(input())
        b=int(input())
        events=[]
        values=[[a]]
        saved=values[0]
        def receiver():
            events.append("receiver")
            return values
        def index():
            events.append("index")
            return 0
        def right():
            events.append("right")
            values[0]=[99]
            return [a+b]
        receiver()[index()]+=right()
        print(events,values,saved,values[0] is saved)
        immutable=(saved,)
        try:
            immutable[0]+=[b]
        except TypeError:
            print("store failed after in-place mutation",saved)
        slice=99
        saved[1:]+=[a*b]
        print(saved)
    '''),
    source('''
        a=int(input())
        b=int(input())
        events=[]
        def mark(label,value):
            events.append(label)
            return value
        try:
            result=mark("left",a)//mark("right",a+a)
        except ZeroDivisionError:
            print("zero division")
        print(events)
        events.clear()
        result=(a+a)==0 and mark("zero",11) or mark("other",13)
        ordered=mark("first",a)<mark("second",b)<mark("third",a+b)
        print(result,ordered,events)
        try:
            print(1<<((a+b)%5-2))
        except ValueError:
            print("negative shift")
    '''),
    source('''
        a=int(input())
        b=int(input())
        convert=int
        print(list(map(convert,[str(a),str(b)])))
        print(list(enumerate(["a","b","c"],a)))
        print(divmod(a,-1),pow(a,3),pow(a,5,97),abs(a))
        def values():
            running=a
            for i in range(4):
                running+=b
                yield running
        print(sum(values(),a),sum([True,False,True]))
    '''),
    source('''
        a=int(input())
        b=int(input())
        events=[]
        def holder():
            pass
        holder.counter=a
        def receiver():
            events.append("receiver")
            return holder
        def right():
            events.append("right")
            holder.counter=b
            return a+b
        receiver().counter+=right()
        print(events,holder.counter)
        def arguments(*items,**keywords):
            return sum(items)+sum(keywords.values())
        print(arguments(a,*[b],function=a+b))
    '''),
]


def input_cases(integer):
    bits = {"i64": 64, "i128": 128, "bigint": 128}[integer]
    half = 1 << (bits - 1)
    values = [(0, 1), (1, 0), (half - 1, 1), (half, -1), (-half, -1),
              (half + 1, (1 << bits) - 1), ((1 << bits) + 1, 3),
              (-(1 << bits) - 1, -3), ((1 << (bits + 9)) - 7, half + 5)]
    rng = random.Random(20261027 + bits)
    values += [(rng.getrandbits(bits + 11) * rng.choice([-1, 1]),
                rng.getrandbits(bits + 5) * rng.choice([-1, 1])) for _ in range(5)]
    return [f"{a}\n{b}\n" for a, b in values]


def native_driver():
    branches = ["selector=int(input())\n"]
    for index, program in enumerate(NATIVE_PROGRAMS):
        branches.append(("if" if index == 0 else "elif") + f" selector=={index}:\n")
        branches.append(textwrap.indent(program, "    "))
    return "".join(branches)


def aot_driver():
    lines = ["programs=" + repr(AOT_PROGRAMS) + "\n"]
    for index, program in enumerate(AOT_PROGRAMS):
        lines += [f"def case_{index}():\n", textwrap.indent(program, "    ")]
    lines += ["selector=int(input())\n", "dynamic=int(input())\n",
              "if dynamic:\n    exec(programs[selector],{})\n", "else:\n"]
    for index in range(len(AOT_PROGRAMS)):
        lines.append("    " + ("if" if index == 0 else "elif") + f" selector=={index}: case_{index}()\n")
    return "".join(lines)


class WrappingReferenceTests(unittest.TestCase):
    def test_each_operation_changes_control_flow_and_division_before_output(self):
        program = "a=int(input())\nx=a+1\nprint(x<0,x//3,-x,abs(x))\nprint((a+a)==0)\n"
        self.assertEqual(execute(program, "i64", f"{(1<<63)-1}\n").stdout,
                         "True -3074457345618258603 -9223372036854775808 -9223372036854775808\nFalse\n")
        self.assertEqual(execute(program, "i128", f"{(1<<127)-1}\n").stdout,
                         "True -56713727820156410577229101238628035243 -170141183460469231731687303715884105728 -170141183460469231731687303715884105728\nFalse\n")
        self.assertEqual(execute("print(((2**63-1)+1)//3)", "bigint").stdout,
                         "3074457345618258602\n")
        self.assertIs(normalize(True, "i64"), True)

    def test_augassign_retains_old_value_target_order_and_shared_mutation(self):
        result = execute(source('''
            events=[]
            data=[[1]]
            saved=data[0]
            def receiver(): events.append("receiver"); return data
            def key(): events.append("key"); return 0
            def rhs(): events.append("rhs"); data[0]=[99]; return [2]
            receiver()[key()]+=rhs()
            pair=(saved,)
            try: pair[0]+=[3]
            except TypeError: pass
            slice=99
            saved[1:]+=[4]
            print(events,data,saved,data[0] is saved)
        '''))
        self.assertIsNone(result.exception_type)
        self.assertEqual(result.stdout, "['receiver', 'key', 'rhs'] [[1, 2, 3, 4]] [1, 2, 3, 4] True\n")

    def test_helper_collision_keywords_and_short_circuit_are_not_observable(self):
        result = execute(source('''
            _wrapping_reference_0=3
            _wrapping_reference_1_temp_1=5
            def f(*,function): return function+_wrapping_reference_0
            events=[]
            def mark(value): events.append(value); return value
            print(f(function=7),0 and mark(1),1 or mark(2))
            print(mark(3)<mark(2)<mark(1),events)
        '''))
        self.assertEqual(result.stdout, "10 0 1\nFalse [3, 2]\n")

    def test_integer_builtins_and_lazy_callbacks_follow_the_same_policy(self):
        result = execute(source('''
            convert=int
            print(list(map(convert,["18446744073709551616","9223372036854775808"])))
            print(list(filter(convert,["18446744073709551616","1"])))
            print(list(enumerate([1,2],9223372036854775807)))
            print(sum([9223372036854775807,1]),divmod(-9223372036854775808,-1))
            print(pow(3,9223372036854775807),1<<9223372036854775807)
            values=["18446744073709551616","1"]
            list.sort(values,key=int)
            print(values)
            value=2.0**-100
            print(next(iter(value.as_integer_ratio,None)),float.as_integer_ratio(value))
        '''))
        self.assertIsNone(result.exception_type)
        self.assertEqual(result.stdout,
                         "[0, -9223372036854775808]\n['1']\n[(9223372036854775807, 1), (-9223372036854775808, 2)]\n-9223372036854775808 (-9223372036854775808, 0)\n-6148914691236517205 0\n['18446744073709551616', '1']\n(1, 0) (1, 0)\n")

    def test_nfkc_normalized_binding_and_parameter_names_cannot_hide_helpers(self):
        result = execute(source('''
            _wrapping_reference_０=41
            def calculate(_wrapping_reference_１,/,*,function):
                return _wrapping_reference_１+function
            def _wrapping_reference_２(): return 3
            def outer():
                _wrapping_reference_３=5
                def inner():
                    nonlocal _wrapping_reference_３
                    _wrapping_reference_３+=1
                    return _wrapping_reference_３
                return inner()
            _wrapping_reference_４_temp_１=[7]
            _wrapping_reference_４_temp_１[0]+=1
            print(_wrapping_reference_０+1,calculate(2,function=3),outer(),_wrapping_reference_４_temp_１)
        '''))
        self.assertIsNone(result.exception_type)
        self.assertEqual(result.stdout,"42 5 6 [8]\n")

    def test_rejected_features_are_explicit_even_when_program_catches_errors(self):
        for program in ["import math", "class C: pass", "print(locals())", "exec('x=1')",
                        "x:int=1", "x=t'{1}'", "complex(1)", "frozenset()", "(-1)**0.5",
                        "raise SystemExit(0)", "raise KeyboardInterrupt()",
                        "try: sum([1.0])\nexcept Exception: pass"]:
            with self.subTest(program=program), self.assertRaises(UnsupportedReference):
                execute(program)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class WrappingProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-wrapping-programs-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binaries = {}
        root = Path(cls.directory.name)
        for integer in ("i64", "i128", "bigint"):
            result = transpile(aot_driver(), TranspileOptions(integer=integer, optimize=False))
            if not result.success:
                raise AssertionError("\n".join(map(str, result.diagnostics)))
            if result.backend != "aot":
                raise AssertionError("shared AOT driver must use the general AOT backend")
            sources = {"aot": result.rust_source}
            if integer != "bigint":
                sources["native"] = try_generate_native(native_driver(), "wrapping_native.py", integer)
                if sources["native"] is None:
                    raise AssertionError("the complete native oracle corpus must remain proved")
            for backend, rust in sources.items():
                path = root / f"{backend}_{integer}.rs"
                path.write_text(rust, encoding="utf-8")
                for optimized in (False, True):
                    binary = root / f"{backend}_{integer}_{'release' if optimized else 'debug'}"
                    command = ["rustc", "--edition=2021", str(path), "-o", str(binary)]
                    if optimized:
                        command.append("-O")
                    compiled = subprocess.run(command, capture_output=True, text=True, timeout=180)
                    if compiled.returncode:
                        raise AssertionError(compiled.stderr)
                    cls.binaries[backend, integer, optimized] = binary

    def test_program_corpus_in_static_dynamic_native_and_debug_release(self):
        for integer in ("i64", "i128", "bigint"):
            for index, program in enumerate(AOT_PROGRAMS):
                for data in input_cases(integer):
                    expected = execute(program, integer, data)
                    modes = [("aot", 0), ("aot", 1)]
                    if integer != "bigint" and index < len(NATIVE_PROGRAMS):
                        modes.append(("native", None))
                    for backend, dynamic in modes:
                        outcomes = []
                        for optimized in (False, True):
                            with self.subTest(integer=integer, program=index, data=data,
                                              backend=backend, dynamic=dynamic, optimized=optimized):
                                payload = f"{index}\n" + (f"{dynamic}\n" if dynamic is not None else "") + data
                                actual = subprocess.run([str(self.binaries[backend, integer, optimized])],
                                                        input=payload, capture_output=True, text=True, timeout=10)
                                error = actual.stderr.strip().splitlines()[-1].split(":", 1)[0] if actual.returncode else None
                                self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
                                self.assertEqual(bool(actual.returncode), bool(expected.returncode), actual.stderr)
                                self.assertEqual(error, expected.exception_type, actual.stderr)
                                outcomes.append((actual.returncode, actual.stdout, error))
                        self.assertEqual(outcomes[0], outcomes[1], "rustc debug and -O must agree")


if __name__ == "__main__":
    unittest.main()
