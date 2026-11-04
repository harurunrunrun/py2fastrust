"""AST-proved list endpoints preserve errors, callbacks and mutable leaf identity."""
import ast,json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
from py2fastrust.native_list_end_indices import method,result
import test_native_class_iterators as iterator_tests

CASES={'plain_scalar_and_other_indices': 'items = [13, 21, 34]\n'
                                   'print(items[0], items[-1], items[1], items[-2], items[+0], '
                                   'items[-True], items[False])\n',
 'empty_first_error_owner_before_later': 'def owner():\n'
                                         '    print("owner")\n'
                                         '    return []\n'
                                         'def later():\n'
                                         '    print("later")\n'
                                         '    return 7\n'
                                         'print(owner()[0], later())\n',
 'empty_last_error_owner_before_later': 'def owner():\n'
                                        '    print("owner")\n'
                                        '    return []\n'
                                        'def later():\n'
                                        '    print("later")\n'
                                        '    return 7\n'
                                        'print(owner()[-1], later())\n',
 'nested_mutable_alias_leaves': 'rows = [[3], [7]]\n'
                                'first = rows[0]\n'
                                'last = rows[-1]\n'
                                'first.append(11)\n'
                                'last[0] += 5\n'
                                'print(rows, first is rows[0], last is rows[-1], first is last)\n',
 'later_argument_mutates_parent': 'def later(rows):\n'
                                  '    previous = rows.pop()\n'
                                  '    previous.append(19)\n'
                                  '    rows.append([99])\n'
                                  '    return rows\n'
                                  '\n'
                                  'def pair(first, second):\n'
                                  '    return first, second\n'
                                  '\n'
                                  'rows = [[2], [5]]\n'
                                  'result = pair(rows[-1], later(rows))\n'
                                  'print(result, result[0] is rows[-1])\n',
 'nested_empty_boundary': 'rows = [[]]\nprint(rows[-1][0])\n',
 'unbound_owner_error_order': 'def read(flag):\n'
                              '    if flag:\n'
                              '        items = [4, 9]\n'
                              '    return items[-1]\n'
                              'print(read(int(input())))\n',
 'class_instance_and_class_namespace': 'class Bag:\n'
                                       '    history = []\n'
                                       '    def __init__(self, values):\n'
                                       '        self.values = values\n'
                                       '    def read(self):\n'
                                       '        return self.values[0], self.values[-1]\n'
                                       '    @classmethod\n'
                                       '    def latest(cls):\n'
                                       '        return cls.history[-1]\n'
                                       '\n'
                                       'first = Bag([4, 9])\n'
                                       'Bag.history.append(13)\n'
                                       'print(first.read(), Bag.latest())\n',
 'index_callback_mutates_owner_unchanged': 'items = [2, 4]\n'
                                           'def index():\n'
                                           '    items.append(9)\n'
                                           '    return -1\n'
                                           'print(items[index()], items)\n',
 'zero_trip_empty_owner': 'items = []\n'
                          'for value in range(0):\n'
                          '    print(items[0], items[-1])\n'
                          'print("done")\n',
 'nonlist_str_bytes_tuple_unchanged': 'print("abc"[0], "abc"[-1], b"de"[0], b"de"[-1], (6, 7)[0], '
                                      '(6, 7)[-1])\n',
 'augmented_before_rhs_resize': 'class Store:\n'
                                '    def __init__(self):\n'
                                '        self.values = [1, 2]\n'
                                '    def change(self):\n'
                                '        self.values[-1] += self.rhs()\n'
                                '    def rhs(self):\n'
                                '        self.values.insert(0, 5)\n'
                                '        return 3\n'
                                'store = Store()\n'
                                'store.change()\n'
                                'print(store.values)\n',
 'augmented_store_error_after_clear': 'class Store:\n'
                                      '    def __init__(self):\n'
                                      '        self.values = [1, 2]\n'
                                      '    def change(self):\n'
                                      '        self.values[0] += self.rhs()\n'
                                      '    def rhs(self):\n'
                                      '        print("rhs")\n'
                                      '        self.values.clear()\n'
                                      '        return 3\n'
                                      'store = Store()\n'
                                      'store.change()\n',
 'class_leaf_reference_identity': 'class Box:\n'
                                  '    def __init__(self, value):\n'
                                  '        self.value = value\n'
                                  'rows = [Box(3), Box(7)]\n'
                                  'first = rows[0]\n'
                                  'last = rows[-1]\n'
                                  'first.value += 11\n'
                                  'last.value += 19\n'
                                  'print(rows[0].value, rows[-1].value, first is rows[0], last is '
                                  'rows[-1])\n',
 'loop_region_unbound_zero_trip': 'class Sum:\n'
                                  '    def run(self, flag, count):\n'
                                  '        if flag:\n'
                                  '            values = [3, 8]\n'
                                  '        total = 0\n'
                                  '        for _ in range(count):\n'
                                  '            total += values[0] + values[-1]\n'
                                  '        return total\n'
                                  'flag, count = map(int, input().split())\n'
                                  'print(Sum().run(flag, count))\n'}
INPUTS={'plain_scalar_and_other_indices': [''],
 'empty_first_error_owner_before_later': [''],
 'empty_last_error_owner_before_later': [''],
 'nested_mutable_alias_leaves': [''],
 'later_argument_mutates_parent': [''],
 'nested_empty_boundary': [''],
 'unbound_owner_error_order': ['0\n', '1\n'],
 'class_instance_and_class_namespace': [''],
 'index_callback_mutates_owner_unchanged': [''],
 'zero_trip_empty_owner': [''],
 'nonlist_str_bytes_tuple_unchanged': [''],
 'augmented_before_rhs_resize': [''],
 'augmented_store_error_after_clear': [''],
 'class_leaf_reference_identity': [''],
 'loop_region_unbound_zero_trip': ['0 0\n', '1 3\n', '0 1\n']}
BOUNDARIES={'custom_index_boundary': 'class Position:\n'
                          '    def __index__(self):\n'
                          '        print("index")\n'
                          '        return -1\n'
                          'print([4, 8][Position()])\n'}

class ListEndIndexProofs(unittest.TestCase):
 def test_only_exact_integer_zero_and_negative_one_ASTs_select(self):
  for source in ('0','0x0','0_0'):
   self.assertEqual(method(ast.parse(source,mode='eval').body),'first')
  for source in ('-1','-(1)','-0x1'):
   self.assertEqual(method(ast.parse(source,mode='eval').body),'last')
  for source in ('1','-2','+0','-0','False','True','-True','0.0','1-1','-(1+0)','index()','position'):
   self.assertIsNone(method(ast.parse(source,mode='eval').body),source)
 def test_owned_leaf_clone_and_checked_reference_use_same_index_error(self):
  for operation in ('first','last'):
   self.assertIn('.'+operation+'().cloned()',result('values',operation))
   self.assertNotIn('.cloned()',result('values',operation,clone=False))
   self.assertIn('IndexError: list index out of range',result('values',operation))
 def test_endpoint_generation_avoids_general_index_arithmetic(self):
  for name in ('plain_scalar_and_other_indices','nested_mutable_alias_leaves','class_instance_and_class_namespace','loop_region_unbound_zero_trip'):
   for integer in ('i64','i128','bigint'):
    observed=[]
    def record(values,operation,*,clone=True):
     code=result(values,operation,clone=clone);observed.append((operation,clone,code));return code
    with patch('py2fastrust.native_list_end_indices.result',side_effect=record):
     converted=transpile(CASES[name],TranspileOptions(integer=integer,license='none'))
    self.assertTrue(converted.success,converted.diagnostics)
    self.assertTrue(observed,(name,integer))
    self.assertTrue(all('class_index'not in code and'native_index'not in code and'.len()'not in code for _,_,code in observed))
 def test_nonliteral_and_nonlist_index_paths_keep_existing_generation(self):
  for name in ('index_callback_mutates_owner_unchanged','nonlist_str_bytes_tuple_unchanged'):
   for integer in ('i64','i128','bigint'):
    new=transpile(CASES[name],TranspileOptions(integer=integer,license='none'))
    with patch('py2fastrust.native_list_end_indices.method',return_value=None):
     old=transpile(CASES[name],TranspileOptions(integer=integer,license='none'))
    self.assertTrue(new.success,new.diagnostics)
    self.assertEqual(new.rust_source,old.rust_source)
 def test_custom_index_protocol_preserves_exact_existing_diagnostic(self):
  for source in BOUNDARIES.values():
   for integer in ('i64','i128','bigint'):
    new=transpile(source,TranspileOptions(integer=integer,license='none'))
    with patch('py2fastrust.native_list_end_indices.method',return_value=None):
     old=transpile(source,TranspileOptions(integer=integer,license='none'))
    self.assertFalse(new.success)
    self.assertEqual(new.diagnostics,old.diagnostics)
    self.assertTrue(all(d.code=='E006'for d in new.diagnostics))

@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ListEndIndexExecution(unittest.TestCase):
 def check(self,name):
  source=CASES[name];filename='endpoint_case.py'
  references=[subprocess.run([sys.executable,'-I','-S','-c',iterator_tests.REFERENCE,source,filename],input=data,capture_output=True,text=True,timeout=10)for data in INPUTS[name]]
  with tempfile.TemporaryDirectory(prefix='pytors-list-end-')as directory:
   for integer in ('i64','i128','bigint'):
    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend used')):
     converted=transpile(source,TranspileOptions(integer=integer,filename=filename,license='none'))
    self.assertTrue(converted.success,converted.diagnostics);self.assertEqual(converted.backend,'native');self.assertLess(len(converted.rust_source.encode()),512*1024)
    rust=Path(directory,integer+'.rs');rust.write_text(converted.rust_source)
    for optimized in (False,True):
     binary=rust.with_suffix('.O'if optimized else'.debug');built=subprocess.run(['rustc','--edition=2021','--crate-name','list_end_indices',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120);self.assertEqual(built.returncode,0,built.stderr)
     for data,expected in zip(INPUTS[name],references):
      actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
      self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
      if expected.returncode:
       error=json.loads(expected.stderr);self.assertEqual(actual.stderr.rstrip().splitlines()[-1],error['message']);self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(row)for row in error['frames']])
      else:self.assertEqual(actual.stderr,'')

def install(name):
 def test(self):self.check(name)
 setattr(ListEndIndexExecution,'test_'+name,test)
for name in CASES:install(name)
