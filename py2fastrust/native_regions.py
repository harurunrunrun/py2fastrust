"""Consume pure owner/affine facts without probing or executing source code."""
import ast
from dataclasses import dataclass,field
from .native import _Binding,_Expression


def site(g,node):
    unit=getattr(g,'source_unit',None)
    if unit is None:return None
    try:return unit.ordinal(node)
    except KeyError:return None


@dataclass
class RegionScope:
    generator:object
    fact:object
    environment:object
    stream:object=None
    setup:list=field(default_factory=list)
    views:dict=field(default_factory=dict)
    slots:dict=field(default_factory=dict)
    named_views:dict=field(default_factory=dict)
    reads:dict=field(default_factory=dict)
    child_versioned:bool=False

    def __post_init__(self):
        if self.fact is None:return
        for owner in self.fact.readonly_owners:
            binding=self.environment.get(owner.name)
            if not isinstance(binding,_Binding) or binding.kind!='str':continue
            name=self.generator.temporary()
            self.setup.append(f'let {name}:&str={binding.slot}.as_str();')
            self.slots[binding.slot]=name
            self.named_views[owner.name]=name
            for index in owner.read_sites:self.views[index]=name

    def __enter__(self):
        stack=getattr(self.generator,'region_scopes',None)
        if stack is None:stack=[];self.generator.region_scopes=stack
        stack.append(self)
        return self

    def __exit__(self,*_):self.generator.region_scopes.pop()

    def capture(self):return '\n'.join(self.setup)

    def project(self,node,checked):
        if (self.fact is None or self.fact.domain is None or self.stream is None
                or self.generator.bits not in {64,128} or self.generator.string_mode!='ascii'
                or self.stream.range_capture is None
                or self.stream.range_capture.call_site!=self.fact.domain.call_site):return None
        unit=self.generator.source_unit
        if any(effect.kind=='control' and unit.nodes[effect.site].kind=='Return' for effect in self.fact.effects):return None
        ordinal=site(self.generator,node)
        access=next((access for access in self.fact.accesses if access.index_site==ordinal),None)
        if access is None or access.owner.name not in self.named_views:return None
        token='\0native_region_char_'+self.generator.temporary().rsplit('_',1)[-1]+'\0'
        self.reads[token]=(access,checked)
        return token

    def emit(self,stream,action,caller,line,continue_label=None):
        used={access.index_site:access for token,(access,_) in self.reads.items()if token in action}
        checked=action
        for token,(_,code) in self.reads.items():checked=checked.replace(token,code)
        original=stream.emit(checked,caller,line,continue_label)
        prefix=self.capture()+'\n'
        if not used or self.child_versioned or len(action)>32768 or len(used)>16:return prefix+original
        from .native_region_guards import build
        guard=build(self,used)
        if guard is None:return prefix+original
        for parent in getattr(self.generator,"region_scopes",()):
            if parent is not self:parent.child_versioned=True
        value=stream.values[0].code
        label=f"'{continue_label}: "if continue_label else''
        counter_count=guard.count+'_selected'
        span_names=[guard.spans[ordinal]for ordinal in sorted(used)]
        ranges=[name+'_range'for name in span_names]
        items={ordinal:guard.spans[ordinal]+'_item'for ordinal in used}
        fast=action
        for token,(access,_)in self.reads.items():
            if access.index_site in items:
                fast=fast.replace(token,f'(*{items[access.index_site]} as u32)')
        captures=[]
        for ordinal,name,span in zip(sorted(used),span_names,ranges):
            view=self.named_views[used[ordinal].owner.name]
            captures.append(f'let {name}:&[u8]=&{view}.as_bytes()[{span}];')
            captures.append(f'debug_assert_eq!({name}.len(),{counter_count});')
        # Guards prove all spans have the original domain length. Encoding
        # traversal as zip carries this relation even if LLVM outlines guards.
        # Forming immutable references ahead of a conditional is nonraising.
        iterator=span_names[0]+'.iter()'
        pattern=items[sorted(used)[0]]
        for ordinal,span in zip(sorted(used)[1:],span_names[1:]):
            iterator=f'({iterator}).zip({span}.iter())'
            pattern=f'({pattern},{items[ordinal]})'
        loop=(f'{label}for ({guard.counter},{pattern}) in ({iterator}).enumerate(){{\n'
              f'let {value}=({stream.range_capture.lower}).wrapping_add({guard.counter} as NativeInt);\n{fast}\n}}')
        return (prefix+guard.prefix+f'\nif let Some(({counter_count},['+','.join(ranges)+f']))={guard.name}{{\n'
                +'\n'.join(captures)+'\n'+loop+'\n}else{\n'+original+'\n}')


def scope(g,key,environment,stream=None):
    return RegionScope(g,getattr(g,'range_facts',{}).get(key),environment,stream)


def owner_view(g,node):
    ordinal=site(g,node)
    for current in reversed(getattr(g,'region_scopes',())):
        if ordinal in current.views:return current.views[ordinal]
    return None


def char_projection(g,node,checked_code,checked_char_code=None):
    # A native str index produces exactly one codepoint. The checked read stays
    # inside this projection and is evaluated only if the operand selects it.
    checked=checked_char_code or (f'(({checked_code}).as_bytes()[0] as u32)' if g.string_mode=='ascii' else
             f'(({checked_code}).chars().next().unwrap() as u32)')
    for current in reversed(getattr(g,'region_scopes',())):
        token=current.project(node,checked)
        if token is not None:return token
    return checked


def literal_char(value):
    return f'{ord(value)}_u32'if isinstance(value,str) and len(value)==1 else None


def compare_characters(g,node,values):
    symbols={ast.Eq:'==',ast.NotEq:'!=',ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>='}
    if not all(value.kind=='str'and value.char_code is not None for value in values):return None
    if not all(type(operator)in symbols for operator in node.ops):return None
    names=[g.temporary()for _ in values];tail='true'
    for index in reversed(range(len(node.ops))):
        test=f'{names[index]} {symbols[type(node.ops[index])]} {names[index+1]}'
        tail=f'{{let {names[index+1]}:u32={values[index+1].char_code};({test})&&({tail})}}'
    return _Expression(f'{{let {names[0]}:u32={values[0].char_code};{tail}}}','bool')


def owner_view_for_slot(g,slot):
    for current in reversed(getattr(g,'region_scopes',())):
        if slot in current.slots:return current.slots[slot]
    return None
