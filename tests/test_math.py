"""CPython 3.14 differential coverage for the standalone Rust math module."""
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile, TranspileOptions


def bits(value):
    return int.from_bytes(struct.pack(">d", value), "big")


def normalize(value, mode):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and mode != "bigint":
        width = 64 if mode == "i64" else 128
        value %= 1 << width
        return value if value < 1 << (width - 1) else value - (1 << width)
    if isinstance(value, tuple):
        return tuple(normalize(item, mode) for item in value)
    return value


def rust_value(value):
    if value is None:
        return "Value::None"
    if isinstance(value, bool):
        return f"Value::Bool({str(value).lower()})"
    if isinstance(value, int):
        return f'Value::Int(Int::parse("{value}",10).unwrap().into())'
    if isinstance(value, float):
        return f"Value::Float(f64::from_bits({bits(value)}u64).into())"
    if isinstance(value, (tuple, list)):
        variant = "Tuple" if isinstance(value, tuple) else "List"
        return f"Value::Obj(rt.alloc(Object::{variant}(vec![{','.join(map(rust_value, value))}])))"
    if isinstance(value, str):
        return 'Value::Str(' + repr(value).replace("'", '"') + '.into())'
    raise TypeError(type(value))


RENDER = r'''
fn math_test_render(rt: &Runtime, value: &Value) -> String {
    match value {
        Value::Int(n) => format!("i{}",n),
        Value::Bool(b) => format!("b{}",u8::from(*b)),
        Value::Float(x) => format!("f{:016x}",x.to_bits()),
        Value::Str(s) => format!("s{}",s),
        Value::None => "none".to_string(),
        Value::Obj(i) => match rt.heap[*i].as_ref().unwrap() {
            Object::Tuple(values) => format!("t[{}]",values.iter().map(|v|math_test_render(rt,v)).collect::<Vec<_>>().join(",")),
            _ => "object".to_string(),
        },
        _ => "other".to_string(),
    }
}
'''


def decode(text):
    if text.startswith("t["):
        return tuple(decode(item) for item in text[2:-1].split(","))
    if text.startswith("i"):
        return int(text[1:])
    if text.startswith("b"):
        return text[1:] == "1"
    if text.startswith("f"):
        return struct.unpack(">d", int(text[1:], 16).to_bytes(8, "big"))[0]
    if text.startswith("s"):
        return text[1:]
    return text


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class MathTests(unittest.TestCase):
    def check_cases(self, cases, mode="bigint", relative=2e-14):
        base = transpile("", TranspileOptions(integer=mode, optimize=False)).rust_source
        base = base.replace("fn main() {", "fn unused_program_main() {", 1)
        commands, expected = [], []
        for name, args, kwargs in cases:
            command = '{ let args=vec![' + ",".join(map(rust_value, args)) + ']; let kwargs=vec!['
            command += ",".join(f'(rt.static_keyword("{key}".to_string()),{rust_value(value)})' for key, value in kwargs.items())
            command += f']; match rt.math_call("{name}",args,kwargs) {{ Ok(v)=>println!("{{}}",math_test_render(&rt,&v)), Err(e)=>println!("ERR:{{}}",e.kind) }} }}'
            commands.append(command)
            try:
                result = getattr(math, name)(*args, **kwargs)
                expected.append(normalize(result, mode))
            except Exception as error:
                expected.append("ERR:" + type(error).__name__)
        source = base + RENDER + '\nfn main(){let mut rt=Runtime::new(Vec::new(),Vec::new());\n' + "\n".join(commands) + "\n}"
        with tempfile.TemporaryDirectory(prefix="py2fastrust-math-") as td:
            path = Path(td) / "main.rs"
            path.write_text(source)
            target = path.with_suffix("")
            result = subprocess.run(["rustc", "--edition=2021", "-O", str(path), "-o", str(target)], text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(target)], text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), len(cases), result.stderr)
        for case, actual, want in zip(cases, lines, expected):
            got = actual if actual.startswith("ERR:") else decode(actual)
            self.compare(got, want, case, relative)

    def compare(self, got, want, case, relative):
        if isinstance(want, tuple):
            self.assertIsInstance(got, tuple, case)
            self.assertEqual(len(got), len(want), case)
            for x, y in zip(got, want):
                self.compare(x, y, case, relative)
        elif isinstance(want, float):
            self.assertIsInstance(got, float, case)
            if math.isnan(want):
                self.assertTrue(math.isnan(got), case)
            elif case[0] in {"copysign", "frexp", "modf", "ulp", "nextafter", "ldexp", "remainder", "fmod", "fsum", "fma"}:
                self.assertEqual(bits(got), bits(want), (case, got, want))
            elif math.isinf(want) or want == 0.0:
                self.assertEqual(bits(got), bits(want), case)
            else:
                self.assertLessEqual(abs(got - want), max(abs(want) * relative, math.ulp(want) * 8), (case, got, want))
        else:
            self.assertEqual(got, want, case)

    def test_all_public_functions(self):
        examples = {
            "acos":(.25,), "acosh":(2.,), "asin":(.25,), "asinh":(-2.,), "atan":(.5,), "atan2":(-2.,3.), "atanh":(.25,),
            "cbrt":(-27.,), "ceil":(-1.2,), "comb":(80,35), "copysign":(1.,-0.), "cos":(.5,), "cosh":(.5,), "degrees":(.5,),
            "dist":([1.,2.,3.],[4.,5.,6.]), "erf":(.5,), "erfc":(3.,), "exp":(.5,), "exp2":(3.5,), "expm1":(1e-15,),
            "fabs":(-2.,), "factorial":(50,), "floor":(-1.2,), "fma":(1e20,1e20,-1e40), "fmod":(-8.,3.), "frexp":(1e-310,),
            "fsum":([1e16,1.,-1e16],), "gamma":(.5,), "gcd":(-12,18,30), "hypot":(3.,4.,12.), "isclose":(1.,1.0000000001),
            "isfinite":(math.inf,), "isinf":(-math.inf,), "isnan":(math.nan,), "isqrt":(10**50+1,), "lcm":(12,18,30), "ldexp":(.5,100),
            "lgamma":(.5,), "log":(8.,2.), "log10":(1000.,), "log1p":(1e-15,), "log2":(8.,), "modf":(-1.25,), "nextafter":(1.,2.),
            "perm":(30,20), "pow":(2.,3.5), "prod":([1,2,3,4],), "radians":(45.,), "remainder":(7.,2.), "sin":(.5,), "sinh":(.5,),
            "sqrt":(2.,), "sumprod":([1.,2.,3.],[4.,5.,6.]), "tan":(.5,), "tanh":(.5,), "trunc":(-1.8,), "ulp":(1.,),
        }
        expected = {name for name in dir(math) if not name.startswith("_") and callable(getattr(math, name))}
        self.assertEqual(set(examples), expected)
        self.check_cases([(name, args, {}) for name, args in examples.items()])

    def test_special_functions_precision(self):
        rng = random.Random(20261027)
        points = [-200.5,-170.5,-50.25,-10.5,-3.5,-1.5,-.5,-1e-20,1e-20,.1,.5,1.,1.5,2.,5.,20.,100.,170.,171.5]
        points += [rng.uniform(-170,171) for _ in range(100)]
        cases = [(name,(point,),{}) for name in ("gamma","lgamma") for point in points]
        error_points = [-30.,-10.,-3.,-1.5,-1.,-1e-20,-0.,0.,1e-20,1.,1.5,3.,10.,26.,27.,30.]
        error_points += [rng.uniform(-10,10) for _ in range(100)]
        cases += [(name,(point,),{}) for name in ("erf","erfc") for point in error_points]
        self.check_cases(cases, relative=1e-14)

    def test_nan_infinity_signed_zero_and_domains(self):
        cases=[]
        unary = ("sqrt","sin","cos","tan","asin","acos","acosh","asinh","atanh","sinh","cosh","tanh","exp","exp2","expm1","log","log2","log10","log1p","gamma","lgamma","erf","erfc","frexp","modf","ulp","ceil","floor","trunc","fabs","cbrt")
        for name in unary:
            for value in (-math.inf,-2.,-1.,-0.,0.,1.,2.,math.inf,math.nan):
                cases.append((name,(value,),{}))
        for name in ("atan2","copysign","fmod","remainder","pow"):
            for a in (-math.inf,-1.,-0.,0.,1.,math.inf,math.nan):
                for b in (-math.inf,-1.,-0.,0.,1.,math.inf,math.nan):
                    cases.append((name,(a,b),{}))
        cases += [("fma",args,{}) for args in ((0.,math.inf,math.nan),(0.,math.inf,1.),(1e308,2.,1.),(math.inf,1.,-math.inf))]
        cases += [("fsum",(values,),{}) for values in ([math.inf,-math.inf],[math.nan,math.inf,-math.inf],[1e308,1e308],[-0.,-0.])]
        cases += [("hypot",(math.inf,math.nan),{}),("hypot",(),{}),("dist",([],[]),{})]
        self.check_cases(cases)

    def test_float_bits_and_accurate_aggregates(self):
        rng=random.Random(4321)
        cases=[]
        for _ in range(100):
            x=struct.unpack(">d",rng.getrandbits(64).to_bytes(8,"big"))[0]
            y=struct.unpack(">d",rng.getrandbits(64).to_bytes(8,"big"))[0]
            cases += [("frexp",(x,),{}),("modf",(x,),{}),("ulp",(x,),{}),("ldexp",(x,rng.randrange(-2200,2200)),{}),("nextafter",(x,y),{"steps":rng.choice((0,1,2,100,1<<64))})]
        for x,y in ((0.,-0.),(-0.,0.),(5e-324,-5e-324),(-5e-324,5e-324)):
            for steps in (0,1,2,3):cases.append(("nextafter",(x,y),{"steps":steps}))
        cases += [("fsum",(v,),{}) for v in ([1e16,1.,-1e16],[1e-16,1.,1e16],[-1.,1.,-0.],[1e100,1.,-1e100,1.])]
        cases += [("sumprod",(a,b),{}) for a,b in (([1e16,1.,-1e16],[1.,1.,1.]),([1e308,1e308,-1e308],[1.,1.,1.]),([1e308,1e308],[1e308,-1e308]),([1,2],[3,4]),([],[]))]
        cases += [("hypot",(3e200,4e200,12e200),{}),("hypot",(3e-200,4e-200),{}),("log",(10**1000,),{}),("log2",(1<<10000,),{}),("log10",(10**1000,),{})]
        self.check_cases(cases)

    def test_integer_algorithms_final_width_normalization(self):
        for mode in ("i64","i128","bigint"):
            cases=[("comb",(100,50),{}),("perm",(100,30),{}),("factorial",(100,),{}),("lcm",(1000000007,1000000009,1000000033),{}),("isqrt",((1<<62)-1,),{}),("gcd",(),{}),("lcm",(),{}),("perm",(10,None),{})]
            self.check_cases(cases,mode)

    def test_bad_arguments(self):
        cases=[("comb",(3,None),{}),("factorial",(3.,),{}),("isqrt",(-1,),{}),("gcd",(1,2.),{}),("lcm",(0,2.),{}),("comb",(-1,0),{}),("perm",(3,-1),{}),("isclose",(1.,2.),{"rel_tol":-1.}),("nextafter",(0.,1.),{"steps":-1}),("nextafter",(0.,1.),{"steps":1.5}),("ldexp",(1.,2.),{}),("sqrt",(),{}),("sin",(1.,2.),{}),("sqrt",(1.,),{"x":1.}),("sumprod",([1],[1,2]),{}),("dist",([1],[1,2]),{})]
        self.check_cases(cases)

    def test_module_dispatch_and_special_conversion_methods(self):
        source='''import math
class Rounded:
 def __floor__(self): return 7
 def __ceil__(self): return 8
 def __trunc__(self): return 9
class Real:
 def __float__(self): return 4.0
print(math.floor(Rounded()),math.ceil(Rounded()),math.trunc(Rounded()))
print(math.sqrt(Real()),math.comb(20,5),math.isclose(1.,1.00001,rel_tol=.001))
print(math.frexp(8.),math.modf(-1.25),math.nextafter(0.,1.,steps=2))
'''
        result=transpile(source,TranspileOptions(optimize=False))
        self.assertTrue(result.success,result.diagnostics)
        with tempfile.TemporaryDirectory(prefix="py2fastrust-math-e2e-") as td:
            p=Path(td)/"main.rs";p.write_text(result.rust_source)
            built=subprocess.run(["rustc","--edition=2021",str(p),"-o",str(p.with_suffix(""))],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            got=subprocess.run([str(p.with_suffix(""))],capture_output=True,text=True,timeout=10)
        expected=subprocess.run([sys.executable,"-c",source],capture_output=True,text=True)
        self.assertEqual(got.returncode,expected.returncode,got.stderr)
        self.assertEqual(got.stdout,expected.stdout)

    def test_generator_conversions_survive_explicit_collection(self):
        source='''import math
import gc
class Real:
 def __float__(self):
  gc.collect()
  return 1.0
def reals():
 for i in range(100):
  yield Real()
print(math.fsum(reals()))
print(math.dist(reals(),reals()))
print(math.hypot(Real(),Real()))
'''
        result=transpile(source,TranspileOptions(optimize=False))
        self.assertTrue(result.success,result.diagnostics)
        with tempfile.TemporaryDirectory(prefix="py2fastrust-math-gc-") as td:
            p=Path(td)/"main.rs";p.write_text(result.rust_source)
            built=subprocess.run(["rustc","--edition=2021",str(p),"-o",str(p.with_suffix(""))],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            got=subprocess.run([str(p.with_suffix(""))],capture_output=True,text=True,timeout=15)
        expected=subprocess.run([sys.executable,"-c",source],capture_output=True,text=True)
        self.assertEqual(got.returncode,expected.returncode,got.stderr)
        self.assertEqual(got.stdout,expected.stdout)


if __name__ == "__main__":
    unittest.main()
