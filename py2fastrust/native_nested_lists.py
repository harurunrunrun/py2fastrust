"""Identity-preserving physical storage for solved nested builtin lists.

The solver selects allocations, not source patterns. Captures own a typed handle;
contents are borrowed only after later operands have finished evaluating.
"""
import ast
from dataclasses import replace
from .native_types import SharedListType,ListType,immutable,rust_type,is_maybe,unmaybe


HELPERS=r'''
type NativeSharedList<T> = std::rc::Rc<std::cell::RefCell<Vec<T>>>;
fn native_shared_list<T>(values:Vec<T>)->NativeSharedList<T> {
    std::rc::Rc::new(std::cell::RefCell::new(values))
}
fn native_shared_len<T>(values:&NativeSharedList<T>)->usize {values.borrow().len()}
struct NativeSharedIter<T> { owner:NativeSharedList<T>, front:usize, back:Option<usize>, done:bool }
fn native_shared_iter<T:Clone>(owner:NativeSharedList<T>)->NativeSharedIter<T> {
    NativeSharedIter {owner,front:0,back:None,done:false}
}
impl<T:Clone> NativeSharedIter<T> {
    fn rev(mut self)->std::iter::Rev<Self> {
        self.back=Some(self.owner.borrow().len());std::iter::Iterator::rev(self)
    }
}
impl<T:Clone> Iterator for NativeSharedIter<T> {
    type Item=T;
    fn next(&mut self)->Option<T> {
        let values=self.owner.borrow();
        if self.done||self.front>=values.len()||self.back.is_some_and(|back|self.front>=back){self.done=true;return None;}
        let result=values[self.front].clone();self.front+=1;Some(result)
    }
}
impl<T:Clone> DoubleEndedIterator for NativeSharedIter<T> {
    fn next_back(&mut self)->Option<T> {
        let values=self.owner.borrow();
        let back=self.back.get_or_insert(values.len());
        if self.done||*back==0||*back<=self.front||*back>values.len(){self.done=true;return None;}
        *back-=1;Some(values[*back].clone())
    }
}
'''


def shared_element(kind):
    return immutable(kind) or isinstance(kind,SharedListType) and shared_element(kind.element)


def kind_for(g,node,environment):
    from .native import _Binding
    from .native_sequence_storage import binding_name
    if isinstance(node,ast.Name):
        binding=environment.get(binding_name(g,node))
        if isinstance(binding,_Binding):return unmaybe(binding.kind)
    from .native_constraint_lowering import facts_for
    facts,site=facts_for(g,node)
    return facts.storage.get(site,facts.expressions.get(site)) if facts is not None else None


def coerce(value,kind):
    from .native import _Unsupported
    if isinstance(value.kind,SharedListType) or isinstance(kind,SharedListType):
        if value.kind!=kind:
            raise _Unsupported("this list reference needs a compatible shared element layout; converting its contents would change Python alias identity",types=(("source",value.kind),("target",kind)),proof="shared list layout and identity")
        return f"({value.code}).clone()"
    return None


def wrap_result(g,value,expected,node):
    from .native import _Expression,_Unsupported
    from .native_constraints import canonical_kind
    if canonical_kind(value.kind)!=canonical_kind(expected) or not value.owned:
        raise _Unsupported("a nested list allocation requires owned elements or existing shared references with the solved physical layout",node=node,types=(("source",value.kind),("target",expected)),proof="nested list identity-preserving storage")
    if isinstance(value.kind,SharedListType):raise _Unsupported("incompatible shared list allocation layout",node=node)
    g.register_type(expected);g.has_typed_lists=g.has_lists=True
    return _Expression(f"native_shared_list({value.code})",expected)


def allocation(g,node,environment,kind,term):
    from .native import _Expression,_Unsupported
    g.register_type(kind);g.has_typed_lists=g.has_lists=True
    if term.operation=="list":
        # Each child expression is evaluated once and moved/cloned as a handle.
        values=[g.expression(g.type_analysis.graph.nodes[item.site],environment) for item in term.operands]
        elements=",".join(g.coerce(value,kind.element) for value in values)
        vec=g.at(f"native_typed_literal([{elements}])",node) if values else f"Vec::<{rust_type(kind.element)}>::new()"
        return _Expression(f"native_shared_list({vec})",kind)
    if term.operation=="call" and not term.operands[1] and not term.operands[2]:
        return _Expression(f"native_shared_list(Vec::<{rust_type(kind.element)}>::new())",kind)
    return None


def _index(g,index,length,node,assignment=False):
    from .native_typed_lists import _index
    return _index(g,index,length,node,assignment=assignment)


def try_expression(g,node,environment):
    from .native import _Binding,_Expression,_MaybeInfo,_Unsupported,_string
    if isinstance(node,ast.Name):
        from .native_sequence_storage import binding_name
        binding=environment.get(binding_name(g,node))
        if not isinstance(binding,_Binding) or not isinstance(unmaybe(binding.kind),SharedListType):return None
        kind=unmaybe(binding.kind)
        if isinstance(binding.info,_MaybeInfo):
            # The ordinary name path supplies the positioned Python exception.
            if binding.info.owner is None:message=f"NameError: name '{node.id}' is not defined"
            elif g.scope_name()!=binding.info.owner:message=f"NameError: cannot access free variable '{node.id}' where it is not associated with a value in enclosing scope"
            else:message=f"UnboundLocalError: cannot access local variable '{node.id}' where it is not associated with a value"
            code=g.at(f"{binding.slot}.as_ref().cloned().ok_or_else(||String::from({_string(message)}))",node)
        else:code=f"{binding.slot}.clone()"
        return _Expression(code,kind)
    if isinstance(node,ast.Subscript) and isinstance(kind_for(g,node.value,environment),SharedListType):
        owner=g.expression(node.value,environment)
        if isinstance(node.slice,ast.Slice):
            raise _Unsupported("shared nested list slicing is not implemented yet",node=node,types=(("owner",owner.kind),),proof="shallow-copy list slice preserving row identity")
        value=g.expression(node.slice,environment)
        handle,index,position,result=(g.temporary() for _ in range(4))
        checked=_index(g,index,f"{handle}.borrow().len()",node)
        code=(f"{{let {handle}={owner.code};let {index}={g.number(value)};let {position}={checked};"
              f"let {result}={handle}.borrow()[{position}].clone();{result}}}")
        return _Expression(code,owner.kind.element)
    if isinstance(node,ast.Subscript) and not isinstance(node.slice,ast.Slice):
        kind=kind_for(g,node.value,environment)
        if kind=="list_int" or isinstance(kind,ListType):
            from .native_container_reads import capture
            owner=g.expression(node.value,environment)
            read=capture(g,node.value,owner,environment)
            value=g.expression(node.slice,environment)
            index,position,result=(g.temporary() for _ in range(3))
            checked=_index(g,index,f"({read.owner}).len()",node)
            element="int"if owner.kind=="list_int"else owner.kind.element
            return _Expression("{"+read.setup+f"let {index}={g.number(value)};let {position}={checked};let {result}=({read.owner})[{position}].clone();{result}"+"}",element)
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        if isinstance(kind_for(g,node.func.value,environment),SharedListType):
            from .native_list_methods import try_expression as sequence_method
            method=sequence_method(g,node,environment)
            if method is not None:return method
            raise _Unsupported(f"shared list method {node.func.attr!r} has no native operation implementation",node=node,types=(("receiver",kind_for(g,node.func.value,environment)),))
    if isinstance(node,ast.BinOp):
        left_kind=kind_for(g,node.left,environment);right_kind=kind_for(g,node.right,environment)
        if not isinstance(left_kind,SharedListType) and not isinstance(right_kind,SharedListType):return None
        left=g.expression(node.left,environment);right=g.expression(node.right,environment)
        a,b=g.temporary(),g.temporary();lines=[f"let {a}={left.code};",f"let {b}={right.code};"]
        if isinstance(node.op,ast.Mult) and isinstance(left.kind,SharedListType)!=isinstance(right.kind,SharedListType):
            values,count,kind=(a,b,left.kind) if isinstance(left.kind,SharedListType) else (b,a,right.kind)
            number=_Expression(count,right.kind if values==a else left.kind)
            from .native_sequence_methods import _bound
            bound=_bound(g,number,None)
            code=g.at(f"native_typed_repeat(&({values}.borrow())[..],{bound})",node)
        elif isinstance(node.op,ast.Add) and left.kind==right.kind and isinstance(left.kind,SharedListType):
            kind=left.kind
            code=g.at(f"native_typed_concat(&({a}.borrow())[..],&({b}.borrow())[..],|item|item,|item|item)",node)
        else:raise _Unsupported("these shared list operand layouts do not have a compatible native list operator",node=node,types=(("left",left.kind),("right",right.kind)))
        result=g.temporary()
        return _Expression("{"+"".join(lines)+f"let {result}=native_shared_list({code});{result}"+"}",kind)
    return None


def _inplace(g,left,operator,right_node,node,environment):
    """Mutate an already captured reference, after one RHS evaluation."""
    from .native import _Expression,_Unsupported
    from .native_types import list_type
    if isinstance(operator,ast.Add):
        right_kind=kind_for(g,right_node,environment)
        if list_type(right_kind):
            right=g.expression(right_node,environment);captured=g.temporary()
            code=right.code if right.owned else f"&({right.code})"
            lines=[f"let {captured}={code};"]
            from .native_sequence_storage import capture_shared
            from .native_sequence_plans import sequence_method
            from .native_sequence_methods import lower
            storage=capture_shared(g,_Expression(f"({left.code}).clone()",left.kind));lines.extend(storage.setup)
            value=lower(g,storage,sequence_method(left.kind,"extend"),
                        {"iterable":_Expression(captured,right.kind,owned=right.owned)},node,environment)
            lines.append(value.code+";")
            return lines
        from .native_iterators import Planner,TraceContext,stream_item
        from .native_stream_plans import context,ProducerKind,ProducerPlan
        plan=context(g,environment).producer(right_node)
        lines=[]
        if plan.kind is ProducerKind.VALUE or right_kind in {"int","bool","int_bool","float","none","str","bytes"} or getattr(right_kind,"fields",None)is not None:
            right=g.expression(right_node,environment);captured=g.temporary()
            code=(right.code if right.owned else g.coerce(right,right.kind)if immutable(right.kind)else f"&({right.code})")
            lines.append(f"let {captured}={code};")
            if right.kind in {"int","bool","int_bool","float","none"}:
                from .native_comparisons import _type_name
                from .native import _string
                message=_string("TypeError: '{}' object is not iterable")
                error=f'Err::<(),String>(format!({message},{_type_name(_Expression(captured,right.kind))}))'
                lines.append(g.at(error,node)+";")
                return lines
            source=Planner(g).lower(ProducerPlan(ProducerKind.VALUE,right_node),environment,
                                    captured_value=_Expression(captured,right.kind))
        else:source=Planner(g).lower(plan,environment)
        value=stream_item(g,source)
        item=g.coerce(value,left.kind.element)
        action=g.at(f"native_typed_push(&mut *{left.code}.borrow_mut(),{item})",node)+";"
        lines.append(source.construct())
        lines.append(source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node)))
        return lines
    if isinstance(operator,ast.Mult):
        right=g.expression(right_node,environment);count=g.temporary();lines=[f"let {count}={right.code};"]
        if right.kind not in {"int","bool","int_bool"}:
            from .native_comparisons import _type_name
            from .native import _string
            message=_string("TypeError: can't multiply sequence by non-int of type '{}'")
            error=f'Err::<(),String>(format!({message},{_type_name(_Expression(count,right.kind))}))'
            lines.append(g.at(error,node)+";")
            return lines
        from .native_sequence_methods import _bound
        bound=_bound(g,_Expression(count,right.kind),None)
        repeated=g.temporary()
        # Reserve/copy before replacing contents: allocation failure leaves the
        # original object intact, while every alias keeps this same handle.
        lines.append(f"let {repeated}="+g.at(f"native_typed_repeat(&({left.code}.borrow())[..],{bound})",node)+";")
        lines.append(f"*{left.code}.borrow_mut()={repeated};")
        return lines
    raise _Unsupported("this shared-list in-place operator is not implemented",node=node,types=(("left",left.kind),))


def try_statement(g,node,environment):
    from .native import _Binding,_Expression,_Unsupported
    if isinstance(node,ast.AugAssign)and isinstance(node.target,ast.Name):
        kind=kind_for(g,node.target,environment)
        if isinstance(kind,SharedListType):
            left=g.expression(node.target,environment);handle=g.temporary()
            lines=[f"let {handle}={left.code};"]
            lines.extend(_inplace(g,_Expression(handle,left.kind),node.op,node.value,node,environment))
            slot=g.bind(node.target.id,_Expression(handle,left.kind),environment)
            lines.append(f"{slot}={handle};")
            return "\n".join(lines),environment
    if isinstance(node,ast.Assign) and all(isinstance(target,ast.Name) for target in node.targets):
        kind=kind_for(g,node.value,environment)
        if not isinstance(kind,SharedListType):return None
        value=g.expression(node.value,environment);name=g.temporary()
        lines=[f"let {name}={value.code};"]
        for target in node.targets:
            lines.append(f"{g.bind(target.id,value,environment)}={name}.clone();")
        return "\n".join(lines),environment
    if not isinstance(node,(ast.Assign,ast.AugAssign,ast.Delete)):return None
    target=(node.targets[0] if isinstance(node,(ast.Assign,ast.Delete)) and len(node.targets)==1 else node.target if isinstance(node,ast.AugAssign) else None)
    if not isinstance(target,ast.Subscript) or not isinstance(kind_for(g,target.value,environment),SharedListType):return None
    if isinstance(target.slice,ast.Slice):raise _Unsupported("shared list slice assignment/deletion is not implemented",node=target)
    lines=[]
    # Assignment evaluates RHS first. AugAssign captures and reads LHS first.
    item=g.temporary()
    if isinstance(node,ast.Assign):
        value=g.expression(node.value,environment);lines.append(f"let {item}={value.code};")
    owner=g.expression(target.value,environment);handle,index=g.temporary(),g.temporary()
    lines.append(f"let {handle}={owner.code};")
    offset=g.expression(target.slice,environment);lines.append(f"let {index}={g.number(offset)};")
    if isinstance(node,ast.AugAssign):
        old=g.temporary();position=g.temporary();checked=_index(g,index,f"{handle}.borrow().len()",target)
        lines.append(f"let {position}={checked};let {old}={handle}.borrow()[{position}].clone();")
        if isinstance(owner.kind.element,SharedListType):
            lines.extend(_inplace(g,_Expression(old,owner.kind.element),node.op,node.value,node,environment))
            value=_Expression(old,owner.kind.element)
            lines.append(f"let {item}={old};")
        else:
            right=g.expression(node.value,environment)
            value=g.binary(node.op,_Expression(old,owner.kind.element),right,node)
            lines.append(f"let {item}={value.code};")
    position=g.temporary();checked=_index(g,index,f"{handle}.borrow().len()",target,assignment=not isinstance(node,ast.Delete))
    lines.append(f"let {position}={checked};")
    if isinstance(node,ast.Delete):lines.append(f"{handle}.borrow_mut().remove({position});")
    else:
        converted=g.coerce(_Expression(item,value.kind),owner.kind.element)
        lines.append(f"{handle}.borrow_mut()[{position}]={converted};")
    return "\n".join(lines),environment


def stream(g,node,value,planner):
    from .native import _Expression
    if not isinstance(value.kind,SharedListType):return None
    g.register_type(value.kind);g.has_typed_lists=g.has_lists=True
    owner,cursor=g.temporary(),g.temporary()
    # Each next owns one immutable value or shared row reference. No contents
    # borrow spans the Python loop body; list mutation remains observable.
    return planner.leaf(f"let {owner}={value.code};",f"let {cursor}=native_shared_iter({owner});",cursor,
                        ((value.kind.element,"@",True),))


def _list_shape(kind):
    from .native_constraints import canonical_kind
    shape=canonical_kind(kind)
    return shape if isinstance(shape,ListType)else None


def _contents(code,kind):
    return f"&({code}.borrow())[..]"if isinstance(kind,SharedListType)else f"&({code})[..]"


def _capture_contents(g,value):
    owner,view=g.temporary(),g.temporary()
    if isinstance(value.kind,SharedListType):
        return f"let {owner}=({value.code}).clone();let {view}={owner}.borrow();",f"&({view})[..]"
    return f"let {owner}=&({value.code});",f"&({owner})[..]"


def equality(g,left,right,node):
    """Compare captured list references and owned vectors by Python contents."""
    from .native import _Expression,_Unsupported
    a,b=_list_shape(left.kind),_list_shape(right.kind)
    if a is not None and b is not None:
        setup_a,view_a=_capture_contents(g,left);setup_b,view_b=_capture_contents(g,right)
        first,second,x,y,result=(g.temporary()for _ in range(5))
        equal=equality(g,_Expression(f"(*{x})",left.kind.element if isinstance(left.kind,ListType)else"int",owned=False),
                       _Expression(f"(*{y})",right.kind.element if isinstance(right.kind,ListType)else"int",owned=False),node)
        return ("{"+setup_a+setup_b+f"let {first}={view_a};let {second}={view_b};"
                f"let {result}={first}.len()=={second}.len()&&{first}.iter().zip({second}.iter()).all(|({x},{y})|{equal});{result}}}")
    if a is not None or b is not None:return "false"
    from .native_tuples import _equal,_scalar
    if not _scalar(left.kind) or not _scalar(right.kind):
        raise _Unsupported("list element equality needs the common identity-aware scalar protocol for these payloads",node=node,types=(("left",left.kind),("right",right.kind)),proof="Python list element equality, including floating/custom identity")
    return _equal(g,left,right)


def ordering(g,left,right,operator,node):
    from .native import _Expression
    from .native_comparisons import ORDERING,ordering as scalar_ordering,_unsupported_pair
    a,b=_list_shape(left.kind),_list_shape(right.kind)
    if a is None or b is None:return _unsupported_pair(g,left,right,operator,node)
    setup_a,view_a=_capture_contents(g,left);setup_b,view_b=_capture_contents(g,right)
    first,second,x,y,label=(g.temporary()for _ in range(5))
    first_element=left.kind.element if isinstance(left.kind,ListType)else"int"
    second_element=right.kind.element if isinstance(right.kind,ListType)else"int"
    one=_Expression(f"(*{x})",first_element,owned=False);two=_Expression(f"(*{y})",second_element,owned=False)
    equal=equality(g,one,two,node)
    order=(ordering(g,one,two,operator,node)if _list_shape(one.kind)is not None or _list_shape(two.kind)is not None
           else scalar_ordering(g,one,two,operator,node))
    return ("{"+setup_a+setup_b+f"let {first}={view_a};let {second}={view_b};"
            f"'{label}:{{for({x},{y})in {first}.iter().zip({second}.iter()){{if !({equal}){{break '{label} {order};}}}}"
            f"{first}.len(){ORDERING[type(operator)]}{second}.len()}}}}")


def total_order(g,left,right,node):
    """Nonfallible native lexicographic order for proved comparable payloads."""
    if not isinstance(left.kind,SharedListType)or left.kind!=right.kind:return None
    from .native import _Expression
    from .native_typed_lists import _ordering
    setup_a,view_a=_capture_contents(g,left);setup_b,view_b=_capture_contents(g,right)
    a,b,x,y,result,part=(g.temporary()for _ in range(6))
    first=_Expression(f"(*{x})",left.kind.element,owned=False)
    second=_Expression(f"(*{y})",right.kind.element,owned=False)
    inner=_ordering(g,first,second,node)
    return ("{"+setup_a+setup_b+f"let {a}={view_a};let {b}={view_b};"
            f"let mut {result}=std::cmp::Ordering::Equal;for({x},{y})in {a}.iter().zip({b}.iter()){{"
            f"let {part}={inner};if {part}!=std::cmp::Ordering::Equal{{{result}={part};break;}}}}"
            f"if {result}==std::cmp::Ordering::Equal{{{result}={a}.len().cmp(&{b}.len());}}{result}}}")


def comparison(g,node,values):
    from .native import _Expression,_Unsupported
    if not any(isinstance(value.kind,SharedListType)for value in values):return None
    names=[g.temporary()for _ in values];tail="true"
    for index in reversed(range(len(node.ops))):
        left,right=values[index],values[index+1];a,b=names[index:index+2];operator=node.ops[index]
        one=_Expression(a,left.kind);two=_Expression(b,right.kind)
        if isinstance(operator,(ast.Is,ast.IsNot)):
            # A raw vector is a proved unique object. All references to a
            # promoted allocation use its handle from the allocation site.
            test=(f"std::rc::Rc::ptr_eq(&{a},&{b})"if left.kind==right.kind and isinstance(left.kind,SharedListType)else"false")
            if isinstance(operator,ast.IsNot):test="!("+test+")"
        elif isinstance(operator,(ast.Eq,ast.NotEq)):
            test=equality(g,one,two,node)
            if isinstance(operator,ast.NotEq):test="!("+test+")"
        elif type(operator)in {ast.Lt,ast.LtE,ast.Gt,ast.GtE}:
            test=ordering(g,one,two,operator,node)
        elif isinstance(operator,(ast.In,ast.NotIn))and isinstance(right.kind,SharedListType):
            item=g.temporary();equal=equality(g,one,_Expression(f"(*{item})",right.kind.element,owned=False),node)
            test=f"{b}.borrow().iter().any(|{item}|{equal})"
            if isinstance(operator,ast.NotIn):test="!("+test+")"
        else:raise _Unsupported("this shared list comparison requires an unimplemented Python operand protocol",node=node,types=(("left",left.kind),("right",right.kind)))
        tested=g.temporary()
        tail=f"{{let {b}={right.code};let {tested}={test};{tested}&&({tail})}}"
    return _Expression(f"{{let {names[0]}={values[0].code};{tail}}}","bool")
