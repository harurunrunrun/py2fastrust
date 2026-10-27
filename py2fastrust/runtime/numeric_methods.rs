// Scalar conversion methods use the same integer normalization as arithmetic.
fn numeric_float_hex(value: f64) -> String {
    if value.is_nan() {return "nan".into();}
    let sign=if value.is_sign_negative(){"-"}else{""};
    if value.is_infinite(){return format!("{sign}inf");}
    if value==0.0{return format!("{sign}0x0.0p+0");}
    let bits=value.to_bits();let exponent=((bits>>52)&2047) as i32;
    let fraction=bits&((1u64<<52)-1);
    if exponent==0 {format!("{sign}0x0.{fraction:013x}p-1022")}
    else {format!("{sign}0x1.{fraction:013x}p{:+}",exponent-1023)}
}

fn numeric_float_fromhex(source: &str) -> PyResult<f64> {
    let invalid=||pyerr("ValueError","invalid hexadecimal floating-point string");
    let mut source=source.trim_matches(|c:char|c.is_ascii_whitespace());
    let negative=source.starts_with('-');
    if source.starts_with(['+','-']){source=&source[1..];}
    match source.to_ascii_lowercase().as_str(){
        "inf"|"infinity"=>return Ok(if negative{f64::NEG_INFINITY}else{f64::INFINITY}),
        "nan"=>return Ok(f64::from_bits((u64::from(negative)<<63)|0x7ff8000000000000)),_=>{},
    }
    if source.starts_with("0x")||source.starts_with("0X"){source=&source[2..];}
    let mut exponent=0i128;
    if let Some(index)=source.find(['p','P']) {
        let mut text=&source[index+1..];source=&source[..index];
        let neg=text.starts_with('-');if text.starts_with(['+','-']){text=&text[1..];}
        if text.is_empty()||!text.bytes().all(|b|b.is_ascii_digit()){return Err(invalid());}
        for digit in text.bytes(){exponent=exponent.saturating_mul(10).saturating_add((digit-b'0') as i128);}
        if neg{exponent=exponent.saturating_neg();}
    }
    let mut digits=Vec::new();let mut fractional=false;let mut fraction_count=0usize;
    for byte in source.bytes(){
        if byte==b'.'&&!fractional{fractional=true;continue;}
        let digit=match byte{b'0'..=b'9'=>byte-b'0',b'a'..=b'f'=>byte-b'a'+10,b'A'..=b'F'=>byte-b'A'+10,_=>return Err(invalid())};
        digits.push(digit);if fractional{fraction_count+=1;}
    }
    if digits.is_empty(){return Err(invalid());}
    let mut limbs=Vec::new();
    for chunk in digits.rchunks(8){let mut limb=0u32;for &d in chunk{limb=(limb<<4)|d as u32;}limbs.push(limb);}
    Int::trim(&mut limbs);
    if limbs.is_empty(){return Ok(f64::from_bits(u64::from(negative)<<63));}
    exponent=exponent.saturating_sub((fraction_count as i128).saturating_mul(4));
    let bits=Int::nat_bits(&limbs);
    let top_exponent=exponent.saturating_add(bits as i128-1);
    if top_exponent>1023{return Err(pyerr("OverflowError","hexadecimal value too large to represent as a float"));}
    if top_exponent< -1075{return Ok(f64::from_bits(u64::from(negative)<<63));}
    // Keep eleven guard bits beyond a binary64 mantissa and a sticky bit.
    // This bounds exact ratio conversion even for very long hexadecimal input.
    if bits>64 {
        let shift=bits-64;let whole=shift/32;let rest=shift%32;
        let sticky=limbs[..whole].iter().any(|&d|d!=0)
            ||(rest!=0&&(limbs[whole]&((1u32<<rest)-1))!=0);
        limbs=Int::nat_shr(&limbs,shift);if sticky{limbs[0]|=1;}
        exponent+=shift as i128;
    }
    let (numerator,denominator)=if exponent>=0{
        (Int::exact_parts(negative,Int::nat_shl(&limbs,exponent as usize)),Int::exact_small(1))
    }else{
        (Int::exact_parts(negative,limbs),Int::exact_parts(false,Int::nat_shl(&[1],(-exponent) as usize)))
    };
    numerator.ratio(&denominator).map_err(int_error)
}

impl Runtime {
    fn numeric_getattr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let owner=match &value {
            Value::Int(_)|Value::Bool(_)=>"int",Value::Float(_)=>"float",
            Value::Builtin(owner)if ["int","bool"].contains(&owner.as_str())=>"int",
            Value::Builtin(owner)if owner=="float"=>"float",_=>return None,
        };
        let names=if owner=="int"{&["to_bytes","from_bytes","as_integer_ratio","is_integer"][..]}
            else{&["hex","fromhex","from_number","as_integer_ratio","is_integer"][..]};
        if !names.contains(&name){return None;}
        let class=match &value{Value::Builtin(_)=>value.clone(),_=>self.native_receiver_class(&value)};
        let descriptor=self.class_attribute_lookup(&class,name)?;
        let instance=if matches!(&value,Value::Builtin(_)){None}else{Some(value)};
        Some(self.bind_descriptor(descriptor,instance,class))
    }

    fn numeric_descriptor_call(&mut self, owner: &str, name: &str, receiver: Value,
                               args: Vec<Value>, kwargs: KeywordArgs) -> Option<PyResult<Value>> {
        if !((owner=="int"&&["to_bytes","from_bytes","as_integer_ratio","is_integer"].contains(&name))
            ||(owner=="float"&&["hex","fromhex","from_number","as_integer_ratio","is_integer"].contains(&name))){return None;}
        let mut roots=vec![receiver.clone()];roots.extend(args.iter().cloned());
        roots.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        Some(self.view_rooted(roots,|runtime,root|{
            if name=="to_bytes" {
                if args.len()>2{return Err(pyerr("TypeError","to_bytes() takes at most 2 positional arguments"));}
                let values=codec_bind("to_bytes",args,kwargs,&["length","byteorder","signed"])?;
                let length=values[0].as_ref().map(|v|runtime.as_int(v)).transpose()?.unwrap_or_else(||Int::exact_small(1));
                let order=codec_argument(runtime,values[1].as_ref(),"big","byteorder")?;
                let signed=values[2].as_ref().map(|v|runtime.truth(v)).transpose()?.unwrap_or(false);
                if length.is_negative(){return Err(pyerr("ValueError","length argument must be non-negative"));}
                let length=length.to_usize().filter(|&n|n<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","cannot fit length into an index-sized integer"))?;
                if order!="big"&&order!="little"{return Err(pyerr("ValueError","byteorder must be either 'little' or 'big'"));}
                let number=runtime.as_int(&receiver)?;
                if number.is_negative()&&!signed{return Err(pyerr("OverflowError","can't convert negative int to unsigned"));}
                let magnitude=if number.is_negative(){Int::exact_parts(false,number.magnitude().into_owned()).exact_add(&Int::exact_small(-1))}else{number.clone()};
                let bits=length.checked_mul(8).ok_or_else(||pyerr("OverflowError","requested byte length is too large"))?;
                let limit=if signed{bits.saturating_sub(1)}else{bits};
                if (length==0&&!number.is_zero())||magnitude.bit_length()>limit{return Err(pyerr("OverflowError","int too big to convert"));}
                let digits=magnitude.magnitude();let mut output=Vec::new();
                output.try_reserve_exact(length).map_err(|_|pyerr("MemoryError","cannot allocate integer bytes"))?;
                output.resize(length,0);
                for (index,byte) in output.iter_mut().enumerate(){
                    *byte=digits.get(index/4).map(|digit|(digit>>((index%4)*8)) as u8).unwrap_or(0);
                    if number.is_negative(){*byte=!*byte;}
                }
                if order=="big"{output.reverse();}
                return Ok(Value::Bytes(output.into()));
            }
            if name=="from_bytes" {
                if args.len()>2{return Err(pyerr("TypeError","from_bytes() takes at most 2 positional arguments"));}
                let mut values=codec_bind("from_bytes",args,kwargs,&["bytes","byteorder","signed"])?;
                let source=values[0].take().ok_or_else(||pyerr("TypeError","from_bytes() missing required argument 'bytes'"))?;
                let order=codec_argument(runtime,values[1].as_ref(),"big","byteorder")?;
                let signed=values[2].as_ref().map(|v|runtime.truth(v)).transpose()?.unwrap_or(false);
                if order!="big"&&order!="little"{return Err(pyerr("ValueError","byteorder must be either 'little' or 'big'"));}
                let mut data=match &source{Value::Bytes(value)=>value.to_vec(),_=>{
                    match runtime.special_method(source.clone(),"__bytes__") {
                        Ok(method)=>{
                            let value=runtime.call(method,Vec::new(),Vec::new(),None)?;
                            let value=runtime.native_payload(&value).unwrap_or(value);
                            match value{Value::Bytes(value)=>value.to_vec(),_=>return Err(pyerr("TypeError","__bytes__ returned non-bytes"))}
                        },
                        Err(error)if runtime.missing_special_method(&source,"__bytes__",&error)=>{
                            let iterator=runtime.iter(source.clone())?;runtime.roots[root].push(iterator.clone());
                            runtime.assoc_length_hint(vec![source],Vec::new())?;
                            let mut output=Vec::new();
                            while let Some(value)=runtime.next(iterator.clone())?{
                                runtime.roots[root].push(value.clone());
                                let byte=runtime.as_int(&value)?.to_usize().filter(|&n|n<=255).ok_or_else(||pyerr("ValueError","bytes must be in range(0, 256)"))?;
                                output.push(byte as u8);runtime.roots[root].pop();
                            }
                            output
                        },Err(error)=>return Err(error),
                    }
                }};
                if order=="big"{data.reverse();}
                let negative=signed&&data.last().is_some_and(|b|b&128!=0);
                if negative{for byte in &mut data{*byte=!*byte;}}
                let mut digits=Vec::new();for chunk in data.chunks(4){let mut digit=0u32;for (i,&byte) in chunk.iter().enumerate(){digit|=(byte as u32)<<(8*i);}digits.push(digit);}
                let mut number=Int::exact_parts(false,digits);if negative{number=number.exact_add(&Int::exact_small(1)).exact_neg();}
                let value=Value::Int(number.normalized().into());
                if Self::same_type(&receiver,&Value::Builtin("int".into())){return Ok(value);}
                return runtime.call(receiver,vec![value],Vec::new(),None);
            }
            if name=="fromhex"||name=="from_number" {
                if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError",format!("{name}() takes exactly one positional argument")));}
                let value=if name=="fromhex" {
                    let source=runtime.native_payload(&args[0]).unwrap_or_else(||args[0].clone());
                    let Value::Str(source)=source else{return Err(pyerr("TypeError","fromhex() argument must be str"));};
                    Value::Float(numeric_float_fromhex(&source)?.into())
                }else{
                    if matches!(&args[0],Value::Str(_)|Value::Bytes(_)){return Err(pyerr("TypeError","from_number() requires a real number"));}
                    if matches!(&args[0],Value::Float(_)){args[0].clone()}else{Value::Float(runtime.math_float(&args[0])?.into())}
                };
                if Self::same_type(&receiver,&Value::Builtin("float".into())){return Ok(value);}
                return runtime.call(receiver,vec![value],Vec::new(),None);
            }
            if !args.is_empty()||!kwargs.is_empty(){return Err(pyerr("TypeError",format!("{name}() takes no arguments")));}
            let payload=runtime.native_payload(&receiver).unwrap_or(receiver);
            if owner=="int"{
                if name=="is_integer"{return Ok(Value::Bool(true));}
                let integer=runtime.as_int(&payload)?;
                return Ok(runtime.obj_value(Object::Tuple(vec![Value::Int(integer.into()),Value::Int(Int::from_i128(1).into())])));
            }
            let Value::Float(value)=payload else{return Err(pyerr("TypeError","descriptor requires a float"));};
            if name=="hex"{return Ok(Value::Str(numeric_float_hex(*value).into()));}
            if name=="is_integer"{return Ok(Value::Bool(value.is_finite()&&value.fract()==0.0));}
            if value.is_nan(){return Err(pyerr("ValueError","cannot convert NaN to integer ratio"));}
            if value.is_infinite(){return Err(pyerr("OverflowError","cannot convert Infinity to integer ratio"));}
            let bits=value.to_bits();let e=((bits>>52)&2047) as i32;
            let mut m=(bits&((1u64<<52)-1))|if e==0{0}else{1u64<<52};
            let mut exponent=if e==0{-1074}else{e-1023-52};
            if m==0{exponent=0;}else if exponent<0{let shift=m.trailing_zeros().min((-exponent) as u32);m>>=shift;exponent+=shift as i32;}
            let limbs=Int::exact_small(m as i128).magnitude().into_owned();
            let numerator=Int::parts(bits>>63!=0,if exponent>0{Int::nat_shl(&limbs,exponent as usize)}else{limbs});
            let denominator=Int::parts(false,if exponent<0{Int::nat_shl(&[1],(-exponent) as usize)}else{vec![1]});
            Ok(runtime.obj_value(Object::Tuple(vec![Value::Int(numerator.into()),Value::Int(denominator.into())])))
        }))
    }
}
