#![forbid(unsafe_code)]

use std::collections::HashSet;
use std::ffi::OsString;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use sgy_core::adapters::raw::{
    commit_stderr_sidecar, completion_media_type, has_debug_query, has_interactive,
    has_terminal_output, new_is_non_interactive, run_raw_adapter, ArtifactPlan, ArtifactSource,
    RawAdapterRequest, RawKind, StderrSidecarPlan,
};
use sgy_core::adapters::run::{
    classify_run_output, run_non_json_adapter, RunAdapterRequest, RunOutputAdapter,
};
use sgy_core::adapters::scan::{
    classify_scan_output, run_non_json_adapter as run_scan_non_json_adapter, ScanAdapterRequest,
    ScanOutputAdapter,
};
use sgy_core::adapters::write::{detect_write_intent, WriteIntent};
use sgy_core::batch::uses_native_stdin;
use sgy_core::cache::{default_cache_root, CacheAudit, CacheLimits, CacheMode, CacheStore};
use sgy_core::config::load_standard_config;
use sgy_core::context_batch::{run_profile_batch, CachePlan, ProfileBatchRequest};
use sgy_core::defaults::CommandClassification;
use sgy_core::engine::{EngineEnvironment, SystemEngineEnvironment};
use sgy_core::invocation::WrapperCommand;
use sgy_core::passthrough::{
    commit_metadata, run_lsp, run_tty, MetadataRequest, PassthroughChannel,
};
use sgy_core::prepare::{prepare_invocation, PrepareError};
use sgy_core::process::{
    CancellationToken, PreparedOutput, ProcessRequest, SignalRelay, StdinMode,
};

fn main() {
    std::process::exit(run_main());
}

fn run_main() -> i32 {
    let action = match sgy_cli::parse_cli_from(std::env::args_os()) {
        Ok(action) => action,
        Err(error) => {
            let exit_code = error.wrapper_exit_code();
            if let Err(print_error) = error.print() {
                eprintln!("sgy: failed to write CLI output: {print_error}");
                return 126;
            }
            return i32::from(exit_code);
        }
    };
    let invocation = match action {
        sgy_cli::CliAction::Cache(command) => return execute_cache(&command),
        sgy_cli::CliAction::Process(command) => return execute_process(&command),
        sgy_cli::CliAction::Inspect(command) => return execute_inspection(&command),
        sgy_cli::CliAction::Native(invocation) => *invocation,
    };
    if invocation.command == WrapperCommand::Exec
        && invocation
            .user_argv
            .first()
            .is_some_and(|token| token == "completions")
        && invocation.explicit.artifact_out.is_none()
    {
        eprintln!("sgy: native completions requires explicit --artifact-out");
        return 125;
    }
    let launch_cwd = match std::env::current_dir() {
        Ok(cwd) => cwd,
        Err(error) => {
            eprintln!("sgy: failed to read launch working directory: {error}");
            return 126;
        }
    };
    let config = match load_standard_config(&launch_cwd) {
        Ok(config) => config,
        Err(error) => {
            eprintln!("sgy: {error}");
            return i32::from(error.wrapper_exit_code());
        }
    };
    let environment = SystemEngineEnvironment::from_process_environment();
    let prepared = match prepare_invocation(invocation, &config.stack, &launch_cwd, &environment) {
        Ok(prepared) => prepared,
        Err(PrepareError::Defaults(error)) => {
            eprintln!("sgy: {error}");
            return i32::from(error.wrapper_exit_code());
        }
        Err(PrepareError::Engine(error)) => {
            eprintln!("sgy: {error}");
            return i32::from(error.wrapper_exit_code());
        }
    };
    let passthrough = match preflight_passthrough(&prepared.invocation) {
        Ok(channel) => channel,
        Err(error) => {
            eprintln!("sgy: {error}");
            return 125;
        }
    };

    debug_assert_eq!(
        passthrough,
        classify_passthrough(&prepared.defaults.effective_argv)
    );

    match prepared.invocation.command {
        WrapperCommand::Defaults => emit_defaults(&prepared.defaults),
        WrapperCommand::Exec => execute_profile(prepared),
    }
}

fn execute_inspection(command: &sgy_cli::InspectionCommand) -> i32 {
    let launch_cwd = match std::env::current_dir() {
        Ok(cwd) => cwd,
        Err(error) => {
            eprintln!("sgy: failed to read launch working directory: {error}");
            return 126;
        }
    };
    let output = match command {
        sgy_cli::InspectionCommand::Schema => {
            sgy_cli::diagnostics::render_config_schema().map(|yaml| (yaml, true))
        }
        sgy_cli::InspectionCommand::Capabilities => {
            sgy_cli::diagnostics::render_capabilities().map(|yaml| (yaml, true))
        }
        sgy_cli::InspectionCommand::Doctor { engine, cwd } => {
            let environment = SystemEngineEnvironment::from_process_environment();
            sgy_cli::diagnostics::run_doctor(engine.clone(), cwd.clone(), &launch_cwd, &environment)
                .map(|output| (output.yaml, output.ok))
        }
    };
    let (yaml, ok) = match output {
        Ok(output) => output,
        Err(error) => {
            eprintln!("sgy: {error}");
            return i32::from(error.wrapper_exit_code());
        }
    };
    let mut stdout = io::stdout().lock();
    if let Err(error) = stdout.write_all(&yaml).and_then(|()| stdout.flush()) {
        eprintln!("sgy: failed to write inspection YAML: {error}");
        return 127;
    }
    if ok {
        0
    } else {
        1
    }
}

fn execute_process(command: &sgy_cli::ProcessCommand) -> i32 {
    let launch_cwd = match std::env::current_dir() {
        Ok(cwd) => cwd,
        Err(error) => {
            eprintln!("sgy: failed to read launch working directory: {error}");
            return 126;
        }
    };
    let mut stdout = io::stdout().lock();
    match sgy_cli::processor::execute(command, &launch_cwd, &mut stdout) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("sgy: {error}");
            error.wrapper_exit_code()
        }
    }
}

fn preflight_passthrough(
    invocation: &sgy_core::invocation::NativeInvocation,
) -> Result<Option<PassthroughChannel>, String> {
    if invocation.command == WrapperCommand::Defaults && invocation.explicit.meta_out.is_some() {
        return Err("--meta-out requires sgy exec".to_owned());
    }
    let channel = classify_passthrough(&invocation.user_argv);
    let explicit = &invocation.explicit;
    let projection_or_budget = explicit.profile.is_some()
        || explicit.max_detail_results.is_some()
        || explicit.max_text_chars.is_some()
        || explicit.max_context_bytes.is_some()
        || explicit.keep_fields.is_some()
        || explicit.prune_fields.is_some();
    match channel {
        Some(PassthroughChannel::Batch) => {
            unreachable!("batch metadata is not a passthrough channel")
        }
        Some(PassthroughChannel::Tty) => {
            if explicit.yaml_out.is_some()
                || explicit.artifact_out.is_some()
                || explicit.stderr_yaml.is_some()
                || projection_or_budget
                || explicit.cache_mode == Some(CacheMode::On)
            {
                return Err(
                    "interactive TTY conflicts with YAML/artifact/stderr output, projection/budget options, or --cache on"
                        .to_owned(),
                );
            }
        }
        Some(PassthroughChannel::Lsp) => {
            if explicit.yaml_out.is_some()
                || explicit.artifact_out.is_some()
                || projection_or_budget
                || explicit.cache_mode == Some(CacheMode::On)
            {
                return Err(
                    "LSP passthrough conflicts with YAML/artifact output, projection/budget options, or --cache on"
                        .to_owned(),
                );
            }
        }
        None => {}
    }
    Ok(channel)
}

fn classify_passthrough(args: &[OsString]) -> Option<PassthroughChannel> {
    let first = args.first().and_then(|value| value.to_str());
    if first == Some("lsp") {
        return Some(PassthroughChannel::Lsp);
    }
    if has_terminal_output(args) {
        return None;
    }
    let interactive = match first {
        Some("run" | "scan" | "test") => has_interactive(args),
        Some("new") => !new_is_non_interactive(args),
        _ => false,
    };
    interactive.then_some(PassthroughChannel::Tty)
}

fn execute_cache(command: &sgy_cli::CacheCommand) -> i32 {
    let launch_cwd = match std::env::current_dir() {
        Ok(cwd) => cwd,
        Err(error) => {
            eprintln!("sgy: failed to read launch working directory: {error}");
            return 126;
        }
    };
    let root = match sgy_core::cache::default_cache_root() {
        Ok(root) => root,
        Err(error) => {
            eprintln!("sgy: {error}");
            return error.wrapper_exit_code();
        }
    };
    let store = match sgy_core::cache::CacheStore::open(
        root,
        Some(&launch_cwd),
        sgy_core::cache::CacheLimits::default(),
    ) {
        Ok(store) => store,
        Err(error) => {
            eprintln!("sgy: {error}");
            return error.wrapper_exit_code();
        }
    };
    let mut stdout = io::stdout().lock();
    match sgy_cli::cache::execute(&store, command, std::time::SystemTime::now(), &mut stdout) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("sgy: {error}");
            error.wrapper_exit_code()
        }
    }
}

fn emit_defaults(decision: &sgy_core::defaults::DefaultsDecision) -> i32 {
    let yaml = match sgy_cli::defaults_output::render_defaults_yaml(decision) {
        Ok(yaml) => yaml,
        Err(error) => {
            eprintln!("sgy: {error}");
            return i32::from(error.wrapper_exit_code());
        }
    };
    let mut stdout = io::stdout().lock();
    if let Err(error) = stdout.write_all(&yaml).and_then(|()| stdout.flush()) {
        eprintln!("sgy: failed to write defaults YAML: {error}");
        return 127;
    }
    0
}

fn execute_profile(prepared: sgy_core::prepare::PreparedInvocation) -> i32 {
    let mut outputs = match prepare_destinations(&prepared.invocation.explicit) {
        Ok(outputs) => outputs,
        Err((code, error)) => {
            eprintln!("sgy: {error}");
            return code;
        }
    };
    if classify_passthrough(&prepared.defaults.effective_argv).is_some() {
        return execute_profile_with_outputs(prepared, outputs);
    }

    let metadata = outputs.meta.take();
    let metadata_version = metadata
        .as_ref()
        .map(|_| engine_version_for_metadata(&prepared));
    let user_argv = prepared.defaults.user_argv.clone();
    let effective_argv = prepared.defaults.effective_argv.clone();
    let write_intent = detect_write_intent(
        &prepared.defaults.effective_argv,
        prepared.defaults.classification,
    );
    let started_at = std::time::SystemTime::now();
    let exit_code = execute_profile_with_outputs(prepared, outputs);
    let ended_at = std::time::SystemTime::now();
    if let Some(output) = metadata.as_ref() {
        let wrapper_failed = (120..=127).contains(&exit_code);
        if let Err(error) = commit_metadata(MetadataRequest {
            output,
            channel: PassthroughChannel::Batch,
            engine_version: metadata_version.as_deref().unwrap_or("unknown"),
            user_argv: &user_argv,
            effective_argv: &effective_argv,
            started_at,
            ended_at,
            native_exit_code: (!wrapper_failed).then_some(exit_code),
            cancelled: matches!(exit_code, 130 | 143),
            stdin_bytes: None,
            stdout_bytes: None,
            stderr_bytes: None,
            wrapper_error_origin: wrapper_failed.then_some("batch_wrapper"),
        }) {
            eprintln!("sgy: {error}");
            warn_possible_partial_write(write_intent);
            return error.wrapper_exit_code();
        }
    }
    exit_code
}

fn execute_profile_with_outputs(
    prepared: sgy_core::prepare::PreparedInvocation,
    mut outputs: PreparedDestinations,
) -> i32 {
    let write_intent = detect_write_intent(
        &prepared.defaults.effective_argv,
        prepared.defaults.classification,
    );
    let Some(engine) = prepared.engine.as_ref() else {
        eprintln!("sgy: execution preparation did not resolve an engine");
        return 120;
    };

    let cancellation = CancellationToken::new();
    let _signal_relay = match SignalRelay::install(cancellation.clone()) {
        Ok(relay) => relay,
        Err(error) => {
            eprintln!("sgy: {error}");
            return 126;
        }
    };
    let mut request = ProcessRequest::new(&engine.path, &prepared.settings.child_cwd.path);
    request.args = prepared.defaults.effective_argv.clone();
    request.stdin = if uses_native_stdin(&request.args) {
        StdinMode::Inherit
    } else {
        StdinMode::Null
    };
    request.cancellation = cancellation;

    if matches!(
        prepared.defaults.classification,
        CommandClassification::BatchRun | CommandClassification::BatchScan
    ) {
        if let Some(output) = outputs.artifact.take() {
            let debug = has_debug_query(&prepared.defaults.effective_argv);
            let artifact = ArtifactPlan {
                output,
                media_type: if debug {
                    "text/plain"
                } else {
                    "application/octet-stream"
                },
                source: if debug {
                    ArtifactSource::Stderr
                } else {
                    ArtifactSource::Stdout
                },
            };
            return execute_raw_profile(
                &prepared,
                request,
                RawKind::Unknown,
                Some(artifact),
                outputs,
                false,
                write_intent,
            );
        }
    }

    match prepared.defaults.classification {
        CommandClassification::NonBatchTest => {
            if has_terminal_output(&prepared.defaults.effective_argv) {
                let artifact = outputs.artifact.take().map(|output| ArtifactPlan {
                    output,
                    media_type: "text/plain",
                    source: ArtifactSource::Stdout,
                });
                return execute_raw_profile(
                    &prepared,
                    request,
                    RawKind::Help,
                    artifact,
                    outputs,
                    false,
                    write_intent,
                );
            }
            if has_interactive(&prepared.defaults.effective_argv) {
                return execute_tty_profile(&prepared, request, outputs);
            }
            let artifact = outputs.artifact.take().map(|output| ArtifactPlan {
                output,
                media_type: "text/plain",
                source: ArtifactSource::Stdout,
            });
            return execute_raw_profile(
                &prepared,
                request,
                RawKind::Test,
                artifact,
                outputs,
                false,
                write_intent,
            );
        }
        CommandClassification::NonBatchNew => {
            if has_terminal_output(&prepared.defaults.effective_argv) {
                let artifact = outputs.artifact.take().map(|output| ArtifactPlan {
                    output,
                    media_type: "text/plain",
                    source: ArtifactSource::Stdout,
                });
                return execute_raw_profile(
                    &prepared,
                    request,
                    RawKind::Help,
                    artifact,
                    outputs,
                    false,
                    write_intent,
                );
            }
            if !new_is_non_interactive(&prepared.defaults.effective_argv) {
                return execute_tty_profile(&prepared, request, outputs);
            }
            let artifact = outputs.artifact.take().map(|output| ArtifactPlan {
                output,
                media_type: "text/plain",
                source: ArtifactSource::Stdout,
            });
            return execute_raw_profile(
                &prepared,
                request,
                RawKind::New,
                artifact,
                outputs,
                true,
                write_intent,
            );
        }
        CommandClassification::ArtifactCompletions => {
            let Some(output) = outputs.artifact.take() else {
                eprintln!("sgy: native completions requires explicit --artifact-out");
                return 125;
            };
            let artifact = ArtifactPlan {
                output,
                media_type: completion_media_type(&prepared.defaults.effective_argv),
                source: ArtifactSource::Stdout,
            };
            return execute_raw_profile(
                &prepared,
                request,
                RawKind::Unknown,
                Some(artifact),
                outputs,
                false,
                write_intent,
            );
        }
        CommandClassification::TerminalHelp => {
            let kind = if prepared
                .defaults
                .effective_argv
                .first()
                .is_some_and(|token| token == "--version" || token == "-V")
            {
                RawKind::Version
            } else {
                RawKind::Help
            };
            let artifact = outputs.artifact.take().map(|output| ArtifactPlan {
                output,
                media_type: "text/plain",
                source: ArtifactSource::Stdout,
            });
            return execute_raw_profile(
                &prepared,
                request,
                kind,
                artifact,
                outputs,
                false,
                write_intent,
            );
        }
        CommandClassification::ProtocolLsp => {
            return execute_lsp_profile(&prepared, request, outputs);
        }
        CommandClassification::UnknownOrImplicit => {
            // Future native commands are deliberately opaque to the wrapper. Preserve their
            // argv and stdin instead of guessing batch defaults or rejecting a newer engine.
            request.stdin = StdinMode::Inherit;
            let artifact = outputs.artifact.take().map(|output| ArtifactPlan {
                output,
                media_type: "application/octet-stream",
                source: ArtifactSource::Stdout,
            });
            return execute_raw_profile(
                &prepared,
                request,
                RawKind::Unknown,
                artifact,
                outputs,
                true,
                write_intent,
            );
        }
        CommandClassification::BatchRun | CommandClassification::BatchScan => {}
    }

    if prepared.defaults.classification == CommandClassification::BatchRun {
        match classify_run_output(&prepared.defaults.effective_argv) {
            RunOutputAdapter::Structured {
                input_kind,
                source_format,
            } => {
                let cache = prepare_cache_plan(&prepared, engine);
                return execute_structured_profile(
                    prepared,
                    request,
                    input_kind,
                    source_format,
                    cache,
                    outputs,
                    write_intent,
                );
            }
            adapter @ (RunOutputAdapter::FilesWithMatches | RunOutputAdapter::Text) => {
                let outcome = match run_non_json_adapter(RunAdapterRequest {
                    process: request,
                    adapter,
                    budget: prepared.defaults.settings.budget,
                    stderr_sidecar: outputs.stderr.take(),
                }) {
                    Ok(outcome) => outcome,
                    Err(error) => {
                        eprintln!("sgy: {error}");
                        warn_possible_partial_write(write_intent);
                        return error.wrapper_exit_code();
                    }
                };
                if let Some(yaml) = outcome.yaml.as_ref() {
                    if let Err(code) = commit_or_emit_yaml(yaml.path(), outputs.yaml.as_ref()) {
                        warn_possible_partial_write(write_intent);
                        return code;
                    }
                }
                if outcome.process.cancellation.is_some() || outcome.process.exit_code() != 0 {
                    warn_possible_partial_write(write_intent);
                }
                return outcome.process.exit_code();
            }
            RunOutputAdapter::Interactive => {
                return execute_tty_profile(&prepared, request, outputs);
            }
        }
    }
    match classify_scan_output(&prepared.defaults.effective_argv) {
        ScanOutputAdapter::Structured {
            input_kind,
            source_format,
        } => {
            let cache = prepare_cache_plan(&prepared, engine);
            execute_structured_profile(
                prepared,
                request,
                input_kind,
                source_format,
                cache,
                outputs,
                write_intent,
            )
        }
        adapter @ (ScanOutputAdapter::FilesWithMatches
        | ScanOutputAdapter::GitHub
        | ScanOutputAdapter::Text) => {
            let outcome = match run_scan_non_json_adapter(ScanAdapterRequest {
                process: request,
                adapter,
                budget: prepared.defaults.settings.budget,
                stderr_sidecar: outputs.stderr.take(),
            }) {
                Ok(outcome) => outcome,
                Err(error) => {
                    eprintln!("sgy: {error}");
                    warn_possible_partial_write(write_intent);
                    return error.wrapper_exit_code();
                }
            };
            if let Some(yaml) = outcome.yaml.as_ref() {
                if let Err(code) = commit_or_emit_yaml(yaml.path(), outputs.yaml.as_ref()) {
                    warn_possible_partial_write(write_intent);
                    return code;
                }
            }
            if outcome.process.cancellation.is_some() || outcome.process.exit_code() != 0 {
                warn_possible_partial_write(write_intent);
            }
            outcome.process.exit_code()
        }
        ScanOutputAdapter::Interactive => execute_tty_profile(&prepared, request, outputs),
    }
}

struct PreparedDestinations {
    yaml: Option<PreparedOutput>,
    artifact: Option<PreparedOutput>,
    stderr: Option<StderrSidecarPlan>,
    meta: Option<PreparedOutput>,
}

fn prepare_destinations(
    explicit: &sgy_core::invocation::ExplicitOptions,
) -> Result<PreparedDestinations, (i32, String)> {
    let prepare = |path: Option<&PathBuf>| {
        path.map(PreparedOutput::prepare)
            .transpose()
            .map_err(|error| (error.wrapper_exit_code(), error.to_string()))
    };
    let yaml = prepare(explicit.yaml_out.as_ref())?;
    let artifact = prepare(explicit.artifact_out.as_ref())?;
    let meta = prepare(explicit.meta_out.as_ref())?;
    let stderr = if let Some(path) = explicit.stderr_yaml.as_ref() {
        let manifest = PreparedOutput::prepare(path)
            .map_err(|error| (error.wrapper_exit_code(), error.to_string()))?;
        let raw_path = append_raw_suffix(path);
        let raw = PreparedOutput::prepare(&raw_path)
            .map_err(|error| (error.wrapper_exit_code(), error.to_string()))?;
        Some(StderrSidecarPlan::new(manifest, raw))
    } else {
        None
    };

    let mut paths = Vec::new();
    if let Some(output) = &yaml {
        paths.push(output.path());
    }
    if let Some(output) = &artifact {
        paths.push(output.path());
    }
    if let Some(output) = &meta {
        paths.push(output.path());
    }
    if let Some(sidecar) = &stderr {
        paths.extend(sidecar.paths());
    }
    let mut distinct = HashSet::new();
    for path in paths {
        if !distinct.insert(output_path_key(path)) {
            return Err((
                125,
                format!("wrapper output paths must be distinct: {}", path.display()),
            ));
        }
    }
    Ok(PreparedDestinations {
        yaml,
        artifact,
        stderr,
        meta,
    })
}

fn append_raw_suffix(path: &Path) -> PathBuf {
    let mut value: OsString = path.as_os_str().to_os_string();
    value.push(".raw");
    PathBuf::from(value)
}

fn execute_tty_profile(
    prepared: &sgy_core::prepare::PreparedInvocation,
    request: ProcessRequest,
    outputs: PreparedDestinations,
) -> i32 {
    let engine_version = outputs
        .meta
        .as_ref()
        .map(|_| engine_version_for_metadata(prepared));
    let started_at = std::time::SystemTime::now();
    let outcome = match run_tty(request) {
        Ok(outcome) => outcome,
        Err(error) => {
            eprintln!("sgy: {error}");
            return error.wrapper_exit_code();
        }
    };
    let ended_at = std::time::SystemTime::now();
    if let Some(output) = outputs.meta.as_ref() {
        if let Err(error) = commit_metadata(MetadataRequest {
            output,
            channel: PassthroughChannel::Tty,
            engine_version: engine_version.as_deref().unwrap_or("unknown"),
            user_argv: &prepared.defaults.user_argv,
            effective_argv: &prepared.defaults.effective_argv,
            started_at,
            ended_at,
            native_exit_code: outcome.native_status.code(),
            cancelled: outcome.cancellation.is_some(),
            stdin_bytes: None,
            stdout_bytes: None,
            stderr_bytes: None,
            wrapper_error_origin: None,
        }) {
            eprintln!("sgy: {error}");
            return error.wrapper_exit_code();
        }
    }
    outcome.exit_code()
}

fn execute_lsp_profile(
    prepared: &sgy_core::prepare::PreparedInvocation,
    request: ProcessRequest,
    mut outputs: PreparedDestinations,
) -> i32 {
    let engine_version = outputs
        .meta
        .as_ref()
        .map(|_| engine_version_for_metadata(prepared));
    let started_at = std::time::SystemTime::now();
    let outcome = match run_lsp(request) {
        Ok(outcome) => outcome,
        Err(error) => {
            eprintln!("sgy: {error}");
            return error.wrapper_exit_code();
        }
    };
    let ended_at = std::time::SystemTime::now();
    let stderr_error = if outcome.cancellation.is_none() {
        commit_stderr_sidecar(outputs.stderr.take(), outcome.stderr_path())
            .err()
            .map(|error| error.to_string())
    } else {
        None
    };
    if let Some(output) = outputs.meta.as_ref() {
        if let Err(error) = commit_metadata(MetadataRequest {
            output,
            channel: PassthroughChannel::Lsp,
            engine_version: engine_version.as_deref().unwrap_or("unknown"),
            user_argv: &prepared.defaults.user_argv,
            effective_argv: &prepared.defaults.effective_argv,
            started_at,
            ended_at,
            native_exit_code: outcome.native_status.code(),
            cancelled: outcome.cancellation.is_some(),
            stdin_bytes: Some(outcome.stdin_bytes),
            stdout_bytes: Some(outcome.stdout_bytes),
            stderr_bytes: Some(outcome.stderr_bytes),
            wrapper_error_origin: stderr_error.as_ref().map(|_| "stderr_sidecar"),
        }) {
            eprintln!("sgy: {error}");
            return error.wrapper_exit_code();
        }
    }
    if let Some(error) = stderr_error {
        eprintln!("sgy: {error}");
        return 127;
    }
    outcome.exit_code()
}

fn engine_version_for_metadata(prepared: &sgy_core::prepare::PreparedInvocation) -> String {
    let Some(engine) = prepared.engine.as_ref() else {
        return "unknown".to_owned();
    };
    if let Some(version) = engine.version_line.as_ref() {
        return version.clone();
    }
    let environment = SystemEngineEnvironment::from_process_environment();
    environment
        .probe_version(&engine.path)
        .ok()
        .filter(|probe| probe.status.success())
        .and_then(|probe| {
            String::from_utf8(probe.stdout).ok().and_then(|text| {
                text.lines()
                    .find(|line| !line.trim().is_empty())
                    .map(str::trim)
                    .map(str::to_owned)
            })
        })
        .unwrap_or_else(|| "unknown".to_owned())
}

#[cfg(windows)]
fn output_path_key(path: &Path) -> String {
    path.to_string_lossy().to_lowercase()
}

#[cfg(not(windows))]
fn output_path_key(path: &Path) -> OsString {
    path.as_os_str().to_os_string()
}

fn execute_raw_profile(
    prepared: &sgy_core::prepare::PreparedInvocation,
    request: ProcessRequest,
    kind: RawKind,
    artifact: Option<ArtifactPlan>,
    mut outputs: PreparedDestinations,
    may_have_native_side_effects: bool,
    write_intent: WriteIntent,
) -> i32 {
    let outcome = match run_raw_adapter(RawAdapterRequest {
        process: request,
        budget: prepared.defaults.settings.budget,
        kind,
        artifact,
        stderr_sidecar: outputs.stderr.take(),
    }) {
        Ok(outcome) => outcome,
        Err(error) => {
            eprintln!("sgy: {error}");
            warn_possible_partial_write(write_intent);
            warn_possible_native_side_effects(may_have_native_side_effects);
            return error.wrapper_exit_code();
        }
    };
    if let Some(yaml) = outcome.yaml.as_ref() {
        if let Err(code) = commit_or_emit_yaml(yaml.path(), outputs.yaml.as_ref()) {
            warn_possible_partial_write(write_intent);
            warn_possible_native_side_effects(may_have_native_side_effects);
            return code;
        }
    }
    if outcome.process.cancellation.is_some() || outcome.process.exit_code() != 0 {
        warn_possible_partial_write(write_intent);
        warn_possible_native_side_effects(may_have_native_side_effects);
    }
    outcome.process.exit_code()
}

fn warn_possible_native_side_effects(may_have_native_side_effects: bool) {
    if may_have_native_side_effects {
        eprintln!(
            "sgy: native command may have created or changed files before wrapper output failed"
        );
    }
}

fn execute_structured_profile(
    prepared: sgy_core::prepare::PreparedInvocation,
    request: ProcessRequest,
    input_kind: sgy_core::codec::JsonInputKind,
    source_format: sgy_core::cache::SourceFormat,
    cache: CachePlan,
    mut outputs: PreparedDestinations,
    write_intent: WriteIntent,
) -> i32 {
    let outcome = match run_profile_batch(ProfileBatchRequest {
        process: request,
        input_kind,
        source_format,
        profile: prepared.defaults.settings.profile,
        budget: prepared.defaults.settings.budget,
        keep_fields: prepared.defaults.settings.keep_paths.clone(),
        prune_fields: prepared.defaults.settings.prune_paths.clone(),
        cache,
        now: std::time::SystemTime::now(),
        write_intent,
        stderr_sidecar: outputs.stderr.take(),
    }) {
        Ok(outcome) => outcome,
        Err(error) => {
            eprintln!("sgy: {error}");
            warn_possible_partial_write(write_intent);
            return error.wrapper_exit_code();
        }
    };
    if let Some(yaml) = outcome.yaml.as_ref() {
        if let Err(code) = commit_or_emit_yaml(yaml.path(), outputs.yaml.as_ref()) {
            warn_possible_partial_write(write_intent);
            return code;
        }
    }
    if outcome.process.cancellation.is_some() || outcome.process.exit_code() != 0 {
        warn_possible_partial_write(write_intent);
    }
    outcome.process.exit_code()
}

fn warn_possible_partial_write(write_intent: WriteIntent) {
    if write_intent.may_modify_files() {
        eprintln!(
            "sgy: native update may have partially modified files; no transaction or rollback was attempted"
        );
    }
}

fn prepare_cache_plan(
    prepared: &sgy_core::prepare::PreparedInvocation,
    engine: &sgy_core::engine::DiscoveredEngine,
) -> CachePlan {
    let mode = prepared.defaults.settings.cache_mode;
    if mode == CacheMode::Off {
        return CachePlan::off();
    }
    let root = match default_cache_root() {
        Ok(root) => root,
        Err(error) => return CachePlan::unavailable(mode, error),
    };
    let store = match CacheStore::open(
        root,
        Some(&prepared.settings.child_cwd.path),
        CacheLimits::default(),
    ) {
        Ok(store) => store,
        Err(error) => return CachePlan::unavailable(mode, error),
    };
    let injected = prepared
        .defaults
        .injected
        .iter()
        .map(|value| value.to_string_lossy().into_owned())
        .collect();
    let engine_version = engine_version_for_metadata(prepared);
    let audit = CacheAudit::from_argv(
        &engine.path,
        &engine_version,
        &prepared.settings.child_cwd.path,
        &prepared.defaults.user_argv,
        &prepared.defaults.effective_argv,
        injected,
        prepared.defaults.settings.profile,
        mode,
    );
    CachePlan::ready(store, audit)
}

fn commit_or_emit_yaml(path: &Path, final_output: Option<&PreparedOutput>) -> Result<(), i32> {
    if let Some(output) = final_output {
        output.commit_from_path(path).map(|_| ()).map_err(|error| {
            eprintln!("sgy: {error}");
            error.wrapper_exit_code()
        })
    } else {
        emit_staged_yaml(path).map_err(|error| {
            eprintln!("sgy: failed to write YAML stdout: {error}");
            127
        })
    }
}

fn emit_staged_yaml(path: &Path) -> io::Result<()> {
    let mut source = std::fs::File::open(path)?;
    let mut stdout = io::stdout().lock();
    io::copy(&mut source, &mut stdout)?;
    stdout.flush()
}
