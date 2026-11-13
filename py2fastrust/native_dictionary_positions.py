"""Closed actual mapping allocation origins with tracked CP entry positions."""


def dictionary_kind(kind):
    from .native_class_mappings import mapping_kind
    from .native_mapping_views import view_kind
    return view_kind(kind)or mapping_kind(kind)and kind.record.category=='dict'


def literal_presize(node):
    """Ask the official compiler for this literal's outer allocation count.

    Large literals can use BUILD_MAP(0)/MAP_ADD rather than presizing all
    operands. No expression executes, and this analysis probe is never emitted.
    """
    import ast,dis
    from .native_classes import ClassUnsupported
    def clone(value):
        if isinstance(value,ast.AST):
            result=getattr(ast,type(value).__name__)(**{name:clone(item)for name,item in ast.iter_fields(value)})
            for name in value._attributes:
                if hasattr(value,name):setattr(result,name,getattr(value,name))
            return result
        if isinstance(value,list):return [clone(item)for item in value]
        return value
    tree=ast.Expression(clone(node))
    ast.fix_missing_locations(tree)
    try:code=compile(tree,'<pytors-dictionary-allocation>','eval',optimize=0)
    except (SyntaxError,TypeError,ValueError):
        raise ClassUnsupported(node,'dictionary literal entry positions need a proved official allocation/presizing plan for this expression context',proof='original dictionary allocation policy')from None
    span=(node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)
    counts=[instruction.arg for instruction in dis.get_instructions(code)
            if instruction.opname in {'BUILD_MAP','BUILD_CONST_KEY_MAP'}
            and tuple(instruction.positions)==span]
    if len(counts)!=1:
        raise ClassUnsupported(node,'dictionary literal allocation has no unique official outer presizing operation; this entry-position plan is not implemented',proof='original dictionary allocation policy')
    return counts[0]


def iterable_origin(kind,model,counter=False):
    from .native_classes import InstanceType,domain
    if domain(kind)in {'list','tuple_sequence','range','str','bytes','deque','array','bytearray','iterator','dict_view','set'}:return True
    if domain(kind)=='tuple':return not getattr(kind,'_native_named_tuple',False)
    if isinstance(kind,InstanceType)and model is not None:
        owner=model.classes[kind.name]
        if owner.node.bases:return False
        members=model.class_namespaces.members
        dynamic={'__getattr__','__getattribute__','__class__'}
        if dynamic.intersection(owner.methods)or dynamic.intersection(owner.fields)or any((owner.index,name)in members for name in dynamic):return False
        # Flat source instances cannot be registered ABC Mapping subclasses by
        # the admitted native APIs. Counter tests Mapping rather than duck keys.
        if counter:return True
        return ('keys'not in owner.fields and (owner.index,'keys')not in members
                and not {'keys','__getattr__','__getattribute__'}.intersection(owner.methods))
    return False


def proved(kind,model=None,seen=frozenset()):
    from .native_class_mappings import mapping_kind
    from .native_classes import shape
    from .native_types import alternatives
    if not mapping_kind(kind)or kind.record.category!='dict'or kind.record.flavor not in {'dict','Counter','defaultdict'}:return False
    record=kind.record
    if record.index in seen:return False
    seen=seen|{record.index}
    def source_proof(value,source_type,counter=False):
        if value is None:return True
        choices=alternatives(shape(value))
        if counter:choices=tuple(choice for choice in choices if choice!='none')
        if not choices:return counter
        mapped=[choice for choice in choices if mapping_kind(choice)and choice.record.category=='dict']
        if mapped:
            return len(mapped)==len(choices)and all(proved(choice,model,seen)for choice in choices)
        return source_type is not None and all(iterable_origin(choice,model,counter)for choice in choices)
    if record.operation in {'literal','comprehension'}:
        valid=record.flavor=='dict'
    elif record.operation=='copy':
        valid=record.source is not None and all(proved(choice,model,seen)for choice in alternatives(shape(record.source)))
    elif record.operation in {'constructor','Counter','defaultdict'}:
        valid=source_proof(record.source,record.source_type,record.flavor=='Counter')
    else:return False
    if not valid:return False
    if record.flavor=='Counter'and model is not None:
        for site in model.mappings.counters.sites.values():
            if site.name not in {'update','subtract'}or not any(mapping_kind(owner)and owner.record is record for owner in alternatives(shape(site.owner))):continue
            if site.mapping_source:
                for source in alternatives(shape(site.source))if site.source is not None else():
                    if source=='none'or mapping_kind(source)and source.record is record:continue
                    if not proved(source,model,seen):return False
            elif not source_proof(site.source,site.source_type,True):return False
    if model is not None:
        from .native_mapping_update import origins_valid
        if not origins_valid(model,record,seen):return False
    return True


def primitive_sources(model):
    """Actual primitive dictionary iteration, distinct from stored payloads."""
    import ast
    for record in model.iterators.records:
        provider=getattr(record.hint_protocol,'dictionary_sources',None)
        if provider is not None:
            yield from provider(record)
    for site in model.mappings.counters.sites.values():
        if site.mapping_source and site.source is not None:yield site.source
    for site in model.mappings.defaultdicts.sites.values():
        if site.source is not None and site.source_type is None:yield site.source
    iterables={id(node.iter)for node in model.iter_nodes()if isinstance(node,(ast.For,ast.comprehension))}
    for key,value in model.records.items():
        if key[1]in iterables:yield value


def guard(model,node):
    from .native_classes import shape,ClassUnsupported
    from .native_types import alternatives
    from .native_mapping_views import view_kind
    for record in model.iterators.records:
        if getattr(record.hint_protocol,'dictionary_sources',None)is None and any(
                dictionary_kind(kind)for kind in alternatives(shape(record.source))):
            raise ClassUnsupported(node,'an iterator provider has not declared whether its dictionary storage is a returned payload or a primitive dictionary cursor; its mutation-safe cursor-origin capability is unknown',proof='provider-owned primitive dictionary cursor origins')
    for source in primitive_sources(model):
        for kind in alternatives(shape(source)):
            if view_kind(kind):owners=alternatives(shape(kind.record.source))
            elif dictionary_kind(kind):owners=(kind,)
            else:continue
            if not all(proved(owner,model)for owner in owners):
                raise ClassUnsupported(node,'list.extend can reach a dictionary cursor whose actual allocation/copy origin has no proved entry-position history; this flavored or constructor origin remains unsupported',types=(('dictionary cursor source',kind),),proof='source-owned dictionary iterator position history')
