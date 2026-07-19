use std::fmt::Write as _;

#[derive(Clone, Copy, Default)]
pub(crate) struct PineRegexMode {
    pub(crate) unicode_classes: bool,
    pub(crate) unicode_case: bool,
    pub(crate) case_insensitive: bool,
    pub(crate) verbose: bool,
    pub(crate) multiline: bool,
    pub(crate) dotall: bool,
    pub(crate) unix_lines: bool,
}

pub(crate) struct PineRegexFlags<'a> {
    pub(crate) end: usize,
    pub(crate) scoped: bool,
    enabled: &'a str,
    disabled: &'a str,
}

pub(crate) fn parse_pine_regex_flags(pattern: &str, start: usize) -> Option<PineRegexFlags<'_>> {
    let bytes = pattern.as_bytes();
    if bytes.get(start..start + 2) != Some(b"(?") {
        return None;
    }

    let flags_start = start + 2;
    let mut index = flags_start;
    let mut separator = None;
    while let Some(&byte) = bytes.get(index) {
        match byte {
            b'd' | b'i' | b'm' | b's' | b'u' | b'U' | b'x' => index += 1,
            b'-' if separator.is_none() => {
                separator = Some(index);
                index += 1;
            }
            b':' | b')' => break,
            _ => return None,
        }
    }

    let terminator = *bytes.get(index)?;
    if !matches!(terminator, b':' | b')') {
        return None;
    }
    let split = separator.unwrap_or(index);
    if (separator.is_none() && split == flags_start && terminator == b')')
        || separator.is_some_and(|separator| separator + 1 == index)
    {
        return None;
    }
    Some(PineRegexFlags {
        end: index + 1,
        scoped: terminator == b':',
        enabled: &pattern[flags_start..split],
        disabled: if separator.is_some() {
            &pattern[split + 1..index]
        } else {
            ""
        },
    })
}

pub(crate) fn apply_pine_regex_flags(
    mode: PineRegexMode,
    flags: &PineRegexFlags<'_>,
) -> PineRegexMode {
    let mut mode = mode;
    if flags.enabled.contains('U') {
        mode.unicode_classes = true;
        mode.unicode_case = true;
    }
    if flags.enabled.contains('u') {
        mode.unicode_case = true;
    }
    if flags.disabled.contains('U') {
        mode.unicode_classes = false;
        mode.unicode_case = false;
    }
    if flags.disabled.contains('u') {
        mode.unicode_case = false;
    }
    if flags.enabled.contains('i') {
        mode.case_insensitive = true;
    }
    if flags.disabled.contains('i') {
        mode.case_insensitive = false;
    }
    if flags.enabled.contains('x') {
        mode.verbose = true;
    }
    if flags.disabled.contains('x') {
        mode.verbose = false;
    }
    if flags.enabled.contains('m') {
        mode.multiline = true;
    }
    if flags.disabled.contains('m') {
        mode.multiline = false;
    }
    if flags.enabled.contains('s') {
        mode.dotall = true;
    }
    if flags.disabled.contains('s') {
        mode.dotall = false;
    }
    if flags.enabled.contains('d') {
        mode.unix_lines = true;
    }
    if flags.disabled.contains('d') {
        mode.unix_lines = false;
    }
    mode
}

pub(crate) fn push_rust_regex_flags(result: &mut String, flags: &PineRegexFlags<'_>) {
    let enabled = flags.enabled.replace(['d', 'u', 'U'], "");
    let disabled = flags.disabled.replace(['d', 'u', 'U'], "");
    if enabled.is_empty() && disabled.is_empty() {
        if flags.scoped {
            result.push_str("(?:");
        }
        return;
    }

    result.push_str("(?");
    result.push_str(&enabled);
    if !disabled.is_empty() {
        result.push('-');
        result.push_str(&disabled);
    }
    result.push(if flags.scoped { ':' } else { ')' });
}

pub(crate) fn push_pine_regex_literal(
    result: &mut String,
    ch: char,
    mode: PineRegexMode,
    must_escape: bool,
) {
    if mode.case_insensitive && !mode.unicode_case {
        if ch.is_ascii_alphabetic() {
            write!(result, r"(?i-u:\x{{{:X}}})", ch as u32)
                .expect("writing to a String cannot fail");
            return;
        }
        if !ch.is_ascii() {
            write!(result, r"(?-i:\x{{{:X}}})", ch as u32)
                .expect("writing to a String cannot fail");
            return;
        }
    }

    if must_escape {
        write!(result, r"\x{{{:X}}}", ch as u32).expect("writing to a String cannot fail");
    } else {
        result.push(ch);
    }
}

pub(crate) fn push_pine_regex_reference(
    result: &mut String,
    ch: char,
    mode: PineRegexMode,
    class_depth: usize,
    hex_width: usize,
) {
    if class_depth == 0 && mode.case_insensitive && !mode.unicode_case {
        push_pine_regex_literal(result, ch, mode, true);
    } else {
        write!(result, r"\x{{{:0width$X}}}", ch as u32, width = hex_width)
            .expect("writing to a String cannot fail");
    }
}

pub(crate) fn push_pine_regex_quoted(
    result: &mut String,
    quoted: &str,
    mode: PineRegexMode,
    inside_class: bool,
) {
    for ch in quoted.chars() {
        if inside_class {
            write!(result, r"\x{{{:X}}}", ch as u32).expect("writing to a String cannot fail");
        } else {
            push_pine_regex_literal(result, ch, mode, true);
        }
    }
}
