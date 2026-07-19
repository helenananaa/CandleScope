mod for_in;

use super::{Analyzer, ConstSwitchKey, HistoryOffsetIntEnv};

impl Analyzer {
    pub(super) fn known_history_offset_switch_key(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<ConstSwitchKey> {
        self.known_const_switch_key(expr)
            .or_else(|| {
                self.known_history_offset_bool_value_inner(expr, env)
                    .map(ConstSwitchKey::Bool)
            })
            .or_else(|| {
                self.known_history_offset_numeric_value_inner(expr, env)
                    .map(ConstSwitchKey::Numeric)
            })
            .or_else(|| {
                self.known_history_offset_string_value_inner(expr, env)
                    .map(ConstSwitchKey::String)
            })
            .or_else(|| {
                self.known_history_offset_color_value_inner(expr, env)
                    .map(ConstSwitchKey::Color)
            })
    }

    pub(super) fn known_history_offset_bool_value_inner(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        self.known_const_bool_value(expr)
            .or_else(|| self.known_history_offset_bool_value_from_symbols(expr, env))
    }

    fn known_history_offset_bool_value_from_symbols(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_bool_value_inner(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if let Some(value) = self.const_bool_symbols.get(&symbol.id) {
                    return Some(*value);
                }
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_bool_value_inner(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Unary {
                op: pine_syntax::UnaryOp::Not,
                expr,
            } => self
                .known_history_offset_bool_value_inner(expr, env)
                .map(|value| !value),
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::And,
                left,
                right,
            } => match self.known_history_offset_bool_value_inner(left, env)? {
                false => Some(false),
                true => self.known_history_offset_bool_value_inner(right, env),
            },
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::Or,
                left,
                right,
            } => match self.known_history_offset_bool_value_inner(left, env)? {
                true => Some(true),
                false => self.known_history_offset_bool_value_inner(right, env),
            },
            pine_syntax::ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_bool_value_inner(then_expr, env),
                Some(false) => self.known_history_offset_bool_value_inner(else_expr, env),
                None => {
                    let then_value = self.known_history_offset_bool_value_inner(then_expr, env)?;
                    let else_value = self.known_history_offset_bool_value_inner(else_expr, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_bool_branch_result(then_branch, env),
                Some(false) => self.known_history_offset_bool_branch_result(else_branch, env),
                None => {
                    let then_value =
                        self.known_history_offset_bool_branch_result(then_branch, env)?;
                    let else_value =
                        self.known_history_offset_bool_branch_result(else_branch, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::Switch { selector, arms } => {
                self.known_history_offset_bool_switch_result(selector.as_deref(), arms, env)
            }
            pine_syntax::ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.known_history_offset_int_value_inner(from, env)?;
                self.known_history_offset_int_value_inner(to, env)?;
                if let Some(step) = step
                    && self.known_history_offset_int_value_inner(step, env)? == 0
                {
                    return None;
                }
                self.known_history_offset_bool_branch_result(body, env)
            }
            pine_syntax::ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.known_history_offset_for_in_branch_result(
                index,
                value,
                iterable,
                body,
                env,
                Self::known_history_offset_bool_branch_result,
            ),
            pine_syntax::ExprKind::Binary {
                op:
                    op @ (pine_syntax::BinaryOp::Eq
                    | pine_syntax::BinaryOp::NotEq
                    | pine_syntax::BinaryOp::Gt
                    | pine_syntax::BinaryOp::Gte
                    | pine_syntax::BinaryOp::Lt
                    | pine_syntax::BinaryOp::Lte),
                left,
                right,
            } => self.known_history_offset_comparison(*op, left, right, env),
            _ => None,
        }
    }

    fn known_history_offset_comparison(
        &self,
        op: pine_syntax::BinaryOp,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        if let Some(value) = self.known_history_offset_int_comparison(op, left, right, env) {
            return Some(value);
        }
        if let Some(value) = self.known_history_offset_numeric_comparison(op, left, right, env) {
            return Some(value);
        }
        if let Some(value) = self.known_history_offset_bool_comparison(op, left, right, env) {
            return Some(value);
        }
        if let Some(value) = self.known_history_offset_string_comparison(op, left, right, env) {
            return Some(value);
        }
        self.known_history_offset_color_comparison(op, left, right, env)
    }

    fn known_history_offset_int_comparison(
        &self,
        op: pine_syntax::BinaryOp,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let left = self.known_history_offset_int_value_inner(left, env)?;
        let right = self.known_history_offset_int_value_inner(right, env)?;
        Some(match op {
            pine_syntax::BinaryOp::Eq => left == right,
            pine_syntax::BinaryOp::NotEq => left != right,
            pine_syntax::BinaryOp::Gt => left > right,
            pine_syntax::BinaryOp::Gte => left >= right,
            pine_syntax::BinaryOp::Lt => left < right,
            pine_syntax::BinaryOp::Lte => left <= right,
            _ => return None,
        })
    }

    fn known_history_offset_numeric_comparison(
        &self,
        op: pine_syntax::BinaryOp,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let left = self.known_history_offset_numeric_value_inner(left, env)?;
        let right = self.known_history_offset_numeric_value_inner(right, env)?;
        Some(match op {
            pine_syntax::BinaryOp::Eq => left == right,
            pine_syntax::BinaryOp::NotEq => left != right,
            pine_syntax::BinaryOp::Gt => left > right,
            pine_syntax::BinaryOp::Gte => left >= right,
            pine_syntax::BinaryOp::Lt => left < right,
            pine_syntax::BinaryOp::Lte => left <= right,
            _ => return None,
        })
    }

    fn known_history_offset_bool_comparison(
        &self,
        op: pine_syntax::BinaryOp,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let left = self.known_history_offset_bool_value_inner(left, env)?;
        let right = self.known_history_offset_bool_value_inner(right, env)?;
        match op {
            pine_syntax::BinaryOp::Eq => Some(left == right),
            pine_syntax::BinaryOp::NotEq => Some(left != right),
            _ => None,
        }
    }

    fn known_history_offset_string_comparison(
        &self,
        op: pine_syntax::BinaryOp,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let left = self.known_history_offset_string_value_inner(left, env)?;
        let right = self.known_history_offset_string_value_inner(right, env)?;
        match op {
            pine_syntax::BinaryOp::Eq => Some(left == right),
            pine_syntax::BinaryOp::NotEq => Some(left != right),
            _ => None,
        }
    }

    fn known_history_offset_color_comparison(
        &self,
        op: pine_syntax::BinaryOp,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let left = self.known_history_offset_color_value_inner(left, env)?;
        let right = self.known_history_offset_color_value_inner(right, env)?;
        match op {
            pine_syntax::BinaryOp::Eq => Some(left == right),
            pine_syntax::BinaryOp::NotEq => Some(left != right),
            _ => None,
        }
    }

    fn known_history_offset_bool_branch_result(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let saved_locals = env.locals.clone();
        let result = self.known_history_offset_bool_branch_result_inner(statements, env);
        env.locals = saved_locals;
        result
    }

    fn known_history_offset_bool_branch_result_inner(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let (last, prefix) = statements.split_last()?;
        for statement in prefix {
            match &statement.kind {
                pine_syntax::StmtKind::Expr(_) => {}
                pine_syntax::StmtKind::Decl {
                    mode: pine_syntax::DeclMode::Normal,
                    name,
                    value,
                    ..
                } => {
                    env.locals.insert(name.clone(), value.clone());
                }
                pine_syntax::StmtKind::TupleDecl { names, value } => {
                    let pine_syntax::ExprKind::Tuple(values) = &value.kind else {
                        return None;
                    };
                    if names.len() != values.len() {
                        return None;
                    }
                    for (name, value) in names.iter().zip(values) {
                        env.locals.insert(name.clone(), value.clone());
                    }
                }
                pine_syntax::StmtKind::Reassign { name, .. } => {
                    env.locals.remove(name);
                }
                _ => return None,
            }
        }

        match &last.kind {
            pine_syntax::StmtKind::Expr(expr) => {
                self.known_history_offset_bool_value_inner(expr, env)
            }
            _ => None,
        }
    }

    fn known_history_offset_bool_switch_result(
        &self,
        selector: Option<&pine_syntax::Expr>,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        if let Some(selector) = selector {
            let Some(selector_key) = self.known_history_offset_switch_key(selector, env) else {
                return self.known_history_offset_bool_all_switch_results_with_default(arms, env);
            };
            for (index, arm) in arms.iter().enumerate() {
                match &arm.condition {
                    Some(condition) => match self.known_history_offset_switch_key(condition, env) {
                        Some(condition_key) => {
                            if condition_key == selector_key {
                                return self
                                    .known_history_offset_bool_switch_arm_result(&arm.result, env);
                            }
                        }
                        None => {
                            return self.known_history_offset_bool_all_switch_results_with_default(
                                &arms[index..],
                                env,
                            );
                        }
                    },
                    None => {
                        return self.known_history_offset_bool_switch_arm_result(&arm.result, env);
                    }
                }
            }
            return None;
        }

        for (index, arm) in arms.iter().enumerate() {
            match &arm.condition {
                Some(condition) => match self.known_history_offset_bool_value_inner(condition, env)
                {
                    Some(true) => {
                        return self.known_history_offset_bool_switch_arm_result(&arm.result, env);
                    }
                    Some(false) => {}
                    None => {
                        return self.known_history_offset_bool_all_switch_results_with_default(
                            &arms[index..],
                            env,
                        );
                    }
                },
                None => {
                    return self.known_history_offset_bool_switch_arm_result(&arm.result, env);
                }
            }
        }
        None
    }

    fn known_history_offset_bool_all_switch_results_with_default(
        &self,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        if !arms.iter().any(|arm| arm.condition.is_none()) {
            return None;
        }

        let mut expected = None;
        for arm in arms {
            let value = self.known_history_offset_bool_switch_arm_result(&arm.result, env)?;
            match expected {
                Some(expected) if expected != value => return None,
                Some(_) => {}
                None => expected = Some(value),
            }
        }
        expected
    }

    fn known_history_offset_bool_switch_arm_result(
        &self,
        result: &pine_syntax::SwitchArmResult,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        match result {
            pine_syntax::SwitchArmResult::Expr(expr) => {
                self.known_history_offset_bool_value_inner(expr, env)
            }
            pine_syntax::SwitchArmResult::Block(statements) => {
                self.known_history_offset_bool_branch_result(statements, env)
            }
        }
    }

    pub(super) fn known_history_offset_numeric_value_inner(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        self.known_const_numeric_value(expr)
            .or_else(|| self.known_history_offset_numeric_value_from_symbols(expr, env))
    }

    fn known_history_offset_numeric_value_from_symbols(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_numeric_value_inner(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if let Some(value) = self.const_numeric_symbols.get(&symbol.id) {
                    return Some(*value);
                }
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_numeric_value_inner(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Call { callee, args } => self
                .known_history_offset_call_value(callee, args, env)
                .and_then(crate::constant_values::ConstValue::as_numeric),
            pine_syntax::ExprKind::Unary {
                op: pine_syntax::UnaryOp::Plus,
                expr,
            } => self.known_history_offset_numeric_value_inner(expr, env),
            pine_syntax::ExprKind::Unary {
                op: pine_syntax::UnaryOp::Minus,
                expr,
            } => self
                .known_history_offset_numeric_value_inner(expr, env)
                .map(|value| -value),
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::Add,
                left,
                right,
            } => Some(
                self.known_history_offset_numeric_value_inner(left, env)?
                    + self.known_history_offset_numeric_value_inner(right, env)?,
            ),
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::Sub,
                left,
                right,
            } => Some(
                self.known_history_offset_numeric_value_inner(left, env)?
                    - self.known_history_offset_numeric_value_inner(right, env)?,
            ),
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::Mul,
                left,
                right,
            } => Some(
                self.known_history_offset_numeric_value_inner(left, env)?
                    * self.known_history_offset_numeric_value_inner(right, env)?,
            ),
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::Div,
                left,
                right,
            } => {
                let value = self.known_history_offset_numeric_value_inner(left, env)?
                    / self.known_history_offset_numeric_value_inner(right, env)?;
                value.is_finite().then_some(value)
            }
            pine_syntax::ExprKind::Binary {
                op: pine_syntax::BinaryOp::Mod,
                left,
                right,
            } => {
                let value = self.known_history_offset_numeric_value_inner(left, env)?
                    % self.known_history_offset_numeric_value_inner(right, env)?;
                value.is_finite().then_some(value)
            }
            pine_syntax::ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_numeric_value_inner(then_expr, env),
                Some(false) => self.known_history_offset_numeric_value_inner(else_expr, env),
                None => {
                    let then_value =
                        self.known_history_offset_numeric_value_inner(then_expr, env)?;
                    let else_value =
                        self.known_history_offset_numeric_value_inner(else_expr, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_numeric_branch_result(then_branch, env),
                Some(false) => self.known_history_offset_numeric_branch_result(else_branch, env),
                None => {
                    let then_value =
                        self.known_history_offset_numeric_branch_result(then_branch, env)?;
                    let else_value =
                        self.known_history_offset_numeric_branch_result(else_branch, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::Switch { selector, arms } => {
                self.known_history_offset_numeric_switch_result(selector.as_deref(), arms, env)
            }
            pine_syntax::ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.known_history_offset_int_value_inner(from, env)?;
                self.known_history_offset_int_value_inner(to, env)?;
                if let Some(step) = step
                    && self.known_history_offset_int_value_inner(step, env)? == 0
                {
                    return None;
                }
                self.known_history_offset_numeric_branch_result(body, env)
            }
            pine_syntax::ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.known_history_offset_for_in_branch_result(
                index,
                value,
                iterable,
                body,
                env,
                Self::known_history_offset_numeric_branch_result,
            ),
            _ => None,
        }
    }

    fn known_history_offset_numeric_branch_result(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        let saved_locals = env.locals.clone();
        let result = self.known_history_offset_numeric_branch_result_inner(statements, env);
        env.locals = saved_locals;
        result
    }

    fn known_history_offset_numeric_branch_result_inner(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        let (last, prefix) = statements.split_last()?;
        for statement in prefix {
            self.apply_history_offset_local_statement(statement, env)?;
        }

        match &last.kind {
            pine_syntax::StmtKind::Expr(expr) => {
                self.known_history_offset_numeric_value_inner(expr, env)
            }
            _ => None,
        }
    }

    fn known_history_offset_numeric_switch_result(
        &self,
        selector: Option<&pine_syntax::Expr>,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        if let Some(selector) = selector {
            let Some(selector_key) = self.known_history_offset_switch_key(selector, env) else {
                return self
                    .known_history_offset_numeric_all_switch_results_with_default(arms, env);
            };
            for (index, arm) in arms.iter().enumerate() {
                match &arm.condition {
                    Some(condition) => match self.known_history_offset_switch_key(condition, env) {
                        Some(condition_key) => {
                            if condition_key == selector_key {
                                return self.known_history_offset_numeric_switch_arm_result(
                                    &arm.result,
                                    env,
                                );
                            }
                        }
                        None => {
                            return self
                                .known_history_offset_numeric_all_switch_results_with_default(
                                    &arms[index..],
                                    env,
                                );
                        }
                    },
                    None => {
                        return self
                            .known_history_offset_numeric_switch_arm_result(&arm.result, env);
                    }
                }
            }
            return None;
        }

        for (index, arm) in arms.iter().enumerate() {
            match &arm.condition {
                Some(condition) => match self.known_history_offset_bool_value_inner(condition, env)
                {
                    Some(true) => {
                        return self
                            .known_history_offset_numeric_switch_arm_result(&arm.result, env);
                    }
                    Some(false) => {}
                    None => {
                        return self.known_history_offset_numeric_all_switch_results_with_default(
                            &arms[index..],
                            env,
                        );
                    }
                },
                None => {
                    return self.known_history_offset_numeric_switch_arm_result(&arm.result, env);
                }
            }
        }
        None
    }

    fn known_history_offset_numeric_all_switch_results_with_default(
        &self,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        if !arms.iter().any(|arm| arm.condition.is_none()) {
            return None;
        }

        let mut expected = None;
        for arm in arms {
            let value = self.known_history_offset_numeric_switch_arm_result(&arm.result, env)?;
            match expected {
                Some(expected) if expected != value => return None,
                Some(_) => {}
                None => expected = Some(value),
            }
        }
        expected
    }

    fn known_history_offset_numeric_switch_arm_result(
        &self,
        result: &pine_syntax::SwitchArmResult,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<f64> {
        match result {
            pine_syntax::SwitchArmResult::Expr(expr) => {
                self.known_history_offset_numeric_value_inner(expr, env)
            }
            pine_syntax::SwitchArmResult::Block(statements) => {
                self.known_history_offset_numeric_branch_result(statements, env)
            }
        }
    }

    fn known_history_offset_string_value_inner(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        self.known_const_string_value(expr)
            .or_else(|| self.known_history_offset_string_value_from_symbols(expr, env))
    }

    fn known_history_offset_string_value_from_symbols(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_string_value_inner(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if let Some(value) = self.const_string_symbols.get(&symbol.id) {
                    return Some(value.clone());
                }
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_string_value_inner(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_string_value_inner(then_expr, env),
                Some(false) => self.known_history_offset_string_value_inner(else_expr, env),
                None => {
                    let then_value =
                        self.known_history_offset_string_value_inner(then_expr, env)?;
                    let else_value =
                        self.known_history_offset_string_value_inner(else_expr, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_string_branch_result(then_branch, env),
                Some(false) => self.known_history_offset_string_branch_result(else_branch, env),
                None => {
                    let then_value =
                        self.known_history_offset_string_branch_result(then_branch, env)?;
                    let else_value =
                        self.known_history_offset_string_branch_result(else_branch, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::Switch { selector, arms } => {
                self.known_history_offset_string_switch_result(selector.as_deref(), arms, env)
            }
            pine_syntax::ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.known_history_offset_int_value_inner(from, env)?;
                self.known_history_offset_int_value_inner(to, env)?;
                if let Some(step) = step
                    && self.known_history_offset_int_value_inner(step, env)? == 0
                {
                    return None;
                }
                self.known_history_offset_string_branch_result(body, env)
            }
            pine_syntax::ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.known_history_offset_for_in_branch_result(
                index,
                value,
                iterable,
                body,
                env,
                Self::known_history_offset_string_branch_result,
            ),
            _ => None,
        }
    }

    fn known_history_offset_string_branch_result(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        let saved_locals = env.locals.clone();
        let result = self.known_history_offset_string_branch_result_inner(statements, env);
        env.locals = saved_locals;
        result
    }

    fn known_history_offset_string_branch_result_inner(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        let (last, prefix) = statements.split_last()?;
        for statement in prefix {
            self.apply_history_offset_local_statement(statement, env)?;
        }

        match &last.kind {
            pine_syntax::StmtKind::Expr(expr) => {
                self.known_history_offset_string_value_inner(expr, env)
            }
            _ => None,
        }
    }

    fn known_history_offset_string_switch_result(
        &self,
        selector: Option<&pine_syntax::Expr>,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        if let Some(selector) = selector {
            let Some(selector_key) = self.known_history_offset_switch_key(selector, env) else {
                return self.known_history_offset_string_all_switch_results_with_default(arms, env);
            };
            for (index, arm) in arms.iter().enumerate() {
                match &arm.condition {
                    Some(condition) => match self.known_history_offset_switch_key(condition, env) {
                        Some(condition_key) => {
                            if condition_key == selector_key {
                                return self.known_history_offset_string_switch_arm_result(
                                    &arm.result,
                                    env,
                                );
                            }
                        }
                        None => {
                            return self
                                .known_history_offset_string_all_switch_results_with_default(
                                    &arms[index..],
                                    env,
                                );
                        }
                    },
                    None => {
                        return self
                            .known_history_offset_string_switch_arm_result(&arm.result, env);
                    }
                }
            }
            return None;
        }

        for (index, arm) in arms.iter().enumerate() {
            match &arm.condition {
                Some(condition) => match self.known_history_offset_bool_value_inner(condition, env)
                {
                    Some(true) => {
                        return self
                            .known_history_offset_string_switch_arm_result(&arm.result, env);
                    }
                    Some(false) => {}
                    None => {
                        return self.known_history_offset_string_all_switch_results_with_default(
                            &arms[index..],
                            env,
                        );
                    }
                },
                None => {
                    return self.known_history_offset_string_switch_arm_result(&arm.result, env);
                }
            }
        }
        None
    }

    fn known_history_offset_string_all_switch_results_with_default(
        &self,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        if !arms.iter().any(|arm| arm.condition.is_none()) {
            return None;
        }

        let mut expected = None;
        for arm in arms {
            let value = self.known_history_offset_string_switch_arm_result(&arm.result, env)?;
            match &expected {
                Some(expected) if *expected != value => return None,
                Some(_) => {}
                None => expected = Some(value),
            }
        }
        expected
    }

    fn known_history_offset_string_switch_arm_result(
        &self,
        result: &pine_syntax::SwitchArmResult,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<String> {
        match result {
            pine_syntax::SwitchArmResult::Expr(expr) => {
                self.known_history_offset_string_value_inner(expr, env)
            }
            pine_syntax::SwitchArmResult::Block(statements) => {
                self.known_history_offset_string_branch_result(statements, env)
            }
        }
    }

    fn known_history_offset_color_value_inner(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        self.known_const_color_value(expr)
            .or_else(|| self.known_history_offset_color_value_from_symbols(expr, env))
    }

    fn known_history_offset_color_value_from_symbols(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_color_value_inner(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if let Some(value) = self.const_color_symbols.get(&symbol.id) {
                    return Some(*value);
                }
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_color_value_inner(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_color_value_inner(then_expr, env),
                Some(false) => self.known_history_offset_color_value_inner(else_expr, env),
                None => {
                    let then_value = self.known_history_offset_color_value_inner(then_expr, env)?;
                    let else_value = self.known_history_offset_color_value_inner(else_expr, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => match self.known_history_offset_bool_value_inner(condition, env) {
                Some(true) => self.known_history_offset_color_branch_result(then_branch, env),
                Some(false) => self.known_history_offset_color_branch_result(else_branch, env),
                None => {
                    let then_value =
                        self.known_history_offset_color_branch_result(then_branch, env)?;
                    let else_value =
                        self.known_history_offset_color_branch_result(else_branch, env)?;
                    (then_value == else_value).then_some(then_value)
                }
            },
            pine_syntax::ExprKind::Switch { selector, arms } => {
                self.known_history_offset_color_switch_result(selector.as_deref(), arms, env)
            }
            pine_syntax::ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.known_history_offset_int_value_inner(from, env)?;
                self.known_history_offset_int_value_inner(to, env)?;
                if let Some(step) = step
                    && self.known_history_offset_int_value_inner(step, env)? == 0
                {
                    return None;
                }
                self.known_history_offset_color_branch_result(body, env)
            }
            pine_syntax::ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.known_history_offset_for_in_branch_result(
                index,
                value,
                iterable,
                body,
                env,
                Self::known_history_offset_color_branch_result,
            ),
            _ => None,
        }
    }

    fn known_history_offset_color_branch_result(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        let saved_locals = env.locals.clone();
        let result = self.known_history_offset_color_branch_result_inner(statements, env);
        env.locals = saved_locals;
        result
    }

    fn known_history_offset_color_branch_result_inner(
        &self,
        statements: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        let (last, prefix) = statements.split_last()?;
        for statement in prefix {
            self.apply_history_offset_local_statement(statement, env)?;
        }

        match &last.kind {
            pine_syntax::StmtKind::Expr(expr) => {
                self.known_history_offset_color_value_inner(expr, env)
            }
            _ => None,
        }
    }

    fn known_history_offset_color_switch_result(
        &self,
        selector: Option<&pine_syntax::Expr>,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        if let Some(selector) = selector {
            let Some(selector_key) = self.known_history_offset_switch_key(selector, env) else {
                return self.known_history_offset_color_all_switch_results_with_default(arms, env);
            };
            for (index, arm) in arms.iter().enumerate() {
                match &arm.condition {
                    Some(condition) => match self.known_history_offset_switch_key(condition, env) {
                        Some(condition_key) => {
                            if condition_key == selector_key {
                                return self.known_history_offset_color_switch_arm_result(
                                    &arm.result,
                                    env,
                                );
                            }
                        }
                        None => {
                            return self
                                .known_history_offset_color_all_switch_results_with_default(
                                    &arms[index..],
                                    env,
                                );
                        }
                    },
                    None => {
                        return self.known_history_offset_color_switch_arm_result(&arm.result, env);
                    }
                }
            }
            return None;
        }

        for (index, arm) in arms.iter().enumerate() {
            match &arm.condition {
                Some(condition) => match self.known_history_offset_bool_value_inner(condition, env)
                {
                    Some(true) => {
                        return self.known_history_offset_color_switch_arm_result(&arm.result, env);
                    }
                    Some(false) => {}
                    None => {
                        return self.known_history_offset_color_all_switch_results_with_default(
                            &arms[index..],
                            env,
                        );
                    }
                },
                None => {
                    return self.known_history_offset_color_switch_arm_result(&arm.result, env);
                }
            }
        }
        None
    }

    fn known_history_offset_color_all_switch_results_with_default(
        &self,
        arms: &[pine_syntax::SwitchArm],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        if !arms.iter().any(|arm| arm.condition.is_none()) {
            return None;
        }

        let mut expected = None;
        for arm in arms {
            let value = self.known_history_offset_color_switch_arm_result(&arm.result, env)?;
            match expected {
                Some(expected) if expected != value => return None,
                Some(_) => {}
                None => expected = Some(value),
            }
        }
        expected
    }

    fn known_history_offset_color_switch_arm_result(
        &self,
        result: &pine_syntax::SwitchArmResult,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<u32> {
        match result {
            pine_syntax::SwitchArmResult::Expr(expr) => {
                self.known_history_offset_color_value_inner(expr, env)
            }
            pine_syntax::SwitchArmResult::Block(statements) => {
                self.known_history_offset_color_branch_result(statements, env)
            }
        }
    }

    fn apply_history_offset_local_statement(
        &self,
        statement: &pine_syntax::Stmt,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<()> {
        match &statement.kind {
            pine_syntax::StmtKind::Expr(_) => {}
            pine_syntax::StmtKind::Decl {
                mode: pine_syntax::DeclMode::Normal,
                name,
                value,
                ..
            } => {
                env.locals.insert(name.clone(), value.clone());
            }
            pine_syntax::StmtKind::TupleDecl { names, value } => {
                let pine_syntax::ExprKind::Tuple(values) = &value.kind else {
                    return None;
                };
                if names.len() != values.len() {
                    return None;
                }
                for (name, value) in names.iter().zip(values) {
                    env.locals.insert(name.clone(), value.clone());
                }
            }
            pine_syntax::StmtKind::Reassign { name, .. } => {
                env.locals.remove(name);
            }
            _ => return None,
        }
        Some(())
    }
}
