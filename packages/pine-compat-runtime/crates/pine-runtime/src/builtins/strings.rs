use std::fmt::Write as _;

use pine_ir::{HirCallArg, HirExpr, HirUserTypeInfo};
use regex::Regex;

use super::{
    regex_character_classes::{
        PineRegexClassPrefix, PineRegexClassReplacementCase, apply_pine_java_empty_intersection,
        next_pine_regex_class_token, normalize_case_insensitive_class,
        pine_java_ampersand_continuation, pine_java_empty_intersection, pine_posix_class,
        pine_unicode_block_property, push_case_folded_class,
        push_case_insensitive_class_replacement, push_pine_unicode_block, resolve_java_bits,
    },
    regex_escapes::{
        is_pine_regex_line_separator, parse_pine_regex_code_point_escape,
        parse_pine_regex_control_escape, parse_pine_regex_octal_escape,
    },
    regex_java_properties::pine_java_property,
    regex_modes::{
        PineRegexMode, apply_pine_regex_flags, parse_pine_regex_flags, push_pine_regex_literal,
        push_pine_regex_quoted, push_pine_regex_reference, push_rust_regex_flags,
    },
    regex_named_characters::parse_pine_regex_named_character_escape,
    regex_unicode_blocks::pine_unicode_block,
};
use crate::builtins::time::{
    format_datetime_with_timezone, format_fixed_timezone_offset, format_utc_datetime,
    timezone_offset_and_short_name, utc_datetime_from_millis,
};
use crate::*;

pub(crate) fn replace_nth_non_overlapping(
    source: &str,
    target: &str,
    replacement: &str,
    occurrence: usize,
) -> String {
    let Some((byte_index, _)) = source.match_indices(target).nth(occurrence) else {
        return source.to_owned();
    };
    let mut result = String::with_capacity(source.len() + replacement.len());
    result.push_str(&source[..byte_index]);
    result.push_str(replacement);
    result.push_str(&source[byte_index + target.len()..]);
    result
}

pub(crate) fn replace_zero_width_occurrence(
    source: &str,
    replacement: &str,
    occurrence: usize,
) -> String {
    let char_count = source.chars().count();
    if occurrence > char_count {
        return source.to_owned();
    }

    let mut result = String::with_capacity(source.len() + replacement.len());
    if occurrence == 0 {
        result.push_str(replacement);
    }
    for (index, ch) in source.chars().enumerate() {
        result.push(ch);
        if index + 1 == occurrence {
            result.push_str(replacement);
        }
    }
    result
}

pub(crate) fn replace_all_zero_width_boundaries(source: &str, replacement: &str) -> String {
    let mut result =
        String::with_capacity(source.len() + replacement.len() * (source.chars().count() + 1));
    result.push_str(replacement);
    for ch in source.chars() {
        result.push(ch);
        result.push_str(replacement);
    }
    result
}

pub(crate) fn is_pine_numeric_string(value: &str) -> bool {
    let unsigned = value.strip_prefix(['+', '-']).unwrap_or(value);
    let (significand, exponent) = match unsigned.split_once(['e', 'E']) {
        Some((significand, exponent)) => (significand, Some(exponent)),
        None => (unsigned, None),
    };
    if unsigned
        .chars()
        .filter(|ch| matches!(ch, 'e' | 'E'))
        .count()
        > 1
    {
        return false;
    }

    let mut saw_digit = false;
    let mut saw_decimal = false;
    for ch in significand.chars() {
        if ch.is_ascii_digit() {
            saw_digit = true;
        } else if ch == '.' && !saw_decimal {
            saw_decimal = true;
        } else {
            return false;
        }
    }
    if !saw_digit {
        return false;
    }

    if let Some(exponent) = exponent {
        let exponent = exponent.strip_prefix(['+', '-']).unwrap_or(exponent);
        !exponent.is_empty() && exponent.chars().all(|ch| ch.is_ascii_digit())
    } else {
        true
    }
}

struct NormalizedPineRegex {
    pattern: String,
    final_newline_captures: Vec<String>,
}

fn is_verbose_ascii_space(byte: u8) -> bool {
    matches!(byte, b' ' | b'\t' | b'\n' | 0x0B | 0x0C | b'\r')
}

fn mark_pine_regex_class_scalar(class_prefixes: &mut [PineRegexClassPrefix]) {
    if let Some(prefix) = class_prefixes.last_mut() {
        prefix.mark_scalar();
    }
}

fn mark_pine_regex_class_set(result: &mut String, class_prefixes: &mut [PineRegexClassPrefix]) {
    if class_prefixes
        .last_mut()
        .is_some_and(PineRegexClassPrefix::mark_set)
    {
        result.push_str(r"\p{__PineInvalidJavaRange}");
    }
}

fn mark_pine_regex_quoted_scalars(quoted: &str, class_prefixes: &mut [PineRegexClassPrefix]) {
    if let Some(prefix) = class_prefixes.last_mut() {
        for _ in quoted.chars() {
            prefix.mark_scalar();
        }
    }
}

fn push_pine_regex_final_anchor(
    result: &mut String,
    capture_names: &mut Vec<String>,
    capture_prefix: &str,
) {
    let name = format!("{capture_prefix}{}", capture_names.len());
    write!(result, r"(?:\z|(?P<{name}>\n)\z)").expect("writing to a String cannot fail");
    capture_names.push(name);
}

fn normalize_pine_regex_with_metadata(pattern: &str) -> NormalizedPineRegex {
    const HORIZONTAL_WHITESPACE: &str =
        r"[ \t\x{00A0}\x{1680}\x{180E}\x{2000}-\x{200A}\x{202F}\x{205F}\x{3000}]";
    const NON_HORIZONTAL_WHITESPACE: &str =
        r"[^ \t\x{00A0}\x{1680}\x{180E}\x{2000}-\x{200A}\x{202F}\x{205F}\x{3000}]";
    const VERTICAL_WHITESPACE: &str = r"[\n\x0B\f\r\x{0085}\x{2028}\x{2029}]";
    const NON_VERTICAL_WHITESPACE: &str = r"[^\n\x0B\f\r\x{0085}\x{2028}\x{2029}]";
    const LINE_BREAK: &str = r"(?:\r\n|[\n\x0B\f\r\x{0085}\x{2028}\x{2029}])";

    let mut result = String::with_capacity(pattern.len());
    let mut mode = PineRegexMode::default();
    let mut modes = Vec::new();
    let mut class_depth = 0usize;
    let mut class_prefixes: Vec<PineRegexClassPrefix> = Vec::new();
    let mut case_class_start = None;
    let mut case_protected_spans = Vec::new();
    let mut index = 0usize;
    let mut final_newline_captures = Vec::new();
    let mut final_newline_capture_prefix = "__pine_final_newline_".to_owned();
    while pattern.contains(&final_newline_capture_prefix) {
        final_newline_capture_prefix.push('_');
    }

    while index < pattern.len() {
        let rest = &pattern[index..];
        let byte = pattern.as_bytes()[index];

        if mode.verbose && byte == b'#' {
            let comment_len = rest
                .char_indices()
                .find_map(|(offset, ch)| is_pine_regex_line_separator(ch).then_some(offset))
                .unwrap_or(rest.len());
            index += comment_len;
            continue;
        }
        if mode.verbose && is_verbose_ascii_space(byte) {
            result.push(byte as char);
            index += 1;
            continue;
        }
        if mode.verbose {
            let ch = rest.chars().next().expect("regex contains a character");
            if !ch.is_ascii() && ch.is_whitespace() {
                mark_pine_regex_class_scalar(&mut class_prefixes);
                if class_depth == 0 {
                    push_pine_regex_literal(&mut result, ch, mode, true);
                } else {
                    write!(result, r"\x{{{:X}}}", ch as u32)
                        .expect("writing to a String cannot fail");
                }
                index += ch.len_utf8();
                continue;
            }
        }

        if byte == b'\\' {
            let mut chars = rest.chars();
            let slash = chars.next().expect("regex escape starts with a character");
            let Some(escaped) = chars.next() else {
                result.push(slash);
                break;
            };
            if escaped == 'Q' {
                let quoted_start = index + slash.len_utf8() + escaped.len_utf8();
                let quoted_rest = &pattern[quoted_start..];
                if let Some(quoted_len) = quoted_rest.find(r"\E") {
                    mark_pine_regex_quoted_scalars(&quoted_rest[..quoted_len], &mut class_prefixes);
                    push_pine_regex_quoted(
                        &mut result,
                        &quoted_rest[..quoted_len],
                        mode,
                        class_depth > 0,
                    );
                    index = quoted_start + quoted_len + r"\E".len();
                } else {
                    mark_pine_regex_quoted_scalars(quoted_rest, &mut class_prefixes);
                    push_pine_regex_quoted(&mut result, quoted_rest, mode, class_depth > 0);
                    index = pattern.len();
                }
                continue;
            }
            if mode.verbose && !escaped.is_ascii() && escaped.is_whitespace() {
                mark_pine_regex_class_scalar(&mut class_prefixes);
                if class_depth == 0 {
                    push_pine_regex_literal(&mut result, escaped, mode, true);
                } else {
                    write!(result, r"\x{{{:X}}}", escaped as u32)
                        .expect("writing to a String cannot fail");
                }
                index += slash.len_utf8() + escaped.len_utf8();
                continue;
            }
            if escaped.is_ascii() && !escaped.is_ascii_alphanumeric() {
                mark_pine_regex_class_scalar(&mut class_prefixes);
                write!(result, r"\x{{{:X}}}", escaped as u32)
                    .expect("writing to a String cannot fail");
                index += slash.len_utf8() + escaped.len_utf8();
                continue;
            }
            if escaped == 'N'
                && let Some(reference) = parse_pine_regex_named_character_escape(pattern, index)
            {
                mark_pine_regex_class_scalar(&mut class_prefixes);
                push_pine_regex_reference(&mut result, reference.scalar, mode, class_depth, 0);
                index = reference.end;
                continue;
            }
            if matches!(escaped, 'u' | 'x')
                && let Some(reference) = parse_pine_regex_code_point_escape(pattern, index)
            {
                if let Some(ch) = reference.scalar {
                    mark_pine_regex_class_scalar(&mut class_prefixes);
                    push_pine_regex_reference(
                        &mut result,
                        ch,
                        mode,
                        class_depth,
                        reference.hex_width,
                    );
                } else {
                    mark_pine_regex_class_set(&mut result, &mut class_prefixes);
                    result.push_str("[a&&b]");
                }
                index = reference.end;
                continue;
            }
            if escaped == 'c'
                && let Some(control) = parse_pine_regex_control_escape(pattern, index, mode.verbose)
            {
                mark_pine_regex_class_scalar(&mut class_prefixes);
                push_pine_regex_reference(&mut result, control.scalar, mode, class_depth, 0);
                index = control.end;
                continue;
            }
            if escaped == '0'
                && let Some(reference) = parse_pine_regex_octal_escape(pattern, index, mode.verbose)
            {
                mark_pine_regex_class_scalar(&mut class_prefixes);
                push_pine_regex_reference(&mut result, reference.scalar, mode, class_depth, 0);
                index = reference.end;
                continue;
            }
            if matches!(escaped, 'p' | 'P') {
                let property_start = index + slash.len_utf8() + escaped.len_utf8();
                if pattern.as_bytes().get(property_start) == Some(&b'{') {
                    let name_start = property_start + 1;
                    if let Some(name_len) = pattern[name_start..].find('}') {
                        let name_end = name_start + name_len;
                        let property = &pattern[name_start..name_end];
                        mark_pine_regex_class_set(&mut result, &mut class_prefixes);
                        if let Some(replacement) = pine_java_property(property, escaped == 'P') {
                            push_case_insensitive_class_replacement(
                                &mut result,
                                replacement,
                                mode.case_insensitive,
                                PineRegexClassReplacementCase::Fold {
                                    replacement_unicode: true,
                                    outer_unicode: mode.unicode_case,
                                },
                                class_depth,
                                &mut case_protected_spans,
                            );
                            index = name_end + 1;
                            continue;
                        }
                        if let Some(replacement) =
                            pine_posix_class(property, mode.unicode_classes, escaped == 'P')
                        {
                            push_case_insensitive_class_replacement(
                                &mut result,
                                replacement,
                                mode.case_insensitive,
                                if property.eq_ignore_ascii_case("ASCII") {
                                    PineRegexClassReplacementCase::Exact
                                } else {
                                    PineRegexClassReplacementCase::Fold {
                                        replacement_unicode: mode.unicode_classes,
                                        outer_unicode: mode.unicode_case,
                                    }
                                },
                                class_depth,
                                &mut case_protected_spans,
                            );
                            index = name_end + 1;
                            continue;
                        }
                        if let Some((start, end)) =
                            pine_unicode_block_property(property).and_then(pine_unicode_block)
                        {
                            let mut replacement = String::new();
                            push_pine_unicode_block(&mut replacement, start, end, escaped == 'P');
                            push_case_insensitive_class_replacement(
                                &mut result,
                                &replacement,
                                mode.case_insensitive,
                                PineRegexClassReplacementCase::Exact,
                                class_depth,
                                &mut case_protected_spans,
                            );
                            index = name_end + 1;
                            continue;
                        }
                        result.push_str(&pattern[index..name_end + 1]);
                        index = name_end + 1;
                        continue;
                    }
                }
            }
            if escaped == 'Z' && class_depth == 0 {
                push_pine_regex_final_anchor(
                    &mut result,
                    &mut final_newline_captures,
                    &final_newline_capture_prefix,
                );
                index += slash.len_utf8() + escaped.len_utf8();
                continue;
            }
            if escaped == 'G' && class_depth == 0 {
                result.push_str(r"\A");
                index += slash.len_utf8() + escaped.len_utf8();
                continue;
            }
            let replacement = match escaped {
                'h' => Some(HORIZONTAL_WHITESPACE),
                'H' => Some(NON_HORIZONTAL_WHITESPACE),
                'v' => Some(VERTICAL_WHITESPACE),
                'V' => Some(NON_VERTICAL_WHITESPACE),
                'R' if class_depth == 0 => Some(LINE_BREAK),
                'e' => Some(r"\x{1B}"),
                _ if !mode.unicode_classes => match escaped {
                    'd' => Some("[0-9]"),
                    'D' => Some("[^0-9]"),
                    'w' => Some("[A-Za-z0-9_]"),
                    'W' => Some("[^A-Za-z0-9_]"),
                    's' => Some(r"[ \t\n\x0B\f\r]"),
                    'S' => Some(r"[^ \t\n\x0B\f\r]"),
                    'b' if class_depth == 0 => Some(r"(?-u:\b)"),
                    'B' if class_depth == 0 => Some(r"(?-u:\B)"),
                    _ => None,
                },
                _ => None,
            };
            if let Some(replacement) = replacement {
                if replacement.starts_with('[') {
                    mark_pine_regex_class_set(&mut result, &mut class_prefixes);
                    push_case_insensitive_class_replacement(
                        &mut result,
                        replacement,
                        mode.case_insensitive,
                        PineRegexClassReplacementCase::Fold {
                            replacement_unicode: mode.unicode_classes,
                            outer_unicode: mode.unicode_case,
                        },
                        class_depth,
                        &mut case_protected_spans,
                    );
                } else {
                    if escaped == 'e' {
                        mark_pine_regex_class_scalar(&mut class_prefixes);
                    }
                    result.push_str(replacement);
                }
                index += slash.len_utf8() + escaped.len_utf8();
                continue;
            }

            if class_depth > 0 {
                if matches!(escaped, 'd' | 'D' | 'w' | 'W' | 's' | 'S') {
                    mark_pine_regex_class_set(&mut result, &mut class_prefixes);
                } else if matches!(escaped, 'a' | 'b' | 't' | 'n' | 'f' | 'r') {
                    mark_pine_regex_class_scalar(&mut class_prefixes);
                }
            }

            result.push(slash);
            result.push(escaped);
            index += slash.len_utf8() + escaped.len_utf8();
            continue;
        }

        if class_depth > 0 && byte == b'-' {
            let is_range = class_prefixes
                .last_mut()
                .expect("a character class has prefix state")
                .mark_raw_hyphen(pattern.as_bytes().get(index + 1).copied());
            result.push_str(if is_range { "-" } else { r"\x{2D}" });
            index += 1;
            continue;
        }

        if class_depth > 0
            && matches!(byte, b'[' | b']')
            && class_prefixes
                .last()
                .is_some_and(PineRegexClassPrefix::expects_range_endpoint)
        {
            class_prefixes
                .last_mut()
                .expect("a character class has prefix state")
                .mark_scalar();
            write!(result, r"\x{{{byte:X}}}").expect("writing to a String cannot fail");
            index += 1;
            continue;
        }

        if class_depth > 0 && byte == b'&' {
            resolve_java_bits(&mut result, &mut class_prefixes, &mut case_protected_spans);
            let prefix = class_prefixes
                .last()
                .expect("a character class has prefix state");
            if !prefix.expects_range_endpoint()
                && let Some((second_index, '&')) =
                    next_pine_regex_class_token(pattern, index + 1, mode.verbose)
            {
                let rhs = next_pine_regex_class_token(
                    pattern,
                    second_index + '&'.len_utf8(),
                    mode.verbose,
                );
                let rhs_is_empty = rhs.is_none_or(|(_, ch)| matches!(ch, '&' | ']'));
                let has_lhs = prefix.has_atom();
                let class_start = prefix.output_start();
                let empty_intersection = (has_lhs && rhs_is_empty).then(|| {
                    pine_java_empty_intersection(
                        &result[class_start..],
                        mode.verbose,
                        mode.case_insensitive && mode.unicode_case,
                    )
                    .with_deferred_bit_class(&mut class_prefixes)
                });
                class_prefixes
                    .last_mut()
                    .expect("a character class has prefix state")
                    .mark_intersection();
                if !has_lhs && rhs_is_empty {
                    result.push_str(r"\p{__PineInvalidJavaIntersection}");
                } else if has_lhs && !rhs_is_empty {
                    result.push_str("&&");
                } else if let Some(empty_intersection) = empty_intersection {
                    let continuation = pine_java_ampersand_continuation(pattern, rhs, mode.verbose);
                    apply_pine_java_empty_intersection(
                        &mut result,
                        class_start,
                        &mut case_protected_spans,
                        &mut class_prefixes,
                        empty_intersection,
                        continuation,
                    );
                }
                index = second_index + '&'.len_utf8();
                continue;
            }
            class_prefixes
                .last_mut()
                .expect("a character class has prefix state")
                .mark_scalar();
            result.push_str(r"\x{26}");
            index += 1;
            continue;
        }

        if class_depth == 0 && byte == b'.' && !mode.dotall {
            result.push_str(if mode.unix_lines {
                r"[^\n]"
            } else {
                r"[^\n\r\x{0085}\x{2028}\x{2029}]"
            });
            index += 1;
            continue;
        }

        if class_depth == 0 && byte == b'$' && !mode.multiline {
            push_pine_regex_final_anchor(
                &mut result,
                &mut final_newline_captures,
                &final_newline_capture_prefix,
            );
            index += 1;
            continue;
        }

        if class_depth == 0 && byte == b'(' {
            if let Some(flags) = parse_pine_regex_flags(pattern, index) {
                let next_mode = apply_pine_regex_flags(mode, &flags);
                push_rust_regex_flags(&mut result, &flags);
                if flags.scoped {
                    modes.push(mode);
                }
                mode = next_mode;
                index = flags.end;
                continue;
            }
            if rest.starts_with("(?<")
                && !matches!(rest.as_bytes().get(3), Some(b'=' | b'!'))
                && let Some(name_end) = rest[3..].find('>')
            {
                let header_end = 3 + name_end + 1;
                result.push_str(&rest[..header_end]);
                modes.push(mode);
                index += header_end;
                continue;
            }
            modes.push(mode);
        } else if class_depth == 0 && byte == b')' {
            if let Some(parent_mode) = modes.pop() {
                mode = parent_mode;
            }
        } else if byte == b'[' {
            mark_pine_regex_class_set(&mut result, &mut class_prefixes);
            if class_depth == 0 && mode.case_insensitive {
                case_class_start = Some(result.len());
                case_protected_spans.clear();
            }
            class_prefixes.push(PineRegexClassPrefix::new(result.len()));
            class_depth += 1;
        } else if byte == b']' && class_depth > 0 {
            if class_prefixes
                .last()
                .is_some_and(|prefix| prefix.can_literal_close)
            {
                class_prefixes
                    .last_mut()
                    .expect("an open class has prefix state")
                    .mark_scalar();
                result.push_str(r"\x{5D}");
                index += 1;
                continue;
            }
            resolve_java_bits(&mut result, &mut class_prefixes, &mut case_protected_spans);
            class_prefixes.pop();
            class_depth -= 1;
        } else if byte == b'^'
            && let Some(prefix) = class_prefixes.last_mut()
        {
            if prefix.can_negate {
                prefix.can_negate = false;
            } else {
                prefix.mark_scalar();
            }
        } else if let Some(prefix) = class_prefixes.last_mut() {
            prefix.mark_scalar();
        }

        let closed_case_class = byte == b']' && class_depth == 0 && case_class_start.is_some();
        let ch = rest.chars().next().expect("regex contains a character");
        if class_depth == 0 {
            push_pine_regex_literal(&mut result, ch, mode, false);
        } else if ch == '~' {
            result.push_str(r"\x{7E}");
        } else {
            result.push(ch);
        }
        index += ch.len_utf8();

        if closed_case_class {
            let start = case_class_start.take().expect("checked class start");
            let class = result.split_off(start);
            let protected = case_protected_spans
                .drain(..)
                .map(|range| range.start - start..range.end - start)
                .collect::<Vec<_>>();
            if let Some(class) =
                normalize_case_insensitive_class(&class, mode.unicode_case, &protected)
            {
                push_case_folded_class(&mut result, &class);
            } else {
                result.push_str(&class);
            }
        }
    }

    NormalizedPineRegex {
        pattern: result,
        final_newline_captures,
    }
}

#[cfg(test)]
pub(crate) fn normalize_pine_regex(pattern: &str) -> String {
    normalize_pine_regex_with_metadata(pattern).pattern
}

pub(crate) fn stringify_array(values: &[PineValue], format: &str) -> String {
    let mut result = String::from("[");
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            result.push_str(", ");
        }
        result.push_str(&stringify_array_element(value, format));
    }
    result.push(']');
    result
}

pub(crate) fn stringify_matrix(
    values: &[PineValue],
    rows: usize,
    columns: usize,
    format: &str,
) -> String {
    let mut result = String::from("[");
    for row in 0..rows {
        if row > 0 {
            result.push_str(", ");
        }
        let start = row.saturating_mul(columns);
        let end = start.saturating_add(columns);
        let Some(row_values) = values.get(start..end) else {
            return "NaN".to_owned();
        };
        result.push_str(&stringify_array(row_values, format));
    }
    result.push(']');
    result
}

pub(crate) fn stringify_array_element(value: &PineValue, format: &str) -> String {
    match value {
        PineValue::Int(value) => format_number(*value as f64, format),
        PineValue::Float(value) => format_number(*value, format),
        PineValue::Bool(value) => value.to_string(),
        PineValue::String(value) => value.clone(),
        PineValue::Na => "NaN".to_owned(),
        _ => "NaN".to_owned(),
    }
}

pub(crate) fn stringify_array_join_element(value: &PineValue) -> String {
    match value {
        PineValue::Int(value) => format_number(*value as f64, "#.########"),
        PineValue::Float(value) => format_number(*value, "#.########"),
        PineValue::Bool(value) => value.to_string(),
        PineValue::String(value) => value.clone(),
        PineValue::Color(value) => value.to_string(),
        PineValue::Na => "NaN".to_owned(),
        _ => "NaN".to_owned(),
    }
}

pub(crate) fn stringify_user_type_array_join_element(
    value: &PineValue,
    type_name: &str,
    user_types: &[HirUserTypeInfo],
) -> String {
    stringify_user_type_array_join_element_with_seen(value, type_name, user_types, &mut Vec::new())
}

fn stringify_user_type_array_join_element_with_seen(
    value: &PineValue,
    type_name: &str,
    user_types: &[HirUserTypeInfo],
    seen: &mut Vec<String>,
) -> String {
    let PineValue::UserType(fields) = value else {
        return stringify_array_join_element(value);
    };

    if seen.iter().any(|seen_type| seen_type == type_name) {
        return stringify_array_join_element(value);
    }
    seen.push(type_name.to_owned());
    let shape = user_types
        .iter()
        .find(|user_type| user_type.identity.type_name == type_name);
    let mut result = String::new();
    result.push_str(type_name);
    result.push('(');
    for (index, field) in fields.iter().enumerate() {
        if index > 0 {
            result.push_str(", ");
        }
        if let Some(field_type_name) = shape
            .and_then(|shape| shape.fields.get(index))
            .and_then(|field| field.user_type_name.as_deref())
        {
            result.push_str(&stringify_user_type_array_join_element_with_seen(
                field,
                field_type_name,
                user_types,
                seen,
            ));
        } else {
            result.push_str(&stringify_array_join_element(field));
        }
    }
    result.push(')');
    seen.pop();
    result
}

pub(crate) fn format_string_placeholders(
    format_string: &str,
    values: &[PineValue],
    runtime: &HistoricalRuntime<'_>,
) -> Result<String, RuntimeError> {
    let mut result = String::new();
    let mut chars = format_string.char_indices().peekable();
    while let Some((byte_index, ch)) = chars.next() {
        match ch {
            '\'' => {
                if chars.peek().is_some_and(|(_, next)| *next == '\'') {
                    chars.next();
                    result.push('\'');
                } else {
                    for (_, literal) in chars.by_ref() {
                        if literal == '\'' {
                            break;
                        }
                        result.push(literal);
                    }
                }
            }
            '{' => {
                let start = byte_index + ch.len_utf8();
                let Some((end, _)) = chars.find(|(_, next)| *next == '}') else {
                    return Err(RuntimeError {
                        message: "str.format has unmatched `{`".to_owned(),
                    });
                };
                let placeholder = &format_string[start..end];
                if let Some(formatted) = format_placeholder(placeholder, values, runtime)? {
                    result.push_str(&formatted);
                } else {
                    result.push('{');
                    result.push_str(placeholder);
                    result.push('}');
                }
            }
            '}' => {
                return Err(RuntimeError {
                    message: "str.format has unmatched `}`".to_owned(),
                });
            }
            _ => result.push(ch),
        }
    }
    Ok(result)
}

pub(crate) fn format_placeholder(
    placeholder: &str,
    values: &[PineValue],
    runtime: &HistoricalRuntime<'_>,
) -> Result<Option<String>, RuntimeError> {
    let mut parts = placeholder.splitn(3, ',').map(str::trim);
    let Some(index) = parts.next().and_then(|part| part.parse::<usize>().ok()) else {
        return Ok(None);
    };
    let Some(value) = values.get(index) else {
        return Ok(None);
    };
    let Some(modifier) = parts.next() else {
        return Ok(Some(runtime.stringify_value(value, "#,###.###")));
    };

    if matches!(modifier, "date" | "time") {
        return format_datetime_placeholder(modifier, parts.next().map(str::trim), value, runtime)
            .map(Some);
    }

    if modifier != "number" {
        return Ok(Some(runtime.stringify_value(value, "#,###.###")));
    }

    let format = match parts.next().map(str::trim) {
        Some("integer") => "#,###",
        Some("percent") => "#,###%",
        Some("currency") => return Ok(Some(format_currency_placeholder(value, runtime))),
        Some(format) if !format.is_empty() => format,
        _ => "#,###.###",
    };
    Ok(Some(runtime.stringify_value(value, format)))
}

pub(crate) fn format_datetime_placeholder(
    modifier: &str,
    format: Option<&str>,
    value: &PineValue,
    runtime: &HistoricalRuntime<'_>,
) -> Result<String, RuntimeError> {
    let PineValue::Int(timestamp) = value else {
        return Ok(runtime.stringify_value(value, "#,###.###"));
    };
    let format = match (modifier, format.filter(|format| !format.is_empty())) {
        (_, Some(format)) => format,
        ("date", None) => "yyyy-MM-dd",
        ("time", None) => "HH:mm:ss",
        _ => unreachable!("validated str.format date/time modifier"),
    };
    let datetime = utc_datetime_from_millis(*timestamp).map_err(|_| RuntimeError {
        message: format!("str.format timestamp is out of range: {timestamp}"),
    })?;
    Ok(format_utc_datetime(datetime, format))
}

pub(crate) fn format_currency_placeholder(
    value: &PineValue,
    runtime: &HistoricalRuntime<'_>,
) -> String {
    let formatted = match value {
        PineValue::Int(value) => format_number(*value as f64, "#,###.00"),
        PineValue::Float(value) => format_number(*value, "#,###.00"),
        _ => return runtime.stringify_value(value, "#,###.00"),
    };
    if formatted == "NaN" {
        formatted
    } else if let Some(unsigned) = formatted.strip_prefix('-') {
        format!("-${unsigned}")
    } else {
        format!("${formatted}")
    }
}

pub(crate) fn format_volume_number(value: f64) -> String {
    const SCALES: &[(f64, &str)] = &[
        (1_000_000_000_000.0, "T"),
        (1_000_000_000.0, "B"),
        (1_000_000.0, "M"),
        (1_000.0, "K"),
    ];

    if !value.is_finite() {
        return "NaN".to_owned();
    }

    let rounded_whole = value.round();
    if rounded_whole.abs() < 1_000.0 {
        return format_number(value, "#");
    }

    for (index, (scale, suffix)) in SCALES.iter().enumerate() {
        if value.abs() < *scale && index + 1 < SCALES.len() {
            continue;
        }
        let mut scaled = value / scale;
        let rounded_scaled = (scaled * 1_000.0).round() / 1_000.0;
        if rounded_scaled.abs() >= 1_000.0 && index > 0 {
            let (next_scale, next_suffix) = SCALES[index - 1];
            scaled = value / next_scale;
            return format!("{}{next_suffix}", format_number(scaled, "#.###"));
        }
        return format!("{}{suffix}", format_number(scaled, "#.###"));
    }

    format_number(value, "#")
}

pub(crate) fn format_number(value: f64, format: &str) -> String {
    if !value.is_finite() {
        return "NaN".to_owned();
    }

    if format == "format.mintick" {
        let mintick = pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
        if !mintick.is_finite() || mintick <= 0.0 {
            return "NaN".to_owned();
        }
        let ticks = value / mintick;
        let tie_tolerance = f64::EPSILON * ticks.abs().max(1.0) * 4.0;
        let rounded = (ticks + 0.5 + tie_tolerance).floor() * mintick;
        if !rounded.is_finite() {
            return "NaN".to_owned();
        }
        let decimal_places = (0..=16)
            .find(|places| {
                let scaled = mintick * 10_f64.powi(*places);
                (scaled - scaled.round()).abs() <= 1e-9
            })
            .unwrap_or(16) as usize;
        let rounded = if rounded == 0.0 { 0.0 } else { rounded };
        return format!("{rounded:.decimal_places$}");
    }

    if format == "format.volume" {
        return format_volume_number(value);
    }

    if format == "format.percent" {
        return format!("{}%", format_number(value, "#.##"));
    }

    let format = match format {
        "" | "format.price" => "#.########",
        other => other,
    };
    let percent = format.ends_with('%');
    let pattern = format.strip_suffix('%').unwrap_or(format);
    let value = if percent { value * 100.0 } else { value };

    let (whole_pattern, fractional_pattern) = pattern.split_once('.').unwrap_or((pattern, ""));
    let decimal_places = fractional_pattern
        .chars()
        .filter(|ch| matches!(ch, '#' | '0'))
        .count();
    let required_fractional = fractional_pattern.chars().filter(|ch| *ch == '0').count();
    let min_integer_digits = whole_pattern.chars().filter(|ch| *ch == '0').count();
    let use_grouping = whole_pattern.contains(',');
    let rounded = if decimal_places == 0 {
        value.round()
    } else {
        let factor = 10_f64.powi(decimal_places.min(308) as i32);
        (value * factor).round() / factor
    };
    let negative = rounded.is_sign_negative() && rounded != 0.0;
    let abs_value = rounded.abs();
    let raw = format!("{abs_value:.decimal_places$}");
    let (whole, fractional) = raw.split_once('.').unwrap_or((raw.as_str(), ""));
    let mut whole = whole.to_owned();
    if whole.len() < min_integer_digits {
        whole = format!("{}{}", "0".repeat(min_integer_digits - whole.len()), whole);
    }
    if use_grouping {
        whole = group_integer_digits(&whole);
    }

    let mut fractional = fractional.to_owned();
    while fractional.len() > required_fractional && fractional.ends_with('0') {
        fractional.pop();
    }

    let mut result = String::new();
    if negative {
        result.push('-');
    }
    result.push_str(&whole);
    if !fractional.is_empty() {
        result.push('.');
        result.push_str(&fractional);
    }
    if percent {
        result.push('%');
    }
    result
}

pub(crate) fn group_integer_digits(value: &str) -> String {
    let mut result = String::new();
    for (index, ch) in value.chars().rev().enumerate() {
        if index > 0 && index % 3 == 0 {
            result.push(',');
        }
        result.push(ch);
    }
    result.chars().rev().collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum StringCase {
    Upper,
    Lower,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum StringMatch {
    Contains,
    StartsWith,
    EndsWith,
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_string_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        if !callee.starts_with("str.") {
            return None;
        }

        Some(match callee {
            "str.length" => self.eval_str_length(args),
            "str.upper" => self.eval_str_case(args, StringCase::Upper),
            "str.lower" => self.eval_str_case(args, StringCase::Lower),
            "str.contains" => self.eval_str_match(args, StringMatch::Contains),
            "str.startswith" => self.eval_str_match(args, StringMatch::StartsWith),
            "str.endswith" => self.eval_str_match(args, StringMatch::EndsWith),
            "str.pos" => self.eval_str_pos(args),
            "str.substring" => self.eval_str_substring(args),
            "str.trim" => self.eval_str_trim(args),
            "str.repeat" => self.eval_str_repeat(args),
            "str.replace" => self.eval_str_replace(args),
            "str.replace_all" => self.eval_str_replace_all(args),
            "str.tonumber" => self.eval_str_tonumber(args),
            "str.tostring" => self.eval_str_tostring(args),
            "str.format" => self.eval_str_format(args),
            "str.match" => self.eval_str_match_regex(args),
            "str.split" => self.eval_str_split(args),
            "str.format_time" => self.eval_str_format_time(args),
            _ => return None,
        })
    }

    pub(crate) fn eval_str_length(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(value) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        Ok(PineValue::Int(value.chars().count() as i64))
    }

    pub(crate) fn eval_str_case(
        &mut self,
        args: &[HirCallArg],
        string_case: StringCase,
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(value) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        let value = match string_case {
            StringCase::Upper => value.to_ascii_uppercase(),
            StringCase::Lower => value.to_ascii_lowercase(),
        };
        Ok(PineValue::String(value))
    }

    pub(crate) fn eval_str_match(
        &mut self,
        args: &[HirCallArg],
        string_match: StringMatch,
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(pattern) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };

        let matched = match string_match {
            StringMatch::Contains => source.contains(&pattern),
            StringMatch::StartsWith => source.starts_with(&pattern),
            StringMatch::EndsWith => source.ends_with(&pattern),
        };
        Ok(PineValue::Bool(matched))
    }

    pub(crate) fn eval_str_pos(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let pattern = match self.eval_expr(&args[1].value)? {
            PineValue::String(pattern) => pattern,
            PineValue::Na => return Ok(PineValue::Int(0)),
            _ => return Ok(PineValue::Na),
        };
        if pattern.is_empty() {
            return Ok(PineValue::Int(0));
        }

        Ok(source.find(&pattern).map_or(PineValue::Na, |byte_index| {
            PineValue::Int(source[..byte_index].chars().count() as i64)
        }))
    }

    pub(crate) fn eval_str_substring(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let begin = self.eval_optional_string_index(&args[1].value, 0)?;
        let chars: Vec<char> = source.chars().collect();
        let len = chars.len() as i64;
        if begin < 0 || begin > len {
            return Err(RuntimeError {
                message: format!("str.substring begin_pos {begin} is outside string length {len}"),
            });
        }

        let end = if let Some(arg) = args.get(2) {
            self.eval_optional_string_index(&arg.value, len)?
        } else {
            len
        }
        .min(len);
        if end < begin {
            return Err(RuntimeError {
                message: format!("str.substring end_pos {end} is less than begin_pos {begin}"),
            });
        }

        Ok(PineValue::String(
            chars[begin as usize..end as usize].iter().collect(),
        ))
    }

    pub(crate) fn eval_str_trim(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let value = match self.eval_expr(&args[0].value)? {
            PineValue::String(value) => value,
            PineValue::Na => return Ok(PineValue::String(String::new())),
            _ => return Ok(PineValue::Na),
        };

        Ok(PineValue::String(
            value
                .trim_matches(|ch: char| ch.is_ascii_whitespace())
                .to_owned(),
        ))
    }

    pub(crate) fn eval_str_repeat(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let Some(repeat) = self.eval_string_index(&args[1].value)? else {
            return Ok(PineValue::Na);
        };
        let separator = if let Some(arg) = args.get(2) {
            let PineValue::String(separator) = self.eval_expr(&arg.value)? else {
                return Ok(PineValue::Na);
            };
            separator
        } else {
            String::new()
        };
        if repeat < 0 {
            return Err(RuntimeError {
                message: format!("str.repeat count cannot be negative: {repeat}"),
            });
        }

        let repeat = repeat as usize;
        let result_chars = repeat
            .saturating_mul(source.chars().count())
            .saturating_add(
                repeat
                    .saturating_sub(1)
                    .saturating_mul(separator.chars().count()),
            );
        if result_chars > MAX_STRING_CHARS {
            return Err(RuntimeError {
                message: format!("str.repeat result cannot exceed {MAX_STRING_CHARS} characters"),
            });
        }

        let mut result = String::new();
        for index in 0..repeat {
            if index > 0 {
                result.push_str(&separator);
            }
            result.push_str(&source);
        }
        Ok(PineValue::String(result))
    }

    pub(crate) fn eval_str_replace(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some((source, target, replacement)) = self.eval_replace_strings(args)? else {
            return Ok(PineValue::Na);
        };
        let occurrence = if let Some(arg) = args.get(3) {
            self.eval_optional_string_index(&arg.value, 0)?
        } else {
            0
        };
        if occurrence < 0 {
            return Ok(PineValue::String(source));
        }

        let result = if target.is_empty() {
            replace_zero_width_occurrence(&source, &replacement, occurrence as usize)
        } else {
            replace_nth_non_overlapping(&source, &target, &replacement, occurrence as usize)
        };
        self.string_value_or_error(result, "str.replace")
    }

    pub(crate) fn eval_str_replace_all(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some((source, target, replacement)) = self.eval_replace_strings(args)? else {
            return Ok(PineValue::Na);
        };
        let result = if target.is_empty() {
            replace_all_zero_width_boundaries(&source, &replacement)
        } else {
            source.replace(&target, &replacement)
        };
        self.string_value_or_error(result, "str.replace_all")
    }

    pub(crate) fn eval_str_tonumber(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(value) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        if !is_pine_numeric_string(&value) {
            return Ok(PineValue::Na);
        }

        Ok(value
            .parse::<f64>()
            .ok()
            .map_or(PineValue::Na, finite_float_or_na))
    }

    pub(crate) fn eval_str_tostring(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        let format = if let Some(arg) = args.get(1) {
            match self.eval_expr(&arg.value)? {
                PineValue::String(format) => format,
                PineValue::Na => "#.########".to_owned(),
                _ => return Ok(PineValue::Na),
            }
        } else {
            "#.########".to_owned()
        };
        let result = self.stringify_value(&value, &format);
        self.string_value_or_error(result, "str.tostring")
    }

    pub(crate) fn eval_str_format(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(format_string) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let mut values = Vec::with_capacity(args.len().saturating_sub(1));
        for arg in &args[1..] {
            values.push(self.eval_expr(&arg.value)?);
        }

        let result = format_string_placeholders(&format_string, &values, self)?;
        self.string_value_or_error(result, "str.format")
    }

    pub(crate) fn eval_str_match_regex(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(regex) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };
        let normalized = normalize_pine_regex_with_metadata(&regex);
        let regex = Regex::new(&normalized.pattern).map_err(|err| RuntimeError {
            message: format!("str.match invalid regex: {err}"),
        })?;
        let Some(captures) = regex.captures(&source) else {
            return Ok(PineValue::String(String::new()));
        };
        let matched = captures
            .get(0)
            .expect("successful regex captures contain the complete match");
        let consumed_final_newline = normalized
            .final_newline_captures
            .iter()
            .any(|name| captures.name(name).is_some());
        let end = matched.end() - usize::from(consumed_final_newline);

        Ok(PineValue::String(source[matched.start()..end].to_owned()))
    }

    pub(crate) fn eval_str_split(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(separator) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };

        let parts: Vec<PineValue> = if separator.is_empty() {
            source
                .chars()
                .map(|ch| PineValue::String(ch.to_string()))
                .collect()
        } else {
            source
                .split(&separator)
                .map(|part| PineValue::String(part.to_owned()))
                .collect()
        };
        if parts.len() > MAX_ARRAY_ELEMENTS {
            return Err(RuntimeError {
                message: format!("str.split cannot exceed {MAX_ARRAY_ELEMENTS} elements"),
            });
        }

        Ok(self.new_array_from_values(ArrayElementKind::String, parts))
    }

    pub(crate) fn eval_str_format_time(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let timestamp = match self.eval_expr(&args[0].value)? {
            PineValue::Int(value) => value,
            PineValue::Na => 0,
            _ => return Ok(PineValue::Na),
        };
        let format = if let Some(arg) = args.get(1) {
            match self.eval_expr(&arg.value)? {
                PineValue::String(format) => format,
                PineValue::Na => "yyyy-MM-dd'T'HH:mm:ssZ".to_owned(),
                _ => return Ok(PineValue::Na),
            }
        } else {
            "yyyy-MM-dd'T'HH:mm:ssZ".to_owned()
        };
        let timezone = if let Some(arg) = args.get(2) {
            match self.eval_expr(&arg.value)? {
                PineValue::String(timezone) => timezone,
                PineValue::Na => "UTC".to_owned(),
                _ => return Ok(PineValue::Na),
            }
        } else {
            "UTC".to_owned()
        };
        let datetime = utc_datetime_from_millis(timestamp).map_err(|_| RuntimeError {
            message: format!("str.format_time timestamp is out of range: {timestamp}"),
        })?;
        let (offset_seconds, timezone_short_name) =
            timezone_offset_and_short_name(&timezone, &datetime).ok_or_else(|| RuntimeError {
                message: format!("str.format_time unsupported timezone `{timezone}`"),
            })?;
        let Some(offset) = chrono::Duration::try_seconds(i64::from(offset_seconds)) else {
            return Err(RuntimeError {
                message: format!("str.format_time unsupported timezone `{timezone}`"),
            });
        };
        let Some(datetime) = datetime.checked_add_signed(offset) else {
            return Err(RuntimeError {
                message: format!("str.format_time timestamp is out of range: {timestamp}"),
            });
        };

        let timezone_offset = format_fixed_timezone_offset(offset_seconds);
        let result = format_datetime_with_timezone(
            datetime,
            &format,
            &timezone_offset,
            Some(&timezone_short_name),
        );
        self.string_value_or_error(result, "str.format_time")
    }

    pub(crate) fn stringify_value(&self, value: &PineValue, format: &str) -> String {
        match value {
            PineValue::Int(value) => format_number(*value as f64, format),
            PineValue::Float(value) => format_number(*value, format),
            PineValue::Bool(value) => value.to_string(),
            PineValue::String(value) => value.clone(),
            PineValue::Array(id) => self
                .array_values_clone(*id)
                .ok()
                .flatten()
                .map(|values| stringify_array(&values, format))
                .unwrap_or_else(|| "NaN".to_owned()),
            PineValue::Matrix(id) => self
                .matrix_store
                .get(id)
                .map(|matrix| stringify_matrix(&matrix.values, matrix.rows, matrix.columns, format))
                .unwrap_or_else(|| "NaN".to_owned()),
            PineValue::Na => "NaN".to_owned(),
            _ => "NaN".to_owned(),
        }
    }

    pub(crate) fn eval_replace_strings(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<(String, String, String)>, RuntimeError> {
        let PineValue::String(source) = self.eval_expr(&args[0].value)? else {
            return Ok(None);
        };
        let PineValue::String(target) = self.eval_expr(&args[1].value)? else {
            return Ok(None);
        };
        let PineValue::String(replacement) = self.eval_expr(&args[2].value)? else {
            return Ok(None);
        };
        Ok(Some((source, target, replacement)))
    }

    pub(crate) fn string_value_or_error(
        &self,
        value: String,
        function: &str,
    ) -> Result<PineValue, RuntimeError> {
        if value.chars().count() > MAX_STRING_CHARS {
            return Err(RuntimeError {
                message: format!("{function} result cannot exceed {MAX_STRING_CHARS} characters"),
            });
        }
        Ok(PineValue::String(value))
    }

    pub(crate) fn eval_string_index(
        &mut self,
        expr: &HirExpr,
    ) -> Result<Option<i64>, RuntimeError> {
        Ok(match self.eval_expr(expr)? {
            PineValue::Int(value) => Some(value),
            PineValue::Float(value) if value.is_finite() => Some(value as i64),
            PineValue::Na => None,
            _ => None,
        })
    }

    pub(crate) fn eval_optional_string_index(
        &mut self,
        expr: &HirExpr,
        default: i64,
    ) -> Result<i64, RuntimeError> {
        Ok(self.eval_string_index(expr)?.unwrap_or(default))
    }
}
