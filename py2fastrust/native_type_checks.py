"""Builtin primitive type predicates over captured values and finite tags."""
from .references import BuiltinIdentity


TYPE_NAMES = frozenset({'int', 'bool', 'float', 'str', 'list', 'range',
                        'tuple', 'dict', 'set', 'map', 'zip', 'filter', 'enumerate'})


def requires_frames(analysis):
    return any(BuiltinIdentity('isinstance') in fact.identity.alternatives
               for scope in analysis.scopes.values() for fact in scope.calls.values())


def emit(emitter, node, arguments):
    from .native import _string
    from .native_classes import Expression, domain
    from .native_aot_callables import function_kind, variant
    from .native_unions import project, union_kind
    value, classes = arguments

    def invalid():
        message = 'TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union'
        return emitter.at(f'Err::<bool,String>({_string(message)}.to_owned())', node)

    def builtin_match(value, name):
        if union_kind(value.kind):
            return project(value.kind, value.code, lambda kind, code:
                           builtin_match(Expression(code, kind), name))
        tag = domain(value.kind)
        if name == 'int':
            return str(tag in {'int', 'bool', 'int_bool'}).lower()
        if name == 'bool' and tag == 'int_bool':
            return f'matches!(&({value.code}),NativeScalar::Bool(_))'
        if name == 'tuple':return str(tag in {'tuple','tuple_sequence'}).lower()
        if name in {'map','zip','filter'}:
            return str(tag == 'iterator' and value.kind.record.operation == name).lower()
        return str(tag == name).lower()

    def check(classes):
        if union_kind(classes.kind):
            return project(classes.kind, classes.code,
                           lambda kind, code: check(Expression(code, kind)))
        tag = domain(classes.kind)
        if tag == 'tuple':
            parts = [check(Expression(f'({classes.code}).{index}.clone()', kind))
                     for index, kind in enumerate(classes.kind.fields)]
            return '(' + '||'.join('(' + part + ')' for part in parts) + ')' if parts else 'false'
        if tag == 'tuple_sequence':
            owner, member = emitter.fresh(), emitter.fresh()
            branch = check(Expression(member, classes.kind.element))
            return ('{let ' + owner + '=' + classes.code + ';loop{let mut matched=false;'
                    'for ' + member + ' in ' + owner + '.as_slice().iter().cloned(){'
                    'if ' + branch + '{matched=true;break;}}break matched;}}')
        if function_kind(classes.kind):
            arms = [f'{variant(identity)}=>{builtin_match(value, identity.name)}'
                    for identity in classes.kind.builtins if identity.name in TYPE_NAMES]
            return 'match ' + classes.code + '{' + ','.join(arms + ['_=>' + invalid()]) + '}'
        return invalid()

    return Expression(check(classes), 'bool')
