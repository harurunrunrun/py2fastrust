"""Exact modular arithmetic for selected-width machine integer operands."""

HELPERS = r'''
#[inline]
fn native_modular_add(a:u128,b:u128,modulus:u128)->u128 {
    if a>=modulus-b {a-(modulus-b)}else{a+b}
}
#[inline]
fn native_modular_product(a:u128,b:u128,modulus:u128)->u128 {
    if let Some(product)=a.checked_mul(b){return product%modulus;}
    let mut a=a%modulus;let mut b=b;let mut result=0;
    while b!=0 {
        if b&1!=0{result=native_modular_add(result,a,modulus);}
        b>>=1;
        if b!=0{a=native_modular_add(a,a,modulus);}
    }
    result
}
fn native_fixed_modpow(base:NativeInt,exponent:NativeInt,modulus:NativeInt)->Result<NativeInt,String> {
    if modulus==0{return Err("ValueError: pow() 3rd argument cannot be 0".into());}
    let m=modulus.unsigned_abs() as u128;
    let mut b=(base.unsigned_abs() as u128)%m;
    if base<0&&b!=0{b=m-b;}
    if exponent<0 {
        let(mut old_r,mut r)=(m,b);
        let(mut old_t,mut t)=(0,1%m);
        while r!=0 {
            let q=old_r/r;
            let rem=old_r%r;
            let product=native_modular_product(q,t,m);
            let next=if old_t>=product{old_t-product}else{m-(product-old_t)};
            old_r=r;r=rem;old_t=t;t=next;
        }
        if old_r!=1{return Err("ValueError: base is not invertible for the given modulus".into());}
        b=old_t;
    }
    let mut e=exponent.unsigned_abs() as u128;
    let mut result=1%m;
    while e!=0 {
        if e&1!=0{result=native_modular_product(result,b,m);}
        e>>=1;
        if e!=0{b=native_modular_product(b,b,m);}
    }
    Ok(if modulus<0&&result!=0{-((m-result)as NativeInt)}else{result as NativeInt})
}
'''
