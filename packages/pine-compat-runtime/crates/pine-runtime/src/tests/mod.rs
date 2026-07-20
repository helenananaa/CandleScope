mod alerts;
mod arrays;
mod builtin_registry;
mod builtins_colors;
mod builtins_core;
mod builtins_inputs;
mod builtins_math;
mod builtins_strings;
mod builtins_ta_averages;
mod builtins_ta_conditionals;
mod builtins_ta_extremes;
mod builtins_ta_flow;
mod builtins_time;
mod imports;
mod legacy_indicators;
mod matrices;
mod methods;
mod outputs;
mod realtime;
mod request;
mod runtime_const_history;
mod runtime_control_flow;
mod runtime_core;
mod runtime_history;
mod strategy;
mod user_types;

use super::*;

fn modern_source_file(name: impl Into<String>, text: impl Into<String>) -> pine_syntax::SourceFile {
    let name = name.into();
    let text = text.into();
    if text
        .lines()
        .any(|line| line.trim_start().starts_with("//@version="))
    {
        pine_syntax::SourceFile::new(name, text)
    } else {
        pine_syntax::SourceFile::new(name, format!("//@version=5\n{text}"))
    }
}

fn analyze_source(source: &pine_syntax::SourceFile) -> pine_sema::Analysis {
    pine_sema::analyze_source(&modern_source_file(source.name(), source.text()))
}

fn bar(close: f64) -> Bar {
    bar_ohlc(close, close, close, close)
}

fn bar_volume(close: f64, volume: f64) -> Bar {
    Bar {
        time: 0,
        open: close,
        high: close,
        low: close,
        close,
        volume,
    }
}

fn bar_ohlc(open: f64, high: f64, low: f64, close: f64) -> Bar {
    bar_ohlcv(open, high, low, close, 1.0)
}

fn bar_ohlcv(open: f64, high: f64, low: f64, close: f64, volume: f64) -> Bar {
    Bar {
        time: 0,
        open,
        high,
        low,
        close,
        volume,
    }
}

fn assert_values_close(actual: &[PineValue], expected: &[f64]) {
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        let actual = actual
            .as_f64()
            .unwrap_or_else(|| panic!("expected numeric value, got {actual:?}"));
        assert!(
            (actual - expected).abs() < 1e-10,
            "expected {expected}, got {actual}"
        );
    }
}
