pub(crate) fn runtime_fixture_bars_csv(fixture: &str) -> Option<&'static str> {
    match fixture {
        "tests/fixtures/legacy/v2/runtime/core_legacy.pine" => Some(include_str!(
            "../../../../tests/fixtures/legacy/v2/runtime/core_bars.csv"
        )),
        "tests/fixtures/legacy/v3/runtime/core_legacy.pine" => Some(include_str!(
            "../../../../tests/fixtures/legacy/v3/runtime/core_bars.csv"
        )),
        "tests/fixtures/legacy/v4/runtime/logical_strict_legacy.pine" => Some(include_str!(
            "../../../../tests/fixtures/legacy/v4/runtime/logical_strict_bars.csv"
        )),
        "tests/fixtures/legacy/v4/runtime/session_defaults_legacy.pine" => Some(include_str!(
            "../../../../tests/fixtures/legacy/v4/runtime/session_weekend_bars.csv"
        )),
        "tests/fixtures/runtime/vwma_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/vwma_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/mfi_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/mfi_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/accdist_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/accdist_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/ao_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/ao_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/bop_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/bop_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/iii_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/iii_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/nvi_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/nvi_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/obv_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/obv_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/pvi_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/pvi_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/pvt_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/pvt_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/vwap_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/vwap_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/wad_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/wad_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/wvad_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/wvad_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/wpr_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/wpr_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/tr_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/tr_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/atr_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/atr_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/supertrend_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/supertrend_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/dmi_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/dmi_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/sar_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/sar_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/trend_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/trend_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/barssince_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/barssince_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/valuewhen_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/valuewhen_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/ema_rma_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/ema_rma_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/rsi_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/rsi_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/dema_tema_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/dema_tema_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/macd_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/macd_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/tsi_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/tsi_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/cmo_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/cmo_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/cci_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/cci_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/cog_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/cog_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/correlation_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/correlation_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/covariance_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/covariance_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/extremes_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/extremes_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/extreme_bars_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/extreme_bars_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/median_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/median_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/mode_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/mode_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/mom_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/mom_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/roc_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/roc_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/stoch_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/stoch_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/percentile_linear_interpolation_edge_cases.pine" => {
            Some(include_str!(
                "../../../../tests/fixtures/runtime/percentile_linear_interpolation_edge_cases_bars.csv"
            ))
        }
        "tests/fixtures/runtime/percentile_nearest_rank_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/percentile_nearest_rank_edge_cases_bars.csv"
        )),
        "tests/fixtures/runtime/percentrank_edge_cases.pine" => Some(include_str!(
            "../../../../tests/fixtures/runtime/percentrank_edge_cases_bars.csv"
        )),
        _ => None,
    }
}
