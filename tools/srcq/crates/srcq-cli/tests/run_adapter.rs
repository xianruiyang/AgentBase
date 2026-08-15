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
    let documents = parse_yaml_documents(bytes).expect("safe YAML output");
    assert_eq!(documents.len(), 1);
    documents.into_iter().next().expect("one document")
}

#[test]
fn structured_run_preserves_native_arguments_stdin_and_unknown_fields() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let mut child = srcq(directory.path())
        .args([
            "--profile",
            "lossless",
            "--",
            "run",
            "--json=compact",
            "--selector",
            "call_expression",
            "--strictness",
            "smart",
            "--globs",
            "*.ts",
            "--no-ignore",
            "hidden",
            "--follow",
            "--stdin",
            "--fixture-matches=1",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("spawn srcq");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all("console.log(中文)".as_bytes())
        .expect("write stdin");
    let output = child.wait_with_output().expect("wait srcq");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    let record = &document[0];
    assert_eq!(record["futureField"]["preserved"], true);
    assert_eq!(
        record["argv"],
        serde_json::json!([
            "run",
            "--json=compact",
            "--selector",
            "call_expression",
            "--strictness",
            "smart",
            "--globs",
            "*.ts",
            "--no-ignore",
            "hidden",
            "--follow",
            "--stdin",
            "--fixture-matches=1"
        ])
    );
}

#[test]
fn files_with_matches_is_bounded_yaml_and_distinguishes_empty_from_error() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--max-detail-results",
            "2",
            "--",
            "run",
            "--files-with-matches",
            "--fixture-files=5",
        ])
        .output()
        .expect("files run");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["kind"], "files-with-matches");
    assert_eq!(document["_sgy"]["total"], 5);
    assert_eq!(document["_sgy"]["shown"], 2);
    assert_eq!(document["_sgy"]["omitted"], 3);
    assert_eq!(document["_sgy"]["complete"], false);
    assert_eq!(
        document["files"],
        serde_json::json!(["src/file 0-中文.ts", "src/file 1-中文.ts"])
    );

    let byte_bounded = srcq(directory.path())
        .args([
            "--max-context-bytes",
            "190",
            "--",
            "run",
            "--files-with-matches",
            "--fixture-files=5",
        ])
        .output()
        .expect("byte-bounded files run");
    assert!(byte_bounded.status.success());
    assert!(byte_bounded.stdout.len() <= 190);
    let document = yaml(&byte_bounded.stdout);
    assert_eq!(document["_sgy"]["total"], 5);
    assert_eq!(document["_sgy"]["complete"], false);

    let empty = srcq(directory.path())
        .args(["--", "run", "--files-with-matches", "--fixture-files=0"])
        .output()
        .expect("empty files run");
    assert!(empty.status.success());
    let document = yaml(&empty.stdout);
    assert_eq!(document["_sgy"]["total"], 0);
    assert_eq!(document["_sgy"]["complete"], true);
    assert_eq!(document["files"], serde_json::json!([]));

    let error = srcq(directory.path())
        .args(["--", "run", "--files-with-matches", "--fixture-empty"])
        .output()
        .expect("native files error");
    assert_eq!(error.status.code(), Some(2));
    assert!(error.stdout.is_empty());
}

#[test]
fn debug_and_inspect_stay_on_stderr_while_stdout_uses_the_right_adapter() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let debug_text = srcq(directory.path())
        .args(["--max-text-chars", "6", "--", "run", "--debug-query=ast"])
        .output()
        .expect("debug text run");
    assert!(debug_text.status.success());
    assert!(String::from_utf8_lossy(&debug_text.stderr).contains("fixture debug query"));
    let document = yaml(&debug_text.stdout);
    assert_eq!(document["_sgy"]["kind"], "text");
    assert_eq!(document["_sgy"]["complete"], false);
    assert_eq!(document["stdout"], "native");
    assert!(!String::from_utf8_lossy(&debug_text.stdout).contains("debug query"));

    let debug_json = srcq(directory.path())
        .args([
            "--",
            "run",
            "--debug-query=ast",
            "--json=stream",
            "--fixture-matches=1",
        ])
        .output()
        .expect("debug JSON run");
    assert!(debug_json.status.success());
    assert!(String::from_utf8_lossy(&debug_json.stderr).contains("fixture debug query"));
    let document = yaml(&debug_json.stdout);
    assert_eq!(document["_sgy"]["total"], 1);
    assert!(!String::from_utf8_lossy(&debug_json.stdout).contains("debug query"));

    let inspect = srcq(directory.path())
        .args(["--", "run", "--inspect", "summary", "--fixture-matches=1"])
        .output()
        .expect("inspect run");
    assert!(inspect.status.success());
    assert!(String::from_utf8_lossy(&inspect.stderr).contains("fixture inspect summary"));
    let document = yaml(&inspect.stdout);
    assert_eq!(document["_sgy"]["total"], 1);
    assert!(!String::from_utf8_lossy(&inspect.stdout).contains("inspect summary"));
}

#[test]
fn raw_text_honors_context_budget_and_yaml_out() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let yaml_path = directory.path().join("raw.yaml");
    let output = srcq(directory.path())
        .args([
            "--no-native-defaults",
            "--max-context-bytes",
            "180",
            "--yaml-out",
            yaml_path.to_str().expect("UTF-8 path"),
            "--",
            "run",
        ])
        .output()
        .expect("raw run");
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    let bytes = std::fs::read(yaml_path).expect("read YAML artifact");
    assert!(bytes.len() <= 180);
    let document = yaml(&bytes);
    assert_eq!(document["_sgy"]["kind"], "text");
    assert_eq!(document["stdout"], "native text output\n");
}
