"""Exercise both observed Python 3.14 ExceptionGroup representation profiles."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions,transpile
import test_runtime


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ExceptionGroupReprProfileTests(unittest.TestCase):
    run_source=test_runtime.RuntimeTests.run_source
    maxDiff=None

    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-eg-profile-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root=Path(cls.directory.name);cls.binaries={}
        result=transpile('import sys\nexec(sys.argv[1])\n',TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        pattern=r'const EG_REPR_USES_EXCEPTIONS_TUPLE: bool = (?:true|false);'
        if len(re.findall(pattern,result.rust_source))!=1:raise AssertionError('missing unique generated profile flag')
        for canonical_tuple in [False,True]:
            source=re.sub(pattern,'const EG_REPR_USES_EXCEPTIONS_TUPLE: bool = '+str(canonical_tuple).lower()+';',result.rust_source)
            target=cls.root/(str(canonical_tuple)+'.rs');target.write_text(source)
            binary=target.with_suffix('')
            built=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            if built.returncode:raise AssertionError(built.stderr)
            cls.binaries[canonical_tuple]=binary

    def check_profiles(self,source,expected):
        source=textwrap.dedent(source)
        for flag,binary in self.binaries.items():
            with self.subTest(canonical_tuple=flag):
                actual=subprocess.run([str(binary),source],capture_output=True,text=True,timeout=15)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout,expected(flag))

    def test_extra_constructor_arguments_only_change_native_group_repr(self):
        source='''
            class Group(ExceptionGroup):
                def __new__(cls,message,errors,marker):return super().__new__(cls,message,errors)
            errors=[ValueError('v'),TypeError('t')]
            group=Group('custom',errors,17)
            print(repr(group))
            print(group.args[1] is errors,type(group.args[1]).__name__,len(group.args),len(group.exceptions))
            print(BaseException.__repr__(group))
            errors.append(KeyError('late'))
            print(repr(group))
            print(len(group.args[1]),len(group.exceptions))
        '''
        def expected(flag):
            sequence="(ValueError('v'), TypeError('t'))"if flag else"[ValueError('v'), TypeError('t')]"
            group="Group('custom', "+sequence+")\n"
            return group+"True list 3 2\nGroup('custom', [ValueError('v'), TypeError('t')], 17)\n"+group+"3 2\n"
        self.check_profiles(source,expected)
        self.run_source(source)

    def test_two_argument_list_compatibility_and_tuple_canonicalization(self):
        source='''
            class List(list):
                def __repr__(self):return 'LIST-OVERRIDE'
            group=ExceptionGroup('original',[ValueError('v')])
            for args in [('changed',List([KeyError('decoy')]),99),
                         ('changed',(KeyError('decoy'),),99),
                         ('changed',List([KeyError('decoy')])),
                         ('changed',List([KeyError('decoy')]),99,100)]:
                group.args=args
                print(repr(group))
                print(group.args is args)
        '''
        def expected(flag):
            canonical="ExceptionGroup('original', (ValueError('v'),))\nTrue\n"
            compatibility="ExceptionGroup('original', [ValueError('v')])\nTrue\n"
            return (canonical if flag else compatibility)+canonical+compatibility+(canonical if flag else compatibility)
        self.check_profiles(source,expected)
        self.run_source(source)

    def test_custom_repr_override_still_wins_and_base_descriptor_uses_profile(self):
        source='''
            class Group(ExceptionGroup):
                def __new__(cls,message,errors,marker):return super().__new__(cls,message,errors)
                def __repr__(self):return 'OVERRIDE'
            group=Group('custom',[ValueError('v')],17)
            print(repr(group))
            print(BaseExceptionGroup.__repr__(group))
            print(BaseException.__repr__(group))
        '''
        def expected(flag):
            native="Group('custom', (ValueError('v'),))"if flag else"Group('custom', [ValueError('v')])"
            return 'OVERRIDE\n'+native+"\nGroup('custom', [ValueError('v')], 17)\n"
        self.check_profiles(source,expected)
        self.run_source(source)

    def test_custom_sequence_representation_is_captured_once_at_construction(self):
        source='''
            import gc
            events=[]
            class Sequence:
                def __len__(self):return 1
                def __getitem__(self,index):
                    if index==0:return ValueError('v')
                    raise IndexError
                def __repr__(self):events.append('repr');gc.collect();return 'SAVED-SEQUENCE'
                def __del__(self):events.append('final')
            source=Sequence();group=ExceptionGroup('custom',source)
            print(events);events.clear()
            print(repr(group),events)
            group.args=('changed',[],17);del source;gc.collect()
            print(repr(group),events)
        '''
        expected="['repr']\nExceptionGroup('custom', SAVED-SEQUENCE) []\nExceptionGroup('custom', SAVED-SEQUENCE) ['final']\n"
        self.check_profiles(source,lambda flag:expected)
        self.run_source(source)


if __name__=='__main__':unittest.main()
