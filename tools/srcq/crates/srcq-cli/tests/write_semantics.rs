use std::{path::Path, process::Command};

use serde_json::Value;
use srcq_core::codec::parse_yaml_documents;

fn srcq(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
    command.current_dir(cwd).args([
        "exec",
        "--output",
        "machine",
        "--engine",
        env!("CARGO_BIN_EXE_srcq-native-fixture"),
        "--cache",
        "off",
    ]);
    command
}

fn yaml(bytes: &[u8]) -> Vec<Value> {
    parse_yaml_documents(bytes).expect("safe YAML output")
}

#[test]
fn rewrite_preview_keeps_replacement_and_full_source_statistics() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--max-detail-results",
            "1",
            "--",
            "run",
            "-p",
            "console.log($A)",
            "-r",
            "logger.info($A)",
            "--fixture-matches=50",
            "--fixture-replacements",
        ])
        .output()
        .expect("rewrite preview");
    assert!(output.status.success());
    let document = &yaml(&output.stdout)[0];
    assert_eq!(document["_sgy"]["total"], 50);
    assert_eq!(document["_sgy"]["shown"], 1);
    assert_eq!(document["_sgy"]["files"], 3);
    assert_eq!(document["_sgy"]["write"]["requested"], "preview");
    assert_eq!(document["_sgy"]["write"]["matches"], 50);
    assert_eq!(document["_sgy"]["write"]["affected_files"], 3);
    assert_eq!(document["_sgy"]["write"]["replacement_records"], 50);
    assert_eq!(document["_sgy"]["write"]["transactional"], false);
    assert_eq!(document["results"][0]["replacement"], "replacement-0");
}

#[test]
fn scan_fix_preview_is_discovered_from_native_replacements() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--max-detail-results",
            "1",
            "--",
            "scan",
            "--rule",
            "fix-rule.yml",
            "--fixture-matches=5",
            "--fixture-replacements",
        ])
        .output()
        .expect("scan fix preview");
    assert!(output.status.success());
    let document = &yaml(&output.stdout)[0];
    assert_eq!(document["_sgy"]["write"]["requested"], "preview");
    assert_eq!(document["_sgy"]["write"]["matches"], 5);
    assert_eq!(document["_sgy"]["write"]["affected_files"], 3);
    assert_eq!(document["_sgy"]["write"]["replacement_records"], 5);
}

#[test]
fn update_all_uses_native_text_path_and_does_not_claim_transactional_success() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--",
            "run",
            "-p",
            "console.log($A)",
            "-r",
            "logger.info($A)",
            "-U",
            "--fixture-matches=2",
        ])
        .output()
        .expect("update all");
    assert!(output.status.success());
    let document = &yaml(&output.stdout)[0];
    assert_eq!(document["_sgy"]["kind"], "update-all");
    assert_eq!(document["_sgy"]["write"]["requested"], "apply");
    assert_eq!(document["_sgy"]["write"]["transactional"], false);
    assert_eq!(document["_sgy"]["write"]["applied_changes"], 2);
    assert_eq!(document["_sgy"]["write"]["affected_files"], Value::Null);
    assert_eq!(document["_sgy"]["write"]["affected_files_complete"], false);
    assert_eq!(
        document["_sgy"]["write"]["result_detail"],
        "applied_count_from_native_stderr; affected_files_require_preview"
    );
    assert!(document["_sgy"].get("complete").is_none());
}

#[test]
fn failed_update_all_emits_no_success_yaml_and_warns_about_partial_writes() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--",
            "scan",
            "-U",
            "--fixture-matches=1",
            "--fixture-exit=7",
        ])
        .output()
        .expect("failed update all");
    assert_eq!(output.status.code(), Some(7));
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("may have partially modified files"));
    assert!(stderr.contains("no transaction or rollback"));
}

#[test]
fn invalid_partial_structured_update_emits_no_yaml_and_warns_about_partial_writes() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--",
            "run",
            "-p",
            "console.log($A)",
            "-r",
            "logger.info($A)",
            "-U",
            "--json=stream",
            "--fixture-invalid",
        ])
        .output()
        .expect("invalid partial structured update");
    assert_eq!(output.status.code(), Some(121));
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("may have partially modified files"));
    assert!(stderr.contains("no transaction or rollback"));
}

#[test]
fn replacement_survives_before_large_match_text_under_context_pressure() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--max-detail-results",
            "1",
            "--max-context-bytes",
            "1400",
            "--",
            "run",
            "-p",
            "console.log($A)",
            "-r",
            "logger.info($A)",
            "--fixture-matches=1",
            "--fixture-text-chars=5000",
            "--fixture-replacements",
        ])
        .output()
        .expect("budgeted rewrite preview");
    assert!(output.status.success());
    let document = &yaml(&output.stdout)[0];
    assert_eq!(document["results"][0]["replacement"], "replacement-0");
    assert_eq!(document["results"][0]["_sgy_text_truncated"], true);
    assert_eq!(document["_sgy"]["write"]["replacement_records"], 1);
}

#[test]
fn rewrite_preview_never_injects_an_apply_flag() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args([
            "--profile",
            "lossless",
            "--",
            "run",
            "-p",
            "console.log($A)",
            "-r",
            "logger.info($A)",
            "--fixture-matches=1",
            "--fixture-replacements",
        ])
        .output()
        .expect("lossless rewrite preview");
    assert!(output.status.success());
    let records = yaml(&output.stdout);
    let argv = records[0]["argv"].as_array().expect("native argv");
    assert!(argv.iter().all(|arg| arg != "-U" && arg != "--update-all"));
    assert!(argv.iter().any(|arg| arg == "--json=stream"));
    assert!(argv.iter().all(|arg| {
        !arg.as_str()
            .is_some_and(|value| value.starts_with("--max-results"))
    }));
}
