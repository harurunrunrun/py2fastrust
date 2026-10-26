// Unicode Normalization Form KC. Python normalizes identifiers after keyword
// recognition, so lexical tokens must retain their original spelling.
fn normalize_combining(codepoint: u32) -> u8 {
    NORMALIZE_COMBINING.binary_search_by_key(&codepoint, |&(point,_)|point)
        .map(|index|NORMALIZE_COMBINING[index].1).unwrap_or(0)
}
fn normalize_compose(first: u32, second: u32) -> Option<u32> {
    const SBASE:u32=0xac00;const LBASE:u32=0x1100;const VBASE:u32=0x1161;const TBASE:u32=0x11a7;
    const LCOUNT:u32=19;const VCOUNT:u32=21;const TCOUNT:u32=28;
    if (LBASE..LBASE+LCOUNT).contains(&first)&&(VBASE..VBASE+VCOUNT).contains(&second) {
        return Some(SBASE+((first-LBASE)*VCOUNT+second-VBASE)*TCOUNT);
    }
    if (SBASE..SBASE+LCOUNT*VCOUNT*TCOUNT).contains(&first)&&(first-SBASE)%TCOUNT==0
        &&(TBASE+1..TBASE+TCOUNT).contains(&second) {return Some(first+second-TBASE);}
    NORMALIZE_COMPOSITIONS.binary_search_by_key(&(first,second), |&(pair,_)|pair).ok()
        .map(|index|NORMALIZE_COMPOSITIONS[index].1)
}
fn normalize_push_ordered(result: &mut Vec<u32>, point: u32) {
    result.push(point);
}
fn text_nfkc(value: &str) -> String {
    if value.is_ascii(){return value.to_owned();}
    let mut decomposed=Vec::with_capacity(value.len());
    for character in value.chars() {
        let point=character as u32;
        if (0xac00..=0xd7a3).contains(&point) {
            let index=point-0xac00;
            normalize_push_ordered(&mut decomposed,0x1100+index/(21*28));
            normalize_push_ordered(&mut decomposed,0x1161+(index/28)%21);
            if index%28!=0{normalize_push_ordered(&mut decomposed,0x11a7+index%28);}
        }else if let Ok(index)=NORMALIZE_DECOMPOSITIONS.binary_search_by_key(&point, |&(codepoint,_)|codepoint) {
            for &point in NORMALIZE_DECOMPOSITIONS[index].1 {normalize_push_ordered(&mut decomposed,point);}
        }else{normalize_push_ordered(&mut decomposed,point);}
    }
    // Stable ordering of each nonstarter run avoids quadratic insertion for
    // long identifiers containing deliberately reversed combining classes.
    let mut segment=0;
    for index in 0..decomposed.len() {
        if normalize_combining(decomposed[index])==0 {
            decomposed[segment..index].sort_by_key(|point|normalize_combining(*point));segment=index+1;
        }
    }
    decomposed[segment..].sort_by_key(|point|normalize_combining(*point));
    let mut result=Vec::<u32>::with_capacity(decomposed.len());
    let mut starter=None;let mut previous_class=0;
    for point in decomposed {
        let class=normalize_combining(point);
        if let Some(index)=starter {
            if previous_class==0||previous_class<class {
                if let Some(composed)=normalize_compose(result[index],point){result[index]=composed;continue;}
            }
        }
        if class==0 {starter=Some(result.len());}
        result.push(point);previous_class=class;
    }
    result.into_iter().map(|point|char::from_u32(point).expect("Unicode normalization scalar invariant")).collect()
}
