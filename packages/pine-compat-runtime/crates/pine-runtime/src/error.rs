#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeError {
    pub message: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RuntimeLoopControl {
    Break,
    Continue,
}

const LOOP_BREAK_SENTINEL: &str = "__pine_internal_loop_break__";
const LOOP_CONTINUE_SENTINEL: &str = "__pine_internal_loop_continue__";

impl RuntimeError {
    pub(crate) fn loop_break() -> Self {
        Self {
            message: LOOP_BREAK_SENTINEL.to_owned(),
        }
    }

    pub(crate) fn loop_continue() -> Self {
        Self {
            message: LOOP_CONTINUE_SENTINEL.to_owned(),
        }
    }

    pub(crate) fn loop_control(&self) -> Option<RuntimeLoopControl> {
        match self.message.as_str() {
            LOOP_BREAK_SENTINEL => Some(RuntimeLoopControl::Break),
            LOOP_CONTINUE_SENTINEL => Some(RuntimeLoopControl::Continue),
            _ => None,
        }
    }

    pub(crate) fn escaped_loop_control() -> Self {
        Self {
            message: "loop control escaped its enclosing loop".to_owned(),
        }
    }
}
