use pine_ir::HirCallArg;

use super::arrays::{ArrayElementKind, array_value_for_kind};
use crate::{HistoricalRuntime, PineValue, RuntimeError};

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct MapStorage {
    pub(crate) key_kind: ArrayElementKind,
    pub(crate) value_kind: ArrayElementKind,
    pub(crate) entries: Vec<(PineValue, PineValue)>,
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_map_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        if !(callee.starts_with("map.new<") || callee.starts_with("map.")) {
            return None;
        }

        Some(match callee {
            name if is_supported_map_new_name(name) => self.eval_map_new(name, args),
            "map.put" => self.eval_map_put(args),
            "map.get" => self.eval_map_get(args),
            "map.contains" => self.eval_map_contains(args),
            "map.clear" => self.eval_map_clear(args),
            "map.remove" => self.eval_map_remove(args),
            "map.copy" => self.eval_map_copy(args),
            "map.put_all" => self.eval_map_put_all(args),
            "map.size" => self.eval_map_size(args),
            "map.keys" => self.eval_map_keys(args),
            "map.values" => self.eval_map_values(args),
            _ => {
                return Some(Err(RuntimeError {
                    message: format!("unsupported runtime call `{callee}`"),
                }));
            }
        })
    }

    fn eval_map_new(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        if !args.is_empty() {
            return Err(RuntimeError {
                message: "map.new does not accept arguments in the current subset".to_owned(),
            });
        }
        let Some((key_kind, value_kind)) = parse_map_new_kinds(callee) else {
            return Err(RuntimeError {
                message: "unsupported map.new template".to_owned(),
            });
        };
        let id = self.next_map_id;
        self.next_map_id += 1;
        self.map_store.insert(
            id,
            MapStorage {
                key_kind,
                value_kind,
                entries: Vec::new(),
            },
        );
        Ok(PineValue::Map(id))
    }

    fn eval_map_put(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(id_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.put expects a map argument".to_owned(),
            });
        };
        let id = self.eval_expr(&id_arg.value)?;
        let PineValue::Map(id) = id else {
            if let Some(key_arg) = args.get(1) {
                let _ = self.eval_expr(&key_arg.value)?;
            }
            if let Some(value_arg) = args.get(2) {
                let _ = self.eval_expr(&value_arg.value)?;
            }
            return Ok(PineValue::Void);
        };
        let Some(storage) = self.map_store.get(&id) else {
            return Ok(PineValue::Void);
        };
        let key_kind = storage.key_kind;
        let value_kind = storage.value_kind;
        let key = self.eval_map_key(&args[1], key_kind)?;
        let value = self.eval_map_value(&args[2], value_kind)?;
        let Some(storage) = self.map_store.get_mut(&id) else {
            return Ok(PineValue::Void);
        };
        if let Some((_, existing_value)) = storage
            .entries
            .iter_mut()
            .find(|(existing_key, _)| map_keys_equal(existing_key, &key))
        {
            *existing_value = value;
        } else {
            storage.entries.push((key, value));
        }
        Ok(PineValue::Void)
    }

    fn eval_map_get(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(id_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.get expects a map argument".to_owned(),
            });
        };
        let id = self.eval_expr(&id_arg.value)?;
        let PineValue::Map(id) = id else {
            if let Some(key_arg) = args.get(1) {
                let _ = self.eval_expr(&key_arg.value)?;
            }
            return Ok(PineValue::Na);
        };
        let Some(storage) = self.map_store.get(&id) else {
            return Ok(PineValue::Na);
        };
        let key_kind = storage.key_kind;
        let key = self.eval_map_key(&args[1], key_kind)?;
        Ok(self
            .map_store
            .get(&id)
            .and_then(|storage| {
                storage
                    .entries
                    .iter()
                    .find(|(existing_key, _)| map_keys_equal(existing_key, &key))
                    .map(|(_, value)| value.clone())
            })
            .unwrap_or(PineValue::Na))
    }

    fn eval_map_contains(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(id_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.contains expects a map argument".to_owned(),
            });
        };
        let id = self.eval_expr(&id_arg.value)?;
        let PineValue::Map(id) = id else {
            if let Some(key_arg) = args.get(1) {
                let _ = self.eval_expr(&key_arg.value)?;
            }
            return Ok(PineValue::Bool(false));
        };
        let Some(storage) = self.map_store.get(&id) else {
            return Ok(PineValue::Bool(false));
        };
        let key_kind = storage.key_kind;
        let key = self.eval_map_key(&args[1], key_kind)?;
        Ok(PineValue::Bool(self.map_store.get(&id).is_some_and(
            |storage| {
                storage
                    .entries
                    .iter()
                    .any(|(existing_key, _)| map_keys_equal(existing_key, &key))
            },
        )))
    }

    fn eval_map_clear(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(id_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.clear expects a map argument".to_owned(),
            });
        };
        let id = self.eval_expr(&id_arg.value)?;
        let PineValue::Map(id) = id else {
            return Ok(PineValue::Void);
        };
        if let Some(storage) = self.map_store.get_mut(&id) {
            storage.entries.clear();
        }
        Ok(PineValue::Void)
    }

    fn eval_map_remove(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(id_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.remove expects a map argument".to_owned(),
            });
        };
        let id = self.eval_expr(&id_arg.value)?;
        let PineValue::Map(id) = id else {
            if let Some(key_arg) = args.get(1) {
                let _ = self.eval_expr(&key_arg.value)?;
            }
            return Ok(PineValue::Void);
        };
        let Some(storage) = self.map_store.get(&id) else {
            return Ok(PineValue::Void);
        };
        let key_kind = storage.key_kind;
        let key = self.eval_map_key(&args[1], key_kind)?;
        if let Some(storage) = self.map_store.get_mut(&id)
            && let Some(index) = storage
                .entries
                .iter()
                .position(|(existing_key, _)| map_keys_equal(existing_key, &key))
        {
            storage.entries.remove(index);
        }
        Ok(PineValue::Void)
    }

    fn eval_map_copy(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(id_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.copy expects a map argument".to_owned(),
            });
        };
        let id = self.eval_expr(&id_arg.value)?;
        let PineValue::Map(id) = id else {
            return Ok(PineValue::Na);
        };
        Ok(self.copy_map(id))
    }

    fn eval_map_put_all(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(target_arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.put_all expects a target map argument".to_owned(),
            });
        };
        let target = self.eval_expr(&target_arg.value)?;
        let source = if let Some(source_arg) = args.get(1) {
            self.eval_expr(&source_arg.value)?
        } else {
            return Err(RuntimeError {
                message: "map.put_all expects a source map argument".to_owned(),
            });
        };
        let (PineValue::Map(target_id), PineValue::Map(source_id)) = (target, source) else {
            return Ok(PineValue::Void);
        };
        let Some(source_entries) = self
            .map_store
            .get(&source_id)
            .map(|storage| storage.entries.clone())
        else {
            return Ok(PineValue::Void);
        };
        let Some(target_storage) = self.map_store.get_mut(&target_id) else {
            return Ok(PineValue::Void);
        };
        for (key, value) in source_entries {
            if let Some((_, existing_value)) = target_storage
                .entries
                .iter_mut()
                .find(|(existing_key, _)| map_keys_equal(existing_key, &key))
            {
                *existing_value = value;
            } else {
                target_storage.entries.push((key, value));
            }
        }
        Ok(PineValue::Void)
    }

    fn eval_map_size(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.size expects a map argument".to_owned(),
            });
        };
        match self.eval_expr(&arg.value)? {
            PineValue::Map(id) => Ok(self.map_store.get(&id).map_or(PineValue::Na, |storage| {
                PineValue::Int(storage.entries.len() as i64)
            })),
            PineValue::Na => Ok(PineValue::Na),
            _ => Err(RuntimeError {
                message: "map.size receiver is not a map".to_owned(),
            }),
        }
    }

    fn eval_map_keys(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.keys expects a map argument".to_owned(),
            });
        };
        let PineValue::Map(id) = self.eval_expr(&arg.value)? else {
            return Ok(PineValue::Na);
        };
        let Some((kind, values)) = self.map_store.get(&id).map(|storage| {
            (
                storage.key_kind,
                storage
                    .entries
                    .iter()
                    .map(|(key, _)| key.clone())
                    .collect::<Vec<_>>(),
            )
        }) else {
            return Ok(PineValue::Na);
        };
        Ok(self.new_array_from_values(kind, values))
    }

    fn eval_map_values(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(arg) = args.first() else {
            return Err(RuntimeError {
                message: "map.values expects a map argument".to_owned(),
            });
        };
        let PineValue::Map(id) = self.eval_expr(&arg.value)? else {
            return Ok(PineValue::Na);
        };
        let Some((kind, values)) = self.map_store.get(&id).map(|storage| {
            (
                storage.value_kind,
                storage
                    .entries
                    .iter()
                    .map(|(_, value)| value.clone())
                    .collect::<Vec<_>>(),
            )
        }) else {
            return Ok(PineValue::Na);
        };
        Ok(self.new_array_from_values(kind, values))
    }

    fn eval_map_key(
        &mut self,
        arg: &HirCallArg,
        kind: ArrayElementKind,
    ) -> Result<PineValue, RuntimeError> {
        let value = array_value_for_kind(kind, self.eval_expr(&arg.value)?);
        match value {
            PineValue::Na => Err(RuntimeError {
                message: "map keys cannot be na".to_owned(),
            }),
            PineValue::Float(value) if !value.is_finite() => Err(RuntimeError {
                message: "map float keys must be finite".to_owned(),
            }),
            value => Ok(value),
        }
    }

    fn eval_map_value(
        &mut self,
        arg: &HirCallArg,
        kind: ArrayElementKind,
    ) -> Result<PineValue, RuntimeError> {
        Ok(array_value_for_kind(kind, self.eval_expr(&arg.value)?))
    }

    pub(crate) fn copy_map(&mut self, source_id: u32) -> PineValue {
        let Some(source) = self.map_store.get(&source_id).cloned() else {
            return PineValue::Na;
        };
        let id = self.next_map_id;
        self.next_map_id += 1;
        self.map_store.insert(id, source);
        PineValue::Map(id)
    }
}

fn is_supported_map_new_name(name: &str) -> bool {
    parse_map_new_types(name).is_some_and(|(key, value)| {
        is_supported_map_scalar_type(key) && is_supported_map_scalar_type(value)
    })
}

fn parse_map_new_types(name: &str) -> Option<(&str, &str)> {
    let inner = name.strip_prefix("map.new<")?.strip_suffix('>')?;
    inner.split_once(',')
}

fn is_supported_map_scalar_type(name: &str) -> bool {
    matches!(name, "int" | "float" | "bool" | "string" | "color")
}

fn parse_map_new_kinds(name: &str) -> Option<(ArrayElementKind, ArrayElementKind)> {
    let (key, value) = parse_map_new_types(name)?;
    Some((map_scalar_kind(key)?, map_scalar_kind(value)?))
}

fn map_scalar_kind(name: &str) -> Option<ArrayElementKind> {
    match name {
        "int" => Some(ArrayElementKind::Int),
        "float" => Some(ArrayElementKind::Float),
        "bool" => Some(ArrayElementKind::Bool),
        "string" => Some(ArrayElementKind::String),
        "color" => Some(ArrayElementKind::Color),
        _ => None,
    }
}

fn map_keys_equal(left: &PineValue, right: &PineValue) -> bool {
    match (left, right) {
        (PineValue::Int(left), PineValue::Int(right)) => left == right,
        (PineValue::Float(left), PineValue::Float(right)) => left == right,
        (PineValue::Bool(left), PineValue::Bool(right)) => left == right,
        (PineValue::String(left), PineValue::String(right)) => left == right,
        (PineValue::Color(left), PineValue::Color(right)) => left == right,
        _ => false,
    }
}
