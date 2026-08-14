use std::{
    fs::{self, File, OpenOptions},
    io::{self, BufReader, Read, Write},
    path::{Path, PathBuf},
    time::SystemTime,
};

use fs2::FileExt;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

use crate::codec::{parse_single_json, write_yaml_document, JsonLines, SourceRecord};

use super::{
    io_error,
    model::{
        hex_lower, path_text, CacheIndexRecord, CacheProcess, CACHE_INDEX_SCHEMA,
        CACHE_METADATA_SCHEMA,
    },
    reader::parse_index_record,
    store::{open_private_lock, CacheStore},
    CacheAudit, CacheError, SourceFormat,
};

#[derive(Clone, Debug, Eq, PartialEq)]
struct SourceSnapshot {
    bytes: u64,
    sha256: String,
}

const STAGED_INDEX_RECORDS: &str = ".index-records.jsonl";

#[derive(Debug)]
pub struct CacheStaging {
    store: CacheStore,
    directory: TempDir,
    lock: Option<File>,
    cache_id: String,
    format: SourceFormat,
    audit: CacheAudit,
    created_at: SystemTime,
    source: Option<SourceSnapshot>,
    records: Option<File>,
    record_count: u64,
}

impl CacheStaging {
    pub(super) fn create(
        store: CacheStore,
        format: SourceFormat,
        audit: CacheAudit,
        now: SystemTime,
    ) -> Result<Self, CacheError> {
        // Keep GC from observing the small interval between directory creation
        // and establishing the per-staging exclusive lease.
        let gc_lock = store.acquire_gc_lock()?;
        let cache_id = ulid::Ulid::new().to_string();
        let directory = tempfile::Builder::new()
            .prefix(&format!("{cache_id}."))
            .tempdir_in(store.staging_root())
            .map_err(|source| io_error("create cache staging", store.staging_root(), source))?;
        set_private_directory_permissions(directory.path())?;
        let lock = open_private_lock(&directory.path().join("access.lock"))?;
        FileExt::try_lock_exclusive(&lock).map_err(|source| {
            io_error(
                "lock new cache staging",
                directory.path().join("access.lock"),
                source,
            )
        })?;
        let records_path = directory.path().join(STAGED_INDEX_RECORDS);
        let records = create_private_file(&records_path)?;
        drop(gc_lock);
        Ok(Self {
            store,
            directory,
            lock: Some(lock),
            cache_id,
            format,
            audit,
            created_at: now,
            source: None,
            records: Some(records),
            record_count: 0,
        })
    }

    #[must_use]
    pub fn cache_id(&self) -> &str {
        &self.cache_id
    }

    #[must_use]
    pub fn source_path(&self) -> PathBuf {
        self.path().join(self.format.file_name())
    }

    pub fn stage_source(&mut self, mut source: impl Read) -> Result<u64, CacheError> {
        if self.source.is_some() {
            return Err(CacheError::Verification(
                "cache source was already staged".to_owned(),
            ));
        }
        let path = self.source_path();
        let mut output = create_private_file(&path)?;
        let mut hasher = Sha256::new();
        let mut total = 0_u64;
        let mut buffer = [0_u8; 64 * 1024];
        loop {
            let count = source
                .read(&mut buffer)
                .map_err(|source| io_error("read native cache source", &path, source))?;
            if count == 0 {
                break;
            }
            let count_u64 = u64::try_from(count)
                .map_err(|error| CacheError::Verification(error.to_string()))?;
            total = total
                .checked_add(count_u64)
                .ok_or_else(|| CacheError::Verification("source size overflow".to_owned()))?;
            if total > self.store.limits().max_entry_bytes {
                return Err(CacheError::EntryTooLarge {
                    limit: self.store.limits().max_entry_bytes,
                });
            }
            output
                .write_all(&buffer[..count])
                .map_err(|source| io_error("write native cache source", &path, source))?;
            hasher.update(&buffer[..count]);
        }
        output
            .flush()
            .map_err(|source| io_error("flush native cache source", &path, source))?;
        output
            .sync_all()
            .map_err(|source| io_error("sync native cache source", &path, source))?;
        self.source = Some(SourceSnapshot {
            bytes: total,
            sha256: hex_lower(&hasher.finalize()),
        });
        Ok(total)
    }

    pub fn add_source_record(&mut self, record: &SourceRecord) -> Result<(), CacheError> {
        self.add_index_record(CacheIndexRecord::from_source(record))
    }

    pub fn add_index_record(&mut self, record: CacheIndexRecord) -> Result<(), CacheError> {
        if self.source.is_none() {
            return Err(CacheError::InvalidIndex(
                "source bytes must be staged before indexing".to_owned(),
            ));
        }
        let expected = self.record_count;
        if record.id != expected {
            return Err(CacheError::InvalidIndex(format!(
                "record id {} is not contiguous expected {expected}",
                record.id
            )));
        }
        let path = self.path().join(STAGED_INDEX_RECORDS);
        let output = self.records.as_mut().ok_or_else(|| {
            CacheError::Verification("cache index record spool is closed".to_owned())
        })?;
        serde_json::to_writer(&mut *output, &record.to_value())
            .map_err(|error| CacheError::Serialization(error.to_string()))?;
        output
            .write_all(b"\n")
            .map_err(|source| io_error("write staged cache index record", &path, source))?;
        self.record_count = self
            .record_count
            .checked_add(1)
            .ok_or_else(|| CacheError::InvalidIndex("record count overflow".to_owned()))?;
        Ok(())
    }

    pub fn commit(
        mut self,
        process: CacheProcess,
        now: SystemTime,
    ) -> Result<CommittedCache, CacheError> {
        if process.failure.is_some() {
            return Err(CacheError::Verification(
                "incomplete process state cannot be committed".to_owned(),
            ));
        }
        let source = self
            .source
            .clone()
            .ok_or_else(|| CacheError::Verification("cache source is missing".to_owned()))?;
        self.finish_record_spool()?;
        self.validate_source_and_index(&source)?;
        self.verify_source_fingerprints()?;

        let gc_lock = self.store.acquire_gc_lock()?;
        let selected_id = self.store.available_id_locked(&self.cache_id)?;
        self.cache_id = selected_id;
        self.write_index(&source)?;
        fs::remove_file(self.path().join(STAGED_INDEX_RECORDS)).map_err(|source| {
            io_error(
                "remove staged cache index records",
                self.path().join(STAGED_INDEX_RECORDS),
                source,
            )
        })?;
        self.write_metadata("committed", &source, &process, now)?;
        sync_directory(self.path())?;
        if hash_file(&self.source_path())? != source {
            return Err(CacheError::Verification(
                "staged source changed after index/metadata generation".to_owned(),
            ));
        }
        let entry_bytes = directory_size(self.path())?;
        if entry_bytes > self.store.limits().max_entry_bytes {
            return Err(CacheError::EntryTooLarge {
                limit: self.store.limits().max_entry_bytes,
            });
        }
        self.store.reserve_locked(now, entry_bytes)?;
        let final_path = self.store.entry_path(&self.cache_id)?;
        if final_path.exists() {
            return Err(CacheError::Conflict(self.cache_id.clone()));
        }
        self.release_staging_lock("unlock cache staging before commit")?;
        fs::rename(self.path(), &final_path)
            .map_err(|source| io_error("atomically commit cache entry", &final_path, source))?;
        sync_directory(self.store.root())?;
        drop(gc_lock);
        Ok(CommittedCache {
            cache_id: self.cache_id.clone(),
            path: final_path,
            source_format: self.format,
            source_bytes: source.bytes,
            source_sha256: source.sha256,
            record_count: self.record_count,
        })
    }

    pub fn mark_incomplete(
        mut self,
        process: CacheProcess,
        now: SystemTime,
    ) -> Result<PathBuf, CacheError> {
        if process.failure.is_none() {
            return Err(CacheError::Verification(
                "incomplete entry requires a failure category".to_owned(),
            ));
        }
        self.finish_record_spool()?;
        let staged_records = self.path().join(STAGED_INDEX_RECORDS);
        if staged_records.exists() {
            fs::remove_file(&staged_records).map_err(|source| {
                io_error(
                    "remove incomplete cache index spool",
                    &staged_records,
                    source,
                )
            })?;
        }
        if self.source.is_none() {
            self.stage_source(io::empty())?;
        }
        let source = self
            .source
            .clone()
            .ok_or_else(|| CacheError::Verification("cache source is missing".to_owned()))?;
        self.write_metadata("incomplete", &source, &process, now)?;
        sync_directory(self.path())?;
        let name = self
            .path()
            .file_name()
            .ok_or_else(|| CacheError::UnsafePath(self.path().to_path_buf()))?;
        let final_path = self.store.incomplete_root().join(name);
        if final_path.exists() {
            return Err(CacheError::Conflict(self.cache_id.clone()));
        }
        let gc_lock = self.store.acquire_gc_lock()?;
        self.release_staging_lock("unlock cache staging before retaining incomplete entry")?;
        fs::rename(self.path(), &final_path)
            .map_err(|source| io_error("retain incomplete cache entry", &final_path, source))?;
        drop(gc_lock);
        Ok(final_path)
    }

    fn path(&self) -> &Path {
        self.directory.path()
    }

    fn finish_record_spool(&mut self) -> Result<(), CacheError> {
        let Some(mut records) = self.records.take() else {
            return Ok(());
        };
        let path = self.path().join(STAGED_INDEX_RECORDS);
        records
            .flush()
            .map_err(|source| io_error("flush cache index record spool", &path, source))?;
        records
            .sync_all()
            .map_err(|source| io_error("sync cache index record spool", &path, source))?;
        drop(records);
        Ok(())
    }

    fn staged_records(
        &self,
    ) -> Result<impl Iterator<Item = Result<CacheIndexRecord, CacheError>>, CacheError> {
        let path = self.path().join(STAGED_INDEX_RECORDS);
        let input = File::open(&path)
            .map_err(|source| io_error("open staged cache index records", &path, source))?;
        Ok(JsonLines::new(BufReader::new(input)).map(|record| {
            let record = record.map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
            let position = usize::try_from(record.ordinal)
                .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
            parse_index_record(position, &record.value)
        }))
    }

    fn release_staging_lock(&mut self, operation: &'static str) -> Result<(), CacheError> {
        let Some(lock) = self.lock.take() else {
            return Ok(());
        };
        FileExt::unlock(&lock)
            .map_err(|source| io_error(operation, self.path().join("access.lock"), source))?;
        drop(lock);
        Ok(())
    }

    fn validate_source_and_index(&self, source: &SourceSnapshot) -> Result<(), CacheError> {
        let actual = hash_file(&self.source_path())?;
        if &actual != source {
            return Err(CacheError::Verification(
                "staged source hash or size changed before commit".to_owned(),
            ));
        }
        match self.format {
            SourceFormat::JsonLines => {
                let input = File::open(self.source_path()).map_err(|source| {
                    io_error(
                        "open JSONL cache source for index validation",
                        self.source_path(),
                        source,
                    )
                })?;
                let mut records = self.staged_records()?;
                let mut count = 0_u64;
                for parsed in JsonLines::new(BufReader::new(input)) {
                    let parsed =
                        parsed.map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
                    let indexed = records.next().transpose()?.ok_or_else(|| {
                        CacheError::InvalidIndex(format!(
                            "JSONL source record {} is missing from index",
                            parsed.ordinal
                        ))
                    })?;
                    if indexed != CacheIndexRecord::from_source(&parsed) {
                        return Err(CacheError::InvalidIndex(format!(
                            "JSONL index record {} does not match native source",
                            parsed.ordinal
                        )));
                    }
                    count = count.checked_add(1).ok_or_else(|| {
                        CacheError::InvalidIndex("record count overflow".to_owned())
                    })?;
                }
                if count != self.record_count || records.next().transpose()?.is_some() {
                    return Err(CacheError::InvalidIndex(format!(
                        "JSONL index has {} records but source has {count}",
                        self.record_count
                    )));
                }
            }
            SourceFormat::JsonValue => {
                let bytes = fs::read(self.source_path()).map_err(|source| {
                    io_error("read JSON value cache source", self.source_path(), source)
                })?;
                let parsed = parse_single_json(&bytes)
                    .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
                let mut records = self.staged_records()?;
                if self.record_count != 1
                    || records.next().transpose()?.as_ref()
                        != Some(&CacheIndexRecord::from_source(&parsed))
                    || records.next().transpose()?.is_some()
                {
                    return Err(CacheError::InvalidIndex(
                        "json-value source requires exactly one full-value index record".to_owned(),
                    ));
                }
            }
            SourceFormat::JsonArray => {
                let bytes = fs::read(self.source_path()).map_err(|source| {
                    io_error("read JSON array cache source", self.source_path(), source)
                })?;
                let parsed = parse_single_json(&bytes)
                    .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
                let array = parsed.value.as_array().ok_or_else(|| {
                    CacheError::InvalidIndex("json-array source is not an array".to_owned())
                })?;
                if u64::try_from(array.len()).unwrap_or(u64::MAX) != self.record_count {
                    return Err(CacheError::InvalidIndex(format!(
                        "JSON array has {} records but index has {}",
                        array.len(),
                        self.record_count
                    )));
                }
                let mut records = self.staged_records()?;
                for (position, value) in array.iter().enumerate() {
                    let expected = CacheIndexRecord::with_pointer(
                        position as u64,
                        format!("/{position}"),
                        value,
                    );
                    if records.next().transpose()?.as_ref() != Some(&expected) {
                        return Err(CacheError::InvalidIndex(format!(
                            "JSON array index record {position} does not match native source"
                        )));
                    }
                }
                if records.next().transpose()?.is_some() {
                    return Err(CacheError::InvalidIndex(
                        "JSON array index has trailing records".to_owned(),
                    ));
                }
            }
            SourceFormat::Sarif => {
                let bytes = fs::read(self.source_path()).map_err(|source| {
                    io_error("read SARIF cache source", self.source_path(), source)
                })?;
                let parsed = parse_single_json(&bytes)
                    .map_err(|error| CacheError::InvalidIndex(error.to_string()))?;
                let mut records = self.staged_records()?;
                let mut position = 0_u64;
                if let Some(runs) = parsed.value.get("runs").and_then(Value::as_array) {
                    for (run_index, run) in runs.iter().enumerate() {
                        if let Some(results) = run.get("results").and_then(Value::as_array) {
                            for (result_index, value) in results.iter().enumerate() {
                                let expected = CacheIndexRecord::with_sarif_pointer(
                                    position,
                                    format!("/runs/{run_index}/results/{result_index}"),
                                    value,
                                );
                                if records.next().transpose()?.as_ref() != Some(&expected) {
                                    return Err(CacheError::InvalidIndex(format!(
                                        "SARIF index record {position} does not match native source"
                                    )));
                                }
                                position = position.checked_add(1).ok_or_else(|| {
                                    CacheError::InvalidIndex("record count overflow".to_owned())
                                })?;
                            }
                        }
                    }
                }
                if position != self.record_count || records.next().transpose()?.is_some() {
                    return Err(CacheError::InvalidIndex(
                        "SARIF index must cover runs[].results[] in native order".to_owned(),
                    ));
                }
            }
        }
        if source.bytes == 0 && self.record_count != 0 {
            return Err(CacheError::InvalidIndex(
                "empty source cannot have indexed records".to_owned(),
            ));
        }
        Ok(())
    }

    fn write_index(&self, source: &SourceSnapshot) -> Result<(), CacheError> {
        let mut index = Map::new();
        index.insert(
            "schema".to_owned(),
            Value::String(CACHE_INDEX_SCHEMA.to_owned()),
        );
        index.insert("cache_id".to_owned(), Value::String(self.cache_id.clone()));
        index.insert(
            "source_format".to_owned(),
            Value::String(self.format.as_str().to_owned()),
        );
        index.insert(
            "source_sha256".to_owned(),
            Value::String(source.sha256.clone()),
        );
        index.insert("record_count".to_owned(), Value::from(self.record_count));
        let mut header = serde_json::to_vec(&Value::Object(index))
            .map_err(|error| CacheError::Serialization(error.to_string()))?;
        if header.pop() != Some(b'}') {
            return Err(CacheError::Serialization(
                "cache index header is not a JSON object".to_owned(),
            ));
        }
        let path = self.path().join("index.json");
        let mut output = create_private_file(&path)?;
        output
            .write_all(&header)
            .and_then(|()| output.write_all(b",\"records\":[\n"))
            .map_err(|source| io_error("write cache index header", &path, source))?;
        let mut count = 0_u64;
        for record in self.staged_records()? {
            let record = record?;
            serde_json::to_writer(&mut output, &record.to_value())
                .map_err(|error| CacheError::Serialization(error.to_string()))?;
            count = count
                .checked_add(1)
                .ok_or_else(|| CacheError::Serialization("record count overflow".to_owned()))?;
            if count < self.record_count {
                output
                    .write_all(b",\n")
                    .map_err(|source| io_error("write cache index separator", &path, source))?;
            }
        }
        if count != self.record_count {
            return Err(CacheError::InvalidIndex(format!(
                "cache index spool has {count} records expected {}",
                self.record_count
            )));
        }
        output
            .write_all(if count == 0 { b"]}\n" } else { b"\n]}\n" })
            .map_err(|source| io_error("finish cache index", &path, source))?;
        output
            .flush()
            .map_err(|source| io_error("flush cache index", &path, source))?;
        output
            .sync_all()
            .map_err(|source| io_error("sync cache index", &path, source))
    }

    fn write_metadata(
        &self,
        state: &str,
        source: &SourceSnapshot,
        process: &CacheProcess,
        now: SystemTime,
    ) -> Result<(), CacheError> {
        let lifetime = if state == "incomplete" {
            self.store.limits().incomplete_ttl
        } else {
            self.store.limits().ttl
        };
        let expires_at = now
            .checked_add(lifetime)
            .ok_or_else(|| CacheError::InvalidTime("expiry overflow".to_owned()))?;
        let mut engine = Map::new();
        engine.insert(
            "path".to_owned(),
            Value::String(path_text(&self.audit.engine_path)),
        );
        engine.insert(
            "version".to_owned(),
            Value::String(self.audit.engine_version.clone()),
        );

        let mut invocation = Map::new();
        invocation.insert(
            "user_argv_sha256".to_owned(),
            Value::String(self.audit.user_argv_sha256.clone()),
        );

        let source_fingerprints = Value::Array(
            self.audit
                .source_fingerprints
                .iter()
                .map(super::SourceFingerprint::to_value)
                .collect(),
        );
        invocation.insert(
            "effective_argv_sha256".to_owned(),
            Value::String(self.audit.effective_argv_sha256.clone()),
        );
        invocation.insert(
            "injected".to_owned(),
            Value::Array(
                self.audit
                    .injected
                    .iter()
                    .cloned()
                    .map(Value::String)
                    .collect(),
            ),
        );
        invocation.insert(
            "profile".to_owned(),
            Value::String(self.audit.profile.as_str().to_owned()),
        );
        invocation.insert(
            "cache_mode".to_owned(),
            Value::String(self.audit.cache_mode.as_str().to_owned()),
        );

        let mut source_value = Map::new();
        source_value.insert(
            "format".to_owned(),
            Value::String(self.format.as_str().to_owned()),
        );
        source_value.insert(
            "file".to_owned(),
            Value::String(self.format.file_name().to_owned()),
        );
        source_value.insert("bytes".to_owned(), Value::from(source.bytes));
        source_value.insert("sha256".to_owned(), Value::String(source.sha256.clone()));
        source_value.insert("records".to_owned(), Value::from(self.record_count));

        let mut process_value = Map::new();
        process_value.insert(
            "exit_code".to_owned(),
            process.exit_code.map_or(Value::Null, Value::from),
        );
        if let Some(failure) = &process.failure {
            process_value.insert("failure".to_owned(), Value::String(failure.clone()));
        }

        let mut metadata = Map::new();
        metadata.insert(
            "schema".to_owned(),
            Value::String(CACHE_METADATA_SCHEMA.to_owned()),
        );
        metadata.insert("cache_id".to_owned(), Value::String(self.cache_id.clone()));
        metadata.insert("state".to_owned(), Value::String(state.to_owned()));
        metadata.insert(
            "created_at".to_owned(),
            Value::String(format_time(self.created_at)?),
        );
        metadata.insert(
            "last_access_at".to_owned(),
            Value::String(format_time(now)?),
        );
        metadata.insert(
            "expires_at".to_owned(),
            Value::String(format_time(expires_at)?),
        );
        metadata.insert("engine".to_owned(), Value::Object(engine));
        metadata.insert("cwd".to_owned(), Value::String(path_text(&self.audit.cwd)));
        metadata.insert("invocation".to_owned(), Value::Object(invocation));
        metadata.insert("source_fingerprints".to_owned(), source_fingerprints);
        metadata.insert("source".to_owned(), Value::Object(source_value));
        metadata.insert("process".to_owned(), Value::Object(process_value));

        let path = self.path().join("metadata.yaml");
        let mut output = create_private_file(&path)?;
        write_yaml_document(&Value::Object(metadata), &mut output, false)
            .map_err(|error| CacheError::Serialization(error.to_string()))?;
        output
            .flush()
            .map_err(|source| io_error("flush cache metadata", &path, source))?;
        output
            .sync_all()
            .map_err(|source| io_error("sync cache metadata", &path, source))
    }

    fn verify_source_fingerprints(&self) -> Result<(), CacheError> {
        for expected in &self.audit.source_fingerprints {
            let actual =
                super::SourceFingerprint::capture(&self.audit.cwd, Path::new(&expected.file))?;
            if &actual != expected {
                return Err(CacheError::Verification(format!(
                    "fingerprint source {:?} changed during ast-grep execution",
                    expected.file
                )));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedCache {
    pub cache_id: String,
    pub path: PathBuf,
    pub source_format: SourceFormat,
    pub source_bytes: u64,
    pub source_sha256: String,
    pub record_count: u64,
}

fn hash_file(path: &Path) -> Result<SourceSnapshot, CacheError> {
    let mut input = BufReader::new(
        File::open(path).map_err(|source| io_error("open cache source for hash", path, source))?,
    );
    let mut hasher = Sha256::new();
    let mut bytes = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = input
            .read(&mut buffer)
            .map_err(|source| io_error("hash cache source", path, source))?;
        if count == 0 {
            break;
        }
        bytes = bytes
            .checked_add(
                u64::try_from(count)
                    .map_err(|error| CacheError::Verification(error.to_string()))?,
            )
            .ok_or_else(|| CacheError::Verification("source size overflow".to_owned()))?;
        hasher.update(&buffer[..count]);
    }
    Ok(SourceSnapshot {
        bytes,
        sha256: hex_lower(&hasher.finalize()),
    })
}

fn create_private_file(path: &Path) -> Result<File, CacheError> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    options
        .open(path)
        .map_err(|source| io_error("create private cache file", path, source))
}

fn set_private_directory_permissions(_path: &Path) -> Result<(), CacheError> {
    Ok(())
}

fn directory_size(path: &Path) -> Result<u64, CacheError> {
    let mut total = 0_u64;
    for entry in
        fs::read_dir(path).map_err(|source| io_error("read cache staging size", path, source))?
    {
        let entry = entry.map_err(|source| io_error("read cache staging entry", path, source))?;
        let metadata = entry
            .file_type()
            .map_err(|source| io_error("inspect cache staging entry", entry.path(), source))?;
        if metadata.is_symlink() || !metadata.is_file() {
            return Err(CacheError::UnsafePath(entry.path()));
        }
        let bytes = entry
            .metadata()
            .map_err(|source| io_error("measure cache staging entry", entry.path(), source))?
            .len();
        total = total
            .checked_add(bytes)
            .ok_or_else(|| CacheError::Verification("cache entry size overflow".to_owned()))?;
    }
    Ok(total)
}

fn format_time(value: SystemTime) -> Result<String, CacheError> {
    Ok(humantime::format_rfc3339(value).to_string())
}

fn sync_directory(_path: &Path) -> Result<(), CacheError> {
    Ok(())
}
