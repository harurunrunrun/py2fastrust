from .native_types import DequeType,deque_type
"""Typed list operations with owned vectors and identity-preserving shared rows."""

import ast

from .native import _Binding, _DequeInfo, _Expression, _ListInfo, _Unsupported, _string
from .native_types import ListType, SharedListType, TupleType, TupleSequenceType, TypedListInfo, immutable, join_types, rust_type, tuple_code
from .call_semantics import FunctionSignature
from .native_stream_plans import ConsumerKind, ConsumerPlan, consumer_plan, context


HELPERS = r'''
fn native_typed_reserve<T>(values:&mut Vec<T>,additional:usize)->Result<(),String> {
    let length=values.len().checked_add(additional).ok_or("MemoryError")?;
    if length>isize::MAX as usize{return Err("MemoryError".into());}
    values.try_reserve(additional).map_err(|_|"MemoryError".to_string())
}
fn native_typed_push<T>(values:&mut Vec<T>,value:T)->Result<(),String> {
    native_typed_reserve(values,1)?;
    values.push(value);
    Ok(())
}
fn native_typed_copy<T:Clone>(values:&[T])->Result<Vec<T>,String> {
    let mut result=Vec::new();
    native_typed_reserve(&mut result,values.len())?;
    result.extend(values.iter().cloned());
    Ok(result)
}
'''


from .native_list_operations import HELPERS as _LIST_OPERATION_HELPERS
HELPERS += _LIST_OPERATION_HELPERS
from .native_list_methods import HELPERS as _LIST_SEARCH_HELPERS
HELPERS += _LIST_SEARCH_HELPERS
from .native_sequence_methods import HELPERS as _SEQUENCE_METHOD_HELPERS
HELPERS += _SEQUENCE_METHOD_HELPERS

def _enable(g):
    g.has_typed_lists = True
    # The existing checked structural index helper is shared by both list
    # implementations. Its integer-specific get/set functions are pruned.
    g.has_lists = True


def _length(g, code):
    return f"Int::from_i128(({code}) as i128)" if not g.bits else f"(({code}) as NativeInt)"


def _index(g, code, length, node, *, assignment=False):
    call = f"native_big_list_index(&({code}),{length})" if not g.bits else f"native_index({code},{length})"
    if assignment:
        call += '.map_err(|_|String::from("IndexError: list assignment index out of range"))'
    return g.at(call, node)


def _clone(g, value, kind):
    return value.code if value.kind == kind and value.owned else g.coerce(value, kind)


def _ordering(g,left,right,node):
    from .native_nested_lists import total_order
    shared_order=total_order(g,left,right,node)
    if shared_order is not None:return shared_order
    shared=getattr(g,"sequence_ordering",None)
    if shared is not None:return shared(left,right,node)
    numeric = {"int","bool","int_bool"}
    if left.kind in numeric and right.kind in numeric:
        return f"({g.number(left)}).cmp(&({g.number(right)}))"
    if left.kind == right.kind and left.kind in {"str","bytes"}:
        return f"({left.code}).cmp(&({right.code}))"
    if isinstance(left.kind,TupleSequenceType)and isinstance(right.kind,TupleSequenceType):
        from .native_tuple_sequences import total_order
        return total_order(g,left,right,node)
    if isinstance(left.kind,TupleType) and isinstance(right.kind,TupleType):
        from .native_tuples import tuple_ordering
        return tuple_ordering(g,left,right,node)
    raise _Unsupported


def _none_operand(g,operand):
    """Query existing semantic facts without emitting an argument twice."""
    if operand.expression is None:return operand.default is not None and operand.default.value is None
    if isinstance(operand.expression,ast.Constant):return operand.expression.value is None
    from .native_constraint_lowering import facts_for
    facts,site=facts_for(g,operand.expression)
    return facts is not None and facts.expressions.get(site)=="none"


def _sort_options(g,node,environment,owners=()):
    reverse,key = "false",None
    lines=[]
    if isinstance(node,ConsumerPlan):
        bound=node.binding
    else:
        normalizer=context(g,environment)
        signature=FunctionSignature.declaration(keyword_only=("key","reverse"),default_names=("key","reverse"))
        from .call_semantics import CallBindingError
        try:
            bound=normalizer.bind(normalizer.invocation(node),signature,(("key",None),("reverse",False)))
        except CallBindingError as error:
            raise _Unsupported from error
    depth = len(g.iterating_lists)
    g.iterating_lists.extend(owners)
    checks=[]
    try:
        for operand in bound.explicit_order:
            if operand.parameter=="iterable":continue
            value=operand.expression
            if operand.parameter == "key":
                from .native_callbacks import prepare
                prepared=prepare(g,value,environment)
                if prepared is not None:
                    setup,key=prepared
                    lines.extend(setup)
                    continue
                if _none_operand(g,operand):
                    if not (isinstance(value,ast.Constant) and value.value is None):
                        captured=g.expression(value,environment)
                        lines.append(f"let {g.temporary()}={captured.code};")
                    continue
                if not isinstance(value,ast.Name):
                    raise _Unsupported
                key = value
            else:
                direction=g.expression(value,environment)
                captured,name = g.temporary(),g.temporary()
                code=direction.code if direction.owned else f"&({direction.code})"
                lines.append(f"let {captured}={code};")
                if not direction.owned and isinstance(value,ast.Name):g.iterating_lists.append(value.id)
                conversion=g.truth(_Expression(captured,direction.kind))
                # All call arguments are evaluated before builtin reverse
                # truth conversion. A later keyword can still raise or have effects.
                checks.append(f"let {name}={conversion};")
                reverse = name
    finally:
        del g.iterating_lists[depth:]
    return lines+checks,reverse,key


def _sort_code(g,owner,element,node,environment,reverse,key,*,forbidden_owners=()):
    left,right = g.temporary(),g.temporary()
    if key is None:
        comparison = _ordering(g,_Expression(f"(*{left})",element),_Expression(f"(*{right})",element),node)
        return f"{owner}.sort_by(|{left},{right}|{{let native_order={comparison};if {reverse} {{native_order.reverse()}}else{{native_order}}}});"
    item = g.temporary()
    from .native_callbacks import InlineLambda,invoke
    if isinstance(key,InlineLambda):
        value=invoke(g,key,(_Expression(f"{item}.clone()",element),),environment,node,
                     forbidden_owners=forbidden_owners)
    else:
        argument = "\0sort_" + g.temporary()
        inside = environment.copy()
        inside[argument] = _Binding(f"(*{item})",element)
        call = ast.copy_location(ast.Call(func=key,args=[ast.Name(id=argument,ctx=ast.Load())],keywords=[]),node)
        ast.fix_missing_locations(call)
        value = g.expression(call,inside)
    if not immutable(value.kind):
        raise _Unsupported
    g.register_type(value.kind)
    comparison = _ordering(g,_Expression(f"{left}.0",value.kind),_Expression(f"{right}.0",value.kind),node)
    decorated = g.temporary()
    push = g.at(f"native_typed_push(&mut {decorated},({value.code},{item}.clone()))",node)
    return (f"let mut {decorated}:Vec<({rust_type(value.kind)},{rust_type(element)})>=Vec::new();\n"
            f"for {item} in {owner}.iter() {{{push};}}\n"
            f"{decorated}.sort_by(|{left},{right}|{{let native_order={comparison};if {reverse} {{native_order.reverse()}}else{{native_order}}}});\n"
            f"{owner}.clear();\nfor (_, {item}) in {decorated} {{{owner}.push({item});}}")


def _collect(g,source,node,*,constructed=False):
    from .native_iterators import TraceContext, _owned
    if source.integer_words is not None:
        prefix=""if constructed else source.construct()
        call=source.integer_words.call(g,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
        return _Expression("{\n"+prefix+"\n"+call+"\n}","list_int",length=source.length)
    if source.tupled:
        element = TupleType(tuple(value.kind for value in source.values))
        code = tuple_code(_owned(g,value,value.kind) for value in source.values)
        value = _Expression(code,element)
    elif len(source.values) == 1:
        value = source.values[0]
        element = value.kind
    else:
        raise _Unsupported
    if not immutable(element) and not isinstance(element,SharedListType) and not (element == "list_int" and value.owned):
        raise _Unsupported
    kind = ("list_int" if element == "int" else "matrix_int" if element == "list_int" else ListType(element))
    g.register_type(kind)
    _enable(g)
    result = g.temporary()
    action = g.at(f"native_typed_push(&mut {result},{_clone(g,value,element)})",node) + ";"
    body = source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
    code = ("" if constructed else source.construct()) + f"\nlet mut {result}:{rust_type(kind)}=Vec::new();\n" + body + f"\n{result}"
    return _Expression("{\n" + code + "\n}",kind,length=source.length)


def _slice(g, node, owner, environment):
    g.has_slices = True
    container = g.temporary()
    lines = [f"let {container}:&[{rust_type(owner.kind.element)}]=&({owner.code});"]
    bounds, constants = [], []
    known = True
    for expression in (node.slice.lower,node.slice.upper,node.slice.step):
        if expression is None or isinstance(expression,ast.Constant) and expression.value is None:
            bounds.append("None")
            constants.append(None)
            continue
        value = g.expression(expression,environment)
        temporary = g.temporary()
        lines.append(f"let {temporary}={g.number(value)};")
        bound = (f"({temporary}) as i128" if g.bits else
                 f"{temporary}.to_i128().unwrap_or_else(||if {temporary}.is_negative(){{i128::MIN}}else{{i128::MAX}})")
        bounds.append(f"Some({bound})")
        constants.append(value.constant)
        known &= value.constant is not None
    indices = g.temporary()
    lines.append(f"let {indices}={g.at(f'native_slice_indices({container}.len(),{",".join(bounds)})',node)};")
    length = None
    if owner.length is not None and known:
        try:
            length = len(range(*slice(*constants).indices(owner.length)))
        except ValueError:
            pass
    return _Expression("{ " + " ".join(lines) + f" native_flat_slice({container},{indices}) }}",owner.kind,length=length)


def try_expression(g, node, environment):
    from .native_list_methods import try_expression as sequence_search
    search=sequence_search(g,node,environment)
    if search is not None:return search
    if isinstance(node,ast.Name):
        binding = environment.get(node.id)
        if isinstance(binding,_Binding) and isinstance(binding.info,TypedListInfo):
            return _Expression(binding.slot,binding.info.kind,owned=False,length=binding.info.length)
        return None
    plan=consumer_plan(g,node,environment,{ConsumerKind.LIST,ConsumerKind.SORTED})
    if plan is not None:
        from .native_iterators import Planner
        # Only a key-free ordering of exact builtin values may discard set
        # traversal order. Producer adapters with callbacks do not inherit
        # this permission; transparent iter(...) alone may retain it.
        order_free=plan.kind is ConsumerKind.SORTED and _none_operand(g,plan.binding.binding["key"])
        source=Planner(g).lower(plan.source,environment,allow_set=order_free)
        if plan.kind is ConsumerKind.LIST:
            return _collect(g,source,node)
        lines=[source.setup+("\n"+source.begin if source.eager else "")]
        checkpoint=len(g.expression_mutations)
        options,reverse,key=_sort_options(g,plan,environment,source.owners if source.eager else ())
        lines.extend(options)
        changed={binding.slot for binding in g.expression_mutations[checkpoint:]}
        if any(isinstance(environment.get(name),_Binding) and environment[name].slot in changed
               for name in source.owners):
            source.length=None
            source.nonempty=False
        result=_collect(g,source,node,constructed=True)
        if not source.eager:lines.append(source.begin)
        owner=g.temporary()
        lines.append(f"let mut {owner}={result.code};")
        element="int"if result.kind=="list_int"else result.kind.element
        from .native_types import EmptyType
        if source.length!=0 and not isinstance(element,EmptyType):
            lines.append(_sort_code(g,owner,element,node,environment,reverse,key))
        return _Expression("{\n"+"\n".join(lines)+f"\n{owner}\n}}",result.kind,length=result.length)
    if isinstance(node,ast.List) and node.elts:
        values = [g.expression(value,environment) for value in node.elts]
        element = values[0].kind
        for value in values[1:]:
            element = join_types(element,value.kind)
            if element is None:
                raise _Unsupported
        if element == "int" or not immutable(element):
            return None
        _enable(g)
        g.register_type(ListType(element))
        return _Expression("vec![" + ",".join(_clone(g,value,element) for value in values) + "]",ListType(element),length=len(values))
    if isinstance(node,ast.Subscript):
        owner = g.expression(node.value,environment)
        if not isinstance(owner.kind,ListType):
            return None
        _enable(g)
        if isinstance(node.slice,ast.Slice):
            return _slice(g,node,owner,environment)
        value = g.expression(node.slice,environment)
        container,index = g.temporary(),g.temporary()
        checked = _index(g,index,f"{container}.len()",node)
        return _Expression(f"{{ let {container}=&({owner.code}); let {index}={g.number(value)}; {container}[{checked}].clone() }}",owner.kind.element)
    if not isinstance(node,ast.Call):
        return None
    if isinstance(node.func,ast.Name) and node.func.id == "len" and len(node.args) == 1 and not node.keywords:
        value = g.expression(node.args[0],environment)
        if isinstance(value.kind,ListType):
            return _Expression(_length(g,f"({value.code}).len()"),"int",value.length)
    return None


def try_statement(g,node,environment):
    from .native_nested_lists import try_statement as shared_statement
    shared=shared_statement(g,node,environment)
    if shared is not None:return shared
    from .native_constraint_lowering import reset_statement
    reset=reset_statement(g,node,environment)
    if reset is not None:return reset
    if isinstance(node,ast.Expr)and isinstance(node.value,ast.Call):
        from .native_list_methods import try_expression as sequence_method
        method=sequence_method(g,node.value,environment)
        if method is not None:return method.code+";",environment
    printed = _print(g,node,environment)
    if printed is not None:
        return printed
    from .native_unpack import try_statement as unpack_statement
    unpacked=unpack_statement(g,node,environment)
    if unpacked is not None:return unpacked
    if isinstance(node,ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0],ast.Subscript):
        target = node.targets[0]
        if not isinstance(target.value,ast.Name) or isinstance(target.slice,ast.Slice):
            return None
        binding = environment.get(target.value.id)
        if not isinstance(binding,_Binding) or not isinstance(binding.info,TypedListInfo):
            return None
        if target.value.id in g.iterating_lists:
            raise _Unsupported
        value = g.expression(node.value,environment)
        index = g.expression(target.slice,environment)
        item,offset,position = g.temporary(),g.temporary(),g.temporary()
        checked = _index(g,offset,f"{binding.slot}.len()",target,assignment=True)
        return (f"let {item}={_clone(g,value,binding.kind.element)};\nlet {offset}={g.number(index)};\n"
                f"let {position}={checked};\n{binding.slot}[{position}]={item};"),environment
    return None


def _representation(g,value,*,quoted=False):
    from .native_types import EmptyType
    if isinstance(value.kind,EmptyType):return f"native_empty::<String>({value.code})"
    from .native_unions import representation
    finite=representation(g,value,_representation,quoted)
    if finite is not None:return finite
    from .native_key_containers import representation as mapping_representation
    mapping=mapping_representation(g,value,_representation)
    if mapping is not None:return mapping
    kind,code = value.kind,value.code
    if kind == "str":
        if quoted:
            g.has_tuples = True
            return f"native_tuple_repr_str(&({code}))"
        return f"({code}).to_string()"
    if kind == "bool":
        return f'(if {code} {{"True"}}else{{"False"}}).to_owned()'
    if kind in {"int","int_bool"}:
        return f"({code}).to_string()"
    if kind == "float":
        g.has_extended_scalars = True
        return f"native_float_text({code})"
    if deque_type(kind):
        g.has_deques=True
        from .native_deques import representation
        return representation(g,value)
    if kind == "bytes":
        from .native_stdio import _enable
        _enable(g)
        return f"native_bytes_repr(&({code}))"
    if isinstance(kind,TupleSequenceType):
        from .native_tuple_sequences import representation
        return representation(g,value)
    if isinstance(kind,TupleType):
        owner,result = g.temporary(),g.temporary()
        lines = [f"let {owner}=&({code});",f'let mut {result}=String::from("(");']
        for index,field in enumerate(kind.fields):
            if index:
                lines.append(f'{result}.push_str(", ");')
            representation = _representation(g,_Expression(f"{owner}.{index}",field,owned=False),quoted=True)
            lines.append(f"{result}.push_str(&({representation}));")
        if len(kind.fields) == 1:
            lines.append(f"{result}.push(',');")
        lines.append(f"{result}.push(')'); {result}")
        return "{" + " ".join(lines) + "}"
    if kind == "list_int" or isinstance(kind,ListType):
        element = "int" if kind == "list_int" else kind.element
        owner,result,index,item = (g.temporary() for _ in range(4))
        representation = _representation(g,_Expression(f"(*{item})",element,owned=False),quoted=True)
        return (f'{{let {owner}='+(f"({code}).borrow()"if isinstance(kind,SharedListType)else f"&({code})")+f'; let mut {result}=String::from("["); '
                f'for ({index},{item}) in {owner}.iter().enumerate() {{if {index}>0 {{{result}.push_str(", ");}} '
                f"{result}.push_str(&({representation}));}} {result}.push(']'); {result}}}")
    raise _Unsupported


def _print_value(g,node,environment):
    from .native_characters import CharacterBinding
    from .references import BuiltinIdentity,callable_reference
    def text_read(expression):
        if isinstance(expression,ast.Name):
            binding=environment.get(expression.id)
            return (isinstance(binding,_Binding) and binding.kind=="str"
                    or isinstance(binding,CharacterBinding))
        if isinstance(expression,ast.Constant):return type(expression.value)is str
        if isinstance(expression,ast.Subscript) and not isinstance(expression.slice,ast.Slice):
            return text_read(expression.value)
        return (isinstance(expression,ast.Call) and len(expression.args)==1 and not expression.keywords
                and callable_reference(g,expression.func,environment)==BuiltinIdentity("str")
                and text_read(expression.args[0]))
    if hasattr(g,"read_expression") and text_read(node):return g.read_expression(node,environment)
    return g.expression(node,environment)


def _print(g,node,environment,*,values=None):
    if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)):
        return None
    return print_call(g,node.value,environment,values=values,error_node=node)


def print_call(g,call,environment,*,values=None,error_node=None):
    from .references import BuiltinIdentity,callable_reference
    if callable_reference(g,call.func,environment)!=BuiltinIdentity("print"):return None
    from .native_unions import union_kind
    separator,end,flush = " ","\n",False
    seen = set()
    for keyword in call.keywords:
        if keyword.arg in seen or keyword.arg not in {"sep","end","flush"} or not isinstance(keyword.value,ast.Constant):
            raise _Unsupported
        seen.add(keyword.arg)
        value = keyword.value.value
        if keyword.arg == "flush":
            if type(value) is not bool:
                raise _Unsupported
            flush = value
        else:
            if type(value) is not str:
                raise _Unsupported
            if keyword.arg == "sep":
                separator = value
            else:
                end = value
    lines = []
    arguments = []
    forbidden=g.iterating_lists
    g.iterating_lists=list(forbidden)
    try:
        for index,argument in enumerate(call.args):
            star=isinstance(argument,ast.Starred)
            source=argument.value if star else argument
            value=_print_value(g,source,environment) if values is None else values[index][1]
            if not star and not value.owned and not immutable(value.kind):
                from .native_sequence_storage import deferred_truth
                captured=deferred_truth(g,value,source,environment)
                if captured is not None:
                    setup,deferred,owners=captured
                    lines.extend(setup)
                    g.iterating_lists.extend(owners)
                    arguments.append((False,deferred))
                    continue
            temporary = g.temporary()
            if value.kind=="str" and not value.owned and hasattr(g,"read_binding"):
                lines.append(g.read_binding(temporary,value))
                arguments.append((star,_Expression(temporary,value.kind,owned=False)))
                continue
            if star and isinstance(value.kind,SharedListType):
                value=_Expression(f"({value.code}).borrow().clone()",ListType(value.kind.element))
            if star and not value.owned and isinstance(value.kind,DequeType):
                from .native_deques import copy_code
                code=copy_code(g,value,source)
            elif star and not value.owned and (value.kind in {"list_int","deque_int"} or isinstance(value.kind,ListType)):
                code=f"({value.code}).clone()"
            elif not value.owned and immutable(value.kind):
                code=g.coerce(value,value.kind)
            else:
                code=value.code
            lines.append(f"let {temporary}={code};")
            arguments.append((star,_Expression(temporary,value.kind)))
    finally:
        g.iterating_lists=forbidden
    first = g.temporary()
    lines.append(f"let mut {first}=true;")
    def write(value):
        prefix=f"if !{first} {{native_output.push_str({_string(separator)});}} {first}=false;\n"
        if value.kind in {"int","int_bool"}:
            return prefix+f'write!(&mut native_output,"{{}}",{value.code}).unwrap();'
        if value.kind=="str":return prefix+f"native_output.push_str(&({value.code}));"
        if value.kind=="bool":return prefix+f'native_output.push_str(if {value.code} {{"True"}}else{{"False"}});'
        display = _representation(g,value)
        return prefix+f"native_output.push_str(&({display}));"
    for star,value in arguments:
        if not star:
            lines.append(write(value))
        elif value.kind in {"list_int","deque_int"} or isinstance(value.kind,(ListType,DequeType,TupleSequenceType)):
            element = "int" if value.kind in {"list_int","deque_int"} else value.kind.element
            item = g.temporary()
            lines.append(f"for {item} in {value.code}.iter() {{\n{write(_Expression(f'(*{item})',element,owned=False))}\n}}")
        elif isinstance(value.kind,TupleType):
            for index,kind in enumerate(value.kind.fields):
                lines.append(write(_Expression(f"{value.code}.{index}",kind,owned=False)))
        else:
            raise _Unsupported
    lines.append(f"native_output.push_str({_string(end)});")
    if flush:
        lines.append(g.at("native_flush_output(&mut native_output)",error_node or call)+";")
    return "\n".join(lines),environment



def stream(g,node,environment,planner,*,value=None):
    from .native_iterators import Stream
    value = g.expression(node,environment) if value is None else value
    from .native_nested_lists import stream as shared_stream
    shared=shared_stream(g,node,value,planner)
    if shared is not None:return shared
    if not isinstance(value.kind,ListType):
        return None
    if not immutable(value.kind.element):
        raise _Unsupported
    _enable(g)
    cursor = g.temporary()
    owners = {node.id} if isinstance(node,ast.Name) else set()
    from .native_container_reads import capture
    read = capture(g,node,value,environment)
    owner,setup = read.owner,read.setup
    fields = ((value.kind.element,"@.clone()",True),)
    return planner.leaf(setup,f"let {cursor}={owner}.iter();",cursor,fields,owners,length=value.length)

from .native_constraint_lowering import MAP_HELPERS
HELPERS+=MAP_HELPERS

from .native_nested_lists import HELPERS as SHARED_LIST_HELPERS
HELPERS+=SHARED_LIST_HELPERS
