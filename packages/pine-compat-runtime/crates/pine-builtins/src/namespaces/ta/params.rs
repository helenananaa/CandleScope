use pine_ir::PineType;

use crate::signature::{Accepts, BuiltinParam};

use super::super::types::*;

pub(super) const TA_SOURCE_LENGTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_SOURCE_OR_SIMPLE_LENGTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_SOURCE_DYNAMIC_LENGTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(super) const TA_SOURCE_DYNAMIC_LENGTH_OFFSET_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_PIVOT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "leftbars",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "rightbars",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(super) const TA_PIVOT_POINT_LEVELS_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "type",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "anchor",
        accepts: Accepts::BoolCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "developing",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

pub(super) const TA_ALMA_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "series",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "sigma",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "floor",
        accepts: Accepts::SimpleBoolCompatible,
        optional: true,
    },
];

pub(super) const TA_SOURCE_ONLY_SERIES_FLOAT_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "source",
    accepts: Accepts::SeriesNumeric,
    optional: false,
}];

pub(super) const TA_SOURCE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "source",
    accepts: Accepts::SeriesOrSimpleNumeric,
    optional: false,
}];

pub(super) const TA_VWAP_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "anchor",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "stdev_mult",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
];

pub(super) const TA_SOURCE_DYNAMIC_LENGTH_BIASED_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "biased",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

pub(super) const TA_SOURCE_OR_SIMPLE_DYNAMIC_LENGTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(super) const TA_SOURCE_DYNAMIC_LENGTH_PERCENTAGE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "percentage",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
];

pub(super) const TA_CONDITION_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "condition",
    accepts: Accepts::BoolCompatible,
    optional: false,
}];

pub(super) const TA_VALUEWHEN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "condition",
        accepts: Accepts::BoolCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "source",
        accepts: Accepts::ValueWhenSource,
        optional: false,
    },
    BuiltinParam {
        name: "occurrence",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(super) const TA_SOURCE_OPTIONAL_LENGTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumericOrBool,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

pub(super) const TA_TWO_SOURCE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source1",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "source2",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
];

pub(super) const TA_TWO_SOURCE_DYNAMIC_LENGTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source1",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "source2",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(super) const TA_STOCH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "high",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "low",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(super) const TA_DYNAMIC_LENGTH_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "length",
    accepts: Accepts::IntCompatible,
    optional: false,
}];

pub(super) const TA_LENGTH_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "length",
    accepts: Accepts::SimpleIntCompatible,
    optional: false,
}];

pub(super) const TA_AO_PARAMS: &[BuiltinParam] = &[];

pub(super) const TA_BOP_PARAMS: &[BuiltinParam] = &[];

pub(super) const TA_TR_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "handle_na",
    accepts: Accepts::ConstBool,
    optional: true,
}];

pub(super) const TA_MACD_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "fastlen",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "slowlen",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "siglen",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_TSI_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "short_length",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "long_length",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_BB_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "mult",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

pub(super) const TA_KC_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "mult",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "useTrueRange",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

pub(super) const TA_SUPERTREND_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "factor",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "atrPeriod",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_DMI_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "diLength",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "adxSmoothing",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

pub(super) const TA_SAR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "start",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "inc",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "max",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
];

pub(super) const TWO_SERIES_FLOATS: &[PineType] = &[SERIES_FLOAT, SERIES_FLOAT];

pub(super) const THREE_SERIES_FLOATS: &[PineType] = &[SERIES_FLOAT, SERIES_FLOAT, SERIES_FLOAT];
