use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use srcq_core::engine::{
    EngineEnvironment, EngineError, SystemEngineEnvironment, VERSION_STREAM_LIMIT,
};

fn isolated_directory() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock should be after Unix epoch")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "srcq-engine-probe-test-{}-{nonce}",
        std::process::id()
    ))
}

fn copy_fixture(directory: &Path, name: &str) -> PathBuf {
    let source = Path::new(env!("CARGO_BIN_EXE_srcq-engine-fixture"));
    let extension = source.extension().and_then(|value| value.to_str());
    let file_name = extension.map_or_else(|| name.to_owned(), |value| format!("{name}.{value}"));
    let target = directory.join(file_name);
    fs::copy(source, &target).expect("copy engine fixture");
    target
}

#[test]
fn system_probe_enforces_timeout_and_stream_limit() {
    let directory = isolated_directory();
    fs::create_dir_all(&directory).expect("create isolated probe directory");
    let slow = copy_fixture(&directory, "slow-engine");
    let huge = copy_fixture(&directory, "huge-engine");
    let environment = SystemEngineEnvironment::from_path(None);

    assert!(matches!(
        environment.probe_version(&slow),
        Err(EngineError::ProbeTimeout(path)) if path == slow
    ));
    let output = environment
        .probe_version(&huge)
        .expect("oversized output probe should remain bounded");
    assert_eq!(output.stdout.len(), VERSION_STREAM_LIMIT);
    assert!(output.stdout_truncated);

    fs::remove_dir_all(&directory).expect("remove isolated probe directory");
}
