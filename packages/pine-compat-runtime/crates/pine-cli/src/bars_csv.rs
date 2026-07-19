use pine_runtime::Bar;

pub(crate) fn parse_bars_csv(text: &str) -> Result<Vec<Bar>, String> {
    let mut bars = Vec::new();
    for (line_index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        if line_index == 0 && line.to_ascii_lowercase().contains("close") {
            continue;
        }

        let columns: Vec<_> = line.split(',').map(str::trim).collect();
        if columns.len() != 6 {
            return Err(format!(
                "invalid bars CSV at line {}: expected 6 columns time,open,high,low,close,volume",
                line_index + 1
            ));
        }

        bars.push(Bar {
            time: parse_time_column(columns[0], line_index)?,
            open: parse_f64_column(columns[1], line_index, "open")?,
            high: parse_f64_column(columns[2], line_index, "high")?,
            low: parse_f64_column(columns[3], line_index, "low")?,
            close: parse_f64_column(columns[4], line_index, "close")?,
            volume: parse_f64_column(columns[5], line_index, "volume")?,
        });
    }
    validate_bar_times(&bars)?;
    Ok(bars)
}

fn parse_time_column(value: &str, line_index: usize) -> Result<i64, String> {
    value.parse::<i64>().map_err(|_| {
        format!(
            "invalid `time` value `{value}` at bars CSV line {}",
            line_index + 1
        )
    })
}

fn parse_f64_column(value: &str, line_index: usize, name: &str) -> Result<f64, String> {
    let parsed = value.parse::<f64>().map_err(|_| {
        format!(
            "invalid `{name}` value `{value}` at bars CSV line {}",
            line_index + 1
        )
    })?;
    if !parsed.is_finite() {
        return Err(format!(
            "invalid `{name}` value `{value}` at bars CSV line {}: value must be finite",
            line_index + 1
        ));
    }
    Ok(parsed)
}

fn validate_bar_times(bars: &[Bar]) -> Result<(), String> {
    let mut previous_time = None;
    for bar in bars {
        if let Some(previous_time) = previous_time {
            if bar.time == previous_time {
                return Err(format!("duplicate bar time `{}` in bars CSV", bar.time));
            }
            if bar.time < previous_time {
                return Err(format!(
                    "bars CSV is not sorted: `{}` follows `{previous_time}`",
                    bar.time
                ));
            }
        }
        previous_time = Some(bar.time);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::parse_bars_csv;

    #[test]
    fn rejects_non_finite_ohlcv_values() {
        let fields = ["open", "high", "low", "close", "volume"];
        let non_finite_values = ["NaN", "inf", "-inf", "infinity"];

        for (field_index, field) in fields.iter().enumerate() {
            for value in non_finite_values {
                let mut columns = ["1", "1", "1", "1", "1", "100"];
                columns[field_index + 1] = value;
                let csv = format!("time,open,high,low,close,volume\n{}\n", columns.join(","));

                let error = parse_bars_csv(&csv).expect_err("non-finite value should fail");

                assert!(
                    error.contains(&format!("invalid `{field}` value `{value}`")),
                    "{error}"
                );
            }
        }
    }

    #[test]
    fn rejects_duplicate_bar_times() {
        let csv = "time,open,high,low,close,volume\n1,1,1,1,1,100\n1,2,2,2,2,200\n";

        let error = parse_bars_csv(csv).expect_err("duplicate time should fail");

        assert_eq!(error, "duplicate bar time `1` in bars CSV");
    }

    #[test]
    fn rejects_unsorted_bar_times() {
        let csv = "time,open,high,low,close,volume\n2,2,2,2,2,200\n1,1,1,1,1,100\n";

        let error = parse_bars_csv(csv).expect_err("unsorted time should fail");

        assert_eq!(error, "bars CSV is not sorted: `1` follows `2`");
    }
}
