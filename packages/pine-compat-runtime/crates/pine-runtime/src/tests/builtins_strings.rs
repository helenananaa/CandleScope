use pine_sema::analyze_source;
use pine_syntax::SourceFile;
use regex::Regex;

use crate::builtins::strings::normalize_pine_regex;

use super::*;

#[test]
fn normalizes_pine_regex_unicode_class_modes() {
    assert_eq!(
        normalize_pine_regex(r"\d(?U)\w(?-U)\s"),
        r"[0-9]\w[ \t\n\x0B\f\r]"
    );
    assert_eq!(
        normalize_pine_regex(r"(?iU:\d)(?-U:\w)"),
        r"(?i:\d)(?:[A-Za-z0-9_])"
    );
    assert_eq!(
        normalize_pine_regex("(?x)\\d # (?U)\\w\n(?U)\\w"),
        "(?x)[0-9] \n\\w"
    );
    assert_eq!(normalize_pine_regex("(?)"), "(?)");
    assert_eq!(normalize_pine_regex("(?-)"), "(?-)");
}

#[test]
fn normalizes_pine_regex_literal_case_modes() {
    assert_eq!(
        normalize_pine_regex(r"(?i)kβ(?U)kβ(?-U)\u004B\u03B2"),
        r"(?i)(?i-u:\x{6B})(?-i:\x{3B2})kβ(?i-u:\x{4B})(?-i:\x{3B2})"
    );
    assert_eq!(
        normalize_pine_regex(r"(?i)(?<word>k)\p{Lu}"),
        r"(?i)(?<word>(?i-u:\x{6B}))\p{Lu}"
    );

    let ascii = Regex::new(&normalize_pine_regex(r"(?i)\Akβ\z"))
        .expect("normalized ASCII-insensitive literal regex");
    assert!(ascii.is_match("Kβ"));
    assert!(!ascii.is_match("Kβ"));
    assert!(!ascii.is_match("KΒ"));

    let unicode = Regex::new(&normalize_pine_regex(r"(?iU)\Akβ\z"))
        .expect("normalized Unicode-insensitive literal regex");
    assert!(unicode.is_match("KΒ"));

    let quoted = Regex::new(&normalize_pine_regex(r"(?i)\A\Qkβ+\E\z"))
        .expect("normalized quoted ASCII-insensitive literal regex");
    assert!(quoted.is_match("Kβ+"));
    assert!(!quoted.is_match("KΒ+"));
}

#[test]
fn normalizes_pine_regex_unicode_case_flag() {
    let literal = Regex::new(&normalize_pine_regex(r"(?iu)\Akβ\z"))
        .expect("normalized Unicode case-insensitive literal regex");
    assert!(literal.is_match("KΒ"));

    let scoped = Regex::new(&normalize_pine_regex(r"\A(?iu:å)(?i:å)\z"))
        .expect("normalized scoped Unicode case mode");
    assert!(scoped.is_match("Åå"));
    assert!(!scoped.is_match("ÅÅ"));

    let literal_class = Regex::new(&normalize_pine_regex(r"(?iu)\A[k]\z"))
        .expect("normalized Unicode-folded literal class");
    assert!(literal_class.is_match("K"));

    let predefined = Regex::new(&normalize_pine_regex(r"(?iu)\A\w[\w]\z"))
        .expect("normalized ASCII predefined classes under Unicode case mode");
    assert!(predefined.is_match("KA"));
    assert!(!predefined.is_match("KA"));
    assert!(!predefined.is_match("KK"));
    assert!(!predefined.is_match("éA"));

    let posix = Regex::new(&normalize_pine_regex(r"(?iu)\A\p{Lower}\z"))
        .expect("normalized ASCII POSIX class under Unicode case mode");
    assert!(posix.is_match("A"));
    assert!(!posix.is_match("K"));
    assert!(!posix.is_match("Β"));

    let classes_without_case = Regex::new(&normalize_pine_regex(r"(?iU-u)\A[k]\w\p{Lower}\z"))
        .expect("normalized Unicode classes with ASCII case mode");
    assert!(classes_without_case.is_match("KKΒ"));
    assert!(!classes_without_case.is_match("KKΒ"));

    let disabled_together = Regex::new(&normalize_pine_regex(r"(?iU)(?-U)\Aå\w\z"))
        .expect("normalized Unicode class and case disablement");
    assert!(disabled_together.is_match("åA"));
    assert!(!disabled_together.is_match("ÅA"));
    assert!(!disabled_together.is_match("åé"));

    let references = Regex::new(&normalize_pine_regex(r"(?iu)\A\Qå\E\u00E5\x{E5}\0145\cβ\z"))
        .expect("normalized Unicode-folded quoted and escaped literals");
    assert!(references.is_match("ÅÅÅEϹ"));
}

#[test]
fn normalizes_pine_regex_character_class_case_modes() {
    let ascii = Regex::new(&normalize_pine_regex(r"(?i)\A[kβ]\z"))
        .expect("normalized ASCII-insensitive character class");
    assert!(ascii.is_match("K"));
    assert!(ascii.is_match("β"));
    assert!(!ascii.is_match("K"));
    assert!(!ascii.is_match("Β"));

    let unicode = Regex::new(&normalize_pine_regex(r"(?iU)\A[kβ]\z"))
        .expect("normalized Unicode-insensitive character class");
    assert!(unicode.is_match("K"));
    assert!(unicode.is_match("Β"));

    let negated = Regex::new(&normalize_pine_regex(r"(?i)\A[^k]\z"))
        .expect("normalized negated ASCII-insensitive class");
    assert!(!negated.is_match("K"));
    assert!(negated.is_match("K"));

    let intersection = Regex::new(&normalize_pine_regex(r"(?i)\A[a-z&&[^q]]\z"))
        .expect("normalized intersected ASCII-insensitive class");
    assert!(intersection.is_match("A"));
    assert!(!intersection.is_match("Q"));
    assert!(!intersection.is_match("ſ"));

    let category = Regex::new(&normalize_pine_regex(r"(?i)\A[\p{Lu}]\z"))
        .expect("normalized case-insensitive category class");
    assert!(category.is_match("β"));

    let ascii_word = Regex::new(&normalize_pine_regex(r"(?i)\A\w\z"))
        .expect("normalized ASCII word class under case-insensitive mode");
    assert!(ascii_word.is_match("K"));
    assert!(!ascii_word.is_match("K"));

    let ascii_lower = Regex::new(&normalize_pine_regex(r"(?i)\A\p{Lower}\z"))
        .expect("normalized ASCII POSIX lower class under case-insensitive mode");
    assert!(ascii_lower.is_match("A"));
    assert!(!ascii_lower.is_match("K"));
    assert!(!ascii_lower.is_match("β"));

    let unicode_lower = Regex::new(&normalize_pine_regex(r"(?iU)\A\p{Lower}\z"))
        .expect("normalized Unicode POSIX lower class under case-insensitive mode");
    assert!(unicode_lower.is_match("K"));
    assert!(unicode_lower.is_match("Β"));

    let block = Regex::new(&normalize_pine_regex(r"(?iU)\A[x\p{InBasicLatin}]\z"))
        .expect("normalized exact Unicode block under case-insensitive mode");
    assert!(block.is_match("X"));
    assert!(!block.is_match("K"));

    let standalone_block = Regex::new(&normalize_pine_regex(r"(?iU)\A\p{InBasicLatin}\z"))
        .expect("normalized standalone exact block under case-insensitive mode");
    assert!(standalone_block.is_match("K"));
    assert!(!standalone_block.is_match("K"));

    let negated_block = Regex::new(&normalize_pine_regex(r"(?iU)\A\P{InBasicLatin}\z"))
        .expect("normalized standalone negated block under case-insensitive mode");
    assert!(!negated_block.is_match("K"));
    assert!(negated_block.is_match("K"));

    let ascii_property = Regex::new(&normalize_pine_regex(r"(?iU)\A\p{ASCII}\z"))
        .expect("normalized exact POSIX ASCII property under case-insensitive mode");
    assert!(ascii_property.is_match("K"));
    assert!(!ascii_property.is_match("K"));

    let quoted = Regex::new(&normalize_pine_regex(r"(?i)\A[\Qkβ\E]\z"))
        .expect("normalized quoted ASCII-insensitive character class");
    assert!(quoted.is_match("K"));
    assert!(quoted.is_match("β"));
    assert!(!quoted.is_match("K"));
    assert!(!quoted.is_match("("));

    let scoped = Regex::new(&normalize_pine_regex(r"\A(?i:[k])(?iU:[k])(?i-U:[β])\z"))
        .expect("normalized scoped character-class case modes");
    assert!(scoped.is_match("KKβ"));
    assert!(!scoped.is_match("KKΒ"));
}

#[test]
fn normalizes_pine_regex_literal_class_tildes() {
    assert_eq!(
        normalize_pine_regex(r"[a-z~~m][a-~~][~][\~]~~"),
        r"[a-z\x{7E}\x{7E}m][a-\x{7E}\x{7E}][\x{7E}][\x{7E}]~~"
    );

    let pair = Regex::new(&normalize_pine_regex(r"\A[a-z~~m]+\z"))
        .expect("normalized literal class tilde pair");
    assert!(pair.is_match("m~"));
    assert!(pair.is_match("az~"));
    assert!(!pair.is_match("A"));

    let range =
        Regex::new(&normalize_pine_regex(r"\A[a-~~]+\z")).expect("normalized tilde range endpoint");
    assert!(range.is_match("az{|}~"));
    assert!(!range.is_match("`"));

    let escaped = Regex::new(&normalize_pine_regex(r"\A\~[\~]\z"))
        .expect("normalized escaped literal tildes");
    assert!(escaped.is_match("~~"));

    let nested = Regex::new(&normalize_pine_regex(r"\A[x[~~]]+\z"))
        .expect("normalized nested literal class tildes");
    assert!(nested.is_match("~x"));
    assert!(!nested.is_match("m"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A[\Q~~\E]+\z"))
        .expect("normalized quoted literal class tildes");
    assert!(quoted.is_match("~~"));

    let insensitive = Regex::new(&normalize_pine_regex(r"(?i)\A[~~a]+\z"))
        .expect("normalized case-insensitive literal class tildes");
    assert!(insensitive.is_match("~A"));

    let outside = Regex::new(&normalize_pine_regex(r"\A~~\z"))
        .expect("preserved unescaped tildes outside a character class");
    assert!(outside.is_match("~~"));
}

#[test]
fn normalizes_pine_regex_java_class_ranges() {
    assert_eq!(
        normalize_pine_regex(r"[a-z--m][--a][--][a-z-][a-z---m]"),
        r"[a-z\x{2D}-m][\x{2D}-a][\x{2D}\x{2D}][a-z\x{2D}][a-z\x{2D}-\x{2D}m]"
    );

    let direct = Regex::new(&normalize_pine_regex(r"\A[a-z--m]+\z"))
        .expect("normalized Java ranges adjacent to raw hyphens");
    assert!(direct.is_match("-0AZaz"));
    assert!(!direct.is_match("{"));

    let leading = Regex::new(&normalize_pine_regex(r"\A[--a]+\z"))
        .expect("normalized Java range with a hyphen start");
    assert!(leading.is_match("-0AZa"));
    assert!(!leading.is_match("b"));

    let literal = Regex::new(&normalize_pine_regex(r"\A[--]\z"))
        .expect("normalized literal Java hyphen pair");
    assert!(literal.is_match("-"));
    assert!(!literal.is_match("a"));

    let low_endpoint = Regex::new(&normalize_pine_regex(r"\A[!--a]+\z"))
        .expect("normalized Java range ending in a hyphen");
    assert!(low_endpoint.is_match("!-a"));
    assert!(!low_endpoint.is_match("."));

    let quoted = Regex::new(&normalize_pine_regex(r"\A[\Q-\E-a]+\z"))
        .expect("normalized quoted Java range start");
    assert!(quoted.is_match("-0AZa"));
    assert!(!quoted.is_match("b"));

    let escaped = Regex::new(&normalize_pine_regex(r"\A[\--a]+\z"))
        .expect("normalized escaped Java range start");
    assert!(escaped.is_match("-0AZa"));
    assert!(!escaped.is_match("b"));

    let nested = Regex::new(&normalize_pine_regex(r"\A[a-[b]]+\z"))
        .expect("normalized hyphen before a nested Java class");
    assert!(nested.is_match("-ab"));
    assert!(!nested.is_match("c"));

    let intersection = Regex::new(&normalize_pine_regex(r"\A[a&&--b]\z"))
        .expect("normalized Java range on an intersection RHS");
    assert!(intersection.is_match("a"));
    assert!(!intersection.is_match("b"));

    let after_set = Regex::new(&normalize_pine_regex(r"\A[\p{L}--a]+\z"))
        .expect("normalized Java hyphen range after a set atom");
    assert!(after_set.is_match("β-0a"));
    assert!(!after_set.is_match("!"));

    let verbose = Regex::new(&normalize_pine_regex(
        "(?x)\\A[a-z- # first hyphen\n-m]+\\z",
    ))
    .expect("normalized verbose Java hyphen range");
    assert!(verbose.is_match("-0AZaz"));
    assert!(!verbose.is_match("{"));

    let verbose_intersection_pattern = normalize_pine_regex(r"(?x)\A[a & & --b]\z");
    let verbose_intersection =
        Regex::new(&verbose_intersection_pattern).expect("normalized verbose Java intersection");
    assert!(verbose_intersection.is_match("a"));
    assert!(!verbose_intersection.is_match("b"));

    let commented_intersection =
        Regex::new(&normalize_pine_regex("(?x)\\A[a& # intersection\n&--b]\\z"))
            .expect("normalized comment-separated Java intersection");
    assert!(commented_intersection.is_match("a"));
    assert!(!commented_intersection.is_match("b"));

    let insensitive = Regex::new(&normalize_pine_regex(r"(?iU)\A[a-z--~]+\z"))
        .expect("normalized case-insensitive Java hyphen and tilde range");
    assert!(insensitive.is_match("K-~"));
    assert!(!insensitive.is_match("\u{007F}"));
}

#[test]
fn normalizes_pine_regex_class_ampersand_boundaries() {
    for (pattern, expected) in [
        (r"[&]", r"[\x{26}]"),
        (r"[a&b]", r"[a\x{26}b]"),
        (r"[a&&]", r"[a]"),
        (r"[&&a]", r"[a]"),
        (r"[a&&&b]", r"[[a]\x{26}b]"),
        (r"[a&&&&b]", r"[[a]&&b]"),
        (r"[a&&&&&b]", r"[[[a]]\x{26}b]"),
        (r"[&-b]", r"[\x{26}-b]"),
        (r"[\Q&&\E]", r"[\x{26}\x{26}]"),
        (r"[\&]", r"[\x{26}]"),
        (r"[da-c&&]", r"[da-c&&a-c]"),
        (r"[A\d&&]", r"[A[0-9]&&[0-9]]"),
        (r"[c[ab]&&]", r"[c[ab]&&[ab]]"),
        (r"[da-c&&&x]", r"[[da-c&&a-c]\x{64}\x{26}x]"),
        (r"[A\d&&&x]", r"[[A[0-9]&&[0-9]]\x{41}\x{26}x]"),
        (r"[a&&b&&&c]", r"[a&&[b]\x{26}c]"),
        (r"[a-c&&b-d&&&x]", r"[a-c&&[b-d]\x{26}x]"),
        (r"[da-c&&&&d]", r"[[da-c&&a-c]&&d]"),
        (r"[A\d&&&&A]", r"[[A[0-9]&&[0-9]]&&A]"),
        (r"[da-c&&&&&x]", r"[[[da-c&&a-c]]\x{64}\x{26}x]"),
        (r"[Aa-c&&&-0]", r"[[Aa-c&&a-c]\x{26}-0]"),
        (r"[Aa-c&&&-0x]", r"[[Aa-c&&a-c]\x{26}-0\x{41}x]"),
    ] {
        assert_eq!(normalize_pine_regex(pattern), expected, "{pattern}");
    }

    let odd = Regex::new(&normalize_pine_regex(r"\A[a&&&b]+\z"))
        .expect("normalized odd raw ampersand run");
    assert!(odd.is_match("a&b"));

    let even = Regex::new(&normalize_pine_regex(r"\A[a-b&&&&b-c]+\z"))
        .expect("normalized even raw ampersand run");
    assert!(even.is_match("b"));
    assert!(!even.is_match("a"));
    assert!(!even.is_match("c"));

    let verbose = Regex::new(&normalize_pine_regex("(?x)\\A[a& # split\n&[a-b]]\\z"))
        .expect("normalized verbose-separated ampersand pair");
    assert!(verbose.is_match("a"));
    assert!(!verbose.is_match("b"));

    let repeated_predicate = Regex::new(&normalize_pine_regex(r"\A[da-c&&]+\z"))
        .expect("normalized empty intersection with a final range predicate");
    assert!(repeated_predicate.is_match("abc"));
    assert!(!repeated_predicate.is_match("d"));

    let repeated_set = Regex::new(&normalize_pine_regex(r"\A[A\d&&]+\z"))
        .expect("normalized empty intersection with a final set predicate");
    assert!(repeated_set.is_match("123"));
    assert!(!repeated_set.is_match("A"));

    let revived_bits = Regex::new(&normalize_pine_regex(r"\A[da-c&&&x]+\z"))
        .expect("normalized odd run with revived Java BitClass literals");
    assert!(revived_bits.is_match("abcdx&"));
    assert!(!revived_bits.is_match("e"));

    let prior_intersection = Regex::new(&normalize_pine_regex(r"\A[a&&b&&&c]\z"))
        .expect("normalized odd run in a Java intersection RHS");
    for ch in ["a", "b", "c", "&"] {
        assert!(!prior_intersection.is_match(ch), "{ch}");
    }
    let recovered_rhs = Regex::new(&normalize_pine_regex(r"\A[a&&b&&&a]\z"))
        .expect("normalized Java intersection RHS revived by a later literal");
    assert!(recovered_rhs.is_match("a"));

    let intersected_range = Regex::new(&normalize_pine_regex(r"\A[a-c&&b-d&&&x]+\z"))
        .expect("normalized odd run in a ranged intersection RHS");
    assert!(intersected_range.is_match("bc"));
    assert!(!intersected_range.is_match("a"));
    assert!(!intersected_range.is_match("d"));

    let predicate_union = Regex::new(&normalize_pine_regex(r"\A[[ab][cd]&&&x]+\z"))
        .expect("normalized predicate-only Java class continuation");
    assert!(predicate_union.is_match("cdx&"));
    assert!(!predicate_union.is_match("a"));

    let unicode_case = Regex::new(&normalize_pine_regex(r"(?iU)\A[k\d&&&x]+\z"))
        .expect("normalized Unicode-case Java BitClass exception");
    assert!(unicode_case.is_match("1xX&"));
    assert!(!unicode_case.is_match("K"));
    assert!(!unicode_case.is_match("K"));

    let verbose_mixed = Regex::new(&normalize_pine_regex(
        "(?x)\\A[d a-c & # first pair byte\n & & x]+\\z",
    ))
    .expect("normalized verbose mixed-predicate odd run");
    assert!(verbose_mixed.is_match("abcdx&"));
    assert!(!verbose_mixed.is_match("e"));

    let next_intersection = Regex::new(&normalize_pine_regex(r"\A[da-c&&&&d]\z"))
        .expect("normalized non-empty intersection after an empty pair");
    assert!(!next_intersection.is_match("d"));
    let next_set_intersection = Regex::new(&normalize_pine_regex(r"\A[A\d&&&&A]\z"))
        .expect("normalized set intersection after an empty pair");
    assert!(!next_set_intersection.is_match("A"));

    let repeated_empty = Regex::new(&normalize_pine_regex(r"\A[da-c&&&&&x]+\z"))
        .expect("normalized repeated empty intersections with BitClass revival");
    assert!(repeated_empty.is_match("abcdx&"));
    assert!(!repeated_empty.is_match("e"));
    let repeated_empty_rhs = Regex::new(&normalize_pine_regex(r"\A[da-c&&&&&&b]+\z"))
        .expect("normalized repeated empty intersections before a non-empty RHS");
    assert!(repeated_empty_rhs.is_match("b"));
    assert!(!repeated_empty_rhs.is_match("d"));
    let repeated_twice = Regex::new(&normalize_pine_regex(r"\A[da-c&&&&&&&x]+\z"))
        .expect("normalized three consecutive empty intersections");
    assert!(repeated_twice.is_match("abcdx&"));

    let deferred_range = Regex::new(&normalize_pine_regex(r"\A[Aa-c&&&-0]+\z"))
        .expect("normalized range without later BitClass mutation");
    assert!(deferred_range.is_match("&0abc"));
    assert!(!deferred_range.is_match("A"));
    let revived_after_range = Regex::new(&normalize_pine_regex(r"\A[Aa-c&&&-0x]+\z"))
        .expect("normalized BitClass mutation after a range");
    assert!(revived_after_range.is_match("A&0abcx"));
    let nested_after_range = Regex::new(&normalize_pine_regex(r"\A[Aa-c&&&-0[x]]+\z"))
        .expect("normalized nested predicate after a range");
    assert!(nested_after_range.is_match("&0abcx"));
    assert!(!nested_after_range.is_match("A"));
    let predicate_after_mutation = Regex::new(&normalize_pine_regex(r"\A[Aa-c&&&-0x\d&&]+\z"))
        .expect("normalized predicate following a revived BitClass");
    assert!(predicate_after_mutation.is_match("01"));
    assert!(!predicate_after_mutation.is_match("A"));
    for pattern in [r"\A[Aa-c&&&-0\x78]+\z", r"\A[Aa-c&&&-0\Qx\E]+\z"] {
        let escaped = Regex::new(&normalize_pine_regex(pattern))
            .expect("normalized escaped BitClass mutation after a range");
        assert!(escaped.is_match("A&0abcx"), "{pattern}");
    }
    let unicode_exception = Regex::new(&normalize_pine_regex(r"(?iU)\A[da-c&&&-0k]+\z"))
        .expect("normalized non-BitClass Unicode case literal after a range");
    assert!(unicode_exception.is_match("KK"));
    assert!(!unicode_exception.is_match("D"));
    let unicode_bit = Regex::new(&normalize_pine_regex(r"(?iU)\A[da-c&&&-0x]+\z"))
        .expect("normalized Unicode-case BitClass mutation after a range");
    assert!(unicode_bit.is_match("DX"));

    for invalid in [
        r"[&&]",
        r"[&&&]",
        r"[&&&a]",
        r"[a-cd&&]",
        r"[\dA&&]",
        r"[[ab]c&&]",
    ] {
        assert!(
            Regex::new(&normalize_pine_regex(invalid)).is_err(),
            "{invalid}"
        );
    }
}

#[test]
fn preserves_invalid_pine_regex_java_class_ranges() {
    for invalid in [
        r"[a--b]",
        r"[a--]",
        r"[.--]",
        r"[a-\p{L}]",
        r"[a-\d]",
        r"[a-\Q-\E]",
        r"(?i)[a-\p{L}]",
        "(?x)[a- ]",
        "(?x)[a- ]x]",
    ] {
        assert!(
            Regex::new(&normalize_pine_regex(invalid)).is_err(),
            "{invalid}"
        );
    }
}

#[test]
fn normalizes_pine_regex_ascii_literal_escapes() {
    assert_eq!(
        normalize_pine_regex(r"\!\%\_\`\~"),
        r"\x{21}\x{25}\x{5F}\x{60}\x{7E}"
    );

    for byte in 0_u8..=0x7F {
        let ch = char::from(byte);
        if ch.is_ascii_alphanumeric() {
            continue;
        }
        let escaped = format!(r"\{ch}");
        let literal = Regex::new(&normalize_pine_regex(&format!(r"\A{escaped}\z")))
            .unwrap_or_else(|error| panic!("normalized escaped U+{byte:04X}: {error}"));
        assert!(literal.is_match(&ch.to_string()), "outside U+{byte:04X}");

        let class = Regex::new(&normalize_pine_regex(&format!(r"\A[{escaped}]\z")))
            .unwrap_or_else(|error| panic!("normalized class-escaped U+{byte:04X}: {error}"));
        assert!(class.is_match(&ch.to_string()), "class U+{byte:04X}");
    }

    let verbose = Regex::new(&normalize_pine_regex(r"(?x)\A\#\ \z"))
        .expect("normalized verbose escaped hash and space");
    assert!(verbose.is_match("# "));

    let insensitive = Regex::new(&normalize_pine_regex(r"(?i)\A\_[a]\z"))
        .expect("normalized case-insensitive escaped punctuation");
    assert!(insensitive.is_match("_A"));

    assert!(Regex::new(&normalize_pine_regex(r"\q")).is_err());
}

#[test]
fn normalizes_pine_regex_horizontal_whitespace_classes() {
    let horizontal =
        Regex::new(&normalize_pine_regex(r"^\h$")).expect("normalized horizontal whitespace regex");
    for ch in [
        ' ', '\t', '\u{00a0}', '\u{1680}', '\u{180e}', '\u{2000}', '\u{200a}', '\u{202f}',
        '\u{205f}', '\u{3000}',
    ] {
        assert!(horizontal.is_match(&ch.to_string()), "U+{:04X}", ch as u32);
    }
    assert!(!horizontal.is_match("\n"));

    let non_horizontal = Regex::new(&normalize_pine_regex(r"^\H$"))
        .expect("normalized non-horizontal whitespace regex");
    assert!(non_horizontal.is_match("A"));
    assert!(non_horizontal.is_match("\n"));
    assert!(!non_horizontal.is_match("\u{2003}"));

    assert_eq!(
        normalize_pine_regex(r"(?U:\h)[\H](?-U:\h)"),
        r"(?:[ \t\x{00A0}\x{1680}\x{180E}\x{2000}-\x{200A}\x{202F}\x{205F}\x{3000}])[[^ \t\x{00A0}\x{1680}\x{180E}\x{2000}-\x{200A}\x{202F}\x{205F}\x{3000}]](?:[ \t\x{00A0}\x{1680}\x{180E}\x{2000}-\x{200A}\x{202F}\x{205F}\x{3000}])"
    );
}

#[test]
fn normalizes_pine_regex_vertical_whitespace_classes() {
    let vertical =
        Regex::new(&normalize_pine_regex(r"^\v$")).expect("normalized vertical whitespace regex");
    for ch in [
        '\n', '\u{000b}', '\u{000c}', '\r', '\u{0085}', '\u{2028}', '\u{2029}',
    ] {
        assert!(vertical.is_match(&ch.to_string()), "U+{:04X}", ch as u32);
    }
    for ch in ['\t', ' ', '\u{00a0}', '\u{3000}', 'A'] {
        assert!(!vertical.is_match(&ch.to_string()), "U+{:04X}", ch as u32);
    }

    let non_vertical = Regex::new(&normalize_pine_regex(r"^\V$"))
        .expect("normalized non-vertical whitespace regex");
    assert!(non_vertical.is_match("A"));
    assert!(non_vertical.is_match("\t"));
    assert!(!non_vertical.is_match("\u{2028}"));

    let modes = Regex::new(&normalize_pine_regex(r"\A(?U:\v)(?-U:\v)[\V]\z"))
        .expect("normalized vertical classes across Unicode modes");
    assert!(modes.is_match("\u{0085}\u{2029}A"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\v\E\z"))
        .expect("normalized quoted vertical-class spelling");
    assert!(quoted.is_match(r"\v"));
    assert!(!quoted.is_match("\u{000b}"));
}

#[test]
fn normalizes_pine_regex_line_break_matcher() {
    let line_break =
        Regex::new(&normalize_pine_regex(r"\A\R\z")).expect("normalized line-break matcher");
    for text in [
        "\n", "\u{000b}", "\u{000c}", "\r", "\u{0085}", "\u{2028}", "\u{2029}", "\r\n",
    ] {
        assert!(line_break.is_match(text), "{text:?}");
    }
    for text in ["", "\t", " ", "A", "\n\r"] {
        assert!(!line_break.is_match(text), "{text:?}");
    }

    let crlf = Regex::new(&normalize_pine_regex(r"\R"))
        .expect("normalized CRLF line-break matcher")
        .find("\r\n")
        .expect("CRLF is a line break");
    assert_eq!(crlf.as_str(), "\r\n");

    let modes = Regex::new(&normalize_pine_regex(r"\A(?U:\R)(?-U:\R)\z"))
        .expect("normalized line-break matcher across Unicode modes");
    assert!(modes.is_match("\r\n\u{2028}"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\R\E\z"))
        .expect("normalized quoted line-break spelling");
    assert!(quoted.is_match(r"\R"));
    assert!(!quoted.is_match("\r\n"));

    assert!(Regex::new(&normalize_pine_regex(r"[\R]")).is_err());
}

#[test]
fn normalizes_pine_regex_control_character_escapes() {
    let escape = Regex::new(&normalize_pine_regex(r"\A\e[\e]\z"))
        .expect("normalized escape-character references");
    assert!(escape.is_match("\u{001b}\u{001b}"));

    let controls = Regex::new(&normalize_pine_regex(r"\A\cA\ca\c😀\cAB\z"))
        .expect("normalized control-character references");
    assert!(controls.is_match("\u{0001}!🙀\u{0001}B"));

    let cases = Regex::new(&normalize_pine_regex(r"\A(?i:\c1)(?iU:\cβ)(?i:[\c1])\z"))
        .expect("normalized case-folded control-character references");
    assert!(cases.is_match("QϹQ"));
    assert!(!cases.is_match("ℚϹQ"));

    let verbose = Regex::new(&normalize_pine_regex("(?x)\\A\\c # comment\n A\\z"))
        .expect("normalized verbose control-character reference");
    assert!(verbose.is_match("\u{0001}"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\e\cA\E\z"))
        .expect("normalized quoted control-reference spellings");
    assert!(quoted.is_match(r"\e\cA"));

    assert!(Regex::new(&normalize_pine_regex(r"\c")).is_err());
}

#[test]
fn normalizes_pine_regex_octal_escapes() {
    let widths = Regex::new(&normalize_pine_regex(r"\A\01\077x\0377x\0777\0400\0128\z"))
        .expect("normalized octal references");
    assert!(widths.is_match("\u{0001}?xÿx?7 0\n8"));

    let cases = Regex::new(&normalize_pine_regex(
        r"\A(?i:\0161)(?iU:\0345)(?i:[\0161])\z",
    ))
    .expect("normalized case-folded octal references");
    assert!(cases.is_match("QÅQ"));
    assert!(!cases.is_match("ℚÅQ"));

    let class = Regex::new(&normalize_pine_regex(r"\A[\0141]\z"))
        .expect("normalized character-class octal reference");
    assert!(class.is_match("a"));

    let verbose = Regex::new(&normalize_pine_regex("(?x)\\A\\0 1 # comment\n 6 1\\z"))
        .expect("normalized verbose octal reference");
    assert!(verbose.is_match("q"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\0141\E\z"))
        .expect("normalized quoted octal-reference spelling");
    assert!(quoted.is_match(r"\0141"));

    for invalid in [r"\0", r"\08"] {
        assert!(
            Regex::new(&normalize_pine_regex(invalid)).is_err(),
            "{invalid}"
        );
    }
}

#[test]
fn normalizes_pine_regex_previous_match_anchor() {
    let anchored =
        Regex::new(&normalize_pine_regex(r"\Gabc")).expect("normalized previous-match anchor");
    assert_eq!(
        anchored.find("abc").map(|matched| matched.as_str()),
        Some("abc")
    );
    assert!(anchored.find("xabc").is_none());

    let empty =
        Regex::new(&normalize_pine_regex(r"\G")).expect("normalized empty previous-match anchor");
    assert_eq!(empty.find("abc").map(|matched| matched.range()), Some(0..0));

    let consumed = Regex::new(&normalize_pine_regex(r"a\G"))
        .expect("normalized consumed-prefix previous-match anchor");
    assert!(!consumed.is_match("a"));

    let multiline = Regex::new(&normalize_pine_regex(r"(?m)\Gabc"))
        .expect("normalized multiline previous-match anchor");
    assert!(!multiline.is_match("x\nabc"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\G\E\z"))
        .expect("normalized quoted previous-match-anchor spelling");
    assert!(quoted.is_match(r"\G"));

    assert!(Regex::new(&normalize_pine_regex(r"[\G]")).is_err());
}

#[test]
fn normalizes_pine_regex_leading_class_closers() {
    let leading =
        Regex::new(&normalize_pine_regex(r"\A[]a]\z")).expect("normalized leading class closer");
    assert!(leading.is_match("]"));
    assert!(leading.is_match("a"));
    assert!(!leading.is_match("b"));

    let negated = Regex::new(&normalize_pine_regex(r"\A[^]]\z"))
        .expect("normalized negated leading class closer");
    assert!(!negated.is_match("]"));
    assert!(negated.is_match("a"));

    let caret = Regex::new(&normalize_pine_regex(r"\A[^^]\z"))
        .expect("normalized leading negation and caret literal");
    assert!(!caret.is_match("^"));
    assert!(caret.is_match("a"));

    let insensitive = Regex::new(&normalize_pine_regex(r"(?i)\A[]a]\z"))
        .expect("normalized case-insensitive leading class closer");
    assert!(insensitive.is_match("A"));
    assert!(insensitive.is_match("]"));

    let verbose = Regex::new(&normalize_pine_regex("(?x)\\A[ # note\n ]]\\z"))
        .expect("normalized verbose leading class closer");
    assert!(verbose.is_match("]"));

    let empty_quote = Regex::new(&normalize_pine_regex(r"\A[\Q\E]]\z"))
        .expect("normalized leading closer after an empty quote");
    assert!(empty_quote.is_match("]"));

    let quoted =
        Regex::new(&normalize_pine_regex(r"\A[\Q]\E]\z")).expect("normalized quoted class closer");
    assert!(quoted.is_match("]"));
}

#[test]
fn normalizes_pine_regex_verbose_trivia() {
    for ch in [
        '\u{0085}', '\u{00a0}', '\u{1680}', '\u{2003}', '\u{2028}', '\u{2029}', '\u{3000}',
    ] {
        let pattern = format!("(?x)\\Aa{ch}b\\z");
        let matcher = Regex::new(&normalize_pine_regex(&pattern))
            .unwrap_or_else(|error| panic!("normalized literal U+{:04X}: {error}", ch as u32));
        assert!(matcher.is_match(&format!("a{ch}b")), "U+{:04X}", ch as u32);
        assert!(!matcher.is_match("ab"), "U+{:04X}", ch as u32);
    }

    for (separator, expected) in [
        ('\n', "ab".to_owned()),
        ('\r', "ab".to_owned()),
        ('\u{0085}', "a\u{0085}b".to_owned()),
        ('\u{2028}', "a\u{2028}b".to_owned()),
        ('\u{2029}', "a\u{2029}b".to_owned()),
    ] {
        let pattern = format!("(?x)\\Aa# note{separator}b\\z");
        let matcher = Regex::new(&normalize_pine_regex(&pattern)).unwrap_or_else(|error| {
            panic!(
                "normalized comment terminator U+{:04X}: {error}",
                separator as u32
            )
        });
        assert!(matcher.is_match(&expected), "U+{:04X}", separator as u32);
    }

    for separator in ['\u{000b}', '\u{000c}'] {
        assert_eq!(
            normalize_pine_regex(&format!("(?x)\\Aa# note{separator}b\\z")),
            r"(?x)\Aa"
        );
    }

    let carriage_class = Regex::new(&normalize_pine_regex("(?x)\\A[a# note\r]\\z"))
        .expect("normalized carriage-return comment inside a class");
    assert!(carriage_class.is_match("a"));

    let unicode_class = Regex::new(&normalize_pine_regex("(?x)\\A[# note\u{0085}]\\z"))
        .expect("normalized Unicode comment terminator inside a class");
    assert!(unicode_class.is_match("\u{0085}"));

    let protected = Regex::new(&normalize_pine_regex(
        "(?x)\\A\\Q# \u{2003}\\E\\#\\\u{2003}\\z",
    ))
    .expect("normalized quoted and escaped verbose literals");
    assert!(protected.is_match("# \u{2003}#\u{2003}"));

    let scoped = Regex::new(&normalize_pine_regex("(?x:\\Aa# note\rb)(?-x:\u{2003})\\z"))
        .expect("normalized scoped verbose comment");
    assert!(scoped.is_match("ab\u{2003}"));
}

#[test]
fn normalizes_pine_regex_quoted_literals() {
    assert_eq!(
        normalize_pine_regex(r"\Q(?U)\d[.]# \E\d"),
        r"\x{28}\x{3F}\x{55}\x{29}\x{5C}\x{64}\x{5B}\x{2E}\x{5D}\x{23}\x{20}[0-9]"
    );

    let verbose = Regex::new(&normalize_pine_regex(r"(?x)^\Q# [ ]\E$"))
        .expect("normalized verbose quoted regex");
    assert!(verbose.is_match("# [ ]"));

    let in_class = Regex::new(&normalize_pine_regex(r"^[\Q]-\E]+$"))
        .expect("normalized quoted character class regex");
    assert!(in_class.is_match("]-"));

    let unclosed =
        Regex::new(&normalize_pine_regex(r"^\Q[a]+$")).expect("normalized unclosed quoted regex");
    assert!(unclosed.is_match("[a]+$"));
}

#[test]
fn normalizes_pine_regex_four_digit_unicode_escapes() {
    assert_eq!(
        normalize_pine_regex(r"\u2014[\u00E5]\u00610"),
        r"\x{2014}[\x{00E5}]\x{0061}0"
    );
    assert_eq!(normalize_pine_regex(r"\u123"), r"\u123");
    assert_eq!(
        normalize_pine_regex(r"\Q\u2014\E\u2014"),
        r"\x{5C}\x{75}\x{32}\x{30}\x{31}\x{34}\x{2014}"
    );
}

#[test]
fn normalizes_pine_regex_named_character_escapes() {
    assert_eq!(
        normalize_pine_regex(r"\N{LATIN CAPITAL LETTER A}\N{GRINNING FACE}\N{LINE FEED (LF)}"),
        r"\x{41}\x{1F600}\x{A}"
    );
    assert_eq!(
        normalize_pine_regex(
            r"\N{CJK UNIFIED IDEOGRAPHS 4E00}\N{HANGUL SYLLABLES AC00}\N{TANGUT 17000}\N{CJK UNIFIED IDEOGRAPHS EXTENSION B 20000}"
        ),
        r"\x{4E00}\x{AC00}\x{17000}\x{20000}"
    );

    let ascii = Regex::new(&normalize_pine_regex(r"(?i)\A\N{LATIN SMALL LETTER K}\z"))
        .expect("normalized ASCII-insensitive named character");
    assert!(ascii.is_match("K"));
    assert!(ascii.is_match("k"));
    assert!(!ascii.is_match("K"));

    let unicode = Regex::new(&normalize_pine_regex(r"(?iu)\A\N{LATIN SMALL LETTER K}\z"))
        .expect("normalized Unicode-insensitive named character");
    assert!(unicode.is_match("K"));

    let class = Regex::new(&normalize_pine_regex(
        r"\A[\N{LATIN CAPITAL LETTER A}-\N{LATIN CAPITAL LETTER C}]+\z",
    ))
    .expect("normalized named character range");
    assert!(class.is_match("ABC"));
    assert!(!class.is_match("D"));

    let tilde_range = Regex::new(&normalize_pine_regex(r"\A[a-\N{TILDE}]+\z"))
        .expect("normalized named range endpoint");
    assert!(tilde_range.is_match("az{|}~"));
    assert!(!tilde_range.is_match("`"));

    let controls = Regex::new(&normalize_pine_regex(
        r"\A\N{NULL}\N{BEL}\N{BACKSPACE}\N{LINE FEED (LF)}\N{DELETE}\z",
    ))
    .expect("normalized Java control character names");
    assert!(controls.is_match("\0\u{0007}\u{0008}\n\u{007F}"));

    let verbose = Regex::new(&normalize_pine_regex(
        r"(?x)\A\N{ LATIN CAPITAL LETTER A }\z",
    ))
    .expect("normalized trimmed verbose named character");
    assert!(verbose.is_match("A"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\N{LATIN CAPITAL LETTER A}\E\z"))
        .expect("preserved quoted named character spelling");
    assert!(quoted.is_match(r"\N{LATIN CAPITAL LETTER A}"));

    let generated = Regex::new(&normalize_pine_regex(
        r"\A\N{cjk unified ideographs 4e00}\N{HANGUL SYLLABLES AC00}\N{TANGUT SUPPLEMENT 18D00}\z",
    ))
    .expect("normalized Java-generated algorithmic names");
    assert!(generated.is_match("一가\u{18D00}"));
}

#[test]
fn normalizes_pine_regex_unix_lines_mode() {
    assert_eq!(
        normalize_pine_regex(r"(?d).(?-d:.)(?d-s:.)"),
        r"[^\n](?:[^\n\r\x{0085}\x{2028}\x{2029}])(?-s:[^\n])"
    );
    assert_eq!(
        normalize_pine_regex(r"(?dm)^.$(?-d:.)"),
        r"(?m)^[^\n]$(?:[^\n\r\x{0085}\x{2028}\x{2029}])"
    );

    let dot =
        Regex::new(&normalize_pine_regex(r"(?d)\A.\z")).expect("normalized global UNIX_LINES dot");
    assert!(dot.is_match("\r"));
    assert!(dot.is_match("\u{0085}"));
    assert!(dot.is_match("\u{2028}"));
    assert!(!dot.is_match("\n"));

    let scoped = Regex::new(&normalize_pine_regex(r"\A(?d:.).\z"))
        .expect("normalized scoped UNIX_LINES restoration");
    assert!(scoped.is_match("\rA"));
    assert!(!scoped.is_match("\r\u{2028}"));

    let disabled = Regex::new(&normalize_pine_regex(r"(?d)\A(?-d:A).\z"))
        .expect("normalized disabled UNIX_LINES scope");
    assert!(disabled.is_match("A\r"));
    assert!(!disabled.is_match("A\n"));

    let dotall = Regex::new(&normalize_pine_regex(r"(?ds)\A.\z"))
        .expect("normalized UNIX_LINES dotall precedence");
    assert!(dotall.is_match("\n"));
}

#[test]
fn rejects_invalid_pine_regex_named_character_escapes() {
    for invalid in [
        r"\N{}",
        r"\N",
        r"\N{NO SUCH NAME}",
        r"\N{LATIN_CAPITAL_LETTER_A}",
        r"\N{LATINCAPITALLETTERA}",
        r"\N{LATIN  CAPITAL LETTER A}",
        r"\N{CJK UNIFIED IDEOGRAPH-4E00}",
        r"\N{HANGUL SYLLABLE GA}",
        r"\N{CJK UNIFIED IDEOGRAPHS 04E00}",
        r"\N{CJK UNIFIED IDEOGRAPHS EXTENSION B 2A6FF}",
        r"\N{TANGUT 18D00}",
        r"[z-\N{HYPHEN-MINUS}]",
    ] {
        assert!(
            Regex::new(&normalize_pine_regex(invalid)).is_err(),
            "{invalid}"
        );
    }
}

#[test]
fn normalizes_pine_regex_hex_code_point_escapes() {
    assert_eq!(normalize_pine_regex(r"\x6B0\x{0000006B}"), r"\x{6B}0\x{6B}");

    let ascii = Regex::new(&normalize_pine_regex(r"(?i)\A\x6B\x{3B2}\z"))
        .expect("normalized ASCII-insensitive hex references");
    assert!(ascii.is_match("Kβ"));
    assert!(!ascii.is_match("Kβ"));
    assert!(!ascii.is_match("KΒ"));

    let unicode = Regex::new(&normalize_pine_regex(r"(?iU)\A\x6B\x{3B2}\z"))
        .expect("normalized Unicode-insensitive hex references");
    assert!(unicode.is_match("KΒ"));

    let class = Regex::new(&normalize_pine_regex(r"(?i)\A[\x6B\x{3B2}]\z"))
        .expect("normalized ASCII-insensitive class hex references");
    assert!(class.is_match("K"));
    assert!(class.is_match("β"));
    assert!(!class.is_match("K"));
    assert!(!class.is_match("Β"));

    let surrogate = Regex::new(&normalize_pine_regex(r"\A\x{D800}\z"))
        .expect("normalized surrogate code-unit reference");
    assert!(!surrogate.is_match(""));
    assert!(!surrogate.is_match("A"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\x6B\E\z"))
        .expect("normalized quoted hex-reference spelling");
    assert!(quoted.is_match(r"\x6B"));
    assert!(!quoted.is_match("k"));

    for invalid in [r"\x{}", r"\xG1", r"\x{110000}"] {
        assert!(
            Regex::new(&normalize_pine_regex(invalid)).is_err(),
            "{invalid}"
        );
    }
}

#[test]
fn normalizes_pine_regex_dot_line_terminators() {
    let default_dot =
        Regex::new(&normalize_pine_regex(r"\A.\z")).expect("normalized default-dot regex");
    for ch in ['\n', '\r', '\u{0085}', '\u{2028}', '\u{2029}'] {
        assert!(
            !default_dot.is_match(&ch.to_string()),
            "U+{:04X}",
            ch as u32
        );
    }
    for ch in ['A', '\u{000b}', '\u{000c}'] {
        assert!(default_dot.is_match(&ch.to_string()), "U+{:04X}", ch as u32);
    }

    let dotall = Regex::new(&normalize_pine_regex(r"(?s:\A.\z)")).expect("normalized dotall regex");
    for ch in ['\n', '\r', '\u{0085}', '\u{2028}', '\u{2029}'] {
        assert!(dotall.is_match(&ch.to_string()), "U+{:04X}", ch as u32);
    }

    assert_eq!(
        normalize_pine_regex(r".(?s).(?-s).(?s:.)(?-s:.)"),
        r"[^\n\r\x{0085}\x{2028}\x{2029}](?s).(?-s)[^\n\r\x{0085}\x{2028}\x{2029}](?s:.)(?-s:[^\n\r\x{0085}\x{2028}\x{2029}])"
    );
    assert_eq!(normalize_pine_regex(r"\.[.]\Q.\E"), r"\x{2E}[.]\x{2E}");
}

#[test]
fn normalizes_pine_regex_posix_classes() {
    assert_eq!(
        normalize_pine_regex(r"\p{Lower}\P{XDigit}(?U)\p{Lower}(?-U)\p{XDigit}"),
        r"[a-z][^0-9A-Fa-f]\p{Lowercase}[0-9A-Fa-f]"
    );
    assert_eq!(
        normalize_pine_regex(r"\p{L}\p{Lowercase}\p{Unknown}"),
        r"\p{L}\p{Lowercase}\p{Unknown}"
    );
    assert_eq!(
        normalize_pine_regex(r"\p{alnum}(?U)\p{aLnUm}"),
        r"\p{alnum}[\p{Alphabetic}\p{Nd}]"
    );
    assert!(Regex::new(&normalize_pine_regex(r"\p{alnum}")).is_err());
    assert_eq!(
        normalize_pine_regex(r"\Q\p{Lower}\E\p{Lower}"),
        r"\x{5C}\x{70}\x{7B}\x{4C}\x{6F}\x{77}\x{65}\x{72}\x{7D}[a-z]"
    );

    for name in [
        "Lower", "Upper", "ASCII", "Alpha", "Digit", "Alnum", "Punct", "Graph", "Print", "Blank",
        "Cntrl", "XDigit", "Space",
    ] {
        for prefix in [r"\p", r"\P"] {
            let default_pattern = format!(r"{prefix}{{{name}}}");
            Regex::new(&normalize_pine_regex(&default_pattern))
                .unwrap_or_else(|err| panic!("default {prefix}{{{name}}}: {err}"));
            let unicode_pattern = format!(r"(?U:{prefix}{{{name}}})");
            Regex::new(&normalize_pine_regex(&unicode_pattern))
                .unwrap_or_else(|err| panic!("Unicode {prefix}{{{name}}}: {err}"));
        }
    }

    let default_lower = Regex::new(&normalize_pine_regex(r"\p{Lower}"))
        .expect("normalized default POSIX lower regex");
    assert_eq!(
        default_lower.find("βa").map(|matched| matched.as_str()),
        Some("a")
    );
    let unicode_lower = Regex::new(&normalize_pine_regex(r"(?U)\p{Lower}"))
        .expect("normalized Unicode POSIX lower regex");
    assert_eq!(
        unicode_lower.find("βa").map(|matched| matched.as_str()),
        Some("β")
    );

    let default_xdigit = Regex::new(&normalize_pine_regex(r"[\p{XDigit}]"))
        .expect("normalized default POSIX xdigit regex");
    assert_eq!(
        default_xdigit.find("𝟙F").map(|matched| matched.as_str()),
        Some("F")
    );
    let unicode_xdigit = Regex::new(&normalize_pine_regex(r"(?U)[\p{XDigit}]"))
        .expect("normalized Unicode POSIX xdigit regex");
    assert_eq!(
        unicode_xdigit.find("𝟙F").map(|matched| matched.as_str()),
        Some("𝟙")
    );

    let unicode_graph = Regex::new(&normalize_pine_regex(r"(?U)\p{Graph}"))
        .expect("normalized Unicode POSIX graph regex");
    assert!(unicode_graph.is_match("—"));
    assert!(unicode_graph.is_match("\u{200d}"));
    assert!(!unicode_graph.is_match("\u{00a0}"));
    assert!(!unicode_graph.is_match("\u{0378}"));
    let unicode_print = Regex::new(&normalize_pine_regex(r"(?U)\p{Print}"))
        .expect("normalized Unicode POSIX print regex");
    assert!(unicode_print.is_match("\u{00a0}"));
    assert!(!unicode_print.is_match("\t"));
}

#[test]
fn normalizes_pine_regex_basic_java_properties() {
    let properties = Regex::new(&normalize_pine_regex(
        r"\A\p{javaLowerCase}\p{javaUpperCase}\p{javaAlphabetic}\p{javaIdeographic}\p{javaTitleCase}\p{javaDigit}\p{javaDefined}\p{javaLetter}\p{javaLetterOrDigit}\z",
    ))
    .expect("normalized basic Java character properties");
    assert!(properties.is_match("ªK\u{0345}中ǅ１Aβ１"));

    let complements = Regex::new(&normalize_pine_regex(
        r"\A\P{javaLowerCase}\P{javaDefined}\z",
    ))
    .expect("normalized Java character-property complements");
    assert!(complements.is_match("A\u{0378}"));
    assert!(!complements.is_match("a\u{0378}"));

    let nested = Regex::new(&normalize_pine_regex(
        r"\A[\p{javaLowerCase}\p{javaDigit}][\P{javaLetterOrDigit}]\z",
    ))
    .expect("normalized Java properties inside character classes");
    assert!(nested.is_match("ª_"));
    assert!(nested.is_match("１_"));
    assert!(!nested.is_match("A_"));

    for pattern in [
        r"(?i)\A\p{javaLowerCase}\z",
        r"(?iu)\A\p{javaLowerCase}\z",
        r"(?iU-u)\A\p{javaLowerCase}\z",
    ] {
        let insensitive = Regex::new(&normalize_pine_regex(pattern))
            .unwrap_or_else(|error| panic!("normalized case-insensitive {pattern}: {error}"));
        assert!(insensitive.is_match("Β"), "{pattern}");
    }

    let modes = Regex::new(&normalize_pine_regex(
        r"\A(?U:\p{javaDigit})(?-U:\p{javaDigit})\z",
    ))
    .expect("normalized U-independent Java property");
    assert!(modes.is_match("１１"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\p{javaLowerCase}\E\z"))
        .expect("normalized quoted Java property spelling");
    assert!(quoted.is_match(r"\p{javaLowerCase}"));

    assert!(Regex::new(&normalize_pine_regex(r"\p{javalowercase}")).is_err());
}

#[test]
fn normalizes_pine_regex_identifier_and_character_java_properties() {
    let properties = Regex::new(&normalize_pine_regex(
        r"\A\p{javaJavaIdentifierStart}\p{javaJavaIdentifierPart}\p{javaUnicodeIdentifierStart}\p{javaUnicodeIdentifierPart}\p{javaIdentifierIgnorable}\p{javaSpaceChar}\p{javaWhitespace}\p{javaISOControl}\p{javaMirrored}\z",
    ))
    .expect("normalized Java identifier and character properties");
    assert!(properties.is_match("$\u{200B}℘·\u{85}\u{A0}\u{1C}\u{9F}("));

    let java_start = Regex::new(&normalize_pine_regex(r"\A\p{javaJavaIdentifierStart}+\z"))
        .expect("normalized Java identifier-start property");
    assert!(java_start.is_match("$_AⅠ"));
    assert!(!java_start.is_match("℘"));

    let java_part = Regex::new(&normalize_pine_regex(r"\A\p{javaJavaIdentifierPart}+\z"))
        .expect("normalized Java identifier-part property");
    assert!(java_part.is_match("$_AⅠ１\u{301}\u{200B}\0\u{85}"));
    assert!(!java_part.is_match("·"));

    let unicode_start = Regex::new(&normalize_pine_regex(
        r"\A\p{javaUnicodeIdentifierStart}+\z",
    ))
    .expect("normalized Unicode identifier-start property");
    assert!(unicode_start.is_match("AⅠ℘"));
    assert!(!unicode_start.is_match("$_"));

    let unicode_part = Regex::new(&normalize_pine_regex(r"\A\p{javaUnicodeIdentifierPart}+\z"))
        .expect("normalized Unicode identifier-part property");
    assert!(unicode_part.is_match("_AⅠ℘１\u{301}·\u{200B}\0\u{85}"));
    assert!(!unicode_part.is_match("$"));

    let ignorable = Regex::new(&normalize_pine_regex(r"\A\p{javaIdentifierIgnorable}+\z"))
        .expect("normalized Java identifier-ignorable property");
    assert!(ignorable.is_match("\0\u{8}\u{E}\u{1B}\u{7F}\u{85}\u{9F}\u{200B}"));
    assert!(!ignorable.is_match("\t\u{1C}"));

    let space = Regex::new(&normalize_pine_regex(r"\A\p{javaSpaceChar}+\z"))
        .expect("normalized Java space-character property");
    assert!(space.is_match(" \u{A0}\u{2007}\u{202F}\u{2028}\u{2029}"));
    assert!(!space.is_match("\u{85}\u{1C}"));

    let whitespace = Regex::new(&normalize_pine_regex(r"\A\p{javaWhitespace}+\z"))
        .expect("normalized Java whitespace property");
    assert!(whitespace.is_match("\t\n\u{B}\u{C}\r\u{1C}\u{1F} \u{2028}\u{2029}"));
    assert!(!whitespace.is_match("\u{85}\u{A0}\u{2007}\u{202F}"));

    let iso_control = Regex::new(&normalize_pine_regex(r"\A\p{javaISOControl}+\z"))
        .expect("normalized Java ISO-control property");
    assert!(iso_control.is_match("\0\u{1F}\u{7F}\u{9F}"));
    assert!(!iso_control.is_match(" \u{7E}\u{A0}"));

    let mirrored = Regex::new(&normalize_pine_regex(r"\A\p{javaMirrored}+\z"))
        .expect("normalized Java mirrored property");
    assert!(mirrored.is_match("()<>"));
    assert!(!mirrored.is_match("A"));

    let complements = Regex::new(&normalize_pine_regex(
        r"\A\P{javaWhitespace}\P{javaSpaceChar}\P{javaMirrored}\z",
    ))
    .expect("normalized remaining Java property complements");
    assert!(complements.is_match("\u{A0}\u{85}A"));

    let nested = Regex::new(&normalize_pine_regex(
        r"\A[\p{javaWhitespace}\p{javaJavaIdentifierStart}]+\z",
    ))
    .expect("normalized remaining Java properties inside a character class");
    assert!(nested.is_match("\u{1C}$Ⅰ"));
    assert!(!nested.is_match("·"));

    let modes = Regex::new(&normalize_pine_regex(
        r"\A(?U:\p{javaUnicodeIdentifierStart})(?-U:\p{javaUnicodeIdentifierStart})\z",
    ))
    .expect("normalized U-independent remaining Java property");
    assert!(modes.is_match("℘℘"));

    let quoted = Regex::new(&normalize_pine_regex(r"\A\Q\p{javaWhitespace}\E\z"))
        .expect("normalized quoted remaining Java property spelling");
    assert!(quoted.is_match(r"\p{javaWhitespace}"));

    assert!(Regex::new(&normalize_pine_regex(r"\p{javawhitespace}")).is_err());
}

#[test]
fn normalizes_pine_regex_unicode_blocks() {
    assert_eq!(
        normalize_pine_regex(r"\p{InBasicLatin}\P{Block=Latin-1Supplement}"),
        r"[\x{0}-\x{7F}][^\x{80}-\x{FF}]"
    );
    assert_eq!(
        normalize_pine_regex(r"(?U)\p{block=basic_latin}(?-U)\p{Block=Greek}\p{InGreekAndCoptic}"),
        r"[\x{0}-\x{7F}][\x{370}-\x{3FF}][\x{370}-\x{3FF}]"
    );
    assert_eq!(
        normalize_pine_regex(r"\p{IsLatin}\p{Script=Latin}\p{L}\p{gc=L}"),
        r"\p{IsLatin}\p{Script=Latin}\p{L}\p{gc=L}"
    );
    assert_eq!(
        normalize_pine_regex(r"\Q\p{InBasicLatin}\E\p{InBasicLatin}"),
        r"\x{5C}\x{70}\x{7B}\x{49}\x{6E}\x{42}\x{61}\x{73}\x{69}\x{63}\x{4C}\x{61}\x{74}\x{69}\x{6E}\x{7D}[\x{0}-\x{7F}]"
    );
    assert_eq!(
        normalize_pine_regex(r"\p{InNoSuchBlock}"),
        r"\p{InNoSuchBlock}"
    );
    assert!(Regex::new(&normalize_pine_regex(r"\p{InBasic-Latin}")).is_err());

    let basic_latin = Regex::new(&normalize_pine_regex(r"[\p{InBasicLatin}]"))
        .expect("normalized nested Basic Latin block regex");
    assert_eq!(
        basic_latin.find("βA").map(|matched| matched.as_str()),
        Some("A")
    );

    let latin_one = Regex::new(&normalize_pine_regex(r"\p{Block=Latin-1Supplement}"))
        .expect("normalized Latin-1 Supplement block regex");
    assert_eq!(
        latin_one.find("Aå").map(|matched| matched.as_str()),
        Some("å")
    );

    let greek = Regex::new(&normalize_pine_regex(r"\p{InGreek}"))
        .expect("normalized Greek and Coptic block regex");
    assert!(greek.is_match("\u{037e}"));
    assert!(!greek.is_match("A"));

    let todhri = Regex::new(&normalize_pine_regex(r"\p{Block=Todhri}"))
        .expect("normalized Unicode 16 Todhri block regex");
    assert!(todhri.is_match("\u{105c0}"));
    assert!(!todhri.is_match("A"));

    let surrogate = Regex::new(&normalize_pine_regex(r"\p{InHighSurrogates}"))
        .expect("normalized surrogate block regex");
    assert!(!surrogate.is_match("A"));
    let not_surrogate = Regex::new(&normalize_pine_regex(r"\P{InHighSurrogates}"))
        .expect("normalized negated surrogate block regex");
    assert!(not_surrogate.is_match("A"));
}

#[test]
fn runs_string_helpers() {
    let source = SourceFile::new(
        "test.pine",
        r##"indicator("strings")
mode = input.string("sma", "Mode")
upper = str.upper(mode)
lower = str.lower(upper)
length = str.length(upper)
missing = str.length(na)
missing_upper = str.upper(na)
missing_lower = str.lower(na)
unicode_length = str.length("åβ")
unicode_upper = str.upper("åβ")
unicode_lower = str.lower("ÅΒ")
empty_length = str.length("")
matched = str.contains(upper, "M") and str.startswith(upper, "S") and str.endswith(upper, "A")
not_matched = not str.contains(upper, "Z") and not str.startswith(upper, "M") and not str.endswith(upper, "S")
empty_match = str.contains(upper, "") and str.startswith(upper, "") and str.endswith(upper, "")
empty_source_match = str.contains("", "") and str.startswith("", "") and str.endswith("", "")
missing_match = str.contains(na, "S")
missing_pattern_match = str.contains(upper, na)
missing_pattern_start = str.startswith(upper, na)
missing_pattern_end = str.endswith(upper, na)
mid = str.pos(upper, "M")
missing_pos = str.pos(upper, "Z")
empty_pos = str.pos(upper, "")
na_pos = str.pos(upper, na)
na_source_pos = str.pos(na, "S")
unicode_pos = str.pos("åβγ", "γ")
slice = str.substring(upper, mid, mid + 1)
tail = str.substring(upper, mid)
wide = str.substring(upper, 1, 99)
empty_slice = str.substring(upper, 1, 1)
tail_empty_slice = str.substring(upper, str.length(upper))
na_source_slice = str.substring(na, 0, 1)
na_begin = str.substring(upper, na, 1)
na_end = str.substring(upper, 1, na)
unicode_slice = str.substring("åβ", 1, 2)
trimmed = str.trim(" \tSMA\n")
non_ascii_trimmed = str.trim(" SMA ")
missing_trim = str.trim(na)
empty_trim = str.trim(" \t\n")
repeated = str.repeat("ab", 2, "-")
default_repeat = str.repeat("ab", 2)
empty_repeat = str.repeat("ab", 0)
missing_repeat = str.repeat("ab", na)
missing_repeat_source = str.repeat(na, 2)
missing_repeat_separator = str.repeat("ab", 2, na)
replace_first = str.replace("hello", "l", "1")
replace_second = str.replace("hello", "l", "1", 1)
replace_missing = str.replace("hello", "z", "1", 0)
replace_negative = str.replace("hello", "l", "1", -1)
replace_na_occurrence = str.replace("hello", "l", "1", na)
replace_out_of_range = str.replace("hello", "l", "1", 9)
replace_all = str.replace_all("hello", "l", "1")
replace_all_missing = str.replace_all("hello", "z", "1")
replace_boundary = str.replace("ab", "", ".", 1)
replace_all_boundaries = str.replace_all("ab", "", ".")
missing_replace = str.replace(na, "x", "y")
missing_replace_target = str.replace("hello", na, "y")
missing_replace_replacement = str.replace("hello", "x", na)
missing_replace_all_target = str.replace_all("hello", na, "y")
missing_replace_all_replacement = str.replace_all("hello", "x", na)
number = str.tonumber("1234.50")
signed_number = str.tonumber("-.5")
plus_number = str.tonumber("+12")
dot_number = str.tonumber(".5")
invalid_number = str.tonumber("$1,234.50")
empty_number = str.tonumber("")
whitespace_number = str.tonumber(" 1")
exponent_number = str.tonumber("1e3")
signed_exponent_number = str.tonumber("-.5e+2")
upper_exponent_number = str.tonumber("+12E-1")
double_decimal_number = str.tonumber("1.2.3")
bad_exponent_number = str.tonumber("1e")
nonfinite_exponent_number = str.tonumber("1e309")
missing_number = str.tonumber(na)
text_int = str.tostring(42)
text_float = str.tostring(1.25)
text_na_format = str.tostring(1.25, na)
text_round0 = str.tostring(1.25, "#")
text_round1 = str.tostring(1.25, "#.#")
text_zeros = str.tostring(1.25, "#.0000")
text_percent = str.tostring(12.3456, format.percent)
text_percent_unscaled = str.tostring(0.1234, format.percent)
text_percent_custom_scaled = str.tostring(0.1234, "#.##%")
text_price = str.tostring(1.234567891, format.price)
text_volume_small = str.tostring(518.3, format.volume)
text_volume_k = str.tostring(5183, format.volume)
text_volume_m = str.tostring(2500000, format.volume)
text_volume_b = str.tostring(2500000000, format.volume)
text_volume_t = str.tostring(1250000000000, format.volume)
text_volume_negative = str.tostring(-5183, format.volume)
text_volume_boundary = str.tostring(999.5, format.volume)
text_mintick_down = str.tostring(1.234, format.mintick)
text_mintick_up = str.tostring(1.235, format.mintick)
text_mintick_negative_tie = str.tostring(-1.235, format.mintick)
text_mintick_trailing_zeros = str.tostring(1, format.mintick)
text_bool = str.tostring(true)
text_bool_false = str.tostring(false)
text_string = str.tostring("ok")
text_na = str.tostring(na)
values = array.new_float(3)
array.set(values, 0, 1.2)
array.set(values, 1, 2.6)
text_array = str.tostring(values, "#")
formatted = str.format("A={0}, B={1}, A2={0}", text_int, text_float)
formatted_missing = str.format("Missing {2}", text_int)
formatted_number = str.format("Rounded {0,number,#.00}", 1.2)
formatted_percent_preset = str.format("Percent {0,number,percent}", 0.0345)
formatted_percent_grouped = str.format("Percent {0,number,percent}", 1234.56)
formatted_percent_custom = str.format("Percent {0,number,#.##%}", 0.0345)
formatted_integer = str.format("Integer {0,number,integer}", 1234.5)
formatted_currency = str.format("Currency {0,number,currency}", 1234.5)
formatted_array = str.format("Values {0}", values)
formatted_datetime = str.format("{0,date,yyyy-MM-dd}T{0,time,HH:mm:ssZ}", 1609459200000)
formatted_datetime_tokens = str.format("{0,date,D E w W} {0,time,HH:mm:ssZ}", 1609459200000)
formatted_datetime_clock_tokens = str.format("{0,time,H HH h hh:mm:ss.S SSS a}", 1609506245123)
formatted_quote = str.format("Literal '{0}' and apostrophe '' {0}", "X")
formatted_na = str.format(na, text_int)
formatted_na_arg = str.format("Missing {0}", na)
formatted_bool = str.format("Flag {0}", true)
match_prefix = str.match("NASDAQ:AAPL", "^(?:BATS|NASDAQ|NYSE|AMEX):")
match_suffix = str.match("NASDAQ:AAPL", "AAPL$")
match_missing = str.match("NASDAQ:AAPL", "^NYSE:")
match_ascii_digit = str.match("１1", "\\d")
match_unicode_digit = str.match("１1", "(?U)\\d")
match_ascii_non_digit = str.match("１1", "\\D")
match_unicode_non_digit = str.match("１A", "(?U)\\D")
match_ascii_word = str.match("β_A", "\\w+")
match_unicode_word = str.match("β_A", "(?U)\\w+")
match_ascii_non_word = str.match("βA", "\\W")
match_unicode_non_word = str.match("β!", "(?U)\\W")
match_ascii_space = str.match("  ", "\\s")
match_unicode_space = str.match("  ", "(?U)\\s")
match_ascii_non_space = str.match("  ", "\\S")
match_ascii_boundary = str.match("βA", "\\bA")
match_unicode_boundary = str.match("βA", "(?U)\\bA")
match_ascii_non_boundary = str.match("βA", "\\BA")
match_unicode_non_boundary = str.match("βA", "(?U)\\BA")
match_ascii_class = str.match("β1", "[\\w]+")
match_scoped_unicode_digit = str.match("１", "(?U:\\d)")
match_scoped_unicode = str.match("１１", "(?U:\\d)\\d")
match_toggled_unicode = str.match("１2", "(?U)\\d(?-U)\\d")
match_unicode_greedy = str.match("abc", "(?U).+")
match_horizontal_tab = str.match("\tA", "\\h")
match_horizontal_em_space = str.match(" A", "\\h")
match_non_horizontal = str.match(" A", "\\H")
match_horizontal_unicode_on = str.match(" ", "(?U)\\h")
match_horizontal_unicode_off = str.match(" ", "(?-U)\\h")
match_horizontal_class = str.match("A ", "[\\h]")
match_vertical_line_feed = str.match("\nA", "\\v")
match_vertical_carriage_return = str.match("\rA", "\\v")
match_vertical_next_line = str.match("A", "\\v")
match_vertical_line_separator = str.match(" A", "\\v")
match_vertical_paragraph_separator = str.match(" A", "\\v")
match_non_vertical = str.match("\nA", "\\V")
match_vertical_unicode_on = str.match("", "(?U)\\v")
match_vertical_unicode_off = str.match(" ", "(?-U)\\v")
match_vertical_class = str.match("A ", "[\\v]")
match_vertical_quoted = str.match("\\v", "\\Q\\v\\E")
match_line_break_crlf = str.match("\r\nA", "\\R")
match_line_break_line_feed = str.match("\nA", "\\R")
match_line_break_next_line = str.match("A", "\\R")
match_line_break_unicode_on = str.match(" ", "(?U)\\R")
match_line_break_unicode_off = str.match(" ", "(?-U)\\R")
match_line_break_quoted = str.match("\\R", "\\Q\\R\\E")
match_control_tab = str.match("\tA", "\\cI")
match_control_lowercase = str.match("!A", "\\ca")
match_control_supplementary = str.match("🙀A", "\\c😀")
match_control_consumption = str.match("\tB", "\\cIB")
match_control_class = str.match("A\t", "[\\cI]")
match_control_ascii_case = str.match("ℚQ", "(?i)\\c1")
match_control_unicode_case = str.match("Ϲϲ", "(?iU)\\cβ")
match_control_verbose = str.match("\t", "(?x)\\c # comment\n I")
match_control_quoted = str.match("\\e\\cA", "\\Q\\e\\cA\\E")
match_octal_two_digit_width = str.match("?7", "\\0777")
match_octal_three_digit_width = str.match("ÿx", "\\0377x")
match_octal_non_octal_tail = str.match("\n8", "\\0128")
match_octal_first_digit_limit = str.match(" 0", "\\0400")
match_octal_class = str.match("xa", "[\\0141]")
match_octal_ascii_case = str.match("ℚQ", "(?i)\\0161")
match_octal_ascii_non_ascii = str.match("Åå", "(?i)\\0345")
match_octal_unicode_case = str.match("Åå", "(?iU)\\0345")
match_octal_verbose = str.match("q", "(?x)\\0 1 # comment\n 6 1")
match_octal_quoted = str.match("\\0141", "\\Q\\0141\\E")
match_previous_anchor_start = str.match("abc", "\\Gabc")
match_previous_anchor_later = str.match("xabc", "\\Gabc")
match_previous_anchor_consumed = str.match("a", "a\\G")
match_previous_anchor_multiline = str.match("x\nabc", "(?m)\\Gabc")
match_previous_anchor_quoted = str.match("\\G", "\\Q\\G\\E")
match_leading_class_closer = str.match("x]a", "[]a]")
match_leading_class_closer_negated = str.match("]a", "[^]]")
match_leading_class_caret = str.match("^a", "[^^]")
match_leading_class_case = str.match("A", "(?i)[]a]")
match_class_tilde_pair = str.match("m~", "[a-z~~m]+")
match_class_tilde_range = str.match("`a~", "[a-~~]+")
match_class_tilde_escaped = str.match("A~~", "\\~[\\~]")
match_class_tilde_nested = str.match("c~x", "[x[~~]]+")
match_class_tilde_quoted = str.match("A~~", "[\\Q~~\\E]+")
match_literal_tilde_outside = str.match("A~~", "~~")
match_escaped_punctuation = str.match("A!%/_`~", "\\!\\%\\/\\_\\`\\~")
match_escaped_punctuation_class = str.match("A!%/_`~", "[\\!\\%\\/\\_\\`\\~]+")
match_escaped_meta = str.match("A$.[{(", "\\$\\.\\[\\{\\(")
match_escaped_hash_verbose = str.match("# ", "(?x)\\#\\ ")
match_escaped_punctuation_nested = str.match("A_~", "[x[\\_\\~]]+")
match_escaped_punctuation_case = str.match("A_A", "(?i)\\_[a]")
match_unicode_case_literal = str.match("KΒ", "(?iu)kβ")
match_unicode_case_scoped = str.match("ÅÅå", "(?iu:å)(?i:å)")
match_unicode_case_word = str.match("KA", "(?iu)\\w")
match_unicode_case_word_class = str.match("KA", "(?iu)[\\w]")
match_unicode_case_literal_class = str.match("K", "(?iu)[k]")
match_unicode_case_posix = str.match("KA", "(?iu)\\p{Lower}")
match_unicode_classes_without_case = str.match("KKΒ", "(?iU-u)[k]\\w\\p{Lower}")
match_unicode_modes_disabled = str.match("ÅéåA", "(?iU)(?-U)å\\w")
match_unicode_case_references = str.match("ÅÅÅEϹ", "(?iu)\\Qå\\E\\u00E5\\x{E5}\\0145\\cβ")
match_verbose_unicode_space = str.match("a b", "(?x)a b")
match_verbose_unicode_space_missing = str.match("ab", "(?x)a b")
match_verbose_escaped_unicode_space = str.match(" ", "(?x)\\ ")
match_verbose_cr_comment = str.match("ab", "(?x)a# note\rb")
match_verbose_next_line_comment = str.match("ab", "(?x)a# noteb")
match_verbose_line_separator_comment = str.match("a b", "(?x)a# note b")
match_verbose_paragraph_separator_comment = str.match("a b", "(?x)a# note b")
match_verbose_cr_class = str.match("a", "(?x)[a# note\r]")
match_verbose_next_line_class = str.match("", "(?x)[# note]")
match_verbose_scoped_comment = str.match("ab ", "(?x:a# note\rb)(?-x: )")
match_leading_class_verbose = str.match("]", "(?x)[ # note\n ]]")
match_leading_class_empty_quote = str.match("]", "[\\Q\\E]]")
match_leading_class_quoted = str.match("]", "[\\Q]\\E]")
match_quoted_meta = str.match("x[a-z]+(?U)# y", "\\Q[a-z]+(?U)# \\E")
match_quoted_escape = str.match("\\d123", "\\Q\\d\\E")
match_quoted_verbose = str.match("# [ ]", "(?x)\\Q# [ ]\\E")
match_quoted_class = str.match("]-", "[\\Q]-\\E]+")
match_quoted_unclosed = str.match("[b]+", "\\Q[b]+")
match_quoted_then_ascii = str.match("[a]123", "\\Q[a]\\E\\d+")
match_final_newline_dollar = str.match("tail\n", "tail$")
match_final_newline_Z = str.match("tail\n", "tail\\Z")
match_absolute_z_missing = str.match("tail\n", "tail\\z")
match_absolute_z = str.match("tail", "tail\\z")
match_explicit_final_newline = str.match("tail\n", "\\n$")
match_empty_final_newline_dollar = str.match("\n", "$")
match_empty_final_newline_Z = str.match("\n", "\\Z")
match_multiline_dollar = str.match("first\nsecond", "(?m)^second$")
match_scoped_multiline_reset = str.match("first\nsecond\n", "(?m:first$)\\n(?-m:second$)")
match_dotall_greedy_end = str.match("a\n", "(?s).*$")
match_dotall_lazy_end = str.match("a\n", "(?s).*?$")
match_default_dot_line_feed = str.match("\nA", ".")
match_default_dot_carriage_return = str.match("\rA", ".")
match_default_dot_next_line = str.match("A", ".")
match_default_dot_line_separator = str.match(" A", ".")
match_default_dot_paragraph_separator = str.match(" A", ".")
match_dotall_line_terminators = str.match("\r  A", "(?s).+")
match_global_dotall_reset = str.match("\rA", "(?s).(?-s).")
match_scoped_dotall_reset = str.match("\rA", "(?s:.)(?-s:.)")
match_literal_dots = str.match("...", "\\.[.]\\Q.\\E")
match_posix_lower_ascii = str.match("βa", "\\p{Lower}")
match_posix_lower_unicode = str.match("βa", "(?U)\\p{Lower}")
match_posix_not_lower_ascii = str.match("βa", "\\P{Lower}")
match_posix_not_lower_unicode = str.match("βA", "(?U)\\P{Lower}")
match_posix_xdigit_ascii = str.match("𝟙F", "[\\p{XDigit}]")
match_posix_xdigit_unicode = str.match("𝟙F", "(?U)[\\p{XDigit}]")
match_posix_scoped_reset = str.match("βa", "(?U:\\p{Lower})(?-U:\\p{Lower})")
match_posix_unicode_casefold_name = str.match("β", "(?U)\\p{aLpHa}")
match_unicode_category_unchanged = str.match("β", "\\p{L}")
match_posix_quoted = str.match("\\p{Lower}", "\\Q\\p{Lower}\\E")
match_java_lower = str.match("Aª", "\\p{javaLowerCase}")
match_java_upper = str.match("aK", "\\p{javaUpperCase}")
match_java_alphabetic = str.match("1ͅ", "\\p{javaAlphabetic}")
match_java_ideographic = str.match("A中", "\\p{javaIdeographic}")
match_java_title = str.match("ǆǅ", "\\p{javaTitleCase}")
match_java_digit = str.match("²１", "\\p{javaDigit}")
match_java_defined = str.match("A", "\\p{javaDefined}")
match_java_letter = str.match("Ⅰβ", "\\p{javaLetter}")
match_java_letter_or_digit = str.match("_１", "\\p{javaLetterOrDigit}")
match_java_complement = str.match("aA", "\\P{javaLowerCase}")
match_java_class = str.match("A１", "[\\p{javaLowerCase}\\p{javaDigit}]")
match_java_case = str.match("Β", "(?i)\\p{javaLowerCase}")
match_java_scopes = str.match("１１", "(?U:\\p{javaDigit})(?-U:\\p{javaDigit})")
match_java_quoted = str.match("\\p{javaLowerCase}", "\\Q\\p{javaLowerCase}\\E")
match_java_java_identifier_start = str.match("!$Ⅰ", "\\p{javaJavaIdentifierStart}+")
match_java_java_identifier_part = str.match("·$", "\\p{javaJavaIdentifierPart}")
match_java_unicode_identifier_start = str.match("$℘", "\\p{javaUnicodeIdentifierStart}")
match_java_unicode_identifier_part = str.match("$·", "\\p{javaUnicodeIdentifierPart}")
match_java_identifier_ignorable = str.match("A", "\\p{javaIdentifierIgnorable}")
match_java_space_char = str.match("A ", "\\p{javaSpaceChar}")
match_java_whitespace = str.match("  ", "\\p{javaWhitespace}")
match_java_iso_control = str.match("A\t", "\\p{javaISOControl}")
match_java_mirrored = str.match("A(", "\\p{javaMirrored}")
match_java_remaining_complement = str.match(" A", "\\P{javaWhitespace}")
match_java_remaining_class = str.match("!·", "[\\p{javaUnicodeIdentifierPart}]")
match_java_remaining_modes = str.match("℘℘", "(?U:\\p{javaUnicodeIdentifierStart})(?-U:\\p{javaUnicodeIdentifierStart})")
match_java_remaining_quoted = str.match("\\p{javaWhitespace}", "\\Q\\p{javaWhitespace}\\E")
match_block_in_basic_latin = str.match("βA", "\\p{InBasicLatin}")
match_block_named_basic_latin = str.match("βA", "\\p{block=basic_latin}")
match_block_latin1 = str.match("Aå", "\\p{Block=Latin-1Supplement}")
match_block_negated = str.match("Aå", "\\P{InBasicLatin}")
match_block_class = str.match("βA", "[\\p{InBasicLatin}]")
match_block_unicode_scopes = str.match("Aβ", "(?U:\\p{InBasicLatin})(?-U:\\p{Block=Greek})")
match_block_quoted = str.match("\\p{InBasicLatin}", "\\Q\\p{InBasicLatin}\\E")
match_script_property_unchanged = str.match("β", "\\p{IsGreek}")
match_category_assignment_unchanged = str.match("β", "\\p{gc=L}")
match_case_ascii_literal = str.match("KK", "(?i)k")
match_case_unicode_literal = str.match("KK", "(?iU)k")
match_case_ascii_non_ascii = str.match("Ββ", "(?i)β")
match_case_unicode_non_ascii = str.match("Ββ", "(?iU)β")
match_case_toggle = str.match("KKβ", "(?i)k(?U)k(?-U)β")
match_case_scoped = str.match("KKβ", "(?i:k)(?iU:k)(?i-U:β)")
match_case_quoted_ascii = str.match("KKβ+", "(?i)\\Qkβ+\\E")
match_case_quoted_unicode = str.match("KΒ+", "(?iU)\\Qkβ+\\E")
match_case_unicode_ref_ascii = str.match("KK", "(?i)\\u004B")
match_case_unicode_ref_unicode = str.match("KK", "(?iU)\\u004B")
match_case_ascii_class = str.match("KK", "(?i)[k]")
match_case_unicode_class = str.match("KK", "(?iU)[k]")
match_case_ascii_class_non_ascii = str.match("Ββ", "(?i)[β]")
match_case_unicode_class_non_ascii = str.match("Ββ", "(?iU)[β]")
match_case_ascii_negated_class = str.match("KK", "(?i)[^k]")
match_case_unicode_negated_class = str.match("KKβ", "(?iU)[^k]")
match_case_ascii_intersection = str.match("QA", "(?i)[a-z&&[^q]]")
match_case_unicode_range = str.match("ſA", "(?iU)[a-z]")
match_case_category_class = str.match("β", "(?i)[\\p{Lu}]")
match_case_ascii_word = str.match("KK", "(?i)\\w")
match_case_ascii_posix = str.match("KA", "(?i)\\p{Lower}")
match_case_block_class = str.match("KX", "(?iU)[x\\p{InBasicLatin}]")
match_case_quoted_class = str.match("KKβ", "(?i)[\\Qkβ\\E]")
match_case_unicode_ref_class = str.match("KKΒβ", "(?i)[\\u006B\\u03B2]")
match_case_scoped_class = str.match("KKβ", "(?i:[k])(?iU:[k])(?i-U:[β])")
match_hex_fixed_consumption = str.match("xk0", "\\x6B0")
match_hex_braced_consumption = str.match("xk0", "\\x{6B}0")
match_hex_leading_zeros = str.match("xk", "\\x{0000006B}")
match_hex_ascii_case = str.match("KK", "(?i)\\x6B")
match_hex_unicode_case = str.match("KK", "(?iU)\\x6B")
match_hex_ascii_non_ascii = str.match("Ββ", "(?i)\\x{3B2}")
match_hex_unicode_non_ascii = str.match("Ββ", "(?iU)\\x{3B2}")
match_hex_class = str.match("KKΒβ", "(?i)[\\x6B\\x{3B2}]")
match_hex_quoted = str.match("\\x6B", "\\Q\\x6B\\E")
match_hex_surrogate = str.match("A", "\\x{D800}")
match_anchor_capture_collision = str.match("tail\n", "(?<__pine_final_newline_0>tail)$")
match_unicode_escape = str.match("x—y", "\\u2014")
match_unicode_escape_class = str.match("xåy", "[\\u00E5]")
match_unicode_escape_fifth_digit = str.match("xa0y", "\\u00610")
match_unicode_escape_quoted = str.match("\\u2014—", "\\Q\\u2014\\E\\u2014")
missing_match_regex = str.match(na, ".+")
missing_match_pattern = str.match("NASDAQ:AAPL", na)
split_words = str.split("A,B,,C", ",")
split_missing_separator_literal = str.split("A,B", "|")
split_chars = str.split("xy", "")
split_unicode = str.split("åβ", "")
split_empty_source_separator = str.split("", ",")
split_empty_source_chars = str.split("", "")
split_missing = str.split(na, ",")
split_missing_separator = str.split("A,B", na)
formatted_time_default = str.format_time(1609459200000)
formatted_time_date = str.format_time(1609459200000, "yyyy-MM-dd")
formatted_time_text = str.format_time(1609459200000, "HH:mm:ss 'on' MMM dd, yyyy", "UTC")
formatted_time_alias = str.format_time(1609459200000, "HH:mm:ssZ", "UTC+00:00")
formatted_time_gmt_alias = str.format_time(1609459200000, "HH:mm:ssZ", "GMT-0")
formatted_time_fixed_east = str.format_time(1609459200000, "yyyy-MM-dd HH:mm:ssZ", "UTC+4")
formatted_time_fixed_west = str.format_time(1609459200000, "yyyy-MM-dd HH:mm:ssZ", "GMT-5")
formatted_time_numeric_offset = str.format_time(1609459200000, "HH:mm:ssZ", "+05:30")
formatted_time_day_of_year = str.format_time(1609459200000, "D DD DDD", "UTC")
formatted_time_day_of_year_later = str.format_time(1612235045000, "D DDD", "UTC")
formatted_time_weekday = str.format_time(1609459200000, "E EEEE", "UTC")
formatted_time_weekday_later = str.format_time(1612235045000, "EEE EEEE", "UTC")
formatted_time_week_of_year = str.format_time(1609459200000, "w ww", "UTC")
formatted_time_week_of_year_later = str.format_time(1612235045000, "w ww", "UTC")
formatted_time_week_of_month = str.format_time(1609459200000, "W WW", "UTC")
formatted_time_week_of_month_later = str.format_time(1612742400000, "W WW", "UTC")
formatted_time_clock_tokens = str.format_time(1609506245123, "H HH h hh:mm:ss.S SSS a", "UTC")
formatted_time_na_format = str.format_time(1609459200000, na)
formatted_time_na_timezone = str.format_time(1609459200000, "HH:mm:ssZ", na)
missing_format_time = str.format_time(na)
plot(upper == "SMA" and lower == "sma" and unicode_length == 2 and unicode_upper == "åβ" and unicode_lower == "ÅΒ" and empty_length == 0 ? length : 0)
plot(na(missing) and na(missing_upper) and na(missing_lower) ? 1 : 0)
plot(matched and not_matched and empty_match and empty_source_match ? 1 : 0)
plot(na(missing_match) and na(missing_pattern_match) and na(missing_pattern_start) and na(missing_pattern_end) ? 1 : 0)
plot(unicode_pos == 2 ? mid + empty_pos : 0)
plot(na(na_pos) ? 0 : na_pos == 0 and na(na_source_pos) ? 1 : 0)
plot(na(missing_pos) ? 1 : 0)
plot(slice == "M" and tail == "MA" and wide == "MA" and empty_slice == "" and tail_empty_slice == "" and na(na_source_slice) and na_begin == "S" and na_end == "MA" and unicode_slice == "β" ? 1 : 0)
plot(trimmed == upper and non_ascii_trimmed == " SMA " and missing_trim == "" and empty_trim == "" and repeated == "ab-ab" and default_repeat == "abab" and empty_repeat == "" ? 1 : 0)
plot(na(missing_repeat) and na(missing_repeat_source) and na(missing_repeat_separator) ? 1 : 0)
plot(replace_first == "he1lo" and replace_second == "hel1o" and replace_missing == "hello" and replace_negative == "hello" and replace_na_occurrence == "he1lo" and replace_out_of_range == "hello" ? 1 : 0)
plot(replace_all == "he11o" and replace_all_missing == "hello" and replace_boundary == "a.b" and replace_all_boundaries == ".a.b." ? 1 : 0)
plot(na(missing_replace) and na(missing_replace_target) and na(missing_replace_replacement) and na(missing_replace_all_target) and na(missing_replace_all_replacement) ? 1 : 0)
plot(number == 1234.5 and signed_number == -0.5 and plus_number == 12 and dot_number == 0.5 ? 1 : 0)
plot(exponent_number == 1000 and signed_exponent_number == -50 and upper_exponent_number == 1.2 ? 1 : 0)
plot(na(invalid_number) and na(empty_number) and na(whitespace_number) and na(double_decimal_number) and na(bad_exponent_number) and na(nonfinite_exponent_number) and na(missing_number) ? 1 : 0)
plot(text_int == "42" and text_float == "1.25" and text_na_format == "1.25" and text_round0 == "1" and text_round1 == "1.3" ? 1 : 0)
plot(text_zeros == "1.2500" and text_percent == "12.35%" and text_percent_unscaled == "0.12%" and text_percent_custom_scaled == "12.34%" ? 1 : 0)
plot(text_price == "1.23456789" and text_volume_small == "518" and text_volume_k == "5.183K" and text_volume_m == "2.5M" and text_volume_b == "2.5B" and text_volume_t == "1.25T" and text_volume_negative == "-5.183K" and text_volume_boundary == "1K" ? 1 : 0)
plot(text_bool == "true" and text_bool_false == "false" and text_string == "ok" and text_na == "NaN" ? 1 : 0)
plot(text_array == "[1, 3, NaN]" ? 1 : 0)
plot(formatted == "A=42, B=1.25, A2=42" and formatted_missing == "Missing {2}" ? 1 : 0)
plot(formatted_number == "Rounded 1.20" and formatted_percent_preset == "Percent 3%" and formatted_percent_grouped == "Percent 123,456%" and formatted_percent_custom == "Percent 3.45%" and formatted_integer == "Integer 1,235" and formatted_currency == "Currency $1,234.50" ? 1 : 0)
plot(formatted_array == "Values [1.2, 2.6, NaN]" and formatted_datetime == "2021-01-01T00:00:00+0000" and formatted_datetime_tokens == "1 Fri 53 1 00:00:00+0000" and formatted_datetime_clock_tokens == "13 13 1 01:04:05.123 123 PM" and formatted_quote == "Literal {0} and apostrophe ' X" and na(formatted_na) and formatted_na_arg == "Missing NaN" and formatted_bool == "Flag true" ? 1 : 0)
plot(match_prefix == "NASDAQ:" and match_suffix == "AAPL" and match_missing == "" ? 1 : 0)
plot(match_ascii_digit == "1" and match_unicode_digit == "１" and match_ascii_non_digit == "１" and match_unicode_non_digit == "A" ? 1 : 0)
plot(match_ascii_word == "_A" and match_unicode_word == "β_A" and match_ascii_non_word == "β" and match_unicode_non_word == "!" ? 1 : 0)
plot(match_ascii_space == " " and match_unicode_space == " " and match_ascii_non_space == " " ? 1 : 0)
plot(match_ascii_boundary == "A" and match_unicode_boundary == "" and match_ascii_non_boundary == "" and match_unicode_non_boundary == "A" and match_ascii_class == "1" ? 1 : 0)
plot(match_scoped_unicode_digit == "１" and match_scoped_unicode == "" and match_toggled_unicode == "１2" and match_unicode_greedy == "abc" ? 1 : 0)
plot(match_horizontal_tab == "\t" and match_horizontal_em_space == " " and match_non_horizontal == "A" and match_horizontal_unicode_on == " " and match_horizontal_unicode_off == " " and match_horizontal_class == " " ? 1 : 0)
plot(match_vertical_line_feed == "\n" and match_vertical_carriage_return == "\r" and match_vertical_next_line == "" and match_vertical_line_separator == " " and match_vertical_paragraph_separator == " " ? 1 : 0)
plot(match_non_vertical == "A" and match_vertical_unicode_on == "" and match_vertical_unicode_off == " " and match_vertical_class == " " and match_vertical_quoted == "\\v" ? 1 : 0)
plot(match_line_break_crlf == "\r\n" and match_line_break_line_feed == "\n" and match_line_break_next_line == "" ? 1 : 0)
plot(match_line_break_unicode_on == " " and match_line_break_unicode_off == " " and match_line_break_quoted == "\\R" ? 1 : 0)
plot(match_control_tab == "\t" and match_control_lowercase == "!" and match_control_supplementary == "🙀" and match_control_consumption == "\tB" and match_control_class == "\t" ? 1 : 0)
plot(match_control_ascii_case == "Q" and match_control_unicode_case == "Ϲ" and match_control_verbose == "\t" and match_control_quoted == "\\e\\cA" ? 1 : 0)
plot(match_octal_two_digit_width == "?7" and match_octal_three_digit_width == "ÿx" and match_octal_non_octal_tail == "\n8" and match_octal_first_digit_limit == " 0" and match_octal_class == "a" ? 1 : 0)
plot(match_octal_ascii_case == "Q" and match_octal_ascii_non_ascii == "å" and match_octal_unicode_case == "Å" and match_octal_verbose == "q" and match_octal_quoted == "\\0141" ? 1 : 0)
plot(match_previous_anchor_start == "abc" and match_previous_anchor_later == "" and match_previous_anchor_consumed == "" and match_previous_anchor_multiline == "" and match_previous_anchor_quoted == "\\G" ? 1 : 0)
plot(match_leading_class_closer == "]" and match_leading_class_closer_negated == "a" and match_leading_class_caret == "a" and match_leading_class_case == "A" ? 1 : 0)
plot(match_class_tilde_pair == "m~" and match_class_tilde_range == "a~" and match_class_tilde_escaped == "~~" and match_class_tilde_nested == "~x" and match_class_tilde_quoted == "~~" and match_literal_tilde_outside == "~~" ? 1 : 0)
plot(match_escaped_punctuation == "!%/_`~" and match_escaped_punctuation_class == "!%/_`~" and match_escaped_meta == "$.[{(" and match_escaped_hash_verbose == "# " and match_escaped_punctuation_nested == "_~" and match_escaped_punctuation_case == "_A" ? 1 : 0)
plot(match_unicode_case_literal == "KΒ" and match_unicode_case_scoped == "Åå" and match_unicode_case_literal_class == "K" ? 1 : 0)
plot(match_unicode_case_word == "A" and match_unicode_case_word_class == "A" and match_unicode_case_posix == "A" ? 1 : 0)
plot(match_unicode_classes_without_case == "KKΒ" and match_unicode_modes_disabled == "åA" and match_unicode_case_references == "ÅÅÅEϹ" ? 1 : 0)
plot(match_verbose_unicode_space == "a b" and match_verbose_unicode_space_missing == "" and match_verbose_escaped_unicode_space == " " ? 1 : 0)
plot(match_verbose_cr_comment == "ab" and match_verbose_next_line_comment == "ab" and match_verbose_line_separator_comment == "a b" and match_verbose_paragraph_separator_comment == "a b" ? 1 : 0)
plot(match_verbose_cr_class == "a" and match_verbose_next_line_class == "" and match_verbose_scoped_comment == "ab " ? 1 : 0)
plot(match_leading_class_verbose == "]" and match_leading_class_empty_quote == "]" and match_leading_class_quoted == "]" ? 1 : 0)
plot(match_quoted_meta == "[a-z]+(?U)# " and match_quoted_escape == "\\d" and match_quoted_verbose == "# [ ]" and match_quoted_class == "]-" and match_quoted_unclosed == "[b]+" and match_quoted_then_ascii == "[a]123" ? 1 : 0)
plot(match_final_newline_dollar == "tail" and match_final_newline_Z == "tail" and match_absolute_z_missing == "" and match_absolute_z == "tail" ? 1 : 0)
plot(match_explicit_final_newline == "\n" and match_empty_final_newline_dollar == "" and match_empty_final_newline_Z == "" ? 1 : 0)
plot(match_multiline_dollar == "second" and match_scoped_multiline_reset == "first\nsecond" ? 1 : 0)
plot(match_dotall_greedy_end == "a\n" and match_dotall_lazy_end == "a" and match_anchor_capture_collision == "tail" ? 1 : 0)
plot(match_default_dot_line_feed == "A" and match_default_dot_carriage_return == "A" and match_default_dot_next_line == "A" and match_default_dot_line_separator == "A" and match_default_dot_paragraph_separator == "A" ? 1 : 0)
plot(match_dotall_line_terminators == "\r  A" and match_global_dotall_reset == "\rA" and match_scoped_dotall_reset == "\rA" and match_literal_dots == "..." ? 1 : 0)
plot(match_posix_lower_ascii == "a" and match_posix_lower_unicode == "β" and match_posix_not_lower_ascii == "β" and match_posix_not_lower_unicode == "A" ? 1 : 0)
plot(match_posix_xdigit_ascii == "F" and match_posix_xdigit_unicode == "𝟙" and match_posix_scoped_reset == "βa" and match_posix_unicode_casefold_name == "β" and match_unicode_category_unchanged == "β" and match_posix_quoted == "\\p{Lower}" ? 1 : 0)
plot(match_java_lower == "ª" and match_java_upper == "K" and match_java_alphabetic == "ͅ" and match_java_ideographic == "中" and match_java_title == "ǅ" ? 1 : 0)
plot(match_java_digit == "１" and match_java_defined == "A" and match_java_letter == "β" and match_java_letter_or_digit == "１" and match_java_complement == "A" ? 1 : 0)
plot(match_java_class == "１" and match_java_case == "Β" and match_java_scopes == "１１" and match_java_quoted == "\\p{javaLowerCase}" ? 1 : 0)
plot(match_java_java_identifier_start == "$Ⅰ" and match_java_java_identifier_part == "$" and match_java_unicode_identifier_start == "℘" and match_java_unicode_identifier_part == "·" ? 1 : 0)
plot(match_java_identifier_ignorable == "" and str.length(match_java_space_char) == 1 and match_java_whitespace == " " and match_java_iso_control == "\t" and match_java_mirrored == "(" ? 1 : 0)
plot(str.length(match_java_remaining_complement) == 1 and match_java_remaining_class == "·" and match_java_remaining_modes == "℘℘" and match_java_remaining_quoted == "\\p{javaWhitespace}" ? 1 : 0)
plot(match_block_in_basic_latin == "A" and match_block_named_basic_latin == "A" and match_block_latin1 == "å" and match_block_negated == "å" and match_block_class == "A" ? 1 : 0)
plot(match_block_unicode_scopes == "Aβ" and match_block_quoted == "\\p{InBasicLatin}" and match_script_property_unchanged == "β" and match_category_assignment_unchanged == "β" ? 1 : 0)
plot(match_case_ascii_literal == "K" and match_case_unicode_literal == "K" and match_case_ascii_non_ascii == "β" and match_case_unicode_non_ascii == "Β" ? 1 : 0)
plot(match_case_toggle == "KKβ" and match_case_scoped == "KKβ" ? 1 : 0)
plot(match_case_quoted_ascii == "Kβ+" and match_case_quoted_unicode == "KΒ+" and match_case_unicode_ref_ascii == "K" and match_case_unicode_ref_unicode == "K" ? 1 : 0)
plot(match_case_ascii_class == "K" and match_case_unicode_class == "K" and match_case_ascii_class_non_ascii == "β" and match_case_unicode_class_non_ascii == "Β" ? 1 : 0)
plot(match_case_ascii_negated_class == "K" and match_case_unicode_negated_class == "β" and match_case_ascii_intersection == "A" and match_case_unicode_range == "ſ" ? 1 : 0)
plot(match_case_category_class == "β" and match_case_ascii_word == "K" and match_case_ascii_posix == "A" and match_case_block_class == "X" ? 1 : 0)
plot(match_case_quoted_class == "K" and match_case_unicode_ref_class == "K" and match_case_scoped_class == "KKβ" ? 1 : 0)
plot(match_hex_fixed_consumption == "k0" and match_hex_braced_consumption == "k0" and match_hex_leading_zeros == "k" ? 1 : 0)
plot(match_hex_ascii_case == "K" and match_hex_unicode_case == "K" and match_hex_ascii_non_ascii == "β" and match_hex_unicode_non_ascii == "Β" ? 1 : 0)
plot(match_hex_class == "K" and match_hex_quoted == "\\x6B" and match_hex_surrogate == "" ? 1 : 0)
plot(match_unicode_escape == "—" and match_unicode_escape_class == "å" and match_unicode_escape_fifth_digit == "a0" and match_unicode_escape_quoted == "\\u2014—" ? 1 : 0)
plot(na(missing_match_regex) and na(missing_match_pattern) ? 1 : 0)
plot(split_words.size() == 4 and split_words.get(0) == "A" and split_words.get(2) == "" and split_words.get(3) == "C" and split_missing_separator_literal.size() == 1 and split_missing_separator_literal.get(0) == "A,B" ? 1 : 0)
plot(split_chars.size() == 2 and split_chars.get(0) == "x" and split_chars.get(1) == "y" and split_unicode.size() == 2 and split_unicode.get(0) == "å" and split_unicode.get(1) == "β" and split_empty_source_separator.size() == 1 and split_empty_source_separator.get(0) == "" and split_empty_source_chars.size() == 0 and na(split_missing) and na(split_missing_separator) ? 1 : 0)
plot(formatted_time_default == "2021-01-01T00:00:00+0000" and formatted_time_date == "2021-01-01" and formatted_time_na_format == "2021-01-01T00:00:00+0000" ? 1 : 0)
plot(formatted_time_text == "00:00:00 on Jan 01, 2021" and missing_format_time == "1970-01-01T00:00:00+0000" ? 1 : 0)
plot(formatted_time_alias == "00:00:00+0000" and formatted_time_gmt_alias == "00:00:00+0000" and formatted_time_na_timezone == "00:00:00+0000" ? 1 : 0)
plot(formatted_time_fixed_east == "2021-01-01 04:00:00+0400" and formatted_time_fixed_west == "2020-12-31 19:00:00-0500" and formatted_time_numeric_offset == "05:30:00+0530" ? 1 : 0)
plot(formatted_time_day_of_year == "1 01 001" and formatted_time_day_of_year_later == "33 033" ? 1 : 0)
plot(formatted_time_weekday == "Fri Friday" and formatted_time_weekday_later == "Tue Tuesday" ? 1 : 0)
plot(formatted_time_week_of_year == "53 53" and formatted_time_week_of_year_later == "5 05" ? 1 : 0)
plot(formatted_time_week_of_month == "1 01" and formatted_time_week_of_month_later == "2 02" and formatted_time_clock_tokens == "13 13 1 01:04:05.123 123 PM" ? 1 : 0)
plot(text_mintick_down == "1.23" and text_mintick_up == "1.24" and text_mintick_negative_tie == "-1.23" and text_mintick_trailing_zeros == "1.00" ? 1 : 0)
string_values = array.from("head", "tail")
plot(str.tostring(string_values) == "[head, tail]" ? 1 : 0)
int_values = array.from(1, 2)
plot(str.tostring(int_values) == "[1, 2]" ? 1 : 0)
bool_values = array.from(true, false)
plot(str.tostring(bool_values) == "[true, false]" ? 1 : 0)
float_matrix = matrix.new<float>(2, 2)
matrix.set(float_matrix, 0, 0, 1.25)
matrix.set(float_matrix, 0, 1, 2.5)
matrix.set(float_matrix, 1, 1, -3.0)
int_matrix = matrix.new<int>(1, 2, 0)
matrix.set(int_matrix, 0, 1, -2)
bool_matrix = matrix.new<bool>(1, 2, false)
matrix.set(bool_matrix, 0, 1, true)
string_matrix = matrix.new<string>(2, 1, "")
matrix.set(string_matrix, 0, 0, "head")
matrix.set(string_matrix, 1, 0, "tail")
empty_rows_matrix = matrix.new<float>(0, 2)
empty_columns_matrix = matrix.new<float>(2, 0)
plot(str.tostring(float_matrix, "#.0") == "[[1.3, 2.5], [NaN, -3.0]]" and str.tostring(int_matrix) == "[[0, -2]]" and str.tostring(bool_matrix) == "[[false, true]]" and str.tostring(string_matrix) == "[[head], [tail]]" and str.tostring(empty_rows_matrix) == "[]" and str.tostring(empty_columns_matrix) == "[[], []]" ? 1 : 0)
mintick_values = array.from(1.234, 1.235, 1.0)
mintick_matrix = matrix.new<float>(1, 3)
matrix.set(mintick_matrix, 0, 0, 1.234)
matrix.set(mintick_matrix, 0, 1, 1.235)
matrix.set(mintick_matrix, 0, 2, 1.0)
plot(str.tostring(mintick_values, format.mintick) == "[1.23, 1.24, 1.00]" and str.tostring(mintick_matrix, format.mintick) == "[[1.23, 1.24, 1.00]]" ? 1 : 0)
volume_values = array.from(518.3, 5183.0, 2500000.0)
volume_matrix = matrix.new<float>(1, 3)
matrix.set(volume_matrix, 0, 0, 518.3)
matrix.set(volume_matrix, 0, 1, 5183.0)
matrix.set(volume_matrix, 0, 2, 2500000.0)
plot(str.tostring(volume_values, format.volume) == "[518, 5.183K, 2.5M]" and str.tostring(volume_matrix, format.volume) == "[[518, 5.183K, 2.5M]]" ? 1 : 0)
percent_values = array.from(12.3456, 0.1234)
percent_matrix = matrix.new<float>(1, 2)
matrix.set(percent_matrix, 0, 0, 12.3456)
matrix.set(percent_matrix, 0, 1, 0.1234)
plot(str.tostring(percent_values, format.percent) == "[12.35%, 0.12%]" and str.tostring(percent_matrix, format.percent) == "[[12.35%, 0.12%]]" ? 1 : 0)
plot(str.format("Words {0}", string_values) == "Words [head, tail]" ? 1 : 0)
plot(str.format("Ints {0}", int_values) == "Ints [1, 2]" ? 1 : 0)
plot(str.format("Flags {0}", bool_values) == "Flags [true, false]" ? 1 : 0)
"##,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[3.0, 3.0]);
    for plot in &result.plots[1..] {
        assert_values_close(&plot.values, &[1.0, 1.0]);
    }
}

#[test]
fn rejects_unbalanced_str_format_placeholders() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad format")
plot(str.length(str.format("Value {0", close)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected str.format placeholder error");

    assert!(
        error.message.contains("str.format has unmatched `{`"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_invalid_str_match_regex() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad match")
plot(str.length(str.match("abc", "(")))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected str.match regex error");

    assert!(
        error.message.contains("str.match invalid regex"),
        "{}",
        error.message
    );
}

#[test]
fn formats_iana_str_format_time_timezones() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("IANA formatted time")
plot(str.format_time(1609504496000, "yyyy-MM-dd HH:mm:ssZ", "America/New_York") == "2021-01-01 07:34:56-0500" ? 1 : 0)
plot(str.format_time(1625142896000, "yyyy-MM-dd HH:mm:ssZ", "America/New_York") == "2021-07-01 08:34:56-0400" ? 1 : 0)
plot(str.format_time(1609504496000, "yyyy-MM-dd HH:mm:ssZ", "Asia/Tokyo") == "2021-01-01 21:34:56+0900" ? 1 : 0)
plot(str.format_time(1609466400000, "yyyy-MM-dd E w HH:mm:ssZ", "America/New_York") == "2020-12-31 Thu 53 21:00:00-0500" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn formats_str_format_time_short_timezone_names() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("formatted timezone names")
plot(str.format_time(1609504496000, "z zz zzz zzzz", "America/New_York") == "EST EST EST zzzz" ? 1 : 0)
plot(str.format_time(1625142896000, "z", "America/New_York") == "EDT" ? 1 : 0)
plot(str.format_time(1609504496000, "z", "Asia/Tokyo") == "JST" ? 1 : 0)
plot(str.format_time(1609459200000, "z", "UTC") == "UTC" ? 1 : 0)
plot(str.format_time(1609459200000, "z", "UTC+4") == "GMT+04:00" ? 1 : 0)
plot(str.format_time(1609459200000, "z", "-05:30") == "GMT-05:30" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn formats_datetime_literal_apostrophes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("datetime literal apostrophes")
plot(str.format_time(1609506245123, "hh 'o''clock' a ''", "UTC") == "01 o'clock PM '" ? 1 : 0)
plot(str.format("{0,time,hh 'o''clock' a ''}", 1609506245123) == "01 o'clock PM '" ? 1 : 0)
plot(str.format_time(1609506245123, "'year=''yyyy''' yyyy", "UTC") == "year='yyyy' 2021" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn formats_datetime_millisecond_widths() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("datetime millisecond widths")
plot(str.format_time(1609506245000, "S SS SSS", "UTC") == "0 00 000" ? 1 : 0)
plot(str.format_time(1609506245005, "S SS SSS", "UTC") == "5 05 005" ? 1 : 0)
plot(str.format_time(1609506245123, "S SS SSS", "UTC") == "123 123 123" ? 1 : 0)
plot(str.format("{0,time,S SS SSS}", 1609506245005) == "5 05 005" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn formats_twelve_hour_clock_boundaries() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("twelve hour clock boundaries")
plot(str.format_time(1609459200000, "h hh a", "UTC") == "0 00 AM" ? 1 : 0)
plot(str.format_time(1609502400000, "h hh a", "UTC") == "0 00 PM" ? 1 : 0)
plot(str.format_time(1609506000000, "h hh a", "UTC") == "1 01 PM" ? 1 : 0)
plot(str.format("{0,time,h hh a}", 1609459200000) == "0 00 AM" ? 1 : 0)
plot(str.format("{0,time,h hh a}", 1609502400000) == "0 00 PM" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn formats_missing_timestamps_as_unix_epoch() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("missing timestamp epoch")
plot(str.format_time(na) == "1970-01-01T00:00:00+0000" ? 1 : 0)
plot(str.format_time(na, na, na) == "1970-01-01T00:00:00+0000" ? 1 : 0)
plot(str.format_time(na, "yyyy-MM-dd HH:mm:ssZ z", "UTC-5") == "1969-12-31 19:00:00-0500 GMT-05:00" ? 1 : 0)
plot(str.format_time(na, "yyyy-MM-dd HH:mm:ssZ z", "America/New_York") == "1969-12-31 19:00:00-0500 EST" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn formats_week_of_month_within_one_to_five() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("week of month range")
plot(str.format_time(1690761600000, "W WW", "UTC") == "5 05" ? 1 : 0)
plot(str.format_time(1690855200000, "yyyy-MM-dd W", "America/New_York") == "2023-07-31 5" ? 1 : 0)
plot(str.format_time(1690855200000, "yyyy-MM-dd W", "UTC") == "2023-08-01 1" ? 1 : 0)
plot(str.format("{0,date,W WW}", 1690761600000) == "5 05" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn rejects_invalid_str_format_time_timezone() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad time")
plot(str.length(str.format_time(1609459200000, "yyyy-MM-dd", "Mars/Olympus")))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected str.format_time timezone error");

    assert!(
        error
            .message
            .contains("str.format_time unsupported timezone `Mars/Olympus`"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_invalid_substring_range() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad substring")
plot(str.length(str.substring("SMA", 2, 1)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected substring range error");

    assert!(
        error
            .message
            .contains("str.substring end_pos 1 is less than begin_pos 2"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_invalid_string_repeat_counts() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad repeat")
plot(str.length(str.repeat("x", -1)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected negative repeat error");

    assert!(
        error
            .message
            .contains("str.repeat count cannot be negative: -1"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_oversized_string_repeat_result() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("huge repeat")
plot(str.length(str.repeat("x", 40961)))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected oversized repeat error");

    assert!(
        error
            .message
            .contains("str.repeat result cannot exceed 40960 characters"),
        "{}",
        error.message
    );
}
