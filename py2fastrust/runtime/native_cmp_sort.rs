// Adapted from CPython v3.14.4 Objects/listobject.c under the PSF License.
// See ../stdlib/PYTHON_LICENSE.txt. Rust index permutation replaces PyObject storage.
#[derive(Clone, Copy)]
struct NativeCmpRun { base: usize, len: usize, power: u32 }
struct NativeCmpSort { order: Vec<usize>, pending: Vec<NativeCmpRun>, min_gallop: usize }
fn native_cmp_sort_apply<T>(values: &mut [T], order: &mut [usize]) {
    for start in 0..order.len() {
        let mut previous = start;
        let mut next = order[previous];
        while next != start {
            values.swap(previous, next);
            order[previous] = previous;
            previous = next;
            next = order[previous];
        }
        order[previous] = previous;
    }
}
fn native_cmp_sort_power(base: usize, first: usize, second: usize, length: usize) -> u32 {
    let mut a = 2 * base + first;
    let mut b = a + first + second;
    let mut result = 0;
    loop {
        result += 1;
        if a >= length { a -= length; b -= length; }
        else if b >= length { return result; }
        a *= 2; b *= 2;
    }
}
