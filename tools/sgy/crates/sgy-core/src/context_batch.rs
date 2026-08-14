//! End-to-end structured native output to bounded context YAML and optional native cache.

use std::{
    ffi::{OsStr, OsString},
    fs::File,
    io::{self, BufReader, Write},
    path::Path,
    time::SystemTime,
};

use tempfile::{NamedTempFile, TempDir};
use thiserror::Error;

use crate::{
    adapters::{
        raw::{commit_stderr_sidecar, ArtifactError, StderrSidecarPlan},
        write::WriteIntent,
    },
    aggregate::{AggregateError, AggregatedContext, ContextAggregator, ContextDocument},
    budget::{BudgetError, BudgetSettings},
    cache::{
        CacheAudit, CacheError, CacheIndexRecord, CacheMode, CacheProcess, CacheStaging,
        CacheStore, CommittedCache, SourceFormat,
    },
    codec::{
        parse_single_json, transcode_lossless, CodecError, JsonInputKind, JsonLines, SourceRecord,
    },
    invocation::Profile,
    process::{run, ProcessError, ProcessOutcome, ProcessRequest},
    profile::{
        project_custom_record, project_location_record, project_sarif_token_safe_record,
        project_token_safe_record, FieldPaths,
    },
};

#[derive(Debug)]
pub enum CachePlan {
    Off,
    Ready {
        store: CacheStore,
        audit: CacheAudit,
    },
    Unavailable {
        mode: CacheMode,
        error: CacheError,
    },
}

impl CachePlan {
    #[must_use]
    pub const fn off() -> Self {
        Self::Off
    }

    #[must_use]
    pub fn ready(store: CacheStore, audit: CacheAudit) -> Self {
        Self::Ready { store, audit }
    }

    #[must_use]
    pub fn unavailable(mode: CacheMode, error: CacheError) -> Self {
        Self::Unavailable { mode, error }
    }
}

#[derive(Debug)]
pub struct ProfileBatchRequest {
    pub process: ProcessRequest,
    pub input_kind: JsonInputKind,
    pub source_format: SourceFormat,
    pub profile: Profile,
    pub budget: BudgetSettings,
    pub keep_fields: Option<FieldPaths>,
    pub prune_fields: FieldPaths,
    pub cache: CachePlan,
    pub now: SystemTime,
    pub write_intent: WriteIntent,
    pub stderr_sidecar: Option<StderrSidecarPlan>,
}

#[derive(Debug)]
pub struct StagedProfileYaml {
    _directory: TempDir,
    file: NamedTempFile,
}

impl StagedProfileYaml {
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
pub struct ProfileBatchOutcome {
    pub process: ProcessOutcome,
    pub yaml: Option<StagedProfileYaml>,
    pub cache_id: Option<String>,
}

#[derive(Debug, Error)]
pub enum ProfileBatchError {
    #[error(transparent)]
    Process(#[from] ProcessError),
    #[error(transparent)]
    Codec(#[from] CodecError),
    #[error(transparent)]
    Aggregate(#[from] AggregateError),
    #[error(transparent)]
    Cache(#[from] CacheError),
    #[error(transparent)]
    Artifact(#[from] ArtifactError),
}

impl ProfileBatchError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Process(error) => error.wrapper_exit_code(),
            Self::Codec(error) => error.wrapper_exit_code(),
            Self::Aggregate(error) => error.wrapper_exit_code(),
            Self::Cache(error) => error.wrapper_exit_code(),
            Self::Artifact(error) => error.wrapper_exit_code(),
        }
    }
}

pub fn run_profile_batch(
    request: ProfileBatchRequest,
) -> Result<ProfileBatchOutcome, ProfileBatchError> {
    let ProfileBatchRequest {
        process,
        input_kind,
        source_format,
        profile,
        budget,
        keep_fields,
        prune_fields,
        cache,
        now,
        write_intent,
        stderr_sidecar,
    } = request;
    let cache = match cache {
        CachePlan::Unavailable {
            mode: CacheMode::On,
            error,
        } => return Err(error.into()),
        other => other,
    };
    let process = run(process)?;
    if process.cancellation.is_none() {
        commit_stderr_sidecar(stderr_sidecar, process.output.stderr_path())?;
    }
    if process.cancellation.is_some()
        || (process.output.stdout_bytes == 0
            && process.exit_code() != 0
            && !is_empty_no_match(&process, profile))
    {
        return Ok(ProfileBatchOutcome {
            process,
            yaml: None,
            cache_id: None,
        });
    }

    if process.output.stdout_bytes == 0 && is_empty_no_match(&process, profile) {
        let mut aggregator = ContextAggregator::new(profile, budget)?;
        aggregator.set_write_intent(write_intent);
        let context = aggregator.into_document()?.fit(budget)?;
        let yaml = stage_context_yaml(&context)?;
        return Ok(ProfileBatchOutcome {
            process,
            yaml: Some(yaml),
            cache_id: None,
        });
    }

    let stage_for_auto = profile != Profile::Lossless;
    let mut cache = CacheSession::start(
        cache,
        source_format,
        process.output.stdout_path(),
        now,
        stage_for_auto,
    )?;

    if profile == Profile::Lossless {
        if cache.mode == CacheMode::On {
            visit_native_records(process.output.stdout_path(), source_format, |_, index| {
                cache.add_record(index)
            })?;
        }
        let committed = if cache.mode == CacheMode::On {
            Some(cache.commit(process.exit_code(), now)?)
        } else {
            None
        };
        let yaml = stage_lossless_yaml(process.output.stdout_path(), input_kind)?;
        return Ok(ProfileBatchOutcome {
            process,
            yaml: Some(yaml),
            cache_id: committed.map(|value| value.cache_id),
        });
    }

    let mut aggregator = ContextAggregator::new(profile, budget)?;
    aggregator.set_write_intent(write_intent);
    visit_native_records(
        process.output.stdout_path(),
        source_format,
        |record, index| {
            cache.add_record(index)?;
            let token_safe = if source_format == SourceFormat::Sarif {
                project_sarif_token_safe_record(&record)
            } else {
                project_token_safe_record(&record)
            };
            match profile {
                Profile::TokenSafe => aggregator.push_token_safe(token_safe)?,
                Profile::Locations => {
                    let displayed = project_location_record(&token_safe);
                    aggregator.push_location(&token_safe, displayed)?;
                }
                Profile::Files => aggregator.push_file(&token_safe)?,
                Profile::Custom => {
                    let displayed = project_custom_record(
                        &record.value,
                        &token_safe,
                        keep_fields.as_ref(),
                        &prune_fields,
                    );
                    aggregator.push_custom(&token_safe, displayed)?;
                }
                Profile::Lossless => unreachable!("lossless returned before context aggregation"),
            }
            Ok(())
        },
    )?;
    let base = aggregator.into_document()?;
    let (context, committed) = finish_context(base, budget, &mut cache, process.exit_code(), now)?;
    let yaml = stage_context_yaml(&context)?;
    Ok(ProfileBatchOutcome {
        process,
        yaml: Some(yaml),
        cache_id: committed.map(|value| value.cache_id),
    })
}

fn is_empty_no_match(process: &ProcessOutcome, profile: Profile) -> bool {
    profile != Profile::Lossless
        && process.exit_code() == 1
        && process.output.stdout_bytes == 0
        && process.output.stderr_bytes == 0
}

fn finish_context(
    base: ContextDocument,
    budget: BudgetSettings,
    cache: &mut CacheSession,
    exit_code: i32,
    now: SystemTime,
) -> Result<(AggregatedContext, Option<CommittedCache>), ProfileBatchError> {
    match cache.mode {
        CacheMode::Off => Ok((base.fit(budget)?, None)),
        CacheMode::On => {
            let committed = cache.commit(exit_code, now)?;
            let context = base.with_cache_id(&committed.cache_id).fit(budget)?;
            Ok((context, Some(committed)))
        }
        CacheMode::Auto => match base.clone().fit(budget) {
            Ok(context) if context.document.complete() => Ok((context, None)),
            Ok(_) | Err(AggregateError::Budget(BudgetError::Minimum { .. })) => {
                let committed = cache.commit(exit_code, now)?;
                let context = base.with_cache_id(&committed.cache_id).fit(budget)?;
                Ok((context, Some(committed)))
            }
            Err(error) => Err(error.into()),
        },
    }
}

struct CacheSession {
    mode: CacheMode,
    staging: Option<CacheStaging>,
    failure: Option<CacheError>,
}

impl CacheSession {
    fn start(
        plan: CachePlan,
        format: SourceFormat,
        source_path: &Path,
        now: SystemTime,
        stage_for_auto: bool,
    ) -> Result<Self, ProfileBatchError> {
        match plan {
            CachePlan::Off => Ok(Self {
                mode: CacheMode::Off,
                staging: None,
                failure: None,
            }),
            CachePlan::Unavailable { mode, error } => Ok(Self {
                mode,
                staging: None,
                failure: Some(error),
            }),
            CachePlan::Ready { store, audit } => {
                let mode = audit.cache_mode;
                if mode == CacheMode::Off {
                    return Ok(Self {
                        mode,
                        staging: None,
                        failure: None,
                    });
                }
                if mode == CacheMode::Auto && !stage_for_auto {
                    return Ok(Self {
                        mode,
                        staging: None,
                        failure: None,
                    });
                }
                let staging = match store.begin(format, audit, now) {
                    Ok(mut staging) => {
                        let source = File::open(source_path).map_err(CodecError::InputIo)?;
                        match staging.stage_source(BufReader::new(source)) {
                            Ok(_) => Some(staging),
                            Err(error) if mode == CacheMode::Auto => {
                                return Ok(Self {
                                    mode,
                                    staging: None,
                                    failure: Some(error),
                                });
                            }
                            Err(error) => return Err(error.into()),
                        }
                    }
                    Err(error) if mode == CacheMode::Auto => {
                        return Ok(Self {
                            mode,
                            staging: None,
                            failure: Some(error),
                        });
                    }
                    Err(error) => return Err(error.into()),
                };
                Ok(Self {
                    mode,
                    staging,
                    failure: None,
                })
            }
        }
    }

    fn add_record(&mut self, record: CacheIndexRecord) -> Result<(), ProfileBatchError> {
        let result = self
            .staging
            .as_mut()
            .map(|staging| staging.add_index_record(record))
            .transpose();
        match result {
            Ok(_) => Ok(()),
            Err(error) if self.mode == CacheMode::Auto => {
                self.staging.take();
                if self.failure.is_none() {
                    self.failure = Some(error);
                }
                Ok(())
            }
            Err(error) => Err(error.into()),
        }
    }

    fn commit(&mut self, exit_code: i32, now: SystemTime) -> Result<CommittedCache, CacheError> {
        if let Some(error) = self.failure.take() {
            return Err(error);
        }
        let staging = self.staging.take().ok_or_else(|| {
            CacheError::Verification("required cache staging is unavailable".to_owned())
        })?;
        staging.commit(CacheProcess::completed(exit_code), now)
    }
}

fn visit_native_records(
    source_path: &Path,
    format: SourceFormat,
    mut visitor: impl FnMut(SourceRecord, CacheIndexRecord) -> Result<(), ProfileBatchError>,
) -> Result<(), ProfileBatchError> {
    match format {
        SourceFormat::JsonLines => {
            let input = File::open(source_path).map_err(CodecError::InputIo)?;
            for record in JsonLines::new(BufReader::new(input)) {
                let record = record?;
                let index = CacheIndexRecord::from_source(&record);
                visitor(record, index)?;
            }
        }
        SourceFormat::JsonValue => {
            let bytes = std::fs::read(source_path).map_err(CodecError::InputIo)?;
            let record = parse_single_json(&bytes)?;
            let index = CacheIndexRecord::from_source(&record);
            visitor(record, index)?;
        }
        SourceFormat::JsonArray => {
            let bytes = std::fs::read(source_path).map_err(CodecError::InputIo)?;
            let document = parse_single_json(&bytes)?;
            let values = document.value.as_array().ok_or_else(|| {
                CodecError::Encode("native --json output must be a JSON array".to_owned())
            })?;
            for (position, value) in values.iter().enumerate() {
                let ordinal = u64::try_from(position)
                    .map_err(|error| CodecError::Encode(error.to_string()))?;
                let record = SourceRecord {
                    ordinal,
                    span: document.span,
                    value: value.clone(),
                };
                visitor(
                    record,
                    CacheIndexRecord::with_pointer(ordinal, format!("/{position}"), value),
                )?;
            }
        }
        SourceFormat::Sarif => {
            let bytes = std::fs::read(source_path).map_err(CodecError::InputIo)?;
            let document = parse_single_json(&bytes)?;
            let mut ordinal = 0_u64;
            if let Some(runs) = document
                .value
                .get("runs")
                .and_then(serde_json::Value::as_array)
            {
                for (run_index, run) in runs.iter().enumerate() {
                    if let Some(results) = run.get("results").and_then(serde_json::Value::as_array)
                    {
                        for (result_index, value) in results.iter().enumerate() {
                            let record = SourceRecord {
                                ordinal,
                                span: document.span,
                                value: value.clone(),
                            };
                            visitor(
                                record,
                                CacheIndexRecord::with_sarif_pointer(
                                    ordinal,
                                    format!("/runs/{run_index}/results/{result_index}"),
                                    value,
                                ),
                            )?;
                            ordinal = ordinal.checked_add(1).ok_or_else(|| {
                                CodecError::Encode("SARIF result count overflow".to_owned())
                            })?;
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

fn stage_lossless_yaml(
    source_path: &Path,
    input_kind: JsonInputKind,
) -> Result<StagedProfileYaml, ProfileBatchError> {
    let (directory, mut file) = new_yaml_staging()?;
    let source = File::open(source_path).map_err(CodecError::InputIo)?;
    transcode_lossless(BufReader::new(source), file.as_file_mut(), input_kind)?;
    file.as_file_mut().flush().map_err(CodecError::OutputIo)?;
    Ok(StagedProfileYaml {
        _directory: directory,
        file,
    })
}

fn stage_context_yaml(context: &AggregatedContext) -> Result<StagedProfileYaml, ProfileBatchError> {
    let (directory, mut file) = new_yaml_staging()?;
    context.document.write_yaml(file.as_file_mut())?;
    file.as_file_mut().flush().map_err(CodecError::OutputIo)?;
    Ok(StagedProfileYaml {
        _directory: directory,
        file,
    })
}

fn new_yaml_staging() -> Result<(TempDir, NamedTempFile), CodecError> {
    let directory = tempfile::Builder::new()
        .prefix("sgy-context-")
        .tempdir()
        .map_err(CodecError::OutputIo)?;
    let file = NamedTempFile::new_in(directory.path()).map_err(CodecError::OutputIo)?;
    Ok((directory, file))
}

#[must_use]
pub fn detect_source_format(args: &[OsString], input_kind: JsonInputKind) -> SourceFormat {
    if input_kind == JsonInputKind::Lines {
        return SourceFormat::JsonLines;
    }
    let mut has_json = false;
    let mut format = None;
    let mut index = 0_usize;
    while index < args.len() {
        let token = args[index].as_os_str();
        if token == OsStr::new("--") {
            break;
        }
        if token == OsStr::new("--json")
            || token
                .to_str()
                .is_some_and(|value| value.starts_with("--json="))
        {
            has_json = true;
        } else if token == OsStr::new("--format") {
            format = args.get(index + 1).and_then(|value| value.to_str());
            index += 1;
        } else if let Some(value) = token
            .to_str()
            .and_then(|value| value.strip_prefix("--format="))
        {
            format = Some(value);
        }
        index += 1;
    }
    if has_json {
        SourceFormat::JsonArray
    } else if format == Some("sarif") {
        SourceFormat::Sarif
    } else {
        SourceFormat::JsonValue
    }
}
