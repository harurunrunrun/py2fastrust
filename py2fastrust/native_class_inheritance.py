"""Single inheritance between module-level source classes (Objects/typeobject.c, CPython 3.14).

``class B(A)`` with one base names a class defined earlier in the same module
whose name is never rebound. The base is then statically known, so the MRO is
the chain ``B, A, ..., object`` and attribute lookup on ``B`` that misses ``B``'s
own namespace continues in ``A``. An inherited method is ``A``'s one function
object: calling it through a ``B`` receiver adds ``B`` to that method's
receiver type, as ``A.f(b)`` would. Inherited class attributes are the base
namespace slots themselves, so reads through the subclass observe base writes.

Special data names (``__qualname__``, ``__doc__``, ...) are per class and are
not inherited. Subclass-dependent protocols that are not implemented keep their
positioned diagnostics: ``__slots__`` in the hierarchy, class-attribute writes
through a subclass, and instance checks against instances of subclasses.
"""
import ast


def _rebound(model, unit, key, definition):
    for node in ast.walk(unit.tree):
        if node is definition:continue
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load) or isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.alias, ast.arg)):
            if model.unit.resolved_names.get(id(node)) == key:return True
    return False


def static_base(model, unit, node):
    """The ClassPlan named by a single statically known base, else None (NamedTuple path)."""
    from .native_classes import ClassUnsupported
    if len(node.bases) != 1 or node.keywords or not isinstance(node.bases[0], ast.Name):return None
    key = model.unit.resolved_names.get(id(node.bases[0]))
    base = model.classes.get(key)
    if base is None or not isinstance(base.node, ast.ClassDef) or base.node not in unit.tree.body:return None
    if base.node.bases and base.base is None:return None
    if _rebound(model, unit, key, base.node):
        raise ClassUnsupported(node.bases[0], 'this base class name is rebound, so the class object it names at definition time is not statically known; dynamic base resolution is not implemented',
                               proof='statically known base class')
    for owner in (base, *_ancestors(base)):
        if any(isinstance(item, (ast.Assign, ast.AnnAssign)) and any(isinstance(target, ast.Name) and target.id == '__slots__'
               for target in (item.targets if isinstance(item, ast.Assign) else [item.target])) for item in owner.node.body):
            raise ClassUnsupported(node.bases[0], 'inheriting from a class with __slots__ needs slot-descriptor layout inheritance; that layout is not implemented',
                                   proof='inherited __slots__ layout')
    return base


def mro_indices(owner):
    """Class indices of the linear MRO of a single-inheritance source class."""
    return {owner.index, *(ancestor.index for ancestor in _ancestors(owner))}


def _ancestors(owner):
    owner = getattr(owner, 'base', None)
    while owner is not None:
        yield owner
        owner = getattr(owner, 'base', None)


def inherited_member(namespaces, owner, name):
    """The base member a subclass lookup of ``name`` resolves to, or None for an own member.

    A subclass namespace is fixed by its class body (writes through the subclass
    are rejected), so every other name is the base's slot itself. Special data
    names belong to each class; special methods are inherited.
    """
    base = getattr(owner, 'base', None)
    if base is None or name in getattr(namespaces, 'own_names', {}).get(owner.index, ()):return None
    member = namespaces.member(base, name)
    if namespaces.special_name(name) and member.plan is None:return None
    return member


def defined_in_chain(namespaces, owner, name):
    return any((ancestor.index, name) in namespaces.members or name in namespaces.own_names.get(ancestor.index, ())
               for ancestor in _ancestors(owner))


def own_write_guard(member, definition, node):
    from .native_classes import ClassUnsupported
    if member.owner.index != definition:
        raise ClassUnsupported(node, 'writing or deleting an inherited class attribute through a subclass creates or removes a subclass slot that shadows the base; versioned subclass namespace slots are not implemented',
                               proof='subclass class-attribute shadowing')


def prepare_base(model, plan, node, environment):
    """Evaluate the base expression of an inheriting class definition; False when not inheriting."""
    from .native_classes import ClassUnsupported, shape
    from .native_module_linking import ClassReferenceType
    owner = model.classes[model.definition_name(node)]
    if owner.base is None:return False
    kind = shape(model.expression(plan, node.bases[0], environment))
    if kind is None and not model.final:
        from .native_guard_flow import AnalysisPending
        raise AnalysisPending()
    if kind != ClassReferenceType(owner.base.index):
        raise ClassUnsupported(node.bases[0], 'the base expression does not evaluate to the statically proved base class', types=(('base', kind),),
                               proof='statically known base class')
    return True


def emit_base(emitter, node):
    owner = emitter.model.classes[emitter.model.definition_name(node)]
    if owner.base is None:return ''
    return 'let _=' + emitter.expression(node.bases[0]).code + ';'


def analyze_union_instance_attribute(namespaces, plan, node, receiver_kind):
    """A class data attribute read through a union of source instances (``o.kind`` for ``A | B``).

    Each alternative reads its own instance dictionary first and then its class
    namespace (an inherited slot is the base's). Methods and descriptors keep
    their existing paths.
    """
    from .native_classes import Cell, InstanceType
    from .native_types import alternatives
    kinds = alternatives(receiver_kind)
    if len(kinds) < 2 or not all(isinstance(kind, InstanceType) for kind in kinds):return None
    name = namespaces.model.resolved_name(plan, node)
    members, written, owners = [], [], []
    result = Cell()
    for kind in kinds:
        owner = namespaces.model.classes[kind.name]
        member = namespaces.lookup(owner, name)
        if member is None or member.plan is not None:return None
        namespaces.check_metadata(member, node)
        namespaces.model.namespace.contribute(result, namespaces.field(member, node), node, force=True)
        field = owner.fields.get(name)
        written.append(field is not None and field.written)
        if written[-1]:namespaces.model.namespace.contribute(result, field.cell, node, force=True)
        members.append(member)
        owners.append(owner.index)
    site = (plan.index, id(node))
    namespaces.attribute_reads[site] = tuple(members)
    namespaces.instance_reads[site] = tuple(written)
    namespaces.read_owners[site] = tuple(owners)
    return namespaces.model.remember(plan, node, result)


def _super_site(model, plan, node):
    """(defining class, receiver parameter) for ``super().name(...)`` in a plain method, else None."""
    from .native_classes import ClassUnsupported
    function = node.func
    if not (isinstance(function, ast.Attribute) and isinstance(function.value, ast.Call)
            and isinstance(function.value.func, ast.Name) and function.value.func.id == 'super'):return None
    if model.resolved_name(plan, function.value.func) != 'super':return None
    call = function.value
    owner = plan.owner
    registry = getattr(model, 'class_namespaces', None)
    if (call.args or call.keywords or owner is None or registry is None or plan.class_body is not None
            or not isinstance(plan.node, ast.FunctionDef) or plan.node not in owner.node.body or not plan.parameters
            or plan.node.args.posonlyargs + plan.node.args.args == []):
        raise ClassUnsupported(call, 'super() outside a plain method body needs the __class__ cell and first-argument lookup of its frame; zero-argument super() is implemented in methods of single-inheritance source classes',
                               proof='zero-argument super() frame lookup')
    if registry.member(owner, model.unit.name_for(plan.node)).descriptor != 'function':
        raise ClassUnsupported(call, 'super() in a static or class method needs descriptor-specific super binding; plain methods are implemented', proof='zero-argument super() frame lookup')
    receiver = (plan.node.args.posonlyargs + plan.node.args.args)[0]
    name = model.resolved_name(plan, receiver)
    scope = model.unit.scope_for(plan.node).ordinal
    if any(binding.owner == scope and binding.name == receiver.arg and binding.role not in {'load', 'parameter'} for binding in model.unit.bindings):
        raise ClassUnsupported(call, 'super() reads the current value of the first argument; rebinding that argument is not implemented', proof='zero-argument super() frame lookup')
    if any(binding.owner == scope and binding.name == receiver.arg and binding.scope != scope for binding in model.unit.bindings):
        raise ClassUnsupported(call, 'super() with a first argument that nested scopes capture needs reading it through its cell; that receiver capture is not implemented', proof='zero-argument super() frame lookup')
    if node.keywords or any(isinstance(item, ast.Starred) for item in node.args):
        raise ClassUnsupported(node, 'super() method calls with keyword or unpacked arguments are not implemented; positional arguments are', proof='super() call binding')
    return owner, receiver, name


def analyze_super_call(model, plan, node, environment):
    """``super().name(args)`` binds ``name`` from the next class in the MRO to the receiver."""
    from .native_classes import Cell, ClassUnsupported
    if not isinstance(node, ast.Call):return None
    site = _super_site(model, plan, node)
    if site is None:return None
    owner, receiver, name = site
    attribute = model.resolved_name(plan, node.func)
    records = model.__dict__.setdefault('super_calls', {})
    if owner.base is None:
        # object is the only remaining class; object.__init__() takes no arguments.
        if attribute != '__init__' or node.args:
            raise ClassUnsupported(node, 'this object method through super() is not implemented; super().__init__() with no arguments is', proof='object methods through super()')
        records[(plan.index, id(node))] = None
        return model.cell(plan, node, 'none')
    member = model.class_namespaces.lookup(owner.base, attribute)
    if member is None or member.plan is None or member.descriptor != 'function' or getattr(member, 'function_slot_writes', False):
        raise ClassUnsupported(node, 'super() attribute lookup found no plain base-class method; data attributes, descriptors and object methods through super() are not implemented',
                               proof='super() method binding')
    value = environment.get(name)
    if value is None:
        if not model.final:
            from .native_guard_flow import AnalysisPending
            raise AnalysisPending()
        raise ClassUnsupported(node, 'the super() receiver is not bound here', proof='zero-argument super() frame lookup')
    arguments = [model.expression(plan, item, environment) for item in node.args]
    records[(plan.index, id(node))] = (member.plan, receiver)
    return model.bind_call(plan, node, member.plan, [value] + arguments, [], environment)


def _receiver(emitter, node, receiver):
    """The current value of the receiver parameter, wherever this frame keeps it."""
    from .native_classes import Expression
    from .native import _string
    model, plan = emitter.model, emitter.plan
    name = model.resolved_name(plan, receiver)
    from .native_classes import shape
    kind = shape(plan.arguments[name])
    from .native_scalar_data_parameters import parameter
    entry = parameter(model, plan, name)
    if entry is not None:return Expression('class_argument_' + str(entry[0]) + '.as_ref()', kind)
    from .native_primitive_parameter_places import lookup
    direct = lookup(emitter, name)
    if direct is not None:return Expression('(' + direct.code + ').clone()', direct.kind)
    message = "UnboundLocalError: cannot access local variable '" + receiver.arg + "' where it is not associated with a value"
    return Expression(emitter.at(emitter.slot(name, kind) + '.clone().ok_or_else(||' + _string(message) + '.to_owned())', node), kind)


def emit_super_call(emitter, node):
    from .native_classes import Expression, shape
    records = getattr(emitter.model, 'super_calls', {})
    key = (emitter.plan.index, id(node))
    if key not in records:return None
    record = records[key]
    if record is None:return Expression('()', 'none')
    method, receiver = record
    loaded = _receiver(emitter, node, receiver)
    return emitter.call_user(node, method, loaded)
