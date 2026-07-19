use crate::namespaces::types::VOID;
use crate::namespaces::{
    alerts, arrays, chart, colors, core, drawings, maps, math, matrices, outputs, requests,
    strategy, strings, syminfo, ta, ticker, time,
};
use crate::signature::{BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

const EMPTY_PARAMS: &[BuiltinParam] = &[];
const EMPTY_SIGNATURE: BuiltinSignature = BuiltinSignature {
    name: "",
    phase: BuiltinPhase::Later,
    params: EMPTY_PARAMS,
    returns: ReturnSpec::Fixed(VOID),
    variadic: false,
};

const BUILTIN_COUNT: usize = core::SCRIPT_SIGNATURES.len()
    + alerts::SIGNATURES.len()
    + outputs::SIGNATURES.len()
    + requests::SIGNATURES.len()
    + strategy::SIGNATURES.len()
    + drawings::SIGNATURES.len()
    + drawings::tables::SIGNATURES.len()
    + chart::SIGNATURES.len()
    + colors::SIGNATURES.len()
    + strings::SIGNATURES.len()
    + syminfo::SIGNATURES.len()
    + ticker::SIGNATURES.len()
    + time::SIGNATURES.len()
    + core::CAST_SIGNATURES.len()
    + math::SIGNATURES.len()
    + core::VALUE_SIGNATURES.len()
    + arrays::SIGNATURES.len()
    + maps::SIGNATURES.len()
    + matrices::SIGNATURES.len()
    + ta::SIGNATURES.len();

static PHASE_1_BUILTINS_ARRAY: [BuiltinSignature; BUILTIN_COUNT] = build_phase_1_builtins();

pub const PHASE_1_BUILTINS: &[BuiltinSignature] = &PHASE_1_BUILTINS_ARRAY;

const fn build_phase_1_builtins() -> [BuiltinSignature; BUILTIN_COUNT] {
    let mut builtins = [EMPTY_SIGNATURE; BUILTIN_COUNT];
    let mut index = 0;

    index = copy_signatures(&mut builtins, index, core::SCRIPT_SIGNATURES);
    index = copy_signatures(&mut builtins, index, alerts::SIGNATURES);
    index = copy_signatures(&mut builtins, index, outputs::SIGNATURES);
    index = copy_signatures(&mut builtins, index, requests::SIGNATURES);
    index = copy_signatures(&mut builtins, index, strategy::SIGNATURES);
    index = copy_signatures(&mut builtins, index, drawings::SIGNATURES);
    index = copy_signatures(&mut builtins, index, drawings::tables::SIGNATURES);
    index = copy_signatures(&mut builtins, index, chart::SIGNATURES);
    index = copy_signatures(&mut builtins, index, colors::SIGNATURES);
    index = copy_signatures(&mut builtins, index, strings::SIGNATURES);
    index = copy_signatures(&mut builtins, index, syminfo::SIGNATURES);
    index = copy_signatures(&mut builtins, index, ticker::SIGNATURES);
    index = copy_signatures(&mut builtins, index, time::SIGNATURES);
    index = copy_signatures(&mut builtins, index, core::CAST_SIGNATURES);
    index = copy_signatures(&mut builtins, index, math::SIGNATURES);
    index = copy_signatures(&mut builtins, index, core::VALUE_SIGNATURES);
    index = copy_signatures(&mut builtins, index, arrays::SIGNATURES);
    index = copy_signatures(&mut builtins, index, maps::SIGNATURES);
    index = copy_signatures(&mut builtins, index, matrices::SIGNATURES);
    let _index = copy_signatures(&mut builtins, index, ta::SIGNATURES);

    builtins
}

const fn copy_signatures<const N: usize>(
    builtins: &mut [BuiltinSignature; N],
    start: usize,
    signatures: &[BuiltinSignature],
) -> usize {
    let mut offset = 0;
    while offset < signatures.len() {
        builtins[start + offset] = signatures[offset];
        offset += 1;
    }
    start + offset
}

#[must_use]
pub fn is_phase_1_builtin(name: &str) -> bool {
    PHASE_1_BUILTINS
        .iter()
        .any(|signature| signature.name == name)
}

#[must_use]
pub fn get_phase_1_builtin(name: &str) -> Option<&'static BuiltinSignature> {
    PHASE_1_BUILTINS
        .iter()
        .find(|signature| signature.name == name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registers_strategy_declaration_signature() {
        let signature = get_phase_1_builtin("strategy").expect("strategy declaration signature");
        assert_eq!(signature.params[0].name, "title");
        assert_eq!(signature.params[0].accepts, crate::Accepts::ConstString);
        assert_eq!(signature.params[4].name, "initial_capital");
        assert_eq!(signature.params[4].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[5].name, "default_qty_type");
        assert_eq!(signature.params[5].accepts, crate::Accepts::ConstString);
        assert_eq!(signature.params[6].name, "default_qty_value");
        assert_eq!(signature.params[6].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[7].name, "commission_type");
        assert_eq!(signature.params[7].accepts, crate::Accepts::ConstString);
        assert_eq!(signature.params[8].name, "commission_value");
        assert_eq!(signature.params[8].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[9].name, "slippage");
        assert_eq!(signature.params[9].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[10].name, "backtest_fill_limits_assumption");
        assert_eq!(signature.params[10].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[11].name, "margin_long");
        assert_eq!(signature.params[11].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[12].name, "margin_short");
        assert_eq!(signature.params[12].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[13].name, "pyramiding");
        assert_eq!(signature.params[13].accepts, crate::Accepts::ConstNumeric);
        assert_eq!(signature.params[14].name, "close_entries_rule");
        assert_eq!(signature.params[14].accepts, crate::Accepts::ConstString);
        assert_eq!(signature.params[15].name, "max_labels_count");
        assert_eq!(
            signature.params[15].accepts,
            crate::Accepts::Exact(pine_ir::PineType::new(
                pine_ir::Qualifier::Const,
                pine_ir::ValueKind::Int
            ))
        );
        assert_eq!(signature.params[16].name, "max_boxes_count");
        assert_eq!(
            signature.params[16].accepts,
            crate::Accepts::Exact(pine_ir::PineType::new(
                pine_ir::Qualifier::Const,
                pine_ir::ValueKind::Int
            ))
        );
        assert_eq!(signature.params[17].name, "max_lines_count");
        assert_eq!(
            signature.params[17].accepts,
            crate::Accepts::Exact(pine_ir::PineType::new(
                pine_ir::Qualifier::Const,
                pine_ir::ValueKind::Int
            ))
        );
        assert_eq!(signature.params[18].name, "max_polylines_count");
        assert_eq!(
            signature.params[18].accepts,
            crate::Accepts::Exact(pine_ir::PineType::new(
                pine_ir::Qualifier::Const,
                pine_ir::ValueKind::Int
            ))
        );
        assert_eq!(signature.params[19].name, "currency");
        assert_eq!(signature.params[19].accepts, crate::Accepts::ConstString);
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_entry_signature() {
        let signature = get_phase_1_builtin("strategy.entry").expect("strategy.entry signature");
        assert_eq!(signature.params[0].name, "id");
        assert_eq!(signature.params[1].name, "direction");
        assert_eq!(signature.params[2].name, "qty");
        assert!(signature.params[2].optional);
        assert_eq!(signature.params[3].name, "limit");
        assert!(signature.params[3].optional);
        assert_eq!(signature.params[4].name, "stop");
        assert!(signature.params[4].optional);
        assert_eq!(signature.params[5].name, "comment");
        assert_eq!(
            signature.params[5].accepts,
            crate::Accepts::StringCompatible
        );
        assert!(signature.params[5].optional);
        assert_eq!(signature.params[6].name, "alert_message");
        assert_eq!(
            signature.params[6].accepts,
            crate::Accepts::StringCompatible
        );
        assert!(signature.params[6].optional);
        assert_eq!(signature.params[7].name, "disable_alert");
        assert_eq!(signature.params[7].accepts, crate::Accepts::BoolCompatible);
        assert!(signature.params[7].optional);
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_default_entry_qty_signature() {
        let signature = get_phase_1_builtin("strategy.default_entry_qty")
            .expect("strategy.default_entry_qty signature");
        assert_eq!(signature.params.len(), 1);
        assert_eq!(signature.params[0].name, "fill_price");
        assert_eq!(
            signature.params[0].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(
            signature.returns,
            crate::ReturnSpec::Fixed(crate::namespaces::types::SERIES_FLOAT)
        );
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_currency_conversion_signatures() {
        for name in ["strategy.convert_to_account", "strategy.convert_to_symbol"] {
            let signature = get_phase_1_builtin(name).expect("strategy conversion signature");
            assert_eq!(signature.params.len(), 1);
            assert_eq!(signature.params[0].name, "value");
            assert_eq!(
                signature.params[0].accepts,
                crate::Accepts::SeriesOrSimpleNumeric
            );
            assert_eq!(
                signature.returns,
                crate::ReturnSpec::Fixed(crate::namespaces::types::SERIES_FLOAT)
            );
            assert!(!signature.variadic);
        }
    }

    #[test]
    fn registers_strategy_close_signature() {
        let signature = get_phase_1_builtin("strategy.close").expect("strategy.close signature");
        assert_eq!(signature.params[0].name, "id");
        assert_eq!(signature.params[1].name, "qty");
        assert!(signature.params[1].optional);
        assert_eq!(signature.params[2].name, "qty_percent");
        assert!(signature.params[2].optional);
        assert_eq!(signature.params[3].name, "comment");
        assert_eq!(
            signature.params[3].accepts,
            crate::Accepts::StringCompatible
        );
        assert!(signature.params[3].optional);
        assert_eq!(signature.params[4].name, "alert_message");
        assert_eq!(
            signature.params[4].accepts,
            crate::Accepts::StringCompatible
        );
        assert!(signature.params[4].optional);
        assert_eq!(signature.params[5].name, "disable_alert");
        assert_eq!(signature.params[5].accepts, crate::Accepts::BoolCompatible);
        assert!(signature.params[5].optional);
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_close_all_signature() {
        let signature =
            get_phase_1_builtin("strategy.close_all").expect("strategy.close_all signature");
        assert_eq!(signature.params[0].name, "comment");
        assert_eq!(
            signature.params[0].accepts,
            crate::Accepts::StringCompatible
        );
        assert!(signature.params[0].optional);
        assert_eq!(signature.params[1].name, "alert_message");
        assert_eq!(
            signature.params[1].accepts,
            crate::Accepts::StringCompatible
        );
        assert!(signature.params[1].optional);
        assert_eq!(signature.params[2].name, "disable_alert");
        assert_eq!(signature.params[2].accepts, crate::Accepts::BoolCompatible);
        assert!(signature.params[2].optional);
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_cancel_signature() {
        let signature = get_phase_1_builtin("strategy.cancel").expect("strategy.cancel signature");
        assert_eq!(signature.params[0].name, "id");
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_cancel_all_signature() {
        let signature =
            get_phase_1_builtin("strategy.cancel_all").expect("strategy.cancel_all signature");
        assert!(signature.params.is_empty());
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_syminfo_symbol_helper_signatures() {
        for name in ["syminfo.prefix", "syminfo.ticker"] {
            let signature = get_phase_1_builtin(name).expect("syminfo symbol helper signature");
            assert_eq!(signature.params.len(), 1);
            assert_eq!(signature.params[0].name, "symbol");
            assert_eq!(signature.params[0].accepts, crate::Accepts::SimpleString);
            assert_eq!(
                signature.returns,
                ReturnSpec::Fixed(crate::namespaces::types::SIMPLE_STRING)
            );
            assert!(!signature.variadic);
        }
    }

    #[test]
    fn registers_strategy_exit_signature() {
        let signature = get_phase_1_builtin("strategy.exit").expect("strategy.exit signature");
        assert_eq!(signature.params.len(), 20);
        assert_eq!(signature.params[0].name, "id");
        assert_eq!(signature.params[1].name, "from_entry");
        assert!(signature.params[1].optional);
        assert_eq!(signature.params[2].name, "stop");
        assert!(signature.params[2].optional);
        assert_eq!(
            signature.params[2].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[3].name, "limit");
        assert!(signature.params[3].optional);
        assert_eq!(
            signature.params[3].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[4].name, "profit");
        assert!(signature.params[4].optional);
        assert_eq!(
            signature.params[4].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[5].name, "loss");
        assert!(signature.params[5].optional);
        assert_eq!(
            signature.params[5].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[6].name, "trail_price");
        assert!(signature.params[6].optional);
        assert_eq!(
            signature.params[6].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[7].name, "trail_points");
        assert!(signature.params[7].optional);
        assert_eq!(
            signature.params[7].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[8].name, "trail_offset");
        assert!(signature.params[8].optional);
        assert_eq!(
            signature.params[8].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[9].name, "qty");
        assert!(signature.params[9].optional);
        assert_eq!(
            signature.params[9].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        assert_eq!(signature.params[10].name, "qty_percent");
        assert!(signature.params[10].optional);
        assert_eq!(
            signature.params[10].accepts,
            crate::Accepts::SeriesOrSimpleNumeric
        );
        for (index, name) in [
            "comment",
            "comment_profit",
            "comment_loss",
            "comment_trailing",
            "alert_message",
            "alert_profit",
            "alert_loss",
            "alert_trailing",
        ]
        .into_iter()
        .enumerate()
        {
            let param = &signature.params[11 + index];
            assert_eq!(param.name, name);
            assert!(param.optional);
            assert_eq!(param.accepts, crate::Accepts::StringCompatible);
        }
        assert_eq!(signature.params[19].name, "disable_alert");
        assert!(signature.params[19].optional);
        assert_eq!(signature.params[19].accepts, crate::Accepts::BoolCompatible);
        assert!(!signature.variadic);
    }

    #[test]
    fn registers_strategy_trade_field_signatures() {
        for name in [
            "strategy.closedtrades.entry_price",
            "strategy.closedtrades.entry_comment",
            "strategy.closedtrades.entry_id",
            "strategy.closedtrades.exit_price",
            "strategy.closedtrades.exit_comment",
            "strategy.closedtrades.exit_id",
            "strategy.closedtrades.entry_bar_index",
            "strategy.closedtrades.exit_bar_index",
            "strategy.closedtrades.entry_time",
            "strategy.closedtrades.exit_time",
            "strategy.closedtrades.commission",
            "strategy.closedtrades.size",
            "strategy.closedtrades.profit",
            "strategy.closedtrades.profit_percent",
            "strategy.closedtrades.max_runup",
            "strategy.closedtrades.max_runup_percent",
            "strategy.closedtrades.max_drawdown",
            "strategy.closedtrades.max_drawdown_percent",
            "strategy.opentrades.entry_price",
            "strategy.opentrades.entry_comment",
            "strategy.opentrades.entry_id",
            "strategy.opentrades.entry_bar_index",
            "strategy.opentrades.entry_time",
            "strategy.opentrades.size",
            "strategy.opentrades.profit",
            "strategy.opentrades.profit_percent",
            "strategy.opentrades.commission",
            "strategy.opentrades.max_runup",
            "strategy.opentrades.max_runup_percent",
            "strategy.opentrades.max_drawdown",
            "strategy.opentrades.max_drawdown_percent",
        ] {
            let signature = get_phase_1_builtin(name).expect("trade field signature");
            assert_eq!(signature.params.len(), 1, "{name}");
            assert_eq!(signature.params[0].name, "trade_num", "{name}");
            assert_eq!(
                signature.params[0].accepts,
                crate::Accepts::SeriesOrSimpleNumeric,
                "{name}"
            );
            assert!(!signature.params[0].optional, "{name}");
            assert!(!signature.variadic, "{name}");
        }
    }
}
