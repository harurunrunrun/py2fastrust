"""Native complex values use Python's constructors, operations and protocols."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
import test_runtime


WRAPPER = '''\
import sys
literal_values = (0j, 1j, -2j, 3+4j, 1e2J)
def aot_multiply(a, b):
    return a*b
exec(sys.stdin.read())
'''


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ComplexTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-complex-")
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(filename="complex_wrapper.py", optimize=False))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        target = directory / "main.rs"
        target.write_text(result.rust_source, encoding="utf-8")
        cls.binary = directory / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=15)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(actual.returncode, expected.returncode, actual.stderr + expected.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)
        if expected.returncode:
            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                             expected.stderr.strip().splitlines()[-1].split(":")[0])

    def test_literals_metadata_identity_components_and_unary_operators(self):
        self.compare('''
            print(literal_values, complex, complex.__name__, complex.__module__)
            value = 3+4j
            alias = value
            print(type(value) is complex, isinstance(value, complex), bool(value), bool(0j))
            print(value.real, value.imag, value.conjugate(), value.__getnewargs__())
            print(+value, -value, abs(value), +value is value,
                  complex(value) is value, value.conjugate() is value,
                  value.__complex__() is value, value.real is value.real)
            print(aot_multiply(value, 2j), alias is value)
            for name in ['real', 'imag', 'other']:
                try: setattr(value, name, 1)
                except AttributeError as error: print(type(error).__name__)
            print(value.__add__('x') is NotImplemented,
                  value.__eq__('x') is NotImplemented)
            print(complex.conjugate(value),complex.__complex__(value) is value,
                  complex.__pow__(value,2,None),pow(value,2,None),
                  pow(exp=2,base=value))
            try:complex.__add__(1,2j)
            except TypeError as error:print(type(error).__name__)
        ''')

    def test_string_constructor_unicode_whitespace_exponents_and_underscores(self):
        self.compare(r'''
            strings = ['0', '-0', 'j', '+j', '-j', '1j', '1+2j', '1-2j',
                       '  ( 1e2-2e-3J )  ', '1_000.25+2_000j',
                       '\u2003\u0661.\u0662+\uff13j\u2003',
                       'nan', '-nan', 'inf', '-Infinity', 'nan-infj', '+inf+nanj',
                       '1e999j', '-1e-999j']
            for source in strings:
                print(repr(complex(source)))
            invalid = ['', ' ', '()', '((1))', '1 +2j', '1+ 2j', '1 + 2j',
                       '1j+2', '0x10', '1__0j', '_1j', '1_j', '1e+_2j',
                       'nan_', '1+2jj', '(1+2j', '1+2j)', '\x001j']
            for source in invalid:
                try: complex(source)
                except ValueError as error: print(type(error).__name__)
            for call in [lambda:complex(b'1'), lambda:complex('1', 2),
                         lambda:complex(1, '2'), lambda:complex(real='1'),
                         lambda:complex(number=1), lambda:complex(1, real=2),
                         lambda:complex(1, 2, 3)]:
                try: call()
                except TypeError as error: print(type(error).__name__)
        ''')

    def test_conversion_protocol_order_return_validation_and_gc(self):
        self.compare('''
            import gc
            events=[]
            class Number:
                def __complex__(self):
                    events.append('complex')
                    gc.collect()
                    return 1+2j
                def __float__(self):
                    events.append('float')
                    return 5.0
                def __index__(self):
                    events.append('index')
                    return 7
            number=Number()
            print(complex(number), events)
            events.clear()
            print(complex(number, number), events)
            class Floating:
                def __float__(self):return 2.5
            class Indexed:
                def __index__(self):return 9
            class Text(str):
                def __complex__(self):raise RuntimeError('must parse string')
            print(complex(Floating()),complex(Indexed()),complex(Text('3+4j')))
            print(complex.from_number(Floating()),complex.from_number(Indexed()),
                  complex.from_number(1j) is 1j)
            for value in ['1',b'1']:
                try:complex.from_number(value)
                except TypeError as error:print(type(error).__name__)
            class BadComplex:
                def __complex__(self):return 1.0
            class BadFloat:
                def __float__(self):return 1
            class BadIndex:
                def __index__(self):return 1.5
            for value in [BadComplex(),BadFloat(),BadIndex(),None,[],{}]:
                try: complex(value)
                except TypeError as error:print(type(error).__name__)
            class Raised:
                def __complex__(self):raise ValueError('conversion')
            try:complex(Raised())
            except ValueError as error:print(str(error))
        ''')

    def test_mixed_arithmetic_and_signed_zero(self):
        self.compare('''
            for left in [1+2j,-3+4j,complex(-0.,-0.),2,2.5,True]:
                for right in [1-2j,complex(0.,-0.),3,-1.5,False]:
                    print(left+right,left-right,left*right)
                    try:print(left/right)
                    except ZeroDivisionError:print('zero')
            z=complex(-0.,-0.)
            print(z+0,0+z,z-0,0-z,z*1,1*z,z/1,z+complex(0,0),z-complex(0,0))
            value=1+2j
            value+=3
            value*=2j
            value/=2
            value-=1j
            print(value)
        ''')

    def test_power_small_integer_polar_zero_and_overflow(self):
        self.compare('''
            def rounded(value):return format(value.real,'.12g'),format(value.imag,'.12g')
            for value in [1j,1+2j,-1+0j,complex(-1,-0.),complex(-0.,-0.)]:
                for exponent in [0,1,2,3,-1,99,100,101,0.5,1+1j]:
                    try:print(rounded(value**exponent))
                    except (ZeroDivisionError,OverflowError) as error:print(type(error).__name__)
            for value in [0j,1j,2+3j]:
                print(value**0j)
            print(rounded((-1.0)**0.5))
            try:(1e308+1e308j)**2
            except OverflowError as error:print(type(error).__name__)
            try:pow(1j,2,3)
            except ValueError as error:print(type(error).__name__)
            for value in [0j,complex(float('inf'),0),complex(0,float('inf')),
                          complex(float('nan'),0),complex(float('inf'),float('nan'))]:
                for exponent in [float('nan'),float('inf'),float('-inf'),0.5,1,2,-1,-2,101,1j]:
                    try:print(repr(value**exponent))
                    except (ZeroDivisionError,OverflowError) as error:print(type(error).__name__)
            for value in [-1.0,float('-inf')]:
                for exponent in [float('nan'),float('inf'),float('-inf'),0.5]:
                    print(type(value**exponent).__name__)
        ''')

    def test_repr_and_format_signed_zero_nan_inf_and_grouping(self):
        self.compare('''
            values=[0j,1j,1+2j,complex(-0.,-0.),12.5+3000.2j,
                    complex(float('inf'),float('nan')),complex(-float('nan'),-0.)]
            specifications=['','20','+',' ','.2','#','z','0>20','020','=20',
                            '.0','.2f','+.2f',',.2f','_','g','G','n','%',
                            '*^30','>.3e','z.2f','#.3g']
            for value in values:
                print(repr(value),str(value),value.__repr__(),value.__str__())
                for specification in specifications:
                    try:print(repr(format(value,specification)))
                    except ValueError as error:print(type(error).__name__)
            print(f"{1+2j!s:>20}",f"{1+2j:.3f}")
        ''')

    def test_infinite_arithmetic_and_magnitudes(self):
        self.compare('''
            inf=float('inf')
            nan=float('nan')
            values=[complex(0.,-0.),1+2j,complex(inf,0),complex(0,inf),
                    complex(inf,inf),complex(nan,2),complex(2,nan)]
            for left in values:
                for right in values:
                    try:print(left*right,left/right)
                    except ZeroDivisionError:print('zero')
                print(abs(left))
            print((1e308+1e308j)/(1e308+1e308j))
            print((1e308+1e308j)/(1e-308+1e-308j))
            try:abs(1.7e308+1.7e308j)
            except OverflowError as error:print(type(error).__name__)
        ''')

    def test_equality_order_errors_numeric_hashes_and_container_keys(self):
        self.compare('''
            for value in [0j,1+0j,-1+0j,1.5+0j,2+3j,complex(float('inf'),0)]:
                print(value==value,value==value.real,value!=value.real,hash(value))
            print(hash(1+0j)==hash(1)==hash(1.0),hash(1.5+0j)==hash(1.5))
            print(hash(-1),hash(-1.0),hash(2.5),hash(float('inf')),hash(float('-inf')))
            print([hash(number) for number in [1e20,-1e20,1e-300,-1e-300,
                                               5e-324,2.2250738585072014e-308]])
            d={1:'integer',1+0j:'complex',1.0:'float'}
            print(len(d),d[1],list(d))
            print(len({0,0j,0.0,False}),[1+0j]==[1],(1+0j,) in {(1,):2})
            value=complex(float('nan'),1)
            print(value==value,hash(value)==hash(value),value in {value:'present'})
            for call in [lambda:(1j<2),lambda:(1j<=1j),lambda:int(1j),
                         lambda:float(1j),lambda:round(1j),lambda:1j//2,
                         lambda:1j%2,lambda:1j&2,lambda:len(1j),lambda:iter(1j)]:
                try:call()
                except TypeError as error:print(type(error).__name__)
        ''')

    def test_subclasses_descriptors_new_overrides_and_reflected_operators(self):
        self.compare('''
            import gc
            events=[]
            class Number(complex):
                def __new__(cls,real=0,imag=0):
                    result=super().__new__(cls,real,imag)
                    result.label='number'
                    return result
                def __init__(self,real=0,imag=0):self.arguments=(real,imag)
                def __radd__(self,other):
                    events.append('reflected')
                    return 'override'
            value=Number(3,4)
            print(type(value).__name__,isinstance(value,complex),value.real,value.imag,
                  value.label,value.arguments,value.__dict__)
            print(value+1,1+value,events,abs(value),bool(value),value.conjugate())
            print(type(+value).__name__,type(complex(value)).__name__,
                  complex(value) is value,hash(value)==hash(3+4j),
                  (+value) is (+value),
                  complex.__complex__(value) is complex.__complex__(value))
            gc.collect()
            print(value.real,value.label,value*2)
            class Converted(Number):
                def __complex__(self):return 7+8j
            print(complex(Converted(1,2)))
            converted=Number.from_number(5)
            print(type(converted).__name__,converted.arguments,converted.label)
            print(type(value.from_number(7)).__name__)
            class Slot(complex):__slots__=('tag',)
            item=Slot(1,2)
            item.tag='slot'
            print(item.tag,hasattr(item,'__dict__'))
        ''')

    def test_complex_literal_patterns(self):
        self.compare('''
            def classify(value):
                match value:
                    case 1j:return 'imaginary'
                    case -2j:return 'negative imaginary'
                    case 3+4j:return 'sum'
                    case -3-4j:return 'negative components'
                    case _:return 'other'
            print([classify(value) for value in [1j,-2j,3+4j,-3-4j,0]])
            match 5+6j:
                case complex(real=real,imag=imag):print(real,imag)
        ''')


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ComplexBigIntTests(unittest.TestCase):
    run_source=test_runtime.RuntimeTests.run_source

    def test_large_integer_rounding_equality_hashing_and_overflow(self):
        self.run_source('''
            numbers=[0,1,-1,2**53+1,2**61-1,2**61,2**127+123,2**1023]
            for number in numbers:
                value=complex(number)
                print(value,value==number,hash(number),hash(complex(float(number),0)))
            for number in [2**1024,-2**1024]:
                try:complex(number)
                except OverflowError as error:print(type(error).__name__)
            print(complex(1,2)+(2**53+1),complex(2**1023,1).real)
        ''',integer='bigint')

    def test_fixed_width_literal_patterns_match_normalized_real_components(self):
        literal=18446744073709551617
        source=f'''
value={literal}+2j
def classify(value):
    match value:
        case {literal}+2j:return 'hit'
        case _:return 'miss'
print(value.real,classify(value))
namespace={{}}
exec("value={literal}+2j\\ndef classify(value):\\n match value:\\n  case {literal}+2j:return 'hit'\\n  case _:return 'miss'\\n",namespace)
print(namespace['value'].real,namespace['classify'](namespace['value']))
'''
        for integer in ['i64','i128','bigint']:
            with self.subTest(integer=integer),tempfile.TemporaryDirectory(prefix='py2fastrust-complex-mode-') as name:
                directory=Path(name)
                result=transpile(source,TranspileOptions(integer=integer,optimize=False))
                self.assertTrue(result.success,'\n'.join(map(str,result.diagnostics)))
                target=directory/'main.rs'
                target.write_text(result.rust_source,encoding='utf-8')
                built=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(directory/'main')],capture_output=True,text=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(directory/'main')],capture_output=True,text=True,timeout=15)
                self.assertEqual(actual.returncode,0,actual.stderr)
                normalized=(literal+2**63)%2**64-2**63 if integer=='i64' else literal
                self.assertEqual(actual.stdout,f'{float(normalized)!r} hit\n'*2)
