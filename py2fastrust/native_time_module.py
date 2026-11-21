"""Clock and sleep functions of the ``time`` module (Modules/timemodule.c, CPython 3.14).

``time()`` reads the system real-time clock and converts its nanosecond count
to float seconds as ``_PyTime_AsSecondsDouble`` does: exact division when the
count is a whole number of seconds, otherwise ``ns / 1e9``. ``monotonic()`` and
``perf_counter()`` read the monotonic clock; Python leaves their reference
point undefined, so the native clock measures from a process-wide origin and
only differences are meaningful, as in CPython. The ``*_ns`` variants return
the same readings as integers. ``sleep(secs)`` converts its argument with the
``_PyTime_FromSecondsObject`` rules (round away from zero, 64-bit nanosecond
range) before checking the sign, then suspends the thread.
"""
from dataclasses import dataclass

CLOCKS = {'time': 'class_time_realtime_ns()', 'monotonic': 'class_time_monotonic_ns()', 'perf_counter': 'class_time_monotonic_ns()'}
NAMES = frozenset(CLOCKS) | frozenset(name + '_ns' for name in CLOCKS) | {'sleep'}


@dataclass
class TimeCall:
    result: object
    error: str | None = None


def _binding(name, positional, keywords):
    if keywords:
        return 'TypeError: time.' + name + '() takes no keyword arguments'
    if name == 'sleep':
        if len(positional) != 1:
            return 'TypeError: time.sleep() takes exactly one argument (' + str(len(positional)) + ' given)'
    elif positional:
        return 'TypeError: time.' + name + '() takes no arguments (' + str(len(positional)) + ' given)'
    return None


class TimeAdapter:
    NAMES = NAMES
    TYPES = frozenset()

    @staticmethod
    def member_type_name(name):
        return 'builtin_function_or_method'

    @staticmethod
    def analyze(model, plan, node, identity, metadata, positional, keywords, environment, *, factory):
        from .native_classes import ClassUnsupported, shape, domain
        from .native_types import EMPTY, EmptyType, alternatives
        name = identity.name
        failure = _binding(name, positional, keywords)
        if failure:
            return TimeCall(factory(EMPTY), failure)
        model.native_time_required = True
        if name == 'sleep':
            for kind in alternatives(shape(positional[0])):
                if kind is None or isinstance(kind, EmptyType) or kind in {'int', 'bool', 'int_bool', 'float', 'none', 'str', 'bytes'}:
                    continue
                if domain(kind) == 'object':
                    raise ClassUnsupported(node, 'time.sleep() with a source instance needs its __float__/__index__ conversion protocol; int and float durations are implemented',
                                           types=(('secs', kind),), proof='time.sleep duration conversion')
            return TimeCall(factory('none'))
        return TimeCall(factory('int' if name.endswith('_ns') else 'float'))

    @staticmethod
    def emit(emitter, node, identity, record, positional, keywords):
        from .native_classes import Expression, shape
        from .native import _string
        wanted = shape(record.result)
        if record.error:
            return Expression(emitter.at('Err::<' + emitter.rust_type(wanted) + ',String>(' + _string(record.error) + '.to_owned())', node), wanted)
        name = identity.name
        if name == 'sleep':
            return Expression(_sleep(emitter, node, positional[0]), wanted)
        reading = CLOCKS[name.removesuffix('_ns')]
        if name.endswith('_ns'):
            if emitter.model.integer == 'bigint':
                return Expression('Int::exact_small(' + reading + ')', wanted)
            return Expression('((' + reading + ') as NativeInt)', wanted)
        return Expression('class_time_seconds(' + reading + ')', wanted)


def _sleep(emitter, node, value):
    from .native_classes import Expression
    from .native_unions import union_kind, project
    from .native_class_builtins import _type_name
    from .native_types import EmptyType

    def duration(kind, code):
        if isinstance(kind, EmptyType):
            return 'native_empty::<i64>(' + code + ')'
        if kind in {'int', 'bool', 'int_bool'}:
            number = emitter.number(Expression(code, kind))
            whole = '(' + number + ').clone().normalized().to_i128()' if emitter.model.integer == 'bigint' else 'Some((' + number + ') as i128)'
            return emitter.at('class_time_integer_timeout(' + whole + ')', node)
        if kind == 'float':
            return emitter.at('class_time_float_timeout(' + code + ')', node)
        message = 'format!("TypeError: \'{}\' object cannot be interpreted as an integer or float",' + _type_name(emitter, Expression(code, kind), node) + ')'
        return emitter.at('Err::<i64,String>(' + message + ')', node)
    nanoseconds = project(value.kind, value.code, duration) if union_kind(value.kind) else duration(value.kind, value.code)
    return emitter.at('class_time_sleep(' + nanoseconds + ')', node)


RUNTIME = r'''
fn class_time_realtime_ns()->i128 {
    match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH){
        Ok(elapsed)=>elapsed.as_nanos() as i128,
        Err(error)=>-(error.duration().as_nanos() as i128),
    }
}

fn class_time_monotonic_ns()->i128 {
    static ORIGIN:std::sync::OnceLock<std::time::Instant>=std::sync::OnceLock::new();
    ORIGIN.get_or_init(std::time::Instant::now).elapsed().as_nanos() as i128
}

fn class_time_seconds(nanoseconds:i128)->f64 {
    if nanoseconds%1_000_000_000==0{(nanoseconds/1_000_000_000) as f64}else{nanoseconds as f64/1e9}
}

fn class_time_integer_timeout(seconds:Option<i128>)->Result<i64,String> {
    seconds.and_then(|value|value.checked_mul(1_000_000_000)).and_then(|value|i64::try_from(value).ok())
        .ok_or_else(||"OverflowError: timestamp too large to convert to C PyTime_t".to_owned())
}

fn class_time_float_timeout(seconds:f64)->Result<i64,String> {
    if seconds.is_nan(){return Err("ValueError: Invalid value NaN (not a number)".to_owned());}
    let scaled=seconds*1e9;
    let rounded=if scaled>=0.0{scaled.ceil()}else{scaled.floor()};
    if !((i64::MIN as f64)<=rounded&&rounded< -(i64::MIN as f64)){
        return Err("OverflowError: timestamp out of range for platform time_t".to_owned());
    }
    Ok(rounded as i64)
}

fn class_time_sleep(nanoseconds:i64)->Result<(),String> {
    if nanoseconds<0{return Err("ValueError: sleep length must be non-negative".to_owned());}
    std::thread::sleep(std::time::Duration::from_nanos(nanoseconds as u64));
    Ok(())
}
'''


def runtime(model):
    return RUNTIME if getattr(model, 'native_time_required', False) else ''
