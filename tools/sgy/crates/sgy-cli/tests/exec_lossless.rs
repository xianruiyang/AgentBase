use std::{
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

use sgy_core::codec::parse_yaml_documents;

fn sgy_command(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.current_dir(cwd).args([
        "exec",
        "--profile",
        "lossless",
        "--engine",
        env!("CARGO_BIN_EXE_sgy-native-fixture"),
    ]);
    command
}

fn parse_stdout(bytes: &[u8]) -> Vec<serde_json::Value> {
    parse_yaml_documents(bytes).expect("safe YAML output")
}

#[test]
fn default_run_injects_stream_and_explicit_json_styles_are_unchanged() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = sgy_command(directory.path())
        .args(["--", "run", "-p", "console.log($A)"])
        .output()
        .expect("run sgy");
    assert!(output.status.success());
    let documents = parse_stdout(&output.stdout);
    assert_eq!(documents.len(), 1);
    assert_eq!(documents[0]["style"], "stream");
    assert_eq!(
        documents[0]["argv"].as_array().expect("argv").last(),
        Some(&serde_json::Value::String("--json=stream".to_owned()))
    );

    for (flag, expected_style) in [
        ("--json", "pretty"),
        ("--json=pretty", "pretty"),
        ("--json=compact", "compact"),
        ("--json=stream", "stream"),
    ] {
        let output = sgy_command(directory.path())
            .args(["--", "scan", flag])
            .output()
            .expect("run explicit style");
        assert!(output.status.success(), "style {flag}");
        let documents = parse_stdout(&output.stdout);
        let record = if expected_style == "stream" {
            &documents[0]
        } else {
            &documents[0][0]
        };
        assert_eq!(record["style"], expected_style);
        let argv = record["argv"].as_array().expect("argv");
        assert_eq!(
            argv.iter()
                .filter(|value| value.as_str().is_some_and(|arg| arg.starts_with("--json")))
                .count(),
            1,
            "wrapper must not append another JSON option"
        );
        assert_eq!(argv.last().and_then(serde_json::Value::as_str), Some(flag));
    }
}

#[test]
fn stdin_native_exit_and_invalid_partial_stream_follow_the_contract() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let mut child = sgy_command(directory.path())
        .args(["--", "run", "--stdin"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("spawn stdin case");
    child
        .stdin
        .take()
        .expect("stdin pipe")
        .write_all("console.log(中文)".as_bytes())
        .expect("write stdin");
    let output = child.wait_with_output().expect("wait stdin case");
    assert!(output.status.success());
    assert_eq!(
        parse_stdout(&output.stdout)[0]["stdin"],
        "console.log(中文)"
    );

    let nonzero = sgy_command(directory.path())
        .args(["--", "scan", "--fixture-exit=7"])
        .output()
        .expect("native nonzero");
    assert_eq!(nonzero.status.code(), Some(7));
    assert!(!nonzero.stdout.is_empty());

    let invalid = sgy_command(directory.path())
        .args(["--", "run", "--fixture-invalid"])
        .output()
        .expect("invalid partial stream");
    assert_eq!(invalid.status.code(), Some(121));
    assert!(invalid.stdout.is_empty());

    let empty = sgy_command(directory.path())
        .args(["--", "run", "--fixture-empty"])
        .output()
        .expect("empty native error");
    assert_eq!(empty.status.code(), Some(2));
    assert!(empty.stdout.is_empty());

    let no_match = Command::new(env!("CARGO_BIN_EXE_sgy"))
        .current_dir(directory.path())
        .args([
            "exec",
            "--engine",
            env!("CARGO_BIN_EXE_sgy-native-fixture"),
            "--cache",
            "off",
            "--",
            "run",
            "--fixture-no-match",
        ])
        .output()
        .expect("empty native no-match");
    assert_eq!(no_match.status.code(), Some(1));
    let no_match_yaml = parse_yaml_documents(&no_match.stdout).expect("no-match YAML");
    assert_eq!(no_match_yaml[0]["_sgy"]["total"], 0);
    assert_eq!(no_match_yaml[0]["_sgy"]["complete"], true);
    assert_eq!(no_match_yaml[0]["results"], serde_json::json!([]));
}

#[test]
fn yaml_out_is_atomic_and_default_profile_is_token_safe() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output_path: PathBuf = directory.path().join("result.yaml");
    let output = sgy_command(directory.path())
        .args([
            "--yaml-out",
            output_path.to_str().expect("UTF-8 test path"),
            "--",
            "run",
        ])
        .output()
        .expect("yaml-out run");
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    assert_eq!(
        parse_stdout(&std::fs::read(output_path).expect("read yaml-out"))[0]["style"],
        "stream"
    );

    let token_safe = Command::new(env!("CARGO_BIN_EXE_sgy"))
        .current_dir(directory.path())
        .args([
            "exec",
            "--engine",
            env!("CARGO_BIN_EXE_sgy-native-fixture"),
            "--cache",
            "off",
            "--",
            "run",
        ])
        .output()
        .expect("default profile");
    assert_eq!(token_safe.status.code(), Some(0));
    let context = &parse_stdout(&token_safe.stdout)[0];
    assert_eq!(context["_sgy"]["profile"], "token-safe");
    assert_eq!(context["_sgy"]["total"], 1);
    assert_eq!(context["_sgy"]["complete"], false);
    assert!(context["_sgy"].get("cache").is_none());
}

#[test]
fn batch_meta_out_records_execution_without_replacing_context_yaml() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let meta_path = directory.path().join("batch-meta.yml");
    let output = Command::new(env!("CARGO_BIN_EXE_sgy"))
        .current_dir(directory.path())
        .args([
            "exec",
            "--engine",
            env!("CARGO_BIN_EXE_sgy-native-fixture"),
            "--cache",
            "off",
            "--meta-out",
            meta_path.to_str().expect("UTF-8 metadata path"),
            "--",
            "run",
            "--fixture-matches=1",
        ])
        .output()
        .expect("batch metadata run");
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(parse_stdout(&output.stdout)[0]["_sgy"]["total"], 1);
    let metadata = parse_stdout(&std::fs::read(meta_path).expect("read batch metadata"));
    assert_eq!(metadata[0]["schema"], "sgy.execution-meta/v1");
    assert_eq!(metadata[0]["channel"], "batch");
    assert_eq!(metadata[0]["engine_version"], "ast-grep fixture 0.0.0");
    assert_eq!(metadata[0]["native_exit_code"], 0);
    assert_eq!(metadata[0]["cancelled"], false);
}
