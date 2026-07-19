#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirUserTypeIdentity {
    pub source_id: usize,
    pub type_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirUserTypeInfo {
    pub identity: HirUserTypeIdentity,
    pub fields: Vec<HirUserTypeField>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirUserTypeField {
    pub name: String,
    pub user_type_name: Option<String>,
}
