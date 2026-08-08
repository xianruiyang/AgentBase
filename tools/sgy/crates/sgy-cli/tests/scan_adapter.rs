use std::{path::Path, process::Command};

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

fn yaml(bytes: &[u8]) -> Vec<Value> {
    parse_yaml_documents(bytes).expect("safe YAML output")
}

#[test]
fn structured_scan_preserves_options_and_finding_diagnostics() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = sgy(directory.path())
        .args([
            "--profile",
            "lossless",
            "--",
            "scan",
            "--json=compact",
            "--config",
            "custom-sgconfig.yml",
            "--filter",
            "^rule-",
            "--error=rule-0",
            "--warning=rule-1",
            "--info=rule-2",
            "--hint=rule-3",
            "--off=rule-4",
            "--include-metadata",
            "--report-style=short",
            "--max-results=7",
            "--globs",
            "*.ts",
            "--no-ignore",
            "hidden",
            "--follow",
            "--fixture-matches=2",
        ])
        .output()
        .expect("lossless scan");
    assert!(output.status.success());
    let documents = yaml(&output.stdout);
    let records = documents[0].as_array().expect("compact array");
    assert_eq!(records.len(), 2);
    assert_eq!(records[0]["metadata"]["category"], "fixture");
    assert_eq!(
        records[0]["argv"],
        serde_json::json!([
            "scan",
            "--json=compact",
            "--config",
            "custom-sgconfig.yml",
            "--filter",
            "^rule-",
            "--error=rule-0",
            "--warning=rule-1",
            "--info=rule-2",
            "--hint=rule-3",
            "--off=rule-4",
            "--include-metadata",
            "--report-style=short",
            "--max-results=7",
            "--globs",
            "*.ts",
            "--no-ignore",
            "hidden",
            "--follow",
            "--fixture-matches=2"
        ])
    );

    let token_safe = sgy(directory.path())
        .args([
            "--",
            "scan",
            "--inline-rules",
            "id: fixture",
            "--json=stream",
            "--fixture-matches=1",
        ])
        .output()
        .expect("token-safe finding");
    assert!(token_safe.status.success());
    let context = &yaml(&token_safe.stdout)[0];
    assert_eq!(context["_sgy"]["total"], 1);
    assert_eq!(context["results"][0]["ruleId"], "rule-0");
    assert_eq!(context["results"][0]["severity"], "warning");
    assert_eq!(context["results"][0]["message"], "finding 0");
}

#[test]
fn sarif_lossless_round_trips_the_exact_native_json() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let native_args = ["scan", "--format=sarif", "--fixture-matches=2"];
    let native = Command::new(env!("CARGO_BIN_EXE_sgy-native-fixture"))
        .current_dir(directory.path())
        .args(native_args)
        .output()
        .expect("native SARIF");
    assert!(native.status.success());

    let wrapped = sgy(directory.path())
        .args(["--profile", "lossless", "--"])
        .args(native_args)
        .output()
        .expect("wrapped SARIF");
    assert!(wrapped.status.success());
    assert_eq!(
        yaml(&wrapped.stdout),
        vec![serde_json::from_slice::<Value>(&native.stdout).expect("native SARIF JSON")]
    );
}

#[test]
fn github_text_and_files_use_bounded_safe_yaml() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let github = sgy(directory.path())
        .args([
            "--max-text-chars",
            "70",
            "--",
            "scan",
            "--format=github",
            "--fixture-matches=3",
        ])
        .output()
        .expect("GitHub scan");
    assert!(github.status.success());
    let document = &yaml(&github.stdout)[0];
    assert_eq!(document["_sgy"]["schema"], "sgy.scan/v1");
    assert_eq!(document["_sgy"]["kind"], "github");
    assert_eq!(document["_sgy"]["complete"], false);
    assert!(document["stdout"]
        .as_str()
        .expect("GitHub text")
        .starts_with("::warning file=src/0.ts"));

    let text = sgy(directory.path())
        .args([
            "--no-native-defaults",
            "--",
            "scan",
            "--report-style=short",
            "--fixture-matches=1",
        ])
        .output()
        .expect("text scan");
    assert!(text.status.success());
    let document = &yaml(&text.stdout)[0];
    assert_eq!(document["_sgy"]["kind"], "text");
    assert_eq!(document["stdout"], "native text output\n");

    let files = sgy(directory.path())
        .args([
            "--max-detail-results",
            "2",
            "--",
            "scan",
            "--files-with-matches",
            "--fixture-files=4",
        ])
        .output()
        .expect("files scan");
    assert!(files.status.success());
    let document = &yaml(&files.stdout)[0];
    assert_eq!(document["_sgy"]["kind"], "files-with-matches");
    assert_eq!(document["_sgy"]["total"], 4);
    assert_eq!(document["_sgy"]["shown"], 2);
    assert_eq!(document["_sgy"]["complete"], false);
}

#[test]
fn inspect_no_match_and_native_error_keep_channels_and_status_distinct() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let inspect = sgy(directory.path())
        .args(["--", "scan", "--inspect=summary", "--fixture-matches=1"])
        .output()
        .expect("inspect scan");
    assert!(inspect.status.success());
    assert!(String::from_utf8_lossy(&inspect.stderr).contains("fixture inspect summary"));
    assert!(!String::from_utf8_lossy(&inspect.stdout).contains("inspect summary"));
    assert_eq!(yaml(&inspect.stdout)[0]["_sgy"]["total"], 1);

    let no_match = sgy(directory.path())
        .args(["--", "scan", "--fixture-matches=0"])
        .output()
        .expect("empty scan");
    assert!(no_match.status.success());
    let document = &yaml(&no_match.stdout)[0];
    assert_eq!(document["_sgy"]["total"], 0);
    assert_eq!(document["_sgy"]["complete"], true);

    let error = sgy(directory.path())
        .args(["--", "scan", "--fixture-empty"])
        .output()
        .expect("native scan error");
    assert_eq!(error.status.code(), Some(2));
    assert!(error.stdout.is_empty());
}
