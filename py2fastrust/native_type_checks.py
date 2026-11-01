"""Builtin primitive type predicates over captured values and finite tags."""
import ast
from .references import BuiltinIdentity


TYPE_NAMES = frozenset({'classmethod', 'int', 'bool', 'float', 'str', 'bytes', 'list', 'range',
                        'tuple', 'dict', 'set', 'map', 'zip', 'filter', 'enumerate', 'reversed'})


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
        if name=='reversed':
            from .native_class_reverse_iterators import matches_builtin_reversed
            return matches_builtin_reversed(emitter,value)
        if name in {'map','zip','filter','enumerate'}:
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
        from .native_module_linking import ClassReferenceType
        if isinstance(classes.kind,ClassReferenceType):
            def source_match(candidate):
                if union_kind(candidate.kind):
                    return project(candidate.kind,candidate.code,lambda kind,code:source_match(Expression(code,kind)))
                if domain(candidate.kind)!='object':return 'false'
                owner=emitter.model.classes[candidate.kind.name]
                if not isinstance(owner.node,ast.ClassDef)or owner.node.bases or owner.node.keywords:
                    from .native_classes import ClassUnsupported
                    raise ClassUnsupported(node,'source-class isinstance needs inheritance/metaclass instance-check dispatch for this class; that protocol is not implemented',types=(('instance',candidate.kind),),proof='source class inheritance and instance-check protocol')
                if not hasattr(emitter.model,'module_linker'):
                    from .native_classes import ClassUnsupported
                    raise ClassUnsupported(node,'source-class isinstance needs the retained class-definition reference in a linked native instance',proof='source class object identity')
                return 'Rc::ptr_eq(&('+candidate.code+').borrow().class_definition,&('+classes.code+'))'
            return source_match(value)
        if function_kind(classes.kind):
            arms = [f'{variant(identity)}=>{builtin_match(value, identity.name)}'
                    for identity in classes.kind.builtins if identity.name in TYPE_NAMES]
            for identity in classes.kind.members:
                adapter=emitter.model.callable_cells.member_adapters.get(identity.module)
                if adapter is not None and identity.name in getattr(adapter,'TYPES',()):
                    arms.append(f'{variant(identity)}=>'+adapter.match_type(emitter,node,value,identity.name))
            return 'match ' + classes.code + '{' + ','.join(arms + ['_=>' + invalid()]) + '}'
        return invalid()

    return Expression(check(classes), 'bool')
