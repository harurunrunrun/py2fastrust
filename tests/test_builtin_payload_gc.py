"""A live built-in subclass retains its native payload during collection."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class BuiltinPayloadGCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-payload-gc-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile("import sys\nexec(sys.stdin.read())\n", TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = root / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = root / "main"
        built = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True,
                                  text=True, timeout=20)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_collection_during_mapping_and_sequence_protocols(self):
        self.compare('''
            import gc
            class Items(list):
                def __getitem__(self,key):
                    gc.collect()
                    return super().__getitem__(key)
                def __setitem__(self,key,value):
                    gc.collect()
                    return super().__setitem__(key,value)
                def __iter__(self):
                    gc.collect()
                    return super().__iter__()
            class Mapping(dict):
                def __getitem__(self,key):
                    gc.collect()
                    return super().__getitem__(key)
                def __setitem__(self,key,value):
                    gc.collect()
                    return super().__setitem__(key,value)
            values=Items([['a'],['b']])
            print(values[0])
            values[1]=['c']
            print(list(values),len(values))
            mapping=Mapping({'x':['first']})
            print(mapping['x'])
            mapping['y']=['second']
            print(mapping['x'],mapping['y'],len(mapping))
        ''')

    def test_scalar_subclasses_and_inherited_payloads(self):
        self.compare('''
            import gc
            class Text(str):
                def __getitem__(self,key):
                    gc.collect()
                    return super().__getitem__(key)
                def measure(self):
                    gc.collect()
                    return len(self)
            class MoreText(Text):pass
            class Number(int):
                def measure(self):
                    gc.collect()
                    return int(self)+3
            class MoreNumber(Number):pass
            for cls in [Text,MoreText]:
                value=cls('abc')
                print(value[1],value.measure(),str(value),len(value))
            for cls in [Number,MoreNumber]:
                value=cls(17)
                print(value.measure(),int(value),value+1)
        ''')

    def test_native_container_members_remain_alive_until_the_owner_dies(self):
        self.compare('''
            import gc
            events=[]
            class Token:
                def __del__(self):events.append('deleted')
            for base in [list,tuple,dict,set,frozenset]:
                class Holder(base):pass
                if base is dict:value=Holder({'member':Token()})
                else:value=Holder([Token()])
                gc.collect()
                print(base.__name__,events)
                del value
                gc.collect()
                print(events)
                events.clear()
        ''')
