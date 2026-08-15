//! `ast-grep run` output classification and bounded non-JSON routing.

use std::ffi::{OsStr, OsString};

use thiserror::Error;

use super::common::{
    run_bounded_adapter, BoundedAdapterError, BoundedAdapterRequest, BoundedAdapterSpec,
    BoundedShape,
};
pub use super::common::{
    BoundedAdapterOutcome as RunAdapterOutcome, StagedAdapterYaml as StagedRunYaml,
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

pub const RUN_SCHEMA: &str = "sgy.run/v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunOutputAdapter {
    Structured {
        input_kind: JsonInputKind,
        source_format: SourceFormat,
    },
    FilesWithMatches,
    Text,
    Interactive,
}

#[derive(Debug)]
pub struct RunAdapterRequest {
    pub process: ProcessRequest,
    pub adapter: RunOutputAdapter,
    pub budget: BudgetSettings,
    pub stderr_sidecar: Option<StderrSidecarPlan>,
}

#[derive(Debug, Error)]
pub enum RunAdapterError {
    #[error("interactive run requires the TTY passthrough adapter")]
    InteractiveUnsupported,
    #[error(transparent)]
    Bounded(#[from] BoundedAdapterError),
}

impl RunAdapterError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::InteractiveUnsupported => 125,
            Self::Bounded(error) => error.wrapper_exit_code(),
        }
    }
}

/// Classifies `run` by its effective argv without changing any native token.
pub fn classify_run_output(args: &[OsString]) -> RunOutputAdapter {
    let mut files = false;
    let mut interactive = false;
    let terminal_output = super::raw::has_terminal_output(args);
    for token in args
        .iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
    {
        let Some(token) = token.to_str() else {
            continue;
        };
        if long_flag(token, "--files-with-matches") {
            files = true;
        }
        if token == "-i" || long_flag(token, "--interactive") || short_cluster_has_i(token) {
            interactive = true;
        }
    }
    if interactive && !terminal_output {
        return RunOutputAdapter::Interactive;
    }
    if files {
        return RunOutputAdapter::FilesWithMatches;
    }
    match detect_json_input_kind(args) {
        Ok(input_kind) => RunOutputAdapter::Structured {
            input_kind,
            source_format: detect_source_format(args, input_kind),
        },
        Err(BatchError::UnsupportedOutput) => RunOutputAdapter::Text,
        Err(BatchError::Process(_) | BatchError::Codec(_)) => {
            unreachable!("output detection cannot execute a process or codec")
        }
    }
}

pub fn run_non_json_adapter(
    request: RunAdapterRequest,
) -> Result<RunAdapterOutcome, RunAdapterError> {
    let spec = match request.adapter {
        RunOutputAdapter::FilesWithMatches => BoundedAdapterSpec {
            schema: RUN_SCHEMA,
            kind: "files-with-matches",
            temp_prefix: "srcq-run-",
            shape: BoundedShape::Files,
            write_apply: false,
        },
        RunOutputAdapter::Text => BoundedAdapterSpec {
            schema: RUN_SCHEMA,
            kind: "text",
            temp_prefix: "srcq-run-",
            shape: BoundedShape::Text,
            write_apply: detect_write_intent(
                &request.process.args,
                crate::defaults::CommandClassification::BatchRun,
            ) == WriteIntent::Apply,
        },
        RunOutputAdapter::Interactive => return Err(RunAdapterError::InteractiveUnsupported),
        RunOutputAdapter::Structured { .. } => {
            unreachable!("structured run output must use the shared profile batch path")
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

    use super::{classify_run_output, RunOutputAdapter};
    use crate::{cache::SourceFormat, codec::JsonInputKind};

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn classifies_run_outputs_without_touching_native_tokens() {
        assert_eq!(
            classify_run_output(&args(&["run", "--json=stream"])),
            RunOutputAdapter::Structured {
                input_kind: JsonInputKind::Lines,
                source_format: SourceFormat::JsonLines,
            }
        );
        assert_eq!(
            classify_run_output(&args(&["run", "--files-with-matches"])),
            RunOutputAdapter::FilesWithMatches
        );
        assert_eq!(
            classify_run_output(&args(&["run", "--debug-query=ast"])),
            RunOutputAdapter::Text
        );
        assert_eq!(
            classify_run_output(&args(&["run", "-Ui"])),
            RunOutputAdapter::Interactive
        );
        assert_eq!(
            classify_run_output(&args(&["run", "--", "--files-with-matches"])),
            RunOutputAdapter::Text
        );
    }
}
