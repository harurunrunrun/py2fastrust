"""No-license selection omits its text and preserves source/third-party notices."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.settings import LICENSES,license_name


class NoLicenseTests(unittest.TestCase):
    def test_aliases_and_separate_unlicense_choice(self):
        for name in ('none','NONE','None','no-license','no_license'):
            self.assertEqual(license_name(name),'NONE')
            result=transpile('print(7)\n',TranspileOptions(license=name))
            self.assertTrue(result.success,result.diagnostics)
            self.assertTrue(result.rust_source.startswith('// LICENSE: NONE\n'))
            self.assertIn('// No license is added for the translated program logic.\n',result.rust_source)
            self.assertNotIn('Creative Commons Legal Code',result.rust_source)
            self.assertNotIn('This is free and unencumbered software',result.rust_source)
        self.assertIn('NONE',LICENSES)
        self.assertEqual(license_name('Unlicense'),'Unlicense')
        self.assertTrue(transpile('print(7)\n').rust_source.startswith('// LICENSE: CC0-1.0\n'))

    def test_existing_source_license_and_inert_original_are_preserved(self):
        source='# SPDX-License-Identifier: MIT\n# /* inert */\nprint(7)\n'
        result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn('// If the original Python source specifies a license, that license takes precedence.\n',result.rust_source)
        for line in source.splitlines():self.assertIn('// '+line+'\n',result.rust_source)

    def test_source_directive_overrides_cli_and_api(self):
        source='# pytors: --license none\nprint(7)\n'
        result=transpile(source,TranspileOptions(license='MIT'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(result.rust_source.startswith('// LICENSE: NONE\n'))
        with tempfile.TemporaryDirectory(prefix='pytors-no-license-cli-')as directory:
            entry=Path(directory)/'main.py';entry.write_text(source)
            output=Path(directory)/'main.rs'
            cli=subprocess.run([sys.executable,'-m','py2fastrust',str(entry),'-o',str(output),'--license','MIT'],capture_output=True,text=True,timeout=30)
            self.assertEqual((cli.returncode,cli.stdout,cli.stderr),(0,'',''))
            self.assertTrue(output.read_text().startswith('// LICENSE: NONE\n'))

    def test_unicode_option_alone_does_not_add_notice_but_data_tables_do(self):
        for source,notice in [('print("猫"[0])\n',False),('word=input()\nprint(word.isalpha())\n',True)]:
            result=transpile(source,TranspileOptions(license='none',string_mode='unicode'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertTrue(result.rust_source.startswith('// LICENSE: NONE\n'))
            self.assertEqual('UNICODE LICENSE V3'in result.rust_source,notice)

    @unittest.skipUnless(shutil.which('rustc'),'rustc is required')
    def test_all_integer_modes_keep_the_same_standalone_program(self):
        source='a,b=map(int,input().split())\nprint(a+b)\n'
        with tempfile.TemporaryDirectory(prefix='pytors-no-license-rust-')as directory:
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode,license='none'))
                other=transpile(source,TranspileOptions(integer=mode,license='CC0-1.0'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertTrue(other.success,other.diagnostics)
                self.assertEqual(result.rust_source.split('\n#![',1)[1],other.rust_source.split('\n#![',1)[1])
                path=Path(directory)/(mode+'.rs');path.write_text(result.rust_source)
                for release in(False,True):
                    binary=path.with_name(mode+str(release))
                    build=subprocess.run(['rustc','--crate-name','no_license','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    actual=subprocess.run([str(binary)],input='2 7\n',capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(0,'9\n',''))
