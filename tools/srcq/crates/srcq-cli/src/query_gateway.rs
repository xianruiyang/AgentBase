//! Native-argv-compatible rg/fd/scc gateway. AST commands deliberately remain in their existing path.

mod scc;

use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{self, Cursor, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::SystemTime,
};

use fs2::FileExt;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use srcq_core::{
    codec::write_yaml_document,
    process::{run, CancellationToken, PreparedOutput, ProcessRequest, StdinMode},
};

use crate::{GatewayBackend, GatewayCommand, GatewayOperation};
use srcq_core::invocation::OutputFormat;

const MAX_STDOUT_BYTES: u64 = 256 * 1024 * 1024;
const MAX_STDERR_BYTES: u64 = 16 * 1024 * 1024;
const MAX_SPOOL_ENTRIES: usize = 32;
const MAX_CONTINUATION_ENTRIES: usize = 128;
const MAX_CONTINUATION_NUMBER: u64 = 999_999;
const CONTINUATION_SCHEMA: &str = "sgy.query.continuation/v1";
pub(super) const DIRECT_COMPLETE_MAX_UNITS: usize = 512;
const DIRECT_SINGLE_PATH_MAX_TEXT_CHARS: usize = 1024;
const SCC_SHORT_VALUE_OPTIONS: &[char] = &['x', 'n', 'i', 'M', 'f', 'o', 's'];
const SCC_LONG_VALUE_OPTIONS: &[&str] = &[
    "--avg-wage",
    "--cocomo-project-type",
    "--count-as",
    "--currency-symbol",
    "--directory-walker-job-workers",
    "--eaf",
    "--exclude-dir",
    "--exclude-ext",
    "--exclude-file",
    "--file-gc-count",
    "--file-list-queue-size",
    "--file-process-job-workers",
    "--file-summary-job-queue-size",
    "--format",
    "--format-multi",
    "--generated-markers",
    "--include-ext",
    "--large-byte-count",
    "--large-line-count",
    "--min-gen-line-length",
    "--not-match",
    "--output",
    "--overhead",
    "--remap-all",
    "--remap-unknown",
    "--size-unit",
    "--sort",
    "--sql-project",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Handling {
    Adaptive,
    Structured,
    BoundedText,
    Artifact,
    Passthrough,
}

#[derive(Clone, Copy, Debug)]
struct Mode {
    id: &'static str,
    handling: Handling,
}

#[derive(Debug)]
struct GatewayError {
    message: String,
    code: i32,
}

impl GatewayError {
    fn input(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            code: 125,
        }
    }

    fn io(context: &str, source: impl std::fmt::Display) -> Self {
        Self {
            message: format!("{context}: {source}"),
            code: 126,
        }
    }

    fn conversion(context: &str, source: impl std::fmt::Display) -> Self {
        Self {
            message: format!("{context}: {source}"),
            code: 124,
        }
    }
}

impl std::fmt::Display for GatewayError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

#[derive(Debug)]
struct Captured {
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    native_exit: i32,
}

#[derive(Debug)]
struct Snapshot {
    id: String,
    query_fingerprint: String,
    engine_version: String,
    native_exit: i32,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    fd_types: BTreeMap<String, String>,
}

#[derive(Debug)]
struct Projection {
    value: Value,
    model: String,
    displayed: usize,
    total: usize,
    view: String,
    display_complete: bool,
}

pub fn execute(command: &GatewayCommand) -> i32 {
    match execute_inner(command) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("srcq: {error}");
            error.code
        }
    }
}

pub fn execute_continuation(handle: &str) -> i32 {
    match load_continuation(handle) {
        Ok(command) => execute(&command),
        Err(error) => {
            eprintln!("srcq: {error}");
            error.code
        }
    }
}

fn execute_inner(command: &GatewayCommand) -> Result<i32, GatewayError> {
    let launch_cwd = std::env::current_dir()
        .map_err(|error| GatewayError::io("cannot read current directory", error))?;
    let cwd = resolve_cwd(command.cwd.as_deref(), &launch_cwd)?;
    if command.operation == GatewayOperation::Defaults {
        let engine = command
            .engine
            .clone()
            .unwrap_or_else(|| PathBuf::from(engine_name(command.backend)));
        return execute_defaults(command, &engine, &cwd);
    }
    let engine = resolve_engine(command.backend, command.engine.as_deref())?;
    match command.operation {
        GatewayOperation::Doctor => execute_doctor(command, &engine, &cwd),
        GatewayOperation::Defaults => unreachable!("defaults returns before engine discovery"),
        GatewayOperation::Exec => execute_query(command, &engine, &cwd),
    }
}

fn resolve_cwd(requested: Option<&Path>, launch: &Path) -> Result<PathBuf, GatewayError> {
    let path = requested.unwrap_or(launch);
    path.canonicalize()
        .map_err(|error| GatewayError::io("cannot resolve --cwd", error))
}

fn engine_name(backend: GatewayBackend) -> &'static str {
    match backend {
        GatewayBackend::Rg => "rg.exe",
        GatewayBackend::Fd => "fd.exe",
        GatewayBackend::Scc => "scc.exe",
    }
}

fn backend_name(backend: GatewayBackend) -> &'static str {
    match backend {
        GatewayBackend::Rg => "rg",
        GatewayBackend::Fd => "fd",
        GatewayBackend::Scc => "scc",
    }
}

fn resolve_engine(
    backend: GatewayBackend,
    explicit: Option<&Path>,
) -> Result<PathBuf, GatewayError> {
    if let Some(path) = explicit {
        return path
            .canonicalize()
            .map_err(|error| GatewayError::io("cannot resolve --engine", error));
    }
    let variable = match backend {
        GatewayBackend::Rg => "SRCQ_RG_PATH",
        GatewayBackend::Fd => "SRCQ_FD_PATH",
        GatewayBackend::Scc => "SRCQ_SCC_PATH",
    };
    if let Some(path) = std::env::var_os(variable) {
        return PathBuf::from(path)
            .canonicalize()
            .map_err(|error| GatewayError::io(&format!("cannot resolve {variable}"), error));
    }
    let Some(paths) = std::env::var_os("PATH") else {
        return Err(GatewayError::input(format!(
            "{} is not available on PATH",
            engine_name(backend)
        )));
    };
    for directory in std::env::split_paths(&paths) {
        let candidate = directory.join(engine_name(backend));
        if candidate.is_file() {
            return candidate
                .canonicalize()
                .map_err(|error| GatewayError::io("cannot canonicalize native engine", error));
        }
    }
    Err(GatewayError::input(format!(
        "{} is not available; use --engine",
        engine_name(backend)
    )))
}

fn execute_doctor(
    command: &GatewayCommand,
    engine: &Path,
    cwd: &Path,
) -> Result<i32, GatewayError> {
    let backend = command.backend;
    let version = native_version(engine, cwd)?
        .lines()
        .next()
        .unwrap_or("unknown")
        .to_owned();
    let value = json!({"_sgy":{"schema":"sgy.query.doctor/v1","backend":backend_name(backend),"ok":true},"engine":engine,"cwd":cwd,"observed_version":version.trim()});
    if command.output == OutputFormat::Machine {
        emit_yaml(&value)?;
    } else {
        emit_model_text("ok")?;
    }
    Ok(0)
}

fn execute_defaults(
    command: &GatewayCommand,
    engine: &Path,
    cwd: &Path,
) -> Result<i32, GatewayError> {
    let mode = classify(command.backend, &command.native_argv);
    validate_view(command.backend, &command.view)?;
    validate_mode_view(
        command.backend,
        mode,
        &command.view,
        command.artifact_out.is_some(),
    )?;
    let injected = injected_argv(command.backend, mode, &command.native_argv);
    let effective = effective_argv(&command.native_argv, &injected);
    let value = json!({
        "_sgy":{"schema":"sgy.query.defaults/v1","backend":backend_name(command.backend)},
        "engine":engine,
        "cwd":cwd,
        "mode":mode.id,
        "handling":handling_name(mode.handling),
        "view":command.view,
        "receipt":command.receipt,
        "user_argv":os_args_json(&command.native_argv)?,
        "injected_argv":os_args_json(&injected)?,
        "effective_argv":os_args_json(&effective)?,
        "engine_started":false
    });
    if command.output == OutputFormat::Machine {
        emit_yaml(&value)?;
    } else {
        let mut lines = vec![format!("{} {}", mode.id, handling_name(mode.handling))];
        if !injected.is_empty() {
            lines.push(format!("+ {}", os_args_json(&injected)?.join(" ")));
        }
        if injected.is_empty() {
            lines.push("unchanged".to_owned());
        }
        emit_model_text(&lines.join("\n"))?;
    }
    Ok(0)
}

fn execute_query(command: &GatewayCommand, engine: &Path, cwd: &Path) -> Result<i32, GatewayError> {
    validate_view(command.backend, &command.view)?;
    let mode = classify(command.backend, &command.native_argv);
    validate_mode_view(
        command.backend,
        mode,
        &command.view,
        command.artifact_out.is_some(),
    )?;
    if command.receipt == "full"
        && (mode.handling == Handling::Passthrough || command.view == "raw")
    {
        return Err(GatewayError::input(
            "--receipt full requires a model-visible structured or bounded-text result",
        ));
    }
    if command.native_argv.iter().any(|arg| arg.to_str().is_none())
        && command.view != "raw"
        && command.artifact_out.is_none()
        && mode.handling != Handling::Passthrough
    {
        return Err(GatewayError::input("native argv contains non-UTF-8 Windows text; use raw, artifact, or native passthrough mode"));
    }
    if mode.handling == Handling::Passthrough {
        if command.artifact_out.is_some()
            || command.snapshot.is_some()
            || command.after.is_some()
            || command.view != "auto"
        {
            return Err(GatewayError::input(
                "passthrough mode conflicts with view, snapshot, cursor, or artifact options",
            ));
        }
        return execute_passthrough(engine, cwd, &command.native_argv);
    }
    if mode.handling == Handling::Artifact {
        let Some(destination) = command.artifact_out.as_deref() else {
            return Err(GatewayError::input(format!("{} requires the explicit artifact channel: srcq query {} exec --artifact-out PATH -- <native argv...>", mode.id, backend_name(command.backend))));
        };
        let prepared = PreparedOutput::prepare(destination).map_err(|error| GatewayError {
            message: error.to_string(),
            code: error.wrapper_exit_code(),
        })?;
        let captured = run_native(engine, cwd, command.native_argv.clone())?;
        write_native_stderr(&captured.stderr, true, command.max_text_chars)?;
        let bytes = prepared
            .commit_from_reader(Cursor::new(&captured.stdout))
            .map_err(|error| GatewayError {
                message: error.to_string(),
                code: error.wrapper_exit_code(),
            })?;
        emit_artifact_result(command, mode, prepared.path(), bytes, &captured)?;
        return Ok(captured.native_exit);
    }
    if matches!(mode.handling, Handling::BoundedText)
        || command.view == "raw"
        || command.artifact_out.is_some()
    {
        if command.snapshot.is_some() || command.after.is_some() {
            return Err(GatewayError::input(
                "raw, artifact, and bounded-text modes do not support structured cursors",
            ));
        }
        let prepared = command
            .artifact_out
            .as_deref()
            .map(PreparedOutput::prepare)
            .transpose()
            .map_err(|error| GatewayError {
                message: error.to_string(),
                code: error.wrapper_exit_code(),
            })?;
        let captured = run_native(engine, cwd, command.native_argv.clone())?;
        write_native_stderr(
            &captured.stderr,
            command.view == "raw" || prepared.is_some(),
            command.max_text_chars,
        )?;
        if let Some(prepared) = prepared {
            prepared
                .commit_from_reader(Cursor::new(&captured.stdout))
                .map_err(|error| GatewayError {
                    message: error.to_string(),
                    code: error.wrapper_exit_code(),
                })?;
            emit_artifact_result(
                command,
                mode,
                prepared.path(),
                captured.stdout.len() as u64,
                &captured,
            )?;
        } else if command.view == "raw" {
            io::stdout()
                .lock()
                .write_all(&captured.stdout)
                .map_err(|error| GatewayError::io("cannot write native stdout", error))?;
        } else {
            emit_bounded_text(command, mode, &captured.stdout, captured.native_exit)?;
        }
        return Ok(captured.native_exit);
    }

    let version = native_version(engine, cwd)?
        .lines()
        .next()
        .unwrap_or("unknown")
        .to_owned();
    let query_fingerprint =
        query_fingerprint(command.backend, engine, cwd, &command.native_argv, &version);
    let inferred_snapshot = command.after.as_deref().map(cursor_snapshot).transpose()?;
    let requested_snapshot = command.snapshot.as_deref().or(inferred_snapshot.as_deref());
    let fresh_snapshot = requested_snapshot.is_none();
    let mut snapshot = if let Some(id) = requested_snapshot {
        let loaded = load_snapshot(id)?;
        if loaded.query_fingerprint != query_fingerprint {
            return Err(GatewayError::input(
                "snapshot does not belong to the current backend/cwd/native argv",
            ));
        }
        loaded
    } else {
        let injected = injected_argv(command.backend, mode, &command.native_argv);
        let effective = effective_argv(&command.native_argv, &injected);
        let captured = run_native(engine, cwd, effective)?;
        write_native_stderr(&captured.stderr, false, command.max_text_chars)?;
        create_snapshot(
            command.backend,
            cwd,
            &command.native_argv,
            query_fingerprint,
            version,
            captured,
        )?
    };
    let (offset, cursor_view) =
        parse_cursor(command.after.as_deref(), &snapshot.id, &command.view)?;
    let mut rendering = command.clone();
    if let Some(view) = cursor_view {
        rendering.view = view;
    }
    let projection_result = match command.backend {
        GatewayBackend::Fd => render_fd(&rendering, cwd, &snapshot, offset),
        GatewayBackend::Scc => scc::render(
            &rendering,
            mode.id == "SCC-FILES",
            &snapshot.stdout,
            snapshot.native_exit,
            offset,
        )
        .map(|projection| Projection {
            value: projection.value,
            model: projection.model,
            displayed: projection.displayed,
            total: projection.total,
            view: projection.view,
            display_complete: projection.display_complete,
        })
        .map_err(GatewayError::input),
        GatewayBackend::Rg
            if matches!(
                mode.id,
                "RG-FILES" | "RG-FILES-WITH-MATCHES" | "RG-FILES-WITHOUT-MATCH"
            ) =>
        {
            render_rg_files(&rendering, &snapshot, offset)
        }
        GatewayBackend::Rg if matches!(mode.id, "RG-COUNT" | "RG-COUNT-MATCHES") => {
            render_rg_counts(&rendering, &snapshot, offset)
        }
        GatewayBackend::Rg if mode.id == "RG-VIMGREP" => {
            render_rg_vimgrep(&rendering, &snapshot, offset)
        }
        GatewayBackend::Rg => render_rg(&rendering, &snapshot, offset),
    };
    let projection = match projection_result {
        Ok(projection) => projection,
        Err(error) => {
            if let Some(exit) =
                try_model_native_fallback(command, mode, engine, cwd, &snapshot, fresh_snapshot)?
            {
                return Ok(exit);
            }
            return Err(GatewayError::conversion(
                "cannot convert native query output",
                error,
            ));
        }
    };
    let end = offset.saturating_add(projection.displayed);
    let has_next = !projection.display_complete && end < projection.total;
    if fresh_snapshot && (has_next || command.receipt == "full") {
        ensure_snapshot_id(&mut snapshot)?;
        persist_snapshot(&snapshot)?;
    }
    let next = has_next.then(|| make_cursor(&snapshot.id, &projection.view, end));
    let mut root = projection.value.as_object().cloned().unwrap_or_default();
    let result_complete = match command.backend {
        GatewayBackend::Rg => matches!(snapshot.native_exit, 0 | 1),
        GatewayBackend::Fd => snapshot.native_exit == 0,
        GatewayBackend::Scc => snapshot.native_exit == 0,
    };
    let content_complete = match command.backend {
        GatewayBackend::Fd => projection.view != "summary" || projection.total == 0,
        GatewayBackend::Scc => true,
        GatewayBackend::Rg
            if matches!(
                mode.id,
                "RG-FILES"
                    | "RG-FILES-WITH-MATCHES"
                    | "RG-FILES-WITHOUT-MATCH"
                    | "RG-COUNT"
                    | "RG-COUNT-MATCHES"
            ) =>
        {
            projection.view != "summary" || projection.total == 0
        }
        GatewayBackend::Rg if mode.id == "RG-VIMGREP" => root
            .get("text_complete")
            .and_then(Value::as_bool)
            .unwrap_or(projection.view == "lossless"),
        GatewayBackend::Rg => match projection.view.as_str() {
            "lossless" => true,
            "grouped" | "records" => root
                .get("text_complete")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            _ => projection.total == 0,
        },
    };
    let machine = command.output == OutputFormat::Machine
        || command.receipt == "full"
        || projection.view == "lossless";
    if machine {
        root.insert(
            "_sgy".to_owned(),
            structured_receipt(
                command,
                mode,
                &snapshot,
                &projection.view,
                projection.total,
                projection.displayed,
                offset,
                next.as_deref(),
                result_complete,
                projection.display_complete,
                content_complete,
            ),
        );
        emit_compact_json(&Value::Object(root))?;
    } else {
        let mut model = projection.model;
        if let Some(cursor) = next.as_deref() {
            push_model_line(
                &mut model,
                &format!(
                    "@more shown={} omitted={}",
                    projection.displayed,
                    projection.total.saturating_sub(end)
                ),
            );
            let handle = persist_continuation(command, cursor, engine, cwd)?;
            push_model_line(&mut model, &format!("@next srcq more {handle}"));
        }
        let cut = model_text_cut_count(command.backend, &projection.view, &root);
        if cut > 0 {
            push_model_line(&mut model, &format!("@cut text={cut}"));
        }
        emit_model_text(&model)?;
    }
    Ok(snapshot.native_exit)
}

#[allow(clippy::too_many_arguments)]
fn structured_receipt(
    command: &GatewayCommand,
    mode: Mode,
    snapshot: &Snapshot,
    chosen_view: &str,
    total: usize,
    displayed: usize,
    offset: usize,
    next_cursor: Option<&str>,
    result_complete: bool,
    display_complete: bool,
    content_complete: bool,
) -> Value {
    let end = offset.saturating_add(displayed);
    if command.receipt == "full" {
        return json!({
            "schema":"sgy.query.result/v1","backend":backend_name(command.backend),"mode":mode.id,
            "engine_version":snapshot.engine_version,"query_snapshot":snapshot.id,
            "view":chosen_view,"native_exit":snapshot.native_exit,"result_total":total,"displayed":displayed,
            "omitted":total.saturating_sub(end),"result_complete":result_complete,"display_complete":display_complete,
            "content_complete":content_complete,
            "offset":offset,"next_cursor":next_cursor,"stdout_bytes":snapshot.stdout.len(),"stderr_bytes":snapshot.stderr.len()
        });
    }

    let mut receipt = Map::new();
    receipt.insert("schema".to_owned(), json!("sgy.query.result/v2"));
    receipt.insert("result_total".to_owned(), json!(total));
    receipt.insert(
        "complete".to_owned(),
        json!({
            "result":result_complete,
            "display":display_complete,
            "content":content_complete
        }),
    );
    if snapshot.native_exit != 0 {
        receipt.insert("native_exit".to_owned(), json!(snapshot.native_exit));
    }
    if !display_complete {
        receipt.insert("displayed".to_owned(), json!(displayed));
        receipt.insert("omitted".to_owned(), json!(total.saturating_sub(end)));
        receipt.insert("query_snapshot".to_owned(), json!(snapshot.id));
        receipt.insert("next_cursor".to_owned(), json!(next_cursor));
    }
    Value::Object(receipt)
}

fn emit_compact_json(value: &Value) -> Result<(), GatewayError> {
    let mut bytes = serde_json::to_vec(value)
        .map_err(|error| GatewayError::input(format!("cannot serialize query result: {error}")))?;
    bytes.push(b'\n');
    io::stdout()
        .lock()
        .write_all(&bytes)
        .map_err(|error| GatewayError::io("cannot write query result", error))
}

fn emit_model_text(value: &str) -> Result<(), GatewayError> {
    if value.is_empty() {
        return Ok(());
    }
    let mut stdout = io::stdout().lock();
    stdout
        .write_all(value.as_bytes())
        .and_then(|()| stdout.write_all(b"\n"))
        .and_then(|()| stdout.flush())
        .map_err(|error| GatewayError::io("cannot write model evidence", error))
}

fn push_model_line(output: &mut String, line: &str) {
    if !output.is_empty() && !output.ends_with('\n') {
        output.push('\n');
    }
    output.push_str(line);
}

fn model_text_cut_count(backend: GatewayBackend, view: &str, root: &Map<String, Value>) -> usize {
    if backend != GatewayBackend::Rg || !matches!(view, "grouped" | "records" | "locations") {
        return 0;
    }
    if let Some(count) = root
        .get("text_truncated_records")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
    {
        return count;
    }
    root.get("locations")
        .and_then(Value::as_array)
        .map(|records| {
            records
                .iter()
                .filter(|record| {
                    record.get("text_complete").and_then(Value::as_bool) == Some(false)
                })
                .count()
        })
        .unwrap_or(0)
}

fn emit_artifact_result(
    command: &GatewayCommand,
    mode: Mode,
    path: &Path,
    bytes: u64,
    captured: &Captured,
) -> Result<(), GatewayError> {
    if command.output == OutputFormat::Machine || command.receipt == "full" {
        return emit_yaml(&json!({
            "_sgy":{"schema":"sgy.query.artifact/v1","backend":backend_name(command.backend),"mode":mode.id},
            "artifact":path,
            "bytes":bytes,
            "sha256":sha256_hex(&captured.stdout),
            "native_exit":captured.native_exit,
            "stderr_bytes":captured.stderr.len()
        }));
    }
    let normalized = path.to_string_lossy().replace('\\', "/");
    let normalized = if let Some(rest) = normalized.strip_prefix("//?/UNC/") {
        format!("//{rest}")
    } else {
        normalized
            .strip_prefix("//?/")
            .unwrap_or(&normalized)
            .to_owned()
    };
    emit_model_text(&normalized)
}

fn validate_view(backend: GatewayBackend, view: &str) -> Result<(), GatewayError> {
    let valid = match backend {
        GatewayBackend::Rg => [
            "auto",
            "grouped",
            "records",
            "locations",
            "files",
            "summary",
            "lossless",
            "raw",
        ]
        .contains(&view),
        GatewayBackend::Fd => {
            ["auto", "tree", "flat", "summary", "lossless", "raw"].contains(&view)
        }
        GatewayBackend::Scc => [
            "auto",
            "summary",
            "languages",
            "files",
            "hotspots",
            "lossless",
            "raw",
        ]
        .contains(&view),
    };
    valid.then_some(()).ok_or_else(|| {
        GatewayError::input(format!(
            "view {view:?} is not valid for {}",
            backend_name(backend)
        ))
    })
}

fn validate_mode_view(
    backend: GatewayBackend,
    mode: Mode,
    view: &str,
    artifact: bool,
) -> Result<(), GatewayError> {
    if artifact && !matches!(view, "auto" | "raw") {
        return Err(GatewayError::input(
            "--artifact-out conflicts with structured projection views",
        ));
    }
    let valid = match (backend, mode.handling, mode.id) {
        (_, Handling::Passthrough, _) => view == "auto",
        (_, Handling::Artifact, _) => view == "auto",
        (_, Handling::BoundedText, _) => matches!(view, "auto" | "raw"),
        (GatewayBackend::Fd, _, "FD-PATHS") => matches!(
            view,
            "auto" | "tree" | "flat" | "summary" | "lossless" | "raw"
        ),
        (GatewayBackend::Scc, _, "SCC-LANGUAGES") => {
            matches!(view, "auto" | "summary" | "languages" | "lossless" | "raw")
        }
        (GatewayBackend::Scc, _, "SCC-FILES") => matches!(
            view,
            "auto" | "summary" | "languages" | "files" | "hotspots" | "lossless" | "raw"
        ),
        (
            GatewayBackend::Rg,
            _,
            "RG-FILES" | "RG-FILES-WITH-MATCHES" | "RG-FILES-WITHOUT-MATCH",
        ) => matches!(view, "auto" | "files" | "summary" | "lossless" | "raw"),
        (GatewayBackend::Rg, _, "RG-COUNT" | "RG-COUNT-MATCHES") => {
            matches!(view, "auto" | "summary" | "lossless" | "raw")
        }
        (GatewayBackend::Rg, _, "RG-VIMGREP") => {
            matches!(view, "auto" | "locations" | "summary" | "lossless" | "raw")
        }
        (GatewayBackend::Rg, _, _) => matches!(
            view,
            "auto" | "grouped" | "records" | "locations" | "files" | "summary" | "lossless" | "raw"
        ),
        _ => false,
    };
    valid.then_some(()).ok_or_else(|| {
        GatewayError::input(format!("view {view:?} is not valid for mode {}", mode.id))
    })
}

fn handling_name(handling: Handling) -> &'static str {
    match handling {
        Handling::Adaptive => "adaptive",
        Handling::Structured => "structured",
        Handling::BoundedText => "bounded-text",
        Handling::Artifact => "artifact",
        Handling::Passthrough => "passthrough",
    }
}

fn has(backend: GatewayBackend, args: &[OsString], names: &[&str]) -> bool {
    let short_values: &[char] = match backend {
        GatewayBackend::Rg => &[
            'A', 'B', 'C', 'd', 'E', 'e', 'f', 'g', 'j', 'M', 'm', 'r', 't', 'T',
        ],
        GatewayBackend::Fd => &['d', 'E', 't', 'e', 'S', 'c', 'j', 'C', 'x', 'X'],
        GatewayBackend::Scc => SCC_SHORT_VALUE_OPTIONS,
    };
    let long_values: &[&str] = match backend {
        GatewayBackend::Rg => &[
            "--regexp",
            "--file",
            "--pre",
            "--pre-glob",
            "--dfa-size-limit",
            "--encoding",
            "--engine",
            "--max-count",
            "--regex-size-limit",
            "--threads",
            "--glob",
            "--iglob",
            "--ignore-file",
            "--max-depth",
            "--max-filesize",
            "--type",
            "--type-not",
            "--type-add",
            "--type-clear",
            "--after-context",
            "--before-context",
            "--color",
            "--colors",
            "--context",
            "--context-separator",
            "--field-context-separator",
            "--field-match-separator",
            "--hostname-bin",
            "--hyperlink-format",
            "--max-columns",
            "--path-separator",
            "--replace",
            "--sort",
            "--sortr",
            "--generate",
        ],
        GatewayBackend::Fd => &[
            "--and",
            "--max-depth",
            "--min-depth",
            "--exact-depth",
            "--exclude",
            "--type",
            "--extension",
            "--size",
            "--changed-within",
            "--changed-before",
            "--format",
            "--exec",
            "--exec-batch",
            "--batch-size",
            "--ignore-file",
            "--color",
            "--ignore-contain",
            "--threads",
            "--max-results",
            "--base-directory",
            "--path-separator",
            "--search-path",
        ],
        GatewayBackend::Scc => SCC_LONG_VALUE_OPTIONS,
    };
    let short_targets = names
        .iter()
        .filter_map(|name| name.strip_prefix('-'))
        .filter(|name| name.len() == 1)
        .filter_map(|name| name.chars().next())
        .collect::<BTreeSet<_>>();
    let mut index = 0;
    while index < args.len() {
        let Some(value) = args[index].to_str() else {
            index += 1;
            continue;
        };
        if value == "--" {
            break;
        }
        if value.starts_with("--") {
            let option = value.split('=').next().unwrap_or(value);
            if names
                .iter()
                .any(|name| name.starts_with("--") && option == *name)
            {
                return true;
            }
            if backend == GatewayBackend::Fd && matches!(option, "--exec" | "--exec-batch") {
                return false;
            }
            index += if !value.contains('=') && long_values.contains(&option) {
                2
            } else {
                1
            };
            continue;
        }
        if value.starts_with('-') && value != "-" {
            let body = &value[1..];
            for (offset, flag) in body.char_indices() {
                if short_targets.contains(&flag) {
                    return true;
                }
                if backend == GatewayBackend::Fd && matches!(flag, 'x' | 'X') {
                    return false;
                }
                if short_values.contains(&flag) {
                    if body[offset + flag.len_utf8()..].is_empty() {
                        index += 1;
                    }
                    break;
                }
            }
        }
        index += 1;
    }
    false
}

fn scc_format(args: &[OsString]) -> Option<&str> {
    let mut index = 0;
    while index < args.len() {
        let Some(value) = args[index].to_str() else {
            index += 1;
            continue;
        };
        if value == "--" {
            return None;
        }
        if let Some(format) = value.strip_prefix("--format=") {
            return Some(format);
        }
        if value == "--format" || value == "-f" {
            return args.get(index + 1)?.to_str();
        }
        if value.starts_with("--") {
            let option = value.split('=').next().unwrap_or(value);
            index += if !value.contains('=') && SCC_LONG_VALUE_OPTIONS.contains(&option) {
                2
            } else {
                1
            };
            continue;
        }
        if let Some(format) = value.strip_prefix("-f=") {
            return Some(format);
        }
        if value.starts_with('-') && value != "-" {
            let body = &value[1..];
            for (offset, flag) in body.char_indices() {
                let remainder = &body[offset + flag.len_utf8()..];
                if flag == 'f' {
                    return if remainder.is_empty() {
                        args.get(index + 1)?.to_str()
                    } else {
                        Some(remainder.trim_start_matches('='))
                    };
                }
                if SCC_SHORT_VALUE_OPTIONS.contains(&flag) {
                    if remainder.is_empty() {
                        index += 1;
                    }
                    break;
                }
            }
        }
        index += 1;
    }
    None
}

fn classify(backend: GatewayBackend, args: &[OsString]) -> Mode {
    match backend {
        GatewayBackend::Fd => {
            if has(backend, args, &["-x", "--exec"]) {
                Mode {
                    id: "FD-EXEC",
                    handling: Handling::Passthrough,
                }
            } else if has(backend, args, &["-X", "--exec-batch"]) {
                Mode {
                    id: "FD-EXEC-BATCH",
                    handling: Handling::Passthrough,
                }
            } else if has(backend, args, &["-0", "--print0"]) {
                Mode {
                    id: "FD-PRINT0",
                    handling: Handling::Artifact,
                }
            } else if has(backend, args, &["-l", "--list-details"]) {
                Mode {
                    id: "FD-LIST-DETAILS",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--format"]) {
                Mode {
                    id: "FD-FORMAT",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--hyperlink"]) {
                Mode {
                    id: "FD-HYPERLINK",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-q", "--quiet", "--has-results"]) {
                Mode {
                    id: "FD-QUIET",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-h", "--help"]) {
                Mode {
                    id: "FD-HELP",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-V", "--version"]) {
                Mode {
                    id: "FD-VERSION",
                    handling: Handling::BoundedText,
                }
            } else {
                Mode {
                    id: "FD-PATHS",
                    handling: Handling::Adaptive,
                }
            }
        }
        GatewayBackend::Rg => {
            if has(backend, args, &["-0", "--null"]) {
                Mode {
                    id: "RG-NUL-PATHS",
                    handling: Handling::Artifact,
                }
            } else if has(backend, args, &["--null-data"]) {
                Mode {
                    id: "RG-NULL-DATA",
                    handling: Handling::Artifact,
                }
            } else if has(backend, args, &["--generate"]) {
                Mode {
                    id: "RG-GENERATE",
                    handling: Handling::Artifact,
                }
            } else if has(backend, args, &["--pre"]) {
                Mode {
                    id: "RG-PREPROCESSOR",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--passthru"]) {
                Mode {
                    id: "RG-PASSTHRU",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-q", "--quiet"]) {
                Mode {
                    id: "RG-QUIET",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--stats"]) {
                Mode {
                    id: "RG-STATS",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-r", "--replace"]) {
                Mode {
                    id: "RG-REPLACE-DISPLAY",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--type-list"]) {
                Mode {
                    id: "RG-TYPE-LIST",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-h", "--help"]) {
                Mode {
                    id: "RG-HELP",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-V", "--version"]) {
                Mode {
                    id: "RG-VERSION",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--files"]) {
                Mode {
                    id: "RG-FILES",
                    handling: Handling::Adaptive,
                }
            } else if has(backend, args, &["-l", "--files-with-matches"]) {
                Mode {
                    id: "RG-FILES-WITH-MATCHES",
                    handling: Handling::Adaptive,
                }
            } else if has(backend, args, &["--files-without-match"]) {
                Mode {
                    id: "RG-FILES-WITHOUT-MATCH",
                    handling: Handling::Adaptive,
                }
            } else if has(backend, args, &["--count-matches"]) {
                Mode {
                    id: "RG-COUNT-MATCHES",
                    handling: Handling::Structured,
                }
            } else if has(backend, args, &["-c", "--count"]) {
                Mode {
                    id: "RG-COUNT",
                    handling: Handling::Structured,
                }
            } else if has(backend, args, &["--vimgrep"]) {
                Mode {
                    id: "RG-VIMGREP",
                    handling: Handling::Structured,
                }
            } else if has(backend, args, &["--json"]) {
                Mode {
                    id: "RG-SEARCH-JSON",
                    handling: Handling::Structured,
                }
            } else if has(backend, args, &["-o", "--only-matching"]) {
                Mode {
                    id: "RG-ONLY-MATCHING",
                    handling: Handling::Adaptive,
                }
            } else if has(backend, args, &["-z", "--search-zip"]) {
                Mode {
                    id: "RG-SEARCH-ZIP",
                    handling: Handling::Adaptive,
                }
            } else {
                Mode {
                    id: "RG-SEARCH-TEXT",
                    handling: Handling::Adaptive,
                }
            }
        }
        GatewayBackend::Scc => {
            if has(backend, args, &["-o", "--output", "--format-multi"]) {
                Mode {
                    id: "SCC-OUTPUT",
                    handling: Handling::Passthrough,
                }
            } else if has(backend, args, &["-h", "--help"]) {
                Mode {
                    id: "SCC-HELP",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--version"]) {
                Mode {
                    id: "SCC-VERSION",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["-l", "--languages"]) {
                Mode {
                    id: "SCC-LANGUAGE-LIST",
                    handling: Handling::BoundedText,
                }
            } else if scc_format(args).is_some_and(|format| {
                !format.eq_ignore_ascii_case("json") && !format.eq_ignore_ascii_case("json2")
            }) {
                Mode {
                    id: "SCC-FORMAT",
                    handling: Handling::BoundedText,
                }
            } else if has(backend, args, &["--by-file"]) {
                Mode {
                    id: "SCC-FILES",
                    handling: Handling::Structured,
                }
            } else {
                Mode {
                    id: "SCC-LANGUAGES",
                    handling: Handling::Structured,
                }
            }
        }
    }
}

fn injected_argv(backend: GatewayBackend, mode: Mode, args: &[OsString]) -> Vec<OsString> {
    match backend {
        GatewayBackend::Fd if mode.id == "FD-PATHS" => vec![
            OsString::from("--print0"),
            OsString::from("--color=never"),
            OsString::from("--path-separator=/"),
        ],
        GatewayBackend::Rg
            if matches!(
                mode.id,
                "RG-SEARCH-TEXT" | "RG-SEARCH-JSON" | "RG-ONLY-MATCHING" | "RG-SEARCH-ZIP"
            ) =>
        {
            let mut injected = Vec::new();
            if !has(backend, args, &["--json"]) {
                injected.push(OsString::from("--json"));
            }
            injected.extend([
                OsString::from("--color=never"),
                OsString::from("--path-separator=/"),
            ]);
            injected
        }
        GatewayBackend::Rg
            if mode.id == "RG-FILES"
                || mode.id == "RG-FILES-WITH-MATCHES"
                || mode.id == "RG-FILES-WITHOUT-MATCH" =>
        {
            if has(backend, args, &["-0", "--null"]) {
                Vec::new()
            } else {
                vec![
                    OsString::from("--null"),
                    OsString::from("--color=never"),
                    OsString::from("--path-separator=/"),
                ]
            }
        }
        GatewayBackend::Rg if matches!(mode.id, "RG-COUNT" | "RG-COUNT-MATCHES" | "RG-VIMGREP") => {
            vec![
                OsString::from("--color=never"),
                OsString::from("--path-separator=/"),
            ]
        }
        GatewayBackend::Scc if matches!(mode.id, "SCC-LANGUAGES" | "SCC-FILES") => {
            if has(backend, args, &["-f", "--format"]) {
                Vec::new()
            } else {
                vec![OsString::from("--format=json")]
            }
        }
        _ => Vec::new(),
    }
}

fn effective_argv(user: &[OsString], injected: &[OsString]) -> Vec<OsString> {
    let insertion = user
        .iter()
        .position(|arg| arg == "--")
        .unwrap_or(user.len());
    let mut effective = Vec::with_capacity(user.len() + injected.len());
    effective.extend_from_slice(&user[..insertion]);
    effective.extend_from_slice(injected);
    effective.extend_from_slice(&user[insertion..]);
    effective
}

fn run_native(engine: &Path, cwd: &Path, args: Vec<OsString>) -> Result<Captured, GatewayError> {
    let mut request = ProcessRequest::new(engine, cwd);
    request.args = args;
    request.stdin = StdinMode::Inherit;
    request.forward_stderr = false;
    request.cancellation = CancellationToken::new();
    request.max_stdout_bytes = Some(MAX_STDOUT_BYTES);
    request.max_stderr_bytes = Some(MAX_STDERR_BYTES);
    let outcome = run(request).map_err(|error| GatewayError::io("native process failed", error))?;
    Ok(Captured {
        stdout: outcome
            .output
            .read_stdout()
            .map_err(|error| GatewayError::io("cannot read staged stdout", error))?,
        stderr: outcome
            .output
            .read_stderr()
            .map_err(|error| GatewayError::io("cannot read staged stderr", error))?,
        native_exit: outcome.exit_code(),
    })
}

fn execute_passthrough(engine: &Path, cwd: &Path, args: &[OsString]) -> Result<i32, GatewayError> {
    let status = Command::new(engine)
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()
        .map_err(|error| GatewayError::io("cannot start passthrough engine", error))?;
    Ok(status.code().unwrap_or(126))
}

fn write_native_stderr(bytes: &[u8], exact: bool, max_chars: usize) -> Result<(), GatewayError> {
    if bytes.is_empty() {
        return Ok(());
    }
    let mut stderr = io::stderr().lock();
    if exact {
        stderr
            .write_all(bytes)
            .map_err(|error| GatewayError::io("cannot write native stderr", error))?;
        return stderr
            .flush()
            .map_err(|error| GatewayError::io("cannot flush native stderr", error));
    }
    let Ok(text) = std::str::from_utf8(bytes) else {
        writeln!(
            stderr,
            "srcq: native stderr is non-UTF-8 ({} bytes); use raw or artifact mode for exact bytes",
            bytes.len()
        )
        .map_err(|error| GatewayError::io("cannot write bounded native stderr", error))?;
        return Ok(());
    };
    let lines = text.lines().collect::<Vec<_>>();
    for line in lines.iter().take(8) {
        writeln!(stderr, "native: {}", truncate_chars(line, max_chars))
            .map_err(|error| GatewayError::io("cannot write bounded native stderr", error))?;
    }
    if lines.len() > 8 {
        writeln!(stderr, "native: … {} more stderr lines", lines.len() - 8)
            .map_err(|error| GatewayError::io("cannot write bounded native stderr", error))?;
    }
    stderr
        .flush()
        .map_err(|error| GatewayError::io("cannot flush bounded native stderr", error))
}

fn native_version(engine: &Path, cwd: &Path) -> Result<String, GatewayError> {
    let captured = run_native(engine, cwd, vec![OsString::from("--version")])?;
    String::from_utf8(captured.stdout)
        .map_err(|_| GatewayError::input("native --version was not UTF-8"))
}

fn replay_safe_after_projection_failure(mode: Mode) -> bool {
    matches!(
        mode.id,
        "FD-PATHS"
            | "RG-SEARCH-TEXT"
            | "RG-SEARCH-JSON"
            | "RG-ONLY-MATCHING"
            | "RG-SEARCH-ZIP"
            | "RG-FILES"
            | "RG-FILES-WITH-MATCHES"
            | "RG-FILES-WITHOUT-MATCH"
            | "RG-COUNT"
            | "RG-COUNT-MATCHES"
            | "RG-VIMGREP"
    )
}

fn try_model_native_fallback(
    command: &GatewayCommand,
    mode: Mode,
    engine: &Path,
    cwd: &Path,
    snapshot: &Snapshot,
    fresh_snapshot: bool,
) -> Result<Option<i32>, GatewayError> {
    if command.output != OutputFormat::Model
        || command.receipt == "full"
        || !fresh_snapshot
        || snapshot.stdout.is_empty()
    {
        return Ok(None);
    }

    if std::str::from_utf8(&snapshot.stdout).is_ok() && !snapshot.stdout.contains(&0) {
        eprintln!("srcq: structured projection unavailable; returned bounded native output");
        emit_bounded_text(command, mode, &snapshot.stdout, snapshot.native_exit)?;
        return Ok(Some(snapshot.native_exit));
    }

    if !replay_safe_after_projection_failure(mode) {
        return Ok(None);
    }
    let captured = run_native(engine, cwd, command.native_argv.clone())?;
    if std::str::from_utf8(&captured.stdout).is_err() || captured.stdout.contains(&0) {
        return Ok(None);
    }
    write_native_stderr(&captured.stderr, false, command.max_text_chars)?;
    eprintln!("srcq: structured projection unavailable; returned bounded native output");
    emit_bounded_text(command, mode, &captured.stdout, captured.native_exit)?;
    Ok(Some(captured.native_exit))
}

fn query_fingerprint(
    backend: GatewayBackend,
    engine: &Path,
    cwd: &Path,
    args: &[OsString],
    version: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(backend_name(backend).as_bytes());
    hasher.update(engine.as_os_str().as_encoded_bytes());
    hasher.update(cwd.as_os_str().as_encoded_bytes());
    hasher.update(version.as_bytes());
    for arg in args {
        hasher.update([0]);
        hasher.update(arg.as_encoded_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn spool_root() -> Result<PathBuf, GatewayError> {
    let root = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| GatewayError::input("LOCALAPPDATA is required for bounded query snapshots"))?
        .join("srcq")
        .join("query-spool-v1");
    fs::create_dir_all(&root)
        .map_err(|error| GatewayError::io("cannot create query spool", error))?;
    ensure_safe_directory(&root)?;
    Ok(root)
}

fn open_spool_lock(root: &Path) -> Result<fs::File, GatewayError> {
    let path = root.join(".spool.lock");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&path)
        .map_err(|error| GatewayError::io("cannot open query spool lock", error))?;
    let metadata = fs::symlink_metadata(&path)
        .map_err(|error| GatewayError::io("cannot inspect query spool lock", error))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(GatewayError::input("query spool lock is not a safe file"));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(GatewayError::input("query spool lock is a reparse point"));
        }
    }
    Ok(file)
}

fn continuation_root(root: &Path) -> Result<PathBuf, GatewayError> {
    let directory = root.join("continuations");
    fs::create_dir_all(&directory)
        .map_err(|error| GatewayError::io("cannot create continuation spool", error))?;
    ensure_safe_directory(&directory)?;
    Ok(directory)
}

fn snapshot_id(
    query_fingerprint: &str,
    engine_version: &str,
    native_exit: i32,
    stdout: &[u8],
    stderr: &[u8],
    fd_types: &BTreeMap<String, String>,
) -> Result<String, GatewayError> {
    let mut hasher = Sha256::new();
    hasher.update(query_fingerprint.as_bytes());
    hasher.update(engine_version.as_bytes());
    hasher.update(native_exit.to_le_bytes());
    hasher.update(stdout);
    hasher.update(stderr);
    hasher.update(serde_json::to_vec(fd_types).map_err(|error| {
        GatewayError::input(format!("cannot serialize fd snapshot types: {error}"))
    })?);
    Ok(format!("{:x}", hasher.finalize())[..32].to_owned())
}

fn create_snapshot(
    backend: GatewayBackend,
    cwd: &Path,
    native_argv: &[OsString],
    query_fingerprint: String,
    engine_version: String,
    captured: Captured,
) -> Result<Snapshot, GatewayError> {
    let fd_cwd = fd_effective_cwd(native_argv, cwd);
    let fd_types = if backend == GatewayBackend::Fd {
        parse_nul_paths(&captured.stdout)?
            .into_iter()
            .map(|path| {
                let kind = path_type(&fd_cwd, &path).to_owned();
                (path, kind)
            })
            .collect()
    } else {
        BTreeMap::new()
    };
    Ok(Snapshot {
        id: String::new(),
        query_fingerprint,
        engine_version,
        native_exit: captured.native_exit,
        stdout: captured.stdout,
        stderr: captured.stderr,
        fd_types,
    })
}

fn ensure_snapshot_id(snapshot: &mut Snapshot) -> Result<(), GatewayError> {
    if snapshot.id.is_empty() {
        snapshot.id = snapshot_id(
            &snapshot.query_fingerprint,
            &snapshot.engine_version,
            snapshot.native_exit,
            &snapshot.stdout,
            &snapshot.stderr,
            &snapshot.fd_types,
        )?;
    }
    Ok(())
}

fn persist_snapshot(snapshot: &Snapshot) -> Result<(), GatewayError> {
    if snapshot.id.is_empty() {
        return Err(GatewayError::input(
            "query snapshot identity was not finalized before persistence",
        ));
    }
    let root = spool_root()?;
    let lock = open_spool_lock(&root)?;
    FileExt::lock_exclusive(&lock)
        .map_err(|error| GatewayError::io("cannot lock query spool", error))?;
    let id = &snapshot.id;
    let directory = root.join(id);
    if !directory.exists() {
        let nonce = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let staging = root.join(format!(".{id}.{}.{nonce}", std::process::id()));
        fs::create_dir(&staging)
            .map_err(|error| GatewayError::io("cannot stage query snapshot", error))?;
        let metadata = json!({"schema":"sgy.query.snapshot/v1","id":id,"query_fingerprint":snapshot.query_fingerprint,"engine_version":snapshot.engine_version,"native_exit":snapshot.native_exit,"stdout_sha256":sha256_hex(&snapshot.stdout),"stderr_sha256":sha256_hex(&snapshot.stderr),"fd_types":&snapshot.fd_types});
        let metadata_bytes = serde_json::to_vec(&metadata).map_err(|error| {
            GatewayError::input(format!("cannot serialize query snapshot metadata: {error}"))
        })?;
        fs::write(staging.join("stdout.bin"), &snapshot.stdout)
            .and_then(|()| fs::write(staging.join("stderr.bin"), &snapshot.stderr))
            .and_then(|()| fs::write(staging.join("meta.json"), metadata_bytes))
            .map_err(|error| GatewayError::io("cannot write query snapshot", error))?;
        match fs::rename(&staging, &directory) {
            Ok(()) => {}
            Err(_error) if directory.exists() => {
                ensure_safe_directory(&staging)?;
                fs::remove_dir_all(&staging).map_err(|error| {
                    GatewayError::io("cannot discard duplicate query snapshot staging", error)
                })?;
            }
            Err(error) => return Err(GatewayError::io("cannot commit query snapshot", error)),
        }
        prune_spool(&root)?;
    }
    Ok(())
}

fn prune_spool(root: &Path) -> Result<(), GatewayError> {
    let mut entries = fs::read_dir(root)
        .map_err(|error| GatewayError::io("cannot enumerate query spool", error))?
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_ok_and(|kind| kind.is_dir())
                && valid_snapshot_id(&entry.file_name().to_string_lossy())
        })
        .collect::<Vec<_>>();
    entries.sort_by_key(|entry| {
        entry
            .metadata()
            .and_then(|meta| meta.modified())
            .unwrap_or(SystemTime::UNIX_EPOCH)
    });
    let remove_count = entries.len().saturating_sub(MAX_SPOOL_ENTRIES);
    for entry in entries.into_iter().take(remove_count) {
        ensure_safe_directory(&entry.path())?;
        fs::remove_dir_all(entry.path())
            .map_err(|error| GatewayError::io("cannot prune query spool", error))?;
    }
    Ok(())
}

fn load_snapshot(id: &str) -> Result<Snapshot, GatewayError> {
    if !valid_snapshot_id(id) {
        return Err(GatewayError::input(
            "snapshot id must be 32 hexadecimal characters",
        ));
    }
    let root = spool_root()?;
    let lock = open_spool_lock(&root)?;
    FileExt::lock_shared(&lock)
        .map_err(|error| GatewayError::io("cannot lock query spool", error))?;
    let directory = root.join(id);
    ensure_safe_directory(&directory)?;
    let metadata: Value = serde_json::from_slice(&read_safe_snapshot_file(
        &directory,
        "meta.json",
        1024 * 1024,
    )?)
    .map_err(|error| GatewayError::input(format!("invalid query snapshot metadata: {error}")))?;
    let stdout = read_safe_snapshot_file(&directory, "stdout.bin", MAX_STDOUT_BYTES)?;
    let stderr = read_safe_snapshot_file(&directory, "stderr.bin", MAX_STDERR_BYTES)?;
    ensure_safe_directory(&directory)?;
    if metadata.get("schema").and_then(Value::as_str) != Some("sgy.query.snapshot/v1")
        || metadata.get("id").and_then(Value::as_str) != Some(id)
        || metadata.get("stdout_sha256").and_then(Value::as_str) != Some(&sha256_hex(&stdout))
        || metadata.get("stderr_sha256").and_then(Value::as_str) != Some(&sha256_hex(&stderr))
    {
        return Err(GatewayError::input("query snapshot fingerprint mismatch"));
    }
    let fd_types = metadata["fd_types"]
        .as_object()
        .map(|items| {
            items
                .iter()
                .filter_map(|(path, kind)| {
                    kind.as_str().map(|kind| (path.clone(), kind.to_owned()))
                })
                .collect()
        })
        .unwrap_or_default();
    let query_fingerprint = metadata["query_fingerprint"]
        .as_str()
        .ok_or_else(|| GatewayError::input("query snapshot is missing query_fingerprint"))?
        .to_owned();
    let engine_version = metadata["engine_version"]
        .as_str()
        .ok_or_else(|| GatewayError::input("query snapshot is missing engine_version"))?
        .to_owned();
    let native_exit = metadata["native_exit"]
        .as_i64()
        .and_then(|value| i32::try_from(value).ok())
        .ok_or_else(|| GatewayError::input("query snapshot has an invalid native_exit"))?;
    if snapshot_id(
        &query_fingerprint,
        &engine_version,
        native_exit,
        &stdout,
        &stderr,
        &fd_types,
    )? != id
    {
        return Err(GatewayError::input("query snapshot identity mismatch"));
    }
    Ok(Snapshot {
        id: id.to_owned(),
        query_fingerprint,
        engine_version,
        native_exit,
        stdout,
        stderr,
        fd_types,
    })
}

fn valid_snapshot_id(id: &str) -> bool {
    id.len() == 32 && id.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn persist_continuation(
    command: &GatewayCommand,
    cursor: &str,
    engine: &Path,
    cwd: &Path,
) -> Result<String, GatewayError> {
    let snapshot = cursor_snapshot(cursor)?;
    let root = spool_root()?;
    let lock = open_spool_lock(&root)?;
    FileExt::lock_exclusive(&lock)
        .map_err(|error| GatewayError::io("cannot lock query spool", error))?;
    let snapshot_directory = root.join(&snapshot);
    if !snapshot_directory.exists() {
        return Err(expired_continuation("new"));
    }
    ensure_safe_directory(&snapshot_directory)?;
    let continuations = continuation_root(&root)?;
    let next_number = next_continuation_number(&continuations)?;
    let handle = format!("q{next_number}");
    let payload = json!({
        "handle": handle,
        "cursor": cursor,
        "backend": backend_name(command.backend),
        "engine": model_path(engine, "engine")?,
        "cwd": model_path(cwd, "cwd")?,
        "view": command.view,
        "limit": command.limit,
        "max_text_chars": command.max_text_chars,
        "model_token_budget": command.model_token_budget,
        "native_argv": continuation_args_json(&command.native_argv)?,
    });
    let payload_bytes = serde_json::to_vec(&payload).map_err(|error| {
        GatewayError::input(format!("cannot serialize continuation payload: {error}"))
    })?;
    let record = json!({
        "schema": CONTINUATION_SCHEMA,
        "handle": handle,
        "payload_sha256": sha256_hex(&payload_bytes),
        "payload": payload,
    });
    let bytes = serde_json::to_vec(&record).map_err(|error| {
        GatewayError::input(format!("cannot serialize continuation record: {error}"))
    })?;
    let nonce = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let staging = continuations.join(format!(".{handle}.{}.{nonce}", std::process::id()));
    let mut staging_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&staging)
        .map_err(|error| GatewayError::io("cannot create continuation staging", error))?;
    staging_file
        .write_all(&bytes)
        .and_then(|()| staging_file.sync_all())
        .map_err(|error| GatewayError::io("cannot write continuation record", error))?;
    drop(staging_file);
    fs::rename(&staging, continuations.join(format!("{handle}.json")))
        .map_err(|error| GatewayError::io("cannot commit continuation record", error))?;
    prune_continuations(&continuations, next_number)?;
    Ok(handle)
}

fn next_continuation_number(root: &Path) -> Result<u64, GatewayError> {
    let used = fs::read_dir(root)
        .map_err(|error| GatewayError::io("cannot enumerate continuations", error))?
        .filter_map(Result::ok)
        .filter_map(|entry| {
            entry
                .file_name()
                .to_str()
                .and_then(|name| name.strip_suffix(".json"))
                .and_then(parse_continuation_number)
        })
        .filter(|number| *number <= MAX_CONTINUATION_NUMBER)
        .collect::<BTreeSet<_>>();
    let highest = used.iter().next_back().copied().unwrap_or(0);
    let first = if highest == MAX_CONTINUATION_NUMBER {
        1
    } else {
        highest + 1
    };
    (first..=MAX_CONTINUATION_NUMBER)
        .chain(1..first)
        .find(|number| !used.contains(number))
        .ok_or_else(|| GatewayError::input("continuation handle space is exhausted"))
}

fn load_continuation(handle: &str) -> Result<GatewayCommand, GatewayError> {
    parse_continuation_number(handle)
        .ok_or_else(|| GatewayError::input("continuation handle must use the form q<number>"))?;
    let root = spool_root()?;
    let continuations = continuation_root(&root)?;
    let lock = open_spool_lock(&root)?;
    FileExt::lock_shared(&lock)
        .map_err(|error| GatewayError::io("cannot lock query spool", error))?;
    let file_name = format!("{handle}.json");
    let path = continuations.join(&file_name);
    if !path.exists() {
        return Err(expired_continuation(handle));
    }
    let bytes = read_safe_snapshot_file(&continuations, &file_name, 1024 * 1024)?;
    let record: Value = serde_json::from_slice(&bytes).map_err(|_| expired_continuation(handle))?;
    if record.get("schema").and_then(Value::as_str) != Some(CONTINUATION_SCHEMA)
        || record.get("handle").and_then(Value::as_str) != Some(handle)
    {
        return Err(expired_continuation(handle));
    }
    let payload = record
        .get("payload")
        .ok_or_else(|| expired_continuation(handle))?;
    let payload_bytes = serde_json::to_vec(payload).map_err(|_| expired_continuation(handle))?;
    if record.get("payload_sha256").and_then(Value::as_str) != Some(&sha256_hex(&payload_bytes))
        || payload.get("handle").and_then(Value::as_str) != Some(handle)
    {
        return Err(expired_continuation(handle));
    }
    let string = |name: &str| {
        payload
            .get(name)
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .ok_or_else(|| expired_continuation(handle))
    };
    let number = |name: &str| {
        payload
            .get(name)
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| expired_continuation(handle))
    };
    let backend = match string("backend")?.as_str() {
        "rg" => GatewayBackend::Rg,
        "fd" => GatewayBackend::Fd,
        "scc" => GatewayBackend::Scc,
        _ => return Err(expired_continuation(handle)),
    };
    let cursor = string("cursor")?;
    let snapshot = cursor_snapshot(&cursor)?;
    let snapshot_directory = root.join(snapshot);
    if !snapshot_directory.exists() {
        return Err(expired_continuation(handle));
    }
    ensure_safe_directory(&snapshot_directory)?;
    let native_argv = payload
        .get("native_argv")
        .and_then(Value::as_array)
        .ok_or_else(|| expired_continuation(handle))?
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(OsString::from)
                .ok_or_else(|| expired_continuation(handle))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(GatewayCommand {
        backend,
        operation: GatewayOperation::Exec,
        engine: Some(PathBuf::from(string("engine")?)),
        cwd: Some(PathBuf::from(string("cwd")?)),
        view: string("view")?,
        limit: number("limit")?,
        max_text_chars: number("max_text_chars")?,
        model_token_budget: number("model_token_budget")?,
        auto_complete: false,
        output: OutputFormat::Model,
        receipt: "auto".to_owned(),
        artifact_out: None,
        snapshot: None,
        after: Some(cursor),
        native_argv,
    })
}

fn prune_continuations(root: &Path, newest: u64) -> Result<(), GatewayError> {
    let mut entries = fs::read_dir(root)
        .map_err(|error| GatewayError::io("cannot enumerate continuations", error))?
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let number = entry
                .file_name()
                .to_str()
                .and_then(|name| name.strip_suffix(".json"))
                .and_then(parse_continuation_number)?;
            entry
                .file_type()
                .ok()
                .is_some_and(|kind| kind.is_file())
                .then_some((number, entry))
        })
        .collect::<Vec<_>>();
    entries.sort_by_key(|(number, _)| {
        if *number > MAX_CONTINUATION_NUMBER {
            (0, *number)
        } else {
            let age = (newest + MAX_CONTINUATION_NUMBER - *number) % MAX_CONTINUATION_NUMBER;
            (1, MAX_CONTINUATION_NUMBER - age)
        }
    });
    let remove_count = entries.len().saturating_sub(MAX_CONTINUATION_ENTRIES);
    for (_, entry) in entries.into_iter().take(remove_count) {
        fs::remove_file(entry.path())
            .map_err(|error| GatewayError::io("cannot prune continuation", error))?;
    }
    Ok(())
}

fn parse_continuation_number(handle: &str) -> Option<u64> {
    let digits = handle.strip_prefix('q')?;
    if digits.is_empty()
        || digits.starts_with('0')
        || !digits.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    digits.parse().ok()
}

fn expired_continuation(handle: &str) -> GatewayError {
    GatewayError::input(format!(
        "continuation {handle} expired or is unavailable; rerun the original query"
    ))
}

fn continuation_args_json(args: &[OsString]) -> Result<Vec<String>, GatewayError> {
    args.iter()
        .map(|argument| {
            argument.to_str().map(ToOwned::to_owned).ok_or_else(|| {
                GatewayError::input(
                    "native argv cannot be represented losslessly in a model continuation",
                )
            })
        })
        .collect()
}

fn read_safe_snapshot_file(
    directory: &Path,
    name: &str,
    max_bytes: u64,
) -> Result<Vec<u8>, GatewayError> {
    let path = directory.join(name);
    let metadata = fs::symlink_metadata(&path)
        .map_err(|error| GatewayError::io("cannot inspect query snapshot file", error))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > max_bytes {
        return Err(GatewayError::input(
            "query snapshot contains an unsafe or oversized file",
        ));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(GatewayError::input(
                "query snapshot file is a reparse point",
            ));
        }
    }
    let bytes = fs::read(&path)
        .map_err(|error| GatewayError::io("cannot read query snapshot file", error))?;
    if bytes.len() as u64 > max_bytes {
        return Err(GatewayError::input(
            "query snapshot file exceeded its read bound",
        ));
    }
    Ok(bytes)
}

fn ensure_safe_directory(path: &Path) -> Result<(), GatewayError> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| GatewayError::io("cannot inspect query snapshot", error))?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(GatewayError::input(
            "query snapshot is not a safe directory",
        ));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(GatewayError::input(
                "query snapshot directory is a reparse point",
            ));
        }
    }
    Ok(())
}

fn make_cursor(snapshot: &str, view: &str, offset: usize) -> String {
    format!("q1.{snapshot}.{view}.{offset}")
}

fn cursor_snapshot(cursor: &str) -> Result<String, GatewayError> {
    let parts = cursor.split('.').collect::<Vec<_>>();
    if parts.len() != 4 || parts[0] != "q1" || parts[1].is_empty() {
        return Err(GatewayError::input("cursor identity is invalid"));
    }
    Ok(parts[1].to_owned())
}

fn parse_cursor(
    cursor: Option<&str>,
    snapshot: &str,
    requested_view: &str,
) -> Result<(usize, Option<String>), GatewayError> {
    let Some(cursor) = cursor else {
        return Ok((0, None));
    };
    let parts = cursor.split('.').collect::<Vec<_>>();
    if parts.len() != 4
        || parts[0] != "q1"
        || parts[1] != snapshot
        || (requested_view != "auto" && parts[2] != requested_view)
    {
        return Err(GatewayError::input(
            "cursor does not identify the requested snapshot and view",
        ));
    }
    let offset = parts[3]
        .parse::<usize>()
        .map_err(|_| GatewayError::input("cursor offset is invalid"))?;
    Ok((offset, Some(parts[2].to_owned())))
}

fn render_fd(
    command: &GatewayCommand,
    cwd: &Path,
    snapshot: &Snapshot,
    offset: usize,
) -> Result<Projection, GatewayError> {
    let paths = parse_nul_paths(&snapshot.stdout)?;
    if command.view == "summary" {
        if offset != 0 {
            return Err(GatewayError::input("summary view does not accept a cursor"));
        }
        return Ok(Projection {
            value: json!({"summary":{"paths":paths.len()}}),
            model: format!("paths {}", paths.len()),
            displayed: paths.len(),
            total: paths.len(),
            view: "summary".to_owned(),
            display_complete: true,
        });
    }
    if offset > paths.len() {
        return Err(GatewayError::input(
            "cursor offset exceeds the snapshot result set",
        ));
    }
    let roots = fd_roots(&command.native_argv, cwd);
    let effective_limit = direct_fd_complete_limit(command, &paths, &roots, &snapshot.fd_types)
        .unwrap_or(command.limit);
    let maximum_end = paths.len().min(offset.saturating_add(effective_limit));
    let end = if command.output == OutputFormat::Model && command.view != "lossless" {
        model_page_end(
            offset,
            maximum_end,
            command.model_token_budget,
            |candidate_end| {
                let (model, _) = render_fd_model(
                    command,
                    &paths[offset..candidate_end],
                    &roots,
                    &snapshot.fd_types,
                );
                model_text_cost(&model)
            },
        )
    } else {
        maximum_end
    };
    let page = &paths[offset..end];
    let flat = json!({"paths":page.iter().map(|path| json!({"path":path,"type":snapshot.fd_types.get(path).map(String::as_str).unwrap_or("unknown")})).collect::<Vec<_>>()});
    let tree = render_fd_tree(page, &snapshot.fd_types, &roots);
    let (model, model_view) = render_fd_model(command, page, &roots, &snapshot.fd_types);
    let chosen = match command.view.as_str() {
        "lossless" => "lossless",
        "auto" => model_view.as_str(),
        "flat" => "flat",
        "tree" => "tree",
        other => other,
    };
    let value = match chosen {
        "tree" => tree,
        _ => flat,
    };
    Ok(Projection {
        value,
        model,
        displayed: page.len(),
        total: paths.len(),
        view: chosen.to_owned(),
        display_complete: end >= paths.len(),
    })
}

fn direct_fd_complete_limit(
    command: &GatewayCommand,
    paths: &[String],
    roots: &[FdRoot],
    types: &BTreeMap<String, String>,
) -> Option<usize> {
    if !command.auto_complete
        || command.output != OutputFormat::Model
        || command.view != "auto"
        || paths.len() <= command.limit
        || paths.len() > DIRECT_COMPLETE_MAX_UNITS
    {
        return None;
    }
    let (model, _) = render_fd_model(command, paths, roots, types);
    (model_text_cost(&model) <= command.model_token_budget).then_some(paths.len())
}

fn render_fd_model(
    command: &GatewayCommand,
    page: &[String],
    roots: &[FdRoot],
    types: &BTreeMap<String, String>,
) -> (String, String) {
    let model_paths = fd_relative_model_paths(page, roots).unwrap_or_else(|| page.to_vec());
    let model_types = model_paths
        .iter()
        .zip(page)
        .map(|(model_path, source_path)| {
            (
                model_path.clone(),
                types
                    .get(source_path)
                    .cloned()
                    .unwrap_or_else(|| "unknown".to_owned()),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let flat_model = render_fd_flat_model(&model_paths, &model_types);
    let tree_model = fd_model_types_are_uniform(&model_paths, &model_types)
        .then(|| render_path_tree_model(&model_paths))
        .flatten();
    let chosen = match command.view.as_str() {
        "auto" => {
            if tree_model.as_ref().is_some_and(|candidate| {
                model_representation_key(candidate) < model_representation_key(&flat_model)
            }) {
                "tree"
            } else {
                "flat"
            }
        }
        "lossless" => "lossless",
        "flat" => "flat",
        "tree" => "tree",
        other => other,
    };
    let model = match chosen {
        "tree" => tree_model.unwrap_or(flat_model),
        _ => flat_model,
    };
    (model, chosen.to_owned())
}

fn parse_nul_paths(bytes: &[u8]) -> Result<Vec<String>, GatewayError> {
    let mut paths = Vec::new();
    for raw in bytes
        .split(|byte| *byte == 0)
        .filter(|value| !value.is_empty())
    {
        let normalized = std::str::from_utf8(raw).map_err(|_| GatewayError::input("native engine returned a non-UTF-8 path; rerun with --artifact-out and an explicit native byte mode"))?.replace('\\', "/");
        paths.push(
            normalized
                .strip_prefix("./")
                .unwrap_or(&normalized)
                .trim_end_matches('/')
                .to_owned(),
        );
    }
    Ok(paths)
}

fn path_type(cwd: &Path, path: &str) -> &'static str {
    let native = Path::new(path);
    let candidate = if native.is_absolute() {
        native.to_path_buf()
    } else {
        cwd.join(native)
    };
    match fs::symlink_metadata(candidate) {
        Ok(meta) if meta.file_type().is_symlink() => "link",
        Ok(meta) if meta.is_dir() => "dir",
        Ok(meta) if meta.is_file() => "file",
        Ok(_) => "other",
        Err(_) => "unknown",
    }
}

#[derive(Default)]
struct Trie {
    count: usize,
    kind: Option<&'static str>,
    children: BTreeMap<String, Trie>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct FdRoot {
    alias: String,
    rendered: String,
}

fn fd_effective_cwd(args: &[OsString], cwd: &Path) -> PathBuf {
    let mut index = 0;
    while index < args.len() {
        let value = args[index].to_string_lossy();
        if value == "--" {
            break;
        }
        if let Some(attached) = value.strip_prefix("--base-directory=") {
            return cwd.join(attached);
        }
        if value == "--base-directory" {
            return args
                .get(index + 1)
                .map(|next| cwd.join(Path::new(next)))
                .unwrap_or_else(|| cwd.to_path_buf());
        }
        if value.starts_with('-') && !value.starts_with("--") {
            let body = &value[1..];
            for (offset, flag) in body.char_indices() {
                if flag == 'C' {
                    let attached = &body[offset + 1..];
                    return if attached.is_empty() {
                        args.get(index + 1)
                            .map(|next| cwd.join(Path::new(next)))
                            .unwrap_or_else(|| cwd.to_path_buf())
                    } else {
                        cwd.join(attached)
                    };
                }
                if ['d', 'E', 't', 'e', 'S', 'c', 'j', 'x', 'X'].contains(&flag) {
                    break;
                }
            }
        }
        index += 1;
    }
    cwd.to_path_buf()
}

fn fd_roots(args: &[OsString], cwd: &Path) -> Vec<FdRoot> {
    const LONG_VALUES: &[&str] = &[
        "--and",
        "--max-depth",
        "--min-depth",
        "--exact-depth",
        "--exclude",
        "--type",
        "--extension",
        "--size",
        "--changed-within",
        "--changed-before",
        "--format",
        "--batch-size",
        "--ignore-file",
        "--color",
        "--ignore-contain",
        "--threads",
        "--max-results",
        "--base-directory",
        "--path-separator",
    ];
    const SHORT_VALUES: &[char] = &['d', 'E', 't', 'e', 'S', 'c', 'j', 'C'];
    let mut positionals = Vec::new();
    let mut search_paths = Vec::new();
    let mut base_directory: Option<String> = None;
    let mut absolute = false;
    let mut options = true;
    let mut index = 0;
    while index < args.len() {
        let value = args[index].to_string_lossy();
        if options && value == "--" {
            options = false;
            index += 1;
            continue;
        }
        if options && value == "--absolute-path" {
            absolute = true;
            index += 1;
            continue;
        }
        if options && (value == "--search-path" || value.starts_with("--search-path=")) {
            if let Some(attached) = value.strip_prefix("--search-path=") {
                search_paths.push(attached.to_owned());
            } else if let Some(next) = args.get(index + 1) {
                search_paths.push(next.to_string_lossy().into_owned());
                index += 1;
            }
            index += 1;
            continue;
        }
        if options && (value == "--base-directory" || value.starts_with("--base-directory=")) {
            if let Some(attached) = value.strip_prefix("--base-directory=") {
                base_directory = Some(attached.to_owned());
            } else if let Some(next) = args.get(index + 1) {
                base_directory = Some(next.to_string_lossy().into_owned());
                index += 1;
            }
            index += 1;
            continue;
        }
        if options && value.starts_with("--") {
            let name = value.split('=').next().unwrap_or(&value);
            if !value.contains('=') && LONG_VALUES.contains(&name) {
                index += 1;
            }
            index += 1;
            continue;
        }
        if options && value.starts_with('-') && value != "-" {
            let body = &value[1..];
            if body.chars().any(|flag| flag == 'a') {
                absolute = true;
            }
            if let Some((flag_offset, flag)) = body
                .char_indices()
                .find(|(_, flag)| SHORT_VALUES.contains(flag))
            {
                let attached = &body[flag_offset + flag.len_utf8()..];
                if flag == 'C' {
                    if attached.is_empty() {
                        if let Some(next) = args.get(index + 1) {
                            base_directory = Some(next.to_string_lossy().into_owned());
                        }
                    } else {
                        base_directory = Some(attached.to_owned());
                    }
                }
                if attached.is_empty() {
                    index += 1;
                }
            }
            index += 1;
            continue;
        }
        positionals.push(value.into_owned());
        index += 1;
    }
    let mut declared = search_paths;
    if positionals.len() > 1 {
        declared.extend(positionals.into_iter().skip(1));
    }
    if declared.is_empty() {
        declared.push(".".to_owned());
    }
    let effective_cwd = base_directory
        .as_deref()
        .map(|base| cwd.join(base))
        .unwrap_or_else(|| cwd.to_path_buf());
    let mut roots = Vec::new();
    for root in declared {
        let raw = Path::new(&root);
        let rendered = if absolute {
            let absolute_root = if raw == Path::new(".") {
                effective_cwd.clone()
            } else if raw.is_absolute() {
                raw.to_path_buf()
            } else {
                effective_cwd.join(raw)
            };
            absolute_root
                .to_string_lossy()
                .replace('\\', "/")
                .trim_end_matches('/')
                .to_owned()
        } else {
            let normalized = root.replace('\\', "/");
            normalized
                .strip_prefix("./")
                .unwrap_or(&normalized)
                .trim_end_matches('/')
                .to_owned()
        };
        let rendered = if rendered.is_empty() {
            ".".to_owned()
        } else {
            rendered
        };
        if !roots
            .iter()
            .any(|existing: &FdRoot| existing.rendered.eq_ignore_ascii_case(&rendered))
        {
            roots.push(FdRoot {
                alias: format!("R{}", roots.len()),
                rendered,
            });
        }
    }
    roots
}

fn relative_to_root<'a>(path: &'a str, root: &str) -> Option<&'a str> {
    if root == "." && !Path::new(path).is_absolute() {
        return Some(path);
    }
    if path.eq_ignore_ascii_case(root) {
        return Some("");
    }
    let prefix = format!("{root}/");
    path.get(..prefix.len())
        .filter(|candidate| candidate.eq_ignore_ascii_case(&prefix))
        .map(|_| &path[prefix.len()..])
}

fn fd_relative_model_paths(paths: &[String], roots: &[FdRoot]) -> Option<Vec<String>> {
    let [root] = roots else {
        return None;
    };
    paths
        .iter()
        .map(|path| {
            relative_to_root(path, &root.rendered)
                .filter(|relative| !relative.is_empty())
                .map(str::to_owned)
        })
        .collect()
}

fn insert_trie(root: &mut Trie, path: &str, kind: &str) {
    if path.is_empty() || path == "." {
        root.count += 1;
        root.kind = Some(match kind {
            "dir" => "dir",
            "file" => "file",
            "link" => "link",
            "other" => "other",
            _ => "unknown",
        });
        return;
    }
    let mut node = root;
    for segment in path.split('/').filter(|segment| !segment.is_empty()) {
        node = node.children.entry(segment.to_owned()).or_default();
    }
    node.count += 1;
    node.kind = Some(match kind {
        "dir" => "dir",
        "file" => "file",
        "link" => "link",
        "other" => "other",
        _ => "unknown",
    });
}

fn trie_lines(root: &Trie) -> Vec<String> {
    fn lines(node: &Trie, depth: usize, output: &mut Vec<String>) {
        for (name, child) in &node.children {
            let count = if child.count > 1 {
                format!("*{}", child.count)
            } else {
                String::new()
            };
            let suffix = if child.children.is_empty() {
                format!("|{}{}", child.kind.unwrap_or("unknown"), count)
            } else if child.count > 0 {
                format!("/|{}{}", child.kind.unwrap_or("unknown"), count)
            } else {
                "/".to_owned()
            };
            output.push(format!(
                "{}{}{}",
                "  ".repeat(depth),
                escape_segment(name),
                suffix
            ));
            lines(child, depth + 1, output);
        }
    }
    let mut output = Vec::new();
    if root.count > 0 {
        output.push(format!(
            "$|{}{}",
            root.kind.unwrap_or("unknown"),
            if root.count > 1 {
                format!("*{}", root.count)
            } else {
                String::new()
            }
        ));
    }
    lines(root, 0, &mut output);
    output
}

fn render_fd_flat_model(paths: &[String], types: &BTreeMap<String, String>) -> String {
    let kinds = paths
        .iter()
        .map(|path| types.get(path).map(String::as_str).unwrap_or("unknown"))
        .collect::<BTreeSet<_>>();
    let include_kind = kinds.len() > 1;
    paths
        .iter()
        .map(|path| {
            if include_kind {
                match types.get(path).map(String::as_str).unwrap_or("unknown") {
                    "file" => path.clone(),
                    "dir" => format!("{path}/"),
                    kind => format!("{path}|{kind}"),
                }
            } else {
                path.clone()
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn fd_model_types_are_uniform(paths: &[String], types: &BTreeMap<String, String>) -> bool {
    paths
        .iter()
        .map(|path| types.get(path).map(String::as_str).unwrap_or("unknown"))
        .collect::<BTreeSet<_>>()
        .len()
        <= 1
}

#[derive(Default)]
struct OrderedPathNode {
    terminal: bool,
    annotations: Vec<String>,
    children: Vec<(String, OrderedPathNode)>,
}

fn path_segments(path: &str) -> Vec<String> {
    path.split('/')
        .filter(|segment| !segment.is_empty())
        .map(str::to_owned)
        .collect()
}

fn insert_ordered_path(root: &mut OrderedPathNode, path: &str, annotations: &[String]) -> bool {
    let segments = path_segments(path);
    if segments.is_empty() || segments.join("/") != path {
        return false;
    }
    let mut node = root;
    for segment in segments {
        let index = node
            .children
            .iter()
            .position(|(name, _)| name == &segment)
            .unwrap_or_else(|| {
                node.children
                    .push((segment.clone(), OrderedPathNode::default()));
                node.children.len() - 1
            });
        node = &mut node.children[index].1;
    }
    if node.terminal {
        return false;
    }
    node.terminal = true;
    node.annotations.extend_from_slice(annotations);
    true
}

#[derive(Clone, Copy)]
enum PathAnnotationLayout {
    SeparateLines,
    InlineSingle,
}

fn render_ordered_path_annotations_with_layout(
    entries: &[(String, Vec<String>)],
    layout: PathAnnotationLayout,
) -> Option<String> {
    if entries.is_empty() {
        return None;
    }
    let mut root = OrderedPathNode::default();
    for (path, annotations) in entries {
        if !insert_ordered_path(&mut root, path, annotations) {
            return None;
        }
    }
    fn valid(node: &OrderedPathNode, layout: PathAnnotationLayout) -> bool {
        (!node.terminal || node.children.is_empty())
            && (!node.terminal
                || !matches!(layout, PathAnnotationLayout::InlineSingle)
                || (node.annotations.len() == 1
                    && !node.annotations[0].contains('\r')
                    && !node.annotations[0].contains('\n')))
            && node.children.iter().all(|(_, child)| valid(child, layout))
    }
    if !valid(&root, layout) {
        return None;
    }
    fn leaf_paths(node: &OrderedPathNode, prefix: &mut Vec<String>, output: &mut Vec<Vec<String>>) {
        if node.terminal {
            output.push(prefix.clone());
        }
        for (name, child) in &node.children {
            prefix.push(name.clone());
            leaf_paths(child, prefix, output);
            prefix.pop();
        }
    }
    let mut rendered_order = Vec::new();
    leaf_paths(&root, &mut Vec::new(), &mut rendered_order);
    let source_order = entries
        .iter()
        .map(|(path, _)| path_segments(path))
        .collect::<Vec<_>>();
    if rendered_order != source_order {
        return None;
    }
    fn lines(
        node: &OrderedPathNode,
        depth: usize,
        layout: PathAnnotationLayout,
        output: &mut Vec<String>,
    ) {
        for (name, child) in &node.children {
            let mut chain = escape_segment(name);
            let mut tail = child;
            while !tail.terminal && tail.children.len() == 1 {
                let (next_name, next) = &tail.children[0];
                chain.push('/');
                chain.push_str(&escape_segment(next_name));
                tail = next;
            }
            let directory = !tail.children.is_empty();
            let mut line = format!(
                "{}{}{}",
                "  ".repeat(depth),
                chain,
                if directory { "/" } else { "" }
            );
            if !directory && matches!(layout, PathAnnotationLayout::InlineSingle) {
                line.push('\t');
                line.push_str(&tail.annotations[0]);
            }
            output.push(line);
            if matches!(layout, PathAnnotationLayout::SeparateLines) {
                for annotation in &tail.annotations {
                    output.push(format!("{}{}", "  ".repeat(depth + 1), annotation));
                }
            }
            lines(tail, depth + 1, layout, output);
        }
    }
    let mut output = Vec::new();
    lines(&root, 0, layout, &mut output);
    Some(output.join("\n"))
}

fn render_ordered_path_annotations(entries: &[(String, Vec<String>)]) -> Option<String> {
    render_ordered_path_annotations_with_layout(entries, PathAnnotationLayout::SeparateLines)
}

fn render_path_tree_model(paths: &[String]) -> Option<String> {
    let entries = paths
        .iter()
        .map(|path| (path.clone(), Vec::new()))
        .collect::<Vec<_>>();
    render_ordered_path_annotations(&entries)
}

fn render_paths_adaptive_model(paths: &[String]) -> String {
    let flat = paths.join("\n");
    render_path_tree_model(paths)
        .filter(|tree| model_representation_key(tree) < model_representation_key(&flat))
        .unwrap_or(flat)
}

fn render_path_annotations(entries: &[(String, Vec<String>)]) -> Option<String> {
    render_ordered_path_annotations(entries)
}

fn render_path_inline_annotations(entries: &[(String, Vec<String>)]) -> Option<String> {
    render_ordered_path_annotations_with_layout(entries, PathAnnotationLayout::InlineSingle)
}

fn render_fd_tree(paths: &[String], types: &BTreeMap<String, String>, roots: &[FdRoot]) -> Value {
    let mut tries = roots
        .iter()
        .map(|root| (root.alias.clone(), Trie::default()))
        .collect::<BTreeMap<_, _>>();
    let mut unmapped = Vec::new();
    for path in paths {
        let matched = roots
            .iter()
            .filter_map(|root| {
                relative_to_root(path, &root.rendered).map(|relative| (root, relative))
            })
            .max_by_key(|(root, _)| root.rendered.len());
        if let Some((root, relative)) = matched {
            insert_trie(
                tries.get_mut(&root.alias).expect("declared root trie"),
                relative,
                types.get(path).map(String::as_str).unwrap_or("unknown"),
            );
        } else {
            unmapped.push(json!({"path":path,"type":types.get(path).map(String::as_str).unwrap_or("unknown")}));
        }
    }
    let root_aliases = roots
        .iter()
        .map(|root| (root.alias.clone(), Value::String(root.rendered.clone())))
        .collect::<serde_json::Map<_, _>>();
    let trees = tries
        .into_iter()
        .filter_map(|(alias, trie)| {
            let lines = trie_lines(&trie);
            (!lines.is_empty()).then_some((alias, json!(lines)))
        })
        .collect::<serde_json::Map<_, _>>();
    json!({"root_aliases":root_aliases,"trees":trees,"unmapped":unmapped,"escape":"backslash escapes slash, pipe, backslash and control characters"})
}

fn render_rg_files(
    command: &GatewayCommand,
    snapshot: &Snapshot,
    offset: usize,
) -> Result<Projection, GatewayError> {
    let files = parse_nul_paths(&snapshot.stdout)?;
    if command.view == "summary" {
        if offset != 0 {
            return Err(GatewayError::input("summary view does not accept a cursor"));
        }
        return Ok(Projection {
            value: json!({"summary":{"files":files.len()}}),
            model: format!("files {}", files.len()),
            displayed: files.len(),
            total: files.len(),
            view: "summary".to_owned(),
            display_complete: true,
        });
    }
    if offset > files.len() {
        return Err(GatewayError::input(
            "cursor offset exceeds the snapshot result set",
        ));
    }
    let maximum_end = files.len().min(offset.saturating_add(command.limit));
    let end = if command.output == OutputFormat::Model && command.view != "lossless" {
        model_page_end(
            offset,
            maximum_end,
            command.model_token_budget,
            |candidate_end| {
                model_text_cost(&render_paths_adaptive_model(&files[offset..candidate_end]))
            },
        )
    } else {
        maximum_end
    };
    let page = &files[offset..end];
    let chosen = if command.view == "lossless" {
        "lossless"
    } else {
        "files"
    };
    Ok(Projection {
        value: json!({"files":page}),
        model: render_paths_adaptive_model(page),
        displayed: page.len(),
        total: files.len(),
        view: chosen.to_owned(),
        display_complete: end >= files.len(),
    })
}

fn render_rg_counts(
    command: &GatewayCommand,
    snapshot: &Snapshot,
    offset: usize,
) -> Result<Projection, GatewayError> {
    let text = std::str::from_utf8(&snapshot.stdout)
        .map_err(|_| GatewayError::input("rg count output was not UTF-8; use --artifact-out"))?;
    let mut records = Vec::new();
    for line in text.lines().filter(|line| !line.is_empty()) {
        let mut parts = line.rsplitn(2, ':');
        let count = parts
            .next()
            .and_then(|value| value.parse::<u64>().ok())
            .ok_or_else(|| {
                GatewayError::input(
                    "rg count output could not be parsed without losing record boundaries",
                )
            })?;
        let path = parts.next();
        records.push(json!({"path":path,"count":count,"native":line}));
    }
    if command.view == "summary" {
        if offset != 0 {
            return Err(GatewayError::input("summary view does not accept a cursor"));
        }
        return Ok(Projection {
            value: json!({"summary":{"records":records.len(),"sum":records.iter().filter_map(|record| record["count"].as_u64()).sum::<u64>()}}),
            model: format!(
                "records {} sum {}",
                records.len(),
                records
                    .iter()
                    .filter_map(|record| record["count"].as_u64())
                    .sum::<u64>()
            ),
            displayed: records.len(),
            total: records.len(),
            view: "summary".to_owned(),
            display_complete: true,
        });
    }
    if offset > records.len() {
        return Err(GatewayError::input(
            "cursor offset exceeds the snapshot result set",
        ));
    }
    let maximum_end = records.len().min(offset.saturating_add(command.limit));
    let end = if command.output == OutputFormat::Model && command.view != "lossless" {
        model_page_end(
            offset,
            maximum_end,
            command.model_token_budget,
            |candidate_end| {
                model_text_cost(&render_rg_counts_model(&records[offset..candidate_end]))
            },
        )
    } else {
        maximum_end
    };
    let page = &records[offset..end];
    let chosen = if command.view == "lossless" {
        "lossless"
    } else {
        "counts"
    };
    Ok(Projection {
        value: json!({"counts":page}),
        model: render_rg_counts_model(page),
        displayed: page.len(),
        total: records.len(),
        view: chosen.to_owned(),
        display_complete: end >= records.len(),
    })
}

fn render_rg_counts_model(records: &[Value]) -> String {
    let flat = records
        .iter()
        .map(|record| {
            let count = record["count"].as_u64().unwrap_or(0);
            record["path"]
                .as_str()
                .map_or_else(|| count.to_string(), |path| format!("{path}:{count}"))
        })
        .collect::<Vec<_>>()
        .join("\n");
    let entries = records
        .iter()
        .map(|record| {
            Some((
                record["path"].as_str()?.replace('\\', "/"),
                vec![record["count"].as_u64()?.to_string()],
            ))
        })
        .collect::<Option<Vec<_>>>();
    entries
        .as_deref()
        .and_then(render_path_annotations)
        .filter(|tree| model_representation_key(tree) < model_representation_key(&flat))
        .unwrap_or(flat)
}

fn render_rg_vimgrep(
    command: &GatewayCommand,
    snapshot: &Snapshot,
    offset: usize,
) -> Result<Projection, GatewayError> {
    let text = std::str::from_utf8(&snapshot.stdout)
        .map_err(|_| GatewayError::input("rg vimgrep output was not UTF-8; use --artifact-out"))?;
    let mut records = Vec::new();
    for line in text.lines() {
        let Some((path, line_number, column, body)) = split_vimgrep(line) else {
            return Err(GatewayError::input(
                "rg vimgrep output could not be parsed without losing path or position",
            ));
        };
        let lossless = command.view == "lossless";
        records.push(json!({"path":path.replace('\\', "/"),"line":line_number,"column":column,"text":if lossless { body.to_owned() } else { truncate_chars(body, command.max_text_chars) },"text_complete":lossless || body.chars().count() <= command.max_text_chars}));
    }
    if command.view == "summary" {
        if offset != 0 {
            return Err(GatewayError::input("summary view does not accept a cursor"));
        }
        return Ok(Projection {
            value: json!({"summary":{"matches":records.len()},"text_complete":false}),
            model: format!("matches {}", records.len()),
            displayed: records.len(),
            total: records.len(),
            view: "summary".to_owned(),
            display_complete: true,
        });
    }
    if offset > records.len() {
        return Err(GatewayError::input(
            "cursor offset exceeds the snapshot result set",
        ));
    }
    let maximum_end = records.len().min(offset.saturating_add(command.limit));
    let end = if command.output == OutputFormat::Model && command.view != "lossless" {
        model_page_end(
            offset,
            maximum_end,
            command.model_token_budget,
            |candidate_end| model_text_cost(&render_vimgrep_model(&records[offset..candidate_end])),
        )
    } else {
        maximum_end
    };
    let page = &records[offset..end];
    let chosen = if command.view == "lossless" {
        "lossless"
    } else {
        "locations"
    };
    let text_complete = records
        .iter()
        .all(|record| record["text_complete"].as_bool() == Some(true));
    let value = if chosen == "lossless" {
        json!({"records":page,"text_complete":text_complete})
    } else {
        json!({"locations":page,"text_complete":text_complete})
    };
    Ok(Projection {
        value,
        model: render_vimgrep_model(page),
        displayed: page.len(),
        total: records.len(),
        view: chosen.to_owned(),
        display_complete: end >= records.len(),
    })
}

fn render_vimgrep_model(records: &[Value]) -> String {
    let flat = records
        .iter()
        .map(|record| {
            format!(
                "{}:{}:{}:{}",
                record["path"].as_str().unwrap_or("<unknown>"),
                record["line"].as_u64().unwrap_or(0),
                record["column"].as_u64().unwrap_or(0),
                record["text"].as_str().unwrap_or("")
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let mut groups: Vec<(String, Vec<String>)> = Vec::new();
    for record in records {
        let path = record["path"]
            .as_str()
            .unwrap_or("<unknown>")
            .replace('\\', "/");
        if groups.last().is_none_or(|(current, _)| current != &path) {
            groups.push((path, Vec::new()));
        }
        groups
            .last_mut()
            .expect("group was inserted")
            .1
            .push(format!(
                "{}:{}:{}",
                record["line"].as_u64().unwrap_or(0),
                record["column"].as_u64().unwrap_or(0),
                record["text"].as_str().unwrap_or("")
            ));
    }
    let grouped = groups
        .iter()
        .flat_map(|(path, annotations)| {
            std::iter::once(path.clone()).chain(
                annotations
                    .iter()
                    .map(|annotation| format!("  {annotation}")),
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let mut candidates = vec![flat, grouped];
    if let Some(tree) = render_path_annotations(&groups) {
        candidates.push(tree);
    }
    candidates
        .into_iter()
        .min_by_key(|candidate| model_representation_key(candidate))
        .unwrap_or_default()
}

fn split_vimgrep(line: &str) -> Option<(&str, u64, u64, &str)> {
    let bytes = line.as_bytes();
    for first in 0..bytes.len() {
        if bytes[first] != b':' {
            continue;
        }
        let second = bytes[first + 1..]
            .iter()
            .position(|byte| *byte == b':')
            .map(|value| first + 1 + value)?;
        let line_number = line[first + 1..second].parse::<u64>().ok();
        if line_number.is_none() {
            continue;
        }
        let third = bytes[second + 1..]
            .iter()
            .position(|byte| *byte == b':')
            .map(|value| second + 1 + value)?;
        let column = line[second + 1..third].parse::<u64>().ok();
        if let (Some(line_number), Some(column)) = (line_number, column) {
            return Some((&line[..first], line_number, column, &line[third + 1..]));
        }
    }
    None
}

fn emit_bounded_text(
    command: &GatewayCommand,
    mode: Mode,
    stdout: &[u8],
    native_exit: i32,
) -> Result<(), GatewayError> {
    let text = std::str::from_utf8(stdout)
        .map_err(|_| GatewayError::input("native output was not UTF-8; use --artifact-out"))?;
    let lines = text.lines().collect::<Vec<_>>();
    let maximum_lines = lines.len().min(command.limit);
    let displayed_lines = if command.output == OutputFormat::Model {
        model_page_end(0, maximum_lines, command.model_token_budget, |end| {
            model_text_cost(
                &lines[..end]
                    .iter()
                    .map(|line| truncate_chars(line, command.max_text_chars))
                    .collect::<Vec<_>>()
                    .join("\n"),
            )
        })
    } else {
        maximum_lines
    };
    let displayed = lines
        .iter()
        .take(displayed_lines)
        .map(|line| truncate_chars(line, command.max_text_chars))
        .collect::<Vec<_>>();
    let text_complete = lines
        .iter()
        .take(displayed_lines)
        .all(|line| line.chars().count() <= command.max_text_chars);
    let display_complete = displayed.len() == lines.len();
    if command.output == OutputFormat::Model && command.receipt != "full" {
        let mut model = displayed.join("\n");
        if !display_complete {
            push_model_line(
                &mut model,
                &format!("@cut lines={}", lines.len().saturating_sub(displayed.len())),
            );
        }
        let cut = displayed.iter().filter(|line| line.ends_with('…')).count();
        if cut > 0 {
            push_model_line(&mut model, &format!("@cut text={cut}"));
        }
        return emit_model_text(&model);
    }
    let receipt = if command.receipt == "full" {
        json!({
            "schema":"sgy.query.bounded-text/v1","backend":backend_name(command.backend),
            "mode":mode.id,"native_exit":native_exit,"total_lines":lines.len(),
            "displayed_lines":displayed.len(),"omitted_lines":lines.len().saturating_sub(displayed.len()),
            "display_complete":display_complete,"text_complete":text_complete
        })
    } else {
        let mut receipt = Map::new();
        receipt.insert("schema".to_owned(), json!("sgy.query.bounded-text/v2"));
        receipt.insert("total_lines".to_owned(), json!(lines.len()));
        receipt.insert(
            "complete".to_owned(),
            json!({"display":display_complete,"content":text_complete}),
        );
        if native_exit != 0 {
            receipt.insert("native_exit".to_owned(), json!(native_exit));
        }
        if !display_complete {
            receipt.insert("displayed_lines".to_owned(), json!(displayed.len()));
            receipt.insert(
                "omitted_lines".to_owned(),
                json!(lines.len().saturating_sub(displayed.len())),
            );
        }
        Value::Object(receipt)
    };
    emit_yaml(&json!({"_sgy":receipt,"lines":displayed}))
}

fn escape_segment(value: &str) -> String {
    let mut output = String::new();
    let mut leading = true;
    for character in value.chars() {
        match character {
            ' ' if leading => output.push_str("\\s"),
            '\\' => output.push_str("\\\\"),
            '/' => output.push_str("\\/"),
            '|' => output.push_str("\\|"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            other if other.is_control() => output.push_str(&format!("\\u{{{:x}}}", other as u32)),
            other => output.push(other),
        }
        if character != ' ' {
            leading = false;
        }
    }
    output
}

fn render_rg(
    command: &GatewayCommand,
    snapshot: &Snapshot,
    offset: usize,
) -> Result<Projection, GatewayError> {
    if command.view == "lossless" {
        let events = parse_rg_all_events(&snapshot.stdout)?;
        if offset > events.len() {
            return Err(GatewayError::input(
                "cursor offset exceeds the snapshot result set",
            ));
        }
        let end = events.len().min(offset.saturating_add(command.limit));
        return Ok(Projection {
            value: json!({"events":&events[offset..end]}),
            model: String::new(),
            displayed: end - offset,
            total: events.len(),
            view: "lossless".to_owned(),
            display_complete: end >= events.len(),
        });
    }
    let events = parse_rg_records(&snapshot.stdout)?;

    if command.view == "summary" {
        if offset != 0 {
            return Err(GatewayError::input("summary view does not accept a cursor"));
        }
        let matches = events
            .iter()
            .filter(|event| event["type"] == "match")
            .count();
        let files = events
            .iter()
            .filter(|event| event["type"] == "match")
            .filter_map(|event| event["path"].as_str())
            .collect::<BTreeSet<_>>()
            .len();
        return Ok(Projection {
            value: json!({"summary":{"events":events.len(),"matches":matches,"files":files}}),
            model: format!("matches {matches} files {files}"),
            displayed: matches,
            total: matches,
            view: "summary".to_owned(),
            display_complete: true,
        });
    }

    if command.view == "files" {
        let files = events
            .iter()
            .filter(|event| event["type"] == "match")
            .filter_map(|event| event["path"].as_str())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        if offset > files.len() {
            return Err(GatewayError::input(
                "cursor offset exceeds the snapshot result set",
            ));
        }
        let end = files.len().min(offset.saturating_add(command.limit));
        return Ok(Projection {
            value: json!({"files":&files[offset..end]}),
            model: render_path_tree_model(
                &files[offset..end]
                    .iter()
                    .map(|path| (*path).to_owned())
                    .collect::<Vec<_>>(),
            )
            .filter(|tree| {
                model_representation_key(tree)
                    < model_representation_key(&files[offset..end].join("\n"))
            })
            .unwrap_or_else(|| files[offset..end].join("\n")),
            displayed: end - offset,
            total: files.len(),
            view: "files".to_owned(),
            display_complete: end >= files.len(),
        });
    }

    if command.view == "locations" {
        let locations = events
            .iter()
            .filter(|event| event["type"] == "match")
            .map(|event| json!({"path":event["path"],"line":event["line_number"],"absolute_offset":event["absolute_offset"],"submatches":event["submatches"]}))
            .collect::<Vec<_>>();
        if offset > locations.len() {
            return Err(GatewayError::input(
                "cursor offset exceeds the snapshot result set",
            ));
        }
        let maximum_end = locations.len().min(offset.saturating_add(command.limit));
        let match_events = events
            .iter()
            .filter(|event| event["type"] == "match")
            .collect::<Vec<_>>();
        let end = if command.output == OutputFormat::Model {
            model_page_end(
                offset,
                maximum_end,
                command.model_token_budget,
                |candidate_end| {
                    model_text_cost(&render_rg_locations_adaptive_model(
                        &match_events[offset..candidate_end],
                    ))
                },
            )
        } else {
            maximum_end
        };
        return Ok(Projection {
            value: json!({"locations":&locations[offset..end]}),
            model: render_rg_locations_adaptive_model(&match_events[offset..end]),
            displayed: end - offset,
            total: locations.len(),
            view: "locations".to_owned(),
            display_complete: end >= locations.len(),
        });
    }

    if offset > events.len() {
        return Err(GatewayError::input(
            "cursor offset exceeds the snapshot result set",
        ));
    }
    let (effective_limit, effective_budget, effective_max_text_chars) =
        direct_rg_complete_policy(command, &events);
    let maximum_end = events.len().min(offset.saturating_add(effective_limit));
    let end = if command.output == OutputFormat::Model {
        model_page_end(offset, maximum_end, effective_budget, |candidate_end| {
            let (model, _) = render_rg_adaptive_model(
                &events[offset..candidate_end],
                &command.view,
                effective_max_text_chars,
            );
            model_text_cost(&model)
        })
    } else {
        maximum_end
    };
    let page = &events[offset..end];
    let grouped = render_rg_grouped(page, effective_max_text_chars);
    let records = render_rg_records(page, effective_max_text_chars);
    let (model, chosen) = render_rg_adaptive_model(page, &command.view, effective_max_text_chars);
    let value = match chosen {
        "grouped" => grouped,
        "records" => records,
        _ => grouped,
    };
    Ok(Projection {
        value,
        model,
        displayed: page.len(),
        total: events.len(),
        view: chosen.to_owned(),
        display_complete: end >= events.len(),
    })
}

fn direct_rg_complete_policy(command: &GatewayCommand, events: &[Value]) -> (usize, usize, usize) {
    let fallback = (
        command.limit,
        command.model_token_budget,
        command.max_text_chars,
    );
    if !command.auto_complete
        || command.output != OutputFormat::Model
        || command.view != "auto"
        || events.is_empty()
        || events.len() > DIRECT_COMPLETE_MAX_UNITS
    {
        return fallback;
    }

    let paths = events
        .iter()
        .filter_map(|event| event["path"].as_str())
        .collect::<BTreeSet<_>>();
    if paths.len() == 1
        && events.iter().all(|event| {
            event["text"]
                .as_str()
                .unwrap_or("")
                .trim_end_matches(['\r', '\n'])
                .chars()
                .count()
                <= DIRECT_SINGLE_PATH_MAX_TEXT_CHARS
        })
    {
        let (model, _) =
            render_rg_adaptive_model(events, &command.view, DIRECT_SINGLE_PATH_MAX_TEXT_CHARS);
        if model_text_cost(&model) <= command.model_token_budget {
            return (
                events.len(),
                command.model_token_budget,
                DIRECT_SINGLE_PATH_MAX_TEXT_CHARS,
            );
        }
    }

    let (model, _) = render_rg_adaptive_model(events, &command.view, command.max_text_chars);
    if model_text_cost(&model) <= command.model_token_budget {
        return (
            events.len(),
            command.model_token_budget,
            command.max_text_chars,
        );
    }
    fallback
}

fn render_rg_adaptive_model<'a>(
    events: &[Value],
    requested_view: &'a str,
    max_chars: usize,
) -> (String, &'a str) {
    let records = render_rg_records_model(events, max_chars);
    if requested_view == "records" {
        return (records, "records");
    }
    let grouped = render_rg_grouped_model(events, max_chars);
    let mut candidates = vec![(grouped, "grouped")];
    if requested_view == "auto" {
        candidates.push((records, "records"));
    }
    if let Some(tree) = render_rg_tree_grouped_model(events, max_chars) {
        candidates.push((tree, "grouped"));
    }
    candidates
        .into_iter()
        .min_by_key(|(candidate, _)| model_representation_key(candidate))
        .unwrap_or_else(|| (String::new(), requested_view))
}

fn parse_rg_all_events(bytes: &[u8]) -> Result<Vec<Value>, GatewayError> {
    let text = std::str::from_utf8(bytes).map_err(|_| {
        GatewayError::input("rg machine output was not UTF-8; use --artifact-out for native bytes")
    })?;
    let mut output = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let event: Value = serde_json::from_str(line).map_err(|error| {
            GatewayError::input(format!(
                "invalid rg JSON event at line {}: {error}",
                index + 1
            ))
        })?;
        output.push(event);
    }
    Ok(output)
}

fn parse_rg_records(bytes: &[u8]) -> Result<Vec<Value>, GatewayError> {
    let events = parse_rg_all_events(bytes)?;
    let mut output = Vec::new();
    for event in events {
        let kind = event["type"].as_str().unwrap_or("unknown");
        if !matches!(kind, "match" | "context") {
            continue;
        }
        let data = &event["data"];
        if data["path"].get("bytes").is_some() || data["lines"].get("bytes").is_some() {
            return Err(GatewayError::input(
                "rg returned byte-encoded path or text; request an explicit artifact/raw mode",
            ));
        }
        output.push(json!({"type":kind,"path":data["path"]["text"],"line_number":data["line_number"],"absolute_offset":data["absolute_offset"],"text":data["lines"]["text"],"submatches":data["submatches"]}));
    }
    Ok(output)
}

fn render_rg_grouped(events: &[Value], max_chars: usize) -> Value {
    let mut groups: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    let mut truncated = 0;
    for event in events {
        let path = event["path"]
            .as_str()
            .unwrap_or("<unknown>")
            .replace('\\', "/");
        let original = event["text"]
            .as_str()
            .unwrap_or("")
            .trim_end_matches(['\r', '\n']);
        let was_truncated = original.chars().count() > max_chars;
        let text = truncate_chars(original, max_chars);
        if was_truncated {
            truncated += 1;
        }
        groups.entry(path).or_default().push(json!({"kind":event["type"],"line":event["line_number"],"absolute_offset":event["absolute_offset"],"text":text,"submatches":event["submatches"]}));
    }
    json!({"groups":groups,"text_truncated_records":truncated,"text_complete":truncated == 0})
}

fn render_rg_records(events: &[Value], max_chars: usize) -> Value {
    let mut records = Vec::with_capacity(events.len());
    let mut truncated = 0;
    for event in events {
        let original = event["text"]
            .as_str()
            .unwrap_or("")
            .trim_end_matches(['\r', '\n']);
        let was_truncated = original.chars().count() > max_chars;
        if was_truncated {
            truncated += 1;
        }
        records.push(json!({
            "type":event["type"],"path":event["path"],"line_number":event["line_number"],
            "absolute_offset":event["absolute_offset"],"text":truncate_chars(original, max_chars),"submatches":event["submatches"]
        }));
    }
    json!({"records":records,"text_truncated_records":truncated,"text_complete":truncated == 0})
}

fn render_rg_grouped_model(events: &[Value], max_chars: usize) -> String {
    let groups = rg_text_annotations(events, max_chars);
    let mut lines = Vec::new();
    for (path, annotations) in groups {
        lines.push(path);
        lines.extend(
            annotations
                .into_iter()
                .map(|annotation| format!("  {annotation}")),
        );
    }
    lines.join("\n")
}

fn rg_text_annotations(events: &[Value], max_chars: usize) -> Vec<(String, Vec<String>)> {
    let mut groups: Vec<(String, Vec<String>)> = Vec::new();
    for event in events {
        let path = event["path"]
            .as_str()
            .unwrap_or("<unknown>")
            .replace('\\', "/");
        if groups.last().is_none_or(|(current, _)| current != &path) {
            groups.push((path, Vec::new()));
        }
        let line = event["line_number"].as_u64().unwrap_or(0);
        let separator = if event["type"] == "context" { '-' } else { ':' };
        let text = truncate_chars(
            event["text"]
                .as_str()
                .unwrap_or("")
                .trim_end_matches(['\r', '\n']),
            max_chars,
        );
        groups
            .last_mut()
            .expect("group was inserted")
            .1
            .push(format!("{line}{separator}{text}"));
    }
    groups
}

fn render_rg_tree_grouped_model(events: &[Value], max_chars: usize) -> Option<String> {
    render_path_annotations(&rg_text_annotations(events, max_chars))
}

fn render_rg_records_model(events: &[Value], max_chars: usize) -> String {
    events
        .iter()
        .map(|event| {
            let path = event["path"]
                .as_str()
                .unwrap_or("<unknown>")
                .replace('\\', "/");
            let line = event["line_number"].as_u64().unwrap_or(0);
            let separator = if event["type"] == "context" { '-' } else { ':' };
            let text = truncate_chars(
                event["text"]
                    .as_str()
                    .unwrap_or("")
                    .trim_end_matches(['\r', '\n']),
                max_chars,
            );
            format!("{path}{separator}{line}{separator}{text}")
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn render_rg_locations_model(events: &[&Value]) -> String {
    events
        .iter()
        .map(|event| {
            let path = event["path"]
                .as_str()
                .unwrap_or("<unknown>")
                .replace('\\', "/");
            let line = event["line_number"].as_u64().unwrap_or(0);
            let ranges = event["submatches"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|range| {
                    Some(format!(
                        "{}-{}",
                        range["start"].as_u64()?,
                        range["end"].as_u64()?
                    ))
                })
                .collect::<Vec<_>>()
                .join(",");
            if ranges.is_empty() {
                format!("{path}:{line}")
            } else {
                format!("{path}:{line}:{ranges}")
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn rg_location_annotations(events: &[&Value]) -> Vec<(String, Vec<String>)> {
    let mut groups: Vec<(String, Vec<String>)> = Vec::new();
    for event in events {
        let path = event["path"]
            .as_str()
            .unwrap_or("<unknown>")
            .replace('\\', "/");
        if groups.last().is_none_or(|(current, _)| current != &path) {
            groups.push((path, Vec::new()));
        }
        let line = event["line_number"].as_u64().unwrap_or(0);
        let ranges = event["submatches"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|range| {
                Some(format!(
                    "{}-{}",
                    range["start"].as_u64()?,
                    range["end"].as_u64()?
                ))
            })
            .collect::<Vec<_>>()
            .join(",");
        let annotation = if ranges.is_empty() {
            line.to_string()
        } else {
            format!("{line}:{ranges}")
        };
        groups
            .last_mut()
            .expect("group was inserted")
            .1
            .push(annotation);
    }
    groups
}

fn render_rg_locations_adaptive_model(events: &[&Value]) -> String {
    let flat = render_rg_locations_model(events);
    let groups = rg_location_annotations(events);
    let grouped = groups
        .iter()
        .flat_map(|(path, annotations)| {
            std::iter::once(path.clone()).chain(
                annotations
                    .iter()
                    .map(|annotation| format!("  {annotation}")),
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let mut candidates = vec![flat, grouped];
    if let Some(tree) = render_path_annotations(&groups) {
        candidates.push(tree);
    }
    candidates
        .into_iter()
        .min_by_key(|candidate| model_representation_key(candidate))
        .unwrap_or_default()
}

fn truncate_chars(value: &str, max: usize) -> String {
    let mut chars = value.chars();
    let prefix = chars.by_ref().take(max).collect::<String>();
    if chars.next().is_some() {
        format!("{prefix}…")
    } else {
        prefix
    }
}

fn os_args_json(args: &[OsString]) -> Result<Vec<String>, GatewayError> {
    args.iter()
        .map(|arg| {
            arg.to_str().map(ToOwned::to_owned).ok_or_else(|| {
                GatewayError::input(
                    "native argv cannot be represented losslessly in UTF-8 defaults output",
                )
            })
        })
        .collect()
}

fn model_path<'a>(path: &'a Path, role: &str) -> Result<&'a str, GatewayError> {
    path.to_str().ok_or_else(|| {
        GatewayError::input(format!(
            "{role} path cannot be represented losslessly in a model continuation"
        ))
    })
}

pub(super) fn model_text_cost(text: &str) -> usize {
    let mut total = 0_usize;
    let mut ascii_word = 0_usize;
    for character in text.chars() {
        if character.is_ascii_alphanumeric() || character == '_' {
            ascii_word += 1;
            continue;
        }
        if ascii_word > 0 {
            total += ascii_word.div_ceil(4);
            ascii_word = 0;
        }
        if character == '\n' || !character.is_whitespace() {
            total += 1;
        }
    }
    total + ascii_word.div_ceil(4)
}

fn model_representation_key(text: &str) -> (usize, usize) {
    (model_text_cost(text), text.chars().count())
}

pub(super) fn model_page_end(
    offset: usize,
    maximum_end: usize,
    budget: usize,
    mut cost: impl FnMut(usize) -> usize,
) -> usize {
    if offset >= maximum_end {
        return offset;
    }
    let first = offset + 1;
    if cost(first) > budget {
        return first;
    }
    let mut best = first;
    let mut low = first + 1;
    let mut high = maximum_end;
    while low <= high {
        let middle = low + (high - low) / 2;
        if cost(middle) <= budget {
            best = middle;
            low = middle + 1;
        } else {
            high = middle - 1;
        }
    }
    best
}

fn emit_yaml(value: &Value) -> Result<(), GatewayError> {
    let mut stdout = io::stdout().lock();
    write_yaml_document(value, &mut stdout, false)
        .map_err(|error| GatewayError::io("cannot write query YAML", error))?;
    stdout
        .flush()
        .map_err(|error| GatewayError::io("cannot flush query YAML", error))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn classifies_side_effect_and_binary_modes_before_adaptive_modes() {
        assert_eq!(
            Handling::Passthrough,
            classify(GatewayBackend::Fd, &args(&[".", "-x", "echo", "{}"])).handling
        );
        assert_eq!(
            Handling::Artifact,
            classify(GatewayBackend::Fd, &args(&["--print0", "."])).handling
        );
        assert_eq!(
            "RG-PREPROCESSOR",
            classify(GatewayBackend::Rg, &args(&["--pre", "tool", "x"])).id
        );
        assert_eq!(
            "RG-NUL-PATHS",
            classify(GatewayBackend::Rg, &args(&["--null", "x"])).id
        );
        assert_eq!(
            "FD-PRINT0",
            classify(GatewayBackend::Fd, &args(&["-H0", "."])).id
        );
        assert_eq!(
            "RG-COUNT",
            classify(GatewayBackend::Rg, &args(&["-Hnc", "needle", "."])).id
        );
        assert_eq!(
            "RG-REPLACE-DISPLAY",
            classify(
                GatewayBackend::Rg,
                &args(&["-irreplacement", "needle", "."])
            )
            .id
        );
        assert_eq!(
            "RG-SEARCH-TEXT",
            classify(GatewayBackend::Rg, &args(&["-ehelp", "."])).id
        );
        assert_eq!(
            "RG-SEARCH-TEXT",
            classify(GatewayBackend::Rg, &args(&["-e", "--help", "."])).id
        );
        assert_eq!(
            "FD-PATHS",
            classify(GatewayBackend::Fd, &args(&["-Ehidden", ".", "."])).id
        );
        assert_eq!(
            "FD-FORMAT",
            classify(
                GatewayBackend::Fd,
                &args(&["--format", "--print0", ".", "."])
            )
            .id
        );
        assert_eq!(
            "RG-SEARCH-TEXT",
            classify(GatewayBackend::Rg, &args(&["--", "--help", "."])).id
        );
        assert_eq!(
            "FD-PATHS",
            classify(GatewayBackend::Fd, &args(&["--", "--print0", "."])).id
        );
        assert_eq!(
            "SCC-FILES",
            classify(GatewayBackend::Scc, &args(&["--by-file", "."])).id
        );
        assert_eq!(
            "SCC-LANGUAGES",
            classify(GatewayBackend::Scc, &args(&["--sort", "--by-file", "."])).id,
            "an option value must not be reinterpreted as a selector"
        );
        assert_eq!(
            "SCC-FORMAT",
            classify(GatewayBackend::Scc, &args(&["-fcsv", "."])).id
        );
        assert_eq!(
            "SCC-OUTPUT",
            classify(GatewayBackend::Scc, &args(&["-oreport.json", "."])).id
        );
        assert_eq!(
            "SCC-LANGUAGES",
            classify(GatewayBackend::Scc, &args(&["--", "--by-file"])).id
        );
        assert_eq!(
            args(&["-F", "--json", "--color=never", "--", "-needle", "."]),
            effective_argv(
                &args(&["-F", "--", "-needle", "."]),
                &args(&["--json", "--color=never"])
            )
        );
    }

    #[test]
    fn covers_every_documented_rg_fd_and_scc_primary_selector() {
        let rg_cases = [
            (&["--json"][..], "RG-SEARCH-JSON"),
            (&["--files"], "RG-FILES"),
            (&["--files-with-matches"], "RG-FILES-WITH-MATCHES"),
            (&["--files-without-match"], "RG-FILES-WITHOUT-MATCH"),
            (&["--count"], "RG-COUNT"),
            (&["--count-matches"], "RG-COUNT-MATCHES"),
            (&["--only-matching"], "RG-ONLY-MATCHING"),
            (&["--vimgrep"], "RG-VIMGREP"),
            (&["--replace", "x"], "RG-REPLACE-DISPLAY"),
            (&["--passthru"], "RG-PASSTHRU"),
            (&["--pre", "tool"], "RG-PREPROCESSOR"),
            (&["--search-zip"], "RG-SEARCH-ZIP"),
            (&["--null"], "RG-NUL-PATHS"),
            (&["--null-data"], "RG-NULL-DATA"),
            (&["--type-list"], "RG-TYPE-LIST"),
            (&["--generate=man"], "RG-GENERATE"),
            (&["--help"], "RG-HELP"),
            (&["--version"], "RG-VERSION"),
            (&["needle"], "RG-SEARCH-TEXT"),
        ];
        for (argv, expected) in rg_cases {
            assert_eq!(
                expected,
                classify(GatewayBackend::Rg, &args(argv)).id,
                "{argv:?}"
            );
        }
        let fd_cases = [
            (&["--list-details"][..], "FD-LIST-DETAILS"),
            (&["--print0"], "FD-PRINT0"),
            (&["--format={}"], "FD-FORMAT"),
            (&["--hyperlink=always"], "FD-HYPERLINK"),
            (&["--has-results"], "FD-QUIET"),
            (&["--exec", "echo"], "FD-EXEC"),
            (&["--exec-batch", "echo"], "FD-EXEC-BATCH"),
            (&["--help"], "FD-HELP"),
            (&["--version"], "FD-VERSION"),
            (&["needle"], "FD-PATHS"),
        ];
        for (argv, expected) in fd_cases {
            assert_eq!(
                expected,
                classify(GatewayBackend::Fd, &args(argv)).id,
                "{argv:?}"
            );
        }
        let scc_cases = [
            (&["--by-file"][..], "SCC-FILES"),
            (&["--format", "json"], "SCC-LANGUAGES"),
            (&["--format", "json2"], "SCC-LANGUAGES"),
            (&["--format", "csv"], "SCC-FORMAT"),
            (&["--format-multi", "json:a.json"], "SCC-OUTPUT"),
            (&["--output", "report.json"], "SCC-OUTPUT"),
            (&["--languages"], "SCC-LANGUAGE-LIST"),
            (&["--help"], "SCC-HELP"),
            (&["--version"], "SCC-VERSION"),
            (&["."], "SCC-LANGUAGES"),
        ];
        for (argv, expected) in scc_cases {
            assert_eq!(
                expected,
                classify(GatewayBackend::Scc, &args(argv)).id,
                "{argv:?}"
            );
        }
        assert!(injected_argv(
            GatewayBackend::Scc,
            classify(GatewayBackend::Scc, &args(&["--format"])),
            &args(&["--format"]),
        )
        .is_empty());
    }

    #[test]
    fn auto_cursor_binds_the_chosen_view_and_exact_snapshot() {
        let snapshot = "a".repeat(32);
        let cursor = make_cursor(&snapshot, "tree", 17);
        assert_eq!(
            (17, Some("tree".to_owned())),
            parse_cursor(Some(&cursor), &snapshot, "auto").expect("valid cursor")
        );
        assert!(parse_cursor(Some(&cursor), &snapshot, "flat").is_err());
        assert!(parse_cursor(Some(&cursor), &"b".repeat(32), "auto").is_err());
    }

    #[test]
    fn fd_tree_preserves_duplicates_and_escapes_names() {
        let types = BTreeMap::from([
            ("src/a|b.ts".to_owned(), "file".to_owned()),
            ("src/nested/c.ts".to_owned(), "file".to_owned()),
        ]);
        let roots = vec![FdRoot {
            alias: "R0".to_owned(),
            rendered: ".".to_owned(),
        }];
        let value = render_fd_tree(
            &[
                "src/a|b.ts".to_owned(),
                "src/a|b.ts".to_owned(),
                "src/nested/c.ts".to_owned(),
            ],
            &types,
            &roots,
        );
        let lines = value["trees"]["R0"]
            .as_array()
            .expect("root tree")
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();
        assert!(lines
            .iter()
            .any(|line| line.contains("a\\|b.ts") && line.contains("*2")));
        assert!(lines.iter().any(|line| line.trim() == "nested/"));
        assert_eq!(value["root_aliases"]["R0"], ".");
        assert_eq!(
            value["unmapped"].as_array().expect("unmapped array").len(),
            0
        );
    }

    #[test]
    fn fd_roots_preserve_explicit_multi_root_and_absolute_identity() {
        let cwd = Path::new(r"C:\repo");
        assert_eq!(
            vec![
                FdRoot {
                    alias: "R0".to_owned(),
                    rendered: "src".to_owned()
                },
                FdRoot {
                    alias: "R1".to_owned(),
                    rendered: "docs".to_owned()
                }
            ],
            fd_roots(&args(&[".", "src", "docs"]), cwd)
        );
        assert_eq!(
            vec![FdRoot {
                alias: "R0".to_owned(),
                rendered: "C:/repo/src".to_owned()
            }],
            fd_roots(&args(&["--absolute-path", ".", "src"]), cwd)
        );
        assert_eq!(
            vec![FdRoot {
                alias: "R0".to_owned(),
                rendered: "C:/repo/src".to_owned()
            }],
            fd_roots(&args(&["-a", "-Csrc", ".", "."]), cwd)
        );
        assert_eq!(
            vec![FdRoot {
                alias: "R0".to_owned(),
                rendered: "src".to_owned()
            }],
            fd_roots(&args(&["--search-path=src", "."]), cwd)
        );
    }

    #[test]
    fn fd_tree_keeps_internal_directory_results_and_unmapped_paths() {
        let paths = vec![
            "src".to_owned(),
            "src/a.ts".to_owned(),
            "elsewhere/x.ts".to_owned(),
        ];
        let types = BTreeMap::from([
            ("src".to_owned(), "dir".to_owned()),
            ("src/a.ts".to_owned(), "file".to_owned()),
            ("elsewhere/x.ts".to_owned(), "file".to_owned()),
        ]);
        let roots = vec![FdRoot {
            alias: "R0".to_owned(),
            rendered: "src".to_owned(),
        }];
        let value = render_fd_tree(&paths, &types, &roots);
        let lines = value["trees"]["R0"].as_array().expect("root tree");
        assert_eq!(lines[0], "$|dir");
        assert_eq!(lines[1], "a.ts|file");
        assert_eq!(value["unmapped"][0]["path"], "elsewhere/x.ts");
    }

    #[test]
    fn fd_tree_segment_escaping_removes_structural_ambiguity() {
        assert_eq!(escape_segment("  文 件|a\\b\t"), r"\s\s文 件\|a\\b\t");
        assert_eq!(escape_segment("plain name"), "plain name");
        assert_eq!(escape_segment("control\u{7}"), r"control\u{7}");
    }

    #[test]
    fn model_tree_collapses_unary_chains_without_metadata() {
        let paths = vec![
            "A/A0".to_owned(),
            "A/A1/F1".to_owned(),
            "A/A2".to_owned(),
            "B/B0/B1".to_owned(),
        ];
        assert_eq!(
            render_path_tree_model(&paths).expect("reversible tree"),
            "A/\n  A0\n  A1/F1\n  A2\nB/B0/B1"
        );
    }

    #[test]
    fn model_tree_preserves_native_depth_first_order_without_requiring_sorting() {
        let paths = vec![
            "src/processor/location.rs".to_owned(),
            "src/processor.rs".to_owned(),
            "tests/process.rs".to_owned(),
        ];
        assert_eq!(
            render_path_tree_model(&paths).expect("order-preserving tree"),
            "src/\n  processor/location.rs\n  processor.rs\ntests/process.rs"
        );
    }

    #[test]
    fn model_tree_rejects_prefix_reentry_that_would_reorder_evidence() {
        let paths = vec!["A/one".to_owned(), "B/two".to_owned(), "A/three".to_owned()];
        assert!(render_path_tree_model(&paths).is_none());
    }

    #[test]
    fn model_tree_can_inline_one_annotation_per_leaf() {
        let entries = vec![
            ("src/a.rs".to_owned(), vec!["Rust\t6\t5".to_owned()]),
            ("src/nested/b.rs".to_owned(), vec!["Rust\t4\t3".to_owned()]),
        ];
        assert_eq!(
            render_path_inline_annotations(&entries).expect("inline path annotations"),
            "src/\n  a.rs\tRust\t6\t5\n  nested/b.rs\tRust\t4\t3"
        );
    }

    #[test]
    fn model_tree_rejects_noncanonical_paths_and_ambiguous_inline_annotations() {
        assert!(render_path_tree_model(&["/src/a.rs".to_owned()]).is_none());
        assert!(render_path_tree_model(&["src//a.rs".to_owned()]).is_none());
        assert!(render_path_inline_annotations(&[(
            "src/a.rs".to_owned(),
            vec!["one".to_owned(), "two".to_owned()],
        )])
        .is_none());
        assert!(render_path_inline_annotations(&[(
            "src/a.rs".to_owned(),
            vec!["line one\nline two".to_owned()],
        )])
        .is_none());
    }

    #[test]
    fn fd_model_paths_remove_a_single_declared_root_only() {
        let paths = vec![
            "tools/srcq/docs/cache.md".to_owned(),
            "tools/srcq/docs/usage.md".to_owned(),
        ];
        let single = vec![FdRoot {
            alias: "R0".to_owned(),
            rendered: "tools/srcq/docs".to_owned(),
        }];
        assert_eq!(
            fd_relative_model_paths(&paths, &single),
            Some(vec!["cache.md".to_owned(), "usage.md".to_owned()])
        );
        assert_eq!(
            fd_relative_model_paths(
                &paths,
                &[
                    single[0].clone(),
                    FdRoot {
                        alias: "R1".to_owned(),
                        rendered: "skills".to_owned(),
                    },
                ]
            ),
            None
        );
    }

    #[test]
    fn fd_model_tree_requires_uniform_types() {
        let paths = vec!["A/file".to_owned(), "A/dir".to_owned()];
        let types = BTreeMap::from([
            ("A/file".to_owned(), "file".to_owned()),
            ("A/dir".to_owned(), "directory".to_owned()),
        ]);
        assert!(!fd_model_types_are_uniform(&paths, &types));
        assert_eq!(
            render_fd_flat_model(&paths, &types),
            "A/file\nA/dir|directory"
        );
    }

    #[test]
    fn fd_mixed_file_and_directory_model_uses_only_a_directory_suffix() {
        let paths = vec!["A/file".to_owned(), "A/dir".to_owned()];
        let types = BTreeMap::from([
            ("A/file".to_owned(), "file".to_owned()),
            ("A/dir".to_owned(), "dir".to_owned()),
        ]);
        assert_eq!(render_fd_flat_model(&paths, &types), "A/file\nA/dir/");
    }

    #[test]
    fn cursor_carries_the_snapshot_needed_for_model_continuation() {
        let cursor = make_cursor("snapshot-id", "tree", 12);
        assert_eq!(
            cursor_snapshot(&cursor).expect("valid cursor"),
            "snapshot-id"
        );
        assert!(cursor_snapshot("q1.invalid").is_err());
    }

    #[test]
    fn continuation_handles_are_short_canonical_and_legacy_readable() {
        assert_eq!(parse_continuation_number("q1"), Some(1));
        assert_eq!(parse_continuation_number("q17"), Some(17));
        assert_eq!(parse_continuation_number("q999999"), Some(999_999));
        assert_eq!(parse_continuation_number("q1000000"), Some(1_000_000));
        assert_eq!(parse_continuation_number("q0"), None);
        assert_eq!(parse_continuation_number("q01"), None);
        assert_eq!(parse_continuation_number("Q1"), None);
        assert_eq!(parse_continuation_number("q1a"), None);
    }

    #[test]
    fn continuation_pruning_keeps_the_newest_bounded_window() {
        let directory = tempfile::tempdir().expect("continuation root");
        for number in 1..=130 {
            fs::write(directory.path().join(format!("q{number}.json")), b"{}")
                .expect("continuation fixture");
        }
        fs::write(directory.path().join("unmanaged.txt"), b"keep").expect("unmanaged fixture");
        prune_continuations(directory.path(), 130).expect("bounded prune");
        assert!(!directory.path().join("q1.json").exists());
        assert!(!directory.path().join("q2.json").exists());
        assert!(directory.path().join("q3.json").exists());
        assert!(directory.path().join("q130.json").exists());
        assert!(directory.path().join("unmanaged.txt").exists());
        assert_eq!(
            next_continuation_number(directory.path()).expect("next handle"),
            131
        );
    }

    #[test]
    fn continuation_numbers_wrap_without_overwriting_the_active_window() {
        let directory = tempfile::tempdir().expect("continuation root");
        let first_active = MAX_CONTINUATION_NUMBER - MAX_CONTINUATION_ENTRIES as u64 + 1;
        for number in first_active..=MAX_CONTINUATION_NUMBER {
            fs::write(directory.path().join(format!("q{number}.json")), b"{}")
                .expect("continuation fixture");
        }
        assert_eq!(
            next_continuation_number(directory.path()).expect("wrapped handle"),
            1
        );

        fs::write(directory.path().join("q1.json"), b"{}").expect("wrapped fixture");
        prune_continuations(directory.path(), 1).expect("wrapped prune");
        assert!(!directory
            .path()
            .join(format!("q{first_active}.json"))
            .exists());
        assert!(directory.path().join("q1.json").exists());
        assert_eq!(
            next_continuation_number(directory.path()).expect("next wrapped handle"),
            2
        );
        assert_eq!(
            fs::read_dir(directory.path())
                .expect("continuation entries")
                .filter_map(Result::ok)
                .count(),
            MAX_CONTINUATION_ENTRIES
        );
    }

    #[test]
    fn continuation_pruning_ages_out_legacy_seven_digit_records_first() {
        let directory = tempfile::tempdir().expect("continuation root");
        for number in 1_000_000..1_000_128 {
            fs::write(directory.path().join(format!("q{number}.json")), b"{}")
                .expect("legacy continuation fixture");
        }
        fs::write(directory.path().join("q1.json"), b"{}").expect("bounded fixture");
        prune_continuations(directory.path(), 1).expect("legacy prune");
        assert!(!directory.path().join("q1000000.json").exists());
        assert!(directory.path().join("q1000001.json").exists());
        assert!(directory.path().join("q1.json").exists());
    }

    #[test]
    fn snapshot_pruning_ignores_the_continuation_namespace() {
        let directory = tempfile::tempdir().expect("query spool");
        let continuations = directory.path().join("continuations");
        fs::create_dir(&continuations).expect("continuation namespace");
        for number in 0..=MAX_SPOOL_ENTRIES {
            fs::create_dir(directory.path().join(format!("{number:032x}")))
                .expect("snapshot fixture");
        }
        prune_spool(directory.path()).expect("snapshot prune");
        let snapshots = fs::read_dir(directory.path())
            .expect("spool entries")
            .filter_map(Result::ok)
            .filter(|entry| valid_snapshot_id(&entry.file_name().to_string_lossy()))
            .count();
        assert_eq!(snapshots, MAX_SPOOL_ENTRIES);
        assert!(continuations.exists());
    }

    #[test]
    fn nul_paths_are_normalized_without_sampling() {
        let paths = parse_nul_paths(b"./src/a.ts\0unicode/\xE6\x96\x87\xE4\xBB\xB6.txt\0")
            .expect("valid NUL paths");
        assert_eq!(vec!["src/a.ts", "unicode/文件.txt"], paths);
    }

    #[test]
    fn vimgrep_parser_preserves_windows_drive_and_colons_in_text() {
        assert_eq!(
            Some(("C:\\repo\\a.rs", 12, 7, "value:more")),
            split_vimgrep("C:\\repo\\a.rs:12:7:value:more")
        );
    }
}
