"""Finite shared list shapes and their identity-preserving native operations.

Every nested list remains an Rc handle. Copying a list copies its outer vector
and clones element handles; it never copies the referenced inner containers.
"""
import ast

from .native import _Expression
from .native_types import ListType,TupleType,NullableType,UnionType,immutable


def shared_element(kind):
    """Kinds whose Clone implementation preserves Python element identity."""
    if immutable(kind):return True
    if isinstance(kind,ListType):return shared_element(kind.element)
    if isinstance(kind,TupleType):return all(shared_element(field)for field in kind.fields)
    if isinstance(kind,NullableType):return shared_element(kind.value)
    if isinstance(kind,UnionType):return all(shared_element(value)for value in kind.alternatives)
    from .native_classes import InstanceType
    return isinstance(kind,InstanceType)


def contains_cell(parent,child):
    """Read existing type links without modifying their union-find parents."""
    child=child.root();pending=list(parent.root().args);seen=set()
    while pending:
        current=pending.pop()
        if not hasattr(current,"root"):continue
        current=current.root()
        if current is child:return True
        if id(current)not in seen:
            seen.add(id(current));pending.extend(current.args)
    return False


def check_merge(left,right,node):
    if left is right:return
    if contains_cell(left,right)or contains_cell(right,left):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,"this storage flow would create a recursive list/tuple element layout; recursive shared values need a recursive typed representation and cycle-aware memory management, which this native class path does not implement",proof="finite nested storage layout and cycle-aware lifetime")


def validate(cell,node,integer,*,field_value=False,seen=frozenset()):
    from .native_classes import ClassUnsupported,Model
    cell=cell.root()
    if id(cell)in seen:
        raise ClassUnsupported(node,"recursive nested element storage needs cycle-aware layout/lifetime management, which is not implemented",proof="finite nested storage layout")
    if cell.tag is None or cell.tag not in Model.DATA:
        raise ClassUnsupported(node,"the class frame's field/result kind has no resolved native stored-value representation; storage for this value or escaping stream/callable has not been implemented",types=(("value",cell),),proof="resolved stored class-frame value")
    if integer=="bigint"and cell.tag=="float":
        raise ClassUnsupported(node,"native binary64 value/operation storage has not been integrated with the BigInt class path",types=(("value","float"),),proof="BigInt/f64 value representation and interoperation")
    if cell.tag=="object"and field_value:
        raise ClassUnsupported(node,"an instance-reference field needs alias-preserving object handles and lifetime/cycle management; that field representation is not implemented on this class path",types=(("field",cell),),proof="object-field identity and lifetime")
    seen=seen|{id(cell)}
    if cell.tag=="list":
        validate(cell.args[0],node,integer,seen=seen)
    elif cell.tag in {"tuple","union"}:
        for value in cell.args:validate(value,node,integer,field_value=field_value,seen=seen)


def validate_instance_graph(model):
    """Rc storage admits acyclic instance ownership, without claiming a GC."""
    from .native_classes import ClassUnsupported
    graph={}
    for name,owner in model.classes.items():
        if not owner.used:continue
        found=set();seen=set();pending=[field.cell for field in owner.fields.values()]
        while pending:
            cell=pending.pop().root()
            if id(cell)in seen:continue
            seen.add(id(cell))
            if cell.tag=="object":found.add(cell.args[0])
            else:pending.extend(value for value in cell.args if hasattr(value,"root"))
        graph[name]=found
    done=set()
    def visit(name,path):
        if name in path:
            cycle=path[path.index(name):]+(name,)
            raise ClassUnsupported(model.classes[name].node,"the class storage types permit a reference cycle ("+" -> ".join(cycle)+"); this native path has no proof that those allocations remain acyclic and no cycle-aware collector for shared instance/list handles",operation="instance/list storage graph",proof="acyclic shared instance ownership or cycle-aware memory management")
        if name in done:return
        for target in graph.get(name,()):visit(target,path+(name,))
        done.add(name)
    for name in graph:visit(name,())


def comparison(emitter,operator,left,right,node):
    """Built-in shared-container protocols; user object equality stays identity."""
    from .native_classes import ClassUnsupported,has_float_payload
    lists=isinstance(left.kind,ListType)and isinstance(right.kind,ListType)
    tuples=(isinstance(left.kind,TupleType)or isinstance(right.kind,TupleType))and not(immutable(left.kind)and immutable(right.kind))
    if not lists and not tuples:return None
    if has_float_payload(left.kind)or has_float_payload(right.kind):
        raise ClassUnsupported(node,"container comparison with floating payloads needs Python's element identity shortcuts, including repeated NaN objects; that identity representation is not implemented",types=(("left",left.kind),("right",right.kind)),proof="floating element identity during container comparison")
    if isinstance(operator,(ast.Eq,ast.NotEq)):
        if lists:
            a,b,x,y=(emitter.fresh()for _ in range(4))
            test=emitter.comparison(ast.Eq(),_Expression(f"{x}.clone()",left.kind.element),_Expression(f"{y}.clone()",right.kind.element),node)
            code=(f"{{let {a}=({left.code}).clone();let {b}=({right.code}).clone();"
                  f"{a}.borrow().len()=={b}.borrow().len()&&{a}.borrow().iter().zip({b}.borrow().iter()).all(|({x},{y})|{test})}}")
        elif isinstance(left.kind,TupleType)and isinstance(right.kind,TupleType):
            if len(left.kind.fields)!=len(right.kind.fields):code="false"
            else:
                values=[emitter.comparison(ast.Eq(),_Expression(f"({left.code}).{i}.clone()",a),_Expression(f"({right.code}).{i}.clone()",b),node)
                        for i,(a,b)in enumerate(zip(left.kind.fields,right.kind.fields))]
                code="&&".join(f"({value})"for value in values)or"true"
        else:code="false"
        return f"!({code})"if isinstance(operator,ast.NotEq)else code
    if isinstance(operator,(ast.Lt,ast.LtE,ast.Gt,ast.GtE)):
        order=ordering(emitter,left,right,node)
        variants={ast.Lt:"Less",ast.LtE:"Less|std::cmp::Ordering::Equal",ast.Gt:"Greater",ast.GtE:"Greater|std::cmp::Ordering::Equal"}
        return f"matches!({order},std::cmp::Ordering::{variants[type(operator)]})"
    return None


def ordering(emitter,left,right,node):
    """Lexicographic ordering only where all leaf operations are non-fallible."""
    from .native_classes import ClassUnsupported
    a,b=left.kind,right.kind
    numeric={"int","bool","int_bool"}
    if a in numeric and b in numeric:
        return f"({emitter.number(left)}).cmp(&({emitter.number(right)}))"
    if a==b and a in {"str","bytes"}:return f"({left.code}).cmp(&({right.code}))"
    if a==b=="none":return "std::cmp::Ordering::Equal"
    if isinstance(a,ListType)and isinstance(b,ListType):
        first,second,read_a,read_b,x,y,result,step=(emitter.fresh()for _ in range(8))
        nested=ordering(emitter,_Expression(f"{x}.clone()",a.element),_Expression(f"{y}.clone()",b.element),node)
        return (f"{{let {first}=({left.code}).clone();let {second}=({right.code}).clone();"
                f"let {read_a}={first}.borrow();let {read_b}={second}.borrow();let mut {result}=std::cmp::Ordering::Equal;"
                f"for ({x},{y})in {read_a}.iter().zip({read_b}.iter()){{let {step}={nested};"
                f"if {step}!=std::cmp::Ordering::Equal{{{result}={step};break;}}}}"
                f"if {result}==std::cmp::Ordering::Equal{{{read_a}.len().cmp(&{read_b}.len())}}else{{{result}}}}}")
    if isinstance(a,TupleType)and isinstance(b,TupleType):
        result=f"{len(a.fields)}_usize.cmp(&{len(b.fields)}_usize)"
        for i in reversed(range(min(len(a.fields),len(b.fields)))):
            step=emitter.fresh()
            nested=ordering(emitter,_Expression(f"({left.code}).{i}.clone()",a.fields[i]),_Expression(f"({right.code}).{i}.clone()",b.fields[i]),node)
            result=f"{{let {step}={nested};if {step}!=std::cmp::Ordering::Equal{{{step}}}else{{{result}}}}}"
        return result
    raise ClassUnsupported(node,"lexicographic shared-container ordering needs a non-fallible Python comparator for these leaf types; custom object ordering, mixed unorderable alternatives and floating identity/NaN ordering are not implemented here",types=(("left",a),("right",b)),proof="non-fallible built-in element ordering")
