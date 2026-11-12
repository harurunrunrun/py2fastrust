"""Borrow scalar integer operands after proving the RHS cannot change storage."""
import ast


def emit(emitter,node,setup,reference,old_kind):
    from .native_scalar_effects import scalar_rhs
    if reference[0]!='index' or old_kind!='int':return None
    _,owner,index,stored=reference
    operators={ast.BitAnd:0,ast.BitOr:1,ast.BitXor:2}
    opcode=operators.get(type(node.op))
    right=node.value
    if (opcode is None or stored!='int' or emitter.kind(node.target)!='int'
            or not isinstance(right,ast.Subscript) or emitter.kind(right)!='int'
            or not isinstance(right.value,ast.Name)
            or not scalar_rhs(right.slice,emitter.kind)):
        return None
    # Physical vector/record/region places have their own storage contracts.
    # Only the shared typed-list representation can use these Rc loans.
    rhs_setup,rhs_reference=emitter.reference(right)
    if rhs_reference[0]!='index' or rhs_reference[3]!='int':return None
    _,rhs_owner,rhs_index,_=rhs_reference
    left_offset,right_offset=emitter.fresh(),emitter.fresh()
    left_check=emitter.at(f'class_index(&({emitter.number(index)}),{owner.code}.borrow().len())',node.target)
    right_check=emitter.at(f'class_index(&({emitter.number(rhs_index)}),{rhs_owner.code}.borrow().len())',right)
    # The old LHS get must succeed before the RHS owner or index is evaluated.
    # Neither RHS binding reads nor the closed scalar index can resize/rebind
    # either list. No Python call runs while an element is borrowed.
    emitter.model.integer_list_bitplaces=True
    return ('{'+setup+f'let {left_offset}={left_check};'+rhs_setup
            +f'let {right_offset}={right_check};'
            +f'class_list_integer_bitop(&{owner.code},{left_offset},&{rhs_owner.code},{right_offset},{opcode});'+'}')


def runtime(model):
    if not getattr(model,'integer_list_bitplaces',False):return ''
    update=('left.bitop_assign(right,operation);'if model.integer=='bigint'else
            '*left=match operation{0=>*left & *right,1=>*left | *right,_=>*left ^ *right};')
    zero='Int::from_i128(0)'if model.integer=='bigint'else'0'
    return '''
#[inline]
fn class_integer_bitop_assign(left:&mut NativeInt,right:&NativeInt,operation:u8){'''+update+'''}
#[inline]
fn class_list_integer_bitop(left:&ClassList<NativeInt>,i:usize,right:&ClassList<NativeInt>,j:usize,operation:u8){
    if Rc::ptr_eq(left,right){
        let mut values=left.borrow_mut();
        if i==j {if operation==2 {values[i]='''+zero+''';} return;}
        if i<j {let (a,b)=values.split_at_mut(j);class_integer_bitop_assign(&mut a[i],&b[0],operation);}
        else {let (a,b)=values.split_at_mut(i);class_integer_bitop_assign(&mut b[0],&a[j],operation);}
    }else{
        let right=right.borrow();let mut left=left.borrow_mut();
        class_integer_bitop_assign(&mut left[i],&right[j],operation);
    }
}
'''
