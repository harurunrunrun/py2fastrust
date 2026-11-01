"""The typed sorting kernel matches CPython's comparisons and partial errors."""
import functools
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_cmp_sorting import kernel


@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class NativeComparisonKernel(unittest.TestCase):
    def test_exposed_wrapper_protocol_diagnostics_name_the_missing_operation(self):
        sources=(('key(3)','construction'),('key.obj','attributes'))
        for expression,missing in sources:
            source='from functools import cmp_to_key\nkey=cmp_to_key(lambda a,b:a-b)\nprint('+expression+')\n'
            result=transpile(source,TranspileOptions(filename='wrapper_case.py',license='none'))
            self.assertFalse(result.success)
            self.assertIn('functools.KeyWrapper',result.diagnostics[0].message)
            self.assertIn(missing,result.diagnostics[0].message)
            self.assertEqual(result.diagnostics[0].line,3)

    def test_sync_async_schedules_and_partial_permutations(self):
        cases=[]
        for size in (7,64,129,513):
            values=[(i*37)%61 for i in range(size)]
            for reverse in (False,True):
                for stop in (0,7,100):
                    events=[];order=list(range(size));failed=False
                    def compare(a,b):
                        events.append((a,b))
                        if len(events)==stop:raise ArithmeticError('injected')
                        return values[a]-values[b]
                    try:order.sort(key=functools.cmp_to_key(compare),reverse=reverse)
                    except ArithmeticError:failed=True
                    cases.append((values,reverse,stop,events,order,failed))
        data=[]
        for values,reverse,stop,events,order,failed in cases:
            data.append('(vec!'+repr(values)+','+str(reverse).lower()+','+str(stop)+
                        ',vec!'+repr(events)+',vec!'+repr(order)+','+str(failed).lower()+')')
        with tempfile.TemporaryDirectory(prefix='pytors-cmp-kernel-')as directory:
            for asynchronous in (False,True):
                body=('let cases:Vec<(Vec<i64>,bool,usize,Vec<(usize,usize)>,Vec<usize>,bool)>=vec!['+','.join(data)+'];'+
                    'for(index,(values,reverse,stop,expected_events,expected_order,expected_error))in cases.into_iter().enumerate(){'+
                    'let mut events=Vec::new();let(mut order,error)=native_cmp_sort_indices'+('_async'if asynchronous else'')+
                    '(values.len(),reverse,'+('async 'if asynchronous else'')+'|a,b|{events.push((a,b));'+
                    'if events.len()==stop{return Err("injected");}Ok(values[a]<values[b])},||"memory")'+
                    ('.await'if asynchronous else'')+'.unwrap();assert_eq!(order,expected_order,"order {}",index);'+
                    'assert_eq!(events,expected_events,"events {}",index);assert_eq!(error.is_some(),expected_error,"error {}",index);'+
                    'let mut moved:Vec<_>=(0..values.len()).collect();native_cmp_sort_apply(&mut moved,&mut order);'+
                    'assert_eq!(moved,expected_order,"move {}",index);}')
                source=kernel(asynchronous=asynchronous)
                if asynchronous:
                    source+='\nfn execute<F:std::future::Future>(f:F)->F::Output{let w=std::task::Waker::noop();let mut cx=std::task::Context::from_waker(w);let mut f=std::pin::pin!(f);loop{if let std::task::Poll::Ready(v)=f.as_mut().poll(&mut cx){return v;}}}\nfn main(){execute(async{'+body+'});}'
                else:source+='\nfn main(){'+body+'}'
                rust=Path(directory,('async'if asynchronous else'sync')+'.rs');rust.write_text(source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)

    def test_sorting_notice_follows_retained_helpers(self):
        source='from functools import cmp_to_key\nprint(sorted([3,1,2],key=cmp_to_key(lambda a,b:a-b)))\n'
        result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertIn('CPython-derived stable sorting',result.rust_source)
        self.assertEqual(result.rust_source.count('PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2'),1)
        plain=transpile('print(7)\n',TranspileOptions(license='none'))
        self.assertTrue(plain.success,plain.diagnostics)
        self.assertNotIn('CPython-derived stable sorting',plain.rust_source)
        self.assertNotIn('PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2',plain.rust_source)
