"""str.splitlines, partition and rpartition following Objects/unicodeobject.c (3.14).

splitlines breaks at \\n, \\r, \\r\\n, \\v, \\f, \\x1c, \\x1d, \\x1e, \\x85,
\\u2028 and \\u2029, keeping the terminator only with ``keepends``; a final
terminator does not start an empty line. partition and rpartition split at the
first or last occurrence of a non-empty separator and return three strings.
"""
import ast

NAMES = frozenset({'splitlines', 'partition', 'rpartition'})


def requires_frames(unit, analysis):
    from .native_constraints import MethodValue
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    nodes = {unit.ordinal(node): node for node in ast.walk(unit.tree)}
    for scope in analysis.scopes.values():
        for ordinal, fact in scope.calls.items():
            for identity in fact.identity.alternatives:
                if isinstance(identity, MethodValue) and identity.name in NAMES:
                    if builtin_text_receiver_kinds(unit, scope, nodes.get(ordinal), identity, allowed=frozenset({'str'})):
                        return True
    return False


def constraint(analysis, term, context, name, kinds, value, TupleValue):
    """Ordinary-analysis result facts so frame selection sees the method results."""
    if name not in NAMES or kinds != {'str'}:
        return None
    if name == 'splitlines':
        result = value(analysis.allocation(term.site, 'list', context))
        analysis.insert(result, 'element', value('str'))
        return result
    return value(TupleValue((value('str'), value('str'), value('str'))))


def _error(name, arguments, keywords):
    if name == 'splitlines':
        names = [key for key, _ in keywords]
        if len(arguments) + len(names) > 1 or any(key != 'keepends' for key in names):
            return 'this str.splitlines() binding is invalid; it accepts one optional keepends argument'
        return None
    if keywords or len(arguments) != 1:
        return f'this str.{name}() binding is invalid; it takes exactly one positional separator'
    return None


def analyze(model, plan, node, receiver, arguments, keywords):
    from .native_classes import Cell, ClassUnsupported, shape
    from .native_types import alternatives
    name = node.func.attr
    if name not in NAMES or shape(receiver) != 'str':
        return None
    failure = _error(name, arguments, keywords)
    if failure is not None:
        raise ClassUnsupported(node, failure, proof='str method argument binding')
    values = list(arguments) + [value for _, value in keywords]
    for value in values:
        kinds = alternatives(shape(value))
        if any(kind is None for kind in kinds) or not kinds:
            if not model.final:
                return model.cell(plan, node)
        allowed = {'int', 'bool', 'int_bool'} if name == 'splitlines' else {'str'}
        if not set(kinds) <= allowed:
            raise ClassUnsupported(node, f'this str.{name}() argument needs its conversion or TypeError protocol; builtin {"integer/boolean" if name == "splitlines" else "str"} arguments are implemented',
                                   types=(('argument', shape(value)),), proof='str method argument conversion')
    sites = getattr(model, 'text_partition_sites', None)
    if sites is None:
        sites = model.text_partition_sites = set()
    sites.add((plan.index, id(node)))
    if name == 'splitlines':
        return model.cell(plan, node, 'list', (Cell('str'),))
    return model.cell(plan, node, 'tuple', (Cell('str'), Cell('str'), Cell('str')))


def emit(emitter, node, receiver, arguments, keywords, wanted):
    from .native_classes import Expression
    from .native_types import TupleType
    if (emitter.plan.index, id(node)) not in getattr(emitter.model, 'text_partition_sites', ()) or receiver.kind != 'str':
        return None
    name = node.func.attr
    text = '(' + receiver.code + ').as_str()'
    used = getattr(emitter.model, 'text_partition_used', None)
    if used is None:
        used = emitter.model.text_partition_used = set()
    if name == 'splitlines':
        used.add('splitlines')
        values = list(arguments) + list(keywords.values())
        keep = 'false' if not values else '(' + emitter.truth(values[0], node) + ')'
        item = emitter.fresh()
        converted = emitter.coerce(Expression('NativeText::from(' + item + ')', 'str'), wanted.element, node)
        code = ('class_list(native_text_splitlines(' + text + ',' + keep + ').into_iter().map(|' + item + '|' + converted
                + ').collect::<Vec<_>>())')
        return Expression(code, wanted)
    used.add('partition')
    separator = '(' + arguments[0].code + ').as_str()'
    parts = emitter.fresh()
    call = emitter.at('native_text_partition(' + text + ',' + separator + ',' + str(name == 'rpartition').lower() + ')', node)
    raw = TupleType(('str', 'str', 'str'))
    value = Expression('{let ' + parts + '=' + call + ';(NativeText::from(' + parts + '.0),NativeText::from(' + parts + '.1),NativeText::from(' + parts + '.2))}', raw)
    return Expression(emitter.coerce(value, wanted, node), wanted)


SPLITLINES = r'''
fn native_text_splitlines(text:&str,keepends:bool)->Vec<String>{
    let mut lines=Vec::new();let mut start=0;let mut chars=text.char_indices().peekable();
    while let Some((index,c))=chars.next(){
        if !matches!(c,'\n'|'\r'|'\u{b}'|'\u{c}'|'\u{1c}'|'\u{1d}'|'\u{1e}'|'\u{85}'|'\u{2028}'|'\u{2029}'){continue;}
        let mut end=index+c.len_utf8();
        if c=='\r'&&chars.peek().is_some_and(|(_,next)|*next=='\n'){chars.next();end+=1;}
        lines.push(text[start..if keepends{end}else{index}].to_owned());start=end;
    }
    if start<text.len(){lines.push(text[start..].to_owned());}
    lines
}
'''

PARTITION = r'''
fn native_text_partition(text:&str,separator:&str,last:bool)->Result<(String,String,String),String>{
    if separator.is_empty(){return Err("ValueError: empty separator".to_owned());}
    let found=if last{text.rfind(separator)}else{text.find(separator)};
    Ok(match found{
        Some(index)=>(text[..index].to_owned(),separator.to_owned(),text[index+separator.len()..].to_owned()),
        None if last=>(String::new(),String::new(),text.to_owned()),
        None=>(text.to_owned(),String::new(),String::new()),
    })
}
'''


def runtime(model):
    used = getattr(model, 'text_partition_used', ())
    return ('' if 'splitlines' not in used else SPLITLINES) + ('' if 'partition' not in used else PARTITION)
