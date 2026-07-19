//! Host-independent intermediate representation scaffolding.

mod strategy;
mod types;
mod user_types;

pub use strategy::{
    DEFAULT_STRATEGY_INITIAL_CAPITAL, StrategyCloseEntriesRule, StrategyCommission,
    StrategyDefaultQuantity, StrategyMarginSetting, StrategySettings,
};
pub use types::{PineType, Qualifier, ValueKind};
pub use user_types::{HirUserTypeField, HirUserTypeIdentity, HirUserTypeInfo};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SeriesId(pub u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct CallSiteId(pub u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct VarSlotId(pub u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SymbolId(pub u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersistenceKind {
    None,
    Var,
    Varip,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScriptMode {
    Indicator,
    Strategy,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct DrawingSettings {
    pub max_labels_count: Option<u32>,
    pub max_boxes_count: Option<u32>,
    pub max_lines_count: Option<u32>,
    pub max_polylines_count: Option<u32>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HirProgram {
    pub language_version: Option<u16>,
    pub script_mode: ScriptMode,
    pub strategy_settings: StrategySettings,
    pub drawing_settings: DrawingSettings,
    pub user_types: Vec<HirUserTypeInfo>,
    pub symbols: Vec<HirSymbol>,
    pub statements: Vec<HirStmt>,
    pub next_series_id: u32,
    pub next_call_site_id: u32,
    pub next_var_slot_id: u32,
    pub max_bars_back: Option<u32>,
    pub series_max_bars_back: Vec<HirSeriesMaxBarsBack>,
    pub history: HirHistoryRequirements,
    pub series_history: Vec<HirSeriesHistoryRequirement>,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct HirHistoryRequirements {
    pub max_constant_offset: u32,
    pub has_dynamic_offsets: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HirSeriesHistoryRequirement {
    pub series_id: SeriesId,
    pub max_constant_offset: u32,
    pub has_dynamic_offsets: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HirSeriesMaxBarsBack {
    pub series_id: SeriesId,
    pub max_bars_back: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirSymbol {
    pub id: SymbolId,
    pub name: String,
    pub pine_type: PineType,
    pub series_id: Option<SeriesId>,
    pub persistence: PersistenceKind,
    pub var_slot_id: Option<VarSlotId>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HirStmt {
    pub kind: HirStmtKind,
}

#[derive(Debug, Clone, PartialEq)]
pub enum HirStmtKind {
    Expr(HirExpr),
    If {
        condition: HirExpr,
        then_branch: Vec<HirStmt>,
        else_branch: Vec<HirStmt>,
    },
    Switch {
        selector: Option<HirExpr>,
        arms: Vec<HirSwitchStmtArm>,
    },
    For {
        counter: SymbolId,
        from: HirExpr,
        to: HirExpr,
        step: Option<HirExpr>,
        body: Vec<HirStmt>,
    },
    ForIn {
        index: Option<SymbolId>,
        value: SymbolId,
        iterable: HirExpr,
        body: Vec<HirStmt>,
    },
    While {
        condition: HirExpr,
        body: Vec<HirStmt>,
    },
    Break,
    Continue,
    Decl {
        symbol: SymbolId,
        value: HirExpr,
    },
    Reassign {
        symbol: SymbolId,
        value: HirExpr,
    },
    FieldReassign {
        symbol: SymbolId,
        field_index: usize,
        value: HirExpr,
    },
    ArrayFieldReassign {
        array: HirExpr,
        index: HirExpr,
        field_index: usize,
        value: HirExpr,
    },
    TupleDecl {
        symbols: Vec<SymbolId>,
        value: HirExpr,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct HirExpr {
    pub kind: HirExprKind,
    pub pine_type: PineType,
    pub series_id: Option<SeriesId>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum HirExprKind {
    Literal(HirLiteral),
    Symbol(SymbolId),
    Builtin(String),
    Unary {
        op: HirUnaryOp,
        expr: Box<HirExpr>,
    },
    Binary {
        op: HirBinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
    Ternary {
        condition: Box<HirExpr>,
        then_expr: Box<HirExpr>,
        else_expr: Box<HirExpr>,
    },
    Switch {
        selector: Option<Box<HirExpr>>,
        arms: Vec<HirSwitchArm>,
    },
    For {
        counter: SymbolId,
        from: Box<HirExpr>,
        to: Box<HirExpr>,
        step: Option<Box<HirExpr>>,
        statements: Vec<HirStmt>,
        result: Box<HirExpr>,
    },
    ForIn {
        index: Option<SymbolId>,
        value: SymbolId,
        iterable: Box<HirExpr>,
        statements: Vec<HirStmt>,
        result: Box<HirExpr>,
    },
    While {
        condition: Box<HirExpr>,
        statements: Vec<HirStmt>,
        result: Box<HirExpr>,
    },
    Tuple(Vec<HirExpr>),
    UserTypeConstruct {
        identity: HirUserTypeIdentity,
        fields: Vec<HirExpr>,
    },
    UserTypeArrayConstruct {
        type_name: String,
        elements: Vec<HirExpr>,
    },
    FieldAccess {
        value: Box<HirExpr>,
        index: usize,
    },
    Block {
        statements: Vec<HirStmt>,
        result: Box<HirExpr>,
    },
    Call {
        callee: String,
        call_site_id: CallSiteId,
        args: Vec<HirCallArg>,
    },
    History {
        expr: Box<HirExpr>,
        offset: HirHistoryOffset,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub enum HirHistoryOffset {
    Constant(u32),
    Dynamic(Box<HirExpr>),
}

#[derive(Debug, Clone, PartialEq)]
pub struct HirSwitchArm {
    pub condition: Option<HirExpr>,
    pub result: HirExpr,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HirSwitchStmtArm {
    pub condition: Option<HirExpr>,
    pub body: Vec<HirStmt>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HirCallArg {
    pub name: Option<String>,
    pub value: HirExpr,
}

#[derive(Debug, Clone, PartialEq)]
pub enum HirLiteral {
    Int(i64),
    Float(f64),
    Bool(bool),
    String(String),
    ColorHex(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HirUnaryOp {
    Plus,
    Minus,
    Not,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HirBinaryOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Eq,
    NotEq,
    Gt,
    Gte,
    Lt,
    Lte,
    And,
    Or,
}
