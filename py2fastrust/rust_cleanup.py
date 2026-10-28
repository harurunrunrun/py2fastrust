"""Conservative local liveness and empty branch cleanup for generated Rust.

This pass does not execute Python or Rust expressions. Unread Copy bindings
can disappear; an unknown/effectful initializer keeps its original position and
type context as a wildcard evaluation. Non-Copy values and reference lifetimes
are outside this proof. Macro token streams and implicit format captures remain
observable. A retained binding is not claimed to be dead.
"""
from collections import Counter
from dataclasses import dataclass
import re

from .rust_pruning import _lex,_group_end,_Unsupported,_WORD
from .rust_layout import strip_comments


_PRIMITIVES=frozenset({"bool","char","u8","u16","u32","u64","u128","usize",
                       "i8","i16","i32","i64","i128","isize","f32","f64"})
_SUFFIX=re.compile(r"(?:^|[0-9_])((?:[ui](?:8|16|32|64|128)|[ui]size|f32|f64))$")
_MACROS=frozenset({"assert","assert_eq","assert_ne","debug_assert","debug_assert_eq",
                  "debug_assert_ne","format","format_args","write","writeln","print",
                  "println","eprint","eprintln","matches","vec","panic","unreachable",
                  "todo","unimplemented","stringify","line","column","file"})
_ATTRIBUTES=frozenset({"allow","deny","warn","forbid","derive","inline","cold","must_use",
                      "cfg","repr","doc","non_exhaustive","deprecated","test","ignore",
                      "should_panic","link_name","link"})
_SOURCE_MACROS=frozenset({"line","column","file","module_path","include","include_str","include_bytes"})
_KEYWORDS=frozenset({"as","break","const","continue","crate","else","enum","extern",
    "false","fn","for","if","impl","in","let","loop","match","mod","move","mut",
    "pub","ref","return","self","Self","static","struct","super","trait","true","type",
    "unsafe","use","where","while","async","await","dyn","abstract","become","box","do",
    "final","macro","override","priv","typeof","unsized","virtual","yield","try","gen"})


@dataclass(frozen=True)
class RustCleanupResult:
    source: str
    removed_else: int=0
    removed_locals: tuple[str,...]=()
    wildcard_evaluations: int=0
    retained: bool=False
    reason: str|None=None


@dataclass
class _Definition:
    name: str
    start: int
    name_index: int
    end: int
    rhs: tuple[int,int]|None
    annotation: tuple[int,int]|None
    mutable: int|None=None
    type_text: str|None=None
    copy: bool=False


@dataclass(frozen=True)
class _Write:
    name: str|None
    start: int
    end: int
    lhs: int
    rhs: tuple[int,int]
    declaration: bool=False


def _inside(index,ranges):
    return any(first<=index<last for first,last in ranges)


def _macro_ranges(tokens,pairs):
    result=[]
    for index,token in enumerate(tokens[:-2]):
        if token.kind!="identifier"or tokens[index+1].text!="!":continue
        opening=index+2
        if token.text=="macro_rules"and tokens[opening].kind=="identifier":opening+=1
        if opening<len(tokens)and tokens[opening].text in {"(","[","{"}:
            result.append((index,pairs[opening]+1,token.text))
    return result


def _statement_end(tokens,pairs,start,stop):
    cursor=start
    while cursor<stop:
        if tokens[cursor].text==";":return cursor
        cursor=pairs[cursor]+1 if tokens[cursor].text in {"(","[","{"} else cursor+1
    return None


def _split(tokens,pairs,first,last,separator=","):
    result=[];start=first;cursor=first
    while cursor<last:
        text=tokens[cursor].text
        if text==separator:
            result.append((start,cursor));start=cursor+1
        if text in {"(","[","{"}:cursor=pairs[cursor]+1
        elif text=="<":cursor=_group_end(tokens,cursor)
        else:cursor+=1
    if start<last:result.append((start,last))
    return result


def _type_text(source,tokens,first,last):
    return strip_comments(source[tokens[first].start:tokens[last-1].end]).strip() if first<last else ""


def _aliases(source,tokens,pairs):
    aliases={};counts=Counter();blocked=set()
    for index,token in enumerate(tokens[:-2]):
        generic=index+2 if token.text in {"fn","trait","struct","enum","union","type"}and tokens[index+1].kind=="identifier"else index+1 if token.text=="impl"else None
        if generic is not None and tokens[generic].text=="<":
            end=_group_end(tokens,generic)
            for first,last in _split(tokens,pairs,generic+1,end-1):
                if tokens[first].text=="const":first+=1
                if first<last and tokens[first].kind=="identifier":blocked.add(tokens[first].text)
        if token.text=="use":
            end=_statement_end(tokens,pairs,index+1,len(tokens))
            if end is not None:
                blocked.update(part.text for part in tokens[index+1:end]if part.kind=="identifier")
                if any(part.text=="*"for part in tokens[index+1:end]):blocked.add("*")
        if token.text in {"struct","enum","union"}and tokens[index+1].kind=="identifier":
            blocked.add(tokens[index+1].text)
        if token.text!="type"or tokens[index+1].kind!="identifier":continue
        name=tokens[index+1].text;counts[name]+=1
        if tokens[index+2].text!="=":blocked.add(name);continue
        end=_statement_end(tokens,pairs,index+3,len(tokens))
        if end is None:blocked.add(name);continue
        aliases[name]=(index+3,end)
    blocked.update(name for name,count in counts.items()if count!=1)
    return aliases,blocked


def _copy_type(tokens,pairs,first,last,aliases,blocked,seen=()):
    if first>=last:return False
    values=tokens[first:last]
    if len(values)==1 and values[0].kind=="identifier":
        name=values[0].text
        if name in blocked or name in seen:return False
        if name in aliases:return _copy_type(tokens,pairs,*aliases[name],aliases,blocked,seen+(name,))
        return name in _PRIMITIVES
    if values[0].text=="("and pairs.get(first)==last-1:
        return all(_copy_type(tokens,pairs,a,b,aliases,blocked,seen)for a,b in _split(tokens,pairs,first+1,last-1))
    if values[0].text=="["and pairs.get(first)==last-1:
        parts=_split(tokens,pairs,first+1,last-1,";")
        return len(parts)==2 and _copy_type(tokens,pairs,*parts[0],aliases,blocked,seen)
    opening=next((i for i in range(first,last)if tokens[i].text=="<"),None)
    if opening is not None and _group_end(tokens,opening)==last:
        owner="".join(token.text for token in tokens[first:opening])
        if owner in {"Option","std::option::Option","core::option::Option"}and "Option"not in blocked:
            parts=_split(tokens,pairs,opening+1,last-1)
            return len(parts)==1 and _copy_type(tokens,pairs,*parts[0],aliases,blocked,seen)
        if owner in {"Result","std::result::Result","core::result::Result"}and "Result"not in blocked:
            parts=_split(tokens,pairs,opening+1,last-1)
            return len(parts)==2 and all(_copy_type(tokens,pairs,a,b,aliases,blocked,seen)for a,b in parts)
    # References are Copy, but let-bound borrows can extend a Non-Copy
    # temporary's lifetime. Do not remove these or unknown nominal types.
    return False


def _functions(tokens,pairs):
    result=[]
    for index,token in enumerate(tokens[:-2]):
        if token.text!="fn"or tokens[index+1].kind!="identifier":continue
        cursor=index+2
        if tokens[cursor].text=="<":cursor=_group_end(tokens,cursor)
        if tokens[cursor].text!="(":continue
        parameters=cursor;cursor=pairs[cursor]+1
        while cursor<len(tokens)and tokens[cursor].text not in {"{",";"}:
            if tokens[cursor].text in {"(","["}:cursor=pairs[cursor]+1
            elif tokens[cursor].text=="<":cursor=_group_end(tokens,cursor)
            else:cursor+=1
        if cursor<len(tokens)and tokens[cursor].text=="{":
            result.append((index,parameters,cursor,pairs[cursor]))
    return result


def _definition(tokens,pairs,index,stop):
    cursor=index+1;mutable=None
    if cursor<stop and tokens[cursor].text=="mut":mutable=cursor;cursor+=1
    if cursor>=stop or tokens[cursor].kind!="identifier"or tokens[cursor].text=="_":return None
    name=cursor;cursor+=1;annotation=None
    if cursor<stop and tokens[cursor].text==":":
        first=cursor+1;cursor=first
        while cursor<stop and tokens[cursor].text not in {"=",";"}:
            if tokens[cursor].text in {"(","["}:cursor=pairs[cursor]+1
            elif tokens[cursor].text=="<":cursor=_group_end(tokens,cursor)
            else:cursor+=1
        annotation=(first,cursor)
    if cursor>=stop or tokens[cursor].text not in {"=",";"}:return None
    end=_statement_end(tokens,pairs,cursor,stop)
    if end is None:return None
    rhs=(cursor+1,end)if tokens[cursor].text=="="else None
    return _Definition(tokens[name].text,index,name,end,rhs,annotation,mutable)


def _unparen(tokens,pairs,first,last):
    while first<last and tokens[first].text=="("and pairs.get(first)==last-1:
        parts=_split(tokens,pairs,first+1,last-1)
        if len(parts)!=1 or parts[0]!=(first+1,last-1):break
        first+=1;last-=1
    return first,last


def _atomic(tokens,pairs,first,last):
    if first>=last:return False
    if last-first==1:return tokens[first].kind in {"identifier","literal"}
    if tokens[first].text in {"(","[","{"}and pairs.get(first)==last-1:return True
    if tokens[first].text in {"-","!","*","&"}:
        first+=1
        if first<last and tokens[first].text=="mut":first+=1
        return _atomic(tokens,pairs,first,last)
    return False


def _infer_type(source,tokens,pairs,first,last,aliases,blocked):
    first,last=_unparen(tokens,pairs,first,last)
    if first>=last:return None
    def primitive(name):return name if name not in aliases and name not in blocked else None
    if last-first==1:
        token=tokens[first]
        if token.text in {"true","false"}:return primitive("bool")
        if token.kind=="literal":
            if token.text.startswith(("'","b'")):return primitive("u8"if token.text.startswith("b'")else"char")
            suffix=_SUFFIX.search(token.text)
            if suffix:return primitive(suffix[1])
    if tokens[first].text=="("and pairs.get(first)==last-1 and first+1==last-1:return "()"
    cursor=first
    while cursor<last:
        if (tokens[cursor].text=="as"and _atomic(tokens,pairs,first,cursor)
                and _copy_type(tokens,pairs,cursor+1,last,aliases,blocked)):
            return _type_text(source,tokens,cursor+1,last)
        cursor=pairs[cursor]+1 if tokens[cursor].text in {"(","[","{"} else cursor+1
    return None


def _pure(tokens,pairs,first,last,removable_names,copy_type,expected_copy=True):
    first,last=_unparen(tokens,pairs,first,last)
    if first>=last:return False
    if last-first==1:
        token=tokens[first]
        if token.kind=="literal":return True
        if token.text in {"true","false"}:return True
        return (expected_copy and token.kind=="identifier"
                and token.text not in _KEYWORDS and token.text in removable_names)
    if tokens[first].text=="("and pairs.get(first)==last-1:
        return all(_pure(tokens,pairs,a,b,removable_names,copy_type,expected_copy)for a,b in _split(tokens,pairs,first+1,last-1))
    if tokens[first].text in {"-","!"}and last-first==2 and tokens[first+1].kind=="literal":return True
    casts=[];cursor=first
    while cursor<last:
        if tokens[cursor].text=="as":casts.append(cursor)
        cursor=pairs[cursor]+1 if tokens[cursor].text in {"(","[","{"}else cursor+1
    for cursor in reversed(casts):
        if copy_type(cursor+1,last):return _pure(tokens,pairs,first,cursor,removable_names,copy_type,False)
    return False


def _preserved_comments(source,comments,start,end):
    return "".join(source[a:b]+(""if source[a:b].endswith("\n")else"\n")for a,b,_doc in comments if start<=a and b<=end)


def _local_edits(source,tokens,comments,pairs,scope,macros,aliases,blocked):
    fn,parameters,body,ending=scope
    if "*"in blocked:return [],[],0
    if any(name not in _MACROS for first,last,name in macros if body<first<ending):return [],[],0
    for first,last,name in macros:
        if not body<first<ending:continue
        if name in blocked:return [],[],0
        if first>=3 and tokens[first-1].text==tokens[first-2].text==":"and tokens[first-3].text not in {"std","core"}:
            return [],[],0
    if any(token.text=="fn"for token in tokens[body+1:ending]):return [],[],0
    protected=[(a,b)for a,b,_name in macros]
    definitions=[]
    for index in range(body+1,ending):
        if tokens[index].text!="let"or _inside(index,protected):continue
        if tokens[index-1].text not in {"{","}",";"}:continue
        definition=_definition(tokens,pairs,index,ending)
        if definition is not None:definitions.append(definition)
    counts=Counter(value.name for value in definitions)
    header_names={token.text for token in tokens[fn:body]if token.kind=="identifier"}
    unique={value.name:value for value in definitions if counts[value.name]==1 and value.name not in header_names}
    local_blocked=set(blocked)
    for index in range(body+1,ending-1):
        if tokens[index].text in {"type","struct","enum","union"}:local_blocked.add(tokens[index+1].text)
    for name,definition in unique.items():
        if definition.annotation and _copy_type(tokens,pairs,*definition.annotation,aliases,local_blocked):
            definition.type_text=_type_text(source,tokens,*definition.annotation);definition.copy=True
    declaration_names={value.name_index for value in definitions}
    writes=[_Write(value.name,value.start,value.end,value.name_index,value.rhs,True)for value in definitions if value.rhs]
    for index in range(body+1,ending-1):
        token=tokens[index]
        if token.text not in unique or index in declaration_names or _inside(index,protected):continue
        if tokens[index-1].text not in {"{","}",";"}or tokens[index+1].text!="=":continue
        if index+2<ending and tokens[index+2].text in {"=",">"}:continue
        end=_statement_end(tokens,pairs,index+2,ending)
        if end is not None:writes.append(_Write(token.text,index,end,index,(index+2,end)))
    # Do not infer types from identifier names or later assignments: let/for/
    # match/closure patterns can shadow an earlier name with a Non-Copy value.
    # Only an initializer whose complete value has a proved primitive type can
    # supplement an explicit annotation.
    for definition in unique.values():
        if definition.annotation is None and definition.rhs is not None:
            inferred=_infer_type(source,tokens,pairs,*definition.rhs,aliases,local_blocked)
            if inferred is not None:definition.type_text=inferred;definition.copy=True
    candidates={name:value for name,value in unique.items()if value.copy}
    if not candidates:return [],[],0
    # Deleting a typed assignment can remove the only inference constraint on
    # an earlier untyped producer (parse(), an integer loop binder, etc.). A
    # name load is removable only inside a fully dead, independently typed
    # component. Unknown or retained dependencies keep a typed wildcard. This
    # also fails closed on names introduced by unsupported binding patterns:
    # their binder occurrence makes the same-named candidate live below.
    removable_names=set(candidates)
    while True:
        effects={};dependencies={name:set()for name in candidates}
        covered=set(declaration_names);live=set()
        for write in writes:
            if write.name not in candidates:continue
            pure=_pure(tokens,pairs,*write.rhs,removable_names,
                       lambda first,last:_copy_type(tokens,pairs,first,last,aliases,local_blocked))
            effects[id(write)]=not pure
            covered.add(write.lhs)
            rhs_names={token.text for token in tokens[write.rhs[0]:write.rhs[1]]if token.kind=="identifier"}
            if pure:
                covered.update(range(*write.rhs));dependencies[write.name].update(rhs_names&candidates.keys())
            else:live.update(rhs_names&candidates.keys())
        for index in range(body+1,ending):
            if index in covered:continue
            token=tokens[index]
            if token.kind=="identifier"and token.text in candidates:live.add(token.text)
            elif token.kind=="literal":live.update(set(_WORD.findall(token.text))&candidates.keys())
        pending=list(live)
        while pending:
            for name in dependencies[pending.pop()]-live:live.add(name);pending.append(name)
        dead=candidates.keys()-live
        if dead==removable_names:break
        removable_names=dead
    edits=[];wildcards=0
    for name in dead:
        definition=candidates[name]
        if definition.rhs is None:
            start,end=tokens[definition.start].start,tokens[definition.end].end
            edits.append((start,end,_preserved_comments(source,comments,start,end)))
    for write in writes:
        if write.name not in dead:continue
        definition=candidates[write.name]
        if not effects[id(write)]:
            start,end=tokens[write.start].start,tokens[write.end].end
            edits.append((start,end,_preserved_comments(source,comments,start,end)))
        elif write.declaration:
            replacement="_"if definition.annotation else "_:"+definition.type_text
            edits.append((tokens[write.lhs].start,tokens[write.lhs].end,replacement))
            if definition.mutable is not None:edits.append((tokens[definition.mutable].start,tokens[definition.mutable].end,""))
            wildcards+=1
        else:
            edits.append((tokens[write.lhs].start,tokens[write.lhs].end,"let _:"+definition.type_text));wildcards+=1
    return edits,sorted(dead),wildcards


def _empty_elses(source):
    tokens,comments,pairs=_lex(source);macros=_macro_ranges(tokens,pairs)
    protected=[(a,b)for a,b,_name in macros];edits=[]
    for index,token in enumerate(tokens[:-2]):
        if token.text!="else"or _inside(index,protected)or tokens[index+1].text!="{":continue
        last=pairs[index+1]
        if any(tokens[i].text!=";"for i in range(index+2,last)):continue
        start,end=token.start,tokens[last].end
        edits.append((start,end,_preserved_comments(source,comments,start,end)))
    for first,last,text in sorted(edits,reverse=True):source=source[:first]+text+source[last:]
    return source,len(edits)


def cleanup_rust_source_with_report(source):
    original=source;removed=[];wildcards=0
    try:
        tokens,_comments,pairs=_lex(source)
        for index,token in enumerate(tokens[:-2]):
            if token.text=="r"and tokens[index+1].text=="#":raise _Unsupported("raw identifier namespace")
            if token.text=="#":
                opening=index+1+(tokens[index+1].text=="!")
                if tokens[opening].text=="["and tokens[opening+1].text not in _ATTRIBUTES:
                    raise _Unsupported("unproved compiler attribute")
                if tokens[opening].text=="["and tokens[opening+1].text=="derive":
                    supported={"derive","Clone","Copy","Debug","Default","PartialEq","Eq","PartialOrd","Ord","Hash"}
                    if any(part.kind=="identifier"and part.text not in supported for part in tokens[opening+1:pairs[opening]]):
                        raise _Unsupported("unproved derive implementation")
        if any(name in _SOURCE_MACROS for _a,_b,name in _macro_ranges(tokens,pairs)):
            raise _Unsupported("source-observing Rust macro")
        source,removed_else=_empty_elses(source)
        tokens,comments,pairs=_lex(source);macros=_macro_ranges(tokens,pairs);aliases,blocked=_aliases(source,tokens,pairs)
        edits=[]
        for scope in _functions(tokens,pairs):
            changes,names,count=_local_edits(source,tokens,comments,pairs,scope,macros,aliases,blocked)
            edits.extend(changes);removed.extend(names);wildcards+=count
        # Nested expressions can have their own let-bindings. Prefix wildcard
        # edits do not overlap their initializer; reject an unproved overlap.
        ordered=sorted(edits)
        if any(a[1]>b[0]for a,b in zip(ordered,ordered[1:])):raise _Unsupported("overlapping local cleanup")
        for first,last,text in reversed(ordered):source=source[:first]+text+source[last:]
        source,additional=_empty_elses(source);removed_else+=additional
        return RustCleanupResult(source,removed_else,tuple(removed),wildcards)
    except (IndexError,KeyError,RecursionError,_Unsupported)as error:
        return RustCleanupResult(original,retained=True,reason=str(error))


def cleanup_rust_source(source):
    return cleanup_rust_source_with_report(source).source
