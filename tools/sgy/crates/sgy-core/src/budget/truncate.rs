use serde_json::{Map, Value};

use crate::profile::ProjectedRecord;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RecoveryField {
    Note,
    Labels,
    Message,
    Replacement,
}

impl RecoveryField {
    const fn field(self) -> &'static str {
        match self {
            Self::Note => "note",
            Self::Labels => "labels",
            Self::Message => "message",
            Self::Replacement => "replacement",
        }
    }

    const fn marker(self) -> &'static str {
        match self {
            Self::Note => "_sgy_note_truncated",
            Self::Labels => "_sgy_labels_truncated",
            Self::Message => "_sgy_message_truncated",
            Self::Replacement => "_sgy_replacement_truncated",
        }
    }
}

pub(crate) fn apply_preview_cap(records: &mut [ProjectedRecord], cap: usize) {
    for record in records {
        let Some(root) = record.value.as_object_mut() else {
            continue;
        };
        let mut truncated = truncate_string_field(root, "text", cap, "_sgy_text_truncated");
        if let Some(meta_variables) = root.get_mut("metaVariables") {
            truncated |= truncate_capture_tree(meta_variables, cap);
        }
        if truncated {
            ensure_result_id(root, record.ordinal);
        }
    }
}

pub(crate) fn max_preview_chars(records: &[ProjectedRecord]) -> usize {
    records
        .iter()
        .map(|record| max_preview_in_value(&record.value))
        .max()
        .unwrap_or(0)
}

pub(crate) fn apply_recovery_cap(
    records: &mut [ProjectedRecord],
    field: RecoveryField,
    cap: usize,
) {
    for record in records {
        let Some(root) = record.value.as_object_mut() else {
            continue;
        };
        let truncated = if field == RecoveryField::Labels {
            truncate_labels_field(root, cap, field.marker())
        } else {
            truncate_string_field(root, field.field(), cap, field.marker())
        };
        if truncated {
            ensure_result_id(root, record.ordinal);
        }
    }
}

pub(crate) fn max_recovery_units(records: &[ProjectedRecord], field: RecoveryField) -> usize {
    records
        .iter()
        .filter_map(|record| record.value.as_object())
        .filter_map(|root| root.get(field.field()))
        .map(|value| match (field, value) {
            (RecoveryField::Labels, Value::Array(items)) => items.len(),
            (RecoveryField::Labels, Value::Object(mapping)) => mapping.len(),
            (_, Value::String(text)) => text.chars().count(),
            _ => 0,
        })
        .max()
        .unwrap_or(0)
}

pub(crate) fn count_truncation_markers(records: &[ProjectedRecord]) -> u64 {
    records
        .iter()
        .map(|record| count_markers_in_value(&record.value))
        .sum()
}

fn truncate_capture_tree(value: &mut Value, cap: usize) -> bool {
    match value {
        Value::Object(mapping) => {
            let mut truncated = false;
            if mapping.get("text").is_some_and(Value::is_string) {
                truncated |= truncate_string_field(mapping, "text", cap, "_sgy_text_truncated");
            } else {
                for child in mapping.values_mut() {
                    truncated |= truncate_capture_tree(child, cap);
                }
            }
            truncated
        }
        Value::Array(items) => items.iter_mut().fold(false, |changed, item| {
            changed | truncate_capture_tree(item, cap)
        }),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => false,
    }
}

fn truncate_string_field(
    mapping: &mut Map<String, Value>,
    field: &str,
    cap: usize,
    marker: &str,
) -> bool {
    let Some(Value::String(text)) = mapping.get_mut(field) else {
        return false;
    };
    if !truncate_string(text, cap) {
        return false;
    }
    mapping.insert(marker.to_owned(), Value::Bool(true));
    true
}

fn truncate_labels_field(mapping: &mut Map<String, Value>, cap: usize, marker: &str) -> bool {
    let Some(labels) = mapping.get_mut("labels") else {
        return false;
    };
    let truncated = match labels {
        Value::Array(items) if items.len() > cap => {
            items.truncate(cap);
            true
        }
        Value::Object(items) if items.len() > cap => {
            let remove: Vec<String> = items.keys().skip(cap).cloned().collect();
            for key in remove {
                items.remove(&key);
            }
            true
        }
        _ => false,
    };
    if truncated {
        mapping.insert(marker.to_owned(), Value::Bool(true));
    }
    truncated
}

fn truncate_string(text: &mut String, cap: usize) -> bool {
    let Some((byte_offset, _)) = text.char_indices().nth(cap) else {
        return false;
    };
    text.truncate(byte_offset);
    true
}

fn ensure_result_id(root: &mut Map<String, Value>, ordinal: u64) {
    root.insert("_sgy_result".to_owned(), Value::from(ordinal));
}

fn max_preview_in_value(value: &Value) -> usize {
    let Some(root) = value.as_object() else {
        return 0;
    };
    let top = root
        .get("text")
        .and_then(Value::as_str)
        .map(|text| text.chars().count())
        .unwrap_or(0);
    let captures = root
        .get("metaVariables")
        .map(max_capture_chars)
        .unwrap_or(0);
    top.max(captures)
}

fn max_capture_chars(value: &Value) -> usize {
    match value {
        Value::Object(mapping) => {
            if let Some(text) = mapping.get("text").and_then(Value::as_str) {
                text.chars().count()
            } else {
                mapping.values().map(max_capture_chars).max().unwrap_or(0)
            }
        }
        Value::Array(items) => items.iter().map(max_capture_chars).max().unwrap_or(0),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => 0,
    }
}

fn count_markers_in_value(value: &Value) -> u64 {
    match value {
        Value::Object(mapping) => mapping
            .iter()
            .map(|(key, child)| {
                u64::from(
                    key.starts_with("_sgy_")
                        && key.ends_with("_truncated")
                        && child.as_bool() == Some(true),
                ) + count_markers_in_value(child)
            })
            .sum(),
        Value::Array(items) => items.iter().map(count_markers_in_value).sum(),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => 0,
    }
}
