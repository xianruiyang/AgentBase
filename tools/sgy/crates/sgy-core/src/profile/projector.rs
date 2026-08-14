use serde_json::{Map, Value};

use crate::codec::SourceRecord;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecordShape {
    Match,
    Finding,
    Unknown,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ProjectedRecord {
    pub ordinal: u64,
    pub shape: RecordShape,
    pub value: Value,
}

impl ProjectedRecord {
    #[must_use]
    pub const fn is_opaque_unknown(&self) -> bool {
        matches!(self.shape, RecordShape::Unknown)
    }
}

/// Compresses one recognized Token-Safe match/finding into a display-only,
/// 0-based `file:start_line:start_column-end_line:end_column` locator.
/// Opaque records remain explicit unknown stubs so completeness is never
/// inferred from a shape that sgy could not interpret.
#[must_use]
pub fn project_location_record(token_safe: &ProjectedRecord) -> ProjectedRecord {
    let value = if token_safe.is_opaque_unknown() {
        token_safe.value.clone()
    } else {
        location_value(&token_safe.value).unwrap_or_else(|| {
            let mut stub = Map::new();
            stub.insert("_sgy_result".to_owned(), Value::from(token_safe.ordinal));
            stub.insert("_sgy_unknown".to_owned(), Value::Bool(true));
            stub.insert("json_type".to_owned(), Value::String("object".to_owned()));
            Value::Object(stub)
        })
    };
    ProjectedRecord {
        ordinal: token_safe.ordinal,
        shape: token_safe.shape,
        value,
    }
}

#[must_use]
pub fn project_token_safe(ordinal: u64, native: &Value) -> ProjectedRecord {
    let Some(mapping) = native.as_object() else {
        return unknown_record(ordinal, native);
    };
    let Some(mut projected) = project_match_base(mapping) else {
        return unknown_record(ordinal, native);
    };

    let finding_marker = ["ruleId", "severity", "message", "note", "labels"]
        .iter()
        .any(|field| mapping.contains_key(*field));
    let shape = if finding_marker {
        let (Some(rule_id), Some(severity), Some(message)) = (
            mapping.get("ruleId").and_then(Value::as_str),
            mapping.get("severity").and_then(Value::as_str),
            mapping.get("message").and_then(Value::as_str),
        ) else {
            return unknown_record(ordinal, native);
        };
        projected.insert("ruleId".to_owned(), Value::String(rule_id.to_owned()));
        projected.insert("severity".to_owned(), Value::String(severity.to_owned()));
        projected.insert("message".to_owned(), Value::String(message.to_owned()));
        insert_string(&mut projected, mapping, "note");
        insert_string(&mut projected, mapping, "language");
        if let Some(labels) = mapping.get("labels").and_then(project_labels) {
            projected.insert("labels".to_owned(), labels);
        }
        RecordShape::Finding
    } else {
        RecordShape::Match
    };

    ProjectedRecord {
        ordinal,
        shape,
        value: Value::Object(projected),
    }
}

#[must_use]
pub fn project_token_safe_record(record: &SourceRecord) -> ProjectedRecord {
    project_token_safe(record.ordinal, &record.value)
}

/// Projects one `runs[].results[]` SARIF result into the same compact finding shape used by
/// native ast-grep JSON findings. SARIF regions are 1-based, so they are normalized to the
/// 0-based, end-exclusive range convention exposed by the rest of the Token-Safe profile.
#[must_use]
pub fn project_sarif_token_safe_record(record: &SourceRecord) -> ProjectedRecord {
    project_sarif_token_safe(record.ordinal, &record.value)
}

#[must_use]
pub fn project_sarif_token_safe(ordinal: u64, native: &Value) -> ProjectedRecord {
    let Some(mapping) = native.as_object() else {
        return unknown_record(ordinal, native);
    };
    let (Some(rule_id), Some(severity), Some(message)) = (
        mapping.get("ruleId").and_then(Value::as_str),
        mapping.get("level").and_then(Value::as_str),
        mapping
            .get("message")
            .and_then(Value::as_object)
            .and_then(|value| value.get("text"))
            .and_then(Value::as_str),
    ) else {
        return unknown_record(ordinal, native);
    };
    let Some((file, range, text)) = project_sarif_location(mapping) else {
        return unknown_record(ordinal, native);
    };

    let mut projected = Map::new();
    projected.insert("file".to_owned(), Value::String(file.to_owned()));
    projected.insert("range".to_owned(), range);
    projected.insert("text".to_owned(), Value::String(text.to_owned()));
    projected.insert("ruleId".to_owned(), Value::String(rule_id.to_owned()));
    projected.insert("severity".to_owned(), Value::String(severity.to_owned()));
    projected.insert("message".to_owned(), Value::String(message.to_owned()));
    if let Some(replacement) = project_sarif_replacement(mapping, file) {
        projected.insert(
            "replacement".to_owned(),
            Value::String(replacement.to_owned()),
        );
    }
    ProjectedRecord {
        ordinal,
        shape: RecordShape::Finding,
        value: Value::Object(projected),
    }
}

fn project_sarif_location(native: &Map<String, Value>) -> Option<(&str, Value, &str)> {
    let physical = native
        .get("locations")?
        .as_array()?
        .first()?
        .get("physicalLocation")?
        .as_object()?;
    let file = physical.get("artifactLocation")?.get("uri")?.as_str()?;
    let region = physical.get("region")?.as_object()?;
    let text = region.get("snippet")?.get("text")?.as_str()?;
    let start_line = sarif_coordinate(region.get("startLine")?)?;
    let start_column = sarif_coordinate(region.get("startColumn")?)?;
    let end_line = sarif_coordinate(region.get("endLine")?)?;
    let end_column = sarif_coordinate(region.get("endColumn")?)?;
    let range = serde_json::json!({
        "start": {"line": start_line, "column": start_column},
        "end": {"line": end_line, "column": end_column},
    });
    Some((file, range, text))
}

fn sarif_coordinate(value: &Value) -> Option<u64> {
    value.as_u64()?.checked_sub(1)
}

fn project_sarif_replacement<'a>(native: &'a Map<String, Value>, file: &str) -> Option<&'a str> {
    let fixes = native.get("fixes")?.as_array()?;
    if fixes.len() != 1 {
        return None;
    }
    let changes = fixes[0].get("artifactChanges")?.as_array()?;
    if changes.len() != 1 || changes[0].get("artifactLocation")?.get("uri")?.as_str()? != file {
        return None;
    }
    let replacements = changes[0].get("replacements")?.as_array()?;
    if replacements.len() != 1 {
        return None;
    }
    replacements[0]
        .get("insertedContent")?
        .get("text")?
        .as_str()
}

fn project_match_base(native: &Map<String, Value>) -> Option<Map<String, Value>> {
    let file = native.get("file")?.as_str()?;
    let text = native.get("text")?.as_str()?;
    let range = project_range(native.get("range")?)?;
    let mut projected = Map::new();
    projected.insert("file".to_owned(), Value::String(file.to_owned()));
    projected.insert("range".to_owned(), range);
    projected.insert("text".to_owned(), Value::String(text.to_owned()));
    if let Some(meta_variables) = native.get("metaVariables").and_then(project_meta_variables) {
        projected.insert("metaVariables".to_owned(), meta_variables);
    }
    insert_string(&mut projected, native, "replacement");
    Some(projected)
}

fn project_range(value: &Value) -> Option<Value> {
    let native = value.as_object()?;
    let mut projected = Map::new();
    projected.insert("start".to_owned(), project_position(native.get("start")?)?);
    projected.insert("end".to_owned(), project_position(native.get("end")?)?);
    Some(Value::Object(projected))
}

fn project_position(value: &Value) -> Option<Value> {
    let native = value.as_object()?;
    let line = native.get("line")?.as_u64()?;
    let column = native.get("column")?.as_u64()?;
    let mut projected = Map::new();
    projected.insert("line".to_owned(), Value::from(line));
    projected.insert("column".to_owned(), Value::from(column));
    Some(Value::Object(projected))
}

fn location_value(value: &Value) -> Option<Value> {
    let native = value.as_object()?;
    let file = native.get("file")?.as_str()?;
    let range = native.get("range")?.as_object()?;
    let start = range.get("start")?.as_object()?;
    let end = range.get("end")?.as_object()?;
    let start_line = start.get("line")?.as_u64()?;
    let start_column = start.get("column")?.as_u64()?;
    let end_line = end.get("line")?.as_u64()?;
    let end_column = end.get("column")?.as_u64()?;
    Some(Value::String(format!(
        "{file}:{start_line}:{start_column}-{end_line}:{end_column}"
    )))
}

fn project_meta_variables(value: &Value) -> Option<Value> {
    let native_groups = value.as_object()?;
    let mut groups = Map::new();
    for (group_name, group_value) in native_groups {
        let Some(native_captures) = group_value.as_object() else {
            continue;
        };
        let mut captures = Map::new();
        for (capture_name, capture_value) in native_captures {
            if let Some(capture) = project_capture(capture_value) {
                captures.insert(capture_name.clone(), capture);
            }
        }
        if !captures.is_empty() {
            groups.insert(group_name.clone(), Value::Object(captures));
        }
    }
    (!groups.is_empty()).then_some(Value::Object(groups))
}

fn project_capture(value: &Value) -> Option<Value> {
    match value {
        Value::Object(native) => {
            let text = native.get("text")?.as_str()?;
            let mut projected = Map::new();
            projected.insert("text".to_owned(), Value::String(text.to_owned()));
            if native.get("_sgy_text_truncated").and_then(Value::as_bool) == Some(true) {
                projected.insert("_sgy_text_truncated".to_owned(), Value::Bool(true));
            }
            Some(Value::Object(projected))
        }
        Value::Array(native) => {
            let projected: Vec<Value> = native.iter().filter_map(project_capture).collect();
            (!projected.is_empty()).then_some(Value::Array(projected))
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => None,
    }
}

fn project_labels(value: &Value) -> Option<Value> {
    let native = value.as_array()?;
    let projected: Vec<Value> = native.iter().filter_map(clean_label_value).collect();
    (!projected.is_empty()).then_some(Value::Array(projected))
}

fn clean_label_value(value: &Value) -> Option<Value> {
    match value {
        Value::Null => None,
        Value::Array(native) => {
            let projected: Vec<Value> = native.iter().filter_map(clean_label_value).collect();
            (!projected.is_empty()).then_some(Value::Array(projected))
        }
        Value::Object(native) => {
            let mut projected = Map::new();
            for (key, child) in native {
                if matches!(
                    key.as_str(),
                    "byteOffset" | "lines" | "charCount" | "replacementOffsets"
                ) {
                    continue;
                }
                if let Some(child) = clean_label_value(child) {
                    projected.insert(key.clone(), child);
                }
            }
            (!projected.is_empty()).then_some(Value::Object(projected))
        }
        Value::Bool(_) | Value::Number(_) | Value::String(_) => Some(value.clone()),
    }
}

fn insert_string(target: &mut Map<String, Value>, source: &Map<String, Value>, field: &str) {
    if let Some(value) = source.get(field).and_then(Value::as_str) {
        target.insert(field.to_owned(), Value::String(value.to_owned()));
    }
}

fn unknown_record(ordinal: u64, native: &Value) -> ProjectedRecord {
    let mut stub = Map::new();
    stub.insert("_sgy_result".to_owned(), Value::from(ordinal));
    stub.insert("_sgy_unknown".to_owned(), Value::Bool(true));
    stub.insert(
        "json_type".to_owned(),
        Value::String(json_type(native).to_owned()),
    );
    ProjectedRecord {
        ordinal,
        shape: RecordShape::Unknown,
        value: Value::Object(stub),
    }
}

const fn json_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}
