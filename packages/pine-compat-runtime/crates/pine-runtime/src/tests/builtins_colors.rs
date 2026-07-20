use pine_syntax::SourceFile;

use crate::builtins::colors::{color_rgba, compose_color, interpolate_color};

use super::*;

#[test]
fn runs_color_new_and_named_colors() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("colors")
c = color.new(color.red, 50)
opaque = color.new(color.blue)
opaque_blue = color.new(color.blue, 0)
custom = color.rgb(255, 153, 0, 50)
clamped = color.rgb(260.4, -1.4, 127.5, 125)
opaque_rgb = color.rgb(0, 128, 0, 0)
clamped_base = #112233
clamped_opaque = color.new(clamped_base, -10)
clamped_clear = color.new(clamped_base, 120)
gradient = color.from_gradient(close, 1, 3, color.red, color.green)
gradient_low = color.from_gradient(0, 1, 3, color.red, color.green)
gradient_equal = color.from_gradient(2, 2, 2, color.red, color.green)
missing_gradient = color.from_gradient(na, 1, 3, color.red, color.green)
hex = #ff990080
low_hex = #00ff0080
channels = color.r(custom) + color.g(custom) + color.b(custom) + color.t(custom)
clamped_channels = color.r(clamped) + color.g(clamped) + color.b(clamped) + color.t(clamped)
clamped_transparency = color.t(clamped_opaque) + color.t(clamped_clear)
hex_channels = color.r(hex) + color.g(hex) + color.b(hex) + color.t(hex)
gradient_channels = color.r(gradient) + color.g(gradient) + color.b(gradient) + color.t(gradient)
bgcolor(low_hex)
plot(na(c) ? 0 : 1)
plot(opaque == color.new(color.blue, 0) ? 1 : 0)
plot(opaque_blue == color.blue ? 1 : 0)
plot(channels)
plot(clamped_channels)
plot(color.r(opaque_rgb) == 0 and color.g(opaque_rgb) == 128 and color.b(opaque_rgb) == 0 and color.t(opaque_rgb) == 0 ? 1 : 0)
plot(clamped_transparency)
plot(hex_channels)
plot(gradient_channels)
plot(color.r(gradient_low) == color.r(color.red) and color.g(gradient_low) == color.g(color.red) and color.b(gradient_low) == color.b(color.red) and color.t(gradient_low) == color.t(color.red) ? 1 : 0)
plot(color.r(gradient_equal) == color.r(color.green) and color.g(gradient_equal) == color.g(color.green) and color.b(gradient_equal) == color.b(color.green) and color.t(gradient_equal) == color.t(color.green) ? 1 : 0)
plot(na(missing_gradient) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[458.0, 458.0]);
    assert_values_close(&result.plots[4].values, &[483.0, 483.0]);
    assert_values_close(&result.plots[5].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[6].values, &[100.0, 100.0]);
    assert_values_close(&result.plots[7].values, &[458.0, 458.0]);
    assert_values_close(&result.plots[8].values, &[365.0, 349.0]);
    assert_values_close(&result.plots[9].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[1.0, 1.0]);
    assert_eq!(apply_transparency(0xF23645, 50), 0xF2364580);
    assert_eq!(apply_transparency(0x112233, -10), 0x112233);
    assert_eq!(apply_transparency(0x112233, 120), 0x11223300);
    assert_eq!(apply_transparency(0x00FF00, 50), (1 << 32) | 0x00FF0080);
    assert_eq!(color_rgba((1 << 32) | 0x00FF0080), (0, 255, 0, 128));
    assert_eq!(compose_color(0x4CAF50, 0xFF), 0x4CAF50);
    assert_eq!(compose_color(0x4CAF50, 0x80), 0x4CAF5080);
    assert_eq!(interpolate_color(0xF23645, 0x4CAF50, 0.0), 0xF23645);
    assert_eq!(interpolate_color(0xF23645, 0x4CAF50, 1.0), 0x4CAF50);
    assert_eq!(
        result.bg_colors[0].values,
        vec![
            PineValue::Color((1 << 32) | 0x00FF0080),
            PineValue::Color((1 << 32) | 0x00FF0080)
        ]
    );
    let public_json = public_runtime_result_json(&result);
    assert!(public_json.contains("\"values\":[4311679104,4311679104]"));
}
