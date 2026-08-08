//! Raw UTF-8 reports, byte-preserving artifacts, and explicit stderr sidecars.

use std::{
    ffi::{OsStr, OsString},
    fs::File,
    io::{self, BufReader, Read},
    path::{Path, PathBuf},
};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use thiserror::Error;

use super::common::{
    read_text_preview, render_text, stage_yaml, BoundedAdapterError, BoundedAdapterOutcome,
    BoundedAdapterSpec, BoundedShape,
};
use crate::{
    budget::BudgetSettings,
    codec::{write_yaml_document, CodecError},
    process::{run, OutputCommitError, PreparedOutput, ProcessError, ProcessRequest},
};

pub const RAW_SCHEMA: &str = "sgy.raw/v1";
pub const MANIFEST_SCHEMA: &str = "sgy.output-manifest/v1";
pub const STDERR_SCHEMA: &str = "sgy.stderr/v1";
const STDERR_INLINE_LIMIT: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RawKind {
    Test,
    New,
    Help,
    Version,
    Unknown,
}

#[must_use]
pub fn new_is_non_interactive(args: &[OsString]) -> bool {
    args.iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
        .any(|token| token == OsStr::new("-y") || token == OsStr::new("--yes"))
}

#[must_use]
pub fn has_debug_query(args: &[OsString]) -> bool {
    args.iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
        .filter_map(|token| token.to_str())
        .any(|token| token == "--debug-query" || token.starts_with("--debug-query="))
}

#[must_use]
pub fn has_interactive(args: &[OsString]) -> bool {
    args.iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
        .filter_map(|token| token.to_str())
        .any(|token| token == "-i" || token == "--interactive" || short_cluster_has(token, 'i'))
}

#[must_use]
pub fn has_terminal_output(args: &[OsString]) -> bool {
    args.iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
        .filter_map(|token| token.to_str())
        .any(|token| {
            token == "--help"
                || token.starts_with("--help=")
                || token == "--version"
                || token.starts_with("--version=")
                || short_cluster_has(token, 'h')
                || short_cluster_has(token, 'V')
        })
}

fn short_cluster_has(token: &str, target: char) -> bool {
    let Some(cluster) = token.strip_prefix('-') else {
        return false;
    };
    !cluster.is_empty()
        && cluster
            .chars()
            .all(|flag| matches!(flag, 'i' | 'U' | 'h' | 'V'))
        && cluster.contains(target)
}

#[must_use]
pub fn completion_media_type(args: &[OsString]) -> &'static str {
    match args.get(1).and_then(|value| value.to_str()) {
        Some("powershell") => "text/x-powershell",
        Some("bash" | "zsh") => "text/x-shellscript",
        Some("fish") => "text/x-fish",
        Some("elvish") => "text/x-elvish",
        _ => "application/octet-stream",
    }
}

impl RawKind {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Test => "test",
            Self::New => "new",
            Self::Help => "help",
            Self::Version => "version",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactSource {
    Stdout,
    Stderr,
}

#[derive(Debug)]
pub struct ArtifactPlan {
    pub output: PreparedOutput,
    pub media_type: &'static str,
    pub source: ArtifactSource,
}

#[derive(Debug)]
pub struct StderrSidecarPlan {
    manifest: PreparedOutput,
    raw: PreparedOutput,
}

impl StderrSidecarPlan {
    #[must_use]
    pub fn new(manifest: PreparedOutput, raw: PreparedOutput) -> Self {
        Self { manifest, raw }
    }

    #[must_use]
    pub fn paths(&self) -> [&Path; 2] {
        [self.manifest.path(), self.raw.path()]
    }
}

#[derive(Debug)]
pub struct RawAdapterRequest {
    pub process: ProcessRequest,
    pub budget: BudgetSettings,
    pub kind: RawKind,
    pub artifact: Option<ArtifactPlan>,
    pub stderr_sidecar: Option<StderrSidecarPlan>,
}

pub type RawAdapterOutcome = BoundedAdapterOutcome;

#[derive(Debug, Error)]
pub enum ArtifactError {
    #[error("cannot inspect artifact bytes: {0}")]
    Inspect(#[source] io::Error),
    #[error("artifact path cannot be represented in YAML UTF-8: {0:?}")]
    NonUnicodePath(PathBuf),
    #[error(transparent)]
    Commit(#[from] OutputCommitError),
    #[error(transparent)]
    Codec(#[from] CodecError),
}

impl ArtifactError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        127
    }
}

#[derive(Debug, Error)]
pub enum RawAdapterError {
    #[error(transparent)]
    Process(#[from] ProcessError),
    #[error(transparent)]
    Codec(#[from] CodecError),
    #[error(transparent)]
    Bounded(#[from] BoundedAdapterError),
    #[error(transparent)]
    Artifact(#[from] ArtifactError),
}

impl RawAdapterError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Process(error) => error.wrapper_exit_code(),
            Self::Codec(error) => error.wrapper_exit_code(),
            Self::Bounded(error) => error.wrapper_exit_code(),
            Self::Artifact(error) => error.wrapper_exit_code(),
        }
    }
}

pub fn run_raw_adapter(request: RawAdapterRequest) -> Result<RawAdapterOutcome, RawAdapterError> {
    let process = run(request.process)?;
    if process.cancellation.is_none() {
        commit_stderr_sidecar(request.stderr_sidecar, process.output.stderr_path())?;
    }
    if process.cancellation.is_some()
        || (process.output.stdout_bytes == 0 && process.exit_code() != 0)
    {
        return Ok(RawAdapterOutcome {
            process,
            yaml: None,
        });
    }

    let yaml = if let Some(artifact) = request.artifact {
        let source = match artifact.source {
            ArtifactSource::Stdout => process.output.stdout_path(),
            ArtifactSource::Stderr => process.output.stderr_path(),
        };
        let value = commit_artifact(source, artifact.output, artifact.media_type)?;
        Some(stage_yaml(&value, "sgy-artifact-")?)
    } else {
        let stdout = process.output.open_stdout().map_err(CodecError::InputIo)?;
        let configured = usize::try_from(request.budget.max_text_chars())
            .map_err(|error| CodecError::Encode(error.to_string()))?;
        let (preview, total_chars) = read_text_preview(stdout, configured)?;
        let value = render_text(
            &preview,
            total_chars,
            request.budget,
            BoundedAdapterSpec {
                schema: RAW_SCHEMA,
                kind: request.kind.as_str(),
                temp_prefix: "sgy-raw-",
                shape: BoundedShape::Text,
                write_apply: false,
            },
            None,
        )?;
        Some(stage_yaml(&value, "sgy-raw-")?)
    };
    Ok(RawAdapterOutcome { process, yaml })
}

pub fn commit_stderr_sidecar(
    plan: Option<StderrSidecarPlan>,
    source: &Path,
) -> Result<(), ArtifactError> {
    let Some(plan) = plan else {
        return Ok(());
    };
    let inspected = inspect_file(source, Some(STDERR_INLINE_LIMIT))?;
    let mut manifest = serde_json::Map::new();
    manifest.insert("schema".to_owned(), Value::String(STDERR_SCHEMA.to_owned()));
    manifest.insert("bytes".to_owned(), Value::from(inspected.bytes));
    manifest.insert("sha256".to_owned(), Value::String(inspected.sha256));
    manifest.insert(
        "encoding".to_owned(),
        Value::String(inspected.encoding.to_owned()),
    );
    if let Some(text) = inspected.inline_text {
        manifest.insert("text".to_owned(), Value::String(text));
    } else {
        let raw_path = yaml_path(plan.raw.path())?;
        plan.raw.commit_from_path(source)?;
        manifest.insert("raw_path".to_owned(), Value::String(raw_path));
    }
    let mut bytes = Vec::new();
    write_yaml_document(&Value::Object(manifest), &mut bytes, false)?;
    plan.manifest.commit_from_reader(bytes.as_slice())?;
    Ok(())
}

fn commit_artifact(
    source: &Path,
    output: PreparedOutput,
    media_type: &'static str,
) -> Result<Value, ArtifactError> {
    let inspected = inspect_file(source, None)?;
    let path = yaml_path(output.path())?;
    output.commit_from_path(source)?;
    Ok(json!({
        "schema": MANIFEST_SCHEMA,
        "kind": "artifact",
        "path": path,
        "bytes": inspected.bytes,
        "sha256": inspected.sha256,
        "media_type": media_type,
        "encoding": inspected.encoding,
    }))
}

struct Inspection {
    bytes: u64,
    sha256: String,
    encoding: &'static str,
    inline_text: Option<String>,
}

fn inspect_file(path: &Path, inline_limit: Option<usize>) -> Result<Inspection, ArtifactError> {
    let mut input = BufReader::new(File::open(path).map_err(ArtifactError::Inspect)?);
    let mut hasher = Sha256::new();
    let mut bytes = 0_u64;
    let mut captured = inline_limit.map(|_| Vec::new());
    let mut valid_utf8 = true;
    let mut pending = Vec::with_capacity(64 * 1024 + 4);
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = input.read(&mut buffer).map_err(ArtifactError::Inspect)?;
        if count == 0 {
            break;
        }
        let chunk = &buffer[..count];
        hasher.update(chunk);
        bytes = bytes
            .checked_add(
                u64::try_from(count)
                    .map_err(|error| ArtifactError::Inspect(io::Error::other(error.to_string())))?,
            )
            .ok_or_else(|| ArtifactError::Inspect(io::Error::other("artifact size overflow")))?;
        if let (Some(limit), Some(bytes)) = (inline_limit, captured.as_mut()) {
            if bytes.len().saturating_add(count) <= limit {
                bytes.extend_from_slice(chunk);
            } else {
                captured = None;
            }
        }
        if valid_utf8 {
            pending.extend_from_slice(chunk);
            validate_pending(&mut pending, &mut valid_utf8);
        }
    }
    if !pending.is_empty() {
        valid_utf8 = false;
    }
    let digest: [u8; 32] = hasher.finalize().into();
    let mut sha256 = String::with_capacity(64);
    for byte in digest {
        sha256.push_str(&format!("{byte:02x}"));
    }
    let inline_text = if valid_utf8 {
        captured
            .map(String::from_utf8)
            .transpose()
            .map_err(|error| ArtifactError::Inspect(io::Error::other(error.to_string())))?
    } else {
        None
    };
    Ok(Inspection {
        bytes,
        sha256,
        encoding: if valid_utf8 { "utf-8" } else { "binary" },
        inline_text,
    })
}

fn validate_pending(pending: &mut Vec<u8>, valid_utf8: &mut bool) {
    loop {
        match std::str::from_utf8(pending) {
            Ok(_) => {
                pending.clear();
                return;
            }
            Err(error) if error.valid_up_to() > 0 => {
                pending.drain(..error.valid_up_to());
            }
            Err(error) if error.error_len().is_some() => {
                *valid_utf8 = false;
                pending.clear();
                return;
            }
            Err(_) => return,
        }
    }
}

fn yaml_path(path: &Path) -> Result<String, ArtifactError> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| ArtifactError::NonUnicodePath(path.to_path_buf()))
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;
    use std::fs;

    use tempfile::tempdir;

    use super::{
        completion_media_type, has_debug_query, has_interactive, has_terminal_output, inspect_file,
        new_is_non_interactive, STDERR_INLINE_LIMIT,
    };

    #[test]
    fn inspection_hashes_and_classifies_utf8_without_lossy_conversion() {
        let directory = tempdir().expect("temporary directory");
        let utf8 = directory.path().join("utf8");
        fs::write(&utf8, "甲乙\n").expect("write UTF-8");
        let inspected = inspect_file(&utf8, Some(STDERR_INLINE_LIMIT)).expect("inspect UTF-8");
        assert_eq!(inspected.encoding, "utf-8");
        assert_eq!(inspected.inline_text.as_deref(), Some("甲乙\n"));
        assert_eq!(inspected.sha256.len(), 64);

        let binary = directory.path().join("binary");
        fs::write(&binary, [b'a', 0xff]).expect("write binary");
        let inspected = inspect_file(&binary, Some(STDERR_INLINE_LIMIT)).expect("inspect binary");
        assert_eq!(inspected.encoding, "binary");
        assert!(inspected.inline_text.is_none());

        let boundary = directory.path().join("boundary");
        let mut bytes = vec![b'a'; 65_535];
        bytes.extend_from_slice("甲".as_bytes());
        fs::write(&boundary, bytes).expect("write split UTF-8");
        let inspected = inspect_file(&boundary, None).expect("inspect split UTF-8");
        assert_eq!(inspected.encoding, "utf-8");
    }

    #[test]
    fn raw_flag_detection_respects_the_native_terminator() {
        let args = |values: &[&str]| values.iter().map(OsString::from).collect::<Vec<_>>();
        assert!(new_is_non_interactive(&args(&["new", "project", "-y"])));
        assert!(!new_is_non_interactive(&args(&["new", "--", "-y"])));
        assert!(has_debug_query(&args(&["run", "--debug-query=ast"])));
        assert!(!has_debug_query(&args(&["run", "--", "--debug-query=ast"])));
        assert!(has_interactive(&args(&["test", "-i"])));
        assert!(!has_interactive(&args(&["test", "--", "-i"])));
        assert!(has_interactive(&args(&["test", "-Ui"])));
        assert!(has_terminal_output(&args(&["new", "project", "-h"])));
        assert!(!has_terminal_output(&args(&["new", "project", "--", "-h"])));
        assert_eq!(
            completion_media_type(&args(&["completions", "powershell"])),
            "text/x-powershell"
        );
    }
}
