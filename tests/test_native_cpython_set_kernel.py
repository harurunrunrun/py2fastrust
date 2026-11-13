"""CPython-first standalone tests of the typed set/hash foundation.

The standalone carrier tests remain independent of frontend registration. The
three numeric inputs are normalized by the fixed-width source policy.
"""
import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path


def rust_text(value):
    escaped=[]
    for character in value:
        if character=='"':escaped.append('\\"')
        elif character=='\\':escaped.append('\\\\')
        elif ord(character)<32:escaped.append('\\u{'+format(ord(character),'x')+'}')
        else:escaped.append(character)
    return '"'+''.join(escaped)+'"'


def canonical(value):
    tag,payload=value
    if tag=='bool':return ['int',str(int(payload))]
    if tag=='tuple':return [tag,[canonical(child)for child in payload]]
    return value


def hash_code(value):
    tag,payload=value
    if tag=='none':return 'native_cp_hash_none()'
    if tag=='bool':return 'native_cp_hash_integer('+str(int(payload))+'i128)'
    if tag=='int':
        number=int(payload)
        if -2**127<=number<2**127:return 'native_cp_hash_integer('+str(number)+'i128)'
        magnitude=abs(number);digits=[]
        while magnitude:digits.append(magnitude%(2**32));magnitude//=2**32
        return 'native_cp_hash_digits('+str(number<0).lower()+',&['+','.join(str(x)+'u32'for x in digits)+'])'
    if tag=='str':return 'native_cp_hash_text('+rust_text(payload)+',secret)'
    if tag=='bytes':return 'native_cp_hash_bytes(&['+','.join(str(x)for x in payload)+'],secret)'
    if tag=='tuple':return 'native_cp_hash_tuple(['+','.join(hash_code(x)for x in payload)+'])'
    raise AssertionError(tag)


def digest(values):
    result=14695981039346656037
    for value in values:
        for byte in int(value).to_bytes(8,'little',signed=True):result=((result^byte)*1099511628211)%(2**64)
    return result


@unittest.skipUnless(shutil.which('rustc')and sys.implementation.name=='cpython'and sys.version_info[:2]==(3,14)and sys.hash_info.width==64 and sys.hash_info.algorithm=='siphash13'and sys.hash_info.cutoff==0 and sys.byteorder=='little','64-bit LE CPython 3.14 with SipHash13 and rustc are required')
class CPythonSetKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-cpython-set-kernel-');cls.root=Path(cls.directory.name)
        cls.oracles={}
        for mode in ('i64','i128','bigint'):
            for seed in (0,1,42,4294967295):
                process=subprocess.run([sys.executable,str(Path(__file__).with_name('native_cpython_set_reference.py')),mode],env={**os.environ,'PYTHONHASHSEED':str(seed)},capture_output=True,text=True,timeout=30)
                if process.returncode:raise AssertionError(process.stderr)
                cls.oracles[(mode,seed)]=json.loads(process.stdout)
        from py2fastrust.native_cpython_hash import RUNTIME as HASH
        from py2fastrust.native_cpython_set_runtime import RUNTIME as SET
        branches=[]
        for mode in ('i64','i128','bigint'):
            rows=[]
            for key in cls.oracles[(mode,0)]['keys']:
                rows.append('TestKey{label:'+rust_text(key['representation'])+'.to_owned(),canonical:'+rust_text(json.dumps(canonical(key['value']),ensure_ascii=False,separators=(',',':')))+'.to_owned(),hash:'+hash_code(key['value'])+'}')
            branches.append(rust_text(mode)+'=>vec!['+','.join(rows)+']')
        keys='fn keys(mode:&str,seed:u32)->Vec<TestKey>{let secret=NativeCPHashSecret::from_seed(seed);match mode{'+','.join(branches)+',_=>panic!("unknown mode")}}'
        runner=Path(__file__).with_name('native_cpython_set_runner.rs').read_text()
        source=HASH+'\n'+SET+'\n'+keys+'\n'+runner
        cls.rust=cls.root/'kernel.rs';cls.rust.write_text(source)
        cls.binaries=[]
        for optimized in (False,True):
            binary=cls.root/('optimized'if optimized else'debug')
            built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(cls.rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            if built.returncode:raise AssertionError(built.stderr)
            cls.binaries.append(binary)
        cls.hashes_source=HASH+'\n'+keys+'\nstruct TestKey{label:String,canonical:String,hash:i64}\nfn main(){let args:Vec<_>=std::env::args().collect();for key in keys(&args[1],args[2].parse().unwrap()){println!("{}",key.hash);}}'

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def test_hashes_all_seed_and_integer_modes(self):
        source=self.root/'hashes.rs';source.write_text(self.hashes_source)
        for optimized in (False,True):
            binary=self.root/('hashes_optimized'if optimized else'hashes_debug')
            built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            for (mode,seed),oracle in self.oracles.items():
                actual=subprocess.run([str(binary),mode,str(seed)],capture_output=True,text=True,timeout=10)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual([int(x)for x in actual.stdout.splitlines()],[x['hash']for x in oracle['keys']],(mode,seed,optimized))

    def test_table_histories_all_seed_and_integer_modes(self):
        for (mode,seed),oracle in self.oracles.items():
            commands=[];expected=[]
            for case in oracle['cases']:
                commands.append('RESET')
                for command,args in case['operations']:
                    fields=[]
                    for argument in args:fields.extend(str(x)for x in argument)if isinstance(argument,list)else fields.append(str(argument))
                    commands.append(command+' '+' '.join(fields))
                for event in case['events']:
                    if event[0]=='state':
                        for name,capacity,keys in event[1]:expected.append('STATE|'+name+'|'+str(capacity)+'|'+'\x1f'.join(keys))
                        expected.append('END')
                    else:expected.append('|'.join(map(str,event)))
            commands.append('LARGE')
            for name,event in oracle['large'].items():expected.append('LARGE|'+name+'|'+str(event[0])+'|'+str(len(event[1]))+'|'+str(digest(event[1])))
            for binary in self.binaries:
                actual=subprocess.run([str(binary),mode,str(seed)],input='\n'.join(commands)+'\n',capture_output=True,text=True,timeout=30)
                self.assertEqual(actual.returncode,0,actual.stderr)
                actual_lines=actual.stdout.split('\n')[:-1]
                self.assertEqual(actual_lines,expected,(mode,seed,binary.name))

    def test_live_cursors_all_seed_and_integer_modes(self):
        for (mode,seed),oracle in self.oracles.items():
            commands=[];expected=[]
            for case in oracle['cursor_cases']:
                commands.append('RESET');expected.extend(case['events'])
                for command,args in case['operations']:
                    fields=[]
                    for argument in args:fields.extend(str(x)for x in argument)if isinstance(argument,list)else fields.append(str(argument))
                    commands.append(command+' '+' '.join(fields))
            for binary in self.binaries:
                actual=subprocess.run([str(binary),mode,str(seed),'cursor'],input='\n'.join(commands)+'\n',capture_output=True,text=True,timeout=30)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout.split('\n')[:-1],expected,(mode,seed,binary.name))

    def test_checked_table_and_physical_key_ownership_invariants(self):
        from py2fastrust.native_cpython_set_runtime import RUNTIME
        source=self.root/'invariants.rs';source.write_text(RUNTIME+'\n'+Path(__file__).with_name('native_cpython_set_invariants.rs').read_text())
        for optimized in (False,True):
            binary=self.root/('invariants_optimized'if optimized else'invariants_debug')
            built=subprocess.run(['rustc','--edition=2021','--test',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            actual=subprocess.run([str(binary),'--test-threads=1'],capture_output=True,text=True,timeout=10)
            self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
            self.assertIn('4 passed; 0 failed',actual.stdout)

    def test_actual_helpers_survive_source_pruning_without_unused_hash_code(self):
        from py2fastrust.native_cpython_hash import RUNTIME as HASH
        from py2fastrust.native_cpython_set_runtime import RUNTIME as SET
        from py2fastrust.rust_pruning import prune_rust_source_with_report
        main='fn main(){let mut set=NativeCPSet::new();set.add(7i64,7i64,native_cp_hash_integer(7)).unwrap();let copied=set.copy_set().unwrap();assert_eq!(copied.len(),1);assert!(copied.contains(&7,native_cp_hash_integer(7)));let owner=std::rc::Rc::new(std::cell::RefCell::new(set));let mut cursor=NativeCPSetCursor::new(owner);assert_eq!(cursor.next().unwrap(),Some(7));assert_eq!(cursor.next().unwrap(),None);}'
        result=prune_rust_source_with_report(HASH+'\n'+SET+'\n'+main)
        self.assertIsNone(result.reason)
        self.assertNotIn('fn native_cp_hash_text',result.source)
        self.assertNotIn('fn native_cp_sip_round',result.source)
        self.assertIn('fn native_cp_hash_integer',result.source)
        source=self.root/'pruned.rs';source.write_text(result.source)
        for optimized in (False,True):
            binary=self.root/('pruned_optimized'if optimized else'pruned_debug')
            built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)
            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
