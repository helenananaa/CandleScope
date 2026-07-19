use std::collections::HashMap;

use pine_ir::{PersistenceKind, PineType, Qualifier, SeriesId, SymbolId, ValueKind};

use crate::resolver::SymbolInfo;

pub(crate) const INITIAL_SYMBOLS: &[(&str, PineType)] = &[
    ("open", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("high", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("low", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("close", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("volume", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("time", PineType::new(Qualifier::Series, ValueKind::Int)),
    (
        "time_close",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "time_tradingday",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "last_bar_index",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "last_bar_time",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    ("year", PineType::new(Qualifier::Series, ValueKind::Int)),
    ("month", PineType::new(Qualifier::Series, ValueKind::Int)),
    (
        "weekofyear",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "dayofmonth",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "dayofweek",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    ("hour", PineType::new(Qualifier::Series, ValueKind::Int)),
    ("minute", PineType::new(Qualifier::Series, ValueKind::Int)),
    ("second", PineType::new(Qualifier::Series, ValueKind::Int)),
    ("hl2", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("hlc3", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("hlcc4", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ohlc4", PineType::new(Qualifier::Series, ValueKind::Float)),
    (
        "bar_index",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    ("na", PineType::new(Qualifier::Const, ValueKind::Na)),
];
pub(crate) fn initial_symbols() -> HashMap<String, SymbolInfo> {
    INITIAL_SYMBOLS
        .iter()
        .enumerate()
        .map(|(index, (name, pine_type))| {
            (
                (*name).to_owned(),
                SymbolInfo {
                    id: SymbolId(index as u32),
                    pine_type: *pine_type,
                    series_id: if pine_type.qualifier == Qualifier::Series {
                        Some(SeriesId(index as u32))
                    } else {
                        None
                    },
                    persistence: PersistenceKind::None,
                    var_slot_id: None,
                },
            )
        })
        .collect()
}
pub(crate) fn initial_symbol_order() -> Vec<String> {
    INITIAL_SYMBOLS
        .iter()
        .map(|(name, _)| (*name).to_owned())
        .collect()
}
pub(crate) fn initial_symbol_count() -> u32 {
    INITIAL_SYMBOLS.len() as u32
}
pub(crate) fn initial_series_count() -> u32 {
    INITIAL_SYMBOLS
        .iter()
        .filter(|(_, pine_type)| pine_type.qualifier == Qualifier::Series)
        .count() as u32
}
