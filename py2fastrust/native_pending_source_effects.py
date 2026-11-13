"""Fair analysis of real source effects before rejecting method/data demands.

This registry schedules compiler bodies only. It neither executes submitted
code nor supplies an object, field type or runtime value.
"""
import ast
from dataclasses import dataclass


@dataclass
class Demand:
    consumer:int
    producers:frozenset
    owners:frozenset
    signature:object


def registry(model):
    result=getattr(model,'pending_source_effects',None)
    if result is None:result=model.pending_source_effects=Registry(model)
    return result


class Registry:
    def __init__(self,model):
        self.model=model;self.sweep=0;self.completed=set();self.waiting={};self.released={}
        self.graph_key=None;self.children={};self.parents={};self.reads={};self.attributes={}
        self.nodes={model.unit.ordinal(node):node for node in model.iter_nodes()}
        self.bindings={binding.node:binding for binding in model.iter_bindings()}
        self.stats=dict(waits=0,releases=0,invalidations=0,backdependencies=0,
                        signature_builds=0,namespace_cell_reads=0,lexical_cell_reads=0,
                        class_field_reads=0,class_member_reads=0,semantic_kind_reads=0,
                        module_attribute_reads=0,full_namespace_snapshots=0)

    def kind_key(self,kind,seen=frozenset()):
        """Opaque family identities also retain their changing payload schema."""
        from .native_classes import shape
        from .native_types import ListType,TupleType,TupleSequenceType,DequeType,NullableType,UnionType,MaybeType
        from .native_key_types import SetType,DictType
        self.stats['semantic_kind_reads']+=1
        if kind in seen:return ('recursive_kind',kind)
        seen=seen|{kind}
        children=tuple(getattr(kind,'_native_owned_kinds',()))
        if isinstance(kind,(ListType,TupleSequenceType,DequeType)):children+= (kind.element,)
        elif isinstance(kind,TupleType):children+=kind.fields
        elif isinstance(kind,SetType):children+=(kind.key,)
        elif isinstance(kind,DictType):children+=(kind.key,kind.value)
        elif isinstance(kind,(NullableType,MaybeType)):children+=(kind.value,)
        elif isinstance(kind,UnionType):children+=kind.alternatives
        if getattr(kind,'_native_class_iterator',False):children+=(shape(kind.record.element),)
        return kind,tuple(self.kind_key(child,seen)for child in children)

    def graph(self):
        key=tuple((index,tuple(sorted(children)))for index,children in sorted(self.model.call_edges.items()))
        if key!=self.graph_key:
            self.graph_key=key
            self.children={index:frozenset(children)for index,children in key}
            self.parents={}
            for parent,children in self.children.items():
                for child in children:self.parents.setdefault(child,set()).add(parent)
        return key

    @staticmethod
    def closure(roots,edges):
        result=set();pending=list(roots)
        while pending:
            node=pending.pop()
            if node in result:continue
            result.add(node);pending.extend(edges.get(node,()))
        return result

    def producers(self,consumer,owners):
        self.graph()
        roots=set(self.children.get(consumer.index,()))
        for name in owners:
            initializer=self.model.classes[name].methods.get('__init__')
            if initializer is not None and initializer.reachable:roots.add(initializer.index)
        reached=self.closure(roots,self.children)
        ancestors=self.closure((consumer.index,),self.parents)
        self.stats['backdependencies']+=len(reached&ancestors)
        return frozenset(index for index in reached-ancestors if self.model.plans[index].reachable)

    def referenced_cells(self,plan):
        """Inspect official free/module reads, without a global namespace walk."""
        if plan.index not in self.reads:
            scope=self.model.lexical.scope(plan);rows=[]
            for ordinal,binding in self.bindings.items():
                if binding.role!='load' or self.model.lexical.execution_scope(binding.scope)!=scope:continue
                node=self.nodes.get(ordinal)
                if isinstance(node,ast.Name):rows.append(node)
            self.reads[plan.index]=tuple(rows)
            self.attributes[plan.index]=tuple(node for ordinal,node in self.nodes.items()
                if isinstance(node,ast.Attribute)and isinstance(node.ctx,ast.Load)
                and self.model.lexical.execution_scope(self.model.unit.nodes[ordinal].scope)==scope)
        from .native_classes import shape
        result=[]
        for node in self.reads[plan.index]:
            captured=self.model.lexical.field_for(node)
            if captured is not None:
                self.stats['lexical_cell_reads']+=1
                result.append(('lexical',captured[0].scope,captured[1],self.kind_key(shape(captured[2]))))
            binding=self.bindings[self.model.unit.ordinal(node)]
            if not self.model.module_owner(binding.owner):continue
            name=self.model.resolved_name(plan,node)
            cell=self.model.namespace.cells.get(name,self.model.global_symbols.get(name))
            self.stats['namespace_cell_reads']+=1
            result.append(('module',name,self.kind_key(None if cell is None else shape(cell))))
        linker=getattr(self.model,'module_linker',None)
        if linker is not None:
            from .native_module_linking import ModuleType
            from .native_types import alternatives
            for node in self.attributes[plan.index]:
                receiver=self.model.records.get((plan.index,id(node.value)))
                kind=None if receiver is None else shape(receiver)
                for choice in alternatives(kind):
                    if not isinstance(choice,ModuleType):continue
                    module=linker.by_number[choice.number]
                    name=self.model.unit.global_name(module.name,node.attr)
                    cell=self.model.namespace.cells.get(name)
                    self.stats['module_attribute_reads']+=1
                    result.append(('module_attribute',name,self.kind_key(None if cell is None else shape(cell))))
        return tuple(result)

    def signature(self,producers,owners):
        from .native_classes import shape
        self.stats['signature_builds']+=1
        frames=[]
        for index in sorted(producers):
            plan=self.model.plans[index]
            frames.append((index,plan.reachable,
                None if plan.global_names is None else frozenset(plan.global_names),
                None if plan.visible_definitions is None else frozenset(plan.visible_definitions),
                tuple((name,self.kind_key(shape(value)))for name,value in plan.arguments.items()),self.kind_key(shape(plan.result)),
                tuple(sorted(self.children.get(index,()))),self.referenced_cells(plan)))
        fields=[]
        # Instance argument kinds name classes; their mutable field layouts are
        # separate inputs. Classes are a bounded schema inventory, not all
        # source expression cells or runtime instances.
        for name,owner in self.model.classes.items():
            for key,field in owner.fields.items():
                self.stats['class_field_reads']+=1
                fields.append((name,key,field.written,self.kind_key(shape(field.cell))))
        members=[]
        namespace=getattr(self.model,'class_namespaces',None)
        if namespace is not None:
            for key,member in namespace.members.items():
                cell=self.model.namespace.cells.get(member.key)
                self.stats['class_member_reads']+=1
                members.append((key,member.descriptor,self.kind_key(None if cell is None else shape(cell))))
        return frozenset(producers),frozenset(owners),tuple(frames),tuple(fields),tuple(members)

    def wait(self,plan,node,owners):
        producers=self.producers(plan,owners)
        if not producers:return
        key=plan.index,id(node)
        signature=self.signature(producers,owners)
        if self.released.get(key)==signature:return
        if key in self.released:
            self.stats['invalidations']+=1;self.released.pop(key)
        self.waiting[key]=Demand(plan.index,producers,frozenset(owners),signature)
        self.stats['waits']+=1
        from .native_guard_flow import AnalysisPending
        raise AnalysisPending()

    def begin_sweep(self):
        self.sweep+=1;self.completed.clear()

    def complete(self,plan):
        self.completed.add(plan.index)

    def release_stable(self):
        self.graph();consumers=set()
        for key,demand in tuple(self.waiting.items()):
            plan=self.model.plans[demand.consumer]
            producers=self.producers(plan,demand.owners)
            if not producers.issubset(self.completed):continue
            signature=self.signature(producers,demand.owners)
            self.released[key]=signature;self.waiting.pop(key)
            self.stats['releases']+=1;consumers.add(demand.consumer)
        return consumers

    def snapshot(self):
        return (tuple(sorted((key,demand.producers,demand.owners,demand.signature)
                             for key,demand in self.waiting.items())),
                tuple(sorted(self.released.items())))


def wait_for_indexed_receiver(model,plan,node,receiver):
    if model.final or model.unit is None:return
    from .native_classes import shape,domain
    from .native_types import alternatives
    from .native_bound_methods import BoundMethodTarget
    kind=shape(receiver);choices=alternatives(kind)
    if any(domain(choice)=='list'for choice in choices):return
    owners=set()
    for choice in choices:
        for target in getattr(choice,'methods',()):
            if not isinstance(target,BoundMethodTarget):continue
            if hasattr(target,'class_definition')and not getattr(target,'_native_instance_function_target',False):continue
            if target.owner in model.classes:owners.add(target.owner)
    if owners:registry(model).wait(plan,node,owners)


def begin_sweep(model):
    value=getattr(model,'pending_source_effects',None)
    if value is not None:value.begin_sweep()


def complete(model,plan):
    value=getattr(model,'pending_source_effects',None)
    if value is not None:value.complete(plan)


def release_stable(model):
    value=getattr(model,'pending_source_effects',None)
    return set()if value is None else value.release_stable()


def snapshot(model):
    value=getattr(model,'pending_source_effects',None)
    return ()if value is None else value.snapshot()
