"""Original-owner hints for canonical materializers which request LengthHint."""


def requires_frames(analysis):
    from .native_constraints import RangeValue
    from .references import BuiltinIdentity
    consumers={BuiltinIdentity('list'),BuiltinIdentity('sorted')}
    for facts in analysis.scopes.values():
        for site,call in facts.calls.items():
            if not consumers.intersection(call.identity.alternatives)or not call.positional:
                continue
            if any(isinstance(part,RangeValue)for part in call.positional[0].alternatives):
                term=analysis.graph.expressions.get(site)
                operands=term.operands[1]if term is not None and term.operation=='call'else()
                source=facts.calls.get(operands[0].site)if operands else None
                if(source is not None and not source.identity.unknown and not source.identity.unbound
                        and source.identity.alternatives==frozenset({BuiltinIdentity('range')})):
                    continue
                return True
    return False


def emit(emitter,node,value,consumer):
    from .native_classes import Expression,InstanceType
    from .native_class_iterators import iterator_kind
    from .native_unions import project,union_kind
    if consumer not in {'list','sorted'}:
        raise AssertionError('this materializer has no registered LengthHint phase')
    if union_kind(value.kind):
        return project(value.kind,value.code,
                       lambda kind,code:emit(emitter,node,Expression(code,kind),consumer)or'8_usize')
    if isinstance(value.kind,InstanceType):
        from .native_source_lengths import emit_hint
        return emit_hint(emitter,node,value,consumer)
    if iterator_kind(value.kind):
        from .native_iterator_hints import emit as provider_hint
        return provider_hint(emitter,node,value)
    from .native_classes import domain
    if domain(value.kind)=='range':
        from .native_list_extend import hint_value
        return hint_value(emitter,node,value)
    return None


def range_count(integer):
    if integer=='bigint':
        return '''let one=Int::from_i128(1);
            let (distance,step)=if step.is_negative(){if start<=stop{return Ok(0);}(start.sub(stop),step.abs())}
                else{if start>=stop{return Ok(0);}(stop.sub(start),step.clone())};
            let length=distance.sub(&one).divmod(&step).unwrap().0.add(&one);
            length.to_i128().and_then(|value|isize::try_from(value).ok()).map(|value|value as usize)'''
    return '''let distance=if *step>0{if start>=stop{return Ok(0); }(*stop as u128).wrapping_sub(*start as u128)}
                else{if start<=stop{return Ok(0);}(*start as u128).wrapping_sub(*stop as u128)};
            let length=(distance-1)/(step.unsigned_abs()as u128)+1;
            isize::try_from(length).ok().map(|value|value as usize)'''


def ordinary_range_reserve(generator,source,node,values):
    capture=source.range_capture
    if capture is None:return ''
    count=range_count('i64'if generator.bits else'bigint')
    lower,upper,step=capture.lower,capture.upper,capture.step
    if not generator.bits:
        lower,upper,step=('('+source.iterator+').'+name for name in ('cursor','stop','step'))
    checked=('(||->Result<usize,String>{let start:&NativeInt=&('+lower+');let stop:&NativeInt=&('
             +upper+');let step:&NativeInt=&('+step+');({' + count
             +'}).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())})()')
    hint=generator.temporary()
    return ('let '+hint+'='+generator.at(checked,node)+';\n'
            +generator.at('native_typed_reserve(&mut '+values+','+hint+')',node)+';\n')
