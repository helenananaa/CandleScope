#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BuiltinSeriesHistoryRequirement {
    pub symbol: &'static str,
    pub offset: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BuiltinHistoryRequirement {
    BuiltinSeries(&'static [BuiltinSeriesHistoryRequirement]),
    SourceOffset {
        source_arg: usize,
        offset: u32,
    },
    OptionalLengthOffset {
        source_arg: usize,
        length_arg: usize,
        default_offset: u32,
    },
    RequiredLengthOffset {
        source_arg: usize,
        length_arg: usize,
    },
    WindowLengthOffset {
        source_arg: usize,
        length_arg: usize,
        default_source: Option<&'static str>,
    },
    Cross {
        args: usize,
        offset: u32,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BuiltinHistoryMetadata {
    pub name: &'static str,
    pub requirement: BuiltinHistoryRequirement,
}

const CLOSE_1: &[BuiltinSeriesHistoryRequirement] = &[BuiltinSeriesHistoryRequirement {
    symbol: "close",
    offset: 1,
}];

const DMI_HISTORY: &[BuiltinSeriesHistoryRequirement] = &[
    BuiltinSeriesHistoryRequirement {
        symbol: "high",
        offset: 1,
    },
    BuiltinSeriesHistoryRequirement {
        symbol: "low",
        offset: 1,
    },
    BuiltinSeriesHistoryRequirement {
        symbol: "close",
        offset: 1,
    },
];

const SAR_HISTORY: &[BuiltinSeriesHistoryRequirement] = &[
    BuiltinSeriesHistoryRequirement {
        symbol: "high",
        offset: 2,
    },
    BuiltinSeriesHistoryRequirement {
        symbol: "low",
        offset: 2,
    },
    BuiltinSeriesHistoryRequirement {
        symbol: "close",
        offset: 1,
    },
];

pub const BUILTIN_HISTORY_METADATA: &[BuiltinHistoryMetadata] = &[
    BuiltinHistoryMetadata {
        name: "ta.tr",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(CLOSE_1),
    },
    BuiltinHistoryMetadata {
        name: "ta.atr",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(CLOSE_1),
    },
    BuiltinHistoryMetadata {
        name: "ta.supertrend",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(CLOSE_1),
    },
    BuiltinHistoryMetadata {
        name: "ta.kc",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(CLOSE_1),
    },
    BuiltinHistoryMetadata {
        name: "ta.kcw",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(CLOSE_1),
    },
    BuiltinHistoryMetadata {
        name: "ta.dmi",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(DMI_HISTORY),
    },
    BuiltinHistoryMetadata {
        name: "ta.sar",
        requirement: BuiltinHistoryRequirement::BuiltinSeries(SAR_HISTORY),
    },
    BuiltinHistoryMetadata {
        name: "ta.mfi",
        requirement: BuiltinHistoryRequirement::SourceOffset {
            source_arg: 0,
            offset: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.tsi",
        requirement: BuiltinHistoryRequirement::SourceOffset {
            source_arg: 0,
            offset: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.cmo",
        requirement: BuiltinHistoryRequirement::SourceOffset {
            source_arg: 0,
            offset: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.change",
        requirement: BuiltinHistoryRequirement::OptionalLengthOffset {
            source_arg: 0,
            length_arg: 1,
            default_offset: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.mom",
        requirement: BuiltinHistoryRequirement::RequiredLengthOffset {
            source_arg: 0,
            length_arg: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.roc",
        requirement: BuiltinHistoryRequirement::RequiredLengthOffset {
            source_arg: 0,
            length_arg: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.highest",
        requirement: BuiltinHistoryRequirement::WindowLengthOffset {
            source_arg: 0,
            length_arg: 1,
            default_source: Some("high"),
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.lowest",
        requirement: BuiltinHistoryRequirement::WindowLengthOffset {
            source_arg: 0,
            length_arg: 1,
            default_source: Some("low"),
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.highestbars",
        requirement: BuiltinHistoryRequirement::WindowLengthOffset {
            source_arg: 0,
            length_arg: 1,
            default_source: Some("high"),
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.lowestbars",
        requirement: BuiltinHistoryRequirement::WindowLengthOffset {
            source_arg: 0,
            length_arg: 1,
            default_source: Some("low"),
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.rising",
        requirement: BuiltinHistoryRequirement::RequiredLengthOffset {
            source_arg: 0,
            length_arg: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.falling",
        requirement: BuiltinHistoryRequirement::RequiredLengthOffset {
            source_arg: 0,
            length_arg: 1,
        },
    },
    BuiltinHistoryMetadata {
        name: "ta.cross",
        requirement: BuiltinHistoryRequirement::Cross { args: 2, offset: 1 },
    },
    BuiltinHistoryMetadata {
        name: "ta.crossover",
        requirement: BuiltinHistoryRequirement::Cross { args: 2, offset: 1 },
    },
    BuiltinHistoryMetadata {
        name: "ta.crossunder",
        requirement: BuiltinHistoryRequirement::Cross { args: 2, offset: 1 },
    },
];

#[must_use]
pub fn builtin_history_requirement(name: &str) -> Option<BuiltinHistoryRequirement> {
    BUILTIN_HISTORY_METADATA
        .iter()
        .find(|metadata| metadata.name == name)
        .map(|metadata| metadata.requirement)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::get_phase_1_builtin;

    #[test]
    fn history_metadata_names_are_registered_builtins() {
        for metadata in BUILTIN_HISTORY_METADATA {
            assert!(
                get_phase_1_builtin(metadata.name).is_some(),
                "{} should have a registered builtin signature",
                metadata.name
            );
        }
    }
}
