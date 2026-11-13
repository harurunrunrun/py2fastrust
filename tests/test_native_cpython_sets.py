"""Controlled-seed source-to-Rust differentials for actual CP set history."""
import ast,json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

CASES={
 'small_constant_arithmetic':'print(list({0+0,8+0,16+0,24+0,32+0}))\n',
 'chained_membership_literal':'class Probe:\n def __contains__(self,values):\n  print(list(values))\n  return True\nprint(0 in {0,8,16,24,32} in Probe())\n',
 'dict_subclass_history':'from collections import defaultdict,Counter\nkeys=[0,8,16,24,32]\nd={}\nf=defaultdict(int)\nc=Counter()\nfor x in keys:\n d[x]=1\n f[x]=1\n c[x]=1\nprint(list(set(d)),list(set(f)),list(set(c)))\na=set()\nb=set()\ne=set()\na.update(d)\nb.update(f)\ne.update(c)\nprint(list(a),list(b),list(e))\n',
 'mutable_set_queries':'print(list({0,8,16,24,32}))\nprint(set()in{1},set([1])not in{1},set([1])in{None},set()in{(1,2)},set()in set())\n',
 'mutable_set_query_effects':'def query():\n print("query")\n return set([0,8])\ndef owner():\n print("owner")\n return {0,8,16,24,32}\nprint(query()in owner(),query()not in owner())\n',
 'mutable_set_query_argument_error':'def query():\n print("query")\n return set([0,8])\ndef owner():\n print("owner")\n return {1//0}\nprint(query()in owner())\n',
 'mutable_set_query_dict_error':'d={1:2}\nq=set()\nprint("prefix")\nprint(q in d)\n',
 'wrapped_iteration_contexts':'def select():return True\nflag=select()\nout=[]\nfor x in ({0,8,16,24,32} if flag else {1,9,17,25,33}):out.append(x)\nprint(out)\nout=[]\nfor x in (flag and {0,8,16,24,32} or {1,9,17,25,33}):out.append(x)\nprint(out)\n',
 'constant_wrapped_iteration':'out=[]\nfor x in (False or {0,8,16,24,32}):out.append(x)\nprint(out)\nout=[]\nfor x in ({0,8,16,24,32} if True else {1,9,17,25,33}):out.append(x)\nprint(out)\n',
 'fixed_wrapped_iteration':'out=[]\nfor x in (((1<<64)&0)or{0,8,16,24,32}):out.append(x)\nprint(out)\n',
 'literal_constant_bulk':'s={0,8,16,24,32,40,48}\nprint(list(s),s)\n',
 'literal_text_bulk':'s={"a","bb","ccc","dddd","eeeee","ffffff","ggggggg"}\nprint(list(s),s)\n',
 'direct_for_text_constants':'out=[]\nfor x in {"a","bb","ccc","dddd","eeeee","ffffff","ggggggg"}:out.append(x)\nprint(out)\n',
 'direct_for_bytes_constants':'out=[]\nfor x in {b"a",b"bb",b"ccc",b"dddd",b"eeeee",b"ffffff",b"ggggggg"}:out.append(x)\nprint(out)\n',
 'literal_two':'s={-1,-2}\nprint(list(s),s)\n',
 'literal_dynamic':'def value(x):\n print("value",x)\n return x\ns={value(0),value(8),value(16),value(24),value(32)}\nprint(list(s))\n',
 'literal_30':'s={'+','.join(str(i*8)for i in range(30))+'}\nprint(list(s))\n',
 'literal_31':'s={'+','.join(str(i*8)for i in range(31))+'}\nprint(list(s))\n',
 'direct_for_constants':'out=[]\nfor x in {0,8,16,24,32,40,48}:out.append(x)\nprint(out)\n',
 'direct_comprehension_constants':'print([x for x in {0,8,16,24,32,40,48}])\n',
 'original_bool_key':'s=set([True,1,False,0])\nprint(list(s),s)\nt=set([1,True,0,False])\nprint(list(t),t)\n',
 'fixed_literal_collisions':'s={True,1,18446744073709551617,340282366920938463463374607431768211457,0}\nprint(list(s),s)\n',
 'fixed_constant_expression_collisions':'s={True,1,1+2**64,1+2**128,0}\nprint(list(s),s)\n',
 'copy_tombstone':'s=set(range(35))\nfor x in range(0,35,2):s.discard(x)\na=s.copy()\nb=set(s)\nprint(list(s),list(a),list(b))\n',
 'set_and_dict_update':'s=set([0,8,16,24])\nt=set([32,40,48,56,64])\ns.update(t)\nprint(list(s))\ns.update({72:1,80:2,88:3})\nprint(list(s))\ns.update([96,104,112])\nprint(list(s))\n',
 'update_alias_clear':'s=set(range(20))\nalias=s\ns.update(alias)\nprint(list(s))\ns.clear()\ns.update([3,11,19])\nprint(list(alias),s is alias)\n',
 'pop_finger_clear':'s=set([0,8,16,24,32,40])\nprint(s.pop(),s.pop())\ns.clear()\ns.update([1,9,17,25,33])\nprint(s.pop(),list(s),s.copy().pop())\n',
 'pop_empty':'s=set()\nprint("prefix")\nprint(s.pop())\n',
 'cross_abi_bool_merge':'s=set([1,9,17])\nt=set([True,False])\ns.update(t)\nprint(list(s),s)\n',
 'none_empty_tuple':'a={None}\nb={()}\nprint(list(a),list(b),None in a,() in a,None in b,() in b)\n',
 'tuple_arity':'a={'+repr(tuple(range(17)))+','+repr(tuple(range(1,18)))+'}\nprint(list(a),tuple(range(17))in a)\n',
 'tuple_arity_bulk':'a={'+','.join(repr(tuple(range(i,i+17)))for i in range(3))+'}\nprint(list(a),tuple(range(17))in a)\n',
 'text_history':'s=set(["a","bb","ccc","dddd","eeeee","f","g","h","i"])\ns.discard("bb")\ns.add("jj")\nt=s.copy()\nprint(list(s),list(t),s)\n',
 'unicode_hashes':'s={"é","Ā","😀","éĀ😀","ÿ","a\\x00é"}\nprint(len(s),"é"in s,"Ā"in s)\nprint(list(s))\n',
 'bytes_hashes':'s={b"a",b"abc",b"abcdefgh",b"abcdefghi",b"\\x00\\xff"}\nprint(list(s),s,b"abc"in s)\n',
 'stored_cursor':'s=set([0,8,16,24,32])\ni=iter(s)\nj=i\nprint(next(i),next(j),list(i),next(j,99))\n',
 'size_change':'s={1}\ni=iter(s)\ns.add(2)\nprint("prefix")\nprint(next(i))\n',
 'last_yield_size_change':'s={1}\ni=iter(s)\nprint(next(i))\ns.add(2)\nprint(next(i,None))\n',
 'exhausted_cursor':'s={1}\ni=iter(s)\nprint(next(i),next(i,99))\ns.clear()\ns.add(2)\nprint(next(i,99))\n',
 'same_size_clear':'s=set([0,8,16,24,32])\ni=iter(s)\nprint(next(i))\ns.clear()\ns.update([1,9,17,25,33])\nprint(list(i))\n',
 'sorting_callback':'s=set([0,8,16,24,32,40,48])\ndef key(x):\n print("key",x)\n s.add(1000+x)\n return 0\nprint(sorted(s,key=key))\nprint(sorted(s))\n',
}


def reference(source,mode,seed):
    probe=r'''
import ast,dis,operator,sys
source=sys.stdin.read();mode=sys.argv[1]
operations={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow,ast.LShift:operator.lshift,ast.RShift:operator.rshift,ast.BitAnd:operator.and_,ast.BitOr:operator.or_,ast.BitXor:operator.xor}
def __pytors_policy_binary(name,left,right):
 result=operations[getattr(ast,name)](left,right)
 if type(result)is int and mode!='bigint':
  width=int(mode[1:]);result=(result+2**(width-1))%2**width-2**(width-1)
 return result
class Normalize(ast.NodeTransformer):
 def number(self,value):
  if type(value)is int and mode!='bigint':
   width=int(mode[1:]);return (value+2**(width-1))%2**width-2**(width-1)
  return value
 def visit_Constant(self,node):
  node.value=self.number(node.value)
  return node
 def visit_BinOp(self,node):
  instructions=[x for x in dis.get_instructions(compile(ast.Expression(node),'<policy-fold>','eval',optimize=0))if x.opname not in {'RESUME','RETURN_VALUE'}]
  folded=len(instructions)==1 and instructions[0].opname in {'LOAD_CONST','LOAD_SMALL_INT','RETURN_CONST'}
  node=self.generic_visit(node)
  if folded and isinstance(node.left,ast.Constant)and isinstance(node.right,ast.Constant)and type(node.left.value)is int and type(node.right.value)is int:
   if type(node.op)in operations:
    value=operations[type(node.op)](node.left.value,node.right.value)
    return ast.copy_location(ast.Constant(self.number(value)),node)
  if mode!='bigint'and type(node.op)in operations:
   return ast.copy_location(ast.Call(func=ast.Name(id='__pytors_policy_binary',ctx=ast.Load()),args=[ast.Constant(type(node.op).__name__),node.left,node.right],keywords=[]),node)
  return node
tree=Normalize().visit(ast.parse(source,filename='set_case.py'))
ast.fix_missing_locations(tree)
exec(compile(tree,'set_case.py','exec'))
'''
    return subprocess.run([sys.executable,'-c',probe,mode],input=source,env={**os.environ,'PYTHONHASHSEED':str(seed)},capture_output=True,text=True,timeout=10)


@unittest.skipUnless(shutil.which('rustc')and sys.implementation.name=='cpython'and sys.version_info[:2]==(3,14)and sys.hash_info.width==64 and sys.hash_info.algorithm=='siphash13'and sys.byteorder=='little','CPython 3.14 64-bit LE and rustc are required')
class CPythonSetExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-cpython-set-source-');cls.root=Path(cls.directory.name)
        cls.oracles={(name,mode,seed):reference('class SetProtocolMarker:pass\n'+source,mode,seed)
                     for name,source in CASES.items()for mode in ('i64','i128','bigint')for seed in (0,1,42,4294967295)}

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def exercise(self,name,*,plain=False):
        from py2fastrust import transpile,TranspileOptions
        source=(''if plain else'class SetProtocolMarker:pass\n')+CASES[name]
        if name in {'literal_text_bulk','direct_for_text_constants'}:
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(filename='set_case.py',integer=mode,license='none'))
                self.assertFalse(result.success)
                self.assertIn('CodeType string interning',result.diagnostics[0].message)
            return
        if plain:
            oracles={(mode,seed):reference(source,mode,seed)for mode in ('i64','i128','bigint')for seed in (0,1,42,4294967295)}
        for mode in ('i64','i128','bigint'):
            converted=transpile(source,TranspileOptions(filename='set_case.py',integer=mode,license='none',string_mode='unicode'if name=='unicode_hashes'else'ascii'))
            self.assertTrue(converted.success,'\n'.join(str(x)for x in converted.diagnostics))
            rust=self.root/(name+'_'+mode+'.rs');rust.write_text(converted.rust_source)
            for optimized in (False,True):
                binary=rust.with_suffix('.optimized'if optimized else'.debug')
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(built.returncode,0,built.stderr[:12000])
                for seed in (0,1,42,4294967295):
                    actual=subprocess.run([str(binary)],env={**os.environ,'PYTHONHASHSEED':str(seed)},capture_output=True,text=True,timeout=10)
                    expected=oracles[mode,seed]if plain else self.oracles[name,mode,seed]
                    self.assertEqual(actual.stdout,expected.stdout,(name,mode,seed,optimized))
                    self.assertEqual(actual.returncode==0,expected.returncode==0,(name,mode,seed,actual.stderr,expected.stderr))
                    if expected.returncode:
                        self.assertEqual(actual.stderr.strip().splitlines()[-1],expected.stderr.strip().splitlines()[-1],(name,mode,seed))
            if name=='none_empty_tuple':
                self.assertNotIn('fn native_cp_sip_round',converted.rust_source)
                self.assertNotIn('Marek Majkowski',converted.rust_source)
                self.assertNotIn('UNICODE LICENSE',converted.rust_source)

    def test_plain_observers_route_from_actual_set_facts(self):
        for name in ('original_bool_key','direct_for_constants','bytes_hashes','text_history','sorting_callback','pop_finger_clear','pop_empty'):
            with self.subTest(name=name):self.exercise(name,plain=True)

    def test_selector_keeps_unused_and_shadowed_nonobserver_calls(self):
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_frame_selection import select_frames
        sources=['def unused():\n print({1,9,17})\nprint(7)\n','def unused():\n for x in {1,9,17}:print(x)\nprint(7)\n','def list(values):return len(values)\ns={1,9,17}\nprint(list(s))\n','def iter(values):return 7\ns={1,9,17}\nprint(iter(s))\n','values=[1,2,3]\nprint(list(values))\n']
        for source in sources:
            selection=select_frames(parse_source(source,'selector.py'))
            self.assertNotIn('CPython-compatible native set traversal',selection.reasons)

    def test_startup_seed_parsing_precedes_source_effects(self):
        from py2fastrust import transpile,TranspileOptions
        source='print("source")\ns=set(["a","bb","ccc","dddd"])\niterator=iter(s)\nprint(sorted(s))\n'
        seeds=['','random','0','+0','-0','  +001','4294967295','4294967296','-1',' 1 ','1\n','1x','+','-','  ','\t0',
               '-18446744073709551615','-18446744073709551614','-18446744069414584321','-18446744069414584320',
               '-18446744073709551616','18446744073709551615','18446744073709551616']
        expected={seed:reference(source,'i64',seed)for seed in seeds}
        converted=transpile(source,TranspileOptions(filename='set_case.py',license='none'))
        self.assertTrue(converted.success,str(converted.diagnostics));rust=self.root/'seed_startup.rs';rust.write_text(converted.rust_source)
        for optimized in (False,True):
            binary=self.root/('seed_startup_optimized'if optimized else'seed_startup_debug')
            built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            for seed in seeds:
                actual=subprocess.run([str(binary)],env={**os.environ,'PYTHONHASHSEED':seed},capture_output=True,text=True,timeout=10)
                self.assertEqual(actual.stdout,expected[seed].stdout,repr(seed))
                self.assertEqual(actual.returncode,expected[seed].returncode,repr(seed))
                if expected[seed].returncode:self.assertEqual(actual.stderr,expected[seed].stderr,repr(seed))

    def test_numeric_hash_and_notices_omit_unused_text_without_final_pruning(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            result=transpile('s={1,9,17}\nprint(list(s))\n',TranspileOptions(integer=mode,license='none',optimize=False))
            self.assertTrue(result.success,str(result.diagnostics))
            for unneeded in ('fn native_cp_hash_text','fn native_cp_sip_round','fn native_cp_entropy_secret','Marek Majkowski','UNICODE LICENSE'):self.assertNotIn(unneeded,result.rust_source)

    def test_ascii_string_hashes_omit_unicode_hash_code(self):
        from py2fastrust import transpile,TranspileOptions
        for optimized in (False,True):
            result=transpile('s={"a-","bb-","ccc-"}\nprint(list(s))\n',TranspileOptions(license='none',optimize=optimized,string_mode='ascii'))
            self.assertTrue(result.success,str(result.diagnostics))
            self.assertNotIn('fn native_cp_hash_text',result.rust_source)
            self.assertNotIn('UNICODE LICENSE',result.rust_source)
            self.assertIn('fn native_cp_hash_bytes',result.rust_source)
            self.assertIn('Marek Majkowski',result.rust_source)

    def test_set_storage_does_not_retain_legacy_dictionary_helpers(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            for optimized in (False,True):
                result=transpile('s={1,9,17}\nprint(list(s))\n',TranspileOptions(integer=mode,license='none',optimize=optimized))
                self.assertTrue(result.success,str(result.diagnostics))
                for legacy in ('struct NativeKeyDict','struct NativeKeySet','struct NativeKeyHasher','trait ClassMappingOwner'):self.assertNotIn(legacy,result.rust_source)
                self.assertNotRegex(result.rust_source,r'impl\s+std::hash::Hash\s+for\s+Int\s*\{')

    def test_actual_original_literal_plans_cover_seeded_bulk_and_direct_paths(self):
        from unittest.mock import patch
        from py2fastrust import transpile,TranspileOptions
        from py2fastrust.native_cpython_set_adapters import CPythonSets
        original=CPythonSets.plan_literal
        for name,wanted in [('literal_text_bulk','frozen_bulk'),('bytes_hashes','frozen_bulk'),('direct_for_text_constants','frozen_direct'),('direct_for_bytes_constants','frozen_direct'),('fixed_literal_collisions','frozen_bulk'),('tuple_arity_bulk','frozen_bulk')]:
            plans=[]
            def observe(registry,node):
                result=original(registry,node);plans.append(result);return result
            with patch.object(CPythonSets,'plan_literal',observe):
                result=transpile(CASES[name],TranspileOptions(license='none'))
            if name in {'literal_text_bulk','direct_for_text_constants'}:
                self.assertFalse(result.success);self.assertIn('CodeType string interning',result.diagnostics[0].message)
            else:self.assertTrue(result.success,str(result.diagnostics))
            self.assertIn(wanted,plans,(name,plans))

    def test_analyzed_before_emission_set_alias_has_real_table_type(self):
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_classes import Model
        for mode in ('i64','i128','bigint'):
            unit=parse_source('values={1,9,17}\n','abi.py')
            model=Model(unit.tree,'abi.py',mode,unit.native_imports,unit=unit);model.run()
            records=model.mappings.records
            self.assertTrue(records);self.assertTrue(all(not record.emitted for record in records))
            kernel=model.mappings.cpython_sets.runtime()
            self.assertNotIn('NATIVE_CP_PROGRAM_SECRET',kernel)
            rust=self.root/('analyzed_alias_'+mode+'.rs')
            rust.write_text(kernel+'\ntype AnalyzedSet=std::rc::Rc<std::cell::RefCell<NativeCPSet<i64,i64>>>;struct FrameAbi{value:Option<AnalyzedSet>}fn main(){let abi=FrameAbi{value:None};assert!(abi.value.is_none());}')
            for optimized in (False,True):
                binary=rust.with_suffix('.optimized'if optimized else'.debug')
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(built.returncode,0,built.stderr)
                actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10);self.assertEqual(actual.returncode,0,actual.stderr)


for _name in CASES:
    setattr(CPythonSetExecution,'test_'+_name,lambda self,name=_name:self.exercise(name))
