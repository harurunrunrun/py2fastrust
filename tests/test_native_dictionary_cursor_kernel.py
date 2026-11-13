"""CP-first mutation histories check typed cursor hints and retained owners."""
import operator
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest


def products():
    from py2fastrust.native_mapping_views import CURSORS
    from py2fastrust.native_ordered_entries import POSITIONED_HELPERS,POPITEM_HELPER
    from py2fastrust.native_key_containers import HELPERS
    rng=random.Random(3141408);functions=[];expected=[];histories=[]
    for case in range(40):
        mapping=dict((i,10*i)for i in range(rng.randrange(1,9)));alias=mapping;cursor=iter(mapping)
        code=['let mut owner=Rc::new(RefCell::new(NativeKeyDict::<i64,i64,i64>::new()));']
        code += [f'owner.borrow_mut().set({k},{k},{v}).unwrap();'for k,v in mapping.items()]
        code += ['let alias=owner.clone();let mut cursor=ClassMappingCursor::new(owner.clone());'];history=[]
        for step in range(40):
            action=rng.choice(['reset']*4+['next']*5+['replace']*4+['set','delete','copy','constructor','pop','rebuild','alias_set']);result='';statement='';operands=[]
            if action=='reset':cursor=iter(mapping);statement='cursor=ClassMappingCursor::new(owner.clone());'
            elif action=='next':
                try:result=str(next(cursor))
                except StopIteration:result='stop'
                except RuntimeError as error:result='RuntimeError: '+str(error)
                statement='outcome=match cursor.next(|key,_|*key){Ok(Some(value))=>value.to_string(),Ok(None)=>"stop".to_owned(),Err(error)=>error};'
            elif action in {'set','alias_set'}:
                key,value=rng.randrange(-10,22),rng.randrange(-20,30);target=mapping if action=='set'else alias;target[key]=value;operands=[key,value];target='owner'if action=='set'else'alias';statement=f'{target}.borrow_mut().set({key},{key},{value}).unwrap();'
            elif action=='delete':
                key=rng.randrange(-10,22);mapping.pop(key,None);operands=[key];statement=f'owner.borrow_mut().delete(&{key});'
            elif action=='replace':
                key=rng.choice(list(mapping))if mapping else 1;new=1000+case*100+step;mapping.pop(key,None);mapping[new]=new;operands=[key,new];statement=f'owner.borrow_mut().delete(&{key});owner.borrow_mut().set({new},{new},{new}).unwrap();'
            elif action in {'copy','constructor'}:
                mapping=mapping.copy()if action=='copy'else dict(mapping)
                statement=('{let mut copied=owner.borrow().clone();copied.entries.prepare_python_copy().unwrap();owner=Rc::new(RefCell::new(copied));}'if action=='copy'else'{let result=Rc::new(RefCell::new(NativeKeyDict::<i64,i64,i64>::new()));{let read=owner.borrow();result.borrow_mut().entries.prepare_mapping_seed(&read.entries).unwrap();for(key,value)in read.entries.iter(){result.borrow_mut().set(*key,*key,*value).unwrap();}}owner=result;}')
            elif action=='pop':
                if mapping:mapping.popitem();statement='{let mut read=owner.borrow_mut();let read=&mut *read;native_dict_popitem(&mut read.entries,&mut read.index,|key|*key).unwrap();}'
            else:
                count=len(mapping);mapping.clear();operands=[count];statement='owner.borrow_mut().clear();'
                for k in range(count):
                    key=20000+case*100+k;mapping[key]=key;statement+=f'owner.borrow_mut().set({key},{key},{key}).unwrap();'
            hint=operator.length_hint(cursor,8);expected.append(f'{case}:{step}|{hint}|{result}');history.append({'action':action,'operands':operands,'hint':hint,'next_result':result})
            code += ['{let mut outcome=String::new();',statement,f'println!("{case}:{step}|{{}}|{{}}",cursor.length_hint(),outcome);}}']
        functions.append(f'fn case_{case}(){{'+''.join(code)+'}');histories.append(history)
    roots=r'''
fn roots(){
 let owner=Rc::new(RefCell::new(NativeKeyDict::<i64,i64,i64>::new()));for key in 0..3{owner.borrow_mut().set(key,key,key).unwrap();}
 let weak=Rc::downgrade(&owner);let mut cursor=ClassMappingCursor::new(owner.clone());cursor.next(|key,_|*key).unwrap();owner.borrow_mut().delete(&0);owner.borrow_mut().set(9,9,9).unwrap();drop(owner);
 cursor.next(|key,_|*key).unwrap();cursor.next(|key,_|*key).unwrap();assert_eq!(cursor.next(|key,_|*key).unwrap_err(),"RuntimeError: dictionary keys changed during iteration");assert_eq!(cursor.length_hint(),0);assert!(weak.upgrade().is_none());assert!(cursor.next(|key,_|*key).unwrap().is_none());
 let owner=Rc::new(RefCell::new(NativeKeyDict::<i64,i64,i64>::new()));owner.borrow_mut().set(1,1,1).unwrap();let weak=Rc::downgrade(&owner);let mut cursor=ClassMappingCursor::new(owner.clone());owner.borrow_mut().set(2,2,2).unwrap();drop(owner);
 assert_eq!(cursor.length_hint(),0);assert_eq!(cursor.next(|key,_|*key).unwrap_err(),"RuntimeError: dictionary changed size during iteration");assert!(weak.upgrade().is_some());drop(cursor);assert!(weak.upgrade().is_none());
}
'''
    rust='#![allow(dead_code,unused_mut,unused_assignments)]\nuse std::rc::Rc;use std::cell::RefCell;\n'+POSITIONED_HELPERS+POPITEM_HELPER+HELPERS+CURSORS+''.join(functions)+roots+'fn main(){roots();'+''.join(f'case_{i}();'for i in range(40))+'}'
    return rust,'\n'.join(expected)+'\n',histories


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class DictionaryCursorKernelTests(unittest.TestCase):
    def test_remaining_hint_errors_and_retained_roots(self):
        rust,expected,_=products()
        with tempfile.TemporaryDirectory(prefix='pytors-dict-cursor-')as directory:
            source=Path(directory)/'kernel.rs';source.write_text(rust)
            for optimized in (False,True):
                binary=Path(directory)/('opt'if optimized else'debug');built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120);self.assertEqual(built.returncode,0,built.stderr)
                result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10);self.assertEqual((result.returncode,result.stdout,result.stderr),(0,expected,''))

if __name__=='__main__':unittest.main()
