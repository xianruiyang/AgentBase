use std::{
    ffi::OsString,
    fs::File,
    io::{self, Read, Write},
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

use command_group::{CommandGroup, GroupChild};
use tempfile::{NamedTempFile, TempDir};
use thiserror::Error;

use super::{CancellationKind, CancellationToken};

const DEFAULT_POLL_INTERVAL: Duration = Duration::from_millis(10);
const DEFAULT_GRACE_PERIOD: Duration = Duration::from_secs(2);

#[derive(Debug)]
pub enum StdinMode {
    Null,
    /// Gives the native child the exact parent standard-input handle. This avoids an
    /// uninterruptible wrapper-side reader and preserves binary/EOF behavior.
    Inherit,
    /// Test/embedding input copied asynchronously to a pipe, then closed to deliver EOF.
    Bytes(Vec<u8>),
}

/// A shell-free process request. Environment variables are inherited without persistence.
#[derive(Debug)]
pub struct ProcessRequest {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    pub stdin: StdinMode,
    pub forward_stderr: bool,
    pub cancellation: CancellationToken,
    pub poll_interval: Duration,
    pub grace_period: Duration,
    /// Optional wall-clock limit for the native process. Expiry terminates the process group.
    pub timeout: Option<Duration>,
    /// Optional hard capture bounds. Crossing either bound terminates the native process group.
    pub max_stdout_bytes: Option<u64>,
    pub max_stderr_bytes: Option<u64>,
}

impl ProcessRequest {
    #[must_use]
    pub fn new(program: impl Into<PathBuf>, cwd: impl Into<PathBuf>) -> Self {
        Self {
            program: program.into(),
            args: Vec::new(),
            cwd: cwd.into(),
            stdin: StdinMode::Null,
            forward_stderr: true,
            cancellation: CancellationToken::new(),
            poll_interval: DEFAULT_POLL_INTERVAL,
            grace_period: DEFAULT_GRACE_PERIOD,
            timeout: None,
            max_stdout_bytes: None,
            max_stderr_bytes: None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminationStage {
    Graceful,
    Kill,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CancellationReport {
    pub reason: CancellationKind,
    pub final_stage: TerminationStage,
}

pub(crate) fn cancellation_from_exit_status(status: &ExitStatus) -> Option<CancellationReport> {
    const STATUS_CONTROL_C_EXIT: i32 = -1_073_741_510;
    if status.code() == Some(STATUS_CONTROL_C_EXIT) {
        return Some(CancellationReport {
            reason: CancellationKind::CtrlC,
            final_stage: TerminationStage::Graceful,
        });
    }
    None
}

/// Captured native byte streams held in a user-private OS temporary directory.
#[derive(Debug)]
pub struct ProcessOutput {
    _directory: TempDir,
    stdout: NamedTempFile,
    stderr: NamedTempFile,
    pub stdout_bytes: u64,
    pub stderr_bytes: u64,
}

impl ProcessOutput {
    #[must_use]
    pub fn stdout_path(&self) -> &Path {
        self.stdout.path()
    }

    #[must_use]
    pub fn stderr_path(&self) -> &Path {
        self.stderr.path()
    }

    pub fn open_stdout(&self) -> io::Result<File> {
        File::open(self.stdout.path())
    }

    pub fn open_stderr(&self) -> io::Result<File> {
        File::open(self.stderr.path())
    }

    pub fn read_stdout(&self) -> io::Result<Vec<u8>> {
        std::fs::read(self.stdout.path())
    }

    pub fn read_stderr(&self) -> io::Result<Vec<u8>> {
        std::fs::read(self.stderr.path())
    }
}

#[derive(Debug)]
pub struct ProcessOutcome {
    pub native_status: ExitStatus,
    pub cancellation: Option<CancellationReport>,
    pub output: ProcessOutput,
}

impl ProcessOutcome {
    /// Returns the wrapper-visible code while retaining the raw native status separately.
    #[must_use]
    pub fn exit_code(&self) -> i32 {
        if let Some(cancellation) = self.cancellation {
            return cancellation.reason.exit_code();
        }
        if let Some(code) = self.native_status.code() {
            return code;
        }
        126
    }
}

#[derive(Debug, Error)]
pub enum ProcessError {
    #[error("cannot create private process staging: {0}")]
    Staging(#[source] io::Error),
    #[error("cannot spawn native engine {program}: {source}")]
    Spawn {
        program: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("native process pipe {stream} is unavailable")]
    MissingPipe { stream: &'static str },
    #[error("native process {operation} failed: {source}")]
    Io {
        operation: &'static str,
        #[source]
        source: io::Error,
    },
    #[error("native process {stream} pump thread failed")]
    PumpPanic { stream: &'static str },
    #[error("native process exceeded its {timeout:?} wall-clock limit")]
    Timeout { timeout: Duration },
}

impl ProcessError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Timeout { .. } => 124,
            _ => 126,
        }
    }
}

pub fn run(request: ProcessRequest) -> Result<ProcessOutcome, ProcessError> {
    let directory = tempfile::Builder::new()
        .prefix("srcq-process-")
        .tempdir()
        .map_err(ProcessError::Staging)?;
    let stdout = NamedTempFile::new_in(directory.path()).map_err(ProcessError::Staging)?;
    let stderr = NamedTempFile::new_in(directory.path()).map_err(ProcessError::Staging)?;

    let mut command = Command::new(&request.program);
    command
        .args(&request.args)
        .current_dir(&request.cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    match &request.stdin {
        StdinMode::Null => {
            command.stdin(Stdio::null());
        }
        StdinMode::Inherit => {
            command.stdin(Stdio::inherit());
        }
        StdinMode::Bytes(_) => {
            command.stdin(Stdio::piped());
        }
    }

    let mut child =
        ChildGuard::new(
            spawn_group(&mut command).map_err(|source| ProcessError::Spawn {
                program: request.program.clone(),
                source,
            })?,
        );

    let child_stdout = child
        .inner()
        .stdout
        .take()
        .ok_or(ProcessError::MissingPipe { stream: "stdout" })?;
    let child_stderr = child
        .inner()
        .stderr
        .take()
        .ok_or(ProcessError::MissingPipe { stream: "stderr" })?;
    let stdout_file = stdout.reopen().map_err(ProcessError::Staging)?;
    let stderr_file = stderr.reopen().map_err(ProcessError::Staging)?;

    let (pump_errors_tx, pump_errors_rx) = mpsc::channel();
    let stdout_thread = spawn_pump(
        "stdout",
        child_stdout,
        stdout_file,
        false,
        request.max_stdout_bytes,
        pump_errors_tx.clone(),
    )?;
    let stderr_thread = spawn_pump(
        "stderr",
        child_stderr,
        stderr_file,
        request.forward_stderr,
        request.max_stderr_bytes,
        pump_errors_tx.clone(),
    )?;

    let stdin_thread = match request.stdin {
        StdinMode::Bytes(bytes) => {
            let stdin = child
                .inner()
                .stdin
                .take()
                .ok_or(ProcessError::MissingPipe { stream: "stdin" })?;
            Some(spawn_stdin(bytes, stdin, pump_errors_tx.clone())?)
        }
        StdinMode::Null | StdinMode::Inherit => None,
    };
    drop(pump_errors_tx);

    let supervision = supervise(
        child.get_mut(),
        &request.cancellation,
        request.poll_interval,
        request.grace_period,
        request.timeout,
        &pump_errors_rx,
    );

    // Closing/terminating the group after its leader exits prevents an inherited pipe in a
    // detached descendant from keeping the drain threads alive. The captured leader status wins.
    child.kill();
    drop(child);

    let stdout_bytes = join_pump(stdout_thread, "stdout")?;
    let stderr_bytes = join_pump(stderr_thread, "stderr")?;
    if let Some(thread) = stdin_thread {
        join_stdin(thread)?;
    }

    if let Ok((stream, source)) = pump_errors_rx.try_recv() {
        return Err(ProcessError::Io {
            operation: stream,
            source,
        });
    }
    let (native_status, cancellation) = supervision?;

    Ok(ProcessOutcome {
        native_status,
        cancellation,
        output: ProcessOutput {
            _directory: directory,
            stdout,
            stderr,
            stdout_bytes,
            stderr_bytes,
        },
    })
}

struct ChildGuard {
    child: GroupChild,
}

impl ChildGuard {
    fn new(child: GroupChild) -> Self {
        Self { child }
    }

    fn get_mut(&mut self) -> &mut GroupChild {
        &mut self.child
    }

    fn kill(&mut self) {
        let _ = self.child.kill();
    }
}

impl std::ops::Deref for ChildGuard {
    type Target = GroupChild;

    fn deref(&self) -> &Self::Target {
        &self.child
    }
}

impl std::ops::DerefMut for ChildGuard {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.child
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        self.kill();
        let _ = self.child.wait();
    }
}

fn spawn_group(command: &mut Command) -> io::Result<GroupChild> {
    command.group().kill_on_drop(true).spawn()
}

type PumpError = (&'static str, io::Error);

fn spawn_pump<R>(
    name: &'static str,
    mut reader: R,
    mut staging: File,
    forward_stderr: bool,
    max_bytes: Option<u64>,
    errors: mpsc::Sender<PumpError>,
) -> Result<thread::JoinHandle<u64>, ProcessError>
where
    R: Read + Send + 'static,
{
    thread::Builder::new()
        .name(format!("srcq-{name}-pump"))
        .spawn(move || {
            let result = if forward_stderr {
                copy_with_optional_stderr(&mut reader, &mut staging, true, max_bytes)
            } else {
                copy_with_optional_stderr(&mut reader, &mut staging, false, max_bytes)
            };
            match result {
                Ok(bytes) => bytes,
                Err(error) => {
                    let _ = errors.send((name, error));
                    0
                }
            }
        })
        .map_err(|source| ProcessError::Io {
            operation: "start output pump",
            source,
        })
}

fn copy_with_optional_stderr(
    reader: &mut impl Read,
    staging: &mut File,
    forward_stderr: bool,
    max_bytes: Option<u64>,
) -> io::Result<u64> {
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            staging.flush()?;
            staging.sync_all()?;
            return Ok(total);
        }
        let next = total + u64::try_from(count).map_err(io::Error::other)?;
        if max_bytes.is_some_and(|limit| next > limit) {
            return Err(io::Error::new(
                io::ErrorKind::FileTooLarge,
                "native output exceeded the configured capture limit",
            ));
        }
        staging.write_all(&buffer[..count])?;
        if forward_stderr {
            let mut destination = io::stderr().lock();
            destination.write_all(&buffer[..count])?;
            destination.flush()?;
        }
        total = next;
    }
}

fn spawn_stdin(
    bytes: Vec<u8>,
    mut stdin: std::process::ChildStdin,
    errors: mpsc::Sender<PumpError>,
) -> Result<thread::JoinHandle<()>, ProcessError> {
    thread::Builder::new()
        .name("srcq-stdin-pump".to_owned())
        .spawn(move || {
            if let Err(error) = stdin.write_all(&bytes) {
                if error.kind() != io::ErrorKind::BrokenPipe {
                    let _ = errors.send(("stdin", error));
                }
            }
            // Dropping the handle is the EOF boundary.
        })
        .map_err(|source| ProcessError::Io {
            operation: "start stdin pump",
            source,
        })
}

fn supervise(
    child: &mut GroupChild,
    cancellation: &CancellationToken,
    poll_interval: Duration,
    grace_period: Duration,
    timeout: Option<Duration>,
    pump_errors: &mpsc::Receiver<PumpError>,
) -> Result<(ExitStatus, Option<CancellationReport>), ProcessError> {
    let deadline = timeout.map(|duration| (Instant::now() + duration, duration));
    loop {
        if let Ok((stream, source)) = pump_errors.try_recv() {
            let _ = child.kill();
            let _ = child.wait();
            return Err(ProcessError::Io {
                operation: stream,
                source,
            });
        }
        if let Some(reason) = cancellation.reason() {
            return terminate(child, reason, poll_interval, grace_period).map(
                |(status, final_stage)| {
                    (
                        status,
                        Some(CancellationReport {
                            reason,
                            final_stage,
                        }),
                    )
                },
            );
        }
        if let Some(status) = child.try_wait().map_err(|source| ProcessError::Io {
            operation: "wait",
            source,
        })? {
            let cancellation = cancellation_from_exit_status(&status);
            return Ok((status, cancellation));
        }
        if let Some((deadline, timeout)) = deadline {
            if Instant::now() >= deadline {
                child.kill().map_err(|source| ProcessError::Io {
                    operation: "kill process group after timeout",
                    source,
                })?;
                child.wait().map_err(|source| ProcessError::Io {
                    operation: "wait after process-group timeout",
                    source,
                })?;
                return Err(ProcessError::Timeout { timeout });
            }
        }
        thread::sleep(poll_interval);
    }
}

fn terminate(
    child: &mut GroupChild,
    reason: CancellationKind,
    poll_interval: Duration,
    grace_period: Duration,
) -> Result<(ExitStatus, TerminationStage), ProcessError> {
    send_graceful(child, reason)?;
    if let Some(status) = wait_until(child, poll_interval, grace_period)? {
        return Ok((status, TerminationStage::Graceful));
    }

    child.kill().map_err(|source| ProcessError::Io {
        operation: "kill process group",
        source,
    })?;
    let status = child.wait().map_err(|source| ProcessError::Io {
        operation: "wait after process-group kill",
        source,
    })?;
    Ok((status, TerminationStage::Kill))
}

fn send_graceful(_child: &GroupChild, _reason: CancellationKind) -> Result<(), ProcessError> {
    // A real console Ctrl+C is broadcast by Windows to both wrapper and child. We deliberately
    // keep the child in the same console group, wait for that event to take effect, then terminate
    // the kill-on-close Job Object if it does not exit. Programmatic cancellation has no safe
    // targeted console event and therefore uses the same bounded grace window before escalation.
    Ok(())
}

fn wait_until(
    child: &mut GroupChild,
    poll_interval: Duration,
    timeout: Duration,
) -> Result<Option<ExitStatus>, ProcessError> {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait().map_err(|source| ProcessError::Io {
            operation: "wait during cancellation",
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

fn join_pump(thread: thread::JoinHandle<u64>, stream: &'static str) -> Result<u64, ProcessError> {
    thread
        .join()
        .map_err(|_| ProcessError::PumpPanic { stream })
}

fn join_stdin(thread: thread::JoinHandle<()>) -> Result<(), ProcessError> {
    thread
        .join()
        .map_err(|_| ProcessError::PumpPanic { stream: "stdin" })
}

#[cfg(all(test, windows))]
mod tests {
    use std::{os::windows::process::ExitStatusExt, process::ExitStatus};

    use super::{cancellation_from_exit_status, CancellationKind, TerminationStage};

    #[test]
    fn windows_control_c_status_is_a_graceful_cancellation() {
        let status = ExitStatus::from_raw(0xC000_013A);
        let report = cancellation_from_exit_status(&status).expect("Ctrl+C report");
        assert_eq!(report.reason, CancellationKind::CtrlC);
        assert_eq!(report.final_stage, TerminationStage::Graceful);
    }
}
