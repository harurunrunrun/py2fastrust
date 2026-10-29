"""Layout and attribution for structurally recognized bundled Unicode data.

Only reserved runtime tables with u32 scalar or (u32,u32) elements are selected.
Their values stay token-identical; unrelated arrays, literals and comments are
never reformatted by this module.
"""
from dataclasses import dataclass
import re

from .rust_pruning import _lex, _Unsupported

_NAMES=frozenset({"ZEROES","RANGES","TEXT_PRINTABLE","NATIVE_TUPLE_PRINTABLE",
                  "NATIVE_FIXED_INT_ZEROES","NATIVE_FIXED_INT_SPACE"})
_NUMBER=re.compile(r"(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|[0-9][0-9_]*)(?:u32)?\Z")


@dataclass(frozen=True)
class UnicodeTable:
    name: str
    start: int
    notice_start: int
    body_start: int
    body_end: int
    elements: tuple[str,...]|None


def _indent(source,position):
    line=source.rfind("\n",0,position)+1
    return re.match(r"[ \t]*",source[line:position]).group()


def _opaque_spans(tokens,pairs):
    """Macros/attributes own token trees, not ordinary const declarations."""
    spans=[]
    for index,token in enumerate(tokens):
        opening=None;first=index
        if token.text=="macro_rules"and index+3<len(tokens)and tokens[index+1].text=="!":
            opening=index+3
        elif token.text=="!"and index and tokens[index-1].kind=="identifier"and index+1<len(tokens):
            opening=index+1;first=index-1
            while first>=3 and [part.text for part in tokens[first-2:first]]==[":",":"]and tokens[first-3].kind=="identifier":first-=3
        elif token.text=="#"and index+1<len(tokens):
            opening=index+1
            if tokens[opening].text=="!":opening+=1
        if opening is not None and opening<len(tokens)and tokens[opening].text in {"(","[","{"}:
            spans.append((tokens[first].start,tokens[pairs[opening]].end))
    return tuple(sorted(spans,key=lambda span:(span[0],-span[1])))


def unicode_tables(source):
    """Find real table declarations; quoted/commented spellings are ignored."""
    tokens,comments,pairs=_lex(source)
    tables=[];opaque=_opaque_spans(tokens,pairs)
    for index,token in enumerate(tokens[:-2]):
        if token.text!="const":continue
        name=tokens[index+1].text
        if name not in _NAMES and not name.startswith("NATIVE_PRED_TABLE_"):continue
        cursor=index+2
        if tokens[cursor].text!=":":continue
        cursor+=1
        if cursor>=len(tokens):continue
        if tokens[cursor].text=="&":
            cursor+=1
            if cursor<len(tokens)and tokens[cursor].kind=="lifetime":cursor+=1
        if cursor>=len(tokens)or tokens[cursor].text!="[":continue
        type_end=pairs[cursor];element=cursor+1;range_elements=False
        if tokens[element].text=="u32":element+=1
        elif tokens[element].text=="(":
            end=pairs[element]
            if [part.text for part in tokens[element:end+1]]not in (["(","u32",",","u32",")"],["(","u32",",","u32",",",")"]):continue
            element=end+1;range_elements=True
        else:continue
        if element!=type_end and tokens[element].text!=";":continue
        cursor=type_end+1
        if cursor>=len(tokens)or tokens[cursor].text!="=":continue
        cursor+=1
        if cursor>=len(tokens):continue
        if tokens[cursor].text=="&":cursor+=1
        if cursor>=len(tokens)or tokens[cursor].text!="[":continue
        array_start=cursor;array_end=pairs[cursor]
        if array_end+1>=len(tokens)or tokens[array_end+1].text!=";":continue
        cursor+=1;elements=[];safe=True
        while cursor<array_end:
            first=cursor
            if range_elements:
                if tokens[cursor].text!="(":safe=False;break
                end=pairs[cursor]
                group=tokens[cursor:end+1]
                if (len(group)not in {5,6}or group[2].text!=","or
                        not _NUMBER.fullmatch(group[1].text)or not _NUMBER.fullmatch(group[3].text)or
                        len(group)==6 and group[4].text!=","):
                    safe=False;break
                cursor=end+1
            else:
                if not _NUMBER.fullmatch(tokens[cursor].text):safe=False;break
                cursor+=1
            if cursor<array_end:
                if tokens[cursor].text!=",":safe=False;break
                cursor+=1
            elements.append("".join(part.text for part in tokens[first:cursor]))
        body_start=tokens[array_start].end;body_end=tokens[array_end].start
        # A data declaration still needs attribution when an unfamiliar
        # initializer cannot be compacted. Retain comments without alteration.
        if any(start<body_end and end>body_start for start,end,_doc in comments):safe=False
        enclosing=next((first for first,last in opaque if first<=token.start<last),None)
        if enclosing is not None:safe=False
        tables.append(UnicodeTable(name,token.start,token.start if enclosing is None else enclosing,body_start,body_end,tuple(elements)if safe else None))
    return tuple(tables)


def compact_unicode_tables(source,width=100):
    """Pack complete numeric elements to bounded lines without changing tokens."""
    try:tables=unicode_tables(source)
    except _Unsupported:return source
    edits=[]
    for table in tables:
        if table.elements is None:continue
        indent=_indent(source,table.start);prefix=indent+"    "
        lines=[];line=prefix
        for element in table.elements:
            separator=" "if line!=prefix else""
            if line!=prefix and len(line)+len(separator)+len(element)>width:
                lines.append(line);line=prefix;separator=""
            line+=separator+element
        if line!=prefix:lines.append(line)
        replacement="\n"+"\n".join(lines)+"\n"+indent if lines else""
        edits.append((table.body_start,table.body_end,replacement))
    for first,last,replacement in reversed(edits):source=source[:first]+replacement+source[last:]
    return source


def attach_unicode_notice(source,notice):
    """Place the full license beside the first table and identify later tables."""
    tables=unicode_tables(source)
    if not tables:return source
    edits=[]
    for index,table in enumerate(tables):
        position=table.notice_start
        indent=_indent(source,position)
        label=f"Unicode 16.0 data table {index+1}: {table.name}"
        if index:
            block=f"// {label}; license: table 1 ({tables[0].name}) above."
        else:block=notice+"\n// "+label+"."
        lines=block.splitlines()
        line_start=source.rfind("\n",0,position)+1
        prefix=""if source[line_start:position].isspace()or line_start==position else"\n"+indent
        insertion=prefix+("\n"+indent).join(lines)+"\n"+indent
        edits.append((position,insertion))
    for position,insertion in reversed(edits):source=source[:position]+insertion+source[position:]
    return source
