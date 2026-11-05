"""Borrow stable typed lists once across closed, non-reentrant scalar loops.

The proof covers the entire loop, including nested loops and their exits.
Mutable regions have exactly one list binding, so aliases outside the region
cannot cause overlapping mutable borrows. Name errors remain at the original
read even when an already-bound list can be borrowed before the first iteration.
"""
import ast
from contextlib import contextmanager
from dataclasses import dataclass

from .native_types import ListType
from .references import BuiltinIdentity


SCALARS=frozenset({'int','bool','int_bool','float'})


class Proof:
    def __init__(self,emitter):
        self.emitter=emitter
        self.roots={}
        self.writes=set()
        self.mutable=False

    def scalar(self,node):
        return self.kind(node)in SCALARS

    def kind(self,node):
        from .native_classes import shape
        cell=self.emitter.model.records.get((self.emitter.plan.index,id(node)))
        return None if cell is None else shape(cell)

    def builtin(self,node):
        if not isinstance(node.func,ast.Name):return None
        identity=self.emitter.model.builtin_identity(self.emitter.plan,node.func,{})
        return identity.name if isinstance(identity,BuiltinIdentity)else None

    def owner(self,node):
        if not isinstance(node,ast.Name):return False
        emitter=self.emitter;kind=self.kind(node)
        if not isinstance(kind,ListType)or kind.element not in SCALARS:return False
        model=emitter.model;name=model.resolved_name(emitter.plan,node)
        if name in getattr(emitter,'owned_matrices',{}):return False
        if name in getattr(emitter,'owned_local_lists',{}):return False
        if name in getattr(emitter,'record_places',{}):return False
        if model.lexical.field_for(node)is not None or model.namespace.owns(emitter.plan,node):return False
        stored=model.namespace.local_kind(emitter.plan,name)
        if stored is not None and stored!=kind:return False
        if name not in emitter.plan.locals:return False
        self.roots[name]=kind
        return True

    def expression(self,node):
        if isinstance(node,ast.Constant):return type(node.value)in {int,bool,float}
        if isinstance(node,ast.Name):return self.scalar(node)
        if isinstance(node,ast.Subscript):
            return self.owner(node.value)and self.expression(node.slice)
        if isinstance(node,ast.UnaryOp):return self.scalar(node)and self.expression(node.operand)
        if isinstance(node,ast.BinOp):return self.scalar(node)and self.expression(node.left)and self.expression(node.right)
        if isinstance(node,ast.BoolOp):return self.scalar(node)and all(self.expression(value)for value in node.values)
        if isinstance(node,ast.Compare):return self.expression(node.left)and all(self.expression(value)for value in node.comparators)
        if isinstance(node,ast.IfExp):return all(self.expression(value)for value in(node.test,node.body,node.orelse))
        if isinstance(node,ast.Call)and not node.keywords:
            name=self.builtin(node)
            if name=='len':return len(node.args)==1 and self.owner(node.args[0])
            if name in {'int','bool','abs'}:return len(node.args)==1 and all(self.expression(value)for value in node.args)
            if name in {'min','max'}:return len(node.args)>=2 and all(self.expression(value)for value in node.args)
        return False

    def target(self,node):
        if isinstance(node,ast.Name):
            self.writes.add(self.emitter.model.resolved_name(self.emitter.plan,node))
            return self.scalar(node)
        if isinstance(node,ast.Subscript):
            self.mutable=True
            return self.owner(node.value)and self.expression(node.slice)
        if isinstance(node,(ast.Tuple,ast.List)):return all(self.target(value)for value in node.elts)
        return False

    def statements(self,body):return all(self.statement(node)for node in body)

    def statement(self,node):
        if isinstance(node,ast.Assign):return self.expression(node.value)and all(self.target(value)for value in node.targets)
        if isinstance(node,ast.AnnAssign):return self.target(node.target)and(node.value is None or self.expression(node.value))
        if isinstance(node,ast.AugAssign):return self.target(node.target)and self.expression(node.value)
        if isinstance(node,ast.If):return self.expression(node.test)and self.statements(node.body)and self.statements(node.orelse)
        if isinstance(node,ast.While):return self.expression(node.test)and self.statements(node.body)and self.statements(node.orelse)
        if isinstance(node,ast.For):
            source=node.iter
            return (isinstance(source,ast.Call)and self.builtin(source)=='range'and not source.keywords
                    and all(self.expression(value)for value in source.args)
                    and self.target(node.target)and self.statements(node.body)and self.statements(node.orelse))
        if isinstance(node,ast.Return):return node.value is None or self.expression(node.value)
        return isinstance(node,(ast.Pass,ast.Break,ast.Continue))


@dataclass(frozen=True)
class Region:
    name:object
    kind:object
    guard:str
    mutable:bool
    defined:bool=False

    def storage(self,mutable=False):
        if self.defined:return self.guard
        return self.guard+('.as_mut().expect("checked mutable list binding")'if mutable else'.as_ref().expect("checked list binding")')

    def checked(self,emitter,node):
        if self.defined:return '(&'+self.guard+')'
        from .native import _string
        label=emitter.model.display_name(self.name)
        message=(f"NameError: name '{label}' is not defined"if emitter.model.is_module_plan(emitter.plan)else
                 f"UnboundLocalError: cannot access local variable '{label}' where it is not associated with a value")
        return emitter.at(f'{self.guard}.as_ref().ok_or_else(||{_string(message)}.to_owned())',node)


@contextmanager
def scope(emitter,node):
    parents=emitter.list_access_regions
    proof=Proof(emitter)
    regions={};lines=[]
    # A parent proof already includes this entire loop. Do not take a second
    # lease for a potentially aliased root in an inner region.
    if (not any(parents)and proof.statement(node)and proof.roots
            and not proof.writes.intersection(proof.roots)
            and(not proof.mutable or len(proof.roots)==1)):
        for name,kind in proof.roots.items():
            guard=emitter.fresh();slot=emitter.slot(name,kind)
            borrow='borrow_mut'if proof.mutable else'borrow'
            from .native_primitive_parameter_places import argument
            direct=argument(emitter,name,kind)
            if direct is None:lines.append(f'let mut {guard}={slot}.as_ref().map(|owner|owner.{borrow}());')
            else:lines.append(f'let mut {guard}={direct}.{borrow}();')
            regions[name]=Region(name,kind,guard,proof.mutable,direct is not None)
    parents.append(regions)
    emitter.list_access_tails[id(node)]=regions
    try:yield ''.join(lines)
    finally:parents.pop()


@contextmanager
def tail_scope(emitter,node):
    emitter.list_access_regions.append(emitter.list_access_tails.pop(id(node),{}))
    try:yield
    finally:emitter.list_access_regions.pop()


def selected(emitter,node):
    if not isinstance(node,ast.Name):return None
    name=emitter.model.resolved_name(emitter.plan,node)
    for regions in reversed(emitter.list_access_regions):
        if name in regions:return regions[name]
    return None


def reference(emitter,node):
    if not isinstance(node,ast.Subscript):return None
    region=selected(emitter,node.value)
    if region is None:return None
    # Validate the owner before evaluating its index. The proof forbids index
    # callbacks and writes, but retains all original arithmetic/name failures.
    setup=f'let _={region.checked(emitter,node.value)};'
    more,index=emitter.capture(emitter.expression(node.slice))
    return setup+more,('list_region',region,index,region.kind.element)


def load(emitter,region,index,node):
    from .native import _Expression
    offset=emitter.fresh()
    checked=emitter.at(f'class_index(&({emitter.number(index)}),{region.storage()}.len())',node)
    code=f'{{let {offset}={checked};{region.storage()}[{offset}].clone()}}'
    return _Expression(code,region.kind.element)


def store(emitter,region,index,value,node):
    offset=emitter.fresh()
    checked=emitter.at(f'class_index(&({emitter.number(index)}),{region.storage()}.len()).map_err(|_|"IndexError: list assignment index out of range".to_owned())',node)
    return f'{{let {offset}={checked};{region.storage(True)}[{offset}]={emitter.coerce(value,region.kind.element,node)};}}'


def augmented(emitter,node,setup,reference,old_kind):
    if reference[0]!='list_region':return None
    from .native import _Expression
    _,region,index,stored=reference
    if stored!=old_kind or emitter.kind(node.target)!=stored:return None
    offset,previous=emitter.fresh(),emitter.fresh()
    checked=emitter.at(f'class_index(&({emitter.number(index)}),{region.storage()}.len())',node.target)
    before=f'let {offset}={checked};let {previous}={region.storage()}[{offset}].clone();'
    more,right=emitter.capture(emitter.expression(node.value))
    result=emitter.binary(node.op,_Expression(previous,stored),right,node,stored)
    after,result=emitter.capture(result)
    # This entire region excludes list resizing and rebinding, including the
    # RHS. The checked offset used by the original get remains valid for set.
    commit=f'{region.storage(True)}[{offset}]={emitter.coerce(result,stored,node.target)};'
    return '{'+setup+before+more+after+commit+'}'


def read(emitter,node):
    from .native import _Expression
    if isinstance(node,ast.Subscript):
        captured=reference(emitter,node)
        if captured is not None:
            setup,(_,region,index,_)=captured
            value=load(emitter,region,index,node)
            return _Expression('{'+setup+value.code+'}',value.kind)
    if isinstance(node,ast.Call)and len(node.args)==1 and not node.keywords:
        region=selected(emitter,node.args[0])
        if region is not None and Proof(emitter).builtin(node)=='len':
            code=f'class_from_usize(({region.checked(emitter,node.args[0])}).len())'
            return _Expression(code,'int')
    return None
