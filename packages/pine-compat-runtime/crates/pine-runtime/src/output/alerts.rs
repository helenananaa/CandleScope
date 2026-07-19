#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AlertEvent {
    pub id: u32,
    pub bar_index: usize,
    pub time: i64,
    pub message: String,
    pub source: String,
}
