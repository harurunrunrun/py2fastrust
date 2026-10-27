"""Native continuation storage is independent from the Python frame limit."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ProtocolResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='py2fastrust-protocol-resources-')
        root=Path(cls.directory.name)
        result=transpile('import sys\nexec(sys.stdin.read())\n',TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        text=result.rust_source
        marker='const PROTOCOL_ACTION_STORAGE_LIMIT:usize=64*1024*1024;'
        if text.count(marker)!=1:raise AssertionError('expected one continuation storage bound')
        cls.binaries={}
        for name,source,extra in [
            ('default',text,[]),
            ('reduced',text.replace(marker,'const PROTOCOL_ACTION_STORAGE_LIMIT:usize=4096;'),[]),
            ('storage',text+'''
#[test]
fn check_actual_default_protocol_storage_bound() {
    assert_eq!(PROTOCOL_ACTION_STORAGE_LIMIT,64*1024*1024);
    let mut actions=ProtocolActions::new();
    while actions.bytes<=PROTOCOL_ACTION_STORAGE_LIMIT {actions.push_front(ProtocolAction::Pass);}
    assert_eq!(actions.check_budget().unwrap_err().kind,"RecursionError");
    actions.pop_front();
    assert!(actions.check_budget().is_ok());
    let before=actions.bytes;
    actions.push_front(ProtocolAction::Operand(Box::new(ProtocolOperand{
        op:"==".into(),left:Value::None,right:Value::None,
        kind:ProtocolOperandKind::Comparison{phase:0,reverse:false},
    })));
    assert_eq!(actions.bytes-before,std::mem::size_of::<ProtocolAction>()+std::mem::size_of::<ProtocolOperand>());
    actions.clear();assert_eq!(actions.bytes,0);
}
''',['--test']),
        ]:
            path=root/(name+'.rs');path.write_text(source,encoding='utf-8')
            binary=root/name
            compiled=subprocess.run(['rustc','--edition=2021',*extra,str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            if compiled.returncode:raise AssertionError(compiled.stderr)
            cls.binaries[name]=binary

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def test_actual_default_action_storage_guard_and_accounting(self):
        result=subprocess.run([str(self.binaries['storage'])],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertIn('test result: ok',result.stdout)

    def test_reduced_native_guard_unwinds_to_caller_without_charging_python_frames(self):
        source=textwrap.dedent('''
            import sys,gc
            sys.setrecursionlimit(50)
            calls=0
            class Element:
                def __eq__(self,other):
                    global calls
                    calls+=1
                    return True
            left=[Element()];left.append(left)
            right=[Element()];right.append(right)
            try:left==right
            except RecursionError:print('native guard',sys.getrecursionlimit(),calls>0)
            gc.collect()
            calls=0
            class Stateful:
                def __eq__(self,other):
                    global calls
                    calls+=1
                    if calls==3:left[1]=right[1]
                    return True
            left=[Stateful()];left.append(left)
            right=[Stateful()];right.append(right)
            print(left==right,calls)
        ''')
        actual=subprocess.run([str(self.binaries['reduced'])],input=source,capture_output=True,text=True,timeout=20)
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=20)
        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+expected.stderr)
        self.assertEqual(actual.stdout,expected.stdout)

    def test_ten_thousand_finite_native_levels_exceed_python_limit_safely(self):
        source=textwrap.dedent('''
            import sys
            sys.setrecursionlimit(50)
            left,right=0,1
            for i in range(10000):left=[left];right=[right]
            print('finite',left==right,sys.getrecursionlimit())
        ''')
        actual=subprocess.run([str(self.binaries['default'])],input=source,capture_output=True,text=True,timeout=90)
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=20)
        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+expected.stderr)
        self.assertEqual(actual.stdout,expected.stdout)
