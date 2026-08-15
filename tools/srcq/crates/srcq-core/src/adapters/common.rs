//! Shared bounded adapters for line-oriented paths and UTF-8 text stdout.

use std::{
    fs::File,
    io::{self, BufRead, BufReader, Read, Seek, SeekFrom, Write},
    path::Path,
};

use serde_json::{json, Value};
use tempfile::{NamedTempFile, TempDir};
use thiserror::Error;

use crate::{
    adapters::raw::{commit_stderr_sidecar, ArtifactError, StderrSidecarPlan},
    budget::{BudgetError, BudgetSettings},
    codec::{write_yaml_document, CodecError},
    process::{run, ProcessError, ProcessOutcome, ProcessRequest},
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum BoundedShape {
    Files,
    Text,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct BoundedAdapterSpec {
    pub schema: &'static str,
    pub kind: &'static str,
    pub temp_prefix: &'static str,
    pub shape: BoundedShape,
    pub write_apply: bool,
}

#[derive(Debug)]
pub(super) struct BoundedAdapterRequest {
    pub process: ProcessRequest,
    pub budget: BudgetSettings,
    pub spec: BoundedAdapterSpec,
    pub stderr_sidecar: Option<StderrSidecarPlan>,
}

#[derive(Debug)]
pub struct StagedAdapterYaml {
    _directory: TempDir,
    file: NamedTempFile,
}

impl StagedAdapterYaml {
    #[must_use]
    pub fn path(&self) -> &Path {
        self.file.path()
    }

    pub fn open(&self) -> io::Result<File> {
        File::open(self.file.path())
    }

    pub fn read(&self) -> io::Result<Vec<u8>> {
        std::fs::read(self.file.path())
    }
}

#[derive(Debug)]
pub struct BoundedAdapterOutcome {
    pub process: ProcessOutcome,
    pub yaml: Option<StagedAdapterYaml>,
}

#[derive(Debug, Error)]
pub enum BoundedAdapterError {
    #[error(transparent)]
    Process(#[from] ProcessError),
    #[error(transparent)]
    Codec(#[from] CodecError),
    #[error(transparent)]
    Budget(#[from] BudgetError),
    #[error(transparent)]
    Artifact(#[from] ArtifactError),
}

impl BoundedAdapterError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Process(error) => error.wrapper_exit_code(),
            Self::Codec(error) => error.wrapper_exit_code(),
            Self::Budget(error) => error.wrapper_exit_code(),
            Self::Artifact(error) => error.wrapper_exit_code(),
        }
    }
}

pub(super) fn run_bounded_adapter(
    request: BoundedAdapterRequest,
) -> Result<BoundedAdapterOutcome, BoundedAdapterError> {
    let process = run(request.process)?;
    if process.cancellation.is_none() {
        commit_stderr_sidecar(request.stderr_sidecar, process.output.stderr_path())?;
    }
    if process.cancellation.is_some()
        || (process.exit_code() != 0
            && (request.spec.write_apply || process.output.stdout_bytes == 0))
    {
        return Ok(BoundedAdapterOutcome {
            process,
            yaml: None,
        });
    }
    let value = match request.spec.shape {
        BoundedShape::Files => {
            let stdout = process.output.open_stdout().map_err(CodecError::InputIo)?;
            let detail_limit = usize::try_from(request.budget.max_detail_results())
                .map_err(|error| CodecError::Encode(error.to_string()))?;
            let (files, total) = read_files(BufReader::new(stdout), detail_limit)?;
            render_files(&files, total, request.budget, request.spec)?
        }
        BoundedShape::Text => {
            let stdout = process.output.open_stdout().map_err(CodecError::InputIo)?;
            let configured = usize::try_from(request.budget.max_text_chars())
                .map_err(|error| CodecError::Encode(error.to_string()))?;
            let (preview, total_chars) = read_text_preview(stdout, configured)?;
            let applied_changes = if request.spec.write_apply {
                read_applied_changes(process.output.stderr_path())?
            } else {
                None
            };
            render_text(
                &preview,
                total_chars,
                request.budget,
                request.spec,
                applied_changes,
            )?
        }
    };
    let yaml = stage_yaml(&value, request.spec.temp_prefix)?;
    Ok(BoundedAdapterOutcome {
        process,
        yaml: Some(yaml),
    })
}

fn render_files(
    files: &[String],
    total: u64,
    budget: BudgetSettings,
    spec: BoundedAdapterSpec,
) -> Result<Value, BoundedAdapterError> {
    let mut shown = files.len();
    loop {
        let value = files_document(&files[..shown], total, spec);
        if encoded_len(&value)? <= budget.max_context_bytes() {
            return Ok(value);
        }
        if shown == 0 {
            return Err(BudgetError::Minimum {
                limit_bytes: budget.max_context_bytes(),
                measured_bytes: encoded_len(&value)?,
            }
            .into());
        }
        shown -= 1;
    }
}

fn files_document(files: &[String], total: u64, spec: BoundedAdapterSpec) -> Value {
    let shown = u64::try_from(files.len()).unwrap_or(u64::MAX);
    let omitted = total.saturating_sub(shown);
    json!({
        "_sgy": {
            "schema": spec.schema,
            "kind": spec.kind,
            "total": total,
            "shown": shown,
            "omitted": omitted,
            "complete": omitted == 0,
        },
        "files": files,
    })
}

pub(super) fn render_text(
    preview: &str,
    total_chars: usize,
    budget: BudgetSettings,
    spec: BoundedAdapterSpec,
    applied_changes: Option<u64>,
) -> Result<Value, BoundedAdapterError> {
    let upper = preview.chars().count();
    let mut low = 0_usize;
    let mut high = upper;
    let mut best = None;
    while low <= high {
        let middle = low + (high - low) / 2;
        let candidate: String = preview.chars().take(middle).collect();
        let value = text_document(candidate, total_chars, middle, spec, applied_changes);
        if encoded_len(&value)? <= budget.max_context_bytes() {
            best = Some(value);
            low = middle.saturating_add(1);
        } else if middle == 0 {
            break;
        } else {
            high = middle - 1;
        }
    }
    best.ok_or_else(|| {
        let minimum = text_document(String::new(), total_chars, 0, spec, applied_changes);
        let required = encoded_len(&minimum).unwrap_or(u64::MAX);
        BoundedAdapterError::Budget(BudgetError::Minimum {
            limit_bytes: budget.max_context_bytes(),
            measured_bytes: required,
        })
    })
}

fn read_files(
    mut input: impl BufRead,
    detail_limit: usize,
) -> Result<(Vec<String>, u64), BoundedAdapterError> {
    let mut files = Vec::with_capacity(detail_limit);
    let mut total = 0_u64;
    let mut byte_offset = 0_u64;
    let mut line = Vec::new();
    loop {
        line.clear();
        let count = input
            .read_until(b'\n', &mut line)
            .map_err(CodecError::InputIo)?;
        if count == 0 {
            break;
        }
        if line.last() == Some(&b'\n') {
            line.pop();
            if line.last() == Some(&b'\r') {
                line.pop();
            }
        }
        let path = std::str::from_utf8(&line).map_err(|error| CodecError::InvalidUtf8 {
            byte_offset: byte_offset.saturating_add(error.valid_up_to() as u64),
        })?;
        total = total
            .checked_add(1)
            .ok_or_else(|| CodecError::Encode("native file count overflow".to_owned()))?;
        if files.len() < detail_limit {
            files.push(path.to_owned());
        }
        byte_offset = byte_offset
            .checked_add(
                u64::try_from(count).map_err(|error| CodecError::Encode(error.to_string()))?,
            )
            .ok_or_else(|| CodecError::Encode("native file byte offset overflow".to_owned()))?;
    }
    Ok((files, total))
}

pub(super) fn read_text_preview(
    mut input: impl Read,
    preview_limit: usize,
) -> Result<(String, usize), BoundedAdapterError> {
    let mut preview = String::new();
    let mut total_chars = 0_usize;
    let mut pending = Vec::with_capacity(8195);
    let mut buffer = [0_u8; 8192];
    let mut byte_offset = 0_u64;
    loop {
        let count = input.read(&mut buffer).map_err(CodecError::InputIo)?;
        if count > 0 {
            pending.extend_from_slice(&buffer[..count]);
        }
        loop {
            match std::str::from_utf8(&pending) {
                Ok(text) => {
                    append_text(text, preview_limit, &mut preview, &mut total_chars)?;
                    byte_offset = byte_offset
                        .checked_add(
                            u64::try_from(pending.len())
                                .map_err(|error| CodecError::Encode(error.to_string()))?,
                        )
                        .ok_or_else(|| {
                            CodecError::Encode("native text byte offset overflow".to_owned())
                        })?;
                    pending.clear();
                    break;
                }
                Err(error) if error.valid_up_to() > 0 => {
                    let valid = error.valid_up_to();
                    let text = std::str::from_utf8(&pending[..valid]).map_err(|nested| {
                        CodecError::InvalidUtf8 {
                            byte_offset: byte_offset.saturating_add(nested.valid_up_to() as u64),
                        }
                    })?;
                    append_text(text, preview_limit, &mut preview, &mut total_chars)?;
                    pending.drain(..valid);
                    byte_offset = byte_offset
                        .checked_add(
                            u64::try_from(valid)
                                .map_err(|nested| CodecError::Encode(nested.to_string()))?,
                        )
                        .ok_or_else(|| {
                            CodecError::Encode("native text byte offset overflow".to_owned())
                        })?;
                }
                Err(error) if error.error_len().is_some() => {
                    return Err(CodecError::InvalidUtf8 {
                        byte_offset: byte_offset.saturating_add(error.valid_up_to() as u64),
                    }
                    .into());
                }
                Err(_) => break,
            }
        }
        if count == 0 {
            if pending.is_empty() {
                return Ok((preview, total_chars));
            }
            return Err(CodecError::InvalidUtf8 { byte_offset }.into());
        }
    }
}

fn append_text(
    text: &str,
    preview_limit: usize,
    preview: &mut String,
    total_chars: &mut usize,
) -> Result<(), BoundedAdapterError> {
    for character in text.chars() {
        if *total_chars < preview_limit {
            preview.push(character);
        }
        *total_chars = total_chars
            .checked_add(1)
            .ok_or_else(|| CodecError::Encode("native text character count overflow".to_owned()))?;
    }
    Ok(())
}

fn text_document(
    stdout: String,
    total_chars: usize,
    shown_chars: usize,
    spec: BoundedAdapterSpec,
    applied_changes: Option<u64>,
) -> Value {
    if spec.write_apply {
        return json!({
            "_sgy": {
                "schema": spec.schema,
                "kind": "update-all",
                "stdout_chars": u64::try_from(total_chars).unwrap_or(u64::MAX),
                "stdout_shown_chars": u64::try_from(shown_chars).unwrap_or(u64::MAX),
                "stdout_complete": shown_chars == total_chars,
                "write": {
                    "requested": "apply",
                    "applied_changes": applied_changes,
                    "affected_files": null,
                    "affected_files_complete": false,
                    "result_detail": if applied_changes.is_some() {
                        "applied_count_from_native_stderr; affected_files_require_preview"
                    } else {
                        "native_stderr_did_not_report_applied_count; affected_files_require_preview"
                    },
                    "transactional": false,
                },
            },
            "stdout": stdout,
        });
    }
    json!({
        "_sgy": {
            "schema": spec.schema,
            "kind": spec.kind,
            "total_chars": u64::try_from(total_chars).unwrap_or(u64::MAX),
            "shown_chars": u64::try_from(shown_chars).unwrap_or(u64::MAX),
            "complete": shown_chars == total_chars,
        },
        "stdout": stdout,
    })
}

fn read_applied_changes(path: &Path) -> Result<Option<u64>, BoundedAdapterError> {
    const TAIL_BYTES: u64 = 64 * 1024;
    let mut file = File::open(path).map_err(CodecError::InputIo)?;
    let length = file.metadata().map_err(CodecError::InputIo)?.len();
    if length > TAIL_BYTES {
        file.seek(SeekFrom::Start(length - TAIL_BYTES))
            .map_err(CodecError::InputIo)?;
    }
    let mut tail = Vec::new();
    file.read_to_end(&mut tail).map_err(CodecError::InputIo)?;
    let text = String::from_utf8_lossy(&tail);
    Ok(text.lines().rev().find_map(parse_applied_changes_line))
}

fn parse_applied_changes_line(line: &str) -> Option<u64> {
    let count = line.trim().strip_prefix("Applied ")?;
    let count = count
        .strip_suffix(" changes")
        .or_else(|| count.strip_suffix(" change"))?;
    count.parse().ok()
}

fn encoded_len(value: &Value) -> Result<u64, CodecError> {
    let mut bytes = Vec::new();
    write_yaml_document(value, &mut bytes, false)?;
    u64::try_from(bytes.len()).map_err(|error| CodecError::Encode(error.to_string()))
}

pub(super) fn stage_yaml(
    value: &Value,
    temp_prefix: &str,
) -> Result<StagedAdapterYaml, BoundedAdapterError> {
    let directory = tempfile::Builder::new()
        .prefix(temp_prefix)
        .tempdir()
        .map_err(CodecError::OutputIo)?;
    let mut file = NamedTempFile::new_in(directory.path()).map_err(CodecError::OutputIo)?;
    write_yaml_document(value, file.as_file_mut(), false)?;
    file.as_file_mut().flush().map_err(CodecError::OutputIo)?;
    Ok(StagedAdapterYaml {
        _directory: directory,
        file,
    })
}

#[cfg(test)]
mod tests {
    use std::{fmt::Write as _, io::Cursor};

    use serde_json::json;

    use super::{
        read_files, read_text_preview, render_files, render_text, BoundedAdapterSpec, BoundedShape,
    };
    use crate::budget::BudgetSettings;

    const RUN_FILES: BoundedAdapterSpec = BoundedAdapterSpec {
        schema: "sgy.run/v1",
        kind: "files-with-matches",
        temp_prefix: "srcq-run-",
        shape: BoundedShape::Files,
        write_apply: false,
    };
    const RUN_TEXT: BoundedAdapterSpec = BoundedAdapterSpec {
        schema: "sgy.run/v1",
        kind: "text",
        temp_prefix: "srcq-run-",
        shape: BoundedShape::Text,
        write_apply: false,
    };

    #[test]
    fn files_are_counted_and_bounded_in_native_order() {
        let budget = BudgetSettings::new(2, 400, 24 * 1024).expect("budget");
        let (files, total) = read_files(
            Cursor::new("src/a.ts\r\nsrc/中文 b.ts\nthird.ts\n"),
            usize::try_from(budget.max_detail_results()).expect("detail limit"),
        )
        .expect("read files");
        let value = render_files(&files, total, budget, RUN_FILES).expect("files YAML value");
        assert_eq!(value["_sgy"]["total"], 3);
        assert_eq!(value["_sgy"]["shown"], 2);
        assert_eq!(value["_sgy"]["complete"], false);
        assert_eq!(value["files"], json!(["src/a.ts", "src/中文 b.ts"]));
    }

    #[test]
    fn text_uses_unicode_char_budget_and_marks_truncation() {
        let budget = BudgetSettings::new(40, 3, 24 * 1024).expect("budget");
        let (preview, total) =
            read_text_preview(Cursor::new("甲乙丙丁"), 3).expect("read text preview");
        let value = render_text(&preview, total, budget, RUN_TEXT, None).expect("text YAML value");
        assert_eq!(value["stdout"], "甲乙丙");
        assert_eq!(value["_sgy"]["total_chars"], 4);
        assert_eq!(value["_sgy"]["shown_chars"], 3);
        assert_eq!(value["_sgy"]["complete"], false);
    }

    #[test]
    fn streaming_readers_validate_complete_utf8_while_retaining_only_bounded_detail() {
        let mut paths = String::new();
        for index in 0..100 {
            writeln!(&mut paths, "src/{index}.ts").expect("write path fixture");
        }
        let (files, total) = read_files(Cursor::new(paths), 3).expect("stream files");
        assert_eq!(total, 100);
        assert_eq!(files.len(), 3);

        let text = "甲".repeat(10_000);
        let (preview, total) = read_text_preview(Cursor::new(text), 7).expect("stream text");
        assert_eq!(total, 10_000);
        assert_eq!(preview, "甲".repeat(7));

        assert!(read_text_preview(Cursor::new(vec![b'a', 0xff]), 10).is_err());
    }
}
