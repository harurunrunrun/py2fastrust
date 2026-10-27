"""Render guarded unit-stride regions from pure affine/effect facts."""
from dataclasses import dataclass
from .native import _Binding,_Expression


def integer(value):
    value=int(value)
    return 'i128::MIN'if value==-(1<<127)else f'{value}_i128'


@dataclass
class Guard:
    prefix:str
    name:str
    count:str
    counter:str
    spans:dict


class Renderer:
    def __init__(self,scope,used):
        self.scope=scope;self.g=scope.generator;self.used=used
        self.lines=[];self.prefix=[];self.leaves={};self.spans={}
        self.capture=scope.stream.range_capture
        self.lower=f'({self.capture.lower}) as i128';self.upper=f'({self.capture.upper}) as i128'
        self.last=self.temporary();self.count=self.temporary()
        self.lines+=[f'let {self.last}=({self.upper}).checked_sub(1)?;',
                     f'let {self.count}=usize::try_from(({self.upper}).checked_sub({self.lower})?).ok()?;']

    def temporary(self,prefix='native_region_value'):
        return prefix+'_'+self.g.temporary().rsplit('_',1)[-1]

    def checked(self,code):
        name=self.temporary();self.lines.append(f'let {name}={code};')
        if self.g.bits==64:self.lines.append(f'i64::try_from({name}).ok()?;')
        return name

    def term(self,term):
        op=term.operation
        if op=='induction':return self.lower,self.last
        if op=='literal':
            value=integer(term.value);return value,value
        if op=='invariant':
            key=('number',term.value)
            if key not in self.leaves:
                binding=self.scope.environment.get(term.value)
                if not isinstance(binding,_Binding) or binding.kind not in {'int','bool','int_bool'}:raise ValueError('invariant binding changed')
                name=self.temporary('native_region_capture')
                code=self.g.number(_Expression(binding.slot,binding.kind))
                self.prefix.append(f'let {name}=({code}) as i128;');self.leaves[key]=name
            return self.leaves[key],self.leaves[key]
        if op=='owner_length':
            view=self.scope.named_views[term.value];code=f'({view}.len() as i128)';return code,code
        if op=='len':return self.term(term.operands[0])
        pairs=[self.term(child)for child in term.operands]
        if op=='UAdd':return pairs[0]
        if op=='USub':return tuple(self.checked(f'({point}).checked_neg()?')for point in pairs[0])
        method={'Add':'checked_add','Sub':'checked_sub','Mult':'checked_mul'}[op]
        return tuple(self.checked(f'({left}).{method}({right})?')for left,right in zip(*pairs))

    def render(self):
        ranges=[]
        for ordinal,access in sorted(self.used.items()):
            first,last=self.term(access.affine)
            begin,end=self.temporary(),self.temporary()
            view=self.scope.named_views[access.owner.name]
            self.lines+=[f'let {begin}=usize::try_from({first}).ok()?;',
                         f'let {end}={begin}.checked_add({self.count})?;',
                         f'if {end}>{view}.len(){{return None;}}',
                         f'if ({last}).checked_sub({first})? != ({self.count} as i128)-1{{return None;}}']
            ranges.append(f'{begin}..{end}')
            self.spans[ordinal]=self.temporary('native_region_span')
        count=len(ranges);name=self.temporary('native_region_guard');counter=self.temporary('native_region_index')
        empty=','.join('0..0'for _ in ranges)
        code=(f'let {name}=(||->Option<(usize,[std::ops::Range<usize>;{count}])>{{\n'
              f'if ({self.upper})<=({self.lower}){{return Some((0,[{empty}]));}}\n'
              +'\n'.join(self.lines)+f'\nSome(({self.count},['+','.join(ranges)+']))\n})();')
        return Guard('\n'.join(self.prefix)+'\n'+code,name,self.count,counter,self.spans)


def build(scope,used):
    try:return Renderer(scope,used).render()
    except (KeyError,ValueError):return None
