
import dis,json,sys
P=2**61-1
def encode(v):
 if v is None:return ['none',None]
 if type(v) is bool:return ['bool',v]
 if type(v) is int:return ['int',str(v)]
 if type(v) is str:return ['str',v]
 if type(v) is bytes:return ['bytes',list(v)]
 if type(v) is tuple:return ['tuple',[encode(x)for x in v]]
 raise AssertionError(type(v))
def capacity(s):
 n=s.__sizeof__()-set().__sizeof__()
 assert n%16==0
 return n//16 if n else 8
keys=[None,False,True,0,1,-1,-2,7,-7,P,P+1,-P,-P-1,2**63-1,-2**63,2**127-1,-2**127,2**200+123,-2**200-123,'','a','abc','abcdefgh','abcdefghi','é','Ā','😀','éĀ😀','\\\"\n',b'',b'a',bytes(range(32)),(),(1,True),(None,'é'),((1,2),(3,None)),tuple(range(17))]
keys += [i*P for i in range(2,18)]
keys += [bytes((i*37+11)%256 for i in range(length))for length in (*range(18),31,32,33,63,64,65,255,256,257,511,512)]
keys += ['\x00','\xff','\u0100','\uffff','\U00010000','a\x00é','é'*17,'Ā'*17,'😀'*17,tuple(),tuple([None]*19)]
mode=sys.argv[1]if len(sys.argv)>1 else 'bigint'
def normalize(value):
 if type(value) is int and mode!='bigint':
  bits=int(mode[1:]);return (value+2**(bits-1))%2**bits-2**(bits-1)
 if type(value) is tuple:return tuple(normalize(x)for x in value)
 return value
keys=[normalize(x)for x in keys]

import operator,weakref
cursor_cases=[]
def cursor_history(name,operations):
 sets={};cursors={};weak={};events=[]
 for command,args in operations:
  if command=='new':sets[args[0]]=set(keys[i]for i in args[1])
  elif command=='iter':cursors[args[0]]=iter(sets[args[1]])
  elif command=='alias':cursors[args[0]]=cursors[args[1]]
  elif command=='add':sets[args[0]].add(keys[args[1]])
  elif command=='discard':sets[args[0]].discard(keys[args[1]])
  elif command=='clear':sets[args[0]].clear()
  elif command=='drop_set':del sets[args[0]]
  elif command=='drop_iter':del cursors[args[0]]
  elif command=='weak':weak[args[0]]=weakref.ref(sets[args[1]])
  elif command=='alive':events.append('ALIVE|'+args[0]+'|'+str(int(weak[args[0]]()is not None)))
  elif command=='hint':
   try:events.append('HINT|'+args[0]+'|'+str(operator.length_hint(cursors[args[0]])))
   except Exception as error:events.append('HINTERROR|'+args[0]+'|'+type(error).__name__)
  elif command=='next':
   try:events.append('YIELD|'+args[0]+'|'+repr(next(cursors[args[0]])))
   except StopIteration:events.append('STOP|'+args[0])
   except Exception as error:events.append('ERROR|'+args[0]+'|'+type(error).__name__+'|'+str(error))
  else:raise AssertionError(command)
 cursor_cases.append(dict(name=name,operations=operations,events=events))
cursor_history('physical_table_order',[('new',['s',list(range(len(keys)))]),('iter',['i','s'])]+sum(([('hint',['i']),('next',['i'])]for _ in range(len(keys)+2)),[]))
cursor_history('sticky_size_error_retains_owner',[('new',['s',[]]),('iter',['i','s']),('weak',['w','s']),('add',['s',7]),('next',['i']),('discard',['s',7]),('next',['i']),('hint',['i']),('drop_set',['s']),('alive',['w']),('drop_iter',['i']),('alive',['w'])])
cursor_history('empty_exhaustion_releases_owner',[('new',['s',[]]),('iter',['i','s']),('weak',['w','s']),('next',['i']),('add',['s',7]),('next',['i']),('drop_set',['s']),('alive',['w'])])
cursor_history('last_yield_keeps_owner',[('new',['s',[7]]),('iter',['i','s']),('weak',['w','s']),('next',['i']),('drop_set',['s']),('alive',['w']),('next',['i']),('alive',['w'])])
cursor_history('stored_cursor_alias',[('new',['s',[7,8,5,6]]),('iter',['i','s']),('alias',['j','i']),('next',['j']),('hint',['i']),('next',['i']),('next',['j']),('hint',['j']),('drop_iter',['i']),('next',['j']),('next',['j'])])
cursor_history('same_size_clear_and_reinsert',[('new',['s',[7,8,5,6]]),('iter',['i','s']),('next',['i']),('clear',['s'])]+[('add',['s',index])for index in [52,51,50,49]]+[('hint',['i'])]+[('next',['i'])for _ in range(7)])
cursor_history('same_size_rehash',[('new',['s',list(range(37,53))]),('iter',['i','s']),('next',['i'])]+sum(([('discard',['s',37+i]),('add',['s',7+i]),('hint',['i']),('next',['i'])]for i in range(12)),[])+[('next',['i'])for _ in range(20)])

pool=[dict(value=encode(v),hash=hash(v),representation=repr(v))for v in keys]
cases=[]
def history(name,ops):
 sets={};events=[]
 for op,args in ops:
  if op=='new':sets[args[0]]=set(keys[i]for i in args[1])
  elif op=='empty':sets[args[0]]=set()
  elif op=='add':sets[args[0]].add(keys[args[1]])
  elif op=='discard':sets[args[0]].discard(keys[args[1]])
  elif op=='remove':
   try:sets[args[0]].remove(keys[args[1]])
   except KeyError:events.append(['KeyError',args[0],args[1]])
  elif op=='clear':sets[args[0]].clear()
  elif op=='copy':sets[args[0]]=sets[args[1]].copy()
  elif op=='from_set':sets[args[0]]=set(sets[args[1]])
  elif op=='update_set':sets[args[0]].update(sets[args[1]])
  elif op=='update_dict':sets[args[0]].update(dict.fromkeys(keys[i]for i in args[1]))
  elif op=='update_iter':sets[args[0]].update(keys[i]for i in args[1])
  elif op=='pop':
   try:events.append(['pop',args[0],repr(sets[args[0]].pop())])
   except KeyError:events.append(['KeyError-pop',args[0]])
  else:raise AssertionError(op)
  events.append(['state',[[n,capacity(s),[repr(v)for v in s]]for n,s in sorted(sets.items())]])
 cases.append(dict(name=name,operations=ops,events=events))
history('representatives_and_collisions',[('empty',['a'])]+[('add',['a',i])for i in range(len(keys))]+[('discard',['a',i])for i in range(0,len(keys),3)]+[('add',['a',i])for i in reversed(range(len(keys)))])
history('bulk_copy_tombstones',[('new',['a',list(range(len(keys)))]),('copy',['b','a']),('from_set',['c','a'])]+[('discard',['a',i])for i in range(0,len(keys),2)]+[('copy',['d','a']),('from_set',['e','a']),('update_set',['b','a']),('update_set',['a','a']),('clear',['c']),('update_set',['c','a']),('update_dict',['d',list(reversed(range(len(keys))))]),('update_iter',['e',list(reversed(range(len(keys))))])])
history('empty_clear_pop',[('empty',['a']),('copy',['b','a']),('pop',['a']),('new',['a',[7,8,5,6]]),('pop',['a']),('clear',['a']),('new',['b',[36,35,34,33,32]]),('update_set',['a','b']),('pop',['a']),('clear',['b']),('update_set',['b','a'])])
import random
r=random.Random(20261113)
ops=[('empty',[n])for n in ('a','b','c')]
for _ in range(300):
 name=r.choice(('a','b','c'));op=r.choice(('add','discard','remove','clear','copy','from_set','update_set','update_dict','update_iter','pop'))
 if op in ('add','discard','remove'):args=[name,r.randrange(len(keys))]
 elif op in ('copy','from_set','update_set'):args=[name,r.choice(('a','b','c'))]
 elif op in ('update_dict','update_iter'):args=[name,[r.randrange(len(keys))for _ in range(r.randrange(24))]]
 else:args=[name]
 ops.append((op,args))
history('seeded_mixed_histories',ops)
large=set()
for i in range(80010):large.add(i)
large_before=[capacity(large),list(large)]
for i in range(0,80010,2):large.discard(i)
large_copy=large.copy()
large_update=set();large_update.update(large)
literal_sources=['{1, 9}', '{1, 9, 17}', '{x, 9, 17}', '{1, True, 0}', '{(1, 2), (3, 4), (5, 6)}']
literals=[]
for src in literal_sources:
 code=compile(src,'<set-literal>','eval');value=eval(code,{'x':1})
 literals.append(dict(source=src,order=[repr(x)for x in value],capacity=capacity(value),instructions=[x.opname for x in dis.get_instructions(code)]))
print(json.dumps(dict(python=sys.version,hash_info=str(sys.hash_info),keys=pool,cases=cases,cursor_cases=cursor_cases,large=dict(before=large_before,after=[capacity(large),list(large)],copy=[capacity(large_copy),list(large_copy)],update=[capacity(large_update),list(large_update)]),literals=literals),ensure_ascii=True))
