//! `ast-grep scan` output classification and bounded non-JSON routing.

use std::ffi::{OsStr, OsString};

use thiserror::Error;

use super::common::{
    run_bounded_adapter, BoundedAdapterError, BoundedAdapterRequest, BoundedAdapterSpec,
    BoundedShape,
};
pub use super::common::{
    BoundedAdapterOutcome as ScanAdapterOutcome, StagedAdapterYaml as StagedScanYaml,
};
use crate::{
    adapters::{
        raw::StderrSidecarPlan,
        write::{detect_write_intent, WriteIntent},
    },
    batch::{detect_json_input_kind, BatchError},
    budget::BudgetSettings,
    cache::SourceFormat,
    codec::JsonInputKind,
    context_batch::detect_source_format,
    process::ProcessRequest,
};

pub const SCAN_SCHEMA: &str = "sgy.scan/v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScanOutputAdapter {
    Structured {
        input_kind: JsonInputKind,
        source_format: SourceFormat,
    },
    FilesWithMatches,
    GitHub,
    Text,
    Interactive,
}

#[derive(Debug)]
pub struct ScanAdapterRequest {
    pub process: ProcessRequest,
    pub adapter: ScanOutputAdapter,
    pub budget: BudgetSettings,
    pub stderr_sidecar: Option<StderrSidecarPlan>,
}

#[derive(Debug, Error)]
pub enum ScanAdapterError {
    #[error("interactive scan requires the TTY passthrough adapter")]
    InteractiveUnsupported,
    #[error(transparent)]
    Bounded(#[from] BoundedAdapterError),
}

impl ScanAdapterError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::InteractiveUnsupported => 125,
            Self::Bounded(error) => error.wrapper_exit_code(),
        }
    }
}

/// Classifies `scan` by its effective argv without changing any native token.
pub fn classify_scan_output(args: &[OsString]) -> ScanOutputAdapter {
    let mut files = false;
    let mut interactive = false;
    let terminal_output = super::raw::has_terminal_output(args);
    let mut format = None;
    let mut index = 0_usize;
    while index < args.len() {
        let token = args[index].as_os_str();
        if token == OsStr::new("--") {
            break;
        }
        let Some(text) = token.to_str() else {
            index += 1;
            continue;
        };
        if long_flag(text, "--files-with-matches") {
            files = true;
        }
        if text == "-i" || long_flag(text, "--interactive") || short_cluster_has_i(text) {
            interactive = true;
        }
        if text == "--format" {
            format = args.get(index + 1).and_then(|value| value.to_str());
            index += 1;
        } else if let Some(value) = text.strip_prefix("--format=") {
            format = Some(value);
        }
        index += 1;
    }
    if interactive && !terminal_output {
        return ScanOutputAdapter::Interactive;
    }
    if files {
        return ScanOutputAdapter::FilesWithMatches;
    }
    if format == Some("github") {
        return ScanOutputAdapter::GitHub;
    }
    match detect_json_input_kind(args) {
        Ok(input_kind) => ScanOutputAdapter::Structured {
            input_kind,
            source_format: detect_source_format(args, input_kind),
        },
        Err(BatchError::UnsupportedOutput) => ScanOutputAdapter::Text,
        Err(BatchError::Process(_) | BatchError::Codec(_)) => {
            unreachable!("output detection cannot execute a process or codec")
        }
    }
}

pub fn run_non_json_adapter(
    request: ScanAdapterRequest,
) -> Result<ScanAdapterOutcome, ScanAdapterError> {
    let spec = match request.adapter {
        ScanOutputAdapter::FilesWithMatches => BoundedAdapterSpec {
            schema: SCAN_SCHEMA,
            kind: "files-with-matches",
            temp_prefix: "srcq-scan-",
            shape: BoundedShape::Files,
            write_apply: false,
        },
        ScanOutputAdapter::GitHub => BoundedAdapterSpec {
            schema: SCAN_SCHEMA,
            kind: "github",
            temp_prefix: "srcq-scan-",
            shape: BoundedShape::Text,
            write_apply: false,
        },
        ScanOutputAdapter::Text => BoundedAdapterSpec {
            schema: SCAN_SCHEMA,
            kind: "text",
            temp_prefix: "srcq-scan-",
            shape: BoundedShape::Text,
            write_apply: detect_write_intent(
                &request.process.args,
                crate::defaults::CommandClassification::BatchScan,
            ) == WriteIntent::Apply,
        },
        ScanOutputAdapter::Interactive => return Err(ScanAdapterError::InteractiveUnsupported),
        ScanOutputAdapter::Structured { .. } => {
            unreachable!("structured scan output must use the shared profile batch path")
        }
    };
    Ok(run_bounded_adapter(BoundedAdapterRequest {
        process: request.process,
        budget: request.budget,
        spec,
        stderr_sidecar: request.stderr_sidecar,
    })?)
}

fn long_flag(token: &str, name: &str) -> bool {
    token == name
        || token
            .strip_prefix(name)
            .is_some_and(|rest| rest.starts_with('='))
}

fn short_cluster_has_i(token: &str) -> bool {
    let Some(cluster) = token.strip_prefix('-') else {
        return false;
    };
    !cluster.is_empty()
        && cluster
            .chars()
            .all(|flag| matches!(flag, 'i' | 'U' | 'h' | 'V'))
        && cluster.contains('i')
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use super::{classify_scan_output, ScanOutputAdapter};
    use crate::{cache::SourceFormat, codec::JsonInputKind};

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn classifies_scan_formats_and_stops_at_native_terminator() {
        assert_eq!(
            classify_scan_output(&args(&["scan", "--json=compact"])),
            ScanOutputAdapter::Structured {
                input_kind: JsonInputKind::Single,
                source_format: SourceFormat::JsonArray,
            }
        );
        assert_eq!(
            classify_scan_output(&args(&["scan", "--format", "sarif"])),
            ScanOutputAdapter::Structured {
                input_kind: JsonInputKind::Single,
                source_format: SourceFormat::Sarif,
            }
        );
        assert_eq!(
            classify_scan_output(&args(&["scan", "--format=github"])),
            ScanOutputAdapter::GitHub
        );
        assert_eq!(
            classify_scan_output(&args(&["scan", "--files-with-matches"])),
            ScanOutputAdapter::FilesWithMatches
        );
        assert_eq!(
            classify_scan_output(&args(&["scan", "--report-style=short"])),
            ScanOutputAdapter::Text
        );
        assert_eq!(
            classify_scan_output(&args(&["scan", "-i"])),
            ScanOutputAdapter::Interactive
        );
        assert_eq!(
            classify_scan_output(&args(&["scan", "--", "--format=github"])),
            ScanOutputAdapter::Text
        );
    }
}
