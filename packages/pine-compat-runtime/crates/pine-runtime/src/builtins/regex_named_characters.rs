pub(crate) struct PineRegexNamedCharacterEscape {
    pub(crate) end: usize,
    pub(crate) scalar: char,
}

const JAVA_CONTROL_NAMES: &[(char, &str)] = &[
    ('\u{0000}', "NULL"),
    ('\u{0001}', "START OF HEADING"),
    ('\u{0002}', "START OF TEXT"),
    ('\u{0003}', "END OF TEXT"),
    ('\u{0004}', "END OF TRANSMISSION"),
    ('\u{0005}', "ENQUIRY"),
    ('\u{0006}', "ACKNOWLEDGE"),
    ('\u{0007}', "BEL"),
    ('\u{0008}', "BACKSPACE"),
    ('\u{0009}', "CHARACTER TABULATION"),
    ('\u{000A}', "LINE FEED (LF)"),
    ('\u{000B}', "LINE TABULATION"),
    ('\u{000C}', "FORM FEED (FF)"),
    ('\u{000D}', "CARRIAGE RETURN (CR)"),
    ('\u{000E}', "SHIFT OUT"),
    ('\u{000F}', "SHIFT IN"),
    ('\u{0010}', "DATA LINK ESCAPE"),
    ('\u{0011}', "DEVICE CONTROL ONE"),
    ('\u{0012}', "DEVICE CONTROL TWO"),
    ('\u{0013}', "DEVICE CONTROL THREE"),
    ('\u{0014}', "DEVICE CONTROL FOUR"),
    ('\u{0015}', "NEGATIVE ACKNOWLEDGE"),
    ('\u{0016}', "SYNCHRONOUS IDLE"),
    ('\u{0017}', "END OF TRANSMISSION BLOCK"),
    ('\u{0018}', "CANCEL"),
    ('\u{0019}', "END OF MEDIUM"),
    ('\u{001A}', "SUBSTITUTE"),
    ('\u{001B}', "ESCAPE"),
    ('\u{001C}', "INFORMATION SEPARATOR FOUR"),
    ('\u{001D}', "INFORMATION SEPARATOR THREE"),
    ('\u{001E}', "INFORMATION SEPARATOR TWO"),
    ('\u{001F}', "INFORMATION SEPARATOR ONE"),
    ('\u{007F}', "DELETE"),
    ('\u{0080}', "PADDING CHARACTER"),
    ('\u{0081}', "HIGH OCTET PRESET"),
    ('\u{0082}', "BREAK PERMITTED HERE"),
    ('\u{0083}', "NO BREAK HERE"),
    ('\u{0084}', "LATIN 1 SUPPLEMENT 84"),
    ('\u{0085}', "NEXT LINE (NEL)"),
    ('\u{0086}', "START OF SELECTED AREA"),
    ('\u{0087}', "END OF SELECTED AREA"),
    ('\u{0088}', "CHARACTER TABULATION SET"),
    ('\u{0089}', "CHARACTER TABULATION WITH JUSTIFICATION"),
    ('\u{008A}', "LINE TABULATION SET"),
    ('\u{008B}', "PARTIAL LINE FORWARD"),
    ('\u{008C}', "PARTIAL LINE BACKWARD"),
    ('\u{008D}', "REVERSE LINE FEED"),
    ('\u{008E}', "SINGLE SHIFT TWO"),
    ('\u{008F}', "SINGLE SHIFT THREE"),
    ('\u{0090}', "DEVICE CONTROL STRING"),
    ('\u{0091}', "PRIVATE USE ONE"),
    ('\u{0092}', "PRIVATE USE TWO"),
    ('\u{0093}', "SET TRANSMIT STATE"),
    ('\u{0094}', "CANCEL CHARACTER"),
    ('\u{0095}', "MESSAGE WAITING"),
    ('\u{0096}', "START OF GUARDED AREA"),
    ('\u{0097}', "END OF GUARDED AREA"),
    ('\u{0098}', "START OF STRING"),
    ('\u{0099}', "SINGLE GRAPHIC CHARACTER INTRODUCER"),
    ('\u{009A}', "SINGLE CHARACTER INTRODUCER"),
    ('\u{009B}', "CONTROL SEQUENCE INTRODUCER"),
    ('\u{009C}', "STRING TERMINATOR"),
    ('\u{009D}', "OPERATING SYSTEM COMMAND"),
    ('\u{009E}', "PRIVACY MESSAGE"),
    ('\u{009F}', "APPLICATION PROGRAM COMMAND"),
];

fn trim_java_character_name(name: &str) -> &str {
    name.trim_matches(|ch| ch <= '\u{0020}')
}

fn java_generated_character(name: &str) -> Option<char> {
    const RANGES: &[(&str, u32, u32)] = &[
        ("CJK UNIFIED IDEOGRAPHS EXTENSION A ", 0x3400, 0x4DBF),
        ("CJK UNIFIED IDEOGRAPHS ", 0x4E00, 0x9FFF),
        ("HANGUL SYLLABLES ", 0xAC00, 0xD7A3),
        ("TANGUT ", 0x17000, 0x187F7),
        ("TANGUT SUPPLEMENT ", 0x18D00, 0x18D08),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION B ", 0x20000, 0x2A6DF),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION C ", 0x2A700, 0x2B739),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION D ", 0x2B740, 0x2B81D),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION E ", 0x2B820, 0x2CEA1),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION F ", 0x2CEB0, 0x2EBE0),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION I ", 0x2EBF0, 0x2EE5D),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION G ", 0x30000, 0x3134A),
        ("CJK UNIFIED IDEOGRAPHS EXTENSION H ", 0x31350, 0x323AF),
    ];

    RANGES.iter().find_map(|(prefix, start, end)| {
        let candidate_prefix = name.get(..prefix.len())?;
        if !candidate_prefix.eq_ignore_ascii_case(prefix) {
            return None;
        }
        let suffix = name.get(prefix.len()..)?;
        if suffix.is_empty() || !suffix.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return None;
        }
        let scalar = u32::from_str_radix(suffix, 16).ok()?;
        let canonical_width = if scalar == 0 {
            1
        } else {
            ((u32::BITS - scalar.leading_zeros()).div_ceil(4)) as usize
        };
        (suffix.len() == canonical_width && (*start..=*end).contains(&scalar))
            .then(|| char::from_u32(scalar))?
    })
}

fn java_named_character(name: &str) -> Option<char> {
    let name = trim_java_character_name(name);
    if name.is_empty() {
        return None;
    }
    if let Some((ch, _)) = JAVA_CONTROL_NAMES
        .iter()
        .find(|(_, candidate)| candidate.eq_ignore_ascii_case(name))
    {
        return Some(*ch);
    }
    if let Some(ch) = java_generated_character(name) {
        return Some(ch);
    }

    let ch = unicode_names2::character(name)?;
    let canonical = unicode_names2::name(ch)?.to_string();
    if canonical.starts_with("CJK UNIFIED IDEOGRAPH-") || canonical.starts_with("HANGUL SYLLABLE ")
    {
        return None;
    }
    canonical.eq_ignore_ascii_case(name).then_some(ch)
}

pub(crate) fn parse_pine_regex_named_character_escape(
    pattern: &str,
    index: usize,
) -> Option<PineRegexNamedCharacterEscape> {
    if pattern.as_bytes().get(index..index + 3) != Some(br"\N{") {
        return None;
    }
    let name_start = index + 3;
    let name_len = pattern.get(name_start..)?.find('}')?;
    let end = name_start + name_len + 1;
    let scalar = java_named_character(pattern.get(name_start..name_start + name_len)?)?;
    Some(PineRegexNamedCharacterEscape { end, scalar })
}

#[cfg(test)]
mod tests {
    use super::{java_named_character, parse_pine_regex_named_character_escape};

    #[test]
    fn resolves_exact_java_unicode_names_and_controls() {
        for (name, expected) in [
            ("LATIN CAPITAL LETTER A", 'A'),
            ("latin capital letter a", 'A'),
            (" GRINNING FACE ", '😀'),
            ("NULL", '\u{0000}'),
            ("bel", '\u{0007}'),
            ("LINE FEED (LF)", '\n'),
            ("NEXT LINE (NEL)", '\u{0085}'),
            ("DELETE", '\u{007F}'),
        ] {
            assert_eq!(java_named_character(name), Some(expected), "{name}");
        }
    }

    #[test]
    fn resolves_java_generated_algorithmic_names() {
        for (name, expected) in [
            ("CJK UNIFIED IDEOGRAPHS EXTENSION A 3400", '\u{3400}'),
            ("CJK UNIFIED IDEOGRAPHS 4E00", '\u{4E00}'),
            ("cjk unified ideographs extension b 20000", '\u{20000}'),
            ("CJK UNIFIED IDEOGRAPHS EXTENSION I 2EBF0", '\u{2EBF0}'),
            ("CJK UNIFIED IDEOGRAPHS EXTENSION H 323AF", '\u{323AF}'),
            ("HANGUL SYLLABLES AC00", '\u{AC00}'),
            ("TANGUT 17000", '\u{17000}'),
            ("TANGUT SUPPLEMENT 18D00", '\u{18D00}'),
        ] {
            assert_eq!(java_named_character(name), Some(expected), "{name}");
        }
    }

    #[test]
    fn rejects_loose_and_algorithmic_names_that_java_rejects() {
        for name in [
            "",
            "LATIN_CAPITAL_LETTER_A",
            "LATINCAPITALLETTERA",
            "LATIN  CAPITAL LETTER A",
            "LATIN\tCAPITAL LETTER A",
            "CJK UNIFIED IDEOGRAPH-4E00",
            "HANGUL SYLLABLE GA",
            "CJK UNIFIED IDEOGRAPHS 04E00",
            "CJK UNIFIED IDEOGRAPHS EXTENSION B 2A6FF",
            "CJK UNIFIED IDEOGRAPHS EXTENSION B 4E00",
            "HANGUL SYLLABLES D7A4",
            "TANGUT 18D00",
            "NO SUCH NAME",
        ] {
            assert_eq!(java_named_character(name), None, "{name}");
        }
    }

    #[test]
    fn parses_named_character_escape_boundaries() {
        let parsed = parse_pine_regex_named_character_escape(r"\N{LATIN CAPITAL LETTER A}tail", 0)
            .expect("valid named character escape");
        assert_eq!(parsed.scalar, 'A');
        assert_eq!(parsed.end, r"\N{LATIN CAPITAL LETTER A}".len());

        assert!(parse_pine_regex_named_character_escape(r"\N{}", 0).is_none());
        assert!(parse_pine_regex_named_character_escape(r"\N{NO SUCH NAME}", 0).is_none());
        assert!(parse_pine_regex_named_character_escape(r"\N", 0).is_none());
    }
}
