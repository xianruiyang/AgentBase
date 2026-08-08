use std::{
    cmp::Ordering,
    collections::BinaryHeap,
    fs::File,
    io::{BufRead, BufReader, Write},
};

use serde_json::{json, Value};
use tempfile::{NamedTempFile, TempDir};

use super::ProcessError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct ExternalSortLimits {
    pub chunk_bytes: usize,
    pub chunk_records: usize,
    pub max_runs: usize,
}

impl Default for ExternalSortLimits {
    fn default() -> Self {
        Self {
            chunk_bytes: 4 * 1024 * 1024,
            chunk_records: 10_000,
            max_runs: 512,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct SpoolRecord {
    pub key: String,
    pub identity: String,
    pub ordinal: u64,
    pub source_ids: Vec<String>,
    pub conflicts: u64,
    pub value: Value,
}

impl SpoolRecord {
    fn to_value(&self) -> Value {
        json!({
            "key": self.key,
            "identity": self.identity,
            "ordinal": self.ordinal,
            "source_ids": self.source_ids,
            "conflicts": self.conflicts,
            "value": self.value,
        })
    }

    fn from_value(value: Value) -> Result<Self, ProcessError> {
        let mut mapping = value.as_object().cloned().ok_or_else(|| {
            ProcessError::InvalidArgument("temporary sort record must be a mapping".to_owned())
        })?;
        let key = take_string(&mut mapping, "key")?;
        let identity = take_string(&mut mapping, "identity")?;
        let ordinal = mapping
            .remove("ordinal")
            .and_then(|value| value.as_u64())
            .ok_or_else(|| {
                ProcessError::InvalidArgument(
                    "temporary sort ordinal must be an unsigned integer".to_owned(),
                )
            })?;
        let source_ids = mapping
            .remove("source_ids")
            .and_then(|value| value.as_array().cloned())
            .ok_or_else(|| {
                ProcessError::InvalidArgument("temporary source_ids must be an array".to_owned())
            })?
            .into_iter()
            .map(|value| {
                value.as_str().map(ToOwned::to_owned).ok_or_else(|| {
                    ProcessError::InvalidArgument(
                        "temporary source_ids must contain strings".to_owned(),
                    )
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let conflicts = mapping
            .remove("conflicts")
            .and_then(|value| value.as_u64())
            .ok_or_else(|| {
                ProcessError::InvalidArgument(
                    "temporary conflicts must be an unsigned integer".to_owned(),
                )
            })?;
        let value = mapping.remove("value").ok_or_else(|| {
            ProcessError::InvalidArgument("temporary sort value is missing".to_owned())
        })?;
        Ok(Self {
            key,
            identity,
            ordinal,
            source_ids,
            conflicts,
            value,
        })
    }
}

fn take_string(
    mapping: &mut serde_json::Map<String, Value>,
    field: &str,
) -> Result<String, ProcessError> {
    mapping
        .remove(field)
        .and_then(|value| value.as_str().map(ToOwned::to_owned))
        .ok_or_else(|| {
            ProcessError::InvalidArgument(format!(
                "temporary sort field {field:?} must be a string"
            ))
        })
}

pub(super) struct ExternalSorter {
    _directory: TempDir,
    runs: Vec<NamedTempFile>,
    buffer: Vec<SpoolRecord>,
    buffer_bytes: usize,
    limits: ExternalSortLimits,
    descending: bool,
}

impl ExternalSorter {
    pub(super) fn new(limits: ExternalSortLimits, descending: bool) -> Result<Self, ProcessError> {
        Ok(Self {
            _directory: tempfile::Builder::new()
                .prefix("sgy-sort-")
                .tempdir()
                .map_err(ProcessError::Temporary)?,
            runs: Vec::new(),
            buffer: Vec::new(),
            buffer_bytes: 0,
            limits,
            descending,
        })
    }

    pub(super) fn push(&mut self, record: SpoolRecord) -> Result<(), ProcessError> {
        let bytes = serde_json::to_vec(&record.to_value())
            .map_err(|error| ProcessError::InvalidArgument(error.to_string()))?
            .len();
        self.buffer_bytes = self
            .buffer_bytes
            .checked_add(bytes)
            .ok_or_else(|| ProcessError::Limit("sort chunk byte count overflow".to_owned()))?;
        self.buffer.push(record);
        if self.buffer_bytes >= self.limits.chunk_bytes
            || self.buffer.len() >= self.limits.chunk_records
        {
            self.spill()?;
        }
        Ok(())
    }

    pub(super) fn finish(
        mut self,
        mut visitor: impl FnMut(SpoolRecord) -> Result<(), ProcessError>,
    ) -> Result<(), ProcessError> {
        if self.runs.is_empty() {
            sort_records(&mut self.buffer, self.descending);
            for record in self.buffer {
                visitor(record)?;
            }
            return Ok(());
        }
        if !self.buffer.is_empty() {
            self.spill()?;
        }
        let mut readers = self
            .runs
            .iter()
            .map(|run| {
                run.reopen()
                    .map(BufReader::new)
                    .map_err(ProcessError::Temporary)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut heap = BinaryHeap::new();
        for (run, reader) in readers.iter_mut().enumerate() {
            if let Some(record) = read_record(reader)? {
                heap.push(HeapEntry {
                    record,
                    run,
                    descending: self.descending,
                });
            }
        }
        while let Some(entry) = heap.pop() {
            let run = entry.run;
            visitor(entry.record)?;
            if let Some(record) = read_record(&mut readers[run])? {
                heap.push(HeapEntry {
                    record,
                    run,
                    descending: self.descending,
                });
            }
        }
        Ok(())
    }

    fn spill(&mut self) -> Result<(), ProcessError> {
        if self.buffer.is_empty() {
            return Ok(());
        }
        if self.runs.len() >= self.limits.max_runs {
            return Err(ProcessError::Limit(format!(
                "external sort run count exceeds {}",
                self.limits.max_runs
            )));
        }
        sort_records(&mut self.buffer, self.descending);
        let mut run =
            NamedTempFile::new_in(self._directory.path()).map_err(ProcessError::Temporary)?;
        for record in self.buffer.drain(..) {
            serde_json::to_writer(run.as_file_mut(), &record.to_value())
                .map_err(|error| ProcessError::InvalidArgument(error.to_string()))?;
            run.as_file_mut()
                .write_all(b"\n")
                .map_err(ProcessError::Temporary)?;
        }
        run.as_file_mut().flush().map_err(ProcessError::Temporary)?;
        self.runs.push(run);
        self.buffer_bytes = 0;
        Ok(())
    }
}

fn sort_records(records: &mut [SpoolRecord], descending: bool) {
    records.sort_by(|left, right| output_order(left, right, descending));
}

fn output_order(left: &SpoolRecord, right: &SpoolRecord, descending: bool) -> Ordering {
    let key = if descending {
        right.key.cmp(&left.key)
    } else {
        left.key.cmp(&right.key)
    };
    key.then_with(|| left.ordinal.cmp(&right.ordinal))
}

fn read_record(reader: &mut BufReader<File>) -> Result<Option<SpoolRecord>, ProcessError> {
    let mut line = Vec::new();
    let bytes = reader
        .read_until(b'\n', &mut line)
        .map_err(ProcessError::Temporary)?;
    if bytes == 0 {
        return Ok(None);
    }
    let value = serde_json::from_slice(&line)
        .map_err(|error| ProcessError::InvalidArgument(error.to_string()))?;
    SpoolRecord::from_value(value).map(Some)
}

#[derive(Debug)]
struct HeapEntry {
    record: SpoolRecord,
    run: usize,
    descending: bool,
}

impl Eq for HeapEntry {}

impl PartialEq for HeapEntry {
    fn eq(&self, other: &Self) -> bool {
        self.run == other.run && self.record == other.record
    }
}

impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        output_order(&other.record, &self.record, self.descending)
            .then_with(|| other.run.cmp(&self.run))
    }
}

impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
