use std::{
    io::Write,
    path::Path,
    process::{Command, Stdio},
};

use serde_json::Value;
use srcq_core::codec::parse_yaml_documents;

fn srcq(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
    command.current_dir(cwd).args([
        "exec",
        "--engine",
        env!("CARGO_BIN_EXE_srcq-native-fixture"),
        "--cache",
        "off",
    ]);
    command
}

fn yaml(bytes: &[u8]) -> Value {
    parse_yaml_documents(bytes).expect("safe YAML output")[0].clone()
}

#[test]
fn batch_and_text_command_success_failure_matrix_preserves_native_status() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let cases: &[(&[&str], i32)] = &[
        (&["run", "--fixture-matches=1"], 0),
        (&["run", "--fixture-matches=1", "--fixture-exit=7"], 7),
        (&["scan", "--fixture-matches=1"], 0),
        (&["scan", "--fixture-matches=1", "--fixture-exit=8"], 8),
        (&["test", "--fixture-matches=1"], 0),
        (&["test", "--fixture-matches=1", "--fixture-exit=9"], 9),
        (&["new", "project", "-y"], 0),
        (&["new", "project", "-y", "--fixture-exit=10"], 10),
        (&["--help"], 0),
        (&["--help", "--fixture-exit=11"], 11),
        (&["--version"], 0),
        (&["--version", "--fixture-exit=12"], 12),
        (&["future-command", "--fixture-matches=1"], 0),
        (
            &["future-command", "--fixture-matches=1", "--fixture-exit=13"],
            13,
        ),
    ];

    for (native_args, expected_status) in cases {
        let output = srcq(directory.path())
            .arg("--")
            .args(*native_args)
            .output()
            .expect("matrix command");
        assert_eq!(
            output.status.code(),
            Some(*expected_status),
            "native args: {native_args:?}; stderr: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(
            !parse_yaml_documents(&output.stdout)
                .expect("matrix output must be safe YAML")
                .is_empty(),
            "native args: {native_args:?}"
        );
    }
}

#[test]
fn unknown_future_command_is_raw_fallback_without_default_injection() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args(["--", "future-command", "--json=compact"])
        .output()
        .expect("unknown raw fallback");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["schema"], "sgy.raw/v1");
    assert_eq!(document["_sgy"]["kind"], "unknown");
    let native: Value = serde_json::from_str(document["stdout"].as_str().expect("raw stdout"))
        .expect("fixture JSON embedded as text");
    assert_eq!(
        native[0]["argv"],
        serde_json::json!(["future-command", "--json=compact"])
    );
}

#[test]
fn unknown_future_command_inherits_stdin_and_keeps_protocol_channels_separate() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let mut child = srcq(directory.path());
    child
        .args([
            "--",
            "future-command",
            "--fixture-read-stdin",
            "--inspect=summary",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = child.spawn().expect("unknown command child");
    child
        .stdin
        .take()
        .expect("piped stdin")
        .write_all(b"future payload\n")
        .expect("write stdin");
    let output = child.wait_with_output().expect("unknown command output");
    assert!(output.status.success());
    assert_eq!(yaml(&output.stdout)["stdout"], "future payload\n");
    assert!(String::from_utf8_lossy(&output.stderr).contains("fixture inspect summary"));
    assert!(!String::from_utf8_lossy(&output.stdout).contains("fixture inspect summary"));
}

#[test]
fn unknown_binary_output_requires_artifact_and_completions_remains_explicit() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let rejected = srcq(directory.path())
        .args(["--", "future-command", "--fixture-invalid-utf8"])
        .output()
        .expect("binary rejection");
    assert_eq!(rejected.status.code(), Some(121));
    assert!(rejected.stdout.is_empty());

    let binary = directory.path().join("future.bin");
    let accepted = srcq(directory.path())
        .args([
            "--artifact-out",
            binary.to_str().expect("UTF-8 path"),
            "--",
            "future-command",
            "--fixture-invalid-utf8",
        ])
        .output()
        .expect("binary artifact");
    assert!(accepted.status.success());
    assert_eq!(
        std::fs::read(&binary).expect("binary artifact"),
        [b'r', 0xff, b'w']
    );
    assert_eq!(yaml(&accepted.stdout)["encoding"], "binary");

    let missing = srcq(directory.path())
        .args(["--", "completions", "powershell"])
        .output()
        .expect("completion rejection");
    assert_eq!(missing.status.code(), Some(125));

    let completion = directory.path().join("completion.ps1");
    let written = srcq(directory.path())
        .args([
            "--artifact-out",
            completion.to_str().expect("UTF-8 path"),
            "--",
            "completions",
            "powershell",
        ])
        .output()
        .expect("completion artifact");
    assert!(written.status.success());
    assert_eq!(yaml(&written.stdout)["kind"], "artifact");
    assert_eq!(
        std::fs::read_to_string(completion).expect("completion text"),
        "# completion fixture\ncomplete -c ast-grep\n"
    );
}

#[test]
fn lsp_is_byte_exact_and_interactive_commands_do_not_fall_into_raw_yaml() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let payload = b"Content-Length: 2\r\n\r\n{}";
    let mut command = srcq(directory.path());
    command
        .args(["--", "lsp"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command.spawn().expect("LSP child");
    child
        .stdin
        .take()
        .expect("LSP stdin")
        .write_all(payload)
        .expect("write LSP payload");
    let output = child.wait_with_output().expect("LSP output");
    assert!(output.status.success());
    assert_eq!(output.stdout, payload);

    let interactive = srcq(directory.path())
        .args(["--", "test", "-i"])
        .output()
        .expect("TTY rejection");
    assert_eq!(interactive.status.code(), Some(125));
    assert!(interactive.stdout.is_empty());
    assert!(String::from_utf8_lossy(&interactive.stderr).contains("E_TTY_UNAVAILABLE"));
}
