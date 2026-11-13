"""Concrete native-C numeric buffers, without external crates or Python state."""
from .native_arrays import ArrayType


def runtime(model):
    codes=sorted(getattr(model,'native_array_codes',()))
    if not codes:return ''
    number='count.to_i128()'if model.integer=='bigint'else'Some(*count as i128)'
    result=['fn class_array_count(count:&NativeInt)->Result<usize,String>{let count='+number+'.ok_or_else(||"OverflowError: cannot fit \'int\' into an index-sized integer".to_owned())?;if count<isize::MIN as i128||count>isize::MAX as i128{return Err("OverflowError: cannot fit \'int\' into an index-sized integer".to_owned());}Ok(if count<0{0}else{count as usize})}']
    for code in codes:
        kind=ArrayType(code);raw=kind.raw;prefix='class_array_'+str(ord(code))
        integer='value.to_i128()'if model.integer=='bigint'else'Some(*value as i128)'
        negative='value.is_negative()'if model.integer=='bigint'else'*value<0'
        if code not in 'fd':
            unsigned=code in 'ILQ'
            extract=('int too big to convert'if code in 'qQ'else'Python int too large to convert to C unsigned long'if unsigned else'Python int too large to convert to C long')
            pack=''
            if unsigned:pack+='if '+negative+'{return Err("OverflowError: '+("can't convert negative int to unsigned"if code=='Q'else"can't convert negative value to unsigned int")+'".to_owned());}'
            pack+='let number='+integer+'.ok_or_else(||"OverflowError: '+extract+'".to_owned())?;'
            intermediate='i64'if code=='q'else'u64'if code=='Q'else'std::os::raw::c_ulong'if unsigned else'std::os::raw::c_long'
            pack+='if number<('+intermediate+'::MIN as i128)||number>('+intermediate+'::MAX as i128){return Err("OverflowError: '+extract+'".to_owned());}'
            label={'b':'signed char','B':'unsigned byte integer','h':'signed short','H':'unsigned short','i':'signed integer','I':'unsigned int'}.get(code)
            if label:
                pack+='if number<('+raw+'::MIN as i128){return Err("OverflowError: '+label+' is less than minimum".to_owned());}if number>('+raw+'::MAX as i128){return Err("OverflowError: '+label+' is greater than maximum".to_owned());}'
            pack+='Ok(number as '+raw+')'
            result.append('fn '+prefix+'_pack(value:&NativeInt)->Result<'+raw+',String>{'+pack+'}')
        index_integer=('index.to_i128()'if model.integer=='bigint'else'Some(*index as i128)')
        result.append('fn '+prefix+'_index(source:&'+kind.rust+',index:&NativeInt,store:bool)->Result<usize,String>{let number='+index_integer+'.ok_or_else(||"IndexError: cannot fit \'int\' into an index-sized integer".to_owned())?;if number<isize::MIN as i128||number>isize::MAX as i128{return Err("IndexError: cannot fit \'int\' into an index-sized integer".to_owned());}let size=source.0.borrow().len();let position=if number<0{size as i128+number}else{number};if position<0||position>=size as i128{return Err(if store{"IndexError: array assignment index out of range"}else{"IndexError: array index out of range"}.to_owned());}Ok(position as usize)}')
        result.append('#[derive(Clone)]\nstruct '+kind.rust+'(Rc<RefCell<Vec<'+raw+'>>>);')
        result.append('fn '+prefix+'_append_raw(source:&'+kind.rust+',value:'+raw+')->Result<(),String>{let mut data=source.0.borrow_mut();data.try_reserve(1).map_err(|_|"MemoryError".to_owned())?;data.push(value);Ok(())}')
        result.append('fn '+prefix+'_extend_raw(source:&'+kind.rust+',other:&'+kind.rust+')->Result<(),String>{if Rc::ptr_eq(&source.0,&other.0){let mut data=source.0.borrow_mut();let size=data.len();data.try_reserve(size).map_err(|_|"MemoryError".to_owned())?;data.extend_from_within(0..size);}else{let input=other.0.borrow();let mut data=source.0.borrow_mut();data.try_reserve(input.len()).map_err(|_|"MemoryError".to_owned())?;data.extend_from_slice(&input);}Ok(())}')
        result.append('fn '+prefix+'_copy(source:&'+kind.rust+')->Result<'+kind.rust+',String>{let result='+kind.rust+'(Rc::new(RefCell::new(Vec::new())));'+prefix+'_extend_raw(&result,source)?;Ok(result)}')
        result.append('fn '+prefix+'_extend_bytes(source:&'+kind.rust+',bytes:&[u8])->Result<(),String>{const WIDTH:usize=std::mem::size_of::<'+raw+'>();if bytes.len()%WIDTH!=0{return Err("ValueError: bytes length not a multiple of item size".to_owned());}let mut data=source.0.borrow_mut();data.try_reserve(bytes.len()/WIDTH).map_err(|_|"MemoryError".to_owned())?;for chunk in bytes.chunks_exact(WIDTH){let mut value=[0_u8;std::mem::size_of::<'+raw+'>()];value.copy_from_slice(chunk);data.push('+raw+'::from_ne_bytes(value));}Ok(())}')
        result.append('fn '+prefix+'_bytes(bytes:&[u8])->Result<'+kind.rust+',String>{let result='+kind.rust+'(Rc::new(RefCell::new(Vec::new())));'+prefix+'_extend_bytes(&result,bytes)?;Ok(result)}')
        result.append('fn '+prefix+'_asbytes(source:&'+kind.rust+')->Result<Vec<u8>,String>{let data=source.0.borrow();let size=data.len().checked_mul(std::mem::size_of::<'+raw+'>()).ok_or_else(||"MemoryError".to_owned())?;let mut result=Vec::new();result.try_reserve(size).map_err(|_|"MemoryError".to_owned())?;for value in data.iter(){result.extend_from_slice(&value.to_ne_bytes());}Ok(result)}')
        result.append('fn '+prefix+'_swap(source:&'+kind.rust+'){for value in source.0.borrow_mut().iter_mut(){let mut bytes=value.to_ne_bytes();bytes.reverse();*value='+raw+'::from_ne_bytes(bytes);}}')
        result.append('fn '+prefix+'_concat(left:&'+kind.rust+',right:&'+kind.rust+')->Result<'+kind.rust+',String>{let result='+prefix+'_copy(left)?;'+prefix+'_extend_raw(&result,right)?;Ok(result)}')
        result.append('fn '+prefix+'_repeat(source:&'+kind.rust+',count:&NativeInt,inplace:bool)->Result<'+kind.rust+',String>{let count=class_array_count(count)?;let base=source.0.borrow().len();let size=base.checked_mul(count).filter(|size|*size<=isize::MAX as usize/std::mem::size_of::<'+raw+'>()).ok_or_else(||"MemoryError".to_owned())?;if inplace{let mut data=source.0.borrow_mut();if count==0{data.clear();}else if base>0{data.try_reserve(size-base).map_err(|_|"MemoryError".to_owned())?;for _ in 1..count{data.extend_from_within(0..base);}}Ok(source.clone())}else{let mut result=Vec::new();result.try_reserve(size).map_err(|_|"MemoryError".to_owned())?;if base>0{let input=source.0.borrow();for _ in 0..count{result.extend_from_slice(&input);}}Ok('+kind.rust+'(Rc::new(RefCell::new(result))))}}')
        result.append('fn '+prefix+'_pop(source:&'+kind.rust+',index:&NativeInt)->Result<'+raw+',String>{let index='+index_integer+'.ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())?;if index<isize::MIN as i128||index>isize::MAX as i128{return Err("OverflowError: Python int too large to convert to C ssize_t".to_owned());}let mut data=source.0.borrow_mut();if data.is_empty(){return Err("IndexError: pop from empty array".to_owned());}let position=if index<0{data.len()as i128+index}else{index};if position<0||position>=data.len()as i128{return Err("IndexError: pop index out of range".to_owned());}Ok(data.remove(position as usize))}')
        render=('native_float_text(*value as f64)'if code in 'fd'else'value.to_string()')
        result.append('impl ClassDisplay for '+kind.rust+'{fn class_str(&self)->String{let values=self.0.borrow();if values.is_empty(){return "array(\''+code+'\')".to_owned();}let items=values.iter().map(|value|'+render+').collect::<Vec<_>>().join(", ");format!("array(\''+code+'\', [{}])",items)}}')
    return '\n'.join(result)
