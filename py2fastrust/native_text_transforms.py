"""str padding, prefix and ASCII case transforms following Objects/unicodeobject.c (3.14).

ljust/rjust/center/zfill return the receiver unchanged when it is already at
least ``width`` long; otherwise they pad by code points (bytes in the ASCII
profile). center puts ``marg // 2 + (marg & width & 1)`` fill characters on
the left. zfill moves a leading sign in front of the zeros. removeprefix and
removesuffix drop one matching affix. swapcase, capitalize and title use the
ASCII case rules of the default profile; Unicode mode keeps them positioned
diagnostics, as for upper() and lower().
"""
import ast

PADDING = {'ljust': 0, 'rjust': 1, 'center': 2, 'zfill': 3}
CASES = {'swapcase': 0, 'capitalize': 1, 'title': 2}
AFFIXES = {'removeprefix': True, 'removesuffix': False}
NAMES = frozenset(PADDING) | frozenset(CASES) | frozenset(AFFIXES)
ARITY = {'ljust': (1, 2), 'rjust': (1, 2), 'center': (1, 2), 'zfill': (1, 1),
         'swapcase': (0, 0), 'capitalize': (0, 0), 'title': (0, 0), 'removeprefix': (1, 1), 'removesuffix': (1, 1)}
INTEGRAL = frozenset({'int', 'bool', 'int_bool'})


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


def _arity_error(name, arguments, keywords):
    low, high = ARITY[name]
    if keywords:
        return f'TypeError: str.{name}() takes no keyword arguments'
    count = len(arguments)
    if low <= count <= high:
        return None
    if low == high:
        return f'TypeError: str.{name}() takes exactly one argument ({count} given)' if low == 1 else f'TypeError: str.{name}() takes no arguments ({count} given)'
    if count < low:
        return f'TypeError: {name} expected at least {low} argument, got {count}'
    return f'TypeError: {name} expected at most {high} arguments, got {count}'


def analyze(model, plan, node, receiver, arguments, keywords):
    from .native_classes import ClassUnsupported, shape
    from .native_types import alternatives
    name = node.func.attr
    if name not in NAMES or shape(receiver) != 'str':
        return None
    if name in CASES and model.string_mode != 'ascii':
        raise ClassUnsupported(node, f'str.{name}() in Unicode mode requires Python 3.14 case-mapping data and title-case properties; this native adapter currently implements the ASCII profile',
                               proof='Python Unicode case mapping and conditional casing')
    if _arity_error(name, arguments, keywords) is None:
        for index, argument in enumerate(arguments):
            kinds = alternatives(shape(argument))
            if kinds is None or any(kind is None for kind in kinds):
                return model.cell(plan, node) if not model.final else None
            expected = INTEGRAL if name in PADDING and index == 0 else frozenset({'str'})
            if not set(kinds) <= expected:
                raise ClassUnsupported(node, f'this str.{name}() argument needs its index or text conversion protocol; builtin integers and str values are implemented',
                                       types=(('argument', shape(argument)),), proof='str transform argument conversion')
    sites = getattr(model, 'text_transform_sites', None)
    if sites is None:
        sites = model.text_transform_sites = {}
    sites[(plan.index, id(node))] = name
    return model.cell(plan, node, 'str')


def emit(emitter, node, receiver, arguments, keywords, wanted):
    from .native_classes import Expression
    from .native_class_builtins import _error
    from .native import _string
    name = getattr(emitter.model, 'text_transform_sites', {}).get((emitter.plan.index, id(node)))
    if name is None or receiver.kind != 'str':
        return None
    failure = _arity_error(name, arguments, list(keywords))
    if failure is not None:
        return _error(emitter, node, wanted, _string(failure) + '.to_owned()')
    used = getattr(emitter.model, 'text_transforms_used', None)
    if used is None:
        used = emitter.model.text_transforms_used = set()
    unicode = str(emitter.model.string_mode != 'ascii').lower()
    text = '(' + receiver.code + ').as_str()'
    if name in PADDING:
        used.add('pad')
        width = emitter.number(arguments[0])
        wide = '(' + width + ').to_i128()' if emitter.model.integer == 'bigint' else 'Some((' + width + ') as i128)'
        fill = '"0"' if name == 'zfill' else '" "' if len(arguments) == 1 else '(' + arguments[1].code + ').as_str()'
        call = f'native_text_pad({text},{wide},{fill},{PADDING[name]},{unicode})'
        code = 'NativeText::from(' + emitter.at(call, node) + ')'
    elif name in CASES:
        used.add('case')
        code = f'NativeText::from(native_text_ascii_case({text},{CASES[name]}))'
    else:
        affix = '(' + arguments[0].code + ').as_str()'
        method = 'strip_prefix' if AFFIXES[name] else 'strip_suffix'
        code = f'NativeText::from({text}.{method}({affix}).unwrap_or({text}).to_owned())'
    return Expression(emitter.coerce(Expression(code, 'str'), wanted, node), wanted)


PAD = r'''
fn native_text_pad(text:&str,width:Option<i128>,fill:&str,mode:u8,unicode:bool)->Result<String,String>{
    let mut fills=fill.chars();
    let fill=match(fills.next(),fills.next()){(Some(fill),None)=>fill,_=>return Err("TypeError: The fill character must be exactly one character long".to_owned())};
    let width=width.and_then(|width|isize::try_from(width).ok()).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())?;
    let length=if unicode{text.chars().count()}else{text.len()};
    if width<=length as isize{return Ok(text.to_owned());}
    let width=width as usize;let marg=width-length;
    let left=match mode{0=>0,1|3=>marg,_=>marg/2+(marg&width&1)};
    let mut result=String::new();
    result.try_reserve(text.len()+marg*fill.len_utf8()).map_err(|_|"MemoryError".to_owned())?;
    if mode==3{
        let signed=text.starts_with(['+','-']);
        if signed{result.push_str(&text[..1]);}
        result.extend(std::iter::repeat('0').take(marg));
        result.push_str(if signed{&text[1..]}else{text});
        return Ok(result);
    }
    result.extend(std::iter::repeat(fill).take(left));result.push_str(text);result.extend(std::iter::repeat(fill).take(marg-left));
    Ok(result)
}
'''

CASE = r'''
fn native_text_ascii_case(text:&str,mode:u8)->String{
    let mut result=String::with_capacity(text.len());let mut previous=false;
    for (index,c) in text.chars().enumerate(){
        let next=match mode{
            0=>if c.is_ascii_uppercase(){c.to_ascii_lowercase()}else{c.to_ascii_uppercase()},
            1=>if index==0{c.to_ascii_uppercase()}else{c.to_ascii_lowercase()},
            _=>{let next=if previous{c.to_ascii_lowercase()}else{c.to_ascii_uppercase()};previous=c.is_ascii_alphabetic();next}
        };
        result.push(next);
    }
    result
}
'''


def runtime(model):
    used = getattr(model, 'text_transforms_used', ())
    return ('' if 'pad' not in used else PAD) + ('' if 'case' not in used else CASE)
