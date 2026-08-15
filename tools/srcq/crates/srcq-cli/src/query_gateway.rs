//! Native-argv-compatible rg/fd gateway. AST commands deliberately remain in their existing path.

use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsString,
    fs,
    io::{self, Cursor, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::SystemTime,
};

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use srcq_core::{
    codec::write_yaml_document,
    process::{run, CancellationToken, PreparedOutput, ProcessRequest, StdinMode},
};

use crate::{GatewayBackend, GatewayCommand, GatewayOperation};

const MAX_STDOUT_BYTES: u64 = 256 * 1024 * 1024;
const MAX_STDERR_BYTES: u64 = 16 * 1024 * 1024;
const MAX_SPOOL_ENTRIES: usize = 32;

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
        GatewayOperation::Doctor => execute_doctor(command.backend, &engine, &cwd),
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
    }
}

fn backend_name(backend: GatewayBackend) -> &'static str {
    match backend {
        GatewayBackend::Rg => "rg",
        GatewayBackend::Fd => "fd",
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

fn execute_doctor(backend: GatewayBackend, engine: &Path, cwd: &Path) -> Result<i32, GatewayError> {
    let version = native_version(engine, cwd)?
        .lines()
        .next()
        .unwrap_or("unknown")
        .to_owned();
    let expected = match backend {
        GatewayBackend::Rg => "ripgrep 15.1.0",
        GatewayBackend::Fd => "fd 10.4.2",
    };
    let ok = version
        .lines()
        .next()
        .is_some_and(|line| line.trim().starts_with(expected));
    let value = json!({"_sgy":{"schema":"sgy.query.doctor/v1","backend":backend_name(backend),"ok":ok},"engine":engine,"cwd":cwd,"observed_version":version.trim(),"expected_version":expected});
    emit_yaml(&value)?;
    Ok(if ok { 0 } else { 1 })
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
    emit_yaml(&value)?;
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
    let version = native_version(engine, cwd)?;
    if !supported_version(command.backend, &version) {
        return Err(GatewayError::input(format!(
            "unsupported {} version: {}; run srcq {} doctor",
            backend_name(command.backend),
            version.lines().next().unwrap_or("unknown"),
            backend_name(command.backend)
        )));
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
            return Err(GatewayError::input(format!("{} requires --artifact-out because native bytes are not a safe model-visible text channel", mode.id)));
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
        emit_yaml(
            &json!({"_sgy":{"schema":"sgy.query.artifact/v1","backend":backend_name(command.backend),"mode":mode.id},"artifact":prepared.path(),"bytes":bytes,"sha256":sha256_hex(&captured.stdout),"native_exit":captured.native_exit,"stderr_bytes":captured.stderr.len()}),
        )?;
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
            emit_yaml(
                &json!({"_sgy":{"schema":"sgy.query.artifact/v1","backend":backend_name(command.backend),"mode":mode.id},"artifact":prepared.path(),"bytes":captured.stdout.len(),"sha256":sha256_hex(&captured.stdout),"native_exit":captured.native_exit}),
            )?;
        } else if command.view == "raw" {
            io::stdout()
                .lock()
                .write_all(&captured.stdout)
                .map_err(|error| GatewayError::io("cannot write native stdout", error))?;
        } else {
            emit_bounded_text(command, mode, &captured)?;
        }
        return Ok(captured.native_exit);
    }

    let version = version.lines().next().unwrap_or("unknown").to_owned();
    let query_fingerprint =
        query_fingerprint(command.backend, engine, cwd, &command.native_argv, &version);
    let fresh_snapshot = command.snapshot.is_none();
    let mut snapshot = if let Some(id) = command.snapshot.as_deref() {
        let loaded = load_snapshot(id)?;
        if loaded.query_fingerprint != query_fingerprint {
            return Err(GatewayError::input(
                "snapshot does not belong to the current backend/cwd/native argv",
            ));
        }
        loaded
    } else {
        if command.after.is_some() {
            return Err(GatewayError::input(
                "--after requires --snapshot from the previous page",
            ));
        }
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
    let projection = match command.backend {
        GatewayBackend::Fd => render_fd(&rendering, cwd, &snapshot, offset)?,
        GatewayBackend::Rg
            if matches!(
                mode.id,
                "RG-FILES" | "RG-FILES-WITH-MATCHES" | "RG-FILES-WITHOUT-MATCH"
            ) =>
        {
            render_rg_files(&rendering, &snapshot, offset)?
        }
        GatewayBackend::Rg if matches!(mode.id, "RG-COUNT" | "RG-COUNT-MATCHES") => {
            render_rg_counts(&rendering, &snapshot, offset)?
        }
        GatewayBackend::Rg if mode.id == "RG-VIMGREP" => {
            render_rg_vimgrep(&rendering, &snapshot, offset)?
        }
        GatewayBackend::Rg => render_rg(&rendering, &snapshot, offset)?,
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
    };
    let content_complete = match command.backend {
        GatewayBackend::Fd => projection.view != "summary" || projection.total == 0,
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

fn supported_version(backend: GatewayBackend, version: &str) -> bool {
    let expected = match backend {
        GatewayBackend::Rg => "ripgrep 15.1.0",
        GatewayBackend::Fd => "fd 10.4.2",
    };
    version
        .lines()
        .next()
        .is_some_and(|line| line.trim().starts_with(expected))
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
                && !entry.file_name().to_string_lossy().starts_with('.')
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
    if id.len() != 32 || !id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(GatewayError::input(
            "snapshot id must be 32 hexadecimal characters",
        ));
    }
    let directory = spool_root()?.join(id);
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
    let end = paths.len().min(offset.saturating_add(command.limit));
    let page = &paths[offset..end];
    let flat = json!({"paths":page.iter().map(|path| json!({"path":path,"type":snapshot.fd_types.get(path).map(String::as_str).unwrap_or("unknown")})).collect::<Vec<_>>()});
    let tree = render_fd_tree(
        page,
        &snapshot.fd_types,
        &fd_roots(&command.native_argv, cwd),
    );
    let chosen = match command.view.as_str() {
        "auto" => {
            if estimated_tokens(&tree) < estimated_tokens(&flat) {
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
    let value = match chosen {
        "tree" => tree,
        _ => flat,
    };
    Ok(Projection {
        value,
        displayed: page.len(),
        total: paths.len(),
        view: chosen.to_owned(),
        display_complete: end >= paths.len(),
    })
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
    let end = files.len().min(offset.saturating_add(command.limit));
    let page = &files[offset..end];
    let chosen = if command.view == "lossless" {
        "lossless"
    } else {
        "files"
    };
    Ok(Projection {
        value: json!({"files":page}),
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
    let end = records.len().min(offset.saturating_add(command.limit));
    let page = &records[offset..end];
    let chosen = if command.view == "lossless" {
        "lossless"
    } else {
        "counts"
    };
    Ok(Projection {
        value: json!({"counts":page}),
        displayed: page.len(),
        total: records.len(),
        view: chosen.to_owned(),
        display_complete: end >= records.len(),
    })
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
    let end = records.len().min(offset.saturating_add(command.limit));
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
        displayed: page.len(),
        total: records.len(),
        view: chosen.to_owned(),
        display_complete: end >= records.len(),
    })
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
    captured: &Captured,
) -> Result<(), GatewayError> {
    let text = std::str::from_utf8(&captured.stdout)
        .map_err(|_| GatewayError::input("native output was not UTF-8; use --artifact-out"))?;
    let lines = text.lines().collect::<Vec<_>>();
    let displayed = lines
        .iter()
        .take(command.limit)
        .map(|line| truncate_chars(line, command.max_text_chars))
        .collect::<Vec<_>>();
    let text_complete = lines
        .iter()
        .take(command.limit)
        .all(|line| line.chars().count() <= command.max_text_chars);
    let display_complete = displayed.len() == lines.len();
    let receipt = if command.receipt == "full" {
        json!({
            "schema":"sgy.query.bounded-text/v1","backend":backend_name(command.backend),
            "mode":mode.id,"native_exit":captured.native_exit,"total_lines":lines.len(),
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
        if captured.native_exit != 0 {
            receipt.insert("native_exit".to_owned(), json!(captured.native_exit));
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
        return Ok(Projection {
            value: json!({"summary":{"events":events.len(),"matches":matches,"files":events.iter().filter(|event| event["type"] == "match").filter_map(|event| event["path"].as_str()).collect::<BTreeSet<_>>().len()}}),
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
        let end = locations.len().min(offset.saturating_add(command.limit));
        return Ok(Projection {
            value: json!({"locations":&locations[offset..end]}),
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
    let end = events.len().min(offset.saturating_add(command.limit));
    let page = &events[offset..end];
    let grouped = render_rg_grouped(page, command.max_text_chars);
    let records = render_rg_records(page, command.max_text_chars);
    let chosen = match command.view.as_str() {
        "auto" => {
            if estimated_tokens(&grouped) <= estimated_tokens(&records) {
                "grouped"
            } else {
                "records"
            }
        }
        "grouped" => "grouped",
        "records" => "records",
        other => other,
    };
    let value = match chosen {
        "grouped" => grouped,
        "records" => records,
        _ => grouped,
    };
    Ok(Projection {
        value,
        displayed: page.len(),
        total: events.len(),
        view: chosen.to_owned(),
        display_complete: end >= events.len(),
    })
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

fn estimated_tokens(value: &Value) -> usize {
    let mut yaml = Vec::new();
    if write_yaml_document(value, &mut yaml, false).is_err() {
        return usize::MAX;
    }
    let text = String::from_utf8_lossy(&yaml);
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
        if !character.is_whitespace() {
            total += 1;
        }
    }
    total + ascii_word.div_ceil(4)
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
            args(&["-F", "--json", "--color=never", "--", "-needle", "."]),
            effective_argv(
                &args(&["-F", "--", "-needle", "."]),
                &args(&["--json", "--color=never"])
            )
        );
    }

    #[test]
    fn covers_every_documented_rg_and_fd_primary_selector() {
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
