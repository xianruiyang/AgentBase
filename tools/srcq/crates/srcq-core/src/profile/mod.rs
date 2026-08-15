//! Pure record projection for model-context profiles.

mod paths;
mod projector;

pub use paths::{FieldPathError, FieldPaths};
pub use projector::{
    project_location_record, project_sarif_token_safe, project_sarif_token_safe_record,
    project_token_safe, project_token_safe_record, ProjectedRecord, RecordShape,
};

use serde_json::Value;

/// Applies custom keep/prune semantics without mutating either source value.
///
/// A present keep set selects directly from the native record. Without keep,
/// pruning starts from the Token-Safe projection. Opaque unknown stubs are
/// retained intact because their locator and type markers are inseparable.
#[must_use]
pub fn project_custom(
    native: &Value,
    token_safe: &ProjectedRecord,
    keep: Option<&FieldPaths>,
    prune: &FieldPaths,
) -> Value {
    let mut selected = match keep {
        Some(paths) => paths.select(native),
        None => token_safe.value.clone(),
    };
    if !(keep.is_none() && token_safe.shape == RecordShape::Unknown) {
        prune.prune(&mut selected);
    }
    selected
}

/// Custom projection variant that preserves the source ordinal and native
/// shape classification for later budgeting and aggregation.
#[must_use]
pub fn project_custom_record(
    native: &Value,
    token_safe: &ProjectedRecord,
    keep: Option<&FieldPaths>,
    prune: &FieldPaths,
) -> ProjectedRecord {
    ProjectedRecord {
        ordinal: token_safe.ordinal,
        shape: token_safe.shape,
        value: project_custom(native, token_safe, keep, prune),
    }
}
