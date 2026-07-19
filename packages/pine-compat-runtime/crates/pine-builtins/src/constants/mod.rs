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
