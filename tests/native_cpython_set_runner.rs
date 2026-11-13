use std::collections::BTreeMap;
use std::io::{self,Read};
struct TestKey {label:String,canonical:String,hash:i64}
fn show(sets:&BTreeMap<String,NativeCPSet<String,String>>) {
    for (name,set)in sets {
        let values:Vec<_>=set.entries().map(|(key,_,_)|key.as_str()).collect();
        println!("STATE|{}|{}|{}",name,set.capacity(),values.join("\u{1f}"));
    }
    println!("END");
}
fn large_state(name:&str,set:&NativeCPSet<i64,i64>) {
    let mut digest=14695981039346656037u64;
    for (key,_,_)in set.entries() {
        for byte in key.to_le_bytes() {digest=(digest^byte as u64).wrapping_mul(1099511628211);}
    }
    println!("LARGE|{}|{}|{}|{}",name,set.capacity(),set.len(),digest);
}
fn main() {
    let arguments:Vec<_>=std::env::args().collect();
    let pool=keys(&arguments[1],arguments[2].parse().unwrap());
    let mut input=String::new();io::stdin().read_to_string(&mut input).unwrap();
    if arguments.get(3).map(|value|value.as_str())==Some("cursor") {run_cursors(pool,&input);return;}
    let mut sets:BTreeMap<String,NativeCPSet<String,String>>=BTreeMap::new();
    for line in input.lines() {
        let fields:Vec<_>=line.split_whitespace().collect();
        let command=fields[0];
        if command=="RESET" {sets.clear();continue;}
        if command=="LARGE" {
            let mut set=NativeCPSet::new();
            for value in 0i64..80010 {set.add(value,value,native_cp_hash_integer(value as i128)).unwrap();}
            large_state("before",&set);
            for value in (0i64..80010).step_by(2) {assert!(set.discard(&value,native_cp_hash_integer(value as i128)));}
            large_state("after",&set);let copy=set.copy_set().unwrap();large_state("copy",&copy);
            let mut merged=NativeCPSet::new();merged.merge(&set).unwrap();large_state("update",&merged);continue;
        }
        let name=fields[1].to_owned();
        let indices=||fields[2..].iter().map(|text|text.parse::<usize>().unwrap()).collect::<Vec<_>>();
        match command {
            "empty"=>{sets.insert(name,NativeCPSet::new());},
            "new"=>{
                let mut set=NativeCPSet::new();
                for index in indices(){let key=&pool[index];set.add(key.label.clone(),key.canonical.clone(),key.hash).unwrap();}
                sets.insert(name,set);
            },
            "add"=>{let key=&pool[indices()[0]];sets.get_mut(&name).unwrap().add(key.label.clone(),key.canonical.clone(),key.hash).unwrap();},
            "discard"|"remove"=>{
                let index=indices()[0];let key=&pool[index];
                let found=sets.get_mut(&name).unwrap().discard(&key.canonical,key.hash);
                if command=="remove"&&!found {println!("KeyError|{}|{}",name,index);}
            },
            "clear"=>sets.get_mut(&name).unwrap().clear(),
            "copy"|"from_set"=>{let copy=sets[fields[2]].copy_set().unwrap();sets.insert(name,copy);},
            "update_set"=>{
                if name!=fields[2] {
                    let other=sets.remove(fields[2]).unwrap();sets.get_mut(&name).unwrap().merge(&other).unwrap();sets.insert(fields[2].to_owned(),other);
                }
            },
            "update_dict"|"update_iter"=>{
                let mut indices=indices();
                if command=="update_dict" {
                    let mut seen=std::collections::HashSet::new();indices.retain(|&index|seen.insert(&pool[index].canonical));
                    sets.get_mut(&name).unwrap().prepare_dict_update(indices.len()).unwrap();
                }
                for index in indices {let key=&pool[index];sets.get_mut(&name).unwrap().add(key.label.clone(),key.canonical.clone(),key.hash).unwrap();}
            },
            "pop"=>match sets.get_mut(&name).unwrap().pop(){Ok(key)=>println!("pop|{}|{}",name,key),Err(_)=>println!("KeyError-pop|{}",name)},
            _=>panic!("unknown test instruction"),
        }
        show(&sets);
    }
}
fn run_cursors(pool:Vec<TestKey>,input:&str) {
    use std::rc::{Rc,Weak};use std::cell::RefCell;
    let mut sets:BTreeMap<String,Rc<RefCell<NativeCPSet<String,String>>>>=BTreeMap::new();
    let mut cursors:BTreeMap<String,Rc<RefCell<NativeCPSetCursor<String,String>>>>=BTreeMap::new();
    let mut weak:BTreeMap<String,Weak<RefCell<NativeCPSet<String,String>>>>=BTreeMap::new();
    for line in input.lines() {
        let fields:Vec<_>=line.split_whitespace().collect();let command=fields[0];
        if command=="RESET" {sets.clear();cursors.clear();weak.clear();continue;}
        let name=fields[1].to_owned();
        match command {
            "new"=>{
                let mut set=NativeCPSet::new();
                for field in &fields[2..] {let key=&pool[field.parse::<usize>().unwrap()];set.add(key.label.clone(),key.canonical.clone(),key.hash).unwrap();}
                sets.insert(name,Rc::new(RefCell::new(set)));
            },
            "iter"=>{let cursor=NativeCPSetCursor::new(sets[fields[2]].clone());cursors.insert(name,Rc::new(RefCell::new(cursor)));},
            "alias"=>{let value=cursors[fields[2]].clone();cursors.insert(name,value);},
            "add"=>{let key=&pool[fields[2].parse::<usize>().unwrap()];sets[&name].borrow_mut().add(key.label.clone(),key.canonical.clone(),key.hash).unwrap();},
            "discard"=>{let key=&pool[fields[2].parse::<usize>().unwrap()];sets[&name].borrow_mut().discard(&key.canonical,key.hash);},
            "clear"=>sets[&name].borrow_mut().clear(),
            "drop_set"=>{sets.remove(&name);},
            "drop_iter"=>{cursors.remove(&name);},
            "weak"=>{weak.insert(name,Rc::downgrade(&sets[fields[2]]));},
            "alive"=>println!("ALIVE|{}|{}",name,usize::from(weak[&name].upgrade().is_some())),
            "hint"=>{let hint=cursors[&name].borrow().length_hint();if hint<0 {println!("HINTERROR|{}|ValueError",name);}else{println!("HINT|{}|{}",name,hint);}},
            "next"=>match cursors[&name].borrow_mut().next() {
                Ok(Some(value))=>println!("YIELD|{}|{}",name,value),Ok(None)=>println!("STOP|{}",name),
                Err(error)=>{let (kind,message)=error.split_once(": ").unwrap();println!("ERROR|{}|{}|{}",name,kind,message);},
            },
            _=>panic!("unknown cursor test instruction"),
        }
    }
}
