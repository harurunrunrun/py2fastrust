// Single-character Unicode names for Python's non-raw string literal decoder.
// Data use Unicode License V3; algorithmic lookup is an independent implementation.
fn unicode_character_name(name: &str) -> Option<char> {
    if !name.is_ascii() {
        return None;
    }
    let name = name.to_ascii_uppercase();
    if let Ok(index) =
        UNICODE_CHARACTER_NAMES.binary_search_by(|(candidate, _)| candidate.cmp(&name.as_str()))
    {
        return char::from_u32(UNICODE_CHARACTER_NAMES[index].1);
    }
    if let Some(syllable) = name.strip_prefix("HANGUL SYLLABLE ") {
        const LEADS: [&str; 19] = [
            "G", "GG", "N", "D", "DD", "R", "M", "B", "BB", "S", "SS", "", "J", "JJ", "C", "K",
            "T", "P", "H",
        ];
        const VOWELS: [&str; 21] = [
            "A", "AE", "YA", "YAE", "EO", "E", "YEO", "YE", "O", "WA", "WAE", "OE", "YO", "U",
            "WEO", "WE", "WI", "YU", "EU", "YI", "I",
        ];
        const TAILS: [&str; 28] = [
            "", "G", "GG", "GS", "N", "NJ", "NH", "D", "L", "LG", "LM", "LB", "LS", "LT", "LP",
            "LH", "M", "B", "BS", "S", "SS", "NG", "J", "C", "K", "T", "P", "H",
        ];
        for (lead, prefix) in LEADS.iter().enumerate() {
            if let Some(after_lead) = syllable.strip_prefix(*prefix) {
                for (vowel, prefix) in VOWELS.iter().enumerate() {
                    if let Some(tail) = after_lead.strip_prefix(*prefix) {
                        if let Some(tail) = TAILS.iter().position(|candidate| *candidate == tail) {
                            return char::from_u32(
                                0xac00 + ((lead * 21 + vowel) * 28 + tail) as u32,
                            );
                        }
                    }
                }
            }
        }
        return None;
    }
    for (prefix, ranges) in UNICODE_ALGORITHMIC_NAMES {
        let Some(suffix) = name
            .strip_prefix(*prefix)
            .and_then(|value| value.strip_prefix('-'))
        else {
            continue;
        };
        if !(4..=6).contains(&suffix.len()) {
            return None;
        }
        let point = u32::from_str_radix(suffix, 16).ok()?;
        if suffix != format!("{point:04X}")
            || !ranges
                .iter()
                .any(|(first, last)| *first <= point && point <= *last)
        {
            return None;
        }
        return char::from_u32(point);
    }
    None
}
