//! Terminal and protocol passthrough channels that deliberately bypass YAML/profile/cache.

use std::{
    ffi::OsString,
    fs::File,
    io::{self, IsTerminal, Read, Write},
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc,
    },
    thread,
    time::{Duration, Instant, SystemTime},
};

use command_group::{CommandGroup, GroupChild};
use serde_json::{Map, Value};
use tempfile::{NamedTempFile, TempDir};
use thiserror::Error;

use crate::{
    cache::hash_argv,
    codec::{write_yaml_document, CodecError},
    process::{
        cancellation_from_exit_status, CancellationKind, CancellationReport, CancellationToken,
        OutputCommitError, PreparedOutput, ProcessRequest, TerminationStage,
    },
};

pub const LSP_META_SCHEMA: &str = "sgy.protocol-meta/v1";
pub const TTY_META_SCHEMA: &str = "srcq.execution-meta/v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PassthroughChannel {
    Batch,
    Tty,
    Lsp,
}

impl PassthroughChannel {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Batch => "batch",
            Self::Tty => "tty",
            Self::Lsp => "lsp",
        }
    }

    const fn schema(self) -> &'static str {
        match self {
            Self::Batch | Self::Tty => TTY_META_SCHEMA,
            Self::Lsp => LSP_META_SCHEMA,
        }
    }
}

#[derive(Debug, Error)]
pub enum PassthroughError {
    #[error("E_TTY_UNAVAILABLE: interactive command requires terminal stdin and stdout")]
    TtyUnavailable,
    #[error("cannot create private LSP stderr staging: {0}")]
    Staging(#[source] io::Error),
    #[error("cannot spawn native engine {program}: {source}")]
    Spawn {
        program: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("native LSP process pipe {stream} is unavailable")]
    MissingPipe { stream: &'static str },
    #[error("LSP client stdout disconnected: {0}")]
    ClientDisconnected(#[source] io::Error),
    #[error("native passthrough {operation} failed: {source}")]
    Io {
        operation: &'static str,
        #[source]
        source: io::Error,
    },
    #[error("native passthrough {stream} pump thread failed")]
    PumpPanic { stream: &'static str },
}

impl PassthroughError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::TtyUnavailable => 125,
            Self::Staging(_)
            | Self::Spawn { .. }
            | Self::MissingPipe { .. }
            | Self::ClientDisconnected(_)
            | Self::Io { .. }
            | Self::PumpPanic { .. } => 126,
        }
    }
}

#[derive(Debug, Error)]
pub enum MetadataError {
    #[error("cannot format passthrough timestamp: {0}")]
    Time(String),
    #[error(transparent)]
    Codec(#[from] CodecError),
    #[error(transparent)]
    Commit(#[from] OutputCommitError),
}

impl MetadataError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        127
    }
}

#[derive(Debug)]
pub struct TtyOutcome {
    pub native_status: ExitStatus,
    pub cancellation: Option<CancellationReport>,
}

impl TtyOutcome {
    #[must_use]
    pub fn exit_code(&self) -> i32 {
        visible_exit_code(self.native_status, self.cancellation)
    }
}

#[derive(Debug)]
pub struct LspOutcome {
    _directory: TempDir,
    stderr: NamedTempFile,
    pub native_status: ExitStatus,
    pub cancellation: Option<CancellationReport>,
    pub stdin_bytes: u64,
    pub stdout_bytes: u64,
    pub stderr_bytes: u64,
}

impl LspOutcome {
    #[must_use]
    pub fn stderr_path(&self) -> &Path {
        self.stderr.path()
    }

    #[must_use]
    pub fn exit_code(&self) -> i32 {
        visible_exit_code(self.native_status, self.cancellation)
    }
}

#[derive(Debug)]
pub struct MetadataRequest<'a> {
    pub output: &'a PreparedOutput,
    pub channel: PassthroughChannel,
    pub engine_version: &'a str,
    pub user_argv: &'a [OsString],
    pub effective_argv: &'a [OsString],
    pub started_at: SystemTime,
    pub ended_at: SystemTime,
    pub native_exit_code: Option<i32>,
    pub cancelled: bool,
    pub stdin_bytes: Option<u64>,
    pub stdout_bytes: Option<u64>,
    pub stderr_bytes: Option<u64>,
    pub wrapper_error_origin: Option<&'a str>,
}

pub fn commit_metadata(request: MetadataRequest<'_>) -> Result<(), MetadataError> {
    let mut value = Map::new();
    value.insert(
        "schema".to_owned(),
        Value::String(request.channel.schema().to_owned()),
    );
    value.insert(
        "channel".to_owned(),
        Value::String(request.channel.as_str().to_owned()),
    );
    value.insert(
        "engine_version".to_owned(),
        Value::String(request.engine_version.to_owned()),
    );
    value.insert(
        "user_argv_sha256".to_owned(),
        Value::String(hash_argv(request.user_argv)),
    );
    value.insert(
        "effective_argv_sha256".to_owned(),
        Value::String(hash_argv(request.effective_argv)),
    );
    value.insert(
        "started_at".to_owned(),
        Value::String(format_time(request.started_at)?),
    );
    value.insert(
        "ended_at".to_owned(),
        Value::String(format_time(request.ended_at)?),
    );
    value.insert(
        "native_exit_code".to_owned(),
        request.native_exit_code.map_or(Value::Null, Value::from),
    );
    value.insert("cancelled".to_owned(), Value::Bool(request.cancelled));
    for (name, bytes) in [
        ("stdin_bytes", request.stdin_bytes),
        ("stdout_bytes", request.stdout_bytes),
        ("stderr_bytes", request.stderr_bytes),
    ] {
        if let Some(bytes) = bytes {
            value.insert(name.to_owned(), Value::from(bytes));
        }
    }
    if let Some(origin) = request.wrapper_error_origin {
        value.insert(
            "wrapper_error_origin".to_owned(),
            Value::String(origin.to_owned()),
        );
    }
    let mut encoded = Vec::new();
    write_yaml_document(&Value::Object(value), &mut encoded, false)?;
    request.output.commit_from_reader(encoded.as_slice())?;
    Ok(())
}

fn format_time(value: SystemTime) -> Result<String, MetadataError> {
    Ok(humantime::format_rfc3339(value).to_string())
}

/// Runs an interactive native command on the caller's existing terminal/PTY.
///
/// No pipe, parser, tee, cache, or serializer is placed between the terminal and child.
pub fn run_tty(request: ProcessRequest) -> Result<TtyOutcome, PassthroughError> {
    if !io::stdin().is_terminal() || !io::stdout().is_terminal() {
        return Err(PassthroughError::TtyUnavailable);
    }
    let mut command = Command::new(&request.program);
    command
        .args(&request.args)
        .current_dir(&request.cwd)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    run_tty_platform(command, &request)
}

fn run_tty_platform(
    mut command: Command,
    request: &ProcessRequest,
) -> Result<TtyOutcome, PassthroughError> {
    let mut child = command
        .group()
        .kill_on_drop(true)
        .spawn()
        .map_err(|source| PassthroughError::Spawn {
            program: request.program.clone(),
            source,
        })?;
    let (native_status, cancellation) = supervise_group(
        &mut child,
        &request.cancellation,
        request.poll_interval,
        request.grace_period,
        &mpsc::channel().1,
    )?;
    Ok(TtyOutcome {
        native_status,
        cancellation,
    })
}

/// Runs the native LSP as an opaque binary proxy with bounded 64 KiB copy buffers.
pub fn run_lsp(request: ProcessRequest) -> Result<LspOutcome, PassthroughError> {
    let directory = tempfile::Builder::new()
        .prefix("srcq-lsp-")
        .tempdir()
        .map_err(PassthroughError::Staging)?;
    let stderr = NamedTempFile::new_in(directory.path()).map_err(PassthroughError::Staging)?;

    let mut command = Command::new(&request.program);
    command
        .args(&request.args)
        .current_dir(&request.cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = spawn_group(&mut command).map_err(|source| PassthroughError::Spawn {
        program: request.program.clone(),
        source,
    })?;
    let child_stdin = child
        .inner()
        .stdin
        .take()
        .ok_or(PassthroughError::MissingPipe { stream: "stdin" })?;
    let child_stdout = child
        .inner()
        .stdout
        .take()
        .ok_or(PassthroughError::MissingPipe { stream: "stdout" })?;
    let child_stderr = child
        .inner()
        .stderr
        .take()
        .ok_or(PassthroughError::MissingPipe { stream: "stderr" })?;
    let stderr_file = stderr.reopen().map_err(PassthroughError::Staging)?;

    let stdin_bytes = Arc::new(AtomicU64::new(0));
    let (errors_tx, errors_rx) = mpsc::channel();
    let stdin_thread = spawn_lsp_stdin(child_stdin, Arc::clone(&stdin_bytes), errors_tx.clone())?;
    let stdout_thread = spawn_lsp_stdout(child_stdout, errors_tx.clone())?;
    let stderr_thread = spawn_lsp_stderr(child_stderr, stderr_file, errors_tx.clone())?;
    drop(errors_tx);

    let supervision = supervise_group(
        &mut child,
        &request.cancellation,
        request.poll_interval,
        request.grace_period,
        &errors_rx,
    );
    // A server can leave descendants holding inherited pipes. Closing the group after the
    // leader exits keeps drain/join bounded without altering the leader's captured status.
    let _ = child.kill();
    let _ = child.wait();

    let stdout_bytes = join_pump(stdout_thread, "stdout")?;
    let stderr_bytes = join_pump(stderr_thread, "stderr")?;
    if stdin_thread.is_finished() {
        stdin_thread
            .join()
            .map_err(|_| PassthroughError::PumpPanic { stream: "stdin" })?;
    } else {
        // Parent stdin may remain open after a valid LSP `exit`. The CLI process is about to
        // terminate, so detaching avoids deadlocking while OS teardown closes the pipe.
        drop(stdin_thread);
    }
    if let Ok(error) = errors_rx.try_recv() {
        return Err(error.into_error());
    }
    let (native_status, cancellation) = supervision?;
    Ok(LspOutcome {
        _directory: directory,
        stderr,
        native_status,
        cancellation,
        stdin_bytes: stdin_bytes.load(Ordering::Acquire),
        stdout_bytes,
        stderr_bytes,
    })
}

#[derive(Debug)]
enum PumpFailure {
    Stdin(io::Error),
    Stdout(io::Error),
    Stderr(io::Error),
}

impl PumpFailure {
    fn into_error(self) -> PassthroughError {
        match self {
            Self::Stdout(error) if error.kind() == io::ErrorKind::BrokenPipe => {
                PassthroughError::ClientDisconnected(error)
            }
            Self::Stdin(error) => PassthroughError::Io {
                operation: "read client stdin/write child stdin",
                source: error,
            },
            Self::Stdout(error) => PassthroughError::Io {
                operation: "read child stdout/write client stdout",
                source: error,
            },
            Self::Stderr(error) => PassthroughError::Io {
                operation: "forward child stderr",
                source: error,
            },
        }
    }
}

fn spawn_lsp_stdin(
    mut child: std::process::ChildStdin,
    bytes: Arc<AtomicU64>,
    errors: mpsc::Sender<PumpFailure>,
) -> Result<thread::JoinHandle<()>, PassthroughError> {
    thread::Builder::new()
        .name("srcq-lsp-stdin".to_owned())
        .spawn(move || {
            let mut input = io::stdin().lock();
            let mut buffer = [0_u8; 64 * 1024];
            loop {
                let count = match input.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(count) => count,
                    Err(error) => {
                        let _ = errors.send(PumpFailure::Stdin(error));
                        return;
                    }
                };
                if let Err(error) = child.write_all(&buffer[..count]) {
                    if error.kind() != io::ErrorKind::BrokenPipe {
                        let _ = errors.send(PumpFailure::Stdin(error));
                    }
                    return;
                }
                bytes.fetch_add(u64::try_from(count).unwrap_or(u64::MAX), Ordering::AcqRel);
            }
            let _ = child.flush();
            // Dropping child stdin is the protocol EOF boundary.
        })
        .map_err(|source| PassthroughError::Io {
            operation: "start LSP stdin pump",
            source,
        })
}

fn spawn_lsp_stdout(
    mut child: std::process::ChildStdout,
    errors: mpsc::Sender<PumpFailure>,
) -> Result<thread::JoinHandle<u64>, PassthroughError> {
    thread::Builder::new()
        .name("srcq-lsp-stdout".to_owned())
        .spawn(move || {
            let mut output = io::stdout().lock();
            match copy_exact(&mut child, &mut output) {
                Ok(bytes) => bytes,
                Err(error) => {
                    let _ = errors.send(PumpFailure::Stdout(error));
                    0
                }
            }
        })
        .map_err(|source| PassthroughError::Io {
            operation: "start LSP stdout pump",
            source,
        })
}

fn spawn_lsp_stderr(
    mut child: std::process::ChildStderr,
    mut staging: File,
    errors: mpsc::Sender<PumpFailure>,
) -> Result<thread::JoinHandle<u64>, PassthroughError> {
    thread::Builder::new()
        .name("srcq-lsp-stderr".to_owned())
        .spawn(move || {
            let mut total = 0_u64;
            let mut buffer = [0_u8; 64 * 1024];
            loop {
                let count = match child.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(count) => count,
                    Err(error) => {
                        let _ = errors.send(PumpFailure::Stderr(error));
                        return 0;
                    }
                };
                let result = staging.write_all(&buffer[..count]).and_then(|()| {
                    let mut destination = io::stderr().lock();
                    destination.write_all(&buffer[..count])?;
                    destination.flush()
                });
                if let Err(error) = result {
                    let _ = errors.send(PumpFailure::Stderr(error));
                    return 0;
                }
                total = total.saturating_add(u64::try_from(count).unwrap_or(u64::MAX));
            }
            if let Err(error) = staging.flush().and_then(|()| staging.sync_all()) {
                let _ = errors.send(PumpFailure::Stderr(error));
                return 0;
            }
            total
        })
        .map_err(|source| PassthroughError::Io {
            operation: "start LSP stderr pump",
            source,
        })
}

fn copy_exact(reader: &mut impl Read, writer: &mut impl Write) -> io::Result<u64> {
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            writer.flush()?;
            return Ok(total);
        }
        writer.write_all(&buffer[..count])?;
        writer.flush()?;
        total = total.saturating_add(u64::try_from(count).unwrap_or(u64::MAX));
    }
}

fn join_pump(
    thread: thread::JoinHandle<u64>,
    stream: &'static str,
) -> Result<u64, PassthroughError> {
    thread
        .join()
        .map_err(|_| PassthroughError::PumpPanic { stream })
}

fn supervise_group(
    child: &mut GroupChild,
    cancellation: &CancellationToken,
    poll_interval: Duration,
    grace_period: Duration,
    pump_errors: &mpsc::Receiver<PumpFailure>,
) -> Result<(ExitStatus, Option<CancellationReport>), PassthroughError> {
    loop {
        if let Ok(error) = pump_errors.try_recv() {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error.into_error());
        }
        if let Some(reason) = cancellation.reason() {
            let (status, final_stage) =
                terminate_group(child, reason, poll_interval, grace_period)?;
            return Ok((
                status,
                Some(CancellationReport {
                    reason,
                    final_stage,
                }),
            ));
        }
        if let Some(status) = child.try_wait().map_err(|source| PassthroughError::Io {
            operation: "wait for native passthrough process",
            source,
        })? {
            let cancellation = cancellation_from_exit_status(&status);
            return Ok((status, cancellation));
        }
        thread::sleep(poll_interval);
    }
}

fn terminate_group(
    child: &mut GroupChild,
    reason: CancellationKind,
    poll_interval: Duration,
    grace_period: Duration,
) -> Result<(ExitStatus, TerminationStage), PassthroughError> {
    send_group_graceful(child, reason)?;
    if let Some(status) = wait_group(child, poll_interval, grace_period)? {
        return Ok((status, TerminationStage::Graceful));
    }
    child.kill().map_err(|source| PassthroughError::Io {
        operation: "kill passthrough process group",
        source,
    })?;
    let status = child.wait().map_err(|source| PassthroughError::Io {
        operation: "wait after passthrough process-group kill",
        source,
    })?;
    Ok((status, TerminationStage::Kill))
}

fn send_group_graceful(
    _child: &GroupChild,
    _reason: CancellationKind,
) -> Result<(), PassthroughError> {
    // Console Ctrl+C/Break is broadcast to wrapper and child. The Job Object is terminated
    // after the bounded grace period if the native server does not exit.
    Ok(())
}

fn wait_group(
    child: &mut GroupChild,
    poll_interval: Duration,
    timeout: Duration,
) -> Result<Option<ExitStatus>, PassthroughError> {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait().map_err(|source| PassthroughError::Io {
            operation: "wait during passthrough cancellation",
            source,
        })? {
            return Ok(Some(status));
        }
        if Instant::now() >= deadline {
            return Ok(None);
        }
        thread::sleep(poll_interval);
    }
}

fn spawn_group(command: &mut Command) -> io::Result<GroupChild> {
    command.group().kill_on_drop(true).spawn()
}

fn visible_exit_code(native_status: ExitStatus, cancellation: Option<CancellationReport>) -> i32 {
    if let Some(cancellation) = cancellation {
        return cancellation.reason.exit_code();
    }
    if let Some(code) = native_status.code() {
        return code;
    }
    126
}

#[cfg(test)]
mod tests {
    use std::{ffi::OsString, time::SystemTime};

    use tempfile::tempdir;

    use super::{commit_metadata, MetadataRequest, PassthroughChannel};
    use crate::{codec::parse_yaml_documents, process::PreparedOutput};

    #[test]
    fn metadata_contains_only_bounded_protocol_fields() {
        let directory = tempdir().expect("temporary directory");
        let path = directory.path().join("meta.yaml");
        let output = PreparedOutput::prepare(&path).expect("prepare metadata");
        let user = vec![OsString::from("lsp"), OsString::from("secret-pattern")];
        let effective = user.clone();
        commit_metadata(MetadataRequest {
            output: &output,
            channel: PassthroughChannel::Lsp,
            engine_version: "0.42.0",
            user_argv: &user,
            effective_argv: &effective,
            started_at: SystemTime::UNIX_EPOCH,
            ended_at: SystemTime::UNIX_EPOCH,
            native_exit_code: Some(0),
            cancelled: false,
            stdin_bytes: Some(12),
            stdout_bytes: Some(34),
            stderr_bytes: Some(0),
            wrapper_error_origin: None,
        })
        .expect("commit metadata");
        let bytes = std::fs::read(path).expect("read metadata");
        let documents = parse_yaml_documents(&bytes).expect("parse metadata");
        let value = &documents[0];
        assert_eq!(value["schema"], "sgy.protocol-meta/v1");
        assert_eq!(value["stdin_bytes"], 12);
        assert_eq!(value["stdout_bytes"], 34);
        let text = String::from_utf8(bytes).expect("UTF-8 metadata");
        assert!(!text.contains("secret-pattern"));
        for forbidden in ["method", "uri", "body", "environment", "cwd"] {
            assert!(!value.as_object().expect("mapping").contains_key(forbidden));
        }
    }
}
