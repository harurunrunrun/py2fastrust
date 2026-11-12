"""Identity-preserving closed TypeVar construction at unique module sites.

Metadata stays in the existing typed carrier. Factories run only after native
argument evaluation; their finite validation result is obtained from Python's
canonical constructor. Repeated or observable metadata creation is explicit.
"""
import ast
import itertools
import typing
import warnings
from dataclasses import dataclass

from .native_typing_metadata import Construction,registry,semantic_key


@dataclass
class TypeVarCall:
    result:object
    record:object
    arguments:object


def unique_site(model,plan,node):
    metadata=registry(model)
    if not model.is_module_plan(plan):
        metadata.fail(node,'TypeVar factories in functions require fresh runtime type-variable identities; only single-execution module sites are implemented')
    current=node
    repeated=(ast.For,ast.AsyncFor,ast.While,ast.comprehension,ast.ListComp,ast.SetComp,
              ast.DictComp,ast.GeneratorExp,ast.Lambda,ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)
    while current is not plan.node:
        current=model.unit.parents.get(id(current))
        if current is None:
            metadata.fail(node,'TypeVar site is not part of an original module initializer')
        if isinstance(current,repeated):
            metadata.fail(node,'TypeVar factories inside repeated execution regions require fresh runtime type-variable identities; move-free single-execution module construction is the implemented protocol')


def native_import_only(linker,bindings):
    """Each module actually initialized by this import has a native factory."""
    for binding in bindings:
        for name in (binding.module,*binding.children):
            parts=name.split('.')
            for length in range(1,len(parts)+1):
                module=linker.modules.get('.'.join(parts[:length]))
                if (module is None or not module.native_adapter
                        or module.source_unit is not None or module.initializer is not None):return False
    return bool(bindings)


def closed_loader(model,node):
    """A source module initializer cannot be reopened through admitted APIs."""
    metadata=registry(model)
    if getattr(metadata,'typevar_loader_checked',False):return
    from .native_classes import shape
    from .native_module_calls import BuiltinRef
    from .references import BuiltinIdentity
    from .native_single_execution_metadata import _identities,_module_name
    linker=model.module_linker
    nodes={id(value):value for value in model.iter_nodes()}
    plans={plan.index:plan for plan in model.plans if plan.reachable}
    # A caught failed import can run its initializer again, without touching
    # sys.modules explicitly. Source initializers require original,
    # unconditional module import statements. Native factories with no source
    # initializer cannot reopen a failed Python module generation.
    for (caller,node_id),bindings in linker.imports.items():
        if caller not in plans:continue
        plan=plans[caller];statement=nodes.get(node_id)
        if not isinstance(statement,(ast.Import,ast.ImportFrom)):
            metadata.fail(node,'TypeVar module uniqueness requires original fixed-name import statements')
        if native_import_only(linker,bindings):continue
        original=model.unit.original_unit(statement)
        if (not model.is_module_plan(plan)or plan.node is not original.tree
                or not any(child is statement for child in original.tree.body)):
            metadata.fail(node,'TypeVar module uniqueness is not proved for imports inside functions or control flow, where failed module initialization can be retried; fresh runtime type-variable identities are not implemented')
    runtime={'__import__','compile','eval','exec'}
    identities=set(model.callable_cells.builtin_used)|set(model.callable_cells.member_used)
    for cell in model.records.values():identities.update(_identities(shape(cell)))
    for identity in identities:
        if (isinstance(identity,BuiltinIdentity)and identity.name in runtime
                or isinstance(identity,BuiltinRef)and(identity.module.startswith(('importlib','_frozen_importlib'))
                    or identity.module in {'_imp','imp'}
                    or identity.module=='builtins'and identity.name in runtime)):
            metadata.fail(node,'TypeVar module uniqueness is not proved with a retained runtime importer/compiler; fresh runtime type-variable identities are not implemented')
    for key in model.records:
        caller,node_id=key[:2]
        value=nodes.get(node_id)
        if caller not in plans or not isinstance(value,ast.Attribute):continue
        name=_module_name(model,plans[caller],value.value)
        if (name=='sys'and value.attr in {'modules','meta_path','path','path_hooks','path_importer_cache'}
                or name is not None and value.attr in {'__loader__','__spec__'}):
            metadata.fail(node,'TypeVar module uniqueness is not proved while the import cache or loader is observed; fresh runtime type-variable identities are not implemented')
    metadata.typevar_loader_checked=True


def outcomes(metadata,plan,arguments,positional,keywords):
    from .native_classes import shape
    cells=(*positional,*(value for _,value in keywords))
    choices=[metadata.choices(shape(value),argument.expression,plan)
             for value,argument in zip(cells,arguments.evaluation_order)]
    return itertools.product(*choices)


def key_for(values,npos,keywords):
    return tuple(map(semantic_key,values[:npos])),tuple((name,semantic_key(value))for(name,_),value in zip(keywords,values[npos:]))


def analyze(model,plan,node,arguments,positional,keywords,*,factory):
    metadata=registry(model)
    if (not isinstance(node,ast.Call)or any(isinstance(value,ast.Starred)for value in node.args)
            or any(value.arg is None for value in node.keywords)
            or len(arguments.positional)!=len(node.args)or len(arguments.keywords)!=len(node.keywords)
            or len(positional)!=len(arguments.positional)or len(keywords)!=len(arguments.keywords)
            or any(value.expression is not source for value,source in zip(arguments.positional,node.args))
            or any(value.expression is not source.value or value.name!=source.arg
                   for value,source in zip(arguments.keywords,node.keywords))):
        metadata.fail(node,'TypeVar factories through expanded or implicit callback arguments need their ordered fresh-construction protocol; only original explicit calls are implemented')
    unique_site(model,plan,node)
    if not hasattr(metadata,'typevar_sites'):metadata.typevar_sites={}
    key=plan.index,id(node)
    record=metadata.typevar_sites.get(key)
    if record is None:
        record=Construction(len(metadata.records),node)
        record.factories={}
        metadata.records.append(record)
        metadata.typevar_sites[key]=record
    for selected in outcomes(metadata,plan,arguments,positional,keywords):
        values=tuple(value for value,_ in selected)
        key=key_for(values,len(positional),keywords)
        if key in record.factories:continue
        try:
            with warnings.catch_warnings(record=True)as emitted:
                warnings.simplefilter('always')
                value=typing.TypeVar(*values[:len(positional)],**dict((name,value)for(name,_),value in zip(keywords,values[len(positional):])))
            if emitted:metadata.fail(node,'TypeVar construction emits warnings needing the runtime warning/filter protocol')
        except (TypeError,ValueError,SyntaxError)as error:
            record.errors[key]=type(error).__name__+': '+str(error)
            record.factories[key]=None
        else:
            record.factories[key]=record.add(value)
    return TypeVarCall(factory(record.kind),record,arguments)


def emit(emitter,node,call,positional,keywords):
    from .native import _string
    from .native_classes import Expression
    metadata=registry(emitter.model)
    closed_loader(emitter.model,node)
    record=call.record
    choices=[metadata.choices(value.kind,argument.expression,emitter.plan)
             for value,argument in zip((*positional,*(value for _,value in keywords)),call.arguments.evaluation_order)]
    captured=(*positional,*(value for _,value in keywords))
    branches=[]
    for selected in itertools.product(*choices):
        values=tuple(value for value,_ in selected)
        key=key_for(values,len(positional),keywords)
        if key in record.errors:
            code=emitter.at('Err::<NativeTypingSymbol,String>('+_string(record.errors[key])+'.to_owned())',node)
        else:
            code='NativeTypingSymbol{case:'+str(record.factories[key])+'}'
        condition='&&'.join('('+test(value.code)+')'for(_,test),value in zip(selected,captured))or'true'
        branches.append('if '+condition+'{'+code+'}else ')
    if not branches:metadata.fail(node,'TypeVar operands have no finite solved constructor cases')
    return Expression('{'+''.join(branches)+'{unreachable!("closed TypeVar operands")}}',record.kind)
