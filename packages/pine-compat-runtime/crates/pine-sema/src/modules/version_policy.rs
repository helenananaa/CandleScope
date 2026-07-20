use pine_syntax::Diagnostic;

use crate::legacy::{LanguageSelection, SourcePolicy};

use super::imports::imports_in_program;
use super::model::ModuleInfo;

pub(super) fn validate_language_versions(
    modules: &[ModuleInfo],
    root_policy: &SourcePolicy,
    implicit_dialect: crate::PineDialect,
    inherit_root_for_implicit_libraries: bool,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if let Some(diagnostic) = root_policy.language.unsupported_diagnostic() {
        diagnostics.push(diagnostic);
    }

    let root_imports = imports_in_program(&modules[0].program);
    for module in modules.iter().skip(1) {
        let module_implicit_dialect = if inherit_root_for_implicit_libraries {
            root_policy.language.dialect.unwrap_or(implicit_dialect)
        } else {
            implicit_dialect
        };
        let selection =
            LanguageSelection::from_program_with_implicit(&module.program, module_implicit_dialect);
        let diagnostic_span = module
            .key
            .as_deref()
            .and_then(|key| root_imports.iter().find(|import| import.key == key))
            .map_or(root_policy.language.span, |import| import.span);

        if selection.dialect.is_none() {
            diagnostics.push(Diagnostic::error(
                "E_LANGUAGE_VERSION_UNSUPPORTED",
                format!(
                    "library `{}` selects unsupported Pine language version {}",
                    module.key.as_deref().unwrap_or("<unknown>"),
                    selection.raw_version
                ),
                diagnostic_span,
            ));
            continue;
        }

        if let (Some(root_dialect), Some(module_dialect)) =
            (root_policy.language.dialect, selection.dialect)
            && root_dialect != module_dialect
        {
            diagnostics.push(Diagnostic::error(
                "E_LANGUAGE_VERSION_CONFLICT",
                format!(
                    "root {} source cannot use library `{}` declared as {}; root and library language versions must match",
                    root_dialect.name(),
                    module.key.as_deref().unwrap_or("<unknown>"),
                    module_dialect.name()
                ),
                diagnostic_span,
            ));
        }
    }
}
