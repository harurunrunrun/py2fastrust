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
    setup:list=field(default_factory=list)
    views:dict=field(default_factory=dict)
    slots:dict=field(default_factory=dict)

    def __post_init__(self):
        if self.fact is None:return
        for owner in self.fact.readonly_owners:
            binding=self.environment.get(owner.name)
            if not isinstance(binding,_Binding) or binding.kind!='str':continue
            name=self.generator.temporary()
            self.setup.append(f'let {name}:&str={binding.slot}.as_str();')
            self.slots[binding.slot]=name
            for index in owner.read_sites:self.views[index]=name

    def __enter__(self):
        stack=getattr(self.generator,'region_scopes',None)
        if stack is None:stack=[];self.generator.region_scopes=stack
        stack.append(self)
        return self

    def __exit__(self,*_):self.generator.region_scopes.pop()

    def capture(self):return '\n'.join(self.setup)


def scope(g,key,environment):
    return RegionScope(g,getattr(g,'range_facts',{}).get(key),environment)


def owner_view(g,node):
    ordinal=site(g,node)
    for current in reversed(getattr(g,'region_scopes',())):
        if ordinal in current.views:return current.views[ordinal]
    return None


def char_projection(g,node,checked_code):
    # A native str index produces exactly one codepoint. The checked read stays
    # inside this projection and is evaluated only if the operand selects it.
    if g.string_mode=='ascii':
        return f'(({checked_code}).as_bytes()[0] as u32)'
    return f'(({checked_code}).chars().next().unwrap() as u32)'


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
