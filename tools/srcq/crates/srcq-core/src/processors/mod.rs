//! Safe, deterministic post-processing for srcq YAML streams and verified cache values.

mod combine;
mod external;

pub use combine::{
    jsonl_to_yaml, write_jsonl_value, yaml_to_jsonl, CollectionBuilder, CollectionOperation,
    CollectionSource, ConflictPolicy, IDENTITY_SCHEMA,
};

use std::{
    collections::BTreeMap,
    io::{self, BufRead, Write},
};

use serde_json::{json, Map, Value};
use thiserror::Error;

use crate::{
    codec::{parse_yaml_documents_with_limits, write_yaml_document, CodecError, YamlParseLimits},
    profile::{FieldPathError, FieldPaths},
};

pub const VALIDATE_SCHEMA: &str = "sgy.process.validate/v1";
pub const COUNT_SCHEMA: &str = "sgy.process.count/v1";
pub const GROUP_SCHEMA: &str = "sgy.process.group/v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProcessLimits {
    pub max_document_bytes: u64,
    pub max_total_bytes: u64,
    pub max_depth: usize,
    pub max_nodes_per_document: u64,
    pub max_documents: u64,
    pub max_groups: usize,
}

impl Default for ProcessLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: 8 * 1024 * 1024,
            max_total_bytes: 1024 * 1024 * 1024,
            max_depth: 128,
            max_nodes_per_document: 250_000,
            max_documents: 1_000_000,
            max_groups: 10_000,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Operation {
    Validate,
    Select { fields: FieldPaths },
    Filter { field: FieldPaths, equals: Value },
    Count,
    Group { field: FieldPaths },
}

impl Operation {
    pub fn select(fields: &str) -> Result<Self, ProcessError> {
        Ok(Self::Select {
            fields: FieldPaths::parse(fields)?,
        })
    }

    pub fn filter(field: &str, equals_json: &str) -> Result<Self, ProcessError> {
        let equals = serde_json::from_str(equals_json).map_err(|error| {
            ProcessError::InvalidArgument(format!("--equals must be one JSON value: {error}"))
        })?;
        Ok(Self::Filter {
            field: single_field_path(field)?,
            equals,
        })
    }

    pub fn group(field: &str) -> Result<Self, ProcessError> {
        Ok(Self::Group {
            field: single_field_path(field)?,
        })
    }
}

fn single_field_path(input: &str) -> Result<FieldPaths, ProcessError> {
    let parsed = FieldPaths::parse(input)?;
    if parsed.len() != 1 {
        return Err(ProcessError::InvalidArgument(
            "filter/group --field requires exactly one field path".to_owned(),
        ));
    }
    Ok(parsed)
}

#[derive(Debug, Error)]
pub enum ProcessError {
    #[error("cannot read process input: {0}")]
    Input(#[source] io::Error),
    #[error("temporary process storage failed: {0}")]
    Temporary(#[source] io::Error),
    #[error(transparent)]
    Codec(#[from] CodecError),
    #[error("invalid process field path: {0}")]
    FieldPath(#[from] FieldPathError),
    #[error("invalid process argument: {0}")]
    InvalidArgument(String),
    #[error("process input schema error in document {document}: {message}")]
    Schema { document: u64, message: String },
    #[error("process resource limit exceeded: {0}")]
    Limit(String),
    #[error("process identity conflict for {identity}: records differ")]
    Conflict { identity: String },
}

impl ProcessError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Input(_) | Self::Temporary(_) => 126,
            Self::Codec(CodecError::OutputIo(_)) => 127,
            Self::FieldPath(_) | Self::InvalidArgument(_) => 125,
            Self::Codec(_) | Self::Schema { .. } | Self::Limit(_) | Self::Conflict { .. } => 122,
        }
    }
}

#[derive(Debug)]
pub struct Processor {
    operation: Operation,
    limits: ProcessLimits,
    documents: u64,
    records: u64,
    schemas: BTreeMap<String, SchemaStats>,
    groups: BTreeMap<String, GroupStats>,
}

#[derive(Clone, Copy, Debug, Default)]
struct SchemaStats {
    count: u64,
    recognized: bool,
}

#[derive(Clone, Debug)]
struct GroupStats {
    key: Option<Value>,
    count: u64,
}

impl Processor {
    #[must_use]
    pub fn new(operation: Operation, limits: ProcessLimits) -> Self {
        Self {
            operation,
            limits,
            documents: 0,
            records: 0,
            schemas: BTreeMap::new(),
            groups: BTreeMap::new(),
        }
    }

    pub fn push(&mut self, value: Value, output: &mut impl Write) -> Result<(), ProcessError> {
        self.documents = self
            .documents
            .checked_add(1)
            .ok_or_else(|| ProcessError::Limit("document count overflow".to_owned()))?;
        if self.documents > self.limits.max_documents {
            return Err(ProcessError::Limit(format!(
                "document count exceeds {}",
                self.limits.max_documents
            )));
        }
        let schema = inspect_schema(&value, self.documents)?;
        let stats = self.schemas.entry(schema.name.clone()).or_default();
        stats.count = stats
            .count
            .checked_add(1)
            .ok_or_else(|| ProcessError::Limit("schema count overflow".to_owned()))?;
        stats.recognized = schema.recognized;
        if !schema.recognized && !matches!(self.operation, Operation::Validate) {
            return Err(ProcessError::Schema {
                document: self.documents,
                message: format!("unsupported srcq schema {:?}", schema.name),
            });
        }

        let input_records = record_count(&value)?;
        self.records = self
            .records
            .checked_add(input_records)
            .ok_or_else(|| ProcessError::Limit("record count overflow".to_owned()))?;

        match self.operation.clone() {
            Operation::Validate | Operation::Count => {}
            Operation::Select { fields } => {
                let mut selected = select_records(value, &fields);
                let output_records = record_count(&selected)?;
                mark_process(&mut selected, "select", input_records, output_records)?;
                write_yaml_document(&selected, output, true)?;
            }
            Operation::Filter { field, equals } => {
                if let Some(mut filtered) = filter_records(value, &field, &equals)? {
                    let output_records = record_count(&filtered)?;
                    mark_process(&mut filtered, "filter", input_records, output_records)?;
                    write_yaml_document(&filtered, output, true)?;
                }
            }
            Operation::Group { field } => {
                for record in records(&value) {
                    let values = field.values(record);
                    if values.is_empty() {
                        self.increment_group("0:missing".to_owned(), None)?;
                    } else {
                        for value in values {
                            let key = scalar_group_key(value)?;
                            self.increment_group(key, Some(value.clone()))?;
                        }
                    }
                }
            }
        }
        Ok(())
    }

    pub fn finish(self, output: &mut impl Write) -> Result<(), ProcessError> {
        let report = match self.operation {
            Operation::Validate => Some(self.validation_report()),
            Operation::Count => Some(json!({
                "schema": COUNT_SCHEMA,
                "documents": self.documents,
                "records": self.records,
            })),
            Operation::Group { .. } => Some(self.group_report()),
            Operation::Select { .. } | Operation::Filter { .. } => None,
        };
        if let Some(report) = report {
            write_yaml_document(&report, output, false)?;
        }
        output.flush().map_err(CodecError::OutputIo)?;
        Ok(())
    }

    fn increment_group(
        &mut self,
        canonical: String,
        key: Option<Value>,
    ) -> Result<(), ProcessError> {
        if !self.groups.contains_key(&canonical) && self.groups.len() >= self.limits.max_groups {
            return Err(ProcessError::Limit(format!(
                "group cardinality exceeds {}",
                self.limits.max_groups
            )));
        }
        let group = self
            .groups
            .entry(canonical)
            .or_insert(GroupStats { key, count: 0 });
        group.count = group
            .count
            .checked_add(1)
            .ok_or_else(|| ProcessError::Limit("group count overflow".to_owned()))?;
        Ok(())
    }

    fn validation_report(&self) -> Value {
        let schemas: Vec<Value> = self
            .schemas
            .iter()
            .map(|(name, stats)| {
                json!({
                    "name": name,
                    "documents": stats.count,
                    "recognized": stats.recognized,
                })
            })
            .collect();
        json!({
            "schema": VALIDATE_SCHEMA,
            "valid": true,
            "documents": self.documents,
            "records": self.records,
            "schemas": schemas,
        })
    }

    fn group_report(&self) -> Value {
        let groups: Vec<Value> = self
            .groups
            .values()
            .map(|group| match &group.key {
                Some(key) => json!({"key": key, "count": group.count}),
                None => json!({"missing": true, "count": group.count}),
            })
            .collect();
        json!({
            "schema": GROUP_SCHEMA,
            "documents": self.documents,
            "records": self.records,
            "groups": groups,
        })
    }
}

pub fn process_yaml(
    input: impl BufRead,
    output: &mut impl Write,
    operation: Operation,
    limits: ProcessLimits,
) -> Result<(), ProcessError> {
    let mut processor = Processor::new(operation, limits);
    visit_yaml_documents(input, limits, |value| processor.push(value, output))?;
    processor.finish(output)
}

pub fn visit_yaml_documents(
    mut input: impl BufRead,
    limits: ProcessLimits,
    mut visitor: impl FnMut(Value) -> Result<(), ProcessError>,
) -> Result<u64, ProcessError> {
    let mut document = Vec::new();
    let mut line = Vec::new();
    let mut total_bytes = 0_u64;
    let mut documents = 0_u64;
    let mut saw_separator = false;
    let mut separator_needs_document = false;

    loop {
        let read = read_bounded_line(&mut input, &mut line, limits.max_document_bytes)?;
        if read == 0 {
            break;
        }
        total_bytes = total_bytes
            .checked_add(read)
            .ok_or_else(|| ProcessError::Limit("total input byte count overflow".to_owned()))?;
        if total_bytes > limits.max_total_bytes {
            return Err(ProcessError::Limit(format!(
                "total input exceeds {} bytes",
                limits.max_total_bytes
            )));
        }
        if is_document_marker(&line) {
            if !document.is_empty() {
                documents = visit_yaml_document(&document, limits, documents, &mut visitor)?;
                document.clear();
            } else if saw_separator && separator_needs_document {
                return Err(ProcessError::InvalidArgument(
                    "YAML stream contains an empty document".to_owned(),
                ));
            }
            saw_separator = true;
            separator_needs_document = true;
            continue;
        }
        let next_len = document
            .len()
            .checked_add(line.len())
            .ok_or_else(|| ProcessError::Limit("document byte count overflow".to_owned()))?;
        if u64::try_from(next_len).unwrap_or(u64::MAX) > limits.max_document_bytes {
            return Err(ProcessError::Limit(format!(
                "document exceeds {} bytes",
                limits.max_document_bytes
            )));
        }
        document.extend_from_slice(&line);
        separator_needs_document = false;
    }

    if !document.is_empty() {
        documents = visit_yaml_document(&document, limits, documents, &mut visitor)?;
    } else if saw_separator && separator_needs_document {
        return Err(ProcessError::InvalidArgument(
            "YAML stream ends with an empty document".to_owned(),
        ));
    }
    Ok(documents)
}

fn read_bounded_line(
    input: &mut impl BufRead,
    line: &mut Vec<u8>,
    max_line_bytes: u64,
) -> Result<u64, ProcessError> {
    line.clear();
    loop {
        let available = input.fill_buf().map_err(ProcessError::Input)?;
        if available.is_empty() {
            return u64::try_from(line.len())
                .map_err(|error| ProcessError::Limit(error.to_string()));
        }
        let take = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(available.len(), |index| index + 1);
        let next_len = line
            .len()
            .checked_add(take)
            .ok_or_else(|| ProcessError::Limit("line byte count overflow".to_owned()))?;
        if u64::try_from(next_len).unwrap_or(u64::MAX) > max_line_bytes {
            return Err(ProcessError::Limit(format!(
                "line exceeds {max_line_bytes} bytes"
            )));
        }
        line.extend_from_slice(&available[..take]);
        input.consume(take);
        if line.last() == Some(&b'\n') {
            return u64::try_from(line.len())
                .map_err(|error| ProcessError::Limit(error.to_string()));
        }
    }
}

fn is_document_marker(line: &[u8]) -> bool {
    let line = line.strip_suffix(b"\n").unwrap_or(line);
    let line = line.strip_suffix(b"\r").unwrap_or(line);
    line == b"---"
}

fn visit_yaml_document(
    bytes: &[u8],
    limits: ProcessLimits,
    documents_seen: u64,
    visitor: &mut impl FnMut(Value) -> Result<(), ProcessError>,
) -> Result<u64, ProcessError> {
    let mut documents = parse_yaml_documents_with_limits(
        bytes,
        YamlParseLimits {
            max_input_bytes: limits.max_document_bytes,
            max_depth: limits.max_depth,
            max_nodes: limits.max_nodes_per_document,
            max_documents: 1,
        },
    )?;
    if documents.len() != 1 {
        return Err(ProcessError::InvalidArgument(
            "each streamed chunk must contain exactly one YAML document".to_owned(),
        ));
    }
    let next = documents_seen
        .checked_add(1)
        .ok_or_else(|| ProcessError::Limit("document count overflow".to_owned()))?;
    if next > limits.max_documents {
        return Err(ProcessError::Limit(format!(
            "document count exceeds {}",
            limits.max_documents
        )));
    }
    visitor(documents.remove(0))?;
    Ok(next)
}

#[derive(Debug)]
struct InspectedSchema {
    name: String,
    recognized: bool,
}

fn inspect_schema(value: &Value, document: u64) -> Result<InspectedSchema, ProcessError> {
    let Some(mapping) = value.as_object() else {
        return Ok(InspectedSchema {
            name: "generic".to_owned(),
            recognized: true,
        });
    };
    if mapping.get("_sgy").is_some_and(|value| !value.is_object()) {
        return Err(ProcessError::Schema {
            document,
            message: "_sgy must be a mapping when present".to_owned(),
        });
    }
    let top_schema = mapping
        .get("schema")
        .and_then(Value::as_str)
        .filter(|schema| schema.starts_with("sgy."));
    let nested_schema = mapping
        .get("_sgy")
        .and_then(Value::as_object)
        .map(|srcq| optional_text(srcq.get("schema"), "_sgy.schema", document))
        .transpose()?
        .flatten();
    if top_schema.is_some() && nested_schema.is_some() && top_schema != nested_schema {
        return Err(ProcessError::Schema {
            document,
            message: "schema and _sgy.schema disagree".to_owned(),
        });
    }
    let Some(schema) = top_schema.or(nested_schema) else {
        return Ok(InspectedSchema {
            name: "generic".to_owned(),
            recognized: true,
        });
    };
    let recognized = is_known_schema(schema);
    if recognized {
        validate_known_schema(schema, mapping, document)?;
    }
    Ok(InspectedSchema {
        name: schema.to_owned(),
        recognized,
    })
}

fn optional_text<'a>(
    value: Option<&'a Value>,
    field: &str,
    document: u64,
) -> Result<Option<&'a str>, ProcessError> {
    value
        .map(|value| {
            value.as_str().ok_or_else(|| ProcessError::Schema {
                document,
                message: format!("{field} must be a string"),
            })
        })
        .transpose()
}

fn is_known_schema(schema: &str) -> bool {
    matches!(
        schema,
        "sgy.run/v1"
            | "sgy.scan/v1"
            | "sgy.raw/v1"
            | "sgy.output-manifest/v1"
            | "sgy.cache-query/v1"
            | "sgy.process.collection/v1"
            | "sgy.process.merged-record/v1"
            | "sgy.process.containing/v1"
            | "sgy.process.grouped-locations/v1"
            | VALIDATE_SCHEMA
            | COUNT_SCHEMA
            | GROUP_SCHEMA
    )
}

fn validate_known_schema(
    schema: &str,
    mapping: &Map<String, Value>,
    document: u64,
) -> Result<(), ProcessError> {
    let require = |field: &str, predicate: fn(&Value) -> bool| {
        if mapping.get(field).is_some_and(predicate) {
            Ok(())
        } else {
            Err(ProcessError::Schema {
                document,
                message: format!("{schema} requires valid field {field:?}"),
            })
        }
    };
    match schema {
        "sgy.raw/v1" => require("stdout", Value::is_string),
        "sgy.output-manifest/v1" => {
            require("path", Value::is_string)?;
            require("bytes", Value::is_u64)
        }
        "sgy.cache-query/v1" => require("results", Value::is_array),
        "sgy.run/v1" | "sgy.scan/v1" => {
            if mapping.get("_sgy").is_some_and(Value::is_object) {
                Ok(())
            } else {
                Err(ProcessError::Schema {
                    document,
                    message: format!("{schema} requires _sgy mapping"),
                })
            }
        }
        VALIDATE_SCHEMA
        | COUNT_SCHEMA
        | GROUP_SCHEMA
        | "sgy.process.collection/v1"
        | "sgy.process.merged-record/v1"
        | "sgy.process.containing/v1"
        | "sgy.process.grouped-locations/v1" => Ok(()),
        _ => Ok(()),
    }
}

fn record_count(value: &Value) -> Result<u64, ProcessError> {
    if value.pointer("/_sgy/schema").and_then(Value::as_str) == Some("sgy.process.collection/v1") {
        return Ok(0);
    }
    let count = match value {
        Value::Array(items) => items.len(),
        Value::Object(mapping) => mapping
            .get("results")
            .and_then(Value::as_array)
            .map_or(1, Vec::len),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => 1,
    };
    u64::try_from(count).map_err(|error| ProcessError::Limit(error.to_string()))
}

fn records(value: &Value) -> Vec<&Value> {
    match value {
        Value::Array(items) => items.iter().collect(),
        Value::Object(mapping) => mapping
            .get("results")
            .and_then(Value::as_array)
            .map_or_else(|| vec![value], |items| items.iter().collect()),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => vec![value],
    }
}

fn select_records(value: Value, fields: &FieldPaths) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(|item| fields.select(item)).collect()),
        Value::Object(mut mapping) if mapping.get("results").is_some_and(Value::is_array) => {
            if let Some(Value::Array(items)) = mapping.get_mut("results") {
                *items = items.iter().map(|item| fields.select(item)).collect();
            }
            Value::Object(mapping)
        }
        other => {
            let mut selected = fields.select(&other);
            preserve_envelope_metadata(&other, &mut selected);
            selected
        }
    }
}

fn preserve_envelope_metadata(source: &Value, selected: &mut Value) {
    let (Some(source), Some(selected)) = (source.as_object(), selected.as_object_mut()) else {
        return;
    };
    for key in ["schema", "_sgy"] {
        if let Some(value) = source.get(key) {
            selected.insert(key.to_owned(), value.clone());
        }
    }
}

fn filter_records(
    value: Value,
    field: &FieldPaths,
    equals: &Value,
) -> Result<Option<Value>, ProcessError> {
    match value {
        Value::Array(items) => Ok(Some(Value::Array(
            items
                .into_iter()
                .filter(|item| matches_filter(item, field, equals))
                .collect(),
        ))),
        Value::Object(mut mapping) if mapping.get("results").is_some_and(Value::is_array) => {
            if let Some(Value::Array(items)) = mapping.get_mut("results") {
                items.retain(|item| matches_filter(item, field, equals));
            }
            Ok(Some(Value::Object(mapping)))
        }
        other => Ok(matches_filter(&other, field, equals).then_some(other)),
    }
}

fn matches_filter(value: &Value, field: &FieldPaths, equals: &Value) -> bool {
    field.values(value).into_iter().any(|value| value == equals)
}

fn mark_process(
    value: &mut Value,
    operation: &str,
    input_records: u64,
    output_records: u64,
) -> Result<(), ProcessError> {
    let Some(mapping) = value.as_object_mut() else {
        return Ok(());
    };
    let srcq = mapping
        .entry("_sgy".to_owned())
        .or_insert_with(|| Value::Object(Map::new()))
        .as_object_mut()
        .ok_or_else(|| ProcessError::Schema {
            document: 0,
            message: "_sgy must be a mapping".to_owned(),
        })?;
    srcq.insert(
        "process".to_owned(),
        json!({
            "operation": operation,
            "input_records": input_records,
            "output_records": output_records,
        }),
    );
    Ok(())
}

fn scalar_group_key(value: &Value) -> Result<String, ProcessError> {
    match value {
        Value::Null => Ok("1:null".to_owned()),
        Value::Bool(value) => Ok(format!("2:{value}")),
        Value::Number(value) => Ok(format!("3:{value}")),
        Value::String(value) => Ok(format!("4:{value}")),
        Value::Array(_) | Value::Object(_) => Err(ProcessError::InvalidArgument(
            "group field values must be JSON scalars".to_owned(),
        )),
    }
}
