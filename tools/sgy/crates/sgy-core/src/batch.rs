//! Foundation batch adapter: native structured output to staged lossless YAML.

use std::{
    ffi::{OsStr, OsString},
    fs::File,
    io::{self, BufReader, Write},
    path::Path,
};

use tempfile::{NamedTempFile, TempDir};
use thiserror::Error;

use crate::{
    codec::{transcode_lossless, CodecError, JsonInputKind, TranscodeStats},
    process::{run, ProcessError, ProcessOutcome, ProcessRequest},
};

#[derive(Debug, Error)]
pub enum BatchError {
    #[error("native batch output is not JSON, JSONL, or SARIF JSON")]
    UnsupportedOutput,
    #[error(transparent)]
    Process(#[from] ProcessError),
    #[error(transparent)]
    Codec(#[from] CodecError),
}

impl BatchError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::UnsupportedOutput => 125,
            Self::Process(error) => error.wrapper_exit_code(),
            Self::Codec(error) => error.wrapper_exit_code(),
        }
    }
}

/// A complete YAML staging file. It is never exposed until all native output
/// has been parsed and serialized successfully.
#[derive(Debug)]
pub struct StagedYaml {
    _directory: TempDir,
    file: NamedTempFile,
    pub stats: TranscodeStats,
}

impl StagedYaml {
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
pub struct LosslessBatchOutcome {
    pub process: ProcessOutcome,
    pub yaml: Option<StagedYaml>,
}

/// Executes one native batch process and converts complete structured stdout
/// into private lossless YAML staging.
pub fn run_lossless_batch(
    request: ProcessRequest,
    input_kind: JsonInputKind,
) -> Result<LosslessBatchOutcome, BatchError> {
    let process = run(request)?;
    if process.cancellation.is_some()
        || (process.output.stdout_bytes == 0 && process.exit_code() != 0)
    {
        return Ok(LosslessBatchOutcome {
            process,
            yaml: None,
        });
    }

    let directory = tempfile::Builder::new()
        .prefix("sgy-yaml-")
        .tempdir()
        .map_err(CodecError::OutputIo)?;
    let mut file = NamedTempFile::new_in(directory.path()).map_err(CodecError::OutputIo)?;
    let stdout = process.output.open_stdout().map_err(CodecError::InputIo)?;
    let stats = transcode_lossless(BufReader::new(stdout), file.as_file_mut(), input_kind)?;
    file.as_file_mut().flush().map_err(CodecError::OutputIo)?;

    Ok(LosslessBatchOutcome {
        process,
        yaml: Some(StagedYaml {
            _directory: directory,
            file,
            stats,
        }),
    })
}

/// Detects the structured native stdout shape without changing argv.
pub fn detect_json_input_kind(args: &[OsString]) -> Result<JsonInputKind, BatchError> {
    let mut json = None;
    let mut format = None;
    let mut index = 0;
    while index < args.len() {
        let token = args[index].as_os_str();
        if token == OsStr::new("--") {
            break;
        }
        if token == OsStr::new("--json") {
            json = Some(JsonInputKind::Single);
        } else if let Some(value) = token
            .to_str()
            .and_then(|value| value.strip_prefix("--json="))
        {
            json = Some(if value == "stream" {
                JsonInputKind::Lines
            } else {
                JsonInputKind::Single
            });
        } else if token == OsStr::new("--format") {
            if let Some(value) = args.get(index + 1).and_then(|value| value.to_str()) {
                format = Some(value);
                index += 1;
            }
        } else if let Some(value) = token
            .to_str()
            .and_then(|value| value.strip_prefix("--format="))
        {
            format = Some(value);
        }
        index += 1;
    }
    if let Some(json) = json {
        return Ok(json);
    }
    format
        .map(detect_format)
        .transpose()?
        .flatten()
        .ok_or(BatchError::UnsupportedOutput)
}

fn detect_format(value: &str) -> Result<Option<JsonInputKind>, BatchError> {
    match value {
        "sarif" => Ok(Some(JsonInputKind::Single)),
        "github" => Err(BatchError::UnsupportedOutput),
        // Preserve forward compatibility: unknown native formats are allowed to
        // run. Empty native error output keeps its native code; non-JSON output
        // is rejected by the codec instead of entering model context.
        _ => Ok(Some(JsonInputKind::Single)),
    }
}

#[must_use]
pub fn uses_native_stdin(args: &[OsString]) -> bool {
    args.iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
        .any(|token| token.as_os_str() == OsStr::new("--stdin"))
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use crate::codec::JsonInputKind;

    use super::{detect_json_input_kind, uses_native_stdin, BatchError};

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn detects_native_json_shapes_without_rewriting_tokens() {
        assert_eq!(
            detect_json_input_kind(&args(&["run", "--json"])).expect("pretty JSON"),
            JsonInputKind::Single
        );
        assert_eq!(
            detect_json_input_kind(&args(&["scan", "--json=compact"])).expect("compact JSON"),
            JsonInputKind::Single
        );
        assert_eq!(
            detect_json_input_kind(&args(&["run", "--json=stream"])).expect("JSONL"),
            JsonInputKind::Lines
        );
        assert_eq!(
            detect_json_input_kind(&args(&["scan", "--format", "sarif"])).expect("SARIF"),
            JsonInputKind::Single
        );
    }

    #[test]
    fn rejects_known_text_outputs_and_stops_at_native_terminator() {
        assert!(matches!(
            detect_json_input_kind(&args(&["scan", "--format=github"])),
            Err(BatchError::UnsupportedOutput)
        ));
        assert!(matches!(
            detect_json_input_kind(&args(&["run", "--", "--json=stream"])),
            Err(BatchError::UnsupportedOutput)
        ));
    }

    #[test]
    fn stdin_detection_is_exact_and_respects_native_terminator() {
        assert!(uses_native_stdin(&args(&["run", "--stdin"])));
        assert!(!uses_native_stdin(&args(&["run", "--stdin-file"])));
        assert!(!uses_native_stdin(&args(&["run", "--", "--stdin"])));
    }
}
