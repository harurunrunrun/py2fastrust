"""A typed live view of actual module binding presence, separate from fallback."""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalsViewType:
    _native_kind_tag="module_globals_dict"
    _native_namespace_view=True
    _native_reference_cloneable=True


GLOBALS_VIEW=GlobalsViewType()


def names(namespace):
    model=namespace.model
    linker=getattr(model,'module_linker',None)
    if linker is not None:return linker.namespace_names()
    initial={"__name__","__doc__","__package__","__loader__","__spec__","__builtins__"}
    if not(model.filename.startswith("<")and model.filename.endswith(">")):
        initial.update({"__file__","__cached__"})
    bound={binding.name for binding in model.unit.bindings
           if model.module_owner(binding.owner)and binding.role not in {"load","parameter"}}
    return sorted(initial|bound),initial


def store(emitter,node,*,name=None,present=True):
    namespace=emitter.model.namespace
    if not namespace.globals_observed:return ""
    if name is None:
        binding=namespace.owners.get(emitter.model.unit.ordinal(node))
        if binding is None or not emitter.model.module_owner(binding.owner):return ""
        name=binding.name
    all_names,_=names(namespace)
    if name not in all_names:return ""
    index=all_names.index(name)
    return f"class_scope.globals.borrow_mut().present[{index}]={str(present).lower()};"


def imported(emitter,node):
    if not emitter.model.namespace.globals_observed:return ""
    result=[]
    for value in ast.walk(node):
        binding=emitter.model.namespace.owners.get(emitter.model.unit.ordinal(value))
        if binding is not None and emitter.model.module_owner(binding.owner)and binding.role=="import":
            result.append(store(emitter,value))
    return ''.join(result)


def runtime(namespace):
    from .native import _string
    if not namespace.globals_observed:return ""
    all_names,_=names(namespace)
    linker=getattr(namespace.model,'module_linker',None)
    if linker is None:
        arms=','.join(f'{_string(name)}=>view.0.borrow().present[{index}]'for index,name in enumerate(all_names))
        contains='match key.as_str(){'+arms+',_=>false}'
    else:
        modules=[]
        for module in linker.modules.values():
            choices=[(index,name)for index,name in enumerate(all_names)if name.module_name==module.name]
            arms=','.join(f'{_string(name.python_name)}=>values.present[{index}]'for index,name in choices)
            modules.append(f'{module.number}=>match key.as_str(){{{arms},_=>false}}')
        contains='let values=view.0.borrow();match values.class_module_id{'+','.join(modules)+',_=>false}'
    return ('#[derive(Clone)]\nstruct ClassGlobalsView(Rc<RefCell<ClassGlobals>>);\n'
            'fn class_globals_contains(view:&ClassGlobalsView,key:&NativeText)->bool{'
            +contains+'}\n'
            'fn class_globals_length(view:&ClassGlobalsView)->usize{'
            'view.0.borrow().present.iter().filter(|value|**value).count()}\n')


def comparison(emitter,operator,left,right,node):
    from .native_classes import Expression,ClassUnsupported,domain
    a,b=domain(left.kind),domain(right.kind)
    if a==b=="globals_dict"and isinstance(operator,(ast.Is,ast.IsNot,ast.Eq,ast.NotEq)):
        test=f"Rc::ptr_eq(&{left.code}.0,&{right.code}.0)"
        return f"!({test})"if isinstance(operator,(ast.IsNot,ast.NotEq))else test
    if b!="globals_dict"or not isinstance(operator,(ast.In,ast.NotIn)):return None
    if a=="str":code=f"class_globals_contains(&{right.code},&{left.code})"
    elif a in {"int","int_bool","bool","float","none","bytes","range","function","object"}:code="false"
    elif a in {"list","globals_dict"}:
        name="list"if a=="list"else"dict"
        code=emitter.at(f'Err::<bool,String>("TypeError: cannot use \'{name}\' as a dict key (unhashable type: \'{name}\')".to_owned())',node)
    else:
        raise ClassUnsupported(node,"this globals-dictionary key needs Python hash/equality protocol dispatch; only primitive, function and default-object keys are implemented",types=(("key",left.kind),),proof="dictionary key hashability and equality")
    return f"!({code})"if isinstance(operator,ast.NotIn)else code
