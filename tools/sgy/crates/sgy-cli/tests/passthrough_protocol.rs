use std::{
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
    thread,
    time::{Duration, Instant},
};

use serde_json::Value;
use sgy_core::codec::parse_yaml_documents;

fn sgy(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.current_dir(cwd).args([
        "exec",
        "--engine",
        env!("CARGO_BIN_EXE_sgy-native-fixture"),
        "--cache",
        "off",
    ]);
    command
}

fn run_with_input(mut command: Command, input: &[u8]) -> Output {
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn sgy");
    child
        .stdin
        .take()
        .expect("stdin pipe")
        .write_all(input)
        .expect("write protocol input");
    child.wait_with_output().expect("wait for sgy")
}

fn yaml(path: &Path) -> Value {
    let bytes = std::fs::read(path).expect("read YAML sidecar");
    parse_yaml_documents(&bytes).expect("safe YAML sidecar")[0].clone()
}

fn lsp_session() -> Vec<u8> {
    let mut stream = Vec::new();
    for body in [
        br#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"rootUri":"file:///private/repo"}}"#.as_slice(),
        br#"{"jsonrpc":"2.0","id":2,"method":"fixture/request","params":{"text":"source-secret"}}"#.as_slice(),
        br#"{"jsonrpc":"2.0","id":3,"method":"shutdown","params":null}"#.as_slice(),
        br#"{"jsonrpc":"2.0","method":"exit","params":null}"#.as_slice(),
    ] {
        stream.extend_from_slice(format!("Content-Length: {}\r\n\r\n", body.len()).as_bytes());
        stream.extend_from_slice(body);
    }
    stream
}

#[test]
fn lsp_is_byte_identical_and_metadata_contains_no_protocol_payload() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let meta = directory.path().join("lsp-meta.yaml");
    let input = lsp_session();
    let mut command = sgy(directory.path());
    command.args([
        "--meta-out",
        meta.to_str().expect("UTF-8 path"),
        "--",
        "lsp",
        "--fixture-exit=7",
    ]);
    let output = run_with_input(command, &input);
    assert_eq!(output.status.code(), Some(7));
    assert_eq!(output.stdout, input);

    let value = yaml(&meta);
    assert_eq!(value["schema"], "sgy.protocol-meta/v1");
    assert_eq!(value["channel"], "lsp");
    assert_eq!(value["stdin_bytes"], input.len() as u64);
    assert_eq!(value["stdout_bytes"], input.len() as u64);
    assert_eq!(value["stderr_bytes"], 0);
    assert_eq!(value["native_exit_code"], 7);
    assert_eq!(value["cancelled"], false);
    assert_eq!(
        value["user_argv_sha256"].as_str().expect("argv hash").len(),
        64
    );
    let text = std::fs::read_to_string(meta).expect("UTF-8 metadata");
    for forbidden in [
        "initialize",
        "fixture/request",
        "file:///private/repo",
        "source-secret",
        "jsonrpc",
    ] {
        assert!(!text.contains(forbidden), "metadata leaked {forbidden}");
    }
}

#[test]
fn lsp_binary_stderr_is_forwarded_and_committed_as_exact_raw_sidecar() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let stderr_yaml = directory.path().join("stderr.yaml");
    let meta = directory.path().join("meta.yaml");
    let mut command = sgy(directory.path());
    command.args([
        "--stderr-yaml",
        stderr_yaml.to_str().expect("UTF-8 path"),
        "--meta-out",
        meta.to_str().expect("UTF-8 path"),
        "--",
        "lsp",
        "--fixture-stderr-invalid",
    ]);
    let output = run_with_input(command, b"");
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, [b'e', 0xff, b'\n']);

    let manifest = yaml(&stderr_yaml);
    assert_eq!(manifest["encoding"], "binary");
    assert_eq!(manifest["bytes"], 3);
    let raw = PathBuf::from(manifest["raw_path"].as_str().expect("raw path"));
    assert_eq!(std::fs::read(raw).expect("raw stderr"), [b'e', 0xff, b'\n']);
    assert_eq!(yaml(&meta)["stderr_bytes"], 3);
}

#[test]
fn lsp_meta_failure_happens_after_exact_protocol_delivery() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let meta = directory.path().join("raced-meta.yaml");
    let input = lsp_session();
    let mut command = sgy(directory.path());
    command.args([
        "--meta-out",
        meta.to_str().expect("UTF-8 path"),
        "--",
        "lsp",
        &format!("--fixture-create={}", meta.display()),
    ]);
    let output = run_with_input(command, &input);
    assert_eq!(output.status.code(), Some(127));
    assert_eq!(output.stdout, input);
    assert_eq!(
        std::fs::read_to_string(meta).expect("native raced file"),
        "created by native fixture\n"
    );
}

#[test]
fn stderr_sidecar_failure_is_recorded_in_meta_without_stdout_pollution() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let stderr_yaml = directory.path().join("raced-stderr.yaml");
    let meta = directory.path().join("meta.yaml");
    let input = lsp_session();
    let mut command = sgy(directory.path());
    command.args([
        "--stderr-yaml",
        stderr_yaml.to_str().expect("UTF-8 path"),
        "--meta-out",
        meta.to_str().expect("UTF-8 path"),
        "--",
        "lsp",
        "--fixture-stderr-invalid",
        &format!("--fixture-create={}", stderr_yaml.display()),
    ]);
    let output = run_with_input(command, &input);
    assert_eq!(output.status.code(), Some(127));
    assert_eq!(output.stdout, input);
    assert_eq!(yaml(&meta)["wrapper_error_origin"], "stderr_sidecar");
}

#[test]
fn lsp_and_tty_conflicts_fail_before_native_side_effects() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let cases: Vec<(Vec<String>, Vec<String>)> = vec![
        (
            vec![
                "--yaml-out".to_owned(),
                directory.path().join("x.yaml").display().to_string(),
            ],
            vec!["lsp".to_owned()],
        ),
        (
            vec!["--profile".to_owned(), "lossless".to_owned()],
            vec!["lsp".to_owned()],
        ),
        (
            vec!["--cache".to_owned(), "on".to_owned()],
            vec!["lsp".to_owned()],
        ),
        (
            vec![
                "--stderr-yaml".to_owned(),
                directory.path().join("tty.yaml").display().to_string(),
            ],
            vec!["test".to_owned(), "-i".to_owned()],
        ),
    ];
    for (ordinal, (wrapper, native)) in cases.into_iter().enumerate() {
        let marker = directory.path().join(format!("marker-{ordinal}"));
        let mut command = sgy(directory.path());
        command
            .args(wrapper)
            .arg("--")
            .args(native)
            .arg(format!("--fixture-create={}", marker.display()));
        let output = command.output().expect("conflict command");
        assert_eq!(output.status.code(), Some(125), "case {ordinal}");
        assert!(output.stdout.is_empty(), "case {ordinal}");
        assert!(!marker.exists(), "case {ordinal} started native child");
    }
}

#[test]
fn passthrough_sidecar_paths_must_be_distinct_before_native_start() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let shared = directory.path().join("shared.yaml");
    let marker = directory.path().join("must-not-exist");
    let output = sgy(directory.path())
        .args([
            "--stderr-yaml",
            shared.to_str().expect("UTF-8 path"),
            "--meta-out",
            shared.to_str().expect("UTF-8 path"),
            "--",
            "lsp",
            &format!("--fixture-create={}", marker.display()),
        ])
        .output()
        .expect("colliding sidecars");
    assert_eq!(output.status.code(), Some(125));
    assert!(output.stdout.is_empty());
    assert!(!marker.exists());
}

#[test]
fn interactive_commands_require_real_tty_and_never_fall_back_to_pipes() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    for (ordinal, native) in [
        vec!["run", "-i"],
        vec!["scan", "--interactive"],
        vec!["test", "-Ui"],
        vec!["new", "project"],
    ]
    .into_iter()
    .enumerate()
    {
        let marker = directory.path().join(format!("tty-marker-{ordinal}"));
        let output = sgy(directory.path())
            .arg("--")
            .args(native)
            .arg(format!("--fixture-create={}", marker.display()))
            .output()
            .expect("interactive command through pipes");
        assert_eq!(output.status.code(), Some(125));
        assert!(output.stdout.is_empty());
        assert!(String::from_utf8_lossy(&output.stderr).contains("E_TTY_UNAVAILABLE"));
        assert!(!marker.exists());
    }
}

#[test]
fn help_barrier_wins_over_interactive_flags() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    for native in [vec!["test", "-i", "--help"], vec!["new", "project", "-ih"]] {
        let output = sgy(directory.path())
            .arg("--")
            .args(native)
            .output()
            .expect("help barrier");
        assert!(output.status.success());
        let documents = parse_yaml_documents(&output.stdout).expect("raw help YAML");
        assert_eq!(documents[0]["_sgy"]["kind"], "help");
    }
}

#[test]
fn lsp_client_disconnect_returns_126_and_kills_descendant_group() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let delayed = directory.path().join("descendant-survived.txt");
    let ready = directory.path().join("descendant-ready.txt");
    let mut child = sgy(directory.path())
        .args([
            "--",
            "lsp",
            &format!("--fixture-spawn-delayed={}", delayed.display()),
            &format!("--fixture-spawn-ready={}", ready.display()),
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn disconnect case");
    let deadline = Instant::now() + Duration::from_secs(2);
    while !ready.exists() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert!(ready.exists(), "fixture descendant did not start");
    drop(child.stdout.take());
    child
        .stdin
        .take()
        .expect("stdin pipe")
        .write_all(&vec![b'x'; 2 * 1024 * 1024])
        .expect("write large protocol stream");
    let status = child.wait().expect("wait disconnect case");
    assert_eq!(status.code(), Some(126));
    thread::sleep(Duration::from_millis(2200));
    assert!(!delayed.exists(), "descendant survived LSP cleanup");
}
