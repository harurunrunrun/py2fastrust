"""Unicode 16 literal names, aliases, algorithmic names, and dynamic strings."""

import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
import unittest

from py2fastrust import TranspileOptions, transpile


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = r'''import sys
AOT_VALUE = '\N{SNOWMAN}'
def aot_join(value):return AOT_VALUE+value
exec(sys.stdin.read())
'''


def alias_names():
    result = []
    for line in (ROOT / 'py2fastrust/unicode/NameAliases-16.0.0.txt').read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            result.append(line.split(';')[1])
    return result


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class UnicodeNameDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='pytors-names-data-')
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        source = 'use std::io::{self,BufRead};\n'
        for name in ['unicode_names_tables.rs', 'unicode_names.rs']:
            source += 'include!('+json.dumps(str(ROOT/'py2fastrust/runtime'/name))+');\n'
        source += '''fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();match unicode_character_name(&line){Some(value)=>println!("{:X}",value as u32),None=>println!("-")}}}
'''
        rust = root/'main.rs'
        rust.write_text(source)
        cls.binary = root/'main'
        build = subprocess.run(['rustc', '--edition=2021', '-O', str(rust), '-o', str(cls.binary)], capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise AssertionError(build.stderr)

    def check_names(self, names):
        actual = subprocess.run([str(self.binary)], input='\n'.join(names)+'\n', capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        expected = []
        for name in names:
            try:
                value = unicodedata.lookup(name)
                expected.append(f'{ord(value):X}' if len(value)==1 else '-')
            except KeyError:
                expected.append('-')
        self.assertEqual(actual.stdout.splitlines(), expected)

    def test_every_canonical_name_alias_and_tangut_lookup(self):
        names = [name for point in range(sys.maxunicode+1) if (name:=unicodedata.name(chr(point), ''))]
        names += alias_names()
        names += [f'TANGUT IDEOGRAPH-{point:X}' for point in range(0x17000,0x18D80)]
        self.check_names(names)

    def test_invalid_names_near_algorithmic_ranges_and_spelling(self):
        names = ['HANGUL SYLLABLE G', 'HANGUL SYLLABLE A', 'HANGUL SYLLABLE HIH',
                 'KEYCAP DIGIT ONE', 'NULL', 'SNOWMAN', ' LATIN CAPITAL LETTER A',
                 'LATIN  CAPITAL LETTER A', 'LATIN CAPITAL LETTER a', 'latin capital letter a',
                 'LATIN CAPITAL LETTER ſ', 'CJK_UNIFIED IDEOGRAPH-4E00']
        for prefix, points in [('CJK UNIFIED IDEOGRAPH',[0x33FF,0x3400,0x4DBF,0x4DC0,0x9FFF,0xA000,0x3134A,0x3134B,0x31350,0x323AF,0x323B0]),
                               ('CJK COMPATIBILITY IDEOGRAPH',[0xF8FF,0xF900,0xFAFF,0xFB00]),
                               ('TANGUT IDEOGRAPH',[0x16FFF,0x17000,0x187F7,0x187F8,0x18D00,0x18D08,0x18D09]),
                               ('NUSHU CHARACTER',[0x1B16F,0x1B170,0x1B2FB,0x1B2FC]),
                               ('KHITAN SMALL SCRIPT CHARACTER',[0x18AFF,0x18B00,0x18CD5,0x18CD6]),
                               ('EGYPTIAN HIEROGLYPH',[0x1345F,0x13460,0x143FA,0x143FB])]:
            for point in points:
                for spelling in [f'{point:X}',f'0{point:X}',f'+{point:X}',f'{point:x}']:
                    names.append(prefix+'-'+spelling)
        self.check_names(names)


class UnicodeNameGeneratorTests(unittest.TestCase):
    def test_generated_data_are_reproducible_and_alias_source_pinned(self):
        checked = subprocess.run([sys.executable, str(ROOT/'tools/generate_unicode_names.py'), '--check'], capture_output=True, text=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stderr)
