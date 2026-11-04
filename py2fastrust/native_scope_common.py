"""Share the three invariant context roots across native module switches.

The finite synchronous renderer certificate is required. This is a sealed
compiler-private layout change: Python values and globals remain unchanged.
Unproved Rust layouts, constructors, field ownership or observers keep their
original native context representation.
"""
import re
from .native_scope_borrows import shared_scope
from .native_scope_views import WITH_MODULE, RUNTIME as VIEW_RUNTIME
from .rust_pruning import _lex, _parse, _Unsupported

STRUCT = ('#[derive(Clone)]struct ClassScope{control:Rc<RefCell<ClassControl>>,'
          'io:Rc<RefCell<ClassIo>>,globals:Rc<RefCell<ClassGlobals>>,'
          'modules:Rc<RefCell<Vec<Option<ClassModuleRef>>>>}')
FIELDS = ('control:Rc::new(RefCell::new(ClassControl{depth:0,limit:1000})),'
          'io:Rc::new(RefCell::new(ClassIo{input:StandardInput::new(),output:String::new()}))')
GROUPED = '''#[derive(Clone)]struct ClassScope{common:Rc<ClassScopeCommon>,globals:Rc<RefCell<ClassGlobals>>}
struct ClassScopeCommon{control:Rc<RefCell<ClassControl>>,io:Rc<RefCell<ClassIo>>,modules:Rc<RefCell<Vec<Option<ClassModuleRef>>>>}
impl std::ops::Deref for ClassScope{type Target=ClassScopeCommon;fn deref(&self)->&ClassScopeCommon{&self.common}}
'''
NEW_WITH_MODULE = 'fn with_module(&self,globals:ClassModuleRef)->Self{Self{common:self.common.clone(),globals}}'
OBSERVERS = {'size_of','size_of_val','size_of_val_raw','align_of','align_of_val',
             'align_of_val_raw','offset_of','addr_of','addr_of_mut','transmute',
             'transmute_copy','strong_count','weak_count','Layout'}
METHODS = {'clone','borrow','borrow_mut','try_borrow','try_borrow_mut','as_ref'}


def _texts(source):
    return [token.text for token in _lex(source)[0]]


def _new(number, builtin=None, grouped=False):
    prefix = ('fn new()->Self{let class_globals=class_module_globals(0);'
              f'let class_modules=Rc::new(RefCell::new(vec![None;{number}]));'
              'class_modules.borrow_mut()[0]=Some(class_globals.clone());')
    if builtin is not None:
        prefix += (f'let class_builtins=class_module_globals({builtin});'
                   'class_builtins.borrow_mut().class_module_status=1;'
                   f'class_modules.borrow_mut()[{builtin}]=Some(class_builtins);')
    fields = FIELDS + ',modules:class_modules'
    value = ('Self{common:Rc::new(ClassScopeCommon{'+fields+'}),globals:class_globals}'
             if grouped else 'Self{'+FIELDS+',globals:class_globals,modules:class_modules}')
    return prefix + value + '}'


def apply(source, model):
    info = {'eligible':False}
    model.scope_common = info
    if not getattr(model,'finite_depth_calls',{}).get('eligible'):
        info['reason']='the finite synchronous source/runtime certificate is unavailable'
        return source
    try:
        tokens, comments, pairs = _lex(source)
        items = _parse(source,tokens,comments,pairs)
        positions={token.start:i for i,token in enumerate(tokens)}
        impl_positions=set()
        for item in items:
            if item.kind=='impl':
                impl_positions.add(next(i for i in range(positions[item.start],len(tokens))
                                        if tokens[i].text=='impl'))
        if any(token.text=='impl' and i not in impl_positions
               and (not i or tokens[i-1].text not in {':','>','<',','})
               for i,token in enumerate(tokens)):
            raise _Unsupported('a nested or unresolved Rust implementation is retained')
        if not shared_scope(tokens,pairs,items):
            raise _Unsupported('the context shared-field or destructor proof is unavailable')
        if any(token.text == 'ClassScopeCommon' for token in tokens):
            raise _Unsupported('a common context layout is already present')
        scope = next(item for item in items if item.kind=='struct' and item.name=='ClassScope')
        if _texts(source[scope.start:scope.end]) != _texts(STRUCT):
            raise _Unsupported('the context is not the exact Clone-only four-root layout')
        view_tokens,view_comments,view_pairs=_lex(VIEW_RUNTIME)
        view_items=_parse(VIEW_RUNTIME,view_tokens,view_comments,view_pairs)
        canonical_deref=next(item for item in view_items if item.kind=='impl'
                             and item.trait and item.owner=='ClassScopeView')
        view_derefs=[item for item in items if item.kind=='impl' and item.trait
                     and item.owner=='ClassScopeView' and 'ClassScope' in item.references]
        for item in view_derefs:
            if (_texts(source[item.start:item.end])
                    != _texts(VIEW_RUNTIME[canonical_deref.start:canonical_deref.end])):
                raise _Unsupported('an execution-context view has an unknown trait implementation')
        # Include local aliases: the item parser deliberately keeps function
        # bodies opaque, but a local alias can still construct the old struct.
        aliases=[]
        for i,token in enumerate(tokens):
            if token.text not in {'type','use'}:continue
            cursor=i+1
            while cursor<len(tokens) and tokens[cursor].text!=';':
                cursor=pairs[cursor]+1 if tokens[cursor].text in {'(','[','{'} else cursor+1
            if cursor==len(tokens):
                raise _Unsupported('an execution-context alias declaration is unproved')
            refs={part.text for part in tokens[i+1:cursor] if part.kind=='identifier'}
            allowed_target=token.text=='type' and any(item.start<=token.start<item.end for item in view_derefs)
            if allowed_target:continue
            if 'ClassScope' in refs:
                raise _Unsupported('an execution-context alias is retained')
            aliases.append((token.text,tokens[i+1].text,refs))
        protected={'ClassScope','ClassControl','ClassIo','ClassGlobals','StandardInput'}
        while True:
            found=protected|{name for kind,name,refs in aliases if kind=='type' and refs & protected}
            if found==protected:break
            protected=found
        if any(kind=='use' and refs & protected for kind,name,refs in aliases):
            raise _Unsupported('an execution-context root payload has a use alias')
        if any(item.kind=='impl' and item.trait and (item.owner in protected
               or not item.owner_nominal and ('Drop' in item.references or item.references & protected))
               for item in items):
            raise _Unsupported('an execution-context or root payload has an unknown trait implementation')
        methods=[]
        for item in items:
            if item.kind=='impl' and not item.trait and item.owner=='ClassScope':
                if _texts(source[item.start:item.end])[:3] != ['impl','ClassScope','{']:
                    raise _Unsupported('the execution-context implementation header is not canonical')
                methods.extend(item.children)
        if any(item.kind!='fn' or item.name not in {'new','with_module','with_module_view'} for item in methods):
            raise _Unsupported('an unknown execution-context method is retained')
        constructors=[item for item in methods if item.name=='new']
        switches=[item for item in methods if item.name=='with_module']
        if len(constructors)!=1 or len(switches)!=1:
            raise _Unsupported('the canonical context constructors are absent or ambiguous')
        views=[item for item in methods if item.name=='with_module_view']
        if len(views)>1:
            raise _Unsupported('the module-context view method is ambiguous')
        if views:
            canonical=next(child for item in view_items
                           if item.kind=='impl' and not item.trait and item.owner=='ClassScope'
                           for child in item.children if child.name=='with_module_view')
            if (_texts(source[views[0].start:views[0].end])
                    != _texts(VIEW_RUNTIME[canonical.start:canonical.end])):
                raise _Unsupported('the module-context view method is not canonical')
        new, switch = constructors[0],switches[0]
        if _texts(source[switch.start:switch.end]) != _texts(WITH_MODULE):
            raise _Unsupported('the module-context constructor is not canonical')
        new_tokens=_texts(source[new.start:new.end])
        counts=[new_tokens[i+5] for i in range(len(new_tokens)-5)
                if new_tokens[i:i+5]==['vec','!','[','None',';']]
        if len(counts)!=1 or not counts[0].isdigit() or int(counts[0])<1:
            raise _Unsupported('the root module-cache construction is not canonical')
        number=int(counts[0]);builtin=None
        if 'class_builtins' in new_tokens:
            matches=[new_tokens[i+5] for i in range(len(new_tokens)-5)
                     if new_tokens[i:i+5]==['let','class_builtins','=','class_module_globals','(']]
            if len(matches)!=1 or not matches[0].isdigit() or not 0<=int(matches[0])<number:
                raise _Unsupported('the canonical builtins namespace initialization is unproved')
            builtin=int(matches[0])
        if new_tokens != _texts(_new(number,builtin)):
            raise _Unsupported('the root context constructor is not canonical')
        for i,token in enumerate(tokens):
            if token.text in OBSERVERS or token.text=='ptr' and i+1<len(tokens) and tokens[i+1].text==':':
                raise _Unsupported('a context layout, address or reference-count observer is retained')
            if token.kind=='literal' and re.search(r':[^"}]*p["}]',token.text):
                raise _Unsupported('a pointer-format observer is retained')
            if token.text=='as' and i+1<len(tokens) and tokens[i+1].text=='*':
                raise _Unsupported('a raw pointer cast is retained')
            if token.text=='ClassScope' and i+1<len(tokens):
                before=[part.text for part in tokens[max(0,i-3):i]]
                return_type=before[-2:]==['-','>'] or before[-3:]==['-','>','&']
                if (tokens[i+1].text=='{' and not(scope.start<=token.start<scope.end)
                        and (not i or tokens[i-1].text!='impl') and not return_type):
                    raise _Unsupported('an alternate context construction or destructuring is retained')
                if i and tokens[i-1].text=='<':
                    raise _Unsupported('an opaque generic context type use is retained')
            if token.text in {'control','io','modules'} and i and tokens[i-1].text=='.':
                if (i+3>=len(tokens) or tokens[i+1].text!='.'
                        or tokens[i+2].text not in METHODS or tokens[i+3].text!='('):
                    raise _Unsupported('a context root is moved, replaced, borrowed mutably or observed opaquely')
        edits=[(scope.start,scope.end,GROUPED),(new.start,new.end,_new(number,builtin,True)),
               (switch.start,switch.end,NEW_WITH_MODULE)]
        for start,end,replacement in sorted(edits,reverse=True):
            source=source[:start]+replacement+source[end:]
        info.update(eligible=True,module_cache_slots=number,builtins_slot=builtin,
                    common_roots=['control','io','modules'],actual_globals_identity_preserved=True)
        return source
    except (_Unsupported,StopIteration,KeyError,IndexError) as error:
        info['reason']=str(error)or type(error).__name__
        return source
