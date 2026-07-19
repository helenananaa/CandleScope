use pine_ir::HirProgram;

use crate::*;

pub struct RealtimeRuntime<'a> {
    confirmed: HistoricalRuntime<'a>,
    forming: Option<HistoricalRuntime<'a>>,
}
impl<'a> RealtimeRuntime<'a> {
    #[must_use]
    pub fn new(program: &'a HirProgram) -> Self {
        Self::with_request_environment(program, RequestEnvironment::default())
    }

    #[must_use]
    pub fn with_request_environment(
        program: &'a HirProgram,
        request_environment: RequestEnvironment,
    ) -> Self {
        Self {
            confirmed: HistoricalRuntime::with_request_environment(program, request_environment),
            forming: None,
        }
    }

    #[must_use]
    pub fn request_environment(&self) -> &RequestEnvironment {
        self.forming
            .as_ref()
            .unwrap_or(&self.confirmed)
            .request_environment()
    }

    pub fn update(&mut self, update: BarUpdate) -> Result<RuntimeResult, RuntimeError> {
        match update.kind {
            BarUpdateKind::Historical => {
                let mut runtime = self.confirmed.clone();
                runtime.append_bar_with_kind(update.bar, update.kind)?;
                self.confirmed = runtime;
                self.forming = None;
                Ok(self.confirmed.result())
            }
            BarUpdateKind::Confirmed => {
                let is_new_bar = self.forming.is_none();
                let mut runtime = self.confirmed.clone();
                if let Some(previous_forming) = &self.forming {
                    runtime.seed_intrabar_persistence_from(previous_forming);
                }
                runtime.append_bar_with_context(update.bar, update.kind, is_new_bar)?;
                self.confirmed = runtime;
                self.forming = None;
                Ok(self.confirmed.result())
            }
            BarUpdateKind::Forming => {
                let is_new_bar = self.forming.is_none();
                let mut runtime = self.confirmed.clone();
                if let Some(previous_forming) = &self.forming {
                    runtime.seed_intrabar_persistence_from(previous_forming);
                }
                runtime.append_bar_with_context(update.bar, update.kind, is_new_bar)?;
                let result = runtime.result();
                self.forming = Some(runtime);
                Ok(result)
            }
        }
    }

    #[must_use]
    pub fn result(&self) -> RuntimeResult {
        self.forming.as_ref().unwrap_or(&self.confirmed).result()
    }

    #[must_use]
    pub fn confirmed_result(&self) -> RuntimeResult {
        self.confirmed.result()
    }

    #[must_use]
    pub fn profile(&self) -> RuntimeProfile {
        self.forming.as_ref().unwrap_or(&self.confirmed).profile()
    }

    #[must_use]
    pub fn confirmed_profile(&self) -> RuntimeProfile {
        self.confirmed.profile()
    }
}
