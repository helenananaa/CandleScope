use std::collections::HashMap;

use pine_syntax::Span;

use crate::source_graph::SourceContextId;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LegacyCallArgRewrite {
    pub(crate) keep: bool,
    pub(crate) canonical_name: Option<&'static str>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LegacyCallLowering {
    HistoryOffset,
    SecuritySpan { start: usize, end: usize },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
struct LegacyUseKey {
    source_context_id: SourceContextId,
    span_start: usize,
    span_end: usize,
}

#[derive(Debug, Default)]
pub(crate) struct LegacyLoweringPlan {
    calls: HashMap<LegacyUseKey, &'static str>,
    call_lowerings: HashMap<LegacyUseKey, LegacyCallLowering>,
    call_arg_rewrites: HashMap<LegacyUseKey, Vec<LegacyCallArgRewrite>>,
    values: HashMap<LegacyUseKey, &'static str>,
    string_values: HashMap<LegacyUseKey, &'static str>,
}

impl LegacyLoweringPlan {
    pub(crate) fn new() -> Self {
        Self {
            calls: HashMap::new(),
            call_lowerings: HashMap::new(),
            call_arg_rewrites: HashMap::new(),
            values: HashMap::new(),
            string_values: HashMap::new(),
        }
    }

    pub(crate) fn record_call_arg_names(
        &mut self,
        source_context_id: SourceContextId,
        span: Span,
        names: Vec<Option<&'static str>>,
    ) {
        self.call_arg_rewrites.insert(
            LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            },
            names
                .into_iter()
                .map(|canonical_name| LegacyCallArgRewrite {
                    keep: true,
                    canonical_name,
                })
                .collect(),
        );
    }

    pub(crate) fn record_call_arg_rewrites(
        &mut self,
        source_context_id: SourceContextId,
        span: Span,
        rewrites: Vec<LegacyCallArgRewrite>,
    ) {
        self.call_arg_rewrites.insert(
            LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            },
            rewrites,
        );
    }

    pub(crate) fn record_call(
        &mut self,
        source_context_id: SourceContextId,
        span: Span,
        canonical_name: &'static str,
    ) {
        self.calls.insert(
            LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            },
            canonical_name,
        );
    }

    pub(crate) fn record_call_lowering(
        &mut self,
        source_context_id: SourceContextId,
        span: Span,
        lowering: LegacyCallLowering,
    ) {
        self.call_lowerings.insert(
            LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            },
            lowering,
        );
    }

    pub(crate) fn record_value(
        &mut self,
        source_context_id: SourceContextId,
        span: Span,
        canonical_name: &'static str,
    ) {
        self.values.insert(
            LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            },
            canonical_name,
        );
    }

    pub(crate) fn record_string_value(
        &mut self,
        source_context_id: SourceContextId,
        span: Span,
        value: &'static str,
    ) {
        self.string_values.insert(
            LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            },
            value,
        );
    }

    pub(crate) fn call_name(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&'static str> {
        self.calls
            .get(&LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            })
            .copied()
    }

    pub(crate) fn call_lowering(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<LegacyCallLowering> {
        self.call_lowerings
            .get(&LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            })
            .copied()
    }

    pub(crate) fn value_name(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&'static str> {
        self.values
            .get(&LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            })
            .copied()
    }

    pub(crate) fn call_arg_rewrites(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&[LegacyCallArgRewrite]> {
        self.call_arg_rewrites
            .get(&LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            })
            .map(Vec::as_slice)
    }

    pub(crate) fn string_value(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&'static str> {
        self.string_values
            .get(&LegacyUseKey {
                source_context_id,
                span_start: span.start,
                span_end: span.end,
            })
            .copied()
    }
}
