"""Exact builtin text predicates with lazy codepoint consumption and pinned data."""
from functools import lru_cache
from importlib.resources import files
import re

STR_PREDICATES=frozenset({"isupper","islower","isalpha","isalnum","isascii","isdecimal",
                          "isdigit","isnumeric","isspace","istitle","isidentifier"})
BYTES_PREDICATES=frozenset({"isupper","islower","isalpha","isalnum","isascii","isdigit","isspace","istitle"})
_TABLES={"isalpha":"ALPHA","isalnum":"ALNUM","isdecimal":"DECIMAL","isdigit":"DIGIT",
         "isnumeric":"NUMERIC","isspace":"SPACE","isupper":"UPPER","islower":"LOWER"}


def supports(kind,name):
    from .native_types import alternatives
    return all(value=="str" and name in STR_PREDICATES or value=="bytes" and name in BYTES_PREDICATES
               for value in alternatives(kind))


def receiver_view(value):
    """A borrowed UTF-8 view; NativeText producers may supply a cached view."""
    view=getattr(value,"text_view",None)
    return value.code if view is None else view


def try_expression(g,node,environment):
    from .native import _Expression,_Unsupported
    from .native_stream_plans import context
    from .call_semantics import CallBindingError
    try:plan=context(g,environment).method(node,names=STR_PREDICATES)
    except CallBindingError as error:raise _Unsupported from error
    if plan is None or plan.identity.name not in STR_PREDICATES:return None
    value=plan.receiver.captured;name=plan.identity.name
    if not supports(value.kind,name):return None
    from .native_types import UnionType,NullableType
    if isinstance(value.kind,(UnionType,NullableType)):
        from .native_unions import project
        owner=g.temporary()
        def leaf(kind,code):
            if kind=="str" and name=="isascii":return g.text_is_ascii(_Expression(f"&({code})","str",owned=False))
            g.text_predicates.add((kind,name,False))
            return f"native_{kind}_{name}(&({code}))"
        expression=project(value.kind,owner,leaf)
        return _Expression(f"{{let {owner}=&({value.code});{expression}}}","bool")
    if value.kind=="str" and value.char_code is not None:
        g.text_predicates.add(("str",name,True))
        codepoint=g.temporary()
        return _Expression(f"{{let {codepoint}:u32={value.char_code};native_str_{name}_code({codepoint})}}","bool")
    if value.kind=="str" and name=="isascii":
        owner=g.temporary()
        predicate=g.text_is_ascii(_Expression(owner,"str",owned=False))
        return _Expression(f"{{let {owner}=&({value.code});{predicate}}}","bool")
    g.text_predicates.add((value.kind,name,False))
    owner=g.temporary()
    if value.kind=="str":capture=f"let {owner}:&str={receiver_view(value)};"
    else:capture=f"let {owner}:&[u8]=&({value.code});"
    return _Expression(f"{{{capture}native_{value.kind}_{name}({owner})}}","bool")


def _ascii(name,code,kind):
    upper=f"({code}>=65&&{code}<=90)";lower=f"({code}>=97&&{code}<=122)";digit=f"({code}>=48&&{code}<=57)"
    if name in {"isupper","istitle"}:return upper
    if name=="islower":return lower
    if name=="isalpha":return f"({upper}||{lower})"
    if name=="isalnum":return f"({upper}||{lower}||{digit})"
    if name in {"isdigit","isdecimal","isnumeric"}:return digit
    if name=="isascii":return f"{code}<128"
    if name=="isspace":return f"(({code}>=9&&{code}<=13)||{code}==32"+(f"||({code}>=28&&{code}<=31)" if kind=="str" else "")+")"
    if name=="isidentifier":return f"({upper}||{lower}||{code}==95)"
    raise ValueError(name)


@lru_cache(maxsize=None)
def _table(name):
    if name=="TITLE":
        return files("py2fastrust").joinpath("runtime","native_titlecase_16.rs").read_text(encoding="utf-8")
    source=files("py2fastrust").joinpath("runtime","text.rs").read_text(encoding="utf-8")
    if 'const TEXT_UNICODE_VERSION: &str = "16.0.0";' not in source:raise RuntimeError("text predicates require pinned Unicode 16.0.0 data")
    found=re.search(r"const TEXT_"+name+r":\s*&\[\(u32,\s*u32\)\]\s*=\s*&\[.*?\n\];",source,re.S)
    if found is None:raise RuntimeError("missing pinned Unicode property "+name)
    return found.group().replace("TEXT_"+name,"NATIVE_PRED_TABLE_"+name)


_PROPERTY='''
fn native_predicate_property(code:u32,ranges:&[(u32,u32)])->bool {
    let index=ranges.partition_point(|(_,last)|*last<code);
    ranges.get(index).is_some_and(|(first,_)|*first<=code)
}
'''


def render_helpers(requests,string_mode):
    """Render only selected predicates and the data each selected form needs."""
    requests=set(requests);unicode=string_mode=="unicode";tables=set();functions=[];codes=set()
    def property(table,code):
        tables.add(table)
        return f"native_predicate_property({code},NATIVE_PRED_TABLE_{table})"
    def cased(code):
        if unicode:return f"(if {code}<128{{{_ascii('isalpha',code,'str')}}}else{{{property('CASED',code)}}})"
        return _ascii("isalpha",code,"str")
    def character(name,code,kind):
        ascii=_ascii(name,code,kind)
        if kind=="bytes" or not unicode or name=="isascii":return ascii
        if name=="istitle":body=f"({property('UPPER',code)}||{property('TITLE',code)})"
        elif name=="isidentifier":body=property("IDENTIFIER_START",code)
        else:body=property(_TABLES[name],code)
        return f"(if {code}<128{{{ascii}}}else{{{body}}})"
    for kind,name,single in sorted(requests):
        if single or name not in {"isascii","isidentifier","istitle"}:
            codes.add((kind,name))
        if single:continue
        input_type="&str" if kind=="str" else "&[u8]"
        iterator="value.chars().map(|item|item as u32)" if kind=="str" and unicode else ("value.as_bytes().iter().map(|&item|item as u32)" if kind=="str" else "value.iter().map(|&item|item as u32)")
        if name=="isascii":body="value.is_ascii()"
        elif name in {"isupper","islower"}:
            is_cased=cased("code") if kind=="str" else _ascii("isalpha","code",kind)
            body=f"let mut found=false;for code in {iterator}{{if {is_cased}{{if !native_{kind}_{name}_code(code){{return false;}}found=true;}}}}found"
        elif name=="istitle":
            upper=character("istitle","code",kind);lower=character("islower","code",kind)
            body=f"let mut found=false;let mut previous=false;for code in {iterator}{{if {upper}{{if previous{{return false;}}found=true;previous=true;}}else if {lower}{{if !previous{{return false;}}found=true;previous=true;}}else{{previous=false;}}}}found"
        elif name=="isidentifier":
            start=character(name,"code",kind)
            if unicode:
                cont=f"(if code<128{{{_ascii('isalnum','code',kind)}||code==95}}else{{{property('IDENTIFIER_CONTINUE','code')}}})"
            else:cont=f"({_ascii('isalnum','code',kind)}||code==95)"
            body=f"let mut chars={iterator};match chars.next(){{Some(code)if {start}=>chars.all(|code|{cont}),_=>false}}"
        else:body=f"!value.is_empty()&&{iterator}.all(|code|native_{kind}_{name}_code(code))"
        functions.append(f"fn native_{kind}_{name}(value:{input_type})->bool{{{body}}}")
    for kind,name in sorted(codes):
        functions.append(f"#[inline]\nfn native_{kind}_{name}_code(code:u32)->bool{{{character(name,'code',kind)}}}")
    return "\n".join(([_PROPERTY]+[_table(name)for name in sorted(tables)] if tables else [])+functions)
