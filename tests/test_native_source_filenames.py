"""Diagnostic filename pooling preserves values, reachability and source scopes."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import transpile,TranspileOptions
from py2fastrust.native import _string
from py2fastrust.native_source_filenames import SourceFilenames
from py2fastrust.rust_pruning import prune_rust_source


class SourceFilenameContracts(unittest.TestCase):
    def test_short_path_and_unused_requests_do_not_change_source(self):
        pool=SourceFilenames()
        self.assertEqual(pool.reference('main.py'),'"main.py"')
        pool.reference('/unused/'+'long_path/'*20+'main.py')
        source='#![allow(dead_code)]\nfn main(){}'
        self.assertEqual(pool.finish(source),source)

    def test_one_use_is_inlined_and_repeated_retained_uses_are_profitable(self):
        filename='/project/'+'long_path/'*20+'main.py'
        pool=SourceFilenames();symbol=pool.reference(filename)
        single='fn main(){let _='+symbol+';}'
        self.assertEqual(pool.finish(single),'fn main(){let _='+_string(filename)+';}')
        repeated='fn main(){let _=('+','.join([symbol]*4)+');}'
        pooled=pool.finish(repeated)
        inline='fn main(){let _=('+','.join([_string(filename)]*4)+');}'
        self.assertLess(len(pooled.encode()),len(inline.encode()))
        self.assertEqual(pooled.count('const '+symbol+':'),1)

    def test_user_text_comments_raw_strings_characters_and_lifetimes_are_untouched(self):
        pool=SourceFilenames();filename='/project/'+'long_path/'*20+'main.py';symbol=pool.reference(filename)
        protected=('"'+symbol+'"', 'r##"'+symbol+'"##', 'br"'+symbol+'"',
                   'cr#"'+symbol+'"#', '// '+symbol, '/* outer /* '+symbol+' */ end */',
                   "'"+symbol, "'x'", "'\\''", "'\\u{4e00}'", 'r#'+symbol,
                   '雪'+symbol, symbol+'雪', symbol+'\u0301')
        source='\n'.join(protected)+'\nfn main(){let _=('+','.join([symbol]*4)+');}'
        result=pool.finish(source)
        for part in protected:self.assertIn(part,result)
        self.assertEqual(result.count('const '+symbol+':'),1)

    def test_user_literal_identifier_does_not_count_as_a_location_use(self):
        pool=SourceFilenames();filename='/project/'+'long_path/'*20+'main.py';symbol=pool.reference(filename)
        source='fn main(){let text="'+symbol+'";let _='+symbol+';}'
        self.assertEqual(pool.finish(source),'fn main(){let text="'+symbol+'";let _='+_string(filename)+';}')

    def test_pruning_unresolved_location_identifiers_preserves_actual_helper_calls(self):
        pool=SourceFilenames()
        needed='/retained/'+'long_path/'*20+'main.py';dead='/dead/'+'long_path/'*20+'dead.py'
        used=pool.reference(needed);unused=pool.reference(dead)
        source=('#![allow(dead_code)]\nfn retained()->&\'static str{'+used+'}\n'
                'fn unused()->(&\'static str,&\'static str){('+unused+','+unused+')}\n'
                'fn main(){println!("{}",retained());}')
        pruned=prune_rust_source(source)
        self.assertIn('fn retained',pruned);self.assertNotIn('fn unused',pruned)
        result=pool.finish(pruned)
        self.assertTrue(result.startswith('#![allow(dead_code)]'))
        self.assertIn(_string(needed),result);self.assertNotIn(_string(dead),result)
        self.assertNotIn('const PYTORS_FILE_',result)
        if shutil.which('rustc'):
            with tempfile.TemporaryDirectory(prefix='pytors-file-pool-pruner-')as temp:
                rust=Path(temp)/'main.rs';rust.write_text(result);binary=Path(temp)/'main'
                built=subprocess.run(['rustc','--edition=2021',str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
                self.assertEqual(actual.stdout,needed+'\n')


ORACLE=r'''import json,runpy,sys,traceback
from pathlib import Path
entry=Path(sys.argv[1]);allowed=set(json.loads(sys.argv[2]));sys.path.insert(0,str(entry.parent))
try:runpy.run_path(str(entry),run_name='__main__')
except BaseException as error:
 frames=[(frame.filename,frame.lineno,frame.name)for frame in traceback.extract_tb(error.__traceback__)if frame.filename in allowed]
 print(json.dumps({'exception':type(error).__name__,'message':str(error),'frames':frames}),file=sys.stderr)
 sys.exit(1)
'''


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class SourceFilenameExecution(unittest.TestCase):
    def exercise(self,source,modules,inputs=('',),*,escaped=False,unpruned=False,user_literal=False):
        with tempfile.TemporaryDirectory(prefix='pytors-filename-pool-')as temp:
            directory=Path(temp)/('long_diagnostic_source_directory_'*3)
            if escaped:directory=directory/'quoted_"_back\\slash_雪'
            directory.mkdir(parents=True)
            entry=directory/('entry_"_back\\slash_雪\t.py'if escaped else'entry.py')
            if user_literal:source=source.replace('SOURCE_LITERAL',repr(str(entry)))
            entry.write_text(source)
            paths=[entry]
            for name,text in modules.items():
                path=directory/(name+'.py');path.write_text(text);paths.append(path)
            # Freeze CPython observations before any conversion in this project.
            references=[subprocess.run([sys.executable,'-I','-c',ORACLE,str(entry),json.dumps(list(map(str,paths)))],
                                      input=data,capture_output=True,text=True,timeout=5)for data in inputs]
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(filename=str(entry),module_paths=(directory,),integer=integer,
                                                        license='none',optimize=not unpruned))
                self.assertTrue(result.success,result.diagnostics);self.assertEqual(result.backend,'native')
                self.assertIn('const PYTORS_FILE_',result.rust_source)
                if user_literal:
                    self.assertIn('"PYTORS_FILE_0"',result.rust_source)
                    self.assertGreaterEqual(result.rust_source.count(_string(str(entry))),2)
                rust=directory/'main.rs';rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=directory/('native_'+integer+str(optimized))
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],
                                         capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,references):
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=5,
                                              env={'PATH':'/unavailable'})
                        self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                        if reference.returncode:
                            expected=json.loads(reference.stderr.splitlines()[-1])
                            last=actual.stderr.splitlines()[-1];kind,separator,message=last.partition(': ')
                            if not separator:kind=last.rstrip(':');message=''
                            self.assertEqual((kind,message),(expected['exception'],expected['message']))
                            frames=[(json.loads(path),int(line),scope)for path,line,scope in
                                    re.findall(r'  File ("(?:\\.|[^"\\])*"), line (\d+), in ([^\n]+)',actual.stderr)]
                            self.assertEqual(frames,[tuple(frame)for frame in expected['frames']],actual.stderr)

    def test_normal_linked_class_values(self):
        self.exercise('from records import Box\nbox=Box(7)\nprint(box.value,box.double(),box.value+3)\n',
                      {'records':'class Box:\n def __init__(self,value):self.value=value\n def double(self):return self.value*2\n'})

    def test_imported_error_positions_and_normal_calls(self):
        self.exercise('from arithmetic import compute\nprint("before")\nprint(compute(int(input())))\n',
                      {'arithmetic':'def compute(value):\n print("compute")\n return (value+1)//(value-2)\n'},('2\n','3\n'))

    def test_generator_expression_scope(self):
        self.exercise('from arithmetic import count\nprint("before")\nprint(count(int(input())))\n',
                      {'arithmetic':'def count(limit):\n return sum(10//(number-2) for number in range(limit))\n'},('2\n','3\n'))

    def test_retained_generator_scope(self):
        self.exercise('from arithmetic import values\nit=values(3)\nprint(next(it))\nprint(next(it))\n',
                      {'arithmetic':'def values(limit):\n for value in range(limit):\n  yield 10//(value-1)\n'})

    def test_escaped_unicode_filename_values(self):
        self.exercise('from arithmetic import compute\nprint("before")\nprint(compute(int(input())))\n',
                      {'arithmetic':'def compute(value):\n return (value+1)//(value-2)\n'},('2\n','3\n'),escaped=True)

    def test_user_literals_equal_filename_and_registry_symbol(self):
        self.exercise('from arithmetic import compute\nname=SOURCE_LITERAL\nprint(name,"PYTORS_FILE_0")\nprint(compute(3))\n',
                      {'arithmetic':'def compute(value):\n return (value+1)//(value-2)\n'},user_literal=True,escaped=True)

    def test_unpruned_linked_errors(self):
        self.exercise('from arithmetic import compute\nprint("before")\nprint(compute(2))\n',
                      {'arithmetic':'def compute(value):\n return (value+1)//(value-2)\n'},unpruned=True)

    def test_three_module_class_method_frames(self):
        self.exercise('from wrapper import solve\nprint("start")\nsolve(int(input()))\n',
                      {'wrapper':'from ledger import Cell\ndef solve(value):\n cell=Cell(value)\n print(cell.combine(8))\n',
                       'ledger':'class Cell:\n def __init__(self,value):self.value=value\n def combine(self,limit):\n  return (self.value+limit)//(self.value-limit)\n'},
                      ('8\n','9\n'))
