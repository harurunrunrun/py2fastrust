"""One Vec lease for scalar-instance loops with closed source callees.

Instance fields keep their normal shared Cell semantics. A source callee must
have no access at all to the leased list's element family, including through
globals, callbacks, containers or captured bindings. Unknown effects decline.
"""
import ast

from .native_list_access_regions import Proof as PrimitiveProof
from .native_types import ListType


class Proof(PrimitiveProof):
    def __init__(self,emitter):
        super().__init__(emitter)
        self.model=emitter.model
        self.plan=emitter.plan
        self.family=None
        self.callees={}
        self.active=set()

    def instance(self,kind):
        from .native_classes import InstanceType
        from .native_scalar_constructor_data import selected
        return isinstance(kind,InstanceType)and selected(self.model,self.model.classes[kind.name])

    def scalar(self,node):
        return super().scalar(node)or self.instance(self.kind(node))

    def owner(self,node):
        if not isinstance(node,ast.Name):return False
        kind=self.kind(node)
        if not isinstance(kind,ListType)or not self.instance(kind.element):return False
        if self.family is not None and kind.element!=self.family:return False
        name=self.model.resolved_name(self.plan,node)
        if (name not in self.plan.locals or name in self.emitter.owned_local_lists
                or name in self.emitter.record_places or name in self.emitter.owned_matrices
                or self.model.lexical.field_for(node)is not None
                or self.model.namespace.owns(self.plan,node)):return False
        stored=self.model.namespace.local_kind(self.plan,name)
        if stored is not None and stored!=kind:return False
        self.family=kind.element
        self.roots[name]=kind
        return True

    def source_targets(self,plan,node):
        registry=self.model.scalar_data_locals
        if isinstance(node,ast.Call):
            owner=next((owner for owner in self.model.classes.values()
                        if owner.index in self.model.scalar_constructor_data.owners
                        and self.model.value_classes.constructor(plan,node,owner)),None)
            return (owner.methods['__init__'],)if owner is not None else registry.targets(plan,node)
        return registry.phases(plan,node)

    def callee(self,plan):
        key=plan.index,self.family
        if key in self.callees:return self.callees[key]
        if key in self.active:return False
        self.active.add(key)
        try:
            from .native_class_calls import synchronous
            valid=synchronous(self.model,plan)and isinstance(plan.node,ast.FunctionDef)
            if valid:
                valid=all(self.callee_node(plan,node)for node in plan.node.body)
            self.callees[key]=valid
            return valid
        finally:self.active.remove(key)

    def callee_node(self,plan,node):
        from .native_source_native_effects import _identity,sealed_builtin,comparison_closed
        from .native_list_positions import closed
        from .references import BuiltinIdentity
        values=self.model.value_classes
        kind=values.kind(plan,node)
        owner=self.model.classes[self.family.name]
        if values.contains(kind,owner):
            # Plain instance loads/fields use separate allocations from Vec.
            # Any container or callable containing them could alias the lease.
            if not self.instance(kind):return False
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda,
                            ast.GeneratorExp,ast.ListComp,ast.SetComp,ast.DictComp,
                            ast.NamedExpr,ast.Yield,ast.YieldFrom,ast.Await,ast.With,
                            ast.Try,ast.TryStar,ast.Delete,ast.For,ast.While,ast.AsyncFor)):return False
        if isinstance(node,(ast.If,ast.IfExp,ast.BoolOp)):
            conditions=node.values[:-1]if isinstance(node,ast.BoolOp)else[node.test]
            if not all(sealed_builtin(self.model,BuiltinIdentity('bool'),[values.kind(plan,value)])for value in conditions):return False
        if isinstance(node,ast.If):
            if not self.callee_node(plan,node.test):return False
            mask=getattr(self.model,'type_guard_branches',{}).get((plan.index,id(node.test)))
            bodies=(node.body if mask[0]else node.orelse,)if mask is not None and not all(mask)else(node.body,node.orelse)
            return all(self.callee_node(plan,child)for body in bodies for child in body)
        if isinstance(node,ast.Attribute):
            receiver=values.kind(plan,node.value)
            from .native_classes import InstanceType
            if isinstance(receiver,InstanceType):
                actual=self.model.classes[receiver.name]
                if not self.instance(receiver):return False
                if self.model.resolved_name(plan,node)not in actual.fields:
                    parent=values.parents.get(id(node))
                    if not isinstance(parent,ast.Call)or parent.func is not node or not self.source_targets(plan,parent):return False
        if isinstance(node,ast.Subscript):
            from .native_types import TupleType,TupleSequenceType
            if (not isinstance(values.kind(plan,node.value),(ListType,TupleType,TupleSequenceType))
                    or values.kind(plan,node.slice)not in {'int','bool','int_bool'}):return False
        if isinstance(node,ast.Call):
            targets=self.source_targets(plan,node)
            if targets:
                if not all(self.callee(target)for target in targets):return False
            else:
                identity=_identity(values,plan,node.func)
                if not sealed_builtin(self.model,identity,[values.kind(plan,arg)for arg in node.args]+[values.kind(plan,arg.value)for arg in node.keywords]):return False
        if isinstance(node,(ast.BinOp,ast.UnaryOp,ast.AugAssign)):
            operands=([node.left,node.right]if isinstance(node,ast.BinOp)else
                      [node.target,node.value]if isinstance(node,ast.AugAssign)else[node.operand])
            if not all(closed(values.kind(plan,value))for value in operands):
                targets=self.source_targets(plan,node)
                if not targets or not all(self.callee(target)for target in targets):return False
        if isinstance(node,ast.Compare):
            operands=[node.left,*node.comparators]
            if not all(comparison_closed(values.kind(plan,left),op,values.kind(plan,right))
                       for left,op,right in zip(operands,node.ops,operands[1:])):return False
        return all(self.callee_node(plan,child)for child in ast.iter_child_nodes(node))

    def expression(self,node):
        from .native_source_native_effects import sealed_builtin,comparison_closed,_identity
        from .references import BuiltinIdentity
        if isinstance(node,(ast.IfExp,ast.BoolOp)):
            conditions=node.values[:-1]if isinstance(node,ast.BoolOp)else[node.test]
            if not all(sealed_builtin(self.model,BuiltinIdentity('bool'),[self.kind(value)])for value in conditions):return False
        if isinstance(node,ast.UnaryOp)and self.instance(self.kind(node.operand)):return False
        if isinstance(node,ast.Subscript)and self.kind(node.slice)not in {'int','bool','int_bool'}:return False
        if isinstance(node,ast.Compare):
            operands=[node.left,*node.comparators]
            if not all(comparison_closed(self.kind(left),op,self.kind(right))
                       for left,op,right in zip(operands,node.ops,operands[1:])):return False
        if isinstance(node,ast.Call):
            if super().expression(node):
                identity=_identity(self.model.value_classes,self.plan,node.func)
                return sealed_builtin(self.model,identity,[self.kind(arg)for arg in node.args])
            targets=self.source_targets(self.plan,node)
            arguments=[*node.args,*(arg.value for arg in node.keywords)]
            if isinstance(node.func,ast.Attribute)and self.instance(self.kind(node.func.value)):
                arguments.append(node.func.value)
            return bool(targets)and all(self.expression(value)for value in arguments)and all(self.callee(target)for target in targets)
        if isinstance(node,ast.Attribute)and self.instance(self.kind(node.value)):
            owner=self.model.classes[self.kind(node.value).name]
            return (isinstance(node.ctx,ast.Load)and self.model.resolved_name(self.plan,node)in owner.fields
                    and self.expression(node.value))
        if isinstance(node,ast.BinOp)and not super().scalar(node):
            targets=self.source_targets(self.plan,node)
            return (bool(targets)and self.expression(node.left)and self.expression(node.right)
                    and all(self.callee(target)for target in targets))
        return super().expression(node)

    def target(self,node):
        if isinstance(node,ast.Subscript)and self.kind(node.slice)not in {'int','bool','int_bool'}:return False
        return super().target(node)

    def statement(self,node):
        if isinstance(node,ast.For)and isinstance(node.iter,ast.Call):
            if any(self.kind(arg)not in {'int','bool','int_bool'}for arg in node.iter.args):return False
        if isinstance(node,(ast.If,ast.While)):
            from .native_source_native_effects import sealed_builtin
            from .references import BuiltinIdentity
            if not sealed_builtin(self.model,BuiltinIdentity('bool'),[self.kind(node.test)]):return False
        if isinstance(node,ast.AugAssign)and self.instance(self.kind(node.target)):
            targets=self.source_targets(self.plan,node)
            return (bool(targets)and self.target(node.target)and self.expression(node.value)
                    and all(self.callee(target)for target in targets))
        return super().statement(node)


def select(emitter,node):
    proof=Proof(emitter)
    # Establish the exact element family before inspecting any source callees.
    for child in ast.walk(node):
        if isinstance(child,ast.Subscript):proof.owner(child.value)
    return proof if proof.family is not None and proof.statement(node)else None
