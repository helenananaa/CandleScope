use crate::Bar;

use super::provider::RequestDataError;

pub fn validate_requested_bars(bars: &[Bar]) -> Result<(), RequestDataError> {
    let mut previous_time = None;
    for bar in bars {
        if let Some(previous_time) = previous_time {
            if bar.time == previous_time {
                return Err(RequestDataError::DuplicateBars { time: bar.time });
            }
            if bar.time < previous_time {
                return Err(RequestDataError::UnsortedBars {
                    previous_time,
                    time: bar.time,
                });
            }
        }
        previous_time = Some(bar.time);
    }
    Ok(())
}
