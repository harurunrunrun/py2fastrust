"""Conservative item reachability for Rust emitted by pytors.

This pass does not simplify expressions or inspect Python values. It removes
only unreferenced Rust definitions. Identifiers in strings are included too,
covering implicit named format captures. Method names are conservatively shared
between live owner types; trait implementations stay with their live owners.
Unknown item forms and macros fail closed by returning the complete source.
Comments, licenses and source provenance are retained byte-for-byte.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
import re


_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_RAW = re.compile(r'(?:br|cr|r)(#*)"')
_CHAR = re.compile(r"(?:b)?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|[^\n])|[^'\\\n])'")
_KINDS = {"fn", "struct", "enum", "type", "const", "static", "use", "impl", "trait", "mod", "extern"}


class _Unsupported(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int
    kind: str = "punct"


@dataclass
class _Item:
    name: str | None
    kind: str
    start: int
    end: int
    references: set[str]
    owner: str | None = None
    trait: bool = False
    owner_nominal: bool = True
    body_start: int | None = None
    body_end: int | None = None
    children: list["_Item"] = field(default_factory=list)
    protected: bool = False


@dataclass(frozen=True)
class RustPruneResult:
    source: str
    before_bytes: int
    after_bytes: int
    removed_functions: tuple[str, ...] = ()
    removed_items: tuple[str, ...] = ()
    retained: bool = False
    reason: str | None = None


def _lex(source):
    tokens, comments = [], []
    position, size = 0, len(source)
    while position < size:
        char = source[position]
        if char.isspace():
            position += 1
            continue
        start = position
        if source.startswith("//", position):
            end = source.find("\n", position)
            position = size if end < 0 else end + 1
            comments.append((start, position, source[start:position].startswith(("///", "//!"))))
            continue
        if source.startswith("/*", position):
            depth = 1
            position += 2
            while depth:
                opening, closing = source.find("/*", position), source.find("*/", position)
                if closing < 0:
                    raise _Unsupported("unterminated block comment")
                if opening >= 0 and opening < closing:
                    depth += 1
                    position = opening + 2
                else:
                    depth -= 1
                    position = closing + 2
            comments.append((start, position, source[start:start + 3] in {"/**", "/*!"}))
            continue
        raw = _RAW.match(source, position)
        if raw:
            closing = '"' + raw[1]
            end = source.find(closing, raw.end())
            if end < 0:
                raise _Unsupported("unterminated raw string")
            position = end + len(closing)
            tokens.append(_Token(source[start:position], start, position, "literal"))
            continue
        quote = position + 1 if char in "bc" and source[position:position + 2] in {'b"', 'c"'} else position
        if source[quote:quote + 1] == '"':
            position = quote + 1
            while position < size:
                if source[position] == "\\":
                    position += 2
                elif source[position] == '"':
                    position += 1
                    break
                else:
                    position += 1
            else:
                raise _Unsupported("unterminated string")
            tokens.append(_Token(source[start:position], start, position, "literal"))
            continue
        character = _CHAR.match(source, position)
        if character:
            position = character.end()
            tokens.append(_Token(source[start:position], start, position, "literal"))
            continue
        if char == "'":
            lifetime = _WORD.match(source, position + 1)
            if lifetime is None:
                raise _Unsupported("unknown apostrophe token")
            position = lifetime.end()
            tokens.append(_Token(source[start:position], start, position, "lifetime"))
            continue
        word = _WORD.match(source, position)
        if word:
            position = word.end()
            tokens.append(_Token(word[0], start, position, "identifier"))
            continue
        if ord(char) >= 128:
            raise _Unsupported("non-ASCII Rust identifier")
        if char.isdigit():
            position += 1
            while position < size and (source[position].isalnum() or source[position] in "_."):
                position += 1
            tokens.append(_Token(source[start:position], start, position, "literal"))
            continue
        position += 1
        tokens.append(_Token(char, start, position))
    pairs, stack = {}, []
    for index, token in enumerate(tokens):
        if token.text in {"(", "[", "{"}:
            stack.append(index)
        elif token.text in {")", "]", "}"}:
            if not stack or tokens[stack[-1]].text != {")": "(", "]": "[", "}": "{"}[token.text]:
                raise _Unsupported("unbalanced Rust delimiters")
            opening = stack.pop()
            pairs[opening] = index
    if stack:
        raise _Unsupported("unbalanced Rust delimiters")
    return tokens, comments, pairs


def _references(tokens):
    result = set()
    for token in tokens:
        if token.kind == "identifier":
            result.add(token.text)
        elif token.kind == "literal":
            # Includes format!("{NAMED_CONSTANT}") captures. Ordinary strings
            # can overretain a definition but can never hide a dependency.
            result.update(_WORD.findall(token.text))
    return result


def _group_end(tokens,start):
    """Skip one balanced type group, including nested generic arguments."""
    opening=tokens[start].text
    closing={"(":")","[":"]","{":"}","<":">"}[opening]
    cursor=start+1
    while cursor<len(tokens):
        text=tokens[cursor].text
        if text==closing and not (closing==">"and tokens[cursor-1].text=="-"):
            return cursor+1
        if text in {"(","[","{","<"}:
            cursor=_group_end(tokens,cursor)
        else:cursor+=1
    raise _Unsupported("unbalanced impl type")


def _type_end(tokens,start):
    """Recognize emitted Rust type heads without guessing a nominal owner.

    Structural types can carry blanket implementations. Their implementation
    and dependencies must be retained independently of any element name.
    """
    if start>=len(tokens):raise _Unsupported("missing impl type")
    cursor=start
    text=tokens[cursor].text
    if text in {"&","*"}:
        cursor+=1
        if text=="&"and cursor<len(tokens)and tokens[cursor].kind=="lifetime":cursor+=1
        if cursor<len(tokens)and tokens[cursor].text in {"mut","const"}:cursor+=1
        end,_root=_type_end(tokens,cursor)
        return end,None
    if text=="(":
        end=_group_end(tokens,cursor)
        cursor+=1
        while cursor<end-1:
            cursor,_root=_type_end(tokens,cursor)
            if cursor<end-1:
                if tokens[cursor].text!=",":raise _Unsupported("unknown tuple impl type")
                cursor+=1
        return end,None
    if text=="[":
        end=_group_end(tokens,cursor)
        cursor,_root=_type_end(tokens,cursor+1)
        if cursor<end-1:
            if tokens[cursor].text!=";"or cursor+1==end-1:raise _Unsupported("unknown array impl type")
            # Const expressions are already tokenized and group-balanced. They
            # contribute dependencies but never establish a nominal type owner.
        return end,None
    if text=="!":return cursor+1,None
    if tokens[cursor].kind!="identifier"or text in {"dyn","impl","fn","unsafe","extern"}:
        raise _Unsupported("unknown impl type")
    root=text
    cursor+=1
    if cursor<len(tokens)and tokens[cursor].text=="<":cursor=_group_end(tokens,cursor)
    qualified=False
    while cursor+1<len(tokens)and tokens[cursor].text==tokens[cursor+1].text==":":
        qualified=True
        cursor+=2
        if cursor>=len(tokens)or tokens[cursor].kind!="identifier":raise _Unsupported("unknown impl type path")
        cursor+=1
        if cursor<len(tokens)and tokens[cursor].text=="<":cursor=_group_end(tokens,cursor)
    return cursor,None if qualified else root


def _impl_target(header,trait):
    start=1
    generics=set()
    if start<len(header)and header[start].text=="<":
        end=_group_end(header,start)
        cursor=start+1
        while cursor<end-1:
            if header[cursor].text=="const":cursor+=1
            if header[cursor].kind=="identifier":generics.add(header[cursor].text)
            while cursor<end-1 and header[cursor].text!=",":
                cursor=_group_end(header,cursor)if header[cursor].text in {"(","[","{","<"}else cursor+1
            cursor+=1
        start=end
    if trait:
        cursor=start
        while cursor<len(header)and header[cursor].text!="for":
            cursor=_group_end(header,cursor)if header[cursor].text in {"(","[","{","<"}else cursor+1
        if cursor==len(header):raise _Unsupported("missing impl target")
        start=cursor+1
    end,root=_type_end(header,start)
    if end<len(header)and header[end].text!="where":raise _Unsupported("unknown impl target suffix")
    nominal=root is not None and root not in generics
    label=root if nominal else "".join(token.text for token in header[start:end])
    return label,nominal


def _owner(header,trait):
    """Compatibility helper for the parser's concrete/structural owner label."""
    return _impl_target(header,trait)[0]


def _parse(source, tokens, comments, pairs, start=0, stop=None, owner=None):
    stop = len(tokens) if stop is None else stop
    result = []
    position = start
    while position < stop:
        first = position
        # Attributes belong to their definition; removing only fn would leave
        # an attribute attached to the next live item.
        while position < stop and tokens[position].text == "#":
            position += 1
            if position < stop and tokens[position].text == "!":
                position += 1
            if position >= stop or tokens[position].text != "[":
                raise _Unsupported("unknown attribute")
            position = pairs[position] + 1
        attribute_end = position
        if position >= stop:
            raise _Unsupported("attribute without item")
        if tokens[position].text == "thread_local" and position + 2 < stop and tokens[position + 1].text == "!" and tokens[position + 2].text in {"{", "(", "["}:
            end=pairs[position+2]+1
            if end<stop and tokens[end].text==";":end+=1
            result.append(_Item(None,"macro",tokens[first].start,tokens[end-1].end,_references(tokens[first:end]),protected=True))
            position=end
            continue
        cursor = position
        while cursor < stop and tokens[cursor].text not in _KINDS:
            if tokens[cursor].text in {";", "{", "}", "!"}:
                raise _Unsupported("unknown Rust item")
            cursor = pairs[cursor] + 1 if tokens[cursor].text in {"(", "["} else cursor + 1
        if cursor >= stop:
            raise _Unsupported("unknown Rust item")
        kind = tokens[cursor].text
        if kind == "const" and cursor + 1 < stop and tokens[cursor + 1].text == "fn":
            cursor += 1
            kind = "fn"
        if kind == "extern":
            # Imported symbols are declarations, not hidden calls. Preserve an
            # extern block as an opaque root and retain all referenced types.
            ending=cursor+1
            while ending<stop and tokens[ending].text not in {"{",";"}:
                ending=pairs[ending]+1 if tokens[ending].text in {"(","["} else ending+1
            if ending>=stop:raise _Unsupported("unterminated extern item")
            ending=pairs[ending]+1 if tokens[ending].text=="{" else ending+1
            if ending<stop and tokens[ending].text==";":ending+=1
            result.append(_Item(None,"extern",tokens[first].start,tokens[ending-1].end,_references(tokens[first:ending]),protected=True))
            position=ending
            continue
        name = tokens[cursor + 1].text if cursor + 1 < stop and kind != "impl" else None
        if kind != "impl" and tokens[cursor + 1].kind != "identifier":
            raise _Unsupported("unknown item name")
        end, body = cursor + 1, None
        while end < stop:
            text = tokens[end].text
            if text == ";":
                end += 1
                break
            if text == "{":
                if kind in {"const", "static", "type", "use"}:
                    end = pairs[end] + 1
                    continue
                body = end
                end = pairs[end] + 1
                if end < stop and tokens[end].text == ";":
                    end += 1
                break
            end = pairs[end] + 1 if text in {"(", "["} else end + 1
        else:
            raise _Unsupported("unterminated Rust item")
        lower, upper = tokens[first].start, tokens[end - 1].end
        gap_start=tokens[first-1].end if first else 0
        protected = any(gap_start <= a < upper and doc for a, _, doc in comments)
        item = _Item(name, kind, lower, upper, _references(tokens[first:end]), owner=owner, protected=protected)
        if kind == "impl":
            if body is None:
                raise _Unsupported("impl without body")
            header = tokens[cursor:body]
            if any(token.text=="for" and index+1<len(header) and header[index+1].text=="<" for index,token in enumerate(header)):
                raise _Unsupported("higher-ranked impl bound")
            item.trait = any(token.text == "for" for token in header)
            item.owner,item.owner_nominal = _impl_target(header,item.trait)
            item.references = _references(tokens[first:body])
            item.body_start, item.body_end = tokens[body].end, tokens[pairs[body]].start
            if item.trait:
                item.references.update(_references(tokens[body + 1:pairs[body]]))
            else:
                item.children = _parse(source, tokens, comments, pairs, body + 1, pairs[body], item.owner)
                # Associated type/const items use the same conservative owner
                # and member-name rule as methods.
                for child in item.children:
                    child.references.update(item.references)
        elif kind in {"mod", "trait"}:
            # A live trait may call a default method without spelling its name
            # at the call site. Keep the declaration and all defaults together.
            if kind == "mod":
                item.protected = True
        elif kind == "use":
            item.protected = True
        if owner is not None and kind not in {"fn", "type", "const"}:
            raise _Unsupported("unknown inherent impl member")
        # Prefixes outside recognized visibility/modifier forms fail closed.
        prefix = tokens[attribute_end:cursor]
        if any(token.text=="pub" for token in prefix):item.protected=True
        allowed = {"pub", "crate", "super", "self", "in", "unsafe", "async", "default", "const", "(", ")", ":"}
        if any(token.kind == "identifier" and token.text not in allowed for token in prefix):
            raise _Unsupported("unknown item modifier")
        result.append(item)
        position = end
    return result


def prune_rust_source_with_report(source: str, *, roots=("main",)) -> RustPruneResult:
    """Remove definitions unreachable from roots in generated standalone Rust.

    Unsupported syntax returns the original source. Public/linkage exports,
    macros and uncommon compiler attributes also retain the whole input rather
    than risk discarding externally or implicitly referenced definitions.
    """
    before = len(source.encode("utf-8"))
    try:
        tokens, comments, pairs = _lex(source)
        opaque_macros={"macro_rules","global_asm","include","include_str","include_bytes","concat","env","option_env","file","module_path"}
        if any(token.text in opaque_macros and index+1<len(tokens) and tokens[index+1].text=="!" for index,token in enumerate(tokens)):
            raise _Unsupported("macro or linkage dependency")
        builtin_macros={"assert","assert_eq","assert_ne","debug_assert","debug_assert_eq","debug_assert_ne","format","format_args","write","writeln","print","println","eprint","eprintln","matches","vec","unreachable","panic","todo","unimplemented","cfg","thread_local","stringify","concat","env","option_env","file","line","column","module_path","compile_error"}
        for index,token in enumerate(tokens[:-1]):
            if token.kind=="identifier" and index+2<len(tokens) and tokens[index+1].text=="!" and tokens[index+2].text in {"(","[","{"} and token.text not in builtin_macros|{"if","while","return","break","yield","let","match","else"}:
                raise _Unsupported("unknown Rust macro: "+token.text)
            if token.text=="r" and tokens[index+1].text=="#":raise _Unsupported("raw Rust identifier")
            if token.text=="#":
                opening=index+1+(tokens[index+1].text=="!")
                if opening<len(tokens) and tokens[opening].text=="[":
                    attribute=tokens[opening+1].text
                    if attribute not in {"allow","deny","warn","forbid","derive","inline","cold","must_use","cfg","repr","doc","non_exhaustive","deprecated","track_caller","test","ignore","should_panic","link_name","link"}:
                        raise _Unsupported("unknown compiler attribute: "+attribute)
                    if attribute=="derive" and any(part.kind=="identifier" and part.text not in {"derive","Clone","Copy","Debug","Default","PartialEq","Eq","PartialOrd","Ord","Hash"} for part in tokens[opening+1:pairs[opening]]):
                        raise _Unsupported("unknown derive implementation")
        # Inner crate attributes are not definitions. Preserve their bytes and
        # skip them when collecting top-level items.
        initial = 0
        while initial + 2 < len(tokens) and tokens[initial].text == "#" and tokens[initial + 1].text == "!" and tokens[initial + 2].text == "[":
            initial = pairs[initial + 2] + 1
        items = _parse(source, tokens, comments, pairs, initial)
        globals_by_name, members_by_name = defaultdict(list), defaultdict(list)
        inherent, traits = [], []
        for item in items:
            if item.kind == "impl":
                (traits if item.trait else inherent).append(item)
                if not item.trait:
                    for child in item.children:
                        members_by_name[child.name].append(child)
            elif item.name is not None:
                globals_by_name[item.name].append(item)
        concrete_types={name for name,definitions in globals_by_name.items() if any(item.kind in {"struct","enum"} for item in definitions)}
        # Blanket/external/alias impls can apply to a concrete type without its
        # target spelling appearing at a call site. Retain those entire impls.
        for item in traits:
            if not item.owner_nominal or item.owner not in concrete_types:item.protected=True
        for item in inherent:
            if not item.owner_nominal or item.owner not in concrete_types:
                for child in item.children:child.protected=True
        if not all(name in globals_by_name for name in roots):
            raise _Unsupported("entry root missing")
        live, names, pending = set(), set(), deque()
        def retain(item):
            identity = id(item)
            if identity not in live:
                live.add(identity)
                pending.extend(item.references)
        for name in roots:
            for item in globals_by_name[name]:retain(item)
        for item in items:
            if item.protected:retain(item)
            if item.kind == "impl" and not item.trait:
                for child in item.children:
                    if item.protected or child.protected:retain(child)
        changed = True
        while pending or changed:
            while pending:
                name = pending.popleft()
                if name in names:continue
                names.add(name)
                for item in globals_by_name.get(name, ()):retain(item)
            changed = False
            for name in tuple(names):
                for item in members_by_name.get(name, ()):
                    if item.owner in names and id(item) not in live:
                        retain(item);changed = True
            for item in traits:
                if item.owner in names and id(item) not in live:
                    retain(item);changed = True
        removed_functions, removed_items, edits = [], [], []
        def remove(item):
            preserved = "".join(source[a:b] + ("\n" if not source[a:b].endswith("\n") else "")
                                for a, b, _ in comments if item.start <= a and b <= item.end)
            edits.append((item.start, item.end, preserved))
            (removed_functions if item.kind == "fn" else removed_items).append(
                (item.owner + "::" if item.owner else "") + (item.name or item.kind))
            if item.kind=="impl" and not item.trait:
                removed_functions.extend(item.owner+"::"+child.name for child in item.children if child.kind=="fn")
        for item in items:
            if item.kind == "impl" and not item.trait:
                if not item.protected and not any(id(child) in live for child in item.children):remove(item)
                else:
                    for child in item.children:
                        if id(child) not in live:remove(child)
            elif id(item) not in live:remove(item)
        output = source
        for start, end, replacement in sorted(edits, reverse=True):output = output[:start] + replacement + output[end:]
        return RustPruneResult(output, before, len(output.encode("utf-8")), tuple(removed_functions), tuple(removed_items))
    except (IndexError, _Unsupported) as error:
        return RustPruneResult(source, before, before, retained=True, reason=str(error))


def prune_rust_source(source: str, *, roots=("main",)) -> str:
    """Return the conservatively pruned source, preserving unsupported input."""
    return prune_rust_source_with_report(source, roots=roots).source
