use std::{path::Path, process::Command};

use srcq_core::profile::{project_token_safe, RecordShape};

#[test]
#[ignore = "requires SRCQ_AST_GREP to point to a real ast-grep binary"]
fn real_run_rewrite_and_scan_shapes_project_as_known_records() {
    let engine = std::env::var_os("SRCQ_AST_GREP").expect("SRCQ_AST_GREP is required");
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root");
    let version = Command::new(&engine)
        .arg("--version")
        .output()
        .expect("read version");
    let expected_version = std::env::var("SRCQ_AST_GREP_EXPECTED_VERSION")
        .unwrap_or_else(|_| "ast-grep 0.44.1".to_owned());
    assert_eq!(
        String::from_utf8(version.stdout)
            .expect("UTF-8 version")
            .trim(),
        expected_version
    );

    let run = Command::new(&engine)
        .current_dir(root)
        .args([
            "run",
            "-p",
            "console.log($A)",
            "-r",
            "logger.info($A)",
            "-l",
            "ts",
            "tests/fixtures/native/run/input.ts",
            "--json=compact",
        ])
        .output()
        .expect("native run");
    assert!(run.status.success());
    let records: Vec<serde_json::Value> =
        serde_json::from_slice(&run.stdout).expect("run JSON array");
    assert_eq!(records.len(), 2);
    for (ordinal, record) in records.iter().enumerate() {
        let projected = project_token_safe(ordinal as u64, record);
        assert_eq!(projected.shape, RecordShape::Match);
        assert!(projected.value.get("file").is_some());
        assert!(projected.value.get("range").is_some());
        assert!(projected.value.get("text").is_some());
        assert!(projected.value.get("replacement").is_some());
        assert!(projected.value.get("lines").is_none());
        assert!(projected.value.get("charCount").is_none());
        assert!(projected.value["range"].get("byteOffset").is_none());
    }

    let scan = Command::new(&engine)
        .current_dir(root)
        .args([
            "scan",
            "-r",
            "tests/fixtures/native/scan/no-console.yml",
            "tests/fixtures/native/scan/input.ts",
            "--json=compact",
            "--include-metadata",
        ])
        .output()
        .expect("native scan");
    assert!(scan.status.success());
    let records: Vec<serde_json::Value> =
        serde_json::from_slice(&scan.stdout).expect("scan JSON array");
    assert_eq!(records.len(), 1);
    let projected = project_token_safe(0, &records[0]);
    assert_eq!(projected.shape, RecordShape::Finding);
    for field in [
        "file", "range", "text", "ruleId", "severity", "message", "labels", "language",
    ] {
        assert!(projected.value.get(field).is_some(), "field {field}");
    }
    assert!(projected.value.get("note").is_none());
    assert!(projected.value["labels"][0]["range"]
        .get("byteOffset")
        .is_none());
}
