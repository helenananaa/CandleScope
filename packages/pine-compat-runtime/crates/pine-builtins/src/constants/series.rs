use pine_ir::{PineType, Qualifier, ValueKind};

use crate::namespaces::types::{
    SERIES_BOOL, SERIES_FLOAT, SERIES_INT, SIMPLE_BOOL, SIMPLE_BOX_ARRAY, SIMPLE_COLOR,
    SIMPLE_FLOAT, SIMPLE_INT, SIMPLE_LABEL_ARRAY, SIMPLE_LINE_ARRAY, SIMPLE_LINE_FILL_ARRAY,
    SIMPLE_POLYLINE_ARRAY, SIMPLE_STRING, SIMPLE_TABLE_ARRAY,
};

const BUILTIN_SERIES_VALUES: &[(&str, PineType)] = &[
    ("strategy.account_currency", SIMPLE_STRING),
    (
        "strategy.position_size",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.position_avg_price",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.position_entry_name",
        PineType::new(Qualifier::Series, ValueKind::String),
    ),
    (
        "strategy.initial_capital",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.openprofit",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.openprofit_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.netprofit",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.netprofit_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.grossprofit",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.grossprofit_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.grossloss",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.grossloss_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.buy_and_hold_return_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.avg_trade",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.avg_trade_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.avg_winning_trade",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.avg_winning_trade_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.avg_losing_trade",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.avg_losing_trade_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_runup",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_runup_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_drawdown",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_drawdown_percent",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_contracts_held_all",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_contracts_held_long",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.max_contracts_held_short",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.equity",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.closedtrades",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "strategy.closedtrades.first_index",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "strategy.wintrades",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "strategy.losstrades",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "strategy.eventrades",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "strategy.opentrades",
        PineType::new(Qualifier::Series, ValueKind::Int),
    ),
    (
        "strategy.opentrades.capital_held",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "strategy.margin_liquidation_price",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "barstate.isfirst",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    (
        "barstate.islast",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    (
        "barstate.islastconfirmedhistory",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    (
        "barstate.isnew",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    (
        "barstate.isconfirmed",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    (
        "barstate.ishistory",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    (
        "barstate.isrealtime",
        PineType::new(Qualifier::Series, ValueKind::Bool),
    ),
    ("session.ismarket", SERIES_BOOL),
    ("session.ispremarket", SERIES_BOOL),
    ("session.ispostmarket", SERIES_BOOL),
    ("session.isfirstbar", SERIES_BOOL),
    ("session.islastbar", SERIES_BOOL),
    ("session.isfirstbar_regular", SERIES_BOOL),
    ("session.islastbar_regular", SERIES_BOOL),
    ("hl2", SERIES_FLOAT),
    ("hlc3", SERIES_FLOAT),
    ("hlcc4", SERIES_FLOAT),
    ("ohlc4", SERIES_FLOAT),
    ("bar_index", SERIES_INT),
    ("last_bar_index", SERIES_INT),
    ("last_bar_time", SERIES_INT),
    ("timeframe.period", SIMPLE_STRING),
    ("timeframe.main_period", SIMPLE_STRING),
    ("timeframe.isticks", SIMPLE_BOOL),
    ("timeframe.isseconds", SIMPLE_BOOL),
    ("timeframe.isminutes", SIMPLE_BOOL),
    ("timeframe.isintraday", SIMPLE_BOOL),
    ("timeframe.isdaily", SIMPLE_BOOL),
    ("timeframe.isweekly", SIMPLE_BOOL),
    ("timeframe.ismonthly", SIMPLE_BOOL),
    ("timeframe.isdwm", SIMPLE_BOOL),
    ("timeframe.multiplier", SIMPLE_INT),
    ("chart.left_visible_bar_time", SIMPLE_INT),
    ("chart.right_visible_bar_time", SIMPLE_INT),
    ("chart.bg_color", SIMPLE_COLOR),
    ("chart.fg_color", SIMPLE_COLOR),
    ("chart.is_standard", SIMPLE_BOOL),
    ("chart.is_heikinashi", SIMPLE_BOOL),
    ("chart.is_kagi", SIMPLE_BOOL),
    ("chart.is_linebreak", SIMPLE_BOOL),
    ("chart.is_pnf", SIMPLE_BOOL),
    ("chart.is_range", SIMPLE_BOOL),
    ("chart.is_renko", SIMPLE_BOOL),
    ("syminfo.tickerid", SIMPLE_STRING),
    ("syminfo.main_tickerid", SIMPLE_STRING),
    ("syminfo.ticker", SIMPLE_STRING),
    ("syminfo.prefix", SIMPLE_STRING),
    ("syminfo.description", SIMPLE_STRING),
    ("syminfo.sector", SIMPLE_STRING),
    ("syminfo.industry", SIMPLE_STRING),
    ("syminfo.country", SIMPLE_STRING),
    ("syminfo.type", SIMPLE_STRING),
    ("syminfo.currency", SIMPLE_STRING),
    ("syminfo.basecurrency", SIMPLE_STRING),
    ("syminfo.session", SIMPLE_STRING),
    ("syminfo.timezone", SIMPLE_STRING),
    ("syminfo.root", SIMPLE_STRING),
    ("syminfo.volumetype", SIMPLE_STRING),
    ("syminfo.mintick", SIMPLE_FLOAT),
    ("syminfo.mincontract", SIMPLE_FLOAT),
    ("syminfo.pointvalue", SIMPLE_FLOAT),
    ("syminfo.minmove", SIMPLE_INT),
    ("syminfo.pricescale", SIMPLE_INT),
    ("label.all", SIMPLE_LABEL_ARRAY),
    ("line.all", SIMPLE_LINE_ARRAY),
    ("linefill.all", SIMPLE_LINE_FILL_ARRAY),
    ("polyline.all", SIMPLE_POLYLINE_ARRAY),
    ("box.all", SIMPLE_BOX_ARRAY),
    ("table.all", SIMPLE_TABLE_ARRAY),
    (
        "ta.accdist",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    ("ta.iii", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ta.nvi", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ta.obv", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ta.pvi", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ta.pvt", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ta.tr", PineType::new(Qualifier::Series, ValueKind::Float)),
    ("ta.wad", PineType::new(Qualifier::Series, ValueKind::Float)),
    (
        "ta.vwap",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
    (
        "ta.wvad",
        PineType::new(Qualifier::Series, ValueKind::Float),
    ),
];

#[must_use]
pub fn builtin_series_value_type(name: &str) -> Option<PineType> {
    BUILTIN_SERIES_VALUES
        .iter()
        .find(|(value_name, _)| *value_name == name)
        .map(|(_, pine_type)| *pine_type)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registers_strategy_trade_count_series_values() {
        for name in [
            "strategy.closedtrades",
            "strategy.closedtrades.first_index",
            "strategy.wintrades",
            "strategy.losstrades",
            "strategy.eventrades",
            "strategy.opentrades",
        ] {
            assert_eq!(
                builtin_series_value_type(name),
                Some(PineType::new(Qualifier::Series, ValueKind::Int))
            );
        }
    }

    #[test]
    fn registers_strategy_position_entry_name_series_value() {
        assert_eq!(
            builtin_series_value_type("strategy.position_entry_name"),
            Some(PineType::new(Qualifier::Series, ValueKind::String))
        );
    }

    #[test]
    fn registers_strategy_account_currency_simple_string_value() {
        assert_eq!(
            builtin_series_value_type("strategy.account_currency"),
            Some(SIMPLE_STRING)
        );
    }

    #[test]
    fn registers_chart_type_metadata_values() {
        for name in [
            "chart.is_standard",
            "chart.is_heikinashi",
            "chart.is_kagi",
            "chart.is_linebreak",
            "chart.is_pnf",
            "chart.is_range",
            "chart.is_renko",
        ] {
            assert_eq!(builtin_series_value_type(name), Some(SIMPLE_BOOL));
        }
    }

    #[test]
    fn registers_chart_appearance_metadata_values() {
        for name in ["chart.bg_color", "chart.fg_color"] {
            assert_eq!(builtin_series_value_type(name), Some(SIMPLE_COLOR));
        }
    }

    #[test]
    fn registers_chart_visible_bar_time_values() {
        for name in [
            "chart.left_visible_bar_time",
            "chart.right_visible_bar_time",
        ] {
            assert_eq!(builtin_series_value_type(name), Some(SIMPLE_INT));
        }
    }

    #[test]
    fn registers_syminfo_string_metadata_values() {
        for name in [
            "syminfo.tickerid",
            "syminfo.main_tickerid",
            "syminfo.ticker",
            "syminfo.prefix",
            "syminfo.description",
            "syminfo.sector",
            "syminfo.industry",
            "syminfo.country",
            "syminfo.type",
            "syminfo.currency",
            "syminfo.basecurrency",
            "syminfo.session",
            "syminfo.timezone",
            "syminfo.root",
            "syminfo.volumetype",
        ] {
            assert_eq!(builtin_series_value_type(name), Some(SIMPLE_STRING));
        }
    }

    #[test]
    fn registers_syminfo_numeric_metadata_values() {
        for name in [
            "syminfo.mintick",
            "syminfo.mincontract",
            "syminfo.pointvalue",
        ] {
            assert_eq!(builtin_series_value_type(name), Some(SIMPLE_FLOAT));
        }
        for name in ["syminfo.minmove", "syminfo.pricescale"] {
            assert_eq!(builtin_series_value_type(name), Some(SIMPLE_INT));
        }
    }

    #[test]
    fn registers_session_bar_boundary_values() {
        for name in [
            "session.isfirstbar",
            "session.islastbar",
            "session.isfirstbar_regular",
            "session.islastbar_regular",
        ] {
            assert_eq!(builtin_series_value_type(name), Some(SERIES_BOOL));
        }
    }

    #[test]
    fn registers_barstate_values() {
        for name in [
            "barstate.isfirst",
            "barstate.islast",
            "barstate.islastconfirmedhistory",
            "barstate.isnew",
            "barstate.isconfirmed",
            "barstate.ishistory",
            "barstate.isrealtime",
        ] {
            assert_eq!(builtin_series_value_type(name), Some(SERIES_BOOL));
        }
    }

    #[test]
    fn registers_last_bar_metadata_values() {
        for name in ["last_bar_index", "last_bar_time"] {
            assert_eq!(builtin_series_value_type(name), Some(SERIES_INT));
        }
    }

    #[test]
    fn registers_derived_price_and_bar_index_values() {
        for name in ["hl2", "hlc3", "hlcc4", "ohlc4"] {
            assert_eq!(builtin_series_value_type(name), Some(SERIES_FLOAT));
        }
        assert_eq!(builtin_series_value_type("bar_index"), Some(SERIES_INT));
    }

    #[test]
    fn registers_drawing_all_array_values() {
        assert_eq!(
            builtin_series_value_type("label.all"),
            Some(SIMPLE_LABEL_ARRAY)
        );
        assert_eq!(
            builtin_series_value_type("line.all"),
            Some(SIMPLE_LINE_ARRAY)
        );
        assert_eq!(
            builtin_series_value_type("linefill.all"),
            Some(SIMPLE_LINE_FILL_ARRAY)
        );
        assert_eq!(
            builtin_series_value_type("polyline.all"),
            Some(SIMPLE_POLYLINE_ARRAY)
        );
        assert_eq!(builtin_series_value_type("box.all"), Some(SIMPLE_BOX_ARRAY));
        assert_eq!(
            builtin_series_value_type("table.all"),
            Some(SIMPLE_TABLE_ARRAY)
        );
    }

    #[test]
    fn registers_strategy_profit_series_values() {
        for name in [
            "strategy.initial_capital",
            "strategy.openprofit",
            "strategy.openprofit_percent",
            "strategy.netprofit",
            "strategy.netprofit_percent",
            "strategy.grossprofit",
            "strategy.grossprofit_percent",
            "strategy.grossloss",
            "strategy.grossloss_percent",
            "strategy.buy_and_hold_return_percent",
            "strategy.avg_trade",
            "strategy.avg_trade_percent",
            "strategy.avg_winning_trade",
            "strategy.avg_winning_trade_percent",
            "strategy.avg_losing_trade",
            "strategy.avg_losing_trade_percent",
            "strategy.max_runup",
            "strategy.max_runup_percent",
            "strategy.max_drawdown",
            "strategy.max_drawdown_percent",
            "strategy.max_contracts_held_all",
            "strategy.max_contracts_held_long",
            "strategy.max_contracts_held_short",
            "strategy.opentrades.capital_held",
            "strategy.margin_liquidation_price",
            "strategy.equity",
        ] {
            assert_eq!(
                builtin_series_value_type(name),
                Some(PineType::new(Qualifier::Series, ValueKind::Float))
            );
        }
    }
}
