pub(crate) struct PineRegexCodePointEscape {
    pub(crate) end: usize,
    pub(crate) hex_width: usize,
    pub(crate) scalar: Option<char>,
}

pub(crate) struct PineRegexControlEscape {
    pub(crate) end: usize,
    pub(crate) scalar: char,
}

pub(crate) struct PineRegexOctalEscape {
    pub(crate) end: usize,
    pub(crate) scalar: char,
}

struct PineRegexToken {
    start: usize,
    end: usize,
    scalar: char,
}

fn is_verbose_ascii_space(ch: char) -> bool {
    matches!(ch, ' ' | '\t' | '\n' | '\u{000b}' | '\u{000c}' | '\r')
}

pub(crate) fn is_pine_regex_line_separator(ch: char) -> bool {
    matches!(ch, '\n' | '\r' | '\u{0085}' | '\u{2028}' | '\u{2029}')
}

fn next_escape_token(pattern: &str, mut index: usize, verbose: bool) -> Option<PineRegexToken> {
    loop {
        let ch = pattern.get(index..)?.chars().next()?;
        let end = index + ch.len_utf8();
        if !verbose {
            return Some(PineRegexToken {
                start: index,
                end,
                scalar: ch,
            });
        }
        if is_verbose_ascii_space(ch) {
            index = end;
            continue;
        }
        if ch != '#' {
            return Some(PineRegexToken {
                start: index,
                end,
                scalar: ch,
            });
        }

        index = end;
        while let Some(comment_ch) = pattern.get(index..)?.chars().next() {
            let comment_end = index + comment_ch.len_utf8();
            if matches!(comment_ch, '\n' | '\r') {
                index = comment_end;
                break;
            }
            // Java ends the comment at every line separator, but its verbose
            // whitespace pass only skips ASCII separators. The remaining
            // separators therefore become the next escape token.
            if is_pine_regex_line_separator(comment_ch) {
                return Some(PineRegexToken {
                    start: index,
                    end: comment_end,
                    scalar: comment_ch,
                });
            }
            index = comment_end;
        }
    }
}

pub(crate) fn parse_pine_regex_control_escape(
    pattern: &str,
    index: usize,
    verbose: bool,
) -> Option<PineRegexControlEscape> {
    if pattern.as_bytes().get(index..index + 2) != Some(br"\c") {
        return None;
    }
    let target = next_escape_token(pattern, index + 2, verbose)?;
    let scalar = char::from_u32((target.scalar as u32) ^ 0x40)
        .expect("XORing a Unicode scalar with 0x40 preserves scalar validity");
    Some(PineRegexControlEscape {
        end: target.end,
        scalar,
    })
}

pub(crate) fn parse_pine_regex_octal_escape(
    pattern: &str,
    index: usize,
    verbose: bool,
) -> Option<PineRegexOctalEscape> {
    if pattern.as_bytes().get(index..index + 2) != Some(br"\0") {
        return None;
    }

    let first = next_escape_token(pattern, index + 2, verbose)?;
    let first_digit = first.scalar.to_digit(8)?;
    let mut value = first_digit;
    let mut end = first.end;

    let Some(second) = next_escape_token(pattern, end, verbose) else {
        return Some(PineRegexOctalEscape {
            end,
            scalar: char::from_u32(value).expect("an octal byte is a Unicode scalar"),
        });
    };
    let Some(second_digit) = second.scalar.to_digit(8) else {
        return Some(PineRegexOctalEscape {
            end: second.start,
            scalar: char::from_u32(value).expect("an octal byte is a Unicode scalar"),
        });
    };
    value = value * 8 + second_digit;
    end = second.end;

    if let Some(third) = next_escape_token(pattern, end, verbose) {
        if first_digit <= 3
            && let Some(third_digit) = third.scalar.to_digit(8)
        {
            value = value * 8 + third_digit;
            end = third.end;
        } else {
            end = third.start;
        }
    }

    Some(PineRegexOctalEscape {
        end,
        scalar: char::from_u32(value).expect("an octal byte is a Unicode scalar"),
    })
}

fn parse_hex_scalar(digits: &str) -> Option<Option<char>> {
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }

    let significant = digits.trim_start_matches('0');
    let value = if significant.is_empty() {
        0
    } else {
        if significant.len() > 6 {
            return None;
        }
        u32::from_str_radix(significant, 16).ok()?
    };
    if value > 0x10_FFFF {
        return None;
    }
    Some(char::from_u32(value))
}

pub(crate) fn parse_pine_regex_code_point_escape(
    pattern: &str,
    index: usize,
) -> Option<PineRegexCodePointEscape> {
    let bytes = pattern.as_bytes();
    if bytes.get(index) != Some(&b'\\') {
        return None;
    }

    let kind = *bytes.get(index + 1)?;
    let digits_start = index + 2;
    let (digits, end, hex_width) = match kind {
        b'u' => (
            pattern.get(digits_start..digits_start + 4)?,
            digits_start + 4,
            4,
        ),
        b'x' if bytes.get(digits_start) == Some(&b'{') => {
            let digits_start = digits_start + 1;
            let digits_len = pattern.get(digits_start..)?.find('}')?;
            let end = digits_start + digits_len + 1;
            (
                pattern.get(digits_start..digits_start + digits_len)?,
                end,
                0,
            )
        }
        b'x' => (
            pattern.get(digits_start..digits_start + 2)?,
            digits_start + 2,
            2,
        ),
        _ => return None,
    };

    Some(PineRegexCodePointEscape {
        end,
        hex_width,
        scalar: parse_hex_scalar(digits)?,
    })
}

#[cfg(test)]
mod tests {
    use super::{
        parse_pine_regex_code_point_escape, parse_pine_regex_control_escape,
        parse_pine_regex_octal_escape,
    };

    #[test]
    fn parses_fixed_and_braced_code_point_escapes() {
        let fixed = parse_pine_regex_code_point_escape(r"\x6B0", 0).expect("fixed hex escape");
        assert_eq!(fixed.scalar, Some('k'));
        assert_eq!(fixed.end, 4);
        assert_eq!(fixed.hex_width, 2);

        let unicode =
            parse_pine_regex_code_point_escape(r"\u03B2x", 0).expect("fixed Unicode escape");
        assert_eq!(unicode.scalar, Some('β'));
        assert_eq!(unicode.end, 6);
        assert_eq!(unicode.hex_width, 4);

        let braced = parse_pine_regex_code_point_escape(r"\x{0000006B}0", 0)
            .expect("braced hex escape with leading zeros");
        assert_eq!(braced.scalar, Some('k'));
        assert_eq!(braced.end, 12);
        assert_eq!(braced.hex_width, 0);
    }

    #[test]
    fn distinguishes_surrogates_from_invalid_code_points() {
        let surrogate =
            parse_pine_regex_code_point_escape(r"\x{D800}", 0).expect("surrogate escape");
        assert_eq!(surrogate.scalar, None);

        assert!(parse_pine_regex_code_point_escape(r"\x{}", 0).is_none());
        assert!(parse_pine_regex_code_point_escape(r"\x{110000}", 0).is_none());
        assert!(parse_pine_regex_code_point_escape(r"\xG1", 0).is_none());
        assert!(parse_pine_regex_code_point_escape(r"\u123", 0).is_none());
    }

    #[test]
    fn parses_control_escapes_and_verbose_trivia() {
        let upper =
            parse_pine_regex_control_escape(r"\cAB", 0, false).expect("uppercase control escape");
        assert_eq!(upper.scalar, '\u{0001}');
        assert_eq!(upper.end, 3);

        let lowercase =
            parse_pine_regex_control_escape(r"\ca", 0, false).expect("lowercase control escape");
        assert_eq!(lowercase.scalar, '!');

        let supplementary = parse_pine_regex_control_escape(r"\c😀", 0, false)
            .expect("supplementary control escape");
        assert_eq!(supplementary.scalar, '🙀');

        let verbose = parse_pine_regex_control_escape("\\c # note\n A", 0, true)
            .expect("verbose control escape");
        assert_eq!(verbose.scalar, '\u{0001}');
        assert_eq!(verbose.end, "\\c # note\n A".len());

        let unicode_separator = parse_pine_regex_control_escape("\\c# note\u{2028}A", 0, true)
            .expect("Unicode comment terminator becomes the control target");
        assert_eq!(unicode_separator.scalar, '\u{2068}');
        assert_eq!(unicode_separator.end, "\\c# note\u{2028}".len());

        assert!(parse_pine_regex_control_escape(r"\c", 0, false).is_none());
    }

    #[test]
    fn parses_pine_octal_width_and_verbose_trivia() {
        for (pattern, scalar, end) in [
            (r"\01", '\u{0001}', 3),
            (r"\077x", '?', 4),
            (r"\0377x", 'ÿ', 5),
            (r"\0777", '?', 4),
            (r"\0400", ' ', 4),
            (r"\0128", '\n', 4),
        ] {
            let parsed = parse_pine_regex_octal_escape(pattern, 0, false)
                .unwrap_or_else(|| panic!("valid octal escape {pattern}"));
            assert_eq!(parsed.scalar, scalar, "{pattern}");
            assert_eq!(parsed.end, end, "{pattern}");
        }

        let verbose = parse_pine_regex_octal_escape("\\0 1 # note\n 6 1", 0, true)
            .expect("verbose octal escape");
        assert_eq!(verbose.scalar, 'q');
        assert_eq!(verbose.end, "\\0 1 # note\n 6 1".len());

        assert!(parse_pine_regex_octal_escape(r"\0", 0, false).is_none());
        assert!(parse_pine_regex_octal_escape(r"\08", 0, false).is_none());
    }
}
