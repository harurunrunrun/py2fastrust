// Adapted from CPython v3.14.4 Objects/listobject.c under the PSF License.
// See ../stdlib/PYTHON_LICENSE.txt. Typed fallible callbacks preserve comparison order.
@ASYNC@fn native_cmp_gallop_left@SUFFIX@<E, F: @BOUND@>(key: usize, values: &[usize], hint: usize, less: &mut F) -> Result<usize, E> {
    let n = values.len();
    let mut last: isize = 0;
    let mut offset = 1usize;
    if less(values[hint], key)@AWAIT@? {
        let maximum = n - hint;
        while offset < maximum {
            if less(values[hint + offset], key)@AWAIT@? { last = offset as isize; offset = offset.saturating_mul(2).saturating_add(1); }
            else { break; }
        }
        offset = offset.min(maximum) + hint;
        last += hint as isize;
    } else {
        let maximum = hint + 1;
        while offset < maximum {
            if less(values[hint - offset], key)@AWAIT@? { break; }
            last = offset as isize; offset = offset.saturating_mul(2).saturating_add(1);
        }
        offset = offset.min(maximum);
        let saved = last;
        last = hint as isize - offset as isize;
        offset = hint - saved as usize;
    }
    let mut low = (last + 1) as usize;
    while low < offset {
        let middle = low + (offset - low) / 2;
        if less(values[middle], key)@AWAIT@? { low = middle + 1; }
        else { offset = middle; }
    }
    Ok(offset)
}
@ASYNC@fn native_cmp_gallop_right@SUFFIX@<E, F: @BOUND@>(key: usize, values: &[usize], hint: usize, less: &mut F) -> Result<usize, E> {
    let n = values.len();
    let mut last: isize = 0;
    let mut offset = 1usize;
    if less(key, values[hint])@AWAIT@? {
        let maximum = hint + 1;
        while offset < maximum {
            if !less(key, values[hint - offset])@AWAIT@? { break; }
            last = offset as isize; offset = offset.saturating_mul(2).saturating_add(1);
        }
        offset = offset.min(maximum);
        let saved = last;
        last = hint as isize - offset as isize;
        offset = hint - saved as usize;
    } else {
        let maximum = n - hint;
        while offset < maximum {
            if less(key, values[hint + offset])@AWAIT@? { break; }
            last = offset as isize; offset = offset.saturating_mul(2).saturating_add(1);
        }
        offset = offset.min(maximum) + hint;
        last += hint as isize;
    }
    let mut low = (last + 1) as usize;
    while low < offset {
        let middle = low + (offset - low) / 2;
        if less(key, values[middle])@AWAIT@? { offset = middle; }
        else { low = middle + 1; }
    }
    Ok(offset)
}
impl NativeCmpSort {
    @ASYNC@fn count_run@SUFFIX@<E, F: @BOUND@>(&mut self, base: usize, less: &mut F) -> Result<usize, E> {
        let remaining = self.order.len() - base;
        let mut n = 1;
        while n < remaining {
            if less(self.order[base+n], self.order[base+n-1])@AWAIT@? { break; }
            n += 1;
        }
        if n == remaining { return Ok(n); }
        if n > 1 {
            if less(self.order[base], self.order[base+n-1])@AWAIT@? { return Ok(n); }
            self.order[base..base+n].reverse();
        }
        n += 1;
        let mut equal = 0;
        while n < remaining {
            if less(self.order[base+n], self.order[base+n-1])@AWAIT@? {
                if equal > 0 { self.order[base+n-equal-1..base+n].reverse(); equal = 0; }
            } else if less(self.order[base+n-1], self.order[base+n])@AWAIT@? { break; }
            else { equal += 1; }
            n += 1;
        }
        if equal > 0 { self.order[base+n-equal-1..base+n].reverse(); }
        self.order[base..base+n].reverse();
        while n < remaining {
            if less(self.order[base+n], self.order[base+n-1])@AWAIT@? { break; }
            n += 1;
        }
        Ok(n)
    }
    @ASYNC@fn binary_sort@SUFFIX@<E, F: @BOUND@>(&mut self, base: usize, n: usize, mut sorted: usize, less: &mut F) -> Result<(), E> {
        if sorted == 0 { sorted = 1; }
        while sorted < n {
            let pivot = self.order[base+sorted];
            let mut low = 0; let mut high = sorted;
            while low < high {
                let middle = (low + high) / 2;
                if less(pivot, self.order[base+middle])@AWAIT@? { high = middle; }
                else { low = middle + 1; }
            }
            self.order.copy_within(base+low..base+sorted, base+low+1);
            self.order[base+low] = pivot;
            sorted += 1;
        }
        Ok(())
    }
    @ASYNC@fn merge_lo@SUFFIX@<E, F: @BOUND@>(&mut self, base_a: usize, mut na: usize, base_b: usize, mut nb: usize, less: &mut F, oom: &impl Fn() -> E) -> Result<(), E> {
        let mut temporary = Vec::new();
        temporary.try_reserve_exact(na).map_err(|_|oom())?;
        temporary.extend_from_slice(&self.order[base_a..base_a+na]);
        let mut a = 0; let mut b = base_b; let mut dest = base_a;
        self.order[dest] = self.order[b]; dest += 1; b += 1; nb -= 1;
        let result = @ASYNC_BLOCK@{
            if nb == 0 { return Ok(()); }
            if na == 1 { self.order.copy_within(b..b+nb, dest); self.order[dest+nb] = temporary[a]; na=0; return Ok(()); }
            let mut threshold = self.min_gallop;
            loop {
                let mut acount = 0; let mut bcount = 0;
                loop {
                    if less(self.order[b], temporary[a])@AWAIT@? {
                        self.order[dest]=self.order[b]; dest+=1; b+=1; nb-=1; bcount+=1; acount=0;
                        if nb==0 { return Ok(()); }
                        if bcount>=threshold { break; }
                    } else {
                        self.order[dest]=temporary[a]; dest+=1; a+=1; na-=1; acount+=1; bcount=0;
                        if na==1 { self.order.copy_within(b..b+nb,dest); self.order[dest+nb]=temporary[a]; na=0; return Ok(()); }
                        if acount>=threshold { break; }
                    }
                }
                threshold+=1;
                loop {
                    threshold-=usize::from(threshold>1); self.min_gallop=threshold;
                    acount=native_cmp_gallop_right@SUFFIX@(self.order[b], &temporary[a..a+na],0,less)@AWAIT@?;
                    if acount>0 {
                        self.order[dest..dest+acount].copy_from_slice(&temporary[a..a+acount]);
                        dest+=acount; a+=acount; na-=acount;
                        if na==1 { self.order.copy_within(b..b+nb,dest); self.order[dest+nb]=temporary[a]; na=0; return Ok(()); }
                        if na==0 { return Ok(()); }
                    }
                    self.order[dest]=self.order[b]; dest+=1; b+=1; nb-=1;
                    if nb==0 { return Ok(()); }
                    bcount=native_cmp_gallop_left@SUFFIX@(temporary[a],&self.order[b..b+nb],0,less)@AWAIT@?;
                    if bcount>0 {
                        self.order.copy_within(b..b+bcount,dest); dest+=bcount; b+=bcount; nb-=bcount;
                        if nb==0 { return Ok(()); }
                    }
                    self.order[dest]=temporary[a]; dest+=1; a+=1; na-=1;
                    if na==1 { self.order.copy_within(b..b+nb,dest); self.order[dest+nb]=temporary[a]; na=0; return Ok(()); }
                    if acount<7 && bcount<7 { break; }
                }
                threshold+=1; self.min_gallop=threshold;
            }
        }@BLOCK_END@;
        if na>0 { self.order[dest..dest+na].copy_from_slice(&temporary[a..a+na]); }
        result
    }
    @ASYNC@fn merge_hi@SUFFIX@<E, F: @BOUND@>(&mut self, base_a: usize, mut na: usize, base_b: usize, mut nb: usize, less: &mut F, oom: &impl Fn() -> E) -> Result<(), E> {
        let mut temporary = Vec::new();
        temporary.try_reserve_exact(nb).map_err(|_|oom())?;
        temporary.extend_from_slice(&self.order[base_b..base_b+nb]);
        let mut dest = base_b+nb;
        self.order[dest-1]=self.order[base_a+na-1]; dest-=1; na-=1;
        let result = @ASYNC_BLOCK@{
            if na==0 { return Ok(()); }
            if nb==1 { self.order.copy_within(base_a..base_a+na,dest-na); self.order[dest-na-1]=temporary[0]; nb=0; return Ok(()); }
            let mut threshold=self.min_gallop;
            loop {
                let mut acount=0; let mut bcount=0;
                loop {
                    if less(temporary[nb-1],self.order[base_a+na-1])@AWAIT@? {
                        self.order[dest-1]=self.order[base_a+na-1]; dest-=1; na-=1; acount+=1; bcount=0;
                        if na==0 { return Ok(()); }
                        if acount>=threshold { break; }
                    } else {
                        self.order[dest-1]=temporary[nb-1]; dest-=1; nb-=1; bcount+=1; acount=0;
                        if nb==1 { self.order.copy_within(base_a..base_a+na,dest-na); self.order[dest-na-1]=temporary[0]; nb=0; return Ok(()); }
                        if bcount>=threshold { break; }
                    }
                }
                threshold+=1;
                loop {
                    threshold-=usize::from(threshold>1); self.min_gallop=threshold;
                    acount=na-native_cmp_gallop_right@SUFFIX@(temporary[nb-1],&self.order[base_a..base_a+na],na-1,less)@AWAIT@?;
                    if acount>0 {
                        self.order.copy_within(base_a+na-acount..base_a+na,dest-acount); dest-=acount; na-=acount;
                        if na==0 { return Ok(()); }
                    }
                    self.order[dest-1]=temporary[nb-1]; dest-=1; nb-=1;
                    if nb==1 { self.order.copy_within(base_a..base_a+na,dest-na); self.order[dest-na-1]=temporary[0]; nb=0; return Ok(()); }
                    bcount=nb-native_cmp_gallop_left@SUFFIX@(self.order[base_a+na-1],&temporary[..nb],nb-1,less)@AWAIT@?;
                    if bcount>0 {
                        self.order[dest-bcount..dest].copy_from_slice(&temporary[nb-bcount..nb]); dest-=bcount; nb-=bcount;
                        if nb==1 { self.order.copy_within(base_a..base_a+na,dest-na); self.order[dest-na-1]=temporary[0]; nb=0; return Ok(()); }
                        if nb==0 { return Ok(()); }
                    }
                    self.order[dest-1]=self.order[base_a+na-1]; dest-=1; na-=1;
                    if na==0 { return Ok(()); }
                    if acount<7 && bcount<7 { break; }
                }
                threshold+=1; self.min_gallop=threshold;
            }
        }@BLOCK_END@;
        if nb>0 { self.order[dest-nb..dest].copy_from_slice(&temporary[..nb]); }
        result
    }
    @ASYNC@fn merge_at@SUFFIX@<E, F: @BOUND@>(&mut self, index: usize, less: &mut F, oom: &impl Fn() -> E) -> Result<(), E> {
        let run_a=self.pending[index]; let run_b=self.pending[index+1];
        self.pending[index].len=run_a.len+run_b.len;
        self.pending.remove(index+1);
        let skipped=native_cmp_gallop_right@SUFFIX@(self.order[run_b.base],&self.order[run_a.base..run_a.base+run_a.len],0,less)@AWAIT@?;
        let base_a=run_a.base+skipped; let na=run_a.len-skipped;
        if na==0 { return Ok(()); }
        let nb=native_cmp_gallop_left@SUFFIX@(self.order[base_a+na-1],&self.order[run_b.base..run_b.base+run_b.len],run_b.len-1,less)@AWAIT@?;
        if nb==0 { return Ok(()); }
        if na<=nb { self.merge_lo@SUFFIX@(base_a,na,run_b.base,nb,less,oom)@AWAIT@ }
        else { self.merge_hi@SUFFIX@(base_a,na,run_b.base,nb,less,oom)@AWAIT@ }
    }
    @ASYNC@fn run@SUFFIX@<E, F: @BOUND@>(&mut self, less: &mut F, oom: &impl Fn() -> E) -> Result<(), E> {
        let length=self.order.len();
        if length<2 { return Ok(()); }
        let mut minrun=length; let mut remainder=0;
        while minrun>=64 { remainder|=minrun&1; minrun>>=1; }
        minrun+=remainder;
        let mut base=0;
        while base<length {
            let mut n=self.count_run@SUFFIX@(base,less)@AWAIT@?;
            if n<minrun { let force=minrun.min(length-base); self.binary_sort@SUFFIX@(base,force,n,less)@AWAIT@?; n=force; }
            if let Some(last)=self.pending.last() {
                let power=native_cmp_sort_power(last.base,last.len,n,length);
                while self.pending.len()>1 && self.pending[self.pending.len()-2].power>power {
                    self.merge_at@SUFFIX@(self.pending.len()-2,less,oom)@AWAIT@?;
                }
                self.pending.last_mut().unwrap().power=power;
            }
            self.pending.push(NativeCmpRun{base,len:n,power:0}); base+=n;
        }
        while self.pending.len()>1 {
            let mut n=self.pending.len()-2;
            if n>0 && self.pending[n-1].len<self.pending[n+1].len { n-=1; }
            self.merge_at@SUFFIX@(n,less,oom)@AWAIT@?;
        }
        Ok(())
    }
}
@ASYNC@fn native_cmp_sort_indices@SUFFIX@<E, F: @BOUND@>(length: usize, reverse: bool, mut less: F, oom: impl Fn() -> E) -> Result<(Vec<usize>,Option<E>), E> {
    let mut state=NativeCmpSort{order:Vec::new(),pending:Vec::new(),min_gallop:7};
    state.order.try_reserve_exact(length).map_err(|_|oom())?;
    state.pending.try_reserve_exact(usize::BITS as usize+1).map_err(|_|oom())?;
    state.order.extend(0..length);
    if reverse { state.order.reverse(); }
    let result=state.run@SUFFIX@(&mut less,&oom)@AWAIT@;
    if reverse { state.order.reverse(); }
    Ok((state.order,result.err()))
}
