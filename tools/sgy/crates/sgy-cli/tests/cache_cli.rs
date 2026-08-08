use std::{fs, process::Command};

use sgy_core::codec::parse_yaml_documents;
use tempfile::tempdir;

#[test]
fn cache_gc_runs_without_engine_discovery_and_emits_yaml() {
    let directory = tempdir().expect("temp directory");
    let workspace = directory.path().join("workspace");
    let user_cache = directory.path().join("user-cache");
    fs::create_dir(&workspace).expect("workspace");

    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.args(["cache", "gc"]).current_dir(&workspace);
    configure_cache_environment(&mut command, &user_cache);
    let output = command.output().expect("run sgy cache gc");

    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let documents = parse_yaml_documents(&output.stdout).expect("safe YAML");
    assert_eq!(documents.len(), 1);
    assert_eq!(documents[0]["schema"], "sgy.cache-gc/v1");
    assert_eq!(documents[0]["remaining_bytes"], 0);

    let mut invalid = Command::new(env!("CARGO_BIN_EXE_sgy"));
    invalid
        .args(["cache", "query", "../../outside"])
        .current_dir(&workspace);
    configure_cache_environment(&mut invalid, &user_cache);
    let invalid = invalid.output().expect("run invalid cache query");
    assert_eq!(invalid.status.code(), Some(123));
    assert!(invalid.stdout.is_empty());
    let stderr = String::from_utf8(invalid.stderr).expect("UTF-8 stderr");
    assert!(stderr.contains("cache id is invalid"));
    assert!(!stderr.contains("engine"));
}

#[cfg(windows)]
fn configure_cache_environment(command: &mut Command, root: &std::path::Path) {
    command.env("LOCALAPPDATA", root);
}

#[cfg(target_os = "macos")]
fn configure_cache_environment(command: &mut Command, root: &std::path::Path) {
    command.env("HOME", root);
}

#[cfg(all(unix, not(target_os = "macos")))]
fn configure_cache_environment(command: &mut Command, root: &std::path::Path) {
    command.env("XDG_CACHE_HOME", root);
}
