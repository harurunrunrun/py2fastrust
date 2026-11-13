"""Slice concrete shared sequences after capturing the owner and all bounds."""
import ast

from .native_types import alternatives

INTEGRAL=frozenset({'int','bool','int_bool'})
SEQUENCES=frozenset({'list','str','bytes','tuple_sequence'})
NONINDEXABLE=frozenset({'int','bool','int_bool','float','none','function'})
INVALID_BOUNDS=frozenset({'float','str','bytes','list','tuple','tuple_sequence','function','range'})


def fixed_tuple_indices(model,node,length):
    from .native_union_sequences import constant_index
    from .native_classes import ClassUnsupported
    from .literal_semantics import integer_policy
    policy=integer_policy(0 if model.integer=='bigint'else 64 if model.integer=='i64'else 128)
    def integer(expression):
        value=constant_index(model,expression)
        if value is not None:return value
        if isinstance(expression,ast.UnaryOp)and isinstance(expression.op,(ast.UAdd,ast.USub)):
            value=integer(expression.operand)
            if value is not None:return policy.normalize(-value if isinstance(expression.op,ast.USub)else value)
        return None
    values=[]
    for bound in(node.slice.lower,node.slice.upper,node.slice.step):
        if bound is None or isinstance(bound,ast.Constant)and bound.value is None:values.append(None);continue
        value=integer(bound)
        if value is None:
            raise ClassUnsupported(bound,'fixed-layout tuple slicing needs literal integral/None bounds until the dynamic tuple materialization adapter is implemented',proof='fixed tuple slice result layout')
        values.append(value)
    if values[2]==0:return None
    return tuple(range(length)[slice(*values)])


def requires_frames(unit,analysis):
    from .native_types import TupleSequenceType,ListType,immutable
    from .native_range_slices import has_range_value
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for facts in analysis.scopes.values():
        if any(isinstance(node,ast.Subscript)and isinstance(node.ctx,ast.Store)
               and isinstance(node.slice,ast.Slice)and unit.ordinal(node.value)in facts.values
               for node in nodes.values()):return True
        for site in facts.expressions:
            node=nodes.get(site)
            if not isinstance(node,ast.Subscript)or not isinstance(node.slice,ast.Slice):continue
            source=facts.values.get(unit.ordinal(node.value))
            if has_range_value(source,analysis.heap):return True
            owner=facts.expressions.get(unit.ordinal(node.value))
            choices=alternatives(owner)
            if owner is not None and (len(choices)>1 or any(kind in {'bytes','range'}or isinstance(kind,TupleSequenceType)for kind in choices)):
                return True
            if any(isinstance(kind,ListType)and not immutable(kind.element)for kind in choices):return True
            for bound in (node.slice.lower,node.slice.upper,node.slice.step):
                if bound is None:continue
                kind=facts.expressions.get(unit.ordinal(bound))
                if kind is not None and any(value not in INTEGRAL|{'none'}for value in alternatives(kind)):return True
    return False


def analyze(model,plan,node,environment):
    from .native_classes import Cell,ClassUnsupported,domain,shape,tuple_cell
    from .native_union_sequences import branches
    owner=model.expression(plan,node.value,environment)
    from .native_source_items import source_owner,check_key
    if source_owner(model,owner)is not None:check_key(node)
    captured_bounds=[]
    for bound in (node.slice.lower,node.slice.upper,node.slice.step):
        if bound is None:captured_bounds.append(None);continue
        value=model.expression(plan,bound,environment);captured_bounds.append(value)
        for kind in alternatives(shape(value)):
            if kind is None and not model.final:continue
            if domain(kind)not in INTEGRAL|{'none'}|INVALID_BOUNDS:
                raise ClassUnsupported(bound,'this slice bound needs its user __index__ method; the typed sequence slice adapter supports builtin integral bounds and their builtin type errors',types=(('bound',kind),),proof='slice bound __index__ protocol')
    from .native_list_slice_assignment import capture_read
    capture_read(model,plan,node,owner,captured_bounds)
    result=model.cell(plan,node)
    for value in branches(owner):
        if value.tag == 'list':
            # Slicing creates a new outer list, while retaining its element
            # references. Register that allocation just like a list literal;
            # an unknown origin would otherwise alias every source list.
            output=model.cell(plan,node,'list',(value.args[0],),identity=('slice_list',))
        elif getattr(value.tag,'_native_array',False)or getattr(value.tag,'_native_bytearray',False):output=Cell(value.tag)
        elif value.tag == 'tuple_sequence':
            output=Cell(value.tag,(value.args[0],))
        elif value.tag in {'str','bytes'}:output=Cell(value.tag)
        elif value.tag in NONINDEXABLE:output=Cell('none')
        elif value.tag=='range':output=Cell('range')
        elif tuple_cell(value):
            indices=fixed_tuple_indices(model,node,len(value.args))
            output=Cell('none')if indices is None else Cell('tuple',tuple(value.args[index]for index in indices))
        elif value.tag is None and not model.final:continue
        else:
            raise ClassUnsupported(node,'slicing this receiver needs its tuple-layout or user __getitem__ slice protocol; the typed slice adapter supports lists, strings, bytes and homogeneous runtime tuples',types=(('receiver',shape(value)),),proof='registered sequence slice storage')
        if not model.namespace.contribute(result,output,node,force=True):model.contribute(result,output,node)
    return model.remember(plan,node,result)


def _bound(emitter,node,value):
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native import _string
    if value is None:return 'None'
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:_bound(emitter,node,Expression(f'({code}).clone()',kind)))
    if value.kind=='none':return 'None'
    if domain(value.kind)in INTEGRAL:
        number=emitter.number(value)
        if emitter.model.integer=='bigint':
            number=f'({number}).to_i128().unwrap_or_else(||if ({number}).is_negative(){{i128::MIN}}else{{i128::MAX}})'
        else:number=f'({number})as i128'
        return 'Some('+number+')'
    message='TypeError: slice indices must be integers or None or have an __index__ method'
    return emitter.at('Err::<Option<i128>,String>('+_string(message)+'.to_owned())',node)



def convert_bounds(emitter,node,bounds):
    """Convert the already captured slice: step and zero check precede bounds."""
    names=[emitter.fresh()for _ in bounds]
    setup='let '+names[2]+'='+_bound(emitter,node,bounds[2])+';'
    setup+='if '+names[2]+'==Some(0){'+emitter.at('Err::<(),String>("ValueError: slice step cannot be zero".to_owned())',node)+';}'
    setup+=''.join('let '+names[i]+'='+_bound(emitter,node,bounds[i])+';'for i in(0,1))
    return setup,names


def _owner(emitter,node,owner,bounds,wanted):
    from .native_classes import Expression,domain
    from .native_types import ListType,TupleSequenceType
    from .native_unions import union_kind,project
    from .native_class_builtins import _error,_type_name
    if union_kind(owner.kind):
        return Expression(project(owner.kind,owner.code,lambda kind,code:_owner(emitter,node,Expression(f'({code}).clone()',kind),bounds,wanted).code),wanted)
    tag=domain(owner.kind)
    if tag=='tuple':
        from .native_types import TupleType,tuple_code
        indices=fixed_tuple_indices(emitter.model,node,len(owner.kind.fields))
        if indices is None:return _error(emitter,node,wanted,'"ValueError: slice step cannot be zero".to_owned()')
        setup,source=emitter.capture(owner)
        raw=TupleType(tuple(owner.kind.fields[index]for index in indices))
        value=Expression(tuple_code(f'{source.code}.{index}.clone()'for index in indices),raw)
        return Expression('{'+setup+emitter.coerce(value,wanted,node)+'}',wanted)
    if tag in NONINDEXABLE:
        return _error(emitter,node,wanted,'format!("TypeError: \'{}\' object is not subscriptable",'+_type_name(emitter,owner,node)+')')
    if tag=='range':
        from .native_range_slices import emit as range_slice
        return range_slice(emitter,node,owner,bounds,wanted)
    setup,owner=emitter.capture(owner)
    # Bound expressions were captured in source order. Builtin slice conversion
    # checks step first, then start and stop, after evaluating all expressions.
    converted,names=convert_bounds(emitter,node,bounds)
    setup+=converted
    if tag in {'array','bytearray'}:length=f'{owner.code}.0.borrow().len()'
    elif tag=='list':length=f'{owner.code}.borrow().len()'
    elif tag=='str':length=f'{owner.code}.'+('byte_len()'if emitter.model.string_mode=='ascii'else'codepoint_len()')
    else:length=f'{owner.code}.len()'
    indices=emitter.fresh()
    setup+=f'let {indices}='+emitter.at(f'native_slice_indices({length},{",".join(names)})',node)+';'
    if tag=='str':
        value=Expression(emitter.at(f'native_text_slice(&{owner.code},{indices},'+('true'if emitter.model.string_mode=='ascii'else'false')+')',node),'str')
    else:
        values,position=emitter.fresh(),emitter.fresh()
        element=owner.kind.element if tag in {'list','tuple_sequence'}else None
        raw_type=owner.kind.raw if tag=='array'else'u8'if tag=='bytearray'else emitter.rust_type(element)if element is not None else'u8'
        setup+=f'let mut {values}=Vec::<{raw_type}>::new();'
        setup+=emitter.at(f'{values}.try_reserve({indices}.len()).map_err(|_|"MemoryError: cannot allocate slice".to_owned())',node)+';'
        if tag in {'array','bytearray'}:
            read=emitter.fresh()
            setup+=f'{{let {read}={owner.code}.0.borrow();for {position} in {indices}{{{values}.push({read}[{position}]);}}}}'
            value=Expression(f'{owner.kind.rust}(Rc::new(RefCell::new({values})))',owner.kind)
        elif tag=='list':
            read=emitter.fresh()
            setup+=f'{{let {read}={owner.code}.borrow();for {position} in {indices}{{{values}.push({read}[{position}].clone());}}}}'
            value=Expression(f'class_list({values})',ListType(element))
        elif tag=='tuple_sequence':
            setup+=f'for {position} in {indices}{{{values}.push({owner.code}.as_slice()[{position}].clone());}}'
            value=Expression(f'NativeTuple::from_vec({values})',TupleSequenceType(element))
        else:
            setup+=f'for {position} in {indices}{{{values}.push({owner.code}[{position}]);}}'
            value=Expression(values,'bytes')
    return Expression('{'+setup+emitter.coerce(value,wanted,node)+'}',wanted)


def emit(emitter,node,wanted):
    setup,owner=emitter.capture(emitter.expression(node.value))
    bounds=[]
    for bound in (node.slice.lower,node.slice.upper,node.slice.step):
        if bound is None:bounds.append(None)
        else:
            before,value=emitter.capture(emitter.expression(bound));setup+=before;bounds.append(value)
    emitter.model.native_frame_slices_required=True
    value=_owner(emitter,node,owner,bounds,wanted)
    from .native_classes import Expression
    return Expression('{'+setup+value.code+'}',wanted)


def runtime(model):
    if not getattr(model,'native_frame_slices_required',False):return ''
    from .native_slices import SLICE_HELPERS
    from .native_range_slices import runtime as range_runtime
    return SLICE_HELPERS+range_runtime(model)
