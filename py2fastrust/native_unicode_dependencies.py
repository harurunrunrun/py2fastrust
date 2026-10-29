"""Mandatory selection of genuinely reachable bundled Unicode components.

This is independent of optional helper-size optimization. Only unreachable
Unicode-bearing items and their otherwise uncompiled reverse dependencies are
removed. Other unused helpers retain their no-optimize behavior.
"""
from collections import defaultdict,deque
from bisect import bisect_left
import re

from .native_unicode_tables import unicode_tables
from .rust_pruning import _lex,_parse,_WORD,_Unsupported,_group_end,prune_rust_source_with_report


_FORMAT_ARGUMENT={"format":0,"format_args":0,"print":0,"println":0,"eprint":0,
                  "eprintln":0,"panic":0,"todo":0,"unreachable":0,"unimplemented":0,
                  "write":1,"writeln":1,"assert":1,"debug_assert":1,
                  "assert_eq":2,"assert_ne":2,"debug_assert_eq":2,"debug_assert_ne":2}


def _string_value(text):
    raw=re.fullmatch(r'r(#+)?"(.*)"\1',text,re.S)
    if raw:return raw[2]
    # The optional raw delimiter group does not backreference an empty group.
    if text.startswith('r"')and text.endswith('"'):return text[2:-1]
    if not(text.startswith('"')and text.endswith('"')):return None
    body=text[1:-1];out=[];index=0
    escapes={"n":"\n","r":"\r","t":"\t","0":"\0","\\":"\\",'"':'"',"'":"'"}
    try:
        while index<len(body):
            char=body[index];index+=1
            if char!='\\':out.append(char);continue
            char=body[index];index+=1
            if char in escapes:out.append(escapes[char])
            elif char=='x':out.append(chr(int(body[index:index+2],16)));index+=2
            elif char=='u'and body[index]=='{':
                end=body.index('}',index);out.append(chr(int(body[index+1:end].replace('_',''),16)));index=end+1
            elif char in '\r\n':
                while index<len(body)and body[index].isspace():index+=1
            else:return None
    except (IndexError,ValueError):return None
    return ''.join(out)


def _capture_names(text):
    names=set();index=0
    while index<len(text):
        if text[index]=='{':
            if index+1<len(text)and text[index+1]=='{':index+=2;continue
            end=text.find('}',index+1)
            if end<0:return None
            names.update(_WORD.findall(text[index+1:end]));index=end+1
        elif text[index:index+2]=='}}':index+=2
        else:index+=1
    return names


def _reference_reader(tokens,pairs,items):
    """Ordinary string contents are values; format captures are references."""
    captures={};all_names={token.text for token in tokens if token.kind=='identifier'}
    for index,token in enumerate(tokens[:-2]):
        if token.kind!='identifier'or token.text not in _FORMAT_ARGUMENT:continue
        if tokens[index+1].text!='!'or tokens[index+2].text not in {'(','[','{'}:continue
        opening=index+2;end=pairs[opening];cursor=opening+1;argument=0;wanted=_FORMAT_ARGUMENT[token.text]
        while cursor<end:
            if argument==wanted:
                literal=tokens[cursor]
                if literal.kind=='literal':
                    value=_string_value(literal.text);names=None if value is None else _capture_names(value)
                    captures[literal.start]=all_names if names is None else names
                break
            if tokens[cursor].text==',':argument+=1;cursor+=1
            elif tokens[cursor].text in {'(','[','{'}:cursor=pairs[cursor]+1
            elif tokens[cursor].text=='<'and cursor>=2 and tokens[cursor-1].text==tokens[cursor-2].text==':':cursor=_group_end(tokens,cursor)
            elif tokens[cursor].text=='<'and(cursor==opening+1 or tokens[cursor-1].text==','):raise _Unsupported('opaque UFCS macro argument')
            else:cursor+=1
    starts=[token.start for token in tokens]
    positions={token.start:index for index,token in enumerate(tokens)}
    contexts=[item for item in items if item.kind=='impl']
    static=set();aliases={item.name:item.references-{item.name}for item in items if item.kind=='type'}
    for item in contexts:
        for child in item.children:
            associated=child.kind in {'const','type'}
            if child.kind=='fn':
                first=bisect_left(starts,child.start);last=bisect_left(starts,child.end)
                fn=next(index for index in range(first,last)if tokens[index].text=='fn')
                cursor=fn+2
                if tokens[cursor].text=='<':cursor=_group_end(tokens,cursor)
                associated=(tokens[cursor].text=='('and not any(token.text=='self'for token in tokens[cursor+1:pairs[cursor]]))
            if associated:static.add((item.owner,child.name))
    static_names={name for owner,name in static}
    nominal={item.name for item in items if item.kind in {'struct','enum','type'}}
    nominal.update(owner for owner,name in static)
    global_alias_spans=[(item.start,item.end)for item in items if item.kind=='type']
    opaque_aliases=set()
    for index,token in enumerate(tokens[:-1]):
        if token.text=='type'and tokens[index+1].kind=='identifier':
            if not any(first<=token.start<last for first,last in global_alias_spans):opaque_aliases.add(tokens[index+1].text)
        elif token.text=='use':
            cursor=index+1
            while cursor<len(tokens)and tokens[cursor].text!=';':
                if tokens[cursor].kind=='identifier'and tokens[cursor].text!='_':opaque_aliases.add(tokens[cursor].text)
                cursor+=1
    def owners(name):
        found=set();pending=[name]
        while pending:
            current=pending.pop()
            if current in found:continue
            found.add(current);pending.extend(aliases.get(current,()))
        return found
    def member_key(item):return item.owner+'::'+item.name if(item.owner,item.name)in static else item.name
    def references(fragment):
        result={token.text for token in fragment if token.kind=='identifier'}
        for token in fragment:
            if token.kind=='literal':result.update(captures.get(token.start,()))
            if token.kind!='identifier'or token.text not in static_names:continue
            index=positions[token.start]
            if index<3 or tokens[index-1].text!=tokens[index-2].text or tokens[index-1].text!=':':continue
            qualifier=tokens[index-3]
            if qualifier.text=='Self':
                possible={item.owner for item in contexts if item.start<=token.start<item.end}
            elif qualifier.kind=='identifier':
                possible=None if qualifier.text in opaque_aliases or qualifier.text not in nominal else owners(qualifier.text)
            else:possible=None
            for owner,name in static:
                if name==token.text and(possible is None or owner in possible):
                    result.add(owner+'::'+name)
                    # Aliased/UFCS references also establish the nominal owner
                    # needed by the shared reachability member rule.
                    result.add(owner)
        return result
    return references,member_key


def select_unicode_dependencies(source):
    """Keep genuine Unicode data dependencies in every optimization profile."""
    try:
        tables=unicode_tables(source)
        if not tables:return source
        tokens,comments,pairs=_lex(source)
        initial=0
        while initial+2<len(tokens)and [part.text for part in tokens[initial:initial+3]]==['#','!','[']:initial=pairs[initial+2]+1
        parsed=_parse(source,tokens,comments,pairs,initial)
        references,member_key=_reference_reader(tokens,pairs,parsed)
    except (IndexError,_Unsupported,StopIteration):return source
    def select(items,live):
        nodes=[]
        for item in items:
            nodes.extend(item.children if item.kind=='impl'and not item.trait else[item])
        names=defaultdict(set)
        for item in nodes:
            if item.name is not None:names[member_key(item)if item.owner is not None else item.name].add(id(item))
            elif item.kind=='impl'and item.owner is not None:names[item.owner].add(id(item))
        reverse=defaultdict(set)
        for item in nodes:
            for name in item.references:
                for target in names.get(name,()):reverse[target].add(id(item))
        seeds={id(item)for item in nodes if id(item)not in live and
               any(item.start<=table.start<item.end for table in tables)}
        chosen=set()
        for seed in seeds:
            component=set();pending=deque([seed])
            while pending:
                current=pending.popleft()
                if current in component:continue
                component.add(current);pending.extend(reverse.get(current,()))
            # Name-based alias/method ambiguity may be broader than the normal
            # owner-aware reachability proof. Preserve that whole component.
            if component&live:continue
            chosen.update(component)
        # Inherent wrappers are not seeds: one local table cannot erase the
        # other methods of a live type. Close wrappers only after their entire
        # body or nominal/header dependency was selected for removal.
        removed_names={item.name for item in nodes if id(item)in chosen and item.owner is None and item.name is not None}
        for item in items:
            if item.kind=='impl'and not item.trait and not item.protected:
                if ((item.children and all(id(child)in chosen for child in item.children))
                        or item.references&removed_names):chosen.add(id(item))
        return chosen
    return prune_rust_source_with_report(source,reference_names=references,select_unreachable=select,member_name=member_key).source
