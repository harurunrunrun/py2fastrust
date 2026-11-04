"""Typed finite sequence alternatives and their indexed access operations."""
import ast

from .native_types import EmptyType,alternatives

INTEGRAL=frozenset({"int","bool","int_bool"})
SEQUENCES=frozenset({"list","tuple","tuple_sequence","str","bytes"})
NONINDEXABLE=frozenset({"int","bool","int_bool","float","none","function"})


def constant_index(model,node):
    from .literal_semantics import Literal,integer_policy
    literal=Literal.from_ast(node)
    if literal is None or literal.kind not in {"int","bool"}:return None
    bits=0 if model.integer=="bigint"else 64 if model.integer=="i64"else 128
    return integer_policy(bits).normalize(literal.value)


def branches(value):
    root=value.root()
    if root.tag=="union":
        for child in root.args:yield from branches(child)
    else:yield root


def ordering_error(emitter,operator,left,right,node):
    from .native_classes import domain
    from .native_class_builtins import _type_name
    from .native_diagnostics import _OPERATORS
    from .native import _string
    a,b=domain(left.kind),domain(right.kind)
    numeric=INTEGRAL|{"float"}
    sealed=numeric|SEQUENCES|NONINDEXABLE|{"range","globals_dict"}
    if not isinstance(operator,(ast.Lt,ast.LtE,ast.Gt,ast.GtE))or a not in sealed or b not in sealed:return None
    if {a,b}<=numeric:return None
    if {a,b}<={"tuple","tuple_sequence"}:return None
    if a==b and a not in {"none","function","range","globals_dict"}:return None
    template=f"TypeError: '{_OPERATORS[type(operator)]}' not supported between instances of '{{}}' and '{{}}'"
    return emitter.at('Err::<bool,String>(format!('+_string(template)+','+_type_name(emitter,left,node)+','+_type_name(emitter,right,node)+'))',node)


def analyze_subscript(model,plan,node,owner,index):
    from .native_classes import Cell,ClassUnsupported,domain,shape,tuple_cell
    a,b=shape(owner),shape(index)
    if a is None:return None
    if not all(domain(choice)in SEQUENCES|NONINDEXABLE for choice in alternatives(a)):return None
    if b is None:
        if not model.final:return model.cell(plan,node)
        return None
    from .native_type_checks import TYPE_NAMES
    for kind in alternatives(a):
        if any(identity.name in TYPE_NAMES for identity in getattr(kind,"builtins",())):
            raise ClassUnsupported(node,"subscription of a builtin type needs its class __class_getitem__ or type-specific subscription-error protocol; that adapter is not registered",types=(("receiver",kind),),proof="builtin type subscription protocol")
    for kind in alternatives(b):
        if domain(kind)not in INTEGRAL|SEQUENCES|NONINDEXABLE:
            raise ClassUnsupported(node,"this indexed access needs the index object's __index__ protocol; no typed index-conversion adapter is registered",types=(("index",kind),),proof="index special-method conversion")
    result=model.cell(plan,node)
    inputs=[]
    if any(domain(choice)in INTEGRAL for choice in alternatives(b)):
        for value in branches(owner):
            if value.tag in {"list","tuple_sequence"}:inputs.append(value.args[0])
            elif tuple_cell(value):
                literal=constant_index(model,node.slice)
                if literal is not None:
                    if -len(value.args)<=literal<len(value.args):inputs.append(value.args[literal])
                else:inputs.extend(value.args)
            elif value.tag in {"str","bytes"}:inputs.append(Cell("str"if value.tag=="str"else"int"))
    if not inputs:inputs.append(Cell("none"))
    for value in inputs:
        if not model.namespace.contribute(result,value,node,force=True):model.contribute(result,value,node)
    return model.remember(plan,node,result)


def emit_subscript(emitter,node,owner,index,wanted):
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native_class_builtins import _type_name,_error
    from .native import _string
    if not all(domain(choice)in SEQUENCES|NONINDEXABLE for choice in alternatives(owner.kind)):return None
    if union_kind(owner.kind):
        return Expression(project(owner.kind,owner.code,lambda kind,code:
            emit_subscript(emitter,node,Expression(f"({code}).clone()",kind),index,wanted).code),wanted)
    if union_kind(index.kind):
        return Expression(project(index.kind,index.code,lambda kind,code:
            emit_subscript(emitter,node,owner,Expression(f"({code}).clone()",kind),wanted).code),wanted)
    tag=domain(owner.kind)
    if tag in NONINDEXABLE:
        return _error(emitter,node,wanted,'format!("TypeError: \'{}\' object is not subscriptable",'+_type_name(emitter,owner,node)+')')
    if domain(index.kind)not in INTEGRAL:
        if tag=="str":template="TypeError: string indices must be integers, not '{}'"
        elif tag=="bytes":template="TypeError: byte indices must be integers or slices, not {}"
        else:template=f"TypeError: {'tuple'if tag=='tuple_sequence'else tag} indices must be integers or slices, not {{}}"
        return _error(emitter,node,wanted,'format!('+_string(template)+','+_type_name(emitter,index,node)+')')
    number=emitter.number(index)
    if tag=="list":
        code=emitter.at(f"class_list_get(&{owner.code},&({number}))",node)
        raw=owner.kind.element
    elif tag=="str":
        code=emitter.at(f"class_string_get(&{owner.code},&({number}))",node);raw="str"
    elif tag=="bytes":
        offset=emitter.at(f"class_index(&({number}),{owner.code}.len()).map_err(|_|\"IndexError: index out of range\".to_owned())",node)
        code=f"class_from_usize({owner.code}[{offset}]as usize)";raw="int"
    elif tag=="tuple_sequence":
        offset=emitter.at(f'class_index(&({number}),{owner.code}.len()).map_err(|_|"IndexError: tuple index out of range".to_owned())',node)
        code=f"{owner.code}.as_slice()[{offset}].clone()";raw=owner.kind.element
    else:
        literal=constant_index(emitter.model,node.slice)
        if literal is not None:
            if not -len(owner.kind.fields)<=literal<len(owner.kind.fields):
                return _error(emitter,node,wanted,'"IndexError: tuple index out of range".to_owned()')
            position=literal%len(owner.kind.fields)
            return Expression(emitter.coerce(Expression(f"{owner.code}.{position}.clone()",owner.kind.fields[position]),wanted,node),wanted)
        offset=emitter.fresh()
        bound=emitter.at(f'class_index(&({number}),{len(owner.kind.fields)}).map_err(|_|"IndexError: tuple index out of range".to_owned())',node)
        arms=[str(position)+"=>"+emitter.coerce(Expression(f"{owner.code}.{position}.clone()",kind),wanted,node)for position,kind in enumerate(owner.kind.fields)]
        arms.append('_=>unreachable!("tuple index contradicts checked bounds")')
        return Expression("{"+f"let {offset}={bound};match {offset}"+"{"+",".join(arms)+"}}",wanted)
    if tag=='list'and(emitter.plan.index,id(node))in getattr(emitter.model,'positional_list_reads',{}):
        from .native_list_positions import project_element
        return project_element(emitter,code,raw,wanted,node)
    return Expression(emitter.coerce(Expression(code,raw),wanted,node),wanted)
