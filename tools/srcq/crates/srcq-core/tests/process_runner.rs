use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    thread,
    time::Duration,
};

use srcq_core::process::{
    run, CancellationKind, CancellationToken, ProcessError, ProcessRequest, StdinMode,
};
use tempfile::tempdir;

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_srcq-process-fixture"))
}

fn request(cwd: &Path, arguments: &[&str]) -> ProcessRequest {
    let mut request = ProcessRequest::new(fixture(), cwd);
    request.args = arguments.iter().map(OsString::from).collect();
    request.forward_stderr = false;
    request
}

#[test]
fn drains_large_stdout_and_stderr_concurrently() {
    let directory = tempdir().expect("temp directory");
    let bytes = 4 * 1024 * 1024;
    let outcome = run(request(directory.path(), &["dual", &bytes.to_string()]))
        .expect("dual-stream fixture must complete");

    assert_eq!(outcome.exit_code(), 0);
    assert_eq!(outcome.output.stdout_bytes, bytes as u64);
    assert_eq!(outcome.output.stderr_bytes, bytes as u64);
    assert!(outcome
        .output
        .read_stdout()
        .expect("read stdout")
        .iter()
        .all(|byte| *byte == b'o'));
    assert!(outcome
        .output
        .read_stderr()
        .expect("read stderr")
        .iter()
        .all(|byte| *byte == b'e'));
}

#[test]
fn capture_limit_terminates_unbounded_native_output() {
    let directory = tempdir().expect("temp directory");
    let mut process = request(directory.path(), &["dual", &(2 * 1024 * 1024).to_string()]);
    process.max_stdout_bytes = Some(64 * 1024);
    process.max_stderr_bytes = Some(64 * 1024);
    let error = run(process).expect_err("capture limit must reject oversized output");
    assert!(error.to_string().contains("capture limit"));
}

#[test]
fn copies_binary_stdin_and_closes_pipe_for_eof() {
    let directory = tempdir().expect("temp directory");
    let input = vec![0, b'a', 0xff, b'\n', 0, b'z'];
    let mut process = request(directory.path(), &["echo-stdin"]);
    process.stdin = StdinMode::Bytes(input.clone());
    let outcome = run(process).expect("stdin fixture must complete");

    assert_eq!(outcome.exit_code(), 0);
    assert_eq!(outcome.output.read_stdout().expect("read stdout"), input);
    assert!(outcome
        .output
        .read_stderr()
        .expect("read stderr")
        .is_empty());
}

#[test]
fn preserves_native_nonzero_exit_with_complete_stdout() {
    let directory = tempdir().expect("temp directory");
    let outcome = run(request(directory.path(), &["exit", "37", "{\"ok\":true}"]))
        .expect("exit fixture must complete");

    assert_eq!(outcome.exit_code(), 37);
    assert_eq!(
        outcome.output.read_stdout().expect("read stdout"),
        br#"{"ok":true}"#
    );
    assert!(outcome.cancellation.is_none());
}

#[test]
fn cancellation_terminates_the_descendant_tree() {
    let directory = tempdir().expect("temp directory");
    let heartbeat = directory.path().join("heartbeat");
    let heartbeat_argument = heartbeat.to_string_lossy().into_owned();
    let token = CancellationToken::new();
    let mut process = request(directory.path(), &["tree", &heartbeat_argument]);
    process.cancellation = token.clone();
    process.poll_interval = Duration::from_millis(5);
    process.grace_period = Duration::from_millis(150);

    let trigger = thread::spawn(move || {
        thread::sleep(Duration::from_millis(180));
        token.cancel(CancellationKind::External);
    });
    let outcome = run(process).expect("cancelled tree fixture must be reaped");
    trigger.join().expect("cancellation trigger");

    assert_eq!(outcome.exit_code(), 143);
    assert!(outcome.cancellation.is_some());
    let size_after_exit = fs::metadata(&heartbeat)
        .expect("leaf created heartbeat")
        .len();
    thread::sleep(Duration::from_millis(250));
    assert_eq!(
        fs::metadata(&heartbeat)
            .expect("heartbeat remains inspectable")
            .len(),
        size_after_exit,
        "descendant continued running after process outcome"
    );
}

#[test]
fn timeout_terminates_the_descendant_tree() {
    let directory = tempdir().expect("temp directory");
    let heartbeat = directory.path().join("timeout-heartbeat");
    let heartbeat_argument = heartbeat.to_string_lossy().into_owned();
    let mut process = request(directory.path(), &["tree", &heartbeat_argument]);
    process.poll_interval = Duration::from_millis(5);
    process.timeout = Some(Duration::from_millis(180));

    let error = run(process).expect_err("timed-out tree fixture must be reaped");
    assert!(matches!(error, ProcessError::Timeout { .. }));

    let size_after_exit = fs::metadata(&heartbeat)
        .expect("leaf created timeout heartbeat")
        .len();
    thread::sleep(Duration::from_millis(250));
    assert_eq!(
        fs::metadata(&heartbeat)
            .expect("timeout heartbeat remains inspectable")
            .len(),
        size_after_exit,
        "descendant continued running after process timeout"
    );
}
