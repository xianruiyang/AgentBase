use std::{ffi::OsString, fs, path::PathBuf, time::SystemTime};

use srcq_core::{
    adapters::write::WriteIntent,
    budget::BudgetSettings,
    cache::{CacheAudit, CacheLimits, CacheMode, CacheStore, SourceFormat},
    codec::{parse_yaml_documents, JsonInputKind},
    context_batch::{run_profile_batch, CachePlan, ProfileBatchRequest},
    invocation::Profile,
    process::ProcessRequest,
    profile::FieldPaths,
};
use tempfile::tempdir;

fn engine() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_srcq-stress-engine"))
}

#[test]
fn large_jsonl_dual_stream_cache_and_context_remain_bounded() {
    const RECORDS: u64 = 100_000;
    let directory = tempdir().expect("stress directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache");
    fs::create_dir(&workspace).expect("workspace");
    let user_argv = vec![
        OsString::from("run"),
        OsString::from("--stress-records=100000"),
        OsString::from("--stress-stderr=4194304"),
        OsString::from(";touch SHOULD_NOT_EXIST"),
    ];
    let mut process = ProcessRequest::new(engine(), &workspace);
    process.args = user_argv.clone();
    process.forward_stderr = false;
    let store = CacheStore::open(&cache_root, Some(&workspace), CacheLimits::default())
        .expect("cache store");
    let engine_path = engine();
    let audit = CacheAudit::from_argv(
        engine_path,
        "0.42.0",
        workspace.clone(),
        &user_argv,
        &user_argv,
        Vec::new(),
        Profile::TokenSafe,
        CacheMode::Auto,
    );
    let outcome = run_profile_batch(ProfileBatchRequest {
        process,
        input_kind: JsonInputKind::Lines,
        source_format: SourceFormat::JsonLines,
        profile: Profile::TokenSafe,
        budget: BudgetSettings::new(40, 400, 24 * 1024).expect("budget"),
        keep_fields: None,
        prune_fields: FieldPaths::default(),
        cache: CachePlan::ready(store, audit),
        now: SystemTime::now(),
        write_intent: WriteIntent::None,
        stderr_sidecar: None,
    })
    .expect("large batch");

    assert!(outcome.process.output.stdout_bytes > 10 * 1024 * 1024);
    assert_eq!(outcome.process.output.stderr_bytes, 4 * 1024 * 1024);
    let yaml = outcome
        .yaml
        .expect("bounded YAML")
        .read()
        .expect("YAML bytes");
    assert!(yaml.len() <= 24 * 1024);
    assert!(!yaml
        .windows("SOURCE_LEAK_SENTINEL".len())
        .any(|window| window == b"SOURCE_LEAK_SENTINEL"));
    let document = parse_yaml_documents(&yaml).expect("safe YAML");
    assert_eq!(document[0]["_sgy"]["total"], RECORDS);
    assert!(document[0]["_sgy"]["shown"].as_u64().expect("shown") <= 40);
    assert!(!workspace.join("SHOULD_NOT_EXIST").exists());
    let cache_id = outcome.cache_id.expect("auto cache for omitted results");
    let verified = CacheStore::open(&cache_root, Some(&workspace), CacheLimits::default())
        .expect("reopen store")
        .open_verified(&cache_id, SystemTime::now())
        .expect("verify cache");
    assert_eq!(verified.record_count(), RECORDS);
    let metadata = fs::read_to_string(cache_root.join(&cache_id).join("metadata.yaml"))
        .expect("cache metadata");
    assert!(!metadata.contains("SHOULD_NOT_EXIST"));
}
