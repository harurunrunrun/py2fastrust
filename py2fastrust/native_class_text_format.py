"""Literal str.format templates lowered through the official field parser."""
import ast
import _string
import string
from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    message:str


@dataclass(frozen=True)
class Field:
    name:int|str
    conversion:str|None
    specification:tuple


@dataclass(frozen=True)
class FormatSite:
    parts:tuple


def requires_frames(unit,analysis):
    return any(isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)
               and node.func.attr=='format'for node in ast.walk(unit.tree))


def parse(template,count,keywords,*,numbering=None,depth=2):
    if depth<=0:return (Failure('ValueError: Max string recursion exceeded'),)
    numbering=[0]if numbering is None else numbering
    result=[]
    iterator=string.Formatter().parse(template)
    while True:
        try:literal,field,specification,conversion=next(iterator)
        except StopIteration:return tuple(result)
        except ValueError as error:
            return (*result,Failure('ValueError: '+str(error)))
        if literal:result.append(literal)
        if field is None:continue
        try:
            root,accesses=_string.formatter_field_name_split(field)
        except ValueError as error:
            return (*result,Failure('ValueError: '+str(error)))
        if root=='':
            if numbering[0]is None:
                return (*result,Failure('ValueError: cannot switch from manual field specification to automatic field numbering'))
            root=numbering[0];numbering[0]+=1
        elif isinstance(root,int):
            if numbering[0]not in (0,None):
                return (*result,Failure('ValueError: cannot switch from automatic field numbering to manual field specification'))
            numbering[0]=None
        if isinstance(root,int)and root>=count:
            return (*result,Failure(f'IndexError: Replacement index {root} out of range for positional args tuple'))
        if isinstance(root,str)and root not in keywords:
            return (*result,Failure('KeyError: '+repr(root)))
        try:access=next(accesses,None)
        except ValueError as error:
            return (*result,Failure('ValueError: '+str(error)))
        if access is not None:
            # Original field syntax is retained rather than silently dropping
            # a traversal or guessing which typed object/member it denotes.
            raise UnsupportedField(field)
        if conversion not in {None,'s','r','a'}:
            return (*result,Failure('ValueError: Unknown conversion specifier '+conversion))
        nested=(parse(specification,count,keywords,numbering=numbering,depth=depth-1)
                if '{'in specification or'}'in specification else(specification,))
        result.append(Field(root,conversion,nested))
        # Parsing stops at an unconditional error in an expanded spec, just as
        # the format call itself does before visiting any following fields.
        if any(isinstance(part,Failure)for part in nested):return tuple(result)


class UnsupportedField(ValueError):
    pass


def analyze(model,plan,node,receiver,arguments,keywords,environment=None):
    from .native_classes import ClassUnsupported,shape
    if node.func.attr!='format'or shape(receiver)!='str':return None
    if not isinstance(node.func.value,ast.Constant)or not isinstance(node.func.value.value,str):
        raise ClassUnsupported(node,'str.format with a nonliteral template needs runtime field parsing and typed attribute/index traversal; this adapter currently lowers original literal templates',proof='literal string format template')
    if (any(isinstance(argument,ast.Starred)for argument in node.args)
            or any(keyword.arg is None for keyword in node.keywords)
            or len(arguments)!=len(node.args)or len(keywords)!=len(node.keywords)):
        raise ClassUnsupported(node,'expanded str.format arguments need ordered captured field binding; only original explicit positional and keyword arguments are implemented',proof='string format argument binding')
    try:parts=parse(node.func.value.value,len(arguments),{name for name,_ in keywords})
    except UnsupportedField as error:
        raise ClassUnsupported(node,'str.format field '+repr(str(error))+' needs typed attribute or subscript traversal; this adapter currently supports positional/named root fields, conversions and nested specifications',proof='string format field traversal')from None
    if not hasattr(model,'text_format_sites'):model.text_format_sites={}
    model.text_format_sites[(plan.index,id(node))]=FormatSite(parts)
    if environment is not None:
        from .native_source_display import analyze as analyze_display
        named=dict(keywords)
        def observers(parts):
            for part in parts:
                if isinstance(part,Failure):break
                if not isinstance(part,Field):continue
                value=arguments[part.name]if isinstance(part.name,int)else named[part.name]
                if part.conversion is not None:
                    analyze_display(model,plan,node,value,environment,part.conversion in {'r','a'})
                observers(part.specification)
                if part.conversion is None and not(all(isinstance(child,str)for child in part.specification)and bool(''.join(part.specification))):
                    analyze_display(model,plan,node,value,environment)
        observers(parts)
    # Every argument is analyzed by the ordinary call path. Their field types
    # can settle through constructor/loop inference before final emission.
    return model.cell(plan,node,'str')


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_classes import Expression
    from .native import _string
    from .native_class_builtins import _error
    from .native_formatting import conversion,format_value
    site=getattr(emitter.model,'text_format_sites',{}).get((emitter.plan.index,id(node)))
    if site is None:return None
    def build(parts):
        result=emitter.fresh();code=[f'let mut {result}=String::new();']
        for part in parts:
            if isinstance(part,str):
                if part:code.append(f'{result}.push_str({_string(part)});')
            elif isinstance(part,Failure):
                failure=_error(emitter,node,'str',_string(part.message)+'.to_owned()')
                code.append(f'let _={failure.code};')
                break
            else:
                value=arguments[part.name]if isinstance(part.name,int)else keywords[part.name]
                if part.conversion is not None:
                    before,value=emitter.capture(conversion(emitter,node,value,ord(part.conversion)))
                    code.append(before)
                if part.specification==('',)and value.kind in {'int','bool','int_bool','str'}:
                    rendered=conversion(emitter,node,value,115)
                    code.append(f'{result}.push_str(&({rendered.code}));')
                    continue
                before,specification=emitter.capture(build(part.specification));code.append(before)
                formatted=format_value(emitter,node,value,specification)
                code.append(f'{result}.push_str(&({formatted.code}));')
        constant=''.join(parts)if all(isinstance(part,str)for part in parts)else None
        return Expression('{'+''.join(code)+f'NativeText::from({result})'+'}','str',constant)
    return build(site.parts)
