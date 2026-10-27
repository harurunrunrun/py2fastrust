"""Numeric conversion methods, exact rounding, protocols and integer policies."""

import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


FIXTURE = '''
for value in [-32768, -129, -128, -1, 0, 1, 127, 128, 255, 256, 65535]:
    print(value.as_integer_ratio(), value.is_integer())
    for length in [0, 1, 2, 4]:
        for signed in [False, True]:
            for order in ['big', 'little']:
                try:
                    data = value.to_bytes(length, order, signed=signed)
                    print(value, length, signed, order, data,
                          int.from_bytes(data, order, signed=signed))
                except OverflowError:
                    print('overflow', value, length, signed, order)
print((1).to_bytes(), int.from_bytes(b'\\x01'), int.from_bytes([1, 2]),
      int.from_bytes(bytes=b'\\xff', byteorder='little', signed=True))
print((-9223372036854775808).to_bytes(8, 'little', signed=True))
for value in [0.0, -0.0, 0.5, -1.75, 2.0, float('inf'), float('-inf'), float('nan')]:
    print(value.hex(), value.is_integer())
    try: print(value.as_integer_ratio())
    except (ValueError, OverflowError) as error: print(type(error).__name__)
for text in ['0x1p0', '-0', '0x.8', '+1.fp-3', '0x1.fffffffffffffp+1023',
             '0x1p-1074', '0x1p-1075', '0x1.0000000000001p-1075', 'inf', '-nan']:
    print(float.fromhex(text).hex())
print(float.from_number(3), float.from_number(True),
      int.to_bytes(257, 2), float.hex(1.75), float.as_integer_ratio(0.5))
'''


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class NumericMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='pytors-numeric-methods-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.driver = cls.build('import sys\nexec(sys.stdin.read())\n', 'driver', 'bigint')

    @classmethod
    def build(cls, source, name, integer, release=False):
        result = transpile(source, TranspileOptions(integer=integer, optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        target = cls.root / (name + '.rs')
        target.write_text(result.rust_source, encoding='utf-8')
        binary = cls.root / name
        built = subprocess.run(['rustc', '--edition=2021', *(['-O'] if release else []),
                                str(target), '-o', str(binary)], capture_output=True, timeout=240)
        if built.returncode:
            raise AssertionError(built.stderr.decode(errors='replace'))
        return binary

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, '-I', '-'], input=source, capture_output=True,
                                  text=True, timeout=30)
        actual = subprocess.run([str(self.driver)], input=source, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_bytes_boundaries_and_binary_float_methods(self):
        self.compare(FIXTURE)

    def test_conversion_protocol_order_defaults_and_integer_subclass_construction(self):
        self.compare('''
            import gc
            events=[]
            class Index:
                def __index__(self):events.append('index');gc.collect();return 2
            class Flag:
                def __bool__(self):events.append('signed');gc.collect();return True
            print((-1).to_bytes(Index(), signed=Flag()),events)
            class Source:
                def __iter__(self):events.append('iter');return iter([1,2])
                def __len__(self):events.append('len');return 2
                def __index__(self):raise AssertionError('not an allocation size')
            events.clear();print(int.from_bytes(Source()),events)
            class Converted:
                def __bytes__(self):events.append('bytes');gc.collect();return b'\\x03'
                def __iter__(self):raise AssertionError('must not iterate')
            events.clear();print(int.from_bytes(Converted()),events)
            class Integer(int):
                def __new__(cls,value):events.append(('new',value));return int.__new__(cls,value+1)
                def __init__(self,value):events.append(('init',value))
            events.clear();value=Integer.from_bytes(b'\\x05')
            print(type(value).__name__,value,events)
            value.to_bytes=lambda:'shadow'
            print(value.to_bytes())
            class Real:
                def __float__(self):events.append('float');return 1.25
            events.clear();print(float.from_number(Real()),events)
            class Text(str):
                def __float__(self):events.append('text float');return 3.25
            class IndexedText(str):
                def __index__(self):events.append('text index');return 7
            events.clear();print(float.from_number(Text('ignored')),
                                 float.from_number(IndexedText('ignored')),events)
        ''')

    def test_rejected_arguments_and_nonfinite_ratio_errors(self):
        self.compare('''
            class PlainText(str):pass
            actions=[lambda:(1).to_bytes(-1),lambda:(1).to_bytes(1,'bad'),
                     lambda:(1).to_bytes(1,None),lambda:(1).to_bytes(1,'big',True),
                     lambda:(1).to_bytes(1,length=2),lambda:int.from_bytes(3),
                     lambda:int.from_bytes(b'1','big',True),lambda:int.from_bytes([256]),
                     lambda:int.from_bytes([-1]),lambda:int.from_bytes([1.5]),
                     lambda:float.hex(1),lambda:float.as_integer_ratio(1),
                     lambda:float.from_number('1'),lambda:float.from_number(PlainText('1.25')),
                     lambda:float.fromhex(1),
                     lambda:float.fromhex(string='1'),lambda:float.fromhex('1__0'),
                     lambda:float.fromhex('0x1p99999999999999999999999999999999')]
            for action in actions:
                try:action()
                except Exception as error:print(type(error).__name__)
                else:print('accepted')
            class Bad:
                def __bytes__(self):return 3
            try:int.from_bytes(Bad())
            except TypeError:print('bad bytes')
        ''')

    def test_float_subclass_protocol_results_and_stringlike_numeric_overrides(self):
        self.compare('''
            import math,gc
            class Float(float):pass
            class Converted:
                def __float__(self):gc.collect();return Float(2.25)
            print(float.from_number(Converted()),math.sqrt(Converted()))
            class Bytes(bytes):
                def __float__(self):return 3.25
            print(float.from_number(Bytes(b'ignored')))
            value=Float(1.75)
            print(value.hex(),value.as_integer_ratio(),value.is_integer())
            value.hex=lambda:'shadow'
            print(value.hex())
            class Derived(float):
                def __new__(cls,value):
                    print('new',value.hex())
                    return float.__new__(cls,value)
                def __init__(self,value):print('init',value.hex())
            print(type(Derived.fromhex('0x1.8p1')).__name__)
            print(type(Derived.from_number(3)).__name__)
        ''')

    def test_bigint_byte_roundtrips_and_exact_binary_ratios(self):
        self.compare('''
            for value in [2**127, -(2**127), 2**521-1, -(2**521), 10**300]:
                for order in ['big','little']:
                    data=value.to_bytes(200, order, signed=True)
                    print(int.from_bytes(data, order, signed=True)==value)
            for value in [5e-324, -5e-324, 1e-300, 1e100, float.fromhex('0x1.fffffffffffffp1023')]:
                print(value.as_integer_ratio())
                print(float.fromhex(value.hex()).hex()==value.hex())
        ''')

    def test_random_hex_rounding_and_very_long_input(self):
        rng = random.Random(90179)
        samples = []
        for _ in range(240):
            digits = ''.join(rng.choice('0123456789abcdef') for _ in range(rng.randrange(1, 80)))
            split = rng.randrange(len(digits) + 1)
            samples.append(rng.choice(['', '-']) + '0x' + digits[:split] + '.' + digits[split:]
                           + 'p' + str(rng.randrange(-1400, 1200)))
        samples += ['0x1.' + '0' * 100_000 + '1p0', '0x1.' + '0' * 13 + '8' + '0' * 100_000 + '1p0',
                    '0x1p-999999999999999999999999999999999999', '-0x0p99999999999999999999999999999999999']
        self.compare('for source in ' + repr(samples) + ''':
 try: print(float.fromhex(source).hex())
 except (ValueError, OverflowError) as error: print(type(error).__name__)
''')

    def test_aot_dynamic_and_all_standalone_integer_build_modes(self):
        prefix = FIXTURE + '\nexec(' + repr(FIXTURE) + ', {})\n'
        for integer in ['i64', 'i128', 'bigint']:
            width = {'i64': 64, 'i128': 128, 'bigint': 0}[integer]
            minimum = -(1 << ((width or 128) - 1))
            byte_count = (width or 128) // 8
            wide = ("print(int.from_bytes(bytes([255]*20)), (1e100).as_integer_ratio(), "
                    f"(5e-324).as_integer_ratio(), ({minimum}).to_bytes({byte_count}, signed=True))\n")
            def norm(value):
                return (value + 2**(width-1)) % 2**width - 2**(width-1) if width else value
            values = (norm(int.from_bytes(b'\xff'*20)),
                      tuple(map(norm, (1e100).as_integer_ratio())),
                      tuple(map(norm, (5e-324).as_integer_ratio())),
                      minimum.to_bytes(byte_count, signed=True))
            expected = subprocess.run([sys.executable, '-I', '-c', prefix + 'print(*' + repr(values) + ')'],
                                      capture_output=True, timeout=30)
            self.assertEqual(expected.returncode, 0, expected.stderr)
            for release in [False, True]:
                with self.subTest(integer=integer, release=release):
                    binary = self.build(prefix + wide, integer + str(release), integer, release)
                    actual = subprocess.run([str(binary)], capture_output=True, timeout=30,
                                            env={**os.environ, 'PATH': str(self.root / 'no-executables')})
                    self.assertEqual(actual.returncode, 0, actual.stderr.decode(errors='replace'))
                    self.assertEqual(actual.stdout, expected.stdout, actual.stderr.decode(errors='replace'))
