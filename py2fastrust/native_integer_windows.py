"""Extract bounded integer windows without materializing a shifted magnitude."""
import ast


def split(node):
    if not isinstance(node,ast.BinOp)or not isinstance(node.op,ast.BitAnd):return None
    for shifted,mask in ((node.left,node.right),(node.right,node.left)):
        if (isinstance(shifted,ast.BinOp)and isinstance(shifted.op,ast.RShift)
                and isinstance(mask,ast.Constant)and type(mask.value)is int
                and 0<=mask.value<1<<127):
            return shifted,mask.value
    return None


def frame(emitter,node):
    if emitter.model.integer!='bigint':return None
    selected=split(node)
    if selected is None:return None
    shifted,mask=selected
    if emitter.kind(shifted.left)!='int'or emitter.kind(shifted.right)not in {'int','bool'}:return None
    from .native import _Expression
    from .native_scalar_effects import scalar_rhs
    value=shifted.left
    if isinstance(value,ast.Subscript)and scalar_rhs(shifted.right,emitter.kind):
        setup,reference=emitter.reference(value)
        if reference[0]=='index'and reference[3]=='int':
            _,owner,index,_=reference
            offset=emitter.fresh()
            checked=emitter.at(f'class_index(&({emitter.number(index)}),{owner.code}.borrow().len())',value)
            more,count=emitter.capture(emitter.expression(shifted.right))
            code=emitter.at(f'{owner.code}.borrow()[{offset}].shr_mask(&({emitter.number(count)}),{mask}_u128)',shifted)
            result=emitter.fresh()
            return _Expression('{'+setup+f'let {offset}={checked};'+more+f'let {result}={code};{result}'+'}','int')
    setup,operand=emitter.capture(emitter.expression(value))
    more,count=emitter.capture(emitter.expression(shifted.right))
    code=emitter.at(f'({operand.code}).shr_mask(&({emitter.number(count)}),{mask}_u128)',shifted)
    return _Expression('{'+setup+more+code+'}','int')


def direct(generator,node,environment):
    selected=split(node)
    if selected is None:return None
    shifted,mask=selected
    left=generator.expression(shifted.left,environment)
    count=generator.expression(shifted.right,environment)
    if left.kind!='int'or count.kind not in {'int','bool'}:return None
    from .native import _Expression
    code=generator.at(f'({left.code}).shr_mask(&({generator.number(count)}),{mask}_u128)',shifted)
    return _Expression(code,'int')
