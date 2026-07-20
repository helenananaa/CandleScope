use pine_ir::HirProgram;
use pine_runtime::{Bar, BarUpdate, InputOverrides, RealtimeRuntime, RequestEnvironment};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyModule};

use crate::outputs::runtime_result_to_py;
use crate::{compile_script, parse_bar, parse_bars};

pub(crate) const REALTIME_SESSION_SCHEMA_VERSION: u32 = 1;

#[pyclass(name = "RealtimeSession", skip_from_py_object)]
pub(crate) struct PyRealtimeSession {
    runtime: RealtimeRuntime<'static>,
    seeded: bool,
    confirmed_bars: usize,
    last_confirmed_time: Option<i64>,
    forming_time: Option<i64>,
}

impl PyRealtimeSession {
    pub(crate) fn new(
        hir: HirProgram,
        request_environment: RequestEnvironment,
        input_overrides: InputOverrides,
    ) -> Self {
        Self {
            runtime: RealtimeRuntime::from_program_with_request_environment_and_input_overrides(
                hir,
                request_environment,
                input_overrides,
            ),
            seeded: false,
            confirmed_bars: 0,
            last_confirmed_time: None,
            forming_time: None,
        }
    }

    fn require_seeded(&self) -> PyResult<()> {
        if self.seeded {
            Ok(())
        } else {
            Err(PyValueError::new_err(
                "realtime session must be seeded before updates",
            ))
        }
    }

    fn validate_next_bar(&self, bar: &Bar, forming: bool) -> PyResult<()> {
        if let Some(last_confirmed_time) = self.last_confirmed_time
            && bar.time <= last_confirmed_time
        {
            return Err(PyValueError::new_err(format!(
                "realtime bar time `{}` must be later than confirmed time `{last_confirmed_time}`",
                bar.time
            )));
        }
        if let Some(forming_time) = self.forming_time
            && bar.time != forming_time
        {
            let action = if forming { "replace" } else { "confirm" };
            return Err(PyValueError::new_err(format!(
                "realtime {action} time `{}` does not match forming time `{forming_time}`",
                bar.time
            )));
        }
        Ok(())
    }
}

#[pymethods]
impl PyRealtimeSession {
    fn seed(&mut self, py: Python<'_>, bars: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        if self.seeded {
            return Err(PyValueError::new_err(
                "realtime session history has already been seeded",
            ));
        }
        let bars = parse_bars(bars)?;
        let result = self
            .runtime
            .seed_historical(&bars)
            .map_err(|err| PyValueError::new_err(err.message))?;
        self.seeded = true;
        self.confirmed_bars = bars.len();
        self.last_confirmed_time = bars.last().map(|bar| bar.time);
        runtime_result_to_py(py, &result)
    }

    fn update_forming(&mut self, py: Python<'_>, bar: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.require_seeded()?;
        let bar = parse_bar(bar)?;
        self.validate_next_bar(&bar, true)?;
        let result = self
            .runtime
            .update(BarUpdate::forming(bar))
            .map_err(|err| PyValueError::new_err(err.message))?;
        self.forming_time = Some(bar.time);
        runtime_result_to_py(py, &result)
    }

    fn update_confirmed(&mut self, py: Python<'_>, bar: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.require_seeded()?;
        let bar = parse_bar(bar)?;
        self.validate_next_bar(&bar, false)?;
        let result = self
            .runtime
            .update(BarUpdate::confirmed(bar))
            .map_err(|err| PyValueError::new_err(err.message))?;
        self.confirmed_bars += 1;
        self.last_confirmed_time = Some(bar.time);
        self.forming_time = None;
        runtime_result_to_py(py, &result)
    }

    fn result(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        runtime_result_to_py(py, &self.runtime.result())
    }

    fn confirmed_result(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        runtime_result_to_py(py, &self.runtime.confirmed_result())
    }

    #[getter]
    fn schema_version(&self) -> u32 {
        REALTIME_SESSION_SCHEMA_VERSION
    }

    #[getter]
    fn is_seeded(&self) -> bool {
        self.seeded
    }

    #[getter]
    fn confirmed_bars(&self) -> usize {
        self.confirmed_bars
    }

    #[getter]
    fn last_confirmed_time(&self) -> Option<i64> {
        self.last_confirmed_time
    }

    #[getter]
    fn forming_time(&self) -> Option<i64> {
        self.forming_time
    }
}

#[pyfunction(signature = (
    source,
    request_bars=None,
    library_sources=None,
    input_overrides=None,
    chart_symbol=None,
    chart_timeframe=None
))]
#[allow(clippy::too_many_arguments)]
fn create_realtime_session(
    source: &str,
    request_bars: Option<&Bound<'_, PyAny>>,
    library_sources: Option<&Bound<'_, PyAny>>,
    input_overrides: Option<&Bound<'_, PyAny>>,
    chart_symbol: Option<&str>,
    chart_timeframe: Option<&str>,
) -> PyResult<PyRealtimeSession> {
    compile_script(source, library_sources)?.realtime_session(
        request_bars,
        input_overrides,
        chart_symbol,
        chart_timeframe,
    )
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add(
        "REALTIME_SESSION_SCHEMA_VERSION",
        REALTIME_SESSION_SCHEMA_VERSION,
    )?;
    module.add_class::<PyRealtimeSession>()?;
    module.add_function(wrap_pyfunction!(create_realtime_session, module)?)?;
    Ok(())
}
