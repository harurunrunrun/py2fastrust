"""Encode proved ordinary text as UTF-8 without a runtime codec interpreter."""
import ast
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Site:
    encoding:object
    errors:object
    failure:str|None=None


@lru_cache(maxsize=None)
def binding_error(count,names):
    # Official builtin binding is deterministic; these fixed placeholder values
    # never evaluate source expressions or call a registered error handler.
    try:''.encode(*(['utf8'if index==0 else'strict'for index in range(count)]),
                  **{name:'utf8'if name=='encoding'else'strict'for name in names})
    except TypeError as error:return 'TypeError: '+str(error)
    return None


def utf8_name(text):
    import encodings
    import encodings.aliases
    normalized=encodings.normalize_encoding(text).lower()
    return encodings.aliases.aliases.get(normalized,normalized)in {'utf_8','utf8'}


def requires_frames(unit,analysis):
    from .native_constraints import MethodValue
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    from .native import _Unsupported
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    found=False
    for facts in analysis.scopes.values():
        for ordinal,call in facts.calls.items():
            node=nodes.get(ordinal)
            for identity in call.identity.alternatives:
                if not isinstance(identity,MethodValue)or identity.name!='encode':continue
                kinds=builtin_text_receiver_kinds(unit,facts,node,identity,allowed={'str'})
                if kinds!={'str'}:continue
                original=nodes.get(identity.site)
                if not(isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)
                       and identity.site==unit.ordinal(node.func)):
                    raise _Unsupported('a stored str.encode bound method needs its owned receiver, callable binding and method identity protocol; this initial encoder supports direct proved-str method calls',node=original or node,proof='stored builtin text encoder callable')
                found=True
    return found


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import ClassUnsupported,shape
    from .native_types import alternatives
    if node.func.attr!='encode'or shape(receiver)!='str':return None
    if (any(isinstance(arg,ast.Starred)for arg in node.args)or any(key.arg is None for key in node.keywords)
            or len(arguments)!=len(node.args)or len(keywords)!=len(node.keywords)):
        raise ClassUnsupported(node,'expanded str.encode arguments need their captured builtin method binding protocol; this initial encoder supports explicit positional and keyword arguments',proof='UTF-8 encoder expanded argument binding')
    names=tuple(name for name,_ in keywords)
    failure=binding_error(len(arguments),names)
    bound=dict(zip(('encoding','errors'),node.args));bound.update((key.arg,key.value)for key in node.keywords)
    encoding=bound.get('encoding');errors=bound.get('errors')
    if failure is None and encoding is not None:
        values=dict(zip(('encoding','errors'),arguments));values.update(keywords)
        encoding_kinds=alternatives(shape(values['encoding']))
        error_kinds=alternatives(shape(values['errors']))if 'errors'in values else('str',)
        encoding_type_may_pass='str'in encoding_kinds
        errors_type_may_pass='str'in error_kinds
        nul=isinstance(encoding,ast.Constant)and isinstance(encoding.value,str)and '\0'in encoding.value
        known=(isinstance(encoding,ast.Constant)and isinstance(encoding.value,str)and utf8_name(encoding.value))
        if encoding_type_may_pass and errors_type_may_pass and not nul and not known and model.final:
            description=repr(encoding.value)if isinstance(encoding,ast.Constant)else'a dynamic encoding name'
            raise ClassUnsupported(encoding,'str.encode with '+description+' requires a codec lookup/encoding implementation; this adapter proves only the default UTF-8 codec or an explicit UTF-8 alias',proof='proved builtin UTF-8 codec identity')
    if not hasattr(model,'utf8_encoding_sites'):model.utf8_encoding_sites={}
    model.utf8_encoding_sites[plan.index,id(node)]=Site(encoding,errors,failure)
    return model.cell(plan,node,'bytes')


def emit(emitter,node,receiver,arguments,keywords,wanted):
    site=getattr(emitter.model,'utf8_encoding_sites',{}).get((emitter.plan.index,id(node)))
    if site is None:return None
    from .native_classes import Expression
    from .native import _string
    from .native_unions import project
    from .native_class_builtins import _type_name
    if site.failure:
        return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(site.failure)+'.to_owned())',node),wanted)
    values=dict(zip(('encoding','errors'),arguments));values.update(keywords)
    checks=[]
    for name in ('encoding','errors'):
        if name not in values:continue
        def checked(kind,code):
            if kind=='str':
                failed='if ('+code+').as_bytes().contains(&0){Err("ValueError: embedded null character".to_owned())}else{Ok(())}'
                return emitter.at(failed,node)
            actual='"None"'if kind=='none'else _type_name(emitter,Expression(code,kind),node)
            message='format!("TypeError: encode() argument \'{name}\' must be str, not {}",'+actual+')'
            message=message.replace('{name}',name)
            return emitter.at('Err::<(),String>('+message+')',node)
        checks.append(project(values[name].kind,values[name].code,checked)+';')
    view,result=emitter.fresh(),emitter.fresh()
    code='{'+''.join(checks)+'let '+view+'=&('+receiver.code+');let mut '+result+'=Vec::<u8>::new();'
    code+=emitter.at(result+'.try_reserve_exact('+view+'.len()).map_err(|_|"MemoryError".to_owned())',node)+';'
    code+=result+'.extend_from_slice('+view+'.as_bytes());'+result+'}'
    return Expression(emitter.coerce(Expression(code,'bytes'),wanted,node),wanted)
