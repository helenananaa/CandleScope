use super::*;

#[test]
fn accepts_ta_window_statistics() {
    let analysis = analyze(
        "plot(ta.bbw(close, 3, 2) + ta.stdev(close, 3, false) + ta.variance(close, 3, true) + ta.range(close, 3) + ta.dev(close, 3) + ta.vwma(close, 3) + ta.wma(close, 3) + ta.hma(close, 4) + ta.swma(close) + ta.alma(close, 4, 0.85, 6, true) + ta.linreg(close, 3, 0) + ta.correlation(close, 1, 3) + ta.covariance(1, high, 3) + ta.median(1, 3) + ta.mode(1, 3) + ta.percentile_nearest_rank(1, 3, 50) + ta.percentile_linear_interpolation(1, 3, 50) + ta.percentrank(1, 3))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.bbw")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.stdev")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.variance")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.range")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.dev")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.correlation")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.covariance")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.median")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.mode")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.percentile_nearest_rank")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.percentile_linear_interpolation")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.percentrank")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.vwma")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.wma")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.hma")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.swma")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.alma")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.linreg")
    );
}

#[test]
fn accepts_ta_numeric_series_sources() {
    let analysis = analyze(
        "[macd, signal, hist] = ta.macd(bar_index, 2, 3, 2)\n[basis, upper, lower] = ta.bb(bar_index, 3, 2)\nplot(ta.sma(bar_index, 2) + ta.ema(bar_index, 2) + ta.rma(bar_index, 2) + ta.rsi(bar_index, 2) + ta.bbw(bar_index, 3, 2) + ta.stdev(bar_index, 3) + ta.variance(bar_index, 3) + ta.range(bar_index, 3) + ta.dev(bar_index, 3) + ta.vwma(bar_index, 3) + ta.wma(bar_index, 3) + ta.hma(bar_index, 4) + ta.swma(bar_index) + ta.alma(bar_index, 4, 0.85, 6) + ta.linreg(bar_index, 3, 0) + ta.median(bar_index, 3) + ta.mode(bar_index, 3) + ta.percentrank(bar_index, 3) + ta.mom(bar_index, 2) + ta.roc(bar_index, 2) + macd + signal + hist + basis + upper + lower + (ta.rising(bar_index, 2) ? 1 : 0) + (ta.falling(bar_index, 2) ? 1 : 0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn accepts_ta_momentum_history_calls() {
    let analysis = analyze(
        "flag_changed = ta.change(close > open)\nplot(ta.change(bar_index) + ta.mom(close, 2) + ta.roc(open, 2) + (flag_changed ? 1 : 0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.change")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.mom")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.roc")
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
    assert!(
        hir.series_history
            .iter()
            .any(|requirement| requirement.max_constant_offset == 2)
    );
}

#[test]
fn accepts_ta_trend_window_calls() {
    let analysis = analyze("plot(ta.rising(close, 2) ? 1 : ta.falling(open, 2) ? -1 : 0)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.rising")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.falling")
    );
}

#[test]
fn accepts_ta_extreme_bar_offsets() {
    let analysis = analyze(
        "plot(ta.highest(3) + ta.lowest(3) + ta.highestbars(close, 3) + ta.lowestbars(open, 3) + ta.highestbars(3) + ta.lowestbars(length=3))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.highest")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.lowest")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.highestbars")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.lowestbars")
    );
}

#[test]
fn accepts_ta_barssince() {
    let analysis = analyze("plot(ta.barssince(close > open))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.barssince")
    );
}

#[test]
fn accepts_ta_valuewhen() {
    let analysis = analyze(
        "price = ta.valuewhen(close > open, close, 0)\nflag = ta.valuewhen(close > open, close > high, 1)\nshade = ta.valuewhen(close > open, color.red, 0)\nplot(price + (flag ? 1 : 0) + (shade == color.red ? 1 : 0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.valuewhen")
    );
}

#[test]
fn accepts_ta_cum() {
    let analysis = analyze("plot(ta.cum(close) + ta.cum(bar_index))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.cum")
    );
}

#[test]
fn accepts_ta_all_time_extremes() {
    let analysis = analyze("plot(ta.max(close) + ta.min(open) + ta.max(bar_index))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.max")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.min")
    );
}

#[test]
fn accepts_ta_dema_tema() {
    let analysis = analyze("plot(ta.dema(close, 3) + ta.tema(bar_index, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.dema")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.tema")
    );
}

#[test]
fn accepts_ta_volume_flow_variables() {
    let analysis = analyze(
        "plot(ta.accdist + ta.iii + ta.nvi + ta.obv + ta.pvi + ta.pvt + ta.vwap + ta.vwap(close) + ta.vwap(close, bar_index == 1) + ta.wad + ta.wvad)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.accdist")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.iii")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.nvi")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.obv")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.pvi")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.pvt")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.vwap")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.wad")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.wvad")
    );
}

#[test]
fn accepts_ta_vwap_bands_tuple_overload() {
    let analysis = analyze(
        "[basis, upper, lower] = ta.vwap(close, bar_index == 1, 2.0)\nplot(basis + upper + lower)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.vwap")
    );
}

#[test]
fn accepts_ta_pivot_point_levels() {
    let analysis = analyze(
        "levels = ta.pivot_point_levels(\"Traditional\", bar_index == 2, true)\nplot(array.get(levels, 0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.pivot_point_levels")
    );
}

#[test]
fn accepts_ta_supertrend() {
    let analysis = analyze("[line, direction] = ta.supertrend(2.0, 3)\nplot(line + direction)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.supertrend")
    );
}

#[test]
fn accepts_ta_dmi() {
    let analysis = analyze("[plus, minus, adx] = ta.dmi(3, 2)\nplot(plus + minus + adx)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.dmi")
    );
}

#[test]
fn accepts_ta_stoch() {
    let analysis = analyze("plot(ta.stoch(close, high, low, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.stoch")
    );
}

#[test]
fn accepts_ta_sar() {
    let analysis = analyze("plot(ta.sar(0.02, 0.02, 0.2))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.sar")
    );
}

#[test]
fn accepts_ta_wpr() {
    let analysis = analyze("plot(ta.wpr(3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.wpr")
    );
}

#[test]
fn accepts_ta_ao() {
    let analysis = analyze("plot(ta.ao())\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.ao")
    );
}

#[test]
fn accepts_ta_bop() {
    let analysis = analyze("plot(ta.bop())\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.bop")
    );
}

#[test]
fn accepts_ta_cci() {
    let analysis = analyze("plot(ta.cci(close, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.cci")
    );
}

#[test]
fn accepts_ta_cog() {
    let analysis = analyze("plot(ta.cog(close, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.cog")
    );
}

#[test]
fn accepts_ta_kc_and_kcw() {
    let analysis = analyze(
        "[middle, upper, lower] = ta.kc(close, 3, 2, false)\nplot(middle + upper + lower + ta.kcw(close, 3, 2))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.kc")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.kcw")
    );
}

#[test]
fn accepts_ta_pivots() {
    let analysis = analyze(
        "plot(ta.pivothigh(close, 2, 1) + ta.pivotlow(low, 2, 1) + ta.pivothigh(2, 1) + ta.pivotlow(leftbars=2, rightbars=1) + ta.pivothigh(rightbars=1, leftbars=2))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.pivothigh")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.pivotlow")
    );
}

#[test]
fn accepts_ta_mfi() {
    let analysis = analyze("plot(ta.mfi(hlc3, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.mfi")
    );
}

#[test]
fn accepts_ta_tsi() {
    let analysis = analyze("plot(ta.tsi(close, 2, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.tsi")
    );
}

#[test]
fn accepts_ta_cmo() {
    let analysis = analyze("plot(ta.cmo(close, 3))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "ta.cmo")
    );
}
