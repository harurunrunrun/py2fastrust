"""Provider-owned length-hint certificates for actual typed iterator values.

An unregistered capability is unknown, never an assertion that a Python slot
is absent. Canonical constructors publish these proofs with their own layout.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class AbsentHint:
    def dictionary_sources(self, record):
        return ()

    def emit(self, emitter, node, value):
        return '8_usize'


ABSENT = AbsentHint()


@dataclass(frozen=True)
class RepeatHint:
    def dictionary_sources(self, record):
        return ()

    def emit(self, emitter, node, value):
        # Infinite repeat's __length_hint__ raises TypeError; LengthHint
        # suppresses that exception and uses the consumer's default.
        return '(' + value.code + ').borrow().remaining.unwrap_or(8_usize)'


REPEAT = RepeatHint()


@dataclass(frozen=True)
class SourceHint:
    reverse: bool = False

    def dictionary_sources(self, record):
        return (record.source,)

    def emit(self, emitter, node, value):
        from .native_classes import shape
        from .native_types import alternatives
        from .native_unions import union_kind
        record = value.kind.record
        kind = shape(record.source)
        state = emitter.fresh()
        prefix = '{let ' + state + '=(' + value.code + ').borrow();'
        if union_kind(kind):
            arms = []
            for index, choice in enumerate(alternatives(kind)):
                source = emitter.fresh()
                body = self.source(emitter, node, choice, source, state + '.index')
                arms.append('ClassIteratorSource_' + str(record.index) + '::V' + str(index)
                            + '(' + source + ')=>' + body)
            return prefix + 'match &' + state + '.source{' + ','.join(arms) + '}}'
        return prefix + self.source(emitter, node, kind, state + '.source', state + '.index') + '}'

    def source(self, emitter, node, kind, source, index):
        from .native_classes import domain, ClassUnsupported
        from .native_set_cursors import accepts, hint
        if accepts(emitter.model, kind):
            return hint(emitter, node, kind, source)
        tag = domain(kind)
        if getattr(kind, '_native_class_deque', False):
            return '(' + source + ').remaining'
        if tag == 'range':
            if self.reverse:
                emitter.model.iterator_hint_reverse_range = True
                return emitter.at('class_iterator_reverse_range_length(&(' + source
                    + ').first,&(' + source + ').cursor,&(' + source + ').step,('
                    + source + ').active)', node)
            emitter.model.list_extend_range = True
            active = '(' + source + ').active' if emitter.model.integer != 'bigint' else 'true'
            length = emitter.at('class_list_extend_range_length(&(' + source + ').cursor,&('
                                + source + ').stop,&(' + source + ').step)', node)
            return 'if ' + active + '{' + length + '}else{0_usize}'
        if tag in {'list', 'tuple_sequence', 'tuple', 'bytes', 'str'}:
            owner = emitter.fresh()
            current = '(' + source + ').source' if self.reverse else '(' + source + ')'
            end = '(' + source + ').end' if self.reverse else index
            if tag == 'list':
                length = owner + '.borrow().len()'
            elif tag == 'tuple_sequence':
                length = owner + '.as_slice().len()'
            elif tag == 'tuple':
                length = str(len(kind.fields)) + '_usize'
            elif tag == 'str' and emitter.model.string_mode != 'ascii':
                retained = '..' + end if self.reverse else end + '..'
                return (current + '.as_ref().map_or(0,|' + owner + '|' + owner + '.get('
                        + retained + ').map_or(0,|text|text.chars().count()))')
            else:
                length = owner + '.len()'
            remaining = ('if ' + end + '<=(' + length + '){' + end + '}else{0_usize}'
                         if self.reverse else '(' + length + ').saturating_sub(' + end + ')')
            return current + '.as_ref().map_or(0,|' + owner + '|' + remaining + ')'
        from .native_dictionary_positions import dictionary_kind
        if not self.reverse and dictionary_kind(kind):
            return emitter.model.mappings.views.hint_cursor(emitter,node,kind,source)
        raise ClassUnsupported(node, "this iterable consumer needs its source cursor's checked remaining-position length hint; that provider capability is not implemented",
                               types=(('iterator source', kind),), proof='registered source cursor remaining-length hint')


@dataclass(frozen=True)
class IndexedOwnerHint:
    reverse: bool = False

    def dictionary_sources(self, record):
        return ()

    def emit(self, emitter, node, value):
        state, owner = emitter.fresh(), emitter.fresh()
        length = owner + '.0.borrow().len()'
        count = state + '.index'
        remaining = ('if ' + count + '<=(' + length + '){' + count + '}else{0_usize}'
                     if self.reverse else '(' + length + ').saturating_sub(' + count + ')')
        return '{let ' + state + '=(' + value.code + ').borrow();' + state + '.source.as_ref().map_or(0,|' + owner + '|' + remaining + ')}'


def emit(emitter, node, value):
    from .native_classes import ClassUnsupported
    capability = value.kind.record.hint_protocol
    if capability is None:
        raise ClassUnsupported(node, "this iterable consumer needs its iterator provider's remaining-length hint protocol; the provider has not published an absent-slot or implemented-state certificate",
                               types=(('iterable', value.kind),), proof='provider-owned iterator length hint')
    return capability.emit(emitter, node, value)


def runtime(model):
    if not getattr(model, 'iterator_hint_reverse_range', False):
        return ''
    if model.integer == 'bigint':
        count = '''let distance=if step.is_negative(){first.sub(cursor)}else{cursor.sub(first)};
        let length=distance.divmod(&step.abs()).unwrap().0.add(&Int::from_i128(1));
        length.to_i128().and_then(|value|isize::try_from(value).ok()).map(|value|value as usize)'''
    else:
        count = '''let distance=if *step>0{(*cursor as u128).wrapping_sub(*first as u128)}else{(*first as u128).wrapping_sub(*cursor as u128)};
        let length=(distance/(step.unsigned_abs()as u128)).checked_add(1);
        length.and_then(|value|isize::try_from(value).ok()).map(|value|value as usize)'''
    return 'fn class_iterator_reverse_range_length(first:&NativeInt,cursor:&NativeInt,step:&NativeInt,active:bool)->Result<usize,String>{if !active{return Ok(0);}({' + count + '}).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())}'
