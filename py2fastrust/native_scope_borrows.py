"""Borrow execution context across synchronous, nonescaping native calls.

This is a physical ABI pass over compiler-owned Rust function symbols. Python
arguments, frames, callbacks, module changes and exceptions keep their normal
evaluation rules. Futures and escaping Rust function references retain an owned
context. Source functions and constructors share the same nonescaping ABI
proof. Every retained/returned context is explicitly cloned.
"""
import re

from .rust_pruning import _lex,_parse


FUNCTION=re.compile(r'class_(?:function|construct)_\d+\Z')


def body_index(tokens,pairs,opening,limit):
    cursor=pairs[opening]+1
    while cursor<len(tokens)and tokens[cursor].start<limit:
        if tokens[cursor].text=='{':return cursor
        if tokens[cursor].text==';':return None
        cursor=pairs[cursor]+1 if tokens[cursor].text in {'(','['}else cursor+1
    return None


def shared_scope(tokens,pairs,items):
    """All context state must be shared; an owned field could change on clone."""
    # A custom destructor can make even a shared-only context clone observable.
    aliases={'ClassScope'}
    while True:
        found=aliases|{item.name for item in items if item.kind=='type'
                       and item.name is not None and item.references&aliases}
        if found==aliases:break
        aliases=found
    if any(item.kind=='impl'and item.trait and item.owner in aliases
           and 'Drop'in item.references for item in items):return False
    item=next((item for item in items if item.kind=='struct'and item.name=='ClassScope'),None)
    if item is None:return False
    first=next(i for i,token in enumerate(tokens)if token.start>=item.start)
    declaration=next(i for i in range(first,len(tokens))if tokens[i].text=='struct')
    header=[token.text for token in tokens[first:declaration]]
    if 'derive'not in header or'Clone'not in header:return False
    opening=declaration+2
    if tokens[opening].text!='{':return False
    closing=pairs[opening];cursor=opening+1
    while cursor<closing:
        if cursor+3>=closing or tokens[cursor+1].text!=':'or tokens[cursor+2].text!='Rc'or tokens[cursor+3].text!='<':return False
        depth=1;cursor+=4
        while cursor<closing and depth:
            text=tokens[cursor].text
            if set(text)<=set('<>'):
                depth+=text.count('<')-text.count('>')
            cursor+=1
        if depth:return False
        if cursor<closing:
            if tokens[cursor].text!=',':return False
            cursor+=1
    return True


def _scope_uses_borrowable(tokens,start,end):
    for i in range(start,end):
        token=tokens[i]
        if token.text in {'move','async'}:return False
        if token.text!='class_scope':continue
        previous=tokens[i-1].text if i else''
        if previous in {'&','let'}:continue
        if i+2<end and tokens[i+1].text=='.':
            member=tokens[i+2].text
            if member in {'clone','with_module'}:continue
            if (member in {'control','io','globals','modules'}and i+4<end
                    and tokens[i+3].text=='.'and tokens[i+4].text in
                    {'clone','borrow','borrow_mut','try_borrow','try_borrow_mut','as_ref'}):continue
        # An owned move into a returned aggregate or an unknown runtime ABI
        # is not a borrow proof. Its function and callers keep the owned ABI.
        return False
    return True


def apply(source):
    tokens,comments,pairs=_lex(source)
    if not any(token.text=='ClassScope'for token in tokens):return source
    # The item parser validates all delimiters/item boundaries before edits.
    items=_parse(source,tokens,comments,pairs)
    if not shared_scope(tokens,pairs,items):return source
    functions={item.name:item for item in items if item.kind=='fn'}
    token_positions={token.start:i for i,token in enumerate(tokens)}
    definitions={}
    for i,token in enumerate(tokens[:-4]):
        if not FUNCTION.fullmatch(token.text)or not i or tokens[i-1].text!='fn':continue
        item=functions.get(token.text)
        if item is None:continue
        first=token_positions[item.start]
        header=[part.text for part in tokens[first:i]]
        if any(qualifier in header for qualifier in {'async','unsafe','extern','const'}):continue
        opening=i+1
        if tokens[opening].text!='(':continue
        if [item.text for item in tokens[opening+1:opening+4]]!=['class_scope',':','ClassScope']:continue
        closing=pairs[opening];body=body_index(tokens,pairs,opening,item.end)
        if body is None:continue
        if not any(item.text=='ClassResult'for item in tokens[closing+1:body]):continue
        if not _scope_uses_borrowable(tokens,body+1,pairs[body]):continue
        definitions[token.text]=(opening+3,body)
    # Rust function pointers carry their explicit ABI independently of source
    # callable enums. Do not change an address-taken function's signature.
    escaped={token.text for i,token in enumerate(tokens[:-1])
             if token.text in definitions and tokens[i+1].text!='('}
    selected={name:value for name,value in definitions.items()if name not in escaped}
    if not selected:return source
    edits=[(tokens[parameter].start,tokens[parameter].start,'&')for parameter,_ in selected.values()]
    for i,token in enumerate(tokens[:-1]):
        if token.text not in selected or tokens[i+1].text!='('or(i and tokens[i-1].text=='fn'):continue
        opening=i+1;closing=pairs[opening];end=closing;cursor=opening+1
        while cursor<closing:
            if tokens[cursor].text==',':end=cursor;break
            cursor=pairs[cursor]+1 if tokens[cursor].text in {'(','[','{'}else cursor+1
        assert opening+1<end,'compiled source call has no execution context'
        start=tokens[opening+1].start;stop=tokens[end].start
        expression=source[start:stop].strip()
        if re.fullmatch(r'(?:class_scope|scope)\.clone\(\)',expression):expression=expression[:-8]
        # Prefix/suffix edits preserve nested call edits and source locations.
        # Only an exact plain context clone can be removed as a whole.
        if re.fullmatch(r'(?:class_scope|scope)',expression):
            edits.append((start,stop,'&'+expression))
        else:
            edits.extend(((start,start,'&('),(stop,stop,')')))
    for start,end,text in sorted(edits,reverse=True):source=source[:start]+text+source[end:]
    return source
