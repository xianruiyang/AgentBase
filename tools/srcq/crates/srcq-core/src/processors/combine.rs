use std::{
    collections::{HashMap, HashSet},
    io::{BufRead, Write},
};

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use super::{
    external::{ExternalSortLimits, ExternalSorter, SpoolRecord},
    inspect_schema, visit_yaml_documents, ProcessError, ProcessLimits,
};
use crate::{
    codec::{parse_single_json, write_yaml_document, CodecError},
    profile::FieldPaths,
};

pub const IDENTITY_SCHEMA: &str = "sgy.identity/v1";
const COLLECTION_SCHEMA: &str = "sgy.process.collection/v1";
const MERGED_RECORD_SCHEMA: &str = "sgy.process.merged-record/v1";
const MAX_SOURCES: usize = 128;
const MAX_WRITE_SUMMARIES: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConflictPolicy {
    Error,
    KeepFirst,
}

impl ConflictPolicy {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Error => "error",
            Self::KeepFirst => "keep-first",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum CollectionOperation {
    Sort { by: FieldPaths, descending: bool },
    Dedupe { conflicts: ConflictPolicy },
    Merge { conflicts: ConflictPolicy },
}

impl CollectionOperation {
    pub fn sort(by: &str, descending: bool) -> Result<Self, ProcessError> {
        let by = FieldPaths::parse(by)?;
        if by.len() != 1 {
            return Err(ProcessError::InvalidArgument(
                "sort --by requires exactly one field path".to_owned(),
            ));
        }
        Ok(Self::Sort { by, descending })
    }

    #[must_use]
    pub const fn dedupe(conflicts: ConflictPolicy) -> Self {
        Self::Dedupe { conflicts }
    }

    #[must_use]
    pub const fn merge(conflicts: ConflictPolicy) -> Self {
        Self::Merge { conflicts }
    }

    const fn name(&self) -> &'static str {
        match self {
            Self::Sort { .. } => "sort",
            Self::Dedupe { .. } => "dedupe",
            Self::Merge { .. } => "merge",
        }
    }

    const fn conflict_policy(&self) -> Option<ConflictPolicy> {
        match self {
            Self::Sort { .. } => None,
            Self::Dedupe { conflicts } | Self::Merge { conflicts } => Some(*conflicts),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct CollectionSource {
    pub id: String,
    pub scope: String,
    pub descriptor: Value,
}

impl CollectionSource {
    pub fn new(
        id: impl Into<String>,
        scope: impl Into<String>,
        descriptor: Value,
    ) -> Result<Self, ProcessError> {
        let id = id.into();
        let scope = scope.into();
        if id.is_empty() || scope.is_empty() {
            return Err(ProcessError::InvalidArgument(
                "collection source id and scope must not be empty".to_owned(),
            ));
        }
        if !descriptor.is_object() {
            return Err(ProcessError::InvalidArgument(
                "collection source descriptor must be a mapping".to_owned(),
            ));
        }
        Ok(Self {
            id,
            scope,
            descriptor,
        })
    }
}

#[derive(Clone, Debug)]
struct SourceStats {
    source: CollectionSource,
    documents: u64,
    records: u64,
    complete: Option<bool>,
    complete_unknown: bool,
    omitted: u64,
    writes: Vec<Value>,
    write_keys: HashSet<String>,
    upstream_sources: Vec<Value>,
    upstream_source_keys: HashSet<String>,
}

impl SourceStats {
    fn new(source: CollectionSource) -> Self {
        Self {
            source,
            documents: 0,
            records: 0,
            complete: None,
            complete_unknown: false,
            omitted: 0,
            writes: Vec::new(),
            write_keys: HashSet::new(),
            upstream_sources: Vec::new(),
            upstream_source_keys: HashSet::new(),
        }
    }

    fn observe_document(&mut self, value: &Value, records: usize) -> Result<(), ProcessError> {
        self.documents = checked_add(self.documents, 1, "source document count")?;
        self.records = checked_add(
            self.records,
            u64::try_from(records).map_err(|error| ProcessError::Limit(error.to_string()))?,
            "source record count",
        )?;
        let Some(srcq) = value.get("_sgy").and_then(Value::as_object) else {
            self.complete_unknown = true;
            return Ok(());
        };
        if let Some(complete) = srcq.get("complete").and_then(Value::as_bool) {
            self.complete = Some(self.complete.unwrap_or(true) && complete);
        } else {
            self.complete_unknown = true;
        }
        if let Some(omitted) = srcq.get("omitted").and_then(Value::as_u64) {
            self.omitted = checked_add(self.omitted, omitted, "source omitted count")?;
        }
        if let Some(write) = srcq.get("write") {
            let key = canonical_json(write)?;
            if self.write_keys.insert(key) {
                if self.writes.len() >= MAX_WRITE_SUMMARIES {
                    return Err(ProcessError::Limit(format!(
                        "source write summary count exceeds {MAX_WRITE_SUMMARIES}"
                    )));
                }
                self.writes.push(write.clone());
            }
        }
        if srcq.get("schema").and_then(Value::as_str) == Some(COLLECTION_SCHEMA) {
            if let Some(sources) = srcq.get("sources").and_then(Value::as_array) {
                for source in sources {
                    let key = canonical_json(source)?;
                    if self.upstream_source_keys.insert(key) {
                        if self.upstream_sources.len() >= MAX_SOURCES {
                            return Err(ProcessError::Limit(format!(
                                "upstream source count exceeds {MAX_SOURCES}"
                            )));
                        }
                        self.upstream_sources.push(source.clone());
                    }
                }
            }
        }
        Ok(())
    }

    fn to_value(&self) -> Value {
        let mut descriptor = self
            .source
            .descriptor
            .as_object()
            .cloned()
            .unwrap_or_default();
        descriptor.insert("id".to_owned(), Value::String(self.source.id.clone()));
        descriptor.insert("documents".to_owned(), Value::from(self.documents));
        descriptor.insert("records".to_owned(), Value::from(self.records));
        if let Some(complete) = self.complete.filter(|_| !self.complete_unknown) {
            descriptor.insert("complete".to_owned(), Value::Bool(complete));
        }
        if self.omitted > 0 {
            descriptor.insert("omitted".to_owned(), Value::from(self.omitted));
        }
        if !self.writes.is_empty() {
            descriptor.insert("write".to_owned(), Value::Array(self.writes.clone()));
        }
        if !self.upstream_sources.is_empty() {
            descriptor.insert(
                "upstream_sources".to_owned(),
                Value::Array(self.upstream_sources.clone()),
            );
        }
        Value::Object(descriptor)
    }
}

pub struct CollectionBuilder {
    operation: CollectionOperation,
    limits: ProcessLimits,
    sorter: ExternalSorter,
    sources: Vec<SourceStats>,
    source_index: HashMap<String, usize>,
    next_ordinal: u64,
    input_records: u64,
}

impl CollectionBuilder {
    pub fn new(
        operation: CollectionOperation,
        limits: ProcessLimits,
    ) -> Result<Self, ProcessError> {
        let descending = matches!(
            operation,
            CollectionOperation::Sort {
                descending: true,
                ..
            }
        );
        Ok(Self {
            operation,
            limits,
            sorter: ExternalSorter::new(ExternalSortLimits::default(), descending)?,
            sources: Vec::new(),
            source_index: HashMap::new(),
            next_ordinal: 0,
            input_records: 0,
        })
    }

    pub fn add_source(&mut self, source: CollectionSource) -> Result<(), ProcessError> {
        if self.sources.len() >= MAX_SOURCES {
            return Err(ProcessError::Limit(format!(
                "collection source count exceeds {MAX_SOURCES}"
            )));
        }
        if self.source_index.contains_key(&source.id) {
            return Err(ProcessError::InvalidArgument(format!(
                "duplicate collection source id {:?}",
                source.id
            )));
        }
        let index = self.sources.len();
        self.source_index.insert(source.id.clone(), index);
        self.sources.push(SourceStats::new(source));
        Ok(())
    }

    pub fn push_document(&mut self, source_id: &str, value: Value) -> Result<(), ProcessError> {
        let index = *self.source_index.get(source_id).ok_or_else(|| {
            ProcessError::InvalidArgument(format!("unknown collection source {source_id:?}"))
        })?;
        let inspected = inspect_schema(&value, self.next_ordinal.saturating_add(1))?;
        if !inspected.recognized {
            return Err(ProcessError::Schema {
                document: self.next_ordinal.saturating_add(1),
                message: format!("unsupported srcq schema {:?}", inspected.name),
            });
        }
        let records = into_records(value.clone());
        self.sources[index].observe_document(&value, records.len())?;
        let scope = self.sources[index].source.scope.clone();
        for value in records {
            self.input_records = checked_add(self.input_records, 1, "input record count")?;
            if self.input_records > self.limits.max_documents {
                return Err(ProcessError::Limit(format!(
                    "collection record count exceeds {}",
                    self.limits.max_documents
                )));
            }
            self.next_ordinal = checked_add(self.next_ordinal, 1, "input record ordinal")?;
            let identity = record_identity(&value, &scope)?;
            let key = match &self.operation {
                CollectionOperation::Sort { by, .. } => sort_key(&value, by)?,
                CollectionOperation::Dedupe { .. } | CollectionOperation::Merge { .. } => {
                    identity.clone()
                }
            };
            self.sorter.push(SpoolRecord {
                key,
                identity,
                ordinal: self.next_ordinal,
                source_ids: vec![source_id.to_owned()],
                conflicts: 0,
                value,
            })?;
        }
        Ok(())
    }

    pub fn finish(self, output: &mut impl Write) -> Result<(), ProcessError> {
        match self.operation {
            CollectionOperation::Sort { .. } => self.finish_sort(output),
            CollectionOperation::Dedupe { conflicts } => {
                self.finish_unique(output, conflicts, false)
            }
            CollectionOperation::Merge { conflicts } => self.finish_unique(output, conflicts, true),
        }
    }

    fn finish_sort(self, output: &mut impl Write) -> Result<(), ProcessError> {
        write_yaml_document(
            &collection_header(
                &self.operation,
                &self.sources,
                self.input_records,
                self.input_records,
                0,
                0,
            ),
            output,
            true,
        )?;
        self.sorter.finish(|record| {
            write_yaml_document(&record.value, output, true)?;
            Ok(())
        })?;
        output.flush().map_err(CodecError::OutputIo)?;
        Ok(())
    }

    fn finish_unique(
        self,
        output: &mut impl Write,
        policy: ConflictPolicy,
        merge: bool,
    ) -> Result<(), ProcessError> {
        let mut stable = ExternalSorter::new(ExternalSortLimits::default(), false)?;
        let mut current: Option<SpoolRecord> = None;
        let mut output_records = 0_u64;
        let mut duplicates = 0_u64;
        let mut conflicts = 0_u64;
        self.sorter.finish(|record| {
            if let Some(winner) = current.as_mut() {
                if winner.identity == record.identity {
                    duplicates = checked_add(duplicates, 1, "duplicate count")?;
                    append_sources(&mut winner.source_ids, &record.source_ids);
                    if canonical_record(&winner.value)? != canonical_record(&record.value)? {
                        conflicts = checked_add(conflicts, 1, "conflict count")?;
                        winner.conflicts = checked_add(winner.conflicts, 1, "record conflicts")?;
                        if policy == ConflictPolicy::Error {
                            return Err(ProcessError::Conflict {
                                identity: winner.identity.clone(),
                            });
                        }
                    }
                    return Ok(());
                }
            }
            if let Some(winner) = current.take() {
                output_records = checked_add(output_records, 1, "output record count")?;
                stable.push(stable_record(winner))?;
            }
            current = Some(record);
            Ok(())
        })?;
        if let Some(winner) = current.take() {
            output_records = checked_add(output_records, 1, "output record count")?;
            stable.push(stable_record(winner))?;
        }

        write_yaml_document(
            &collection_header(
                &self.operation,
                &self.sources,
                self.input_records,
                output_records,
                duplicates,
                conflicts,
            ),
            output,
            true,
        )?;
        stable.finish(|record| {
            let value = if merge {
                json!({
                    "_sgy": {
                        "schema": MERGED_RECORD_SCHEMA,
                        "identity": record.identity,
                        "source_ids": record.source_ids,
                        "conflicts": record.conflicts,
                    },
                    "value": record.value,
                })
            } else {
                record.value
            };
            write_yaml_document(&value, output, true)?;
            Ok(())
        })?;
        output.flush().map_err(CodecError::OutputIo)?;
        Ok(())
    }
}

fn stable_record(mut record: SpoolRecord) -> SpoolRecord {
    record.key = format!("{:020}", record.ordinal);
    record
}

fn append_sources(target: &mut Vec<String>, sources: &[String]) {
    for source in sources {
        if !target.contains(source) {
            target.push(source.clone());
        }
    }
}

fn collection_header(
    operation: &CollectionOperation,
    sources: &[SourceStats],
    input_records: u64,
    records: u64,
    duplicates: u64,
    conflicts: u64,
) -> Value {
    let mut metadata = Map::new();
    metadata.insert(
        "schema".to_owned(),
        Value::String(COLLECTION_SCHEMA.to_owned()),
    );
    metadata.insert(
        "operation".to_owned(),
        Value::String(operation.name().to_owned()),
    );
    metadata.insert(
        "identity".to_owned(),
        Value::String(IDENTITY_SCHEMA.to_owned()),
    );
    metadata.insert("input_records".to_owned(), Value::from(input_records));
    metadata.insert("records".to_owned(), Value::from(records));
    metadata.insert("duplicates".to_owned(), Value::from(duplicates));
    metadata.insert("conflicts".to_owned(), Value::from(conflicts));
    if let Some(policy) = operation.conflict_policy() {
        metadata.insert(
            "conflict_policy".to_owned(),
            Value::String(policy.as_str().to_owned()),
        );
    }
    metadata.insert(
        "sources".to_owned(),
        Value::Array(sources.iter().map(SourceStats::to_value).collect()),
    );
    json!({"_sgy": metadata})
}

fn into_records(value: Value) -> Vec<Value> {
    let schema = value.pointer("/_sgy/schema").and_then(Value::as_str);
    if schema == Some(COLLECTION_SCHEMA) {
        return Vec::new();
    }
    if schema == Some(MERGED_RECORD_SCHEMA) {
        return value
            .get("value")
            .cloned()
            .map_or_else(Vec::new, |value| vec![value]);
    }
    match value {
        Value::Array(items) => items,
        Value::Object(mut mapping) if mapping.get("results").is_some_and(Value::is_array) => {
            mapping
                .remove("results")
                .and_then(|value| value.as_array().cloned())
                .unwrap_or_default()
        }
        other => vec![other],
    }
}

fn sort_key(value: &Value, by: &FieldPaths) -> Result<String, ProcessError> {
    let values = by.values(value);
    match values.as_slice() {
        [] => Ok("0:missing".to_owned()),
        [value] => scalar_key(value),
        _ => Err(ProcessError::InvalidArgument(
            "sort field path resolves to multiple values for one record".to_owned(),
        )),
    }
}

fn scalar_key(value: &Value) -> Result<String, ProcessError> {
    match value {
        Value::Null => Ok("1:null".to_owned()),
        Value::Bool(value) => Ok(format!("2:{value}")),
        Value::Number(value) => number_key(&value.to_string()),
        Value::String(value) => Ok(format!("4:{value}")),
        Value::Array(_) | Value::Object(_) => Err(ProcessError::InvalidArgument(
            "sort field values must be JSON scalars".to_owned(),
        )),
    }
}

fn number_key(input: &str) -> Result<String, ProcessError> {
    let (negative, unsigned) = input
        .strip_prefix('-')
        .map_or((false, input), |value| (true, value));
    let (coefficient, exponent) = unsigned
        .split_once(['e', 'E'])
        .map_or((unsigned, "0"), |parts| parts);
    let exponent = exponent.parse::<i64>().map_err(|error| {
        ProcessError::InvalidArgument(format!(
            "number exponent is outside sortable range: {error}"
        ))
    })?;
    let (integer, fraction) = coefficient
        .split_once('.')
        .map_or((coefficient, ""), |parts| parts);
    let mut digits = format!("{integer}{fraction}");
    let leading = digits.bytes().take_while(|byte| *byte == b'0').count();
    if leading == digits.len() {
        return Ok("3:1".to_owned());
    }
    digits.drain(..leading);
    while digits.ends_with('0') {
        digits.pop();
    }
    let integer_digits = i64::try_from(integer.len())
        .map_err(|error| ProcessError::InvalidArgument(error.to_string()))?;
    let leading =
        i64::try_from(leading).map_err(|error| ProcessError::InvalidArgument(error.to_string()))?;
    let magnitude = exponent
        .checked_add(integer_digits)
        .and_then(|value| value.checked_sub(leading))
        .and_then(|value| value.checked_sub(1))
        .ok_or_else(|| ProcessError::InvalidArgument("number magnitude overflow".to_owned()))?;
    let ordered_magnitude = (magnitude as u64) ^ (1_u64 << 63);
    let magnitude_key = format!("{ordered_magnitude:016x}");
    if negative {
        let magnitude_key = complement_hex(&magnitude_key);
        let digits = digits
            .bytes()
            .map(|byte| char::from(b'9' - (byte - b'0')))
            .collect::<String>();
        Ok(format!("3:0:{magnitude_key}:{digits}:"))
    } else {
        Ok(format!("3:2:{magnitude_key}:{digits}/"))
    }
}

fn complement_hex(value: &str) -> String {
    value
        .bytes()
        .map(|byte| {
            let digit = match byte {
                b'0'..=b'9' => byte - b'0',
                b'a'..=b'f' => byte - b'a' + 10,
                _ => 0,
            };
            let complement = 15 - digit;
            if complement < 10 {
                char::from(b'0' + complement)
            } else {
                char::from(b'a' + complement - 10)
            }
        })
        .collect()
}

fn record_identity(value: &Value, scope: &str) -> Result<String, ProcessError> {
    let basis = value.as_object().and_then(|mapping| {
        let file = mapping.get("file")?.as_str()?;
        let range = mapping.get("range")?.clone();
        let mut basis = Map::new();
        basis.insert("scope".to_owned(), Value::String(scope.to_owned()));
        basis.insert("file".to_owned(), Value::String(file.to_owned()));
        basis.insert("range".to_owned(), range);
        if let Some(rule) = mapping.get("ruleId") {
            basis.insert("ruleId".to_owned(), rule.clone());
        }
        Some(Value::Object(basis))
    });
    let basis = basis.unwrap_or_else(|| {
        json!({
            "scope": scope,
            "record": normalized_record(value),
        })
    });
    Ok(format!(
        "{IDENTITY_SCHEMA}:{}",
        sha256(&canonical_json(&basis)?)
    ))
}

fn canonical_record(value: &Value) -> Result<String, ProcessError> {
    canonical_json(&normalized_record(value))
}

fn normalized_record(value: &Value) -> Value {
    let mut value = value.clone();
    if let Some(srcq) = value.get_mut("_sgy").and_then(Value::as_object_mut) {
        srcq.remove("process");
    }
    value
}

fn canonical_json(value: &Value) -> Result<String, ProcessError> {
    serde_json::to_string(&canonical_value(value))
        .map_err(|error| ProcessError::InvalidArgument(error.to_string()))
}

fn canonical_value(value: &Value) -> Value {
    match value {
        Value::Object(mapping) => {
            let mut keys: Vec<&String> = mapping.keys().collect();
            keys.sort();
            let mut output = Map::new();
            for key in keys {
                output.insert(key.clone(), canonical_value(&mapping[key]));
            }
            Value::Object(output)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonical_value).collect()),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => value.clone(),
    }
}

fn sha256(value: &str) -> String {
    let digest = Sha256::digest(value.as_bytes());
    let mut output = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

fn checked_add(left: u64, right: u64, name: &str) -> Result<u64, ProcessError> {
    left.checked_add(right)
        .ok_or_else(|| ProcessError::Limit(format!("{name} overflow")))
}

pub fn yaml_to_jsonl(
    input: impl BufRead,
    output: &mut impl Write,
    limits: ProcessLimits,
) -> Result<(), ProcessError> {
    visit_yaml_documents(input, limits, |value| write_jsonl_value(&value, output))?;
    output.flush().map_err(CodecError::OutputIo)?;
    Ok(())
}

pub fn write_jsonl_value(value: &Value, output: &mut impl Write) -> Result<(), ProcessError> {
    serde_json::to_writer(&mut *output, value)
        .map_err(|error| ProcessError::InvalidArgument(error.to_string()))?;
    output.write_all(b"\n").map_err(CodecError::OutputIo)?;
    Ok(())
}

pub fn jsonl_to_yaml(
    mut input: impl BufRead,
    output: &mut impl Write,
    limits: ProcessLimits,
) -> Result<(), ProcessError> {
    let mut line = Vec::new();
    let mut total = 0_u64;
    let mut records = 0_u64;
    loop {
        let bytes = read_json_line(&mut input, &mut line, limits.max_document_bytes)?;
        if bytes == 0 {
            break;
        }
        total = checked_add(total, bytes, "JSONL total bytes")?;
        if total > limits.max_total_bytes {
            return Err(ProcessError::Limit(format!(
                "JSONL input exceeds {} bytes",
                limits.max_total_bytes
            )));
        }
        if line.iter().all(|byte| byte.is_ascii_whitespace()) {
            continue;
        }
        let record = parse_single_json(&line)?;
        records = checked_add(records, 1, "JSONL record count")?;
        if records > limits.max_documents {
            return Err(ProcessError::Limit(format!(
                "JSONL record count exceeds {}",
                limits.max_documents
            )));
        }
        write_yaml_document(&record.value, output, true)?;
    }
    output.flush().map_err(CodecError::OutputIo)?;
    Ok(())
}

fn read_json_line(
    input: &mut impl BufRead,
    line: &mut Vec<u8>,
    max_bytes: u64,
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
        let next = line
            .len()
            .checked_add(take)
            .ok_or_else(|| ProcessError::Limit("JSONL line byte count overflow".to_owned()))?;
        if u64::try_from(next).unwrap_or(u64::MAX) > max_bytes {
            return Err(ProcessError::Limit(format!(
                "JSONL record exceeds {max_bytes} bytes"
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
