// The generator supplies INT_BITS: 64, 128, or 0 (arbitrary precision).
// Magnitudes use base 2^32. A canonical small representation avoids allocations.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Int(IntRepr);

#[derive(Clone, Debug, PartialEq, Eq)]
enum IntRepr {
    Small(i128),
    Big { negative: bool, digits: Vec<u32> },
}

impl Int {
    fn from_i128(value: i128) -> Self {
        Self(IntRepr::Small(if INT_BITS == 64 {
            value as i64 as i128
        } else {
            value
        }))
    }

    fn exact_small(value: i128) -> Self {
        Self(IntRepr::Small(value))
    }

    fn trim(digits: &mut Vec<u32>) {
        while digits.last() == Some(&0) {
            digits.pop();
        }
    }

    fn magnitude(&self) -> std::borrow::Cow<'_, [u32]> {
        match &self.0 {
            IntRepr::Big { digits, .. } => std::borrow::Cow::Borrowed(digits),
            IntRepr::Small(value) => {
                let mut n = value.unsigned_abs();
                let mut result = Vec::new();
                while n != 0 {
                    result.push(n as u32);
                    n >>= 32;
                }
                std::borrow::Cow::Owned(result)
            }
        }
    }

    fn exact_parts(negative: bool, mut digits: Vec<u32>) -> Self {
        Self::trim(&mut digits);
        if digits.len() <= 4 {
            let mut n = 0u128;
            for &limb in digits.iter().rev() {
                n = (n << 32) | limb as u128;
            }
            if n == 0 {
                return Self::exact_small(0);
            }
            if negative && n <= 1u128 << 127 {
                return Self::exact_small((0u128.wrapping_sub(n)) as i128);
            }
            if !negative && n <= i128::MAX as u128 {
                return Self::exact_small(n as i128);
            }
        }
        Self(IntRepr::Big { negative, digits })
    }

    fn parts(negative: bool, digits: Vec<u32>) -> Self {
        if INT_BITS == 0 {
            return Self::exact_parts(negative, digits);
        }
        let count = (INT_BITS / 32) as usize;
        let mut n = 0u128;
        for &limb in digits.iter().take(count).rev() {
            n = (n << 32) | limb as u128;
        }
        if negative {
            n = 0u128.wrapping_sub(n);
        }
        Self::from_i128(n as i128)
    }

    fn normalized(self) -> Self {
        if INT_BITS == 0 {
            return self;
        }
        match self.0 {
            IntRepr::Small(n) => Self::from_i128(n),
            IntRepr::Big { negative, digits } => Self::parts(negative, digits),
        }
    }

    fn is_zero(&self) -> bool {
        matches!(self.0, IntRepr::Small(0))
    }
    fn is_negative(&self) -> bool {
        match &self.0 {
            IntRepr::Small(n) => *n < 0,
            IntRepr::Big { negative, .. } => *negative,
        }
    }
    fn to_i128(&self) -> Option<i128> {
        if let IntRepr::Small(n) = self.0 {
            Some(n)
        } else {
            None
        }
    }
    fn to_usize(&self) -> Option<usize> {
        self.to_i128().and_then(|n| usize::try_from(n).ok())
    }

    // Power-of-two conversion visits the limbs directly, without a fixed-width
    // intermediate or quadratic repeated division. The sign is kept separate
    // from the magnitude so that fixed-width MIN formats correctly as well.
    fn unsigned_radix(&self, base: u32, upper: bool) -> String {
        if base == 10 {
            return self.to_string().trim_start_matches('-').to_string();
        }
        let step = match base {
            2 => 1,
            8 => 3,
            16 => 4,
            _ => unreachable!("unsupported integer output radix"),
        };
        let alphabet = if upper {
            b"0123456789ABCDEF"
        } else {
            b"0123456789abcdef"
        };
        let bits = self.bit_length();
        if bits == 0 {
            return "0".into();
        }
        let magnitude = self.magnitude();
        let count = (bits + step - 1) / step;
        let mut output = String::with_capacity(count);
        for index in (0..count).rev() {
            let bit = index * step;
            let limb = bit / 32;
            let mut value = magnitude[limb] as u64;
            if limb + 1 < magnitude.len() {
                value |= (magnitude[limb + 1] as u64) << 32;
            }
            let digit = (value >> (bit % 32)) & (base - 1) as u64;
            output.push(alphabet[digit as usize] as char);
        }
        output
    }

    fn radix(&self, base: u32, upper: bool) -> String {
        let digits = self.unsigned_radix(base, upper);
        if self.is_negative() {
            "-".to_string() + &digits
        } else {
            digits
        }
    }

    fn format_digit(character: char) -> Option<usize> {
        if character.is_ascii_digit() {
            return Some((character as u8 - b'0') as usize);
        }
        // Unicode 16.0 decimal ranges, generated from CPython unicodedata.
        const RANGES: &[(u32, u32)] = &[
            (1632, 1641),
            (1776, 1785),
            (1984, 1993),
            (2406, 2415),
            (2534, 2543),
            (2662, 2671),
            (2790, 2799),
            (2918, 2927),
            (3046, 3055),
            (3174, 3183),
            (3302, 3311),
            (3430, 3439),
            (3558, 3567),
            (3664, 3673),
            (3792, 3801),
            (3872, 3881),
            (4160, 4169),
            (4240, 4249),
            (6112, 6121),
            (6160, 6169),
            (6470, 6479),
            (6608, 6617),
            (6784, 6793),
            (6800, 6809),
            (6992, 7001),
            (7088, 7097),
            (7232, 7241),
            (7248, 7257),
            (42528, 42537),
            (43216, 43225),
            (43264, 43273),
            (43472, 43481),
            (43504, 43513),
            (43600, 43609),
            (44016, 44025),
            (65296, 65305),
            (66720, 66729),
            (68912, 68921),
            (68928, 68937),
            (69734, 69743),
            (69872, 69881),
            (69942, 69951),
            (70096, 70105),
            (70384, 70393),
            (70736, 70745),
            (70864, 70873),
            (71248, 71257),
            (71360, 71369),
            (71376, 71395),
            (71472, 71481),
            (71904, 71913),
            (72016, 72025),
            (72688, 72697),
            (72784, 72793),
            (73040, 73049),
            (73120, 73129),
            (73552, 73561),
            (90416, 90425),
            (92768, 92777),
            (92864, 92873),
            (93008, 93017),
            (93552, 93561),
            (118000, 118009),
            (120782, 120831),
            (123200, 123209),
            (123632, 123641),
            (124144, 124153),
            (124401, 124410),
            (125264, 125273),
            (130032, 130041),
        ];
        let code = character as u32;
        let index = RANGES.partition_point(|(_, end)| *end < code);
        RANGES
            .get(index)
            .filter(|(start, _)| *start <= code)
            .map(|(start, _)| ((code - *start) % 10) as usize)
    }

    // Integer presentation types of Python's format specification language.
    // Floating presentation types are delegated to the VM's float formatter.
    fn format_integer(&self, spec: &str) -> Result<Option<String>, String> {
        if spec.is_empty() {
            return Ok(Some(self.to_string()));
        }
        let chars: Vec<char> = spec.chars().collect();
        let mut index = 0;
        let mut fill = ' ';
        let mut align = '>';
        let mut explicit_fill = false;
        let mut explicit_align = false;
        if chars.len() > 1 && "<>=^".contains(chars[1]) {
            fill = chars[0];
            align = chars[1];
            explicit_fill = true;
            explicit_align = true;
            index = 2;
        } else if "<>=^".contains(chars[0]) {
            align = chars[0];
            explicit_align = true;
            index = 1;
        }
        let mut sign = None;
        if index < chars.len() && "+- ".contains(chars[index]) {
            sign = Some(chars[index]);
            index += 1;
        }
        let zero_coercion = index < chars.len() && chars[index] == 'z';
        if zero_coercion {
            index += 1;
        }
        let alternate = index < chars.len() && chars[index] == '#';
        if alternate {
            index += 1;
        }
        if index < chars.len() && chars[index] == '0' {
            if !explicit_fill {
                fill = '0';
            }
            if !explicit_align {
                align = '=';
            }
            index += 1;
        }
        let mut width = 0usize;
        while index < chars.len() && Self::format_digit(chars[index]).is_some() {
            width = width
                .checked_mul(10)
                .and_then(|n| n.checked_add(Self::format_digit(chars[index]).unwrap()))
                .filter(|n| *n <= isize::MAX as usize)
                .ok_or("ValueError: Too many decimal digits in format string")?;
            index += 1;
        }
        let mut grouping = None;
        if index < chars.len() && ",_".contains(chars[index]) {
            grouping = Some(chars[index]);
            index += 1;
        }
        let mut precision = false;
        if index < chars.len() && chars[index] == '.' {
            precision = true;
            index += 1;
            let start = index;
            while index < chars.len() && Self::format_digit(chars[index]).is_some() {
                index += 1;
            }
            if index < chars.len() && ",_".contains(chars[index]) {
                index += 1;
            } else if index == start {
                return Err("ValueError: Format specifier missing precision".into());
            }
        }
        let kind = if index == chars.len() {
            'd'
        } else if index + 1 == chars.len() {
            chars[index]
        } else {
            return Err("ValueError: Invalid format specifier for object of type 'int'".into());
        };
        if "eEfFgG%".contains(kind) {
            return Ok(None);
        }
        if !"bcdoxXn".contains(kind) {
            return Err(format!(
                "ValueError: Unknown format code '{}' for object of type 'int'",
                kind
            ));
        }
        if zero_coercion {
            return Err(
                "ValueError: Negative zero coercion (z) not allowed in integer format specifier"
                    .into(),
            );
        }
        if precision {
            return Err("ValueError: Precision not allowed in integer format specifier".into());
        }
        if let Some(separator) = grouping {
            if kind == 'n' || kind == 'c' || (separator == ',' && kind != 'd') {
                return Err(format!(
                    "ValueError: Cannot specify '{}' with '{}'.",
                    separator, kind
                ));
            }
        }
        let mut prefix = String::new();
        let mut digits = if kind == 'c' {
            if sign.is_some() || alternate {
                return Err("ValueError: Sign or alternate form not allowed with integer format specifier 'c'".into());
            }
            let value = self
                .to_i128()
                .and_then(|n| u32::try_from(n).ok())
                .and_then(char::from_u32)
                .ok_or("OverflowError: %c arg not in range(0x110000)")?;
            value.to_string()
        } else {
            let base = match kind {
                'b' => 2,
                'o' => 8,
                'x' | 'X' => 16,
                _ => 10,
            };
            if self.is_negative() {
                prefix.push('-');
            } else if sign == Some('+') || sign == Some(' ') {
                prefix.push(sign.unwrap());
            }
            if alternate {
                prefix.push_str(match kind {
                    'b' => "0b",
                    'o' => "0o",
                    'x' => "0x",
                    'X' => "0X",
                    _ => "",
                });
            }
            self.unsigned_radix(base, kind == 'X')
        };
        let group = if kind == 'd' { 3 } else { 4 };
        if fill == '0' && align == '=' && grouping.is_some() {
            let target = width.saturating_sub(prefix.len());
            let mut low = digits.len();
            let mut high = target.max(low);
            while low < high {
                let middle = low + (high - low) / 2;
                if middle.saturating_add(middle.saturating_sub(1) / group) < target {
                    low = middle + 1;
                } else {
                    high = middle;
                }
            }
            if low > digits.len() {
                let mut padded = String::new();
                padded
                    .try_reserve(low)
                    .map_err(|_| "MemoryError: integer format is too large")?;
                padded.extend(std::iter::repeat_n('0', low - digits.len()));
                padded.push_str(&digits);
                digits = padded;
            }
        }
        if let Some(separator) = grouping {
            let mut grouped = String::new();
            grouped
                .try_reserve(digits.len().saturating_mul(2))
                .map_err(|_| "MemoryError: integer format is too large")?;
            for (index, byte) in digits.bytes().enumerate() {
                if index > 0 && (digits.len() - index) % group == 0 {
                    grouped.push(separator);
                }
                grouped.push(byte as char);
            }
            digits = grouped;
        }
        let length = prefix.chars().count() + digits.chars().count();
        let padding = width.saturating_sub(length);
        let capacity = prefix
            .len()
            .checked_add(digits.len())
            .and_then(|n| {
                padding
                    .checked_mul(fill.len_utf8())
                    .and_then(|p| n.checked_add(p))
            })
            .ok_or("MemoryError: integer format is too large")?;
        let mut output = String::new();
        output
            .try_reserve(capacity)
            .map_err(|_| "MemoryError: integer format is too large")?;
        let (before, between, after) = match align {
            '<' => (0, 0, padding),
            '^' => (padding / 2, 0, padding - padding / 2),
            '=' => (0, padding, 0),
            _ => (padding, 0, 0),
        };
        output.extend(std::iter::repeat_n(fill, before));
        output.push_str(&prefix);
        output.extend(std::iter::repeat_n(fill, between));
        output.push_str(&digits);
        output.extend(std::iter::repeat_n(fill, after));
        Ok(Some(output))
    }
    fn bit_length(&self) -> usize {
        match &self.0 {
            IntRepr::Small(n) => 128 - n.unsigned_abs().leading_zeros() as usize,
            IntRepr::Big { digits, .. } => Self::nat_bits(digits),
        }
    }
    fn bit_count(&self) -> usize {
        match &self.0 {
            IntRepr::Small(n) => n.unsigned_abs().count_ones() as usize,
            IntRepr::Big { digits, .. } => digits.iter().map(|n| n.count_ones() as usize).sum(),
        }
    }

    fn nat_bits(a: &[u32]) -> usize {
        a.last()
            .map_or(0, |n| (a.len() - 1) * 32 + 32 - n.leading_zeros() as usize)
    }
    fn nat_cmp(a: &[u32], b: &[u32]) -> std::cmp::Ordering {
        a.len()
            .cmp(&b.len())
            .then_with(|| a.iter().rev().cmp(b.iter().rev()))
    }
    fn nat_add(a: &[u32], b: &[u32]) -> Vec<u32> {
        let mut out = Vec::with_capacity(a.len().max(b.len()) + 1);
        let mut carry = 0u64;
        for i in 0..a.len().max(b.len()) {
            let n = a.get(i).copied().unwrap_or(0) as u64
                + b.get(i).copied().unwrap_or(0) as u64
                + carry;
            out.push(n as u32);
            carry = n >> 32;
        }
        if carry != 0 {
            out.push(carry as u32);
        }
        out
    }
    fn nat_sub(a: &[u32], b: &[u32]) -> Vec<u32> {
        debug_assert!(Self::nat_cmp(a, b) != std::cmp::Ordering::Less);
        let mut out = Vec::with_capacity(a.len());
        let mut borrow = 0u64;
        for (i, &limb) in a.iter().enumerate() {
            let rhs = b.get(i).copied().unwrap_or(0) as u64 + borrow;
            out.push((limb as u64).wrapping_sub(rhs) as u32);
            borrow = u64::from((limb as u64) < rhs);
        }
        Self::trim(&mut out);
        out
    }
    fn nat_mul(a: &[u32], b: &[u32]) -> Vec<u32> {
        if a.is_empty() || b.is_empty() {
            return Vec::new();
        }
        let mut out = vec![0u32; a.len() + b.len()];
        for (i, &x) in a.iter().enumerate() {
            let mut carry = 0u64;
            for (j, &y) in b.iter().enumerate() {
                let n = x as u64 * y as u64 + out[i + j] as u64 + carry;
                out[i + j] = n as u32;
                carry = n >> 32;
            }
            out[i + b.len()] = carry as u32;
        }
        Self::trim(&mut out);
        out
    }
    fn nat_shl(a: &[u32], shift: usize) -> Vec<u32> {
        if a.is_empty() {
            return Vec::new();
        }
        let words = shift / 32;
        let bits = shift % 32;
        let mut out = vec![0u32; words];
        out.reserve(a.len() + 1);
        let mut carry = 0u64;
        for &x in a {
            let n = ((x as u64) << bits) | carry;
            out.push(n as u32);
            carry = n >> 32;
        }
        if carry != 0 {
            out.push(carry as u32);
        }
        out
    }
    fn nat_shr(a: &[u32], shift: usize) -> Vec<u32> {
        let words = shift / 32;
        let bits = shift % 32;
        if words >= a.len() {
            return Vec::new();
        }
        let mut out = a[words..].to_vec();
        if bits != 0 {
            let mut carry = 0u32;
            for n in out.iter_mut().rev() {
                let old = *n;
                *n = (old >> bits) | carry;
                carry = old << (32 - bits);
            }
        }
        Self::trim(&mut out);
        out
    }

    fn nat_div_small(a: &[u32], divisor: u32) -> (Vec<u32>, u32) {
        let mut out = vec![0u32; a.len()];
        let mut rem = 0u64;
        for i in (0..a.len()).rev() {
            let n = (rem << 32) | a[i] as u64;
            out[i] = (n / divisor as u64) as u32;
            rem = n % divisor as u64;
        }
        Self::trim(&mut out);
        (out, rem as u32)
    }

    // Knuth's normalized long division, with base 2^32 and 64-bit trial quotients.
    fn nat_divmod(a: &[u32], b: &[u32]) -> (Vec<u32>, Vec<u32>) {
        debug_assert!(!b.is_empty());
        if Self::nat_cmp(a, b) == std::cmp::Ordering::Less {
            return (Vec::new(), a.to_vec());
        }
        if b.len() == 1 {
            let (q, r) = Self::nat_div_small(a, b[0]);
            return (q, if r == 0 { Vec::new() } else { vec![r] });
        }
        let shift = b.last().unwrap().leading_zeros() as usize;
        let v = Self::nat_shl(b, shift);
        let mut u = Self::nat_shl(a, shift);
        u.resize(a.len() + 1, 0);
        let n = b.len();
        let m = a.len() - n;
        let base = 1u64 << 32;
        let mut quotient = vec![0u32; m + 1];
        for j in (0..=m).rev() {
            let numerator = ((u[j + n] as u64) << 32) | u[j + n - 1] as u64;
            let top = v[n - 1] as u64;
            let mut qhat = numerator / top;
            if qhat >= base {
                qhat = base - 1;
            }
            let mut rhat = numerator - qhat * top;
            while rhat < base && qhat * v[n - 2] as u64 > (rhat << 32) + u[j + n - 2] as u64 {
                qhat -= 1;
                rhat += top;
            }
            let mut borrow = 0u64;
            for i in 0..n {
                let product = qhat * v[i] as u64 + borrow;
                let low = product as u32 as u64;
                let old = u[j + i] as u64;
                u[j + i] = old.wrapping_sub(low) as u32;
                borrow = (product >> 32) + u64::from(old < low);
            }
            let negative = (u[j + n] as u64) < borrow;
            u[j + n] = (u[j + n] as u64).wrapping_sub(borrow) as u32;
            if negative {
                qhat -= 1;
                let mut carry = 0u64;
                for i in 0..n {
                    let total = u[j + i] as u64 + v[i] as u64 + carry;
                    u[j + i] = total as u32;
                    carry = total >> 32;
                }
                u[j + n] = (u[j + n] as u64 + carry) as u32;
            }
            quotient[j] = qhat as u32;
        }
        Self::trim(&mut quotient);
        let remainder = Self::nat_shr(&u[..n], shift);
        (quotient, remainder)
    }

    fn exact_add(&self, other: &Self) -> Self {
        if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
            if let Some(n) = a.checked_add(*b) {
                return Self::exact_small(n);
            }
        }
        let a = self.magnitude();
        let b = other.magnitude();
        if self.is_negative() == other.is_negative() {
            Self::exact_parts(self.is_negative(), Self::nat_add(&a, &b))
        } else {
            match Self::nat_cmp(&a, &b) {
                std::cmp::Ordering::Less => {
                    Self::exact_parts(other.is_negative(), Self::nat_sub(&b, &a))
                }
                _ => Self::exact_parts(self.is_negative(), Self::nat_sub(&a, &b)),
            }
        }
    }
    fn exact_neg(&self) -> Self {
        if let IntRepr::Small(n) = self.0 {
            if let Some(x) = n.checked_neg() {
                return Self::exact_small(x);
            }
        }
        Self::exact_parts(!self.is_negative(), self.magnitude().into_owned())
    }
    fn exact_mul(&self, other: &Self) -> Self {
        if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
            if let Some(n) = a.checked_mul(*b) {
                return Self::exact_small(n);
            }
        }
        Self::exact_parts(
            self.is_negative() ^ other.is_negative(),
            Self::nat_mul(&self.magnitude(), &other.magnitude()),
        )
    }
    fn add(&self, other: &Self) -> Self {
        if INT_BITS != 0 {
            if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
                return Self::from_i128(a.wrapping_add(*b));
            }
        }
        self.exact_add(other).normalized()
    }
    fn sub(&self, other: &Self) -> Self {
        if INT_BITS != 0 {
            if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
                return Self::from_i128(a.wrapping_sub(*b));
            }
        }
        self.exact_add(&other.exact_neg()).normalized()
    }
    fn mul(&self, other: &Self) -> Self {
        if INT_BITS != 0 {
            if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
                return Self::from_i128(a.wrapping_mul(*b));
            }
        }
        self.exact_mul(other).normalized()
    }
    fn neg(&self) -> Self {
        if INT_BITS != 0 {
            if let IntRepr::Small(n) = self.0 {
                return Self::from_i128(n.wrapping_neg());
            }
        }
        self.exact_neg().normalized()
    }
    fn abs(&self) -> Self {
        if self.is_negative() {
            self.neg()
        } else {
            self.clone()
        }
    }

    fn exact_divmod(&self, other: &Self) -> Result<(Self, Self), String> {
        if other.is_zero() {
            return Err("ZeroDivisionError: integer division or modulo by zero".into());
        }
        if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
            if let Some(mut q) = a.checked_div(*b) {
                let mut r = a % b;
                if r != 0 && (r < 0) != (*b < 0) {
                    q -= 1;
                    r += b;
                }
                return Ok((Self::exact_small(q), Self::exact_small(r)));
            }
        }
        let a = self.magnitude();
        let b = other.magnitude();
        let (mut q, mut r) = Self::nat_divmod(&a, &b);
        let different = self.is_negative() ^ other.is_negative();
        if different && !r.is_empty() {
            q = Self::nat_add(&q, &[1]);
            r = Self::nat_sub(&b, &r);
        }
        Ok((
            Self::exact_parts(different, q),
            Self::exact_parts(other.is_negative(), r),
        ))
    }
    fn divmod(&self, other: &Self) -> Result<(Self, Self), String> {
        self.exact_divmod(other)
            .map(|(q, r)| (q.normalized(), r.normalized()))
    }

    fn twos(&self, words: usize) -> Vec<u32> {
        let mut out = self.magnitude().into_owned();
        out.resize(words, 0);
        if self.is_negative() {
            let mut carry = 1u64;
            for n in &mut out {
                let total = (!*n) as u64 + carry;
                *n = total as u32;
                carry = total >> 32;
            }
        }
        out
    }
    fn bitop(&self, other: &Self, op: u8) -> Self {
        if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
            return Self::from_i128(match op {
                0 => a & b,
                1 => a | b,
                _ => a ^ b,
            });
        }
        let words = self.bit_length().max(other.bit_length()) / 32 + 1;
        let mut a = self.twos(words);
        let b = other.twos(words);
        for (x, y) in a.iter_mut().zip(b) {
            *x = match op {
                0 => *x & y,
                1 => *x | y,
                _ => *x ^ y,
            };
        }
        let negative = a.last().unwrap() & 0x8000_0000 != 0;
        if negative {
            let mut carry = 1u64;
            for x in &mut a {
                let n = (!*x) as u64 + carry;
                *x = n as u32;
                carry = n >> 32;
            }
        }
        Self::parts(negative, a)
    }
    fn bitand(&self, other: &Self) -> Self {
        self.bitop(other, 0)
    }
    fn bitor(&self, other: &Self) -> Self {
        self.bitop(other, 1)
    }
    fn bitxor(&self, other: &Self) -> Self {
        self.bitop(other, 2)
    }
    fn invert(&self) -> Self {
        if let IntRepr::Small(n) = self.0 {
            return Self::from_i128(!n);
        }
        self.exact_neg()
            .exact_add(&Self::exact_small(-1))
            .normalized()
    }
    fn shl(&self, shift: &Self) -> Result<Self, String> {
        if shift.is_negative() {
            return Err("ValueError: negative shift count".into());
        }
        if self.is_zero() {
            return Ok(Self::from_i128(0));
        }
        if INT_BITS != 0 {
            let n = shift.to_usize();
            if n.is_none() || n.unwrap() >= INT_BITS as usize {
                return Ok(Self::from_i128(0));
            }
            return Ok(Self::from_i128(
                self.to_i128().unwrap().wrapping_shl(n.unwrap() as u32),
            ));
        }
        let n = shift
            .to_usize()
            .ok_or_else(|| "OverflowError: too many digits in integer".to_string())?;
        let size = self
            .bit_length()
            .checked_add(n)
            .and_then(|x| x.checked_add(31))
            .map(|x| x / 32)
            .ok_or_else(|| "OverflowError: too many digits in integer".to_string())?;
        let mut digits = Vec::<u32>::new();
        digits
            .try_reserve_exact(size)
            .map_err(|_| "MemoryError: integer is too large".to_string())?;
        digits.resize(n / 32, 0);
        let mut carry = 0u64;
        for &limb in self.magnitude().iter() {
            let value = ((limb as u64) << (n % 32)) | carry;
            digits.push(value as u32);
            carry = value >> 32;
        }
        if carry != 0 {
            digits.push(carry as u32);
        }
        Ok(Self::exact_parts(self.is_negative(), digits))
    }
    fn shr(&self, shift: &Self) -> Result<Self, String> {
        if shift.is_negative() {
            return Err("ValueError: negative shift count".into());
        }
        let n = match shift.to_usize() {
            Some(n) if n < self.bit_length() => n,
            _ => return Ok(Self::from_i128(if self.is_negative() { -1 } else { 0 })),
        };
        if let IntRepr::Small(value) = self.0 {
            return Ok(Self::from_i128(value >> n));
        }
        let digits = self.magnitude();
        let mut out = Self::nat_shr(&digits, n);
        if self.is_negative() {
            let words = n / 32;
            let bits = n % 32;
            let discarded = digits[..words].iter().any(|&x| x != 0)
                || (bits != 0 && digits[words] & ((1u32 << bits) - 1) != 0);
            if discarded {
                out = Self::nat_add(&out, &[1]);
            }
        }
        Ok(Self::parts(self.is_negative(), out))
    }

    fn pow(&self, exponent: &Self) -> Result<Self, String> {
        if exponent.is_negative() {
            return Err("ValueError: negative exponent requires floating point power".into());
        }
        let mut result = Self::from_i128(1);
        let mut base = self.clone();
        let bits = exponent.bit_length();
        let digits = exponent.magnitude();
        for i in 0..bits {
            if digits[i / 32] & (1u32 << (i % 32)) != 0 {
                result = result.mul(&base);
            }
            if i + 1 < bits {
                base = base.mul(&base);
            }
        }
        Ok(result)
    }
    fn modpow(&self, exponent: &Self, modulus: &Self) -> Result<Self, String> {
        if modulus.is_zero() {
            return Err("ValueError: pow() 3rd argument cannot be 0".into());
        }
        let m = if modulus.is_negative() {
            modulus.exact_neg()
        } else {
            modulus.clone()
        };
        let mut base = self.exact_divmod(&m)?.1;
        if exponent.is_negative() {
            let (mut old_r, mut r) = (m.clone(), base);
            let (mut old_t, mut t) = (Self::exact_small(0), Self::exact_small(1));
            while !r.is_zero() {
                let (q, rem) = old_r.exact_divmod(&r)?;
                let next = old_t.exact_add(&q.exact_mul(&t).exact_neg());
                old_r = r;
                r = rem;
                old_t = t;
                t = next;
            }
            if old_r != Self::exact_small(1) {
                return Err("ValueError: base is not invertible for the given modulus".into());
            }
            base = old_t.exact_divmod(&m)?.1;
        }
        let mut result = Self::exact_small(1).exact_divmod(&m)?.1;
        let digits = exponent.magnitude();
        let bits = exponent.bit_length();
        for i in 0..bits {
            if digits[i / 32] & (1u32 << (i % 32)) != 0 {
                result = result.exact_mul(&base).exact_divmod(&m)?.1;
            }
            if i + 1 < bits {
                base = base.exact_mul(&base).exact_divmod(&m)?.1;
            }
        }
        if modulus.is_negative() && !result.is_zero() {
            result = result.exact_add(&m.exact_neg());
        }
        Ok(result.normalized())
    }

    fn decimal_digit(c: char) -> Option<u32> {
        if let Some(n) = c.to_digit(36) {
            return Some(n);
        }
        // Unicode Nd blocks. Mathematical digit styles are five adjacent blocks.
        const ZEROES: &[u32] = &[
            0x660, 0x6f0, 0x7c0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66,
            0xde6, 0xe50, 0xed0, 0xf20, 0x1040, 0x1090, 0x17e0, 0x1810, 0x1946, 0x19d0, 0x1a80,
            0x1a90, 0x1b50, 0x1bb0, 0x1c40, 0x1c50, 0xa620, 0xa8d0, 0xa900, 0xa9d0, 0xa9f0, 0xaa50,
            0xabf0, 0xff10, 0x104a0, 0x10d30, 0x10d40, 0x11066, 0x110f0, 0x11136, 0x111d0, 0x112f0,
            0x11450, 0x114d0, 0x11650, 0x116c0, 0x116d0, 0x116da, 0x11730, 0x118e0, 0x11950,
            0x11bf0, 0x11c50, 0x11d50, 0x11da0, 0x11f50, 0x16130, 0x16a60, 0x16ac0, 0x16b50,
            0x16d70, 0x1ccf0, 0x1d7ce, 0x1d7d8, 0x1d7e2, 0x1d7ec, 0x1d7f6, 0x1e140, 0x1e2f0,
            0x1e4f0, 0x1e5f1, 0x1e950, 0x1fbf0,
        ];
        let x = c as u32;
        ZEROES.iter().find_map(|&zero| {
            if x >= zero && x < zero + 10 {
                Some(x - zero)
            } else {
                None
            }
        })
    }
    fn parse(text: &str, mut base: u32) -> Result<Self, String> {
        let invalid = || "ValueError: invalid literal for int()".to_string();
        if base != 0 && !(2..=36).contains(&base) {
            return Err("ValueError: int() base must be >= 2 and <= 36, or 0".into());
        }
        let mut s = text.trim();
        let negative = s.starts_with('-');
        if s.starts_with('-') || s.starts_with('+') {
            s = &s[1..];
        }
        if s.is_empty() {
            return Err(invalid());
        }
        let auto = base == 0;
        let mut prefix = false;
        let mut prefix_chars = s.chars();
        let first = prefix_chars.next().unwrap();
        let second = prefix_chars.next();
        let detected = if Self::decimal_digit(first) == Some(0) {
            match second {
                Some('x' | 'X') => 16,
                Some('o' | 'O') => 8,
                Some('b' | 'B') => 2,
                _ => 0,
            }
        } else {
            0
        };
        if detected != 0 && (base == 0 || base == detected) {
            base = detected;
            s = &s[first.len_utf8() + 1..];
            prefix = true;
            if s.starts_with('_') {
                s = &s[1..];
            }
        }
        if base == 0 {
            base = 10;
        }
        let mut digits = Vec::<u32>::new();
        let mut previous_digit = false;
        let mut first_zero = false;
        let mut any_nonzero = false;
        let mut count = 0usize;
        for c in s.chars() {
            if c == '_' {
                if !previous_digit {
                    return Err(invalid());
                }
                previous_digit = false;
                continue;
            }
            let d = Self::decimal_digit(c)
                .filter(|&n| n < base)
                .ok_or_else(invalid)?;
            if count == 0 {
                first_zero = d == 0;
            }
            any_nonzero |= d != 0;
            let mut carry = d as u64;
            for limb in &mut digits {
                let n = *limb as u64 * base as u64 + carry;
                *limb = n as u32;
                carry = n >> 32;
            }
            if carry != 0 {
                digits.push(carry as u32);
            }
            previous_digit = true;
            count += 1;
        }
        if !previous_digit || count == 0 || (auto && !prefix && first_zero && any_nonzero) {
            return Err(invalid());
        }
        Ok(Self::parts(negative, digits))
    }

    fn exact_pow10(mut exponent: usize) -> Self {
        let mut result = Self::exact_small(1);
        let mut base = Self::exact_small(10);
        while exponent != 0 {
            if exponent & 1 != 0 {
                result = result.exact_mul(&base);
            }
            exponent >>= 1;
            if exponent != 0 {
                base = base.exact_mul(&base);
            }
        }
        result
    }

    // Work on exact internal integers: normalizing an intermediate divisor
    // would change rounding near a fixed-width integer's signed boundary.
    fn exact_round_ratio(numerator: &Self, denominator: &Self) -> Self {
        let (quotient, remainder) = numerator.exact_divmod(denominator).unwrap();
        let halfway = remainder.exact_mul(&Self::exact_small(2)).cmp(denominator);
        if halfway == std::cmp::Ordering::Greater
            || (halfway == std::cmp::Ordering::Equal
                && quotient.magnitude().first().is_some_and(|limb| limb & 1 != 0))
        {
            quotient.exact_add(&Self::exact_small(1))
        } else {
            quotient
        }
    }

    fn round_decimal(&self, ndigits: &Self) -> Self {
        if !ndigits.is_negative() || self.is_zero() {
            return self.clone();
        }
        // 10^(bits/3+2) exceeds every value of this bit length. Avoid
        // allocating a decimal power for an arbitrarily large ndigits.
        let bound = self.bit_length() / 3 + 2;
        let exponent = match ndigits.to_i128() {
            Some(n) if n.unsigned_abs() <= bound as u128 => n.unsigned_abs() as usize,
            _ => return Self::from_i128(0),
        };
        let scale = Self::exact_pow10(exponent);
        Self::exact_round_ratio(self, &scale).exact_mul(&scale).normalized()
    }

    fn round_float_decimal(value: f64, ndigits: &Self) -> Result<f64, String> {
        if !value.is_finite() || value == 0.0 {
            return Ok(value);
        }
        // These bounds cover every finite binary64, including subnormals.
        let digits = match ndigits.to_i128() {
            Some(n) if n >= 324 => return Ok(value),
            Some(n) if n <= -309 => return Ok(0.0f64.copysign(value)),
            Some(n) => n as i32,
            None if ndigits.is_negative() => return Ok(0.0f64.copysign(value)),
            None => return Ok(value),
        };
        let bits = value.to_bits();
        let exponent = ((bits >> 52) & 0x7ff) as i32;
        let fraction = bits & ((1u64 << 52) - 1);
        let mantissa = if exponent == 0 { fraction } else { fraction | (1u64 << 52) };
        let power = if exponent == 0 { -1074 } else { exponent - 1023 - 52 };
        let raw = vec![mantissa as u32, (mantissa >> 32) as u32];
        let mut numerator = Self::exact_parts(bits >> 63 != 0, if power >= 0 {
            Self::nat_shl(&raw, power as usize)
        } else {
            raw
        });
        let mut denominator = if power < 0 {
            Self::exact_parts(false, Self::nat_shl(&[1], (-power) as usize))
        } else {
            Self::exact_small(1)
        };
        let scale = Self::exact_pow10(digits.unsigned_abs() as usize);
        if digits >= 0 {
            numerator = numerator.exact_mul(&scale);
        } else {
            denominator = denominator.exact_mul(&scale);
        }
        let rounded = Self::exact_round_ratio(&numerator, &denominator);
        if rounded.is_zero() {
            return Ok(0.0f64.copysign(value));
        }
        if digits >= 0 {
            rounded.ratio(&scale)
        } else {
            rounded.exact_mul(&scale).ratio(&Self::exact_small(1))
        }
    }

    fn exact_from_f64(value: f64) -> Result<Self, String> {
        if value.is_nan() {
            return Err("ValueError: cannot convert float NaN to integer".into());
        }
        if value.is_infinite() {
            return Err("OverflowError: cannot convert float infinity to integer".into());
        }
        let bits = value.to_bits();
        let exp = ((bits >> 52) & 0x7ff) as i32;
        let mantissa = bits & ((1u64 << 52) - 1);
        let mantissa = if exp == 0 {
            mantissa
        } else {
            mantissa | (1u64 << 52)
        };
        let power = if exp == 0 { -1074 } else { exp - 1023 - 52 };
        let mut digits = vec![mantissa as u32, (mantissa >> 32) as u32];
        Self::trim(&mut digits);
        let digits = if power >= 0 {
            Self::nat_shl(&digits, power as usize)
        } else {
            Self::nat_shr(&digits, (-power) as usize)
        };
        Ok(Self::exact_parts(bits >> 63 != 0, digits))
    }
    fn from_f64(value: f64) -> Result<Self, String> {
        Self::exact_from_f64(value).map(Self::normalized)
    }
    // Comparisons must not use from_f64: that conversion wraps in fixed-width modes.
    fn cmp_f64(&self, value: f64) -> Option<std::cmp::Ordering> {
        use std::cmp::Ordering;
        if value.is_nan() {
            return None;
        }
        if value == f64::INFINITY {
            return Some(Ordering::Less);
        }
        if value == f64::NEG_INFINITY {
            return Some(Ordering::Greater);
        }
        let truncated = Self::exact_from_f64(value).unwrap();
        let order = self.cmp(&truncated);
        if order != Ordering::Equal || value.fract() == 0.0 {
            return Some(order);
        }
        Some(if value.is_sign_positive() {
            Ordering::Less
        } else {
            Ordering::Greater
        })
    }
    fn to_f64(&self) -> f64 {
        self.ratio(&Self::exact_small(1)).unwrap_or_else(|_| {
            if self.is_negative() {
                f64::NEG_INFINITY
            } else {
                f64::INFINITY
            }
        })
    }
    fn ratio(&self, denominator: &Self) -> Result<f64, String> {
        if denominator.is_zero() {
            return Err("ZeroDivisionError: division by zero".into());
        }
        let sign = u64::from(self.is_negative() ^ denominator.is_negative()) << 63;
        if self.is_zero() {
            return Ok(f64::from_bits(sign));
        }
        let a = self.magnitude();
        let b = denominator.magnitude();
        let mut exponent = Self::nat_bits(&a) as i128 - Self::nat_bits(&b) as i128;
        let overflow =
            || "OverflowError: integer division result too large for a float".to_string();
        if exponent > 1024 {
            return Err(overflow());
        }
        if exponent < -1075 {
            return Ok(f64::from_bits(sign));
        }
        let cmp = if exponent >= 0 {
            Self::nat_cmp(&a, &Self::nat_shl(&b, exponent as usize))
        } else {
            Self::nat_cmp(&Self::nat_shl(&a, (-exponent) as usize), &b)
        };
        if cmp == std::cmp::Ordering::Less {
            exponent -= 1;
        }
        if exponent > 1023 {
            return Err(overflow());
        }
        if exponent < -1075 {
            return Ok(f64::from_bits(sign));
        }
        let subnormal = exponent < -1022;
        let shift = if subnormal { 1074 } else { 52 - exponent };
        let (numerator, divisor) = if shift >= 0 {
            (Self::nat_shl(&a, shift as usize), b.into_owned())
        } else {
            (a.into_owned(), Self::nat_shl(&b, (-shift) as usize))
        };
        let (q, r) = Self::nat_divmod(&numerator, &divisor);
        let mut rounded = 0u64;
        for &limb in q.iter().rev() {
            rounded = (rounded << 32) | limb as u64;
        }
        let rounding = Self::nat_cmp(&Self::nat_shl(&r, 1), &divisor);
        if rounding == std::cmp::Ordering::Greater
            || (rounding == std::cmp::Ordering::Equal && rounded & 1 != 0)
        {
            rounded += 1;
        }
        if subnormal {
            return Ok(f64::from_bits(sign | rounded));
        }
        if rounded == 1u64 << 53 {
            rounded >>= 1;
            exponent += 1;
        }
        if exponent > 1023 {
            return Err(overflow());
        }
        let result = sign | (((exponent + 1023) as u64) << 52) | (rounded - (1u64 << 52));
        Ok(f64::from_bits(result))
    }
}

impl std::cmp::Ord for Int {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        if let (IntRepr::Small(a), IntRepr::Small(b)) = (&self.0, &other.0) {
            return a.cmp(b);
        }
        match (self.is_negative(), other.is_negative()) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            (negative, _) => {
                let order = Self::nat_cmp(&self.magnitude(), &other.magnitude());
                if negative {
                    order.reverse()
                } else {
                    order
                }
            }
        }
    }
}
impl std::cmp::PartialOrd for Int {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}
impl std::fmt::Display for Int {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if let IntRepr::Small(n) = self.0 {
            return write!(formatter, "{}", n);
        }
        let mut magnitude = self.magnitude().into_owned();
        let mut chunks = Vec::new();
        while !magnitude.is_empty() {
            let (q, r) = Self::nat_div_small(&magnitude, 1_000_000_000);
            chunks.push(r);
            magnitude = q;
        }
        if self.is_negative() {
            formatter.write_str("-")?;
        }
        if let Some(first) = chunks.pop() {
            write!(formatter, "{}", first)?;
        }
        for chunk in chunks.iter().rev() {
            write!(formatter, "{:09}", chunk)?;
        }
        Ok(())
    }
}
