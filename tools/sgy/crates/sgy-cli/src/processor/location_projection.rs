use std::{
    collections::BTreeMap,
    fs,
    io::Write,
    path::{Path, PathBuf},
};

use serde_json::{json, Map, Value};
use sgy_core::{
    cache::{CacheIndexRecord, VerifiedCache},
    codec::{write_compact_yaml_document, write_yaml_document},
    processors::ProcessError,
};

use crate::ProcessInput;

use super::{open_cache, ProcessCommandError};

const CONTAINING_SCHEMA: &str = "sgy.process.containing/v1";
const GROUPED_LOCATIONS_SCHEMA: &str = "sgy.process.grouped-locations/v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Position {
    line: u64,
    column: u64,
}

impl Position {
    const fn new(line: u64, column: u64) -> Self {
        Self { line, column }
    }

    const fn before_or_equal(self, other: Self) -> bool {
        self.line < other.line || self.line == other.line && self.column <= other.column
    }

    const fn strictly_before(self, other: Self) -> bool {
        self.line < other.line || self.line == other.line && self.column < other.column
    }

    fn to_value(self) -> Value {
        json!({"line": self.line, "column": self.column})
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct SourceRange {
    start: Position,
    end: Position,
}

impl SourceRange {
    fn parse(value: &Value) -> Option<Self> {
        let position = |value: &Value| {
            Some(Position::new(
                value.get("line")?.as_u64()?,
                value.get("column")?.as_u64()?,
            ))
        };
        let range = Self {
            start: position(value.get("start")?)?,
            end: position(value.get("end")?)?,
        };
        range.start.strictly_before(range.end).then_some(range)
    }

    const fn contains_position(self, position: Position) -> bool {
        self.start.before_or_equal(position) && position.strictly_before(self.end)
    }

    const fn strictly_contains(self, other: Self) -> bool {
        self.start.before_or_equal(other.start)
            && other.end.before_or_equal(self.end)
            && (self.start.line != other.start.line
                || self.start.column != other.start.column
                || self.end.line != other.end.line
                || self.end.column != other.end.column)
    }

    fn to_value(self) -> Value {
        json!({"start": self.start.to_value(), "end": self.end.to_value()})
    }

    fn compact(self) -> String {
        format!(
            "{}:{}-{}:{}",
            self.start.line, self.start.column, self.end.line, self.end.column
        )
    }
}

#[derive(Clone, Debug)]
struct CachedLocation {
    id: u64,
    file: String,
    range: SourceRange,
}

pub(super) fn execute_containing(
    input: &ProcessInput,
    file: &str,
    line: u64,
    column: u64,
    include_text: bool,
    launch_cwd: &Path,
    output: &mut impl Write,
) -> Result<(), ProcessCommandError> {
    let (cache_id, cache) = location_cache(input, launch_cwd)?;
    let target = normalized_file(file);
    let position = Position::new(line, column);
    let mut candidates = Vec::new();
    for record in cache.iter_records()? {
        let record = record?;
        let record_file = record.file.as_deref().ok_or_else(|| {
            ProcessError::InvalidArgument(format!(
                "cache result {} has no source file; containing selection is incomplete",
                record.id
            ))
        })?;
        if normalized_file(record_file) != target {
            continue;
        }
        let range = indexed_range(&record)?;
        if range.contains_position(position) {
            candidates.push(CachedLocation {
                id: record.id,
                file: record_file.to_owned(),
                range,
            });
        }
    }
    let selected: Vec<CachedLocation> = candidates
        .iter()
        .filter(|candidate| {
            !candidates.iter().any(|other| {
                candidate.id != other.id && candidate.range.strictly_contains(other.range)
            })
        })
        .cloned()
        .collect();
    let mut source_cache = BTreeMap::new();
    let mut results = Vec::new();
    for selected in &selected {
        let text = verify_cached_location(&cache, selected, &mut source_cache)?;
        let mut result = Map::new();
        result.insert("ordinal".to_owned(), Value::from(selected.id));
        result.insert("file".to_owned(), Value::String(selected.file.clone()));
        result.insert("range".to_owned(), selected.range.to_value());
        if include_text {
            result.insert("text".to_owned(), Value::String(text));
        }
        results.push(Value::Object(result));
    }
    let report = json!({
        "_sgy": {
            "schema": CONTAINING_SCHEMA,
            "cache": cache_id,
            "file": file.replace('\\', "/"),
            "position": position.to_value(),
            "candidates": candidates.len(),
            "selected": selected.len(),
            "selection_complete": true,
            "source_verified_records": selected.len(),
            "text_included": include_text,
        },
        "results": results,
    });
    write_yaml_document(&report, output, false).map_err(ProcessError::from)?;
    Ok(())
}

pub(super) fn execute_grouped_locations(
    input: &ProcessInput,
    file: Option<&str>,
    offset: usize,
    limit: usize,
    launch_cwd: &Path,
    output: &mut impl Write,
) -> Result<(), ProcessCommandError> {
    let (cache_id, cache) = location_cache(input, launch_cwd)?;
    let target = file.map(normalized_file);
    let mut locations = Vec::new();
    let mut unprojectable = 0_u64;
    for record in cache.iter_records()? {
        let record = record?;
        let Some(record_file) = record.file.as_deref() else {
            unprojectable = unprojectable.saturating_add(1);
            continue;
        };
        if target
            .as_ref()
            .is_some_and(|target| normalized_file(record_file) != *target)
        {
            continue;
        }
        let Some(range) = record.range.as_ref().and_then(SourceRange::parse) else {
            unprojectable = unprojectable.saturating_add(1);
            continue;
        };
        locations.push(CachedLocation {
            id: record.id,
            file: record_file.to_owned(),
            range,
        });
    }
    let total = locations.len();
    let page: Vec<CachedLocation> = locations.into_iter().skip(offset).take(limit).collect();
    let mut source_cache = BTreeMap::new();
    for location in &page {
        verify_cached_location(&cache, location, &mut source_cache)?;
    }
    let mut grouped: Vec<(String, Vec<String>)> = Vec::new();
    let mut group_index: BTreeMap<String, usize> = BTreeMap::new();
    for location in &page {
        let key = normalized_file(&location.file);
        if let Some(index) = group_index.get(&key).copied() {
            grouped[index].1.push(location.range.compact());
        } else {
            group_index.insert(key, grouped.len());
            grouped.push((location.file.clone(), vec![location.range.compact()]));
        }
    }
    let results: Vec<Value> = grouped
        .into_iter()
        .map(|(file, ranges)| json!({"file": file, "ranges": ranges}))
        .collect();
    let shown = page.len();
    let has_more = offset.saturating_add(shown) < total;
    let mut metadata = Map::new();
    metadata.insert(
        "schema".to_owned(),
        Value::String(GROUPED_LOCATIONS_SCHEMA.to_owned()),
    );
    metadata.insert("cache".to_owned(), Value::String(cache_id));
    metadata.insert("total".to_owned(), Value::from(total));
    metadata.insert("shown".to_owned(), Value::from(shown));
    metadata.insert(
        "omitted".to_owned(),
        Value::from(total.saturating_sub(shown)),
    );
    metadata.insert("offset".to_owned(), Value::from(offset));
    metadata.insert(
        "complete".to_owned(),
        Value::Bool(offset == 0 && !has_more && unprojectable == 0),
    );
    metadata.insert("unprojectable".to_owned(), Value::from(unprojectable));
    metadata.insert("source_verified_records".to_owned(), Value::from(shown));
    if has_more {
        metadata.insert(
            "next_offset".to_owned(),
            Value::from(offset.saturating_add(shown)),
        );
    }
    let report = json!({"_sgy": metadata, "results": results});
    write_compact_yaml_document(&report, output).map_err(ProcessError::from)?;
    Ok(())
}

fn location_cache(
    input: &ProcessInput,
    launch_cwd: &Path,
) -> Result<(String, VerifiedCache), ProcessCommandError> {
    let ProcessInput::Cache(cache_id) = input else {
        return Err(ProcessError::InvalidArgument(
            "location projection requires --cache-id".to_owned(),
        )
        .into());
    };
    let cache = open_cache(cache_id, launch_cwd)?;
    if cache
        .metadata()
        .pointer("/source/format")
        .and_then(Value::as_str)
        == Some("sarif")
    {
        return Err(ProcessError::InvalidArgument(
            "location projection requires native ast-grep JSON ranges, not SARIF".to_owned(),
        )
        .into());
    }
    Ok((cache_id.clone(), cache))
}

fn indexed_range(record: &CacheIndexRecord) -> Result<SourceRange, ProcessCommandError> {
    record
        .range
        .as_ref()
        .and_then(SourceRange::parse)
        .ok_or_else(|| {
            ProcessError::InvalidArgument(format!(
                "cache result {} has no valid 0-based range",
                record.id
            ))
            .into()
        })
}

fn verify_cached_location(
    cache: &VerifiedCache,
    location: &CachedLocation,
    source_cache: &mut BTreeMap<String, Vec<u8>>,
) -> Result<String, ProcessCommandError> {
    let native = cache.result(location.id)?;
    let native_file = native.get("file").and_then(Value::as_str).ok_or_else(|| {
        ProcessError::InvalidArgument(format!("cache result {} has no source file", location.id))
    })?;
    let native_range = native
        .get("range")
        .and_then(SourceRange::parse)
        .ok_or_else(|| {
            ProcessError::InvalidArgument(format!(
                "cache result {} has no valid source range",
                location.id
            ))
        })?;
    let text = native.get("text").and_then(Value::as_str).ok_or_else(|| {
        ProcessError::InvalidArgument(format!(
            "cache result {} has no complete source text",
            location.id
        ))
    })?;
    if normalized_file(native_file) != normalized_file(&location.file)
        || native_range != location.range
    {
        return Err(ProcessError::InvalidArgument(format!(
            "cache result {} disagrees with its verified location index",
            location.id
        ))
        .into());
    }
    let key = normalized_file(native_file);
    if !source_cache.contains_key(&key) {
        let expected = cache.source_fingerprint(native_file).ok_or_else(|| {
            ProcessError::InvalidArgument(format!(
                "cache has no pre-execution fingerprint for {native_file:?}; rerun sgy exec with --cache on --fingerprint-file"
            ))
        })?;
        let cwd = cache
            .metadata()
            .get("cwd")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                ProcessError::InvalidArgument("cache metadata cwd is missing".to_owned())
            })?;
        let actual =
            sgy_core::cache::SourceFingerprint::capture(Path::new(cwd), Path::new(native_file))?;
        if &actual != expected {
            return Err(ProcessError::InvalidArgument(format!(
                "cached source for {native_file:?} changed; rerun ast-grep before reusing locations"
            ))
            .into());
        }
        let path = resolve_cache_source(cache, native_file)?;
        source_cache.insert(key.clone(), fs::read(path).map_err(ProcessError::Input)?);
    }
    let source = source_cache
        .get(&key)
        .ok_or_else(|| ProcessError::InvalidArgument("source cache lookup failed".to_owned()))?;
    let current = source_slice(source, native_range).map_err(|_| {
        ProcessError::InvalidArgument(format!(
            "cached source for {native_file:?} changed; rerun ast-grep before reusing locations"
        ))
    })?;
    if current != text.as_bytes() {
        return Err(ProcessError::InvalidArgument(format!(
            "cached source for {native_file:?} changed; rerun ast-grep before reusing locations"
        ))
        .into());
    }
    Ok(text.to_owned())
}

fn resolve_cache_source(cache: &VerifiedCache, file: &str) -> Result<PathBuf, ProcessCommandError> {
    let cwd = cache
        .metadata()
        .get("cwd")
        .and_then(Value::as_str)
        .ok_or_else(|| ProcessError::InvalidArgument("cache metadata cwd is missing".to_owned()))?;
    let canonical_cwd = fs::canonicalize(cwd).map_err(ProcessError::Input)?;
    let native = PathBuf::from(file.replace('/', "\\"));
    let candidate = if native.is_absolute() {
        native
    } else {
        canonical_cwd.join(native)
    };
    let canonical = fs::canonicalize(candidate).map_err(ProcessError::Input)?;
    if !canonical.starts_with(&canonical_cwd) {
        return Err(ProcessError::InvalidArgument(format!(
            "cached source path {file:?} resolves outside its workspace"
        ))
        .into());
    }
    Ok(canonical)
}

fn source_slice(source: &[u8], range: SourceRange) -> Result<&[u8], ProcessCommandError> {
    let mut starts = vec![0_usize];
    for (index, byte) in source.iter().enumerate() {
        if *byte == b'\n' {
            starts.push(index.saturating_add(1));
        }
    }
    let offset = |position: Position| -> Result<usize, ProcessCommandError> {
        let line = usize::try_from(position.line).map_err(|_| {
            ProcessError::InvalidArgument("source position line is too large".to_owned())
        })?;
        let column = usize::try_from(position.column).map_err(|_| {
            ProcessError::InvalidArgument("source position column is too large".to_owned())
        })?;
        let start = *starts.get(line).ok_or_else(|| {
            ProcessError::InvalidArgument(
                "cached source line is outside the current file".to_owned(),
            )
        })?;
        let end = starts
            .get(line.saturating_add(1))
            .copied()
            .unwrap_or(source.len());
        let value = start
            .checked_add(column)
            .ok_or_else(|| ProcessError::InvalidArgument("source position overflow".to_owned()))?;
        if value > end {
            return Err(ProcessError::InvalidArgument(
                "cached source column is outside the current line".to_owned(),
            )
            .into());
        }
        Ok(value)
    };
    let start = offset(range.start)?;
    let end = offset(range.end)?;
    if start > end || end > source.len() {
        return Err(ProcessError::InvalidArgument(
            "cached source range is invalid for the current file".to_owned(),
        )
        .into());
    }
    Ok(&source[start..end])
}

fn normalized_file(value: &str) -> String {
    let normalized = value.replace('\\', "/");
    normalized
        .strip_prefix("./")
        .unwrap_or(&normalized)
        .to_ascii_lowercase()
}
