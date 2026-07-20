mod colors;
mod floats;
mod ints;
mod series;
mod strings;

pub use colors::{NAMED_COLORS, NamedColor, named_color};
pub use floats::named_float_constant;
pub use ints::named_int_constant;
pub use series::builtin_series_value_type;
pub use strings::named_string_constant;

#[doc(hidden)]
pub fn registered_value_names() -> impl Iterator<Item = &'static str> {
    strings::named_string_constant_names()
        .chain(ints::named_int_constant_names())
        .chain(floats::named_float_constant_names())
        .chain(series::builtin_series_value_names())
        .chain(NAMED_COLORS.iter().map(|color| color.name))
}
