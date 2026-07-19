//! Built-in registry scaffolding.

mod constants;
mod history;
mod namespaces;
mod registry;
mod returns;
mod signature;

pub use constants::{
    NAMED_COLORS, NamedColor, builtin_series_value_type, named_color, named_float_constant,
    named_int_constant, named_string_constant,
};
pub use history::{
    BUILTIN_HISTORY_METADATA, BuiltinHistoryMetadata, BuiltinHistoryRequirement,
    BuiltinSeriesHistoryRequirement, builtin_history_requirement,
};
pub use registry::{PHASE_1_BUILTINS, get_phase_1_builtin, is_phase_1_builtin};
pub use returns::{
    change_return_for_arg, color_return_for_arg, fallback_bool_for_arg, input_return_for_arg,
    tuple_return_type,
};
pub use signature::{
    Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, QualifierBoundScalar, QualifierRelation,
    ReturnSpec, ScalarKind,
};
