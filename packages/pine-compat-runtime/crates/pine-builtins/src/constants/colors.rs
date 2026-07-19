pub struct NamedColor {
    pub name: &'static str,
    pub rgb: u32,
}

pub const NAMED_COLORS: &[NamedColor] = &[
    NamedColor {
        name: "color.black",
        rgb: 0x363A45,
    },
    NamedColor {
        name: "color.silver",
        rgb: 0xB2B5BE,
    },
    NamedColor {
        name: "color.gray",
        rgb: 0x787B86,
    },
    NamedColor {
        name: "color.white",
        rgb: 0xFFFFFF,
    },
    NamedColor {
        name: "color.maroon",
        rgb: 0x880E4F,
    },
    NamedColor {
        name: "color.red",
        rgb: 0xF23645,
    },
    NamedColor {
        name: "color.purple",
        rgb: 0x9C27B0,
    },
    NamedColor {
        name: "color.fuchsia",
        rgb: 0xE040FB,
    },
    NamedColor {
        name: "color.green",
        rgb: 0x4CAF50,
    },
    NamedColor {
        name: "color.lime",
        rgb: 0x00E676,
    },
    NamedColor {
        name: "color.olive",
        rgb: 0x808000,
    },
    NamedColor {
        name: "color.yellow",
        rgb: 0xFDD835,
    },
    NamedColor {
        name: "color.navy",
        rgb: 0x311B92,
    },
    NamedColor {
        name: "color.blue",
        rgb: 0x2196F3,
    },
    NamedColor {
        name: "color.teal",
        rgb: 0x089981,
    },
    NamedColor {
        name: "color.aqua",
        rgb: 0x00BCD4,
    },
    NamedColor {
        name: "color.orange",
        rgb: 0xFF9800,
    },
];

#[must_use]
pub fn named_color(name: &str) -> Option<u32> {
    NAMED_COLORS
        .iter()
        .find(|color| color.name == name)
        .map(|color| color.rgb)
}
