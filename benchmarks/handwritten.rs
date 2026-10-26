// Standard-library-only counterparts to benchmarks/run.py.
// Select exactly one workload with --cfg 'benchmark="arithmetic"' etc.
#![allow(dead_code, unused_imports)]
use std::collections::{HashMap, HashSet, VecDeque};
use std::fmt::Write as _;
use std::io::{self, Read, Write as _};
use std::str::SplitWhitespace;

fn number(input: &mut SplitWhitespace<'_>) -> i64 {
    input.next().unwrap().parse().unwrap()
}

#[cfg(benchmark = "arithmetic")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let mut total = 0_i64;
    for i in 0..n {
        total = total.wrapping_add(i.wrapping_mul(17).wrapping_add(3) % 1_000_000_007);
    }
    writeln!(output, "{total}").unwrap();
}

#[cfg(benchmark = "input")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let mut total = 0_i64;
    for _ in 0..n {
        total = total.wrapping_add(number(input));
    }
    writeln!(output, "{total}").unwrap();
}

#[cfg(benchmark = "list")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let values: Vec<i64> = (0..n).map(|i| i % 100).collect();
    let mut total = 0_i64;
    for value in values {
        total = total.wrapping_add(value.wrapping_mul(value));
    }
    writeln!(output, "{total}").unwrap();
}

#[cfg(benchmark = "sort")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let mut values: Vec<i64> = (0..n).map(|i| i.wrapping_mul(19237) % 100003).collect();
    values.sort_unstable();
    let total = values
        .iter()
        .fold(0_i64, |sum, value| sum.wrapping_add(*value));
    writeln!(output, "{} {} {total}", values[0], values[values.len() - 1]).unwrap();
}

#[cfg(benchmark = "dict")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let mut values = HashMap::<i64, i64>::new();
    for i in 0..n {
        let key = i % 101;
        let old = values.get(&key).copied().unwrap_or(0);
        values.insert(key, old.wrapping_add(1));
    }
    let total = values
        .values()
        .fold(0_i64, |sum, value| sum.wrapping_add(*value));
    writeln!(output, "{total}").unwrap();
}

#[cfg(benchmark = "set")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let mut values = HashSet::<i64>::new();
    for i in 0..n {
        values.insert(i.wrapping_mul(19237) % 101);
    }
    let mut found = 0_i64;
    for i in 0..n {
        if values.contains(&(i.wrapping_mul(31) % 101)) {
            found += 1;
        }
    }
    writeln!(output, "{} {found}", values.len()).unwrap();
}

#[cfg(benchmark = "bfs")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input) as usize;
    let m = number(input) as usize;
    let mut graph = vec![Vec::<usize>::new(); n];
    for _ in 0..m {
        let a = number(input) as usize;
        let b = number(input) as usize;
        graph[a].push(b);
        graph[b].push(a);
    }
    let mut distance = vec![-1_i64; n];
    distance[0] = 0;
    let mut queue = VecDeque::from([0_usize]);
    while let Some(vertex) = queue.pop_front() {
        for &neighbor in &graph[vertex] {
            if distance[neighbor] == -1 {
                distance[neighbor] = distance[vertex] + 1;
                queue.push_back(neighbor);
            }
        }
    }
    for (index, value) in distance.iter().enumerate() {
        if index != 0 {
            output.push(' ');
        }
        write!(output, "{value}").unwrap();
    }
    output.push('\n');
}

#[cfg(benchmark = "dp")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input) as usize;
    let mut values = vec![0_i64; n + 2];
    values[0] = 1;
    for i in 0..n {
        values[i + 1] = values[i + 1].wrapping_add(values[i]) % 1_000_000_007;
        values[i + 2] = values[i + 2].wrapping_add(values[i]) % 1_000_000_007;
    }
    writeln!(output, "{}", values[n]).unwrap();
}

#[cfg(benchmark = "bigint")]
struct Big(Vec<u32>);

#[cfg(benchmark = "bigint")]
impl Big {
    fn mul_small(&self, factor: u32) -> Self {
        let mut result = Vec::with_capacity(self.0.len() + 1);
        let mut carry = 0_u64;
        for &limb in &self.0 {
            let product = u64::from(limb) * u64::from(factor) + carry;
            result.push(product as u32);
            carry = product >> 32;
        }
        if carry != 0 {
            result.push(carry as u32);
        }
        Self(result)
    }
    fn add_small(&self, value: u32) -> Self {
        let mut result = self.0.clone();
        let mut carry = u64::from(value);
        for limb in &mut result {
            let sum = u64::from(*limb) + carry;
            *limb = sum as u32;
            carry = sum >> 32;
            if carry == 0 {
                break;
            }
        }
        if carry != 0 {
            result.push(carry as u32);
        }
        Self(result)
    }
    fn bit_length(&self) -> usize {
        self.0.len().saturating_sub(1) * 32
            + self
                .0
                .last()
                .map_or(0, |limb| 32 - limb.leading_zeros() as usize)
    }
}

#[cfg(benchmark = "bigint")]
fn work(input: &mut SplitWhitespace<'_>, output: &mut String) {
    let n = number(input);
    let mut value = Big(vec![1]);
    // Evaluate every multiply and add. No n+1/closed-form substitution.
    for _ in 0..n {
        value = value.mul_small(2).add_small(1);
    }
    writeln!(output, "{}", value.bit_length()).unwrap();
}

fn main() {
    let mut text = String::new();
    io::stdin().read_to_string(&mut text).unwrap();
    let mut input = text.split_whitespace();
    let batch = number(&mut input);
    let mut output = String::new();
    for _ in 0..batch {
        work(&mut input, &mut output);
    }
    io::stdout().write_all(output.as_bytes()).unwrap();
}
