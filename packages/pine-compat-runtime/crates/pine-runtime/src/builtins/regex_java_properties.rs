pub(crate) fn pine_java_property(name: &str, negated: bool) -> Option<&'static str> {
    let (positive, negative) = match name {
        "javaLowerCase" => (r"\p{Lowercase}", r"\P{Lowercase}"),
        "javaUpperCase" => (r"\p{Uppercase}", r"\P{Uppercase}"),
        "javaAlphabetic" => (r"\p{Alphabetic}", r"\P{Alphabetic}"),
        "javaIdeographic" => (r"\p{Ideographic}", r"\P{Ideographic}"),
        "javaTitleCase" => (r"\p{Lt}", r"\P{Lt}"),
        "javaDigit" => (r"\p{Nd}", r"\P{Nd}"),
        "javaDefined" => (r"\P{Cn}", r"\p{Cn}"),
        "javaLetter" => (r"\p{L}", r"\P{L}"),
        "javaLetterOrDigit" => (r"[\p{L}\p{Nd}]", r"[^\p{L}\p{Nd}]"),
        "javaJavaIdentifierStart" => (r"[\p{L}\p{Nl}\p{Sc}\p{Pc}]", r"[^\p{L}\p{Nl}\p{Sc}\p{Pc}]"),
        "javaJavaIdentifierPart" => (
            r"[\p{L}\p{Nl}\p{Sc}\p{Pc}\p{Nd}\p{Mn}\p{Mc}\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]",
            r"[^\p{L}\p{Nl}\p{Sc}\p{Pc}\p{Nd}\p{Mn}\p{Mc}\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]",
        ),
        "javaUnicodeIdentifierStart" => (r"\p{ID_Start}", r"\P{ID_Start}"),
        "javaUnicodeIdentifierPart" => (
            r"[\p{ID_Continue}\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]",
            r"[^\p{ID_Continue}\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]",
        ),
        "javaIdentifierIgnorable" => (
            r"[\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]",
            r"[^\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]",
        ),
        "javaSpaceChar" => (r"\p{Z}", r"\P{Z}"),
        "javaWhitespace" => (
            r"[[\p{Z}\x{9}-\x{D}\x{1C}-\x{1F}]--[\x{A0}\x{2007}\x{202F}]]",
            r"[[^\p{Z}\x{9}-\x{D}\x{1C}-\x{1F}]\x{A0}\x{2007}\x{202F}]",
        ),
        "javaISOControl" => (
            r"[\x{0}-\x{1F}\x{7F}-\x{9F}]",
            r"[^\x{0}-\x{1F}\x{7F}-\x{9F}]",
        ),
        "javaMirrored" => (r"\p{Bidi_Mirrored}", r"\P{Bidi_Mirrored}"),
        _ => return None,
    };
    Some(if negated { negative } else { positive })
}

#[cfg(test)]
mod tests {
    use super::pine_java_property;

    #[test]
    fn maps_basic_java_character_properties_and_complements() {
        assert_eq!(
            pine_java_property("javaLowerCase", false),
            Some(r"\p{Lowercase}")
        );
        assert_eq!(pine_java_property("javaDefined", true), Some(r"\p{Cn}"));
        assert_eq!(
            pine_java_property("javaLetterOrDigit", false),
            Some(r"[\p{L}\p{Nd}]")
        );
        assert_eq!(
            pine_java_property("javaUnicodeIdentifierStart", true),
            Some(r"\P{ID_Start}")
        );
        assert_eq!(
            pine_java_property("javaIdentifierIgnorable", false),
            Some(r"[\p{Cf}\x{0}-\x{8}\x{E}-\x{1B}\x{7F}-\x{9F}]")
        );
        assert_eq!(
            pine_java_property("javaWhitespace", true),
            Some(r"[[^\p{Z}\x{9}-\x{D}\x{1C}-\x{1F}]\x{A0}\x{2007}\x{202F}]")
        );
        assert_eq!(
            pine_java_property("javaMirrored", false),
            Some(r"\p{Bidi_Mirrored}")
        );
        assert_eq!(pine_java_property("javalowercase", false), None);
    }
}
