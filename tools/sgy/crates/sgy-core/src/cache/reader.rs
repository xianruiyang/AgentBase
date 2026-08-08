use std::{
    fs::{self, File},
    io::{BufRead, BufReader, Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    time::SystemTime,
};

use atomic_write_file::AtomicWriteFile;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::codec::{
    parse_single_json, parse_yaml_documents, write_yaml_document, ByteSpan, JsonLines,
};

use super::{
    io_error,
    model::{hex_lower, CACHE_INDEX_SCHEMA, CACHE_METADATA_SCHEMA},
    store::ensure_safe_file,
    CacheEntryLease, CacheError, CacheIndexRecord, CacheStore, SourceFormat,
};

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct CacheQuery {
    pub file: Option<String>,
    pub rule_id: Option<String>,
    pub offset: usize,
    pub limit: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CachedResult {
    pub id: u64,
    pub value: Value,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CacheQueryResult {
    pub total: u64,
    pub shown: u64,
    pub complete: bool,
    pub results: Vec<CachedResult>,
}

#[derive(Debug)]
pub struct VerifiedCache {
    lease: CacheEntryLease,
    cache_id: String,
    source_format: SourceFormat,
    metadata: Value,
    index: IndexDescriptor,
    record_count: u64,
    source_document: Option<Value>,
}

#[derive(Clone, Debug)]
struct IndexDescriptor {
    path: PathBuf,
    cache_id: String,
    source_format: SourceFormat,
    source_hash: String,
    record_count: u64,
    max_bytes: u64,
}

pub struct CacheIndexIter {
    reader: BufReader<File>,
    expected_records: u64,
    seen: u64,
    total_bytes: u64,
    max_bytes: u64,
    finished: bool,
}

impl CacheStore {
    pub fn open_verified(
        &self,
        cache_id: &str,
        now: SystemTime,
    ) -> Result<VerifiedCache, CacheError> {
        let lease = self.acquire_entry(cache_id)?;
        let mut verified = VerifiedCache::load(
            lease,
            cache_id,
            self.limits().max_entry_bytes,
            self.limits().quota_bytes,
        )?;
        self.touch_verified(&verified.lease, &mut verified.metadata, now)?;
        Ok(verified)
    }

    fn touch_verified(
        &self,
        lease: &CacheEntryLease,
        metadata: &mut Value,
        now: SystemTime,
    ) -> Result<(), CacheError> {
        if lease.path().parent() != Some(self.root()) {
            return Err(CacheError::UnsafePath(lease.path().to_path_buf()));
        }
        let _gc_lock = self.acquire_gc_lock()?;
        let mapping = metadata.as_object_mut().ok_or_else(|| {
            CacheError::Verification("metadata root must be a mapping".to_owned())
        })?;
        let previous_access = parse_time(text_field(mapping, "last_access_at")?)?;
        let accessed_at = now.max(previous_access);
        let expires = accessed_at
            .checked_add(self.limits().ttl)
            .ok_or_else(|| CacheError::InvalidTime("expiry overflow".to_owned()))?;
        mapping.insert(
            "last_access_at".to_owned(),
            Value::String(format_time(accessed_at)?),
        );
        mapping.insert(
            "expires_at".to_owned(),
            Value::String(format_time(expires)?),
        );

        let path = lease.metadata_path();
        ensure_safe_file(&path)?;
        let mut staged = AtomicWriteFile::open(&path)
            .map_err(|source| io_error("stage cache access metadata", &path, source))?;
        write_yaml_document(metadata, &mut staged, false)
            .map_err(|error| CacheError::Serialization(error.to_string()))?;
        staged
            .flush()
            .map_err(|source| io_error("flush cache access metadata", &path, source))?;
        staged
            .sync_all()
            .map_err(|source| io_error("sync cache access metadata", &path, source))?;
        staged
            .commit()
            .map_err(|source| io_error("commit cache access metadata", &path, source))
    }
}

impl VerifiedCache {
    fn load(
        lease: CacheEntryLease,
        expected_id: &str,
        max_entry_bytes: u64,
        max_index_bytes: u64,
    ) -> Result<Self, CacheError> {
        let metadata = read_metadata(&lease.metadata_path())?;
        let metadata_root = object(&metadata, "metadata")?;
        expect_text(metadata_root, "schema", CACHE_METADATA_SCHEMA)?;
        expect_text(metadata_root, "cache_id", expected_id)?;
        expect_text(metadata_root, "state", "committed")?;
        validate_metadata_shape(metadata_root)?;

        let source_metadata = object_field(metadata_root, "source")?;
        let source_format = SourceFormat::parse(text_field(source_metadata, "format")?)?;
        expect_text(source_metadata, "file", source_format.file_name())?;
        let expected_bytes = u64_field(source_metadata, "bytes")?;
        if expected_bytes > max_entry_bytes {
            return Err(CacheError::Verification(format!(
                "source declares {expected_bytes} bytes above entry limit {max_entry_bytes}"
            )));
        }
        let expected_hash = hash_field(source_metadata, "sha256")?;
        let expected_records = u64_field(source_metadata, "records")?;

        let source_path = lease.source_path(source_format);
        ensure_safe_file(&source_path)?;
        let (actual_bytes, actual_hash) = hash_file(&source_path, max_entry_bytes)?;
        if actual_bytes != expected_bytes || actual_hash != expected_hash {
            return Err(CacheError::Verification(
                "native source size or SHA-256 does not match metadata".to_owned(),
            ));
        }

        let index = IndexDescriptor {
            path: lease.index_path(),
            cache_id: expected_id.to_owned(),
            source_format,
            source_hash: expected_hash.to_owned(),
            record_count: expected_records,
            max_bytes: max_index_bytes,
        };
        let mut records = index.iter()?;
        let source_document =
            validate_source_records(&source_path, source_format, &mut records, expected_records)?;

        Ok(Self {
            lease,
            cache_id: expected_id.to_owned(),
            source_format,
            metadata,
            index,
            record_count: expected_records,
            source_document,
        })
    }

    #[must_use]
    pub fn cache_id(&self) -> &str {
        &self.cache_id
    }

    #[must_use]
    pub const fn source_format(&self) -> SourceFormat {
        self.source_format
    }

    #[must_use]
    pub fn metadata(&self) -> &Value {
        &self.metadata
    }

    #[must_use]
    pub const fn record_count(&self) -> u64 {
        self.record_count
    }

    pub fn iter_records(&self) -> Result<CacheIndexIter, CacheError> {
        self.index.iter()
    }

    #[must_use]
    pub fn source_document(&self) -> Option<&Value> {
        self.source_document.as_ref()
    }

    pub fn result(&self, id: u64) -> Result<Value, CacheError> {
        if id >= self.record_count {
            return Err(CacheError::InvalidSelection(format!(
                "result {id} is outside the cache index"
            )));
        }
        let position = usize::try_from(id).map_err(|error| {
            CacheError::InvalidSelection(format!("result id is too large: {error}"))
        })?;
        let record = self
            .iter_records()?
            .nth(position)
            .transpose()?
            .ok_or_else(|| {
                CacheError::InvalidSelection(format!("result {id} is outside the cache index"))
            })?;
        if record.id != id {
            return Err(CacheError::Verification(format!(
                "index position {position} has unexpected id {}",
                record.id
            )));
        }
        if let Some(span) = record.byte_span {
            return read_spanned_value(&self.lease.source_path(self.source_format), span);
        }
        let pointer = record.pointer.as_deref().ok_or_else(|| {
            CacheError::Verification(format!("result {id} has no source locator"))
        })?;
        self.source_document
            .as_ref()
            .and_then(|source| source.pointer(pointer))
            .cloned()
            .ok_or_else(|| {
                CacheError::Verification(format!(
                    "result {id} pointer {pointer:?} is missing from source"
                ))
            })
    }

    pub fn field(&self, id: u64, pointer: &str) -> Result<Value, CacheError> {
        if !pointer.starts_with('/') {
            return Err(CacheError::InvalidSelection(
                "field must be a non-empty RFC 6901 JSON pointer beginning with '/'".to_owned(),
            ));
        }
        self.result(id)?.pointer(pointer).cloned().ok_or_else(|| {
            CacheError::InvalidSelection(format!(
                "field pointer {pointer:?} does not exist in result {id}"
            ))
        })
    }

    pub fn query(&self, query: &CacheQuery) -> Result<CacheQueryResult, CacheError> {
        if query.limit == 0 || query.limit > 1_000 {
            return Err(CacheError::InvalidSelection(
                "query limit must be between 1 and 1000".to_owned(),
            ));
        }
        let mut total = 0_u64;
        let mut results = Vec::new();
        for record in self.iter_records()? {
            let record = record?;
            if query
                .file
                .as_ref()
                .is_some_and(|file| record.file.as_ref() != Some(file))
                || query
                    .rule_id
                    .as_ref()
                    .is_some_and(|rule| record.rule_id.as_ref() != Some(rule))
            {
                continue;
            }
            let ordinal = total;
            total = total
                .checked_add(1)
                .ok_or_else(|| CacheError::Verification("query count overflow".to_owned()))?;
            if ordinal < query.offset as u64 || results.len() >= query.limit {
                continue;
            }
            results.push(CachedResult {
                id: record.id,
                value: self.result(record.id)?,
            });
        }
        let shown = u64::try_from(results.len())
            .map_err(|error| CacheError::Verification(error.to_string()))?;
        let offset = u64::try_from(query.offset)
            .map_err(|error| CacheError::InvalidSelection(error.to_string()))?;
        Ok(CacheQueryResult {
            total,
            shown,
            complete: offset.saturating_add(shown) >= total,
            results,
        })
    }
}

impl IndexDescriptor {
    fn iter(&self) -> Result<CacheIndexIter, CacheError> {
        CacheIndexIter::open(self)
    }
}

fn read_metadata(path: &Path) -> Result<Value, CacheError> {
    ensure_safe_file(path)?;
    let bytes = read_limited_file(path, 1024 * 1024, "cache metadata")?;
    let mut documents = parse_yaml_documents(&bytes)
        .map_err(|error| CacheError::Serialization(error.to_string()))?;
    if documents.len() != 1 {
        return Err(CacheError::Verification(
            "metadata must contain exactly one YAML document".to_owned(),
        ));
    }
    documents
        .pop()
        .ok_or_else(|| CacheError::Verification("metadata is empty".to_owned()))
}

fn validate_metadata_shape(root: &Map<String, Value>) -> Result<(), CacheError> {
    for field in ["created_at", "last_access_at", "expires_at"] {
        parse_time(text_field(root, field)?)?;
    }
    let engine = object_field(root, "engine")?;
    let _ = text_field(engine, "path")?;
    let _ = text_field(engine, "version")?;
    let _ = text_field(root, "cwd")?;
    let invocation = object_field(root, "invocation")?;
    let _ = hash_field(invocation, "user_argv_sha256")?;
    let _ = hash_field(invocation, "effective_argv_sha256")?;
    let injected = invocation
        .get("injected")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            CacheError::Verification("metadata invocation.injected must be an array".to_owned())
        })?;
    if injected.iter().any(|value| !value.is_string()) {
        return Err(CacheError::Verification(
            "metadata invocation.injected must contain only strings".to_owned(),
        ));
    }
    let _ = text_field(invocation, "profile")?;
    let _ = text_field(invocation, "cache_mode")?;
    let process = object_field(root, "process")?;
    if process
        .get("exit_code")
        .is_none_or(|value| !(value.is_null() || value.as_i64().is_some()))
    {
        return Err(CacheError::Verification(
            "metadata process.exit_code must be an integer or null".to_owned(),
        ));
    }
    if process
        .get("failure")
        .is_some_and(|value| !value.is_string())
    {
        return Err(CacheError::Verification(
            "metadata process.failure must be a string".to_owned(),
        ));
    }
    Ok(())
}

const MAX_INDEX_HEADER_BYTES: u64 = 1024 * 1024;
const MAX_INDEX_RECORD_BYTES: u64 = 8 * 1024 * 1024;
const INDEX_RECORDS_SUFFIX: &[u8] = b",\"records\":[\n";

impl CacheIndexIter {
    fn open(descriptor: &IndexDescriptor) -> Result<Self, CacheError> {
        ensure_safe_file(&descriptor.path)?;
        let file = File::open(&descriptor.path)
            .map_err(|source| io_error("open cache index", &descriptor.path, source))?;
        let mut reader = BufReader::new(file);
        let mut header = Vec::new();
        let bytes = read_bounded_index_line(
            &mut reader,
            &mut header,
            MAX_INDEX_HEADER_BYTES,
            0,
            descriptor.max_bytes,
        )?;
        if bytes == 0 || !header.ends_with(INDEX_RECORDS_SUFFIX) {
            return Err(CacheError::InvalidIndex(
                "index must use the streaming records layout".to_owned(),
            ));
        }
        header.truncate(header.len() - INDEX_RECORDS_SUFFIX.len());
        header.push(b'}');
        let parsed = parse_single_json(&header)
            .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
        let root = object(&parsed.value, "index")?;
        expect_text(root, "schema", CACHE_INDEX_SCHEMA)?;
        expect_text(root, "cache_id", &descriptor.cache_id)?;
        expect_text(root, "source_format", descriptor.source_format.as_str())?;
        expect_text(root, "source_sha256", &descriptor.source_hash)?;
        if u64_field(root, "record_count")? != descriptor.record_count {
            return Err(CacheError::InvalidIndex(
                "index and metadata record counts differ".to_owned(),
            ));
        }
        Ok(Self {
            reader,
            expected_records: descriptor.record_count,
            seen: 0,
            total_bytes: bytes,
            max_bytes: descriptor.max_bytes,
            finished: false,
        })
    }

    fn read_next(&mut self) -> Result<Option<CacheIndexRecord>, CacheError> {
        if self.finished {
            return Ok(None);
        }
        if self.seen == self.expected_records {
            let mut footer = Vec::new();
            let bytes = read_bounded_index_line(
                &mut self.reader,
                &mut footer,
                MAX_INDEX_HEADER_BYTES,
                self.total_bytes,
                self.max_bytes,
            )?;
            self.total_bytes = self
                .total_bytes
                .checked_add(bytes)
                .ok_or_else(|| CacheError::InvalidIndex("index byte count overflow".to_owned()))?;
            if footer != b"]}\n" {
                return Err(CacheError::InvalidIndex(
                    "index records array has an invalid footer".to_owned(),
                ));
            }
            let mut trailing = [0_u8; 1];
            if self
                .reader
                .read(&mut trailing)
                .map_err(|source| io_error("read cache index footer", "index.json", source))?
                != 0
            {
                return Err(CacheError::InvalidIndex(
                    "index has trailing bytes after records array".to_owned(),
                ));
            }
            self.finished = true;
            return Ok(None);
        }

        let mut line = Vec::new();
        let bytes = read_bounded_index_line(
            &mut self.reader,
            &mut line,
            MAX_INDEX_RECORD_BYTES,
            self.total_bytes,
            self.max_bytes,
        )?;
        if bytes == 0 {
            return Err(CacheError::InvalidIndex(
                "index ended before all records were read".to_owned(),
            ));
        }
        self.total_bytes = self
            .total_bytes
            .checked_add(bytes)
            .ok_or_else(|| CacheError::InvalidIndex("index byte count overflow".to_owned()))?;
        let expected_suffix = if self.seen + 1 < self.expected_records {
            b",\n".as_slice()
        } else {
            b"\n".as_slice()
        };
        if !line.ends_with(expected_suffix) {
            return Err(CacheError::InvalidIndex(format!(
                "index record {} has an invalid separator",
                self.seen
            )));
        }
        line.truncate(line.len() - expected_suffix.len());
        let parsed = parse_single_json(&line)
            .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
        let position = usize::try_from(self.seen)
            .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
        let record = parse_index_record(position, &parsed.value)?;
        self.seen += 1;
        Ok(Some(record))
    }
}

impl Iterator for CacheIndexIter {
    type Item = Result<CacheIndexRecord, CacheError>;

    fn next(&mut self) -> Option<Self::Item> {
        match self.read_next() {
            Ok(Some(record)) => Some(Ok(record)),
            Ok(None) => None,
            Err(error) => {
                self.finished = true;
                Some(Err(error))
            }
        }
    }
}

fn read_bounded_index_line(
    input: &mut impl BufRead,
    line: &mut Vec<u8>,
    max_line_bytes: u64,
    bytes_seen: u64,
    max_total_bytes: u64,
) -> Result<u64, CacheError> {
    line.clear();
    loop {
        let available = input
            .fill_buf()
            .map_err(|source| io_error("read cache index", "index.json", source))?;
        if available.is_empty() {
            return u64::try_from(line.len())
                .map_err(|error| CacheError::InvalidIndex(error.to_string()));
        }
        let take = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(available.len(), |index| index + 1);
        let next = line
            .len()
            .checked_add(take)
            .ok_or_else(|| CacheError::InvalidIndex("index line length overflow".to_owned()))?;
        let next_u64 =
            u64::try_from(next).map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
        if next_u64 > max_line_bytes || bytes_seen.saturating_add(next_u64) > max_total_bytes {
            return Err(CacheError::InvalidIndex(
                "cache index exceeds its resource limit".to_owned(),
            ));
        }
        line.extend_from_slice(&available[..take]);
        input.consume(take);
        if line.last() == Some(&b'\n') {
            return Ok(next_u64);
        }
    }
}

pub(super) fn parse_index_record(
    position: usize,
    value: &Value,
) -> Result<CacheIndexRecord, CacheError> {
    let root = object(value, "index record")?;
    let id = u64_field(root, "id")?;
    if id != position as u64 {
        return Err(CacheError::InvalidIndex(format!(
            "index record at position {position} has id {id}"
        )));
    }
    let byte_span = match (root.get("byte_start"), root.get("byte_end")) {
        (Some(start), Some(end)) => Some(ByteSpan::new(
            start
                .as_u64()
                .ok_or_else(|| CacheError::InvalidIndex("byte_start must be u64".to_owned()))?,
            end.as_u64()
                .ok_or_else(|| CacheError::InvalidIndex("byte_end must be u64".to_owned()))?,
        )),
        (None, None) => None,
        _ => {
            return Err(CacheError::InvalidIndex(
                "byte_start and byte_end must occur together".to_owned(),
            ))
        }
    };
    let pointer = optional_string(root, "pointer")?;
    if byte_span.is_some() == pointer.is_some() {
        return Err(CacheError::InvalidIndex(
            "each record must have exactly one span or pointer".to_owned(),
        ));
    }
    let range = root.get("range").cloned();
    if range.as_ref().is_some_and(|value| !value.is_object()) {
        return Err(CacheError::InvalidIndex(
            "range hint must be an object".to_owned(),
        ));
    }
    Ok(CacheIndexRecord {
        id,
        byte_span,
        pointer,
        file: optional_string(root, "file")?,
        range,
        rule_id: optional_string(root, "ruleId")?,
    })
}

fn validate_source_records(
    source_path: &Path,
    format: SourceFormat,
    records: &mut CacheIndexIter,
    expected_records: u64,
) -> Result<Option<Value>, CacheError> {
    match format {
        SourceFormat::JsonLines => {
            let input = File::open(source_path)
                .map_err(|source| io_error("open cached JSONL", source_path, source))?;
            let mut count = 0_u64;
            for parsed in JsonLines::new(BufReader::new(input)) {
                let parsed = parsed.map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
                let expected = CacheIndexRecord::from_source(&parsed);
                let actual = records.next().transpose()?;
                compare_record(actual.as_ref(), &expected)?;
                count = count.checked_add(1).ok_or_else(|| {
                    CacheError::InvalidIndex("JSONL record count overflow".to_owned())
                })?;
            }
            if count != expected_records || records.next().transpose()?.is_some() {
                return Err(CacheError::InvalidIndex(
                    "JSONL source and index counts differ".to_owned(),
                ));
            }
            Ok(None)
        }
        SourceFormat::JsonValue => {
            let parsed = read_json_document(source_path)?;
            let actual = records.next().transpose()?;
            compare_record(actual.as_ref(), &CacheIndexRecord::from_source(&parsed))?;
            if expected_records != 1 || records.next().transpose()?.is_some() {
                return Err(CacheError::InvalidIndex(
                    "json-value cache must contain exactly one record".to_owned(),
                ));
            }
            Ok(Some(parsed.value))
        }
        SourceFormat::JsonArray => {
            let parsed = read_json_document(source_path)?;
            let array = parsed.value.as_array().ok_or_else(|| {
                CacheError::InvalidIndex("json-array source is not an array".to_owned())
            })?;
            if u64::try_from(array.len()).ok() != Some(expected_records) {
                return Err(CacheError::InvalidIndex(
                    "JSON array source and index counts differ".to_owned(),
                ));
            }
            for (position, value) in array.iter().enumerate() {
                let actual = records.next().transpose()?;
                compare_record(
                    actual.as_ref(),
                    &CacheIndexRecord::with_pointer(position as u64, format!("/{position}"), value),
                )?;
            }
            if records.next().transpose()?.is_some() {
                return Err(CacheError::InvalidIndex(
                    "JSON array source and index counts differ".to_owned(),
                ));
            }
            Ok(Some(parsed.value))
        }
        SourceFormat::Sarif => {
            let parsed = read_json_document(source_path)?;
            let mut position = 0_usize;
            if let Some(runs) = parsed.value.get("runs").and_then(Value::as_array) {
                for (run_index, run) in runs.iter().enumerate() {
                    if let Some(results) = run.get("results").and_then(Value::as_array) {
                        for (result_index, value) in results.iter().enumerate() {
                            let actual = records.next().transpose()?;
                            compare_record(
                                actual.as_ref(),
                                &CacheIndexRecord::with_sarif_pointer(
                                    position as u64,
                                    format!("/runs/{run_index}/results/{result_index}"),
                                    value,
                                ),
                            )?;
                            position += 1;
                        }
                    }
                }
            }
            if u64::try_from(position).ok() != Some(expected_records)
                || records.next().transpose()?.is_some()
            {
                return Err(CacheError::InvalidIndex(
                    "SARIF source and index counts differ".to_owned(),
                ));
            }
            Ok(Some(parsed.value))
        }
    }
}

fn compare_record(
    actual: Option<&CacheIndexRecord>,
    expected: &CacheIndexRecord,
) -> Result<(), CacheError> {
    if actual != Some(expected) {
        Err(CacheError::InvalidIndex(format!(
            "index record {} does not match native source",
            expected.id
        )))
    } else {
        Ok(())
    }
}

fn read_json_document(path: &Path) -> Result<crate::codec::SourceRecord, CacheError> {
    let bytes = fs::read(path).map_err(|source| io_error("read cached JSON", path, source))?;
    parse_single_json(&bytes).map_err(|error| CacheError::InvalidIndex(error.to_string()))
}

fn read_spanned_value(path: &Path, span: ByteSpan) -> Result<Value, CacheError> {
    if span.is_empty() {
        return Err(CacheError::InvalidIndex("result span is empty".to_owned()));
    }
    let length =
        usize::try_from(span.len()).map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
    let mut bytes = vec![0_u8; length];
    let mut input =
        File::open(path).map_err(|source| io_error("open cached result", path, source))?;
    input
        .seek(SeekFrom::Start(span.start))
        .map_err(|source| io_error("seek cached result", path, source))?;
    input
        .read_exact(&mut bytes)
        .map_err(|source| io_error("read cached result", path, source))?;
    parse_single_json(&bytes)
        .map(|record| record.value)
        .map_err(|error| CacheError::InvalidIndex(error.to_string()))
}

fn hash_file(path: &Path, limit: u64) -> Result<(u64, String), CacheError> {
    let mut input = BufReader::new(
        File::open(path).map_err(|source| io_error("open cached source for hash", path, source))?,
    );
    let mut hasher = Sha256::new();
    let mut bytes = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = input
            .read(&mut buffer)
            .map_err(|source| io_error("hash cached source", path, source))?;
        if count == 0 {
            break;
        }
        bytes = bytes
            .checked_add(count as u64)
            .ok_or_else(|| CacheError::Verification("source size overflow".to_owned()))?;
        if bytes > limit {
            return Err(CacheError::EntryTooLarge { limit });
        }
        hasher.update(&buffer[..count]);
    }
    Ok((bytes, hex_lower(&hasher.finalize())))
}

fn read_limited_file(path: &Path, limit: u64, label: &'static str) -> Result<Vec<u8>, CacheError> {
    let metadata = fs::metadata(path)
        .map_err(|source| io_error("measure cache control file", path, source))?;
    if metadata.len() > limit {
        return Err(CacheError::Verification(format!(
            "{label} exceeds the {limit} byte read limit"
        )));
    }
    fs::read(path).map_err(|source| io_error("read cache control file", path, source))
}

fn object<'a>(value: &'a Value, name: &str) -> Result<&'a Map<String, Value>, CacheError> {
    value
        .as_object()
        .ok_or_else(|| CacheError::Verification(format!("{name} must be a mapping")))
}

fn object_field<'a>(
    root: &'a Map<String, Value>,
    field: &str,
) -> Result<&'a Map<String, Value>, CacheError> {
    root.get(field)
        .and_then(Value::as_object)
        .ok_or_else(|| CacheError::Verification(format!("metadata {field} must be a mapping")))
}

fn text_field<'a>(root: &'a Map<String, Value>, field: &str) -> Result<&'a str, CacheError> {
    root.get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| CacheError::Verification(format!("missing string field {field}")))
}

fn expect_text(root: &Map<String, Value>, field: &str, expected: &str) -> Result<(), CacheError> {
    let actual = text_field(root, field)?;
    if actual == expected {
        Ok(())
    } else {
        Err(CacheError::Verification(format!(
            "field {field} is {actual:?}, expected {expected:?}"
        )))
    }
}

fn optional_string(root: &Map<String, Value>, field: &str) -> Result<Option<String>, CacheError> {
    root.get(field)
        .map(|value| {
            value
                .as_str()
                .map(ToOwned::to_owned)
                .ok_or_else(|| CacheError::InvalidIndex(format!("{field} must be a string")))
        })
        .transpose()
}

fn u64_field(root: &Map<String, Value>, field: &str) -> Result<u64, CacheError> {
    root.get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| CacheError::Verification(format!("missing u64 field {field}")))
}

fn hash_field<'a>(root: &'a Map<String, Value>, field: &str) -> Result<&'a str, CacheError> {
    let value = text_field(root, field)?;
    if value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        Ok(value)
    } else {
        Err(CacheError::Verification(format!(
            "field {field} must be a lowercase SHA-256"
        )))
    }
}

fn parse_time(value: &str) -> Result<SystemTime, CacheError> {
    humantime::parse_rfc3339(value).map_err(|error| CacheError::InvalidTime(error.to_string()))
}

fn format_time(value: SystemTime) -> Result<String, CacheError> {
    Ok(humantime::format_rfc3339(value).to_string())
}
