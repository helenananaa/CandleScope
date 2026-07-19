use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn integer_math_extremes_preserve_i64_precision() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("integer math extremes")
maximum = math.max(9223372036854775806, 9223372036854775805)
minimum = math.min(9223372036854775806, 9223372036854775805)
plot(maximum)
plot(minimum)
plot(maximum % 2 == 0 ? 1 : 2)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect("runtime should preserve integer precision");

    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Int(9_223_372_036_854_775_806)]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(9_223_372_036_854_775_805)]
    );
    assert_eq!(result.plots[2].values, vec![PineValue::Int(1)]);
}

#[test]
fn runs_selected_math_functions() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("math")
x = math.max(math.abs(close - 3), math.round(close / 2), 1)
y = math.min(x, 3.5)
avg_value = math.avg(open, close, high, low)
floor_value = math.floor(close / 2)
ceil_value = math.ceil(close / 2 - 0.25)
trunc_value = math.trunc(close / 2 + 0.75)
const_value = math.floor(2) + math.ceil(1)
sqrt_value = math.sqrt(close)
cbrt_value = math.cbrt(close)
log_value = math.log(close)
log10_value = math.log10(close)
exp_value = math.exp(close)
acos_value = math.acos(close - 2)
asin_value = math.asin(close - 2)
atan_value = math.atan(close)
sign_value = math.sign(close - 2)
degrees_value = math.todegrees(close)
radians_value = math.toradians(close)
constants = math.pi + math.e + math.phi + math.rphi
sin_value = math.sin(close)
cos_value = math.cos(close)
tan_value = math.tan(close)
pow_value = math.pow(close, 2)
hypot_value = math.hypot(close, close + 1)
rounded_precision = math.round(close / 3, 2)
rounded_mintick = math.round_to_mintick(close + 0.006)
mintick = syminfo.mintick
seeded_random = math.random(10, 20, 7)
seeded_random_repeat = math.random(10, 20, 7)
default_random = math.random()
invalid_random = math.random(5, 5, 7)
plot(x)
plot(y)
plot(avg_value)
plot(floor_value + ceil_value)
plot(trunc_value)
plot(const_value)
plot(sqrt_value)
plot(cbrt_value)
plot(log_value)
plot(log10_value)
plot(exp_value)
plot(acos_value)
plot(asin_value)
plot(atan_value)
plot(sign_value)
plot(degrees_value)
plot(radians_value)
plot(constants)
plot(sin_value)
plot(cos_value)
plot(tan_value)
plot(pow_value)
plot(hypot_value)
plot(rounded_precision)
plot(rounded_mintick)
plot(mintick)
plot(seeded_random)
plot(seeded_random_repeat)
plot(default_random)
plot(invalid_random)
plot(math.sqrt(-1))
plot(math.log(0))
plot(math.log10(0))
plot(math.exp(1000))
plot(math.acos(2))
plot(math.asin(2))
plot(math.pow(-1, 0.5))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[2.0, 1.0, 2.0, 2.0]);
    assert_values_close(&result.plots[1].values, &[2.0, 1.0, 2.0, 2.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 2.0, 3.0, 4.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 2.0, 3.0, 4.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0, 2.0, 2.0]);
    assert_values_close(&result.plots[5].values, &[3.0, 3.0, 3.0, 3.0]);
    assert_values_close(
        &result.plots[6].values,
        &[1.0, 2.0_f64.sqrt(), 3.0_f64.sqrt(), 2.0],
    );
    assert_values_close(
        &result.plots[7].values,
        &[1.0, 2.0_f64.cbrt(), 3.0_f64.cbrt(), 4.0_f64.cbrt()],
    );
    assert_values_close(
        &result.plots[8].values,
        &[0.0, 2.0_f64.ln(), 3.0_f64.ln(), 4.0_f64.ln()],
    );
    assert_values_close(
        &result.plots[9].values,
        &[0.0, 2.0_f64.log10(), 3.0_f64.log10(), 4.0_f64.log10()],
    );
    assert_values_close(
        &result.plots[10].values,
        &[1.0_f64.exp(), 2.0_f64.exp(), 3.0_f64.exp(), 4.0_f64.exp()],
    );
    assert_values_close(
        &result.plots[11].values[..3],
        &[(-1.0_f64).acos(), 0.0_f64.acos(), 1.0_f64.acos()],
    );
    assert_eq!(result.plots[11].values[3], PineValue::Na);
    assert_values_close(
        &result.plots[12].values[..3],
        &[(-1.0_f64).asin(), 0.0_f64.asin(), 1.0_f64.asin()],
    );
    assert_eq!(result.plots[12].values[3], PineValue::Na);
    assert_values_close(
        &result.plots[13].values,
        &[
            1.0_f64.atan(),
            2.0_f64.atan(),
            3.0_f64.atan(),
            4.0_f64.atan(),
        ],
    );
    assert_values_close(&result.plots[14].values, &[-1.0, 0.0, 1.0, 1.0]);
    assert_values_close(
        &result.plots[15].values,
        &[
            1.0_f64.to_degrees(),
            2.0_f64.to_degrees(),
            3.0_f64.to_degrees(),
            4.0_f64.to_degrees(),
        ],
    );
    assert_values_close(
        &result.plots[16].values,
        &[
            1.0_f64.to_radians(),
            2.0_f64.to_radians(),
            3.0_f64.to_radians(),
            4.0_f64.to_radians(),
        ],
    );
    assert_values_close(
        &result.plots[17].values,
        &[std::f64::consts::PI
            + std::f64::consts::E
            + 1.618_033_988_749_895
            + 0.618_033_988_749_894_8; 4],
    );
    assert_values_close(
        &result.plots[18].values,
        &[1.0_f64.sin(), 2.0_f64.sin(), 3.0_f64.sin(), 4.0_f64.sin()],
    );
    assert_values_close(
        &result.plots[19].values,
        &[1.0_f64.cos(), 2.0_f64.cos(), 3.0_f64.cos(), 4.0_f64.cos()],
    );
    assert_values_close(
        &result.plots[20].values,
        &[1.0_f64.tan(), 2.0_f64.tan(), 3.0_f64.tan(), 4.0_f64.tan()],
    );
    assert_values_close(&result.plots[21].values, &[1.0, 4.0, 9.0, 16.0]);
    assert_values_close(
        &result.plots[22].values,
        &[5.0_f64.sqrt(), 13.0_f64.sqrt(), 5.0, 41.0_f64.sqrt()],
    );
    assert_values_close(&result.plots[23].values, &[0.33, 0.67, 1.0, 1.33]);
    assert_values_close(&result.plots[24].values, &[1.01, 2.01, 3.01, 4.01]);
    assert_values_close(&result.plots[25].values, &[0.01, 0.01, 0.01, 0.01]);
    for value in &result.plots[26].values {
        let value = value.as_f64().expect("seeded random is numeric");
        assert!((10.0..20.0).contains(&value), "random value {value}");
    }
    assert_eq!(result.plots[26].values, result.plots[27].values);
    for value in &result.plots[28].values {
        let value = value.as_f64().expect("default random is numeric");
        assert!((0.0..1.0).contains(&value), "random value {value}");
    }
    assert_eq!(result.plots[29].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[30].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[31].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[32].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[33].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[34].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[35].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[36].values, vec![PineValue::Na; 4]);
}

#[test]
fn math_round_ties_round_up() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("math round ties")
plot(math.round(1.5))
plot(math.round(-1.5))
plot(math.round(1.25, 1))
plot(math.round(-1.25, 1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values, vec![PineValue::Int(2); 4]);
    assert_eq!(result.plots[1].values, vec![PineValue::Int(-1); 4]);
    assert_values_close(&result.plots[2].values, &[1.3, 1.3, 1.3, 1.3]);
    assert_values_close(&result.plots[3].values, &[-1.2, -1.2, -1.2, -1.2]);
}

#[test]
fn integer_rounding_math_functions_return_int_values() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("integer rounding")
plot(math.floor(1.9))
plot(math.ceil(1.1))
plot(math.trunc(-1.9))
plot(math.round(-1.5))
plot(math.round(1.25, 1))
plot(math.floor(1e20))
plot(math.round(1e20))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values, vec![PineValue::Int(1); 4]);
    assert_eq!(result.plots[1].values, vec![PineValue::Int(2); 4]);
    assert_eq!(result.plots[2].values, vec![PineValue::Int(-1); 4]);
    assert_eq!(result.plots[3].values, vec![PineValue::Int(-1); 4]);
    assert_values_close(&result.plots[4].values, &[1.3, 1.3, 1.3, 1.3]);
    assert_eq!(result.plots[5].values, vec![PineValue::Na; 4]);
    assert_eq!(result.plots[6].values, vec![PineValue::Na; 4]);
}

#[test]
fn runs_math_sum_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("math sum")
value = math.sum(close, 3)
with_na = math.sum(bar_index == 3 ? na : close, 3)
recovers_after_na = math.sum(bar_index == 1 ? na : close, 2)
invalid = math.sum(close, 0)
plot(value)
plot(with_na)
plot(recovers_after_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[7.0, 14.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..3], &[7.0]);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_eq!(result.plots[2].values[2], PineValue::Na);
    assert_values_close(&result.plots[2].values[3..], &[12.0]);
    assert_eq!(result.plots[3].values, vec![PineValue::Na; 4]);
}

#[test]
fn runs_math_sum_with_computed_integer_length() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("math sum computed length")
n = 2
value = math.sum(close, n + 0)
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[3.0, 6.0, 12.0]);
}
