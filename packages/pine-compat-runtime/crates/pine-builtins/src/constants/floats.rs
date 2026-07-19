struct NamedFloatConstant {
    name: &'static str,
    value: f64,
}

const NAMED_FLOAT_CONSTANTS: &[NamedFloatConstant] = &[
    NamedFloatConstant {
        name: "math.e",
        value: std::f64::consts::E,
    },
    NamedFloatConstant {
        name: "math.pi",
        value: std::f64::consts::PI,
    },
    NamedFloatConstant {
        name: "math.phi",
        value: 1.618_033_988_749_895,
    },
    NamedFloatConstant {
        name: "math.rphi",
        value: 0.618_033_988_749_894_8,
    },
    NamedFloatConstant {
        name: "syminfo.mintick",
        value: 0.01,
    },
    NamedFloatConstant {
        name: "syminfo.mincontract",
        value: 1.0,
    },
    NamedFloatConstant {
        name: "syminfo.pointvalue",
        value: 1.0,
    },
];

#[must_use]
pub fn named_float_constant(name: &str) -> Option<f64> {
    NAMED_FLOAT_CONSTANTS
        .iter()
        .find(|constant| constant.name == name)
        .map(|constant| constant.value)
}
