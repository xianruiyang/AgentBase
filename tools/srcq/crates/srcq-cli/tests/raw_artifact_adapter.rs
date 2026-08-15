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

fn yaml(bytes: &[u8]) -> Value {
    parse_yaml_documents(bytes).expect("safe YAML output")[0].clone()
}

#[test]
fn test_help_and_version_are_utf8_raw_yaml_with_separate_stderr() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    for (args, kind) in [
        (vec!["test", "--fixture-matches=1"], "test"),
        (vec!["--help"], "help"),
        (vec!["--version"], "version"),
    ] {
        let output = srcq(directory.path())
            .arg("--")
            .args(args)
            .output()
            .expect("raw command");
        assert!(output.status.success(), "kind {kind}");
        let document = yaml(&output.stdout);
        assert_eq!(document["_sgy"]["schema"], "sgy.raw/v1");
        assert_eq!(document["_sgy"]["kind"], kind);
        assert!(document["stdout"].is_string());
        if document["stdout"]
            .as_str()
            .is_some_and(|text| text.contains('\n'))
        {
            assert!(String::from_utf8_lossy(&output.stdout).contains("\"stdout\": |"));
        }
        assert!(!String::from_utf8_lossy(&output.stdout).contains("fixture inspect summary"));
    }

    let diagnostic = srcq(directory.path())
        .args(["--", "test", "--inspect=summary", "--fixture-matches=1"])
        .output()
        .expect("raw diagnostic");
    assert!(String::from_utf8_lossy(&diagnostic.stderr).contains("fixture inspect summary"));
    assert!(!String::from_utf8_lossy(&diagnostic.stdout).contains("fixture inspect summary"));
}

#[test]
fn non_interactive_new_preserves_side_effects_and_interactive_new_is_rejected() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let created = directory.path().join("created.txt");
    let output = srcq(directory.path())
        .args([
            "--",
            "new",
            "project",
            "-y",
            &format!("--fixture-create={}", created.display()),
        ])
        .output()
        .expect("non-interactive new");
    assert!(output.status.success());
    assert_eq!(yaml(&output.stdout)["_sgy"]["kind"], "new");
    assert_eq!(
        std::fs::read_to_string(&created).expect("created file"),
        "created by native fixture\n"
    );

    let rejected = directory.path().join("must-not-exist.txt");
    let output = srcq(directory.path())
        .args([
            "--",
            "new",
            "project",
            &format!("--fixture-create={}", rejected.display()),
        ])
        .output()
        .expect("interactive new rejection");
    assert_eq!(output.status.code(), Some(125));
    assert!(!rejected.exists());
}

#[test]
fn completions_requires_artifact_before_engine_discovery() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = Command::new(env!("CARGO_BIN_EXE_srcq"))
        .current_dir(directory.path())
        .args([
            "exec",
            "--engine",
            "definitely-missing-ast-grep.exe",
            "--",
            "completions",
            "powershell",
        ])
        .output()
        .expect("missing artifact rejection");
    assert_eq!(output.status.code(), Some(125));
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("requires explicit --artifact-out"));
    assert!(!String::from_utf8_lossy(&output.stderr).contains("engine"));
}

#[test]
fn completion_artifact_is_exact_and_manifest_can_use_yaml_out() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let artifact = directory.path().join("completion.ps1");
    let manifest = directory.path().join("manifest.yaml");
    let output = srcq(directory.path())
        .args([
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--yaml-out",
            manifest.to_str().expect("UTF-8 manifest path"),
            "--",
            "completions",
            "powershell",
        ])
        .output()
        .expect("completion artifact");
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    let expected = b"# completion fixture\ncomplete -c ast-grep\n";
    assert_eq!(std::fs::read(&artifact).expect("artifact bytes"), expected);
    let document = yaml(&std::fs::read(&manifest).expect("manifest YAML"));
    assert_eq!(document["schema"], "sgy.output-manifest/v1");
    assert_eq!(document["kind"], "artifact");
    assert_eq!(document["bytes"], expected.len() as u64);
    assert_eq!(document["media_type"], "text/x-powershell");
    assert_eq!(document["encoding"], "utf-8");
    let hash = document["sha256"].as_str().expect("sha256");
    assert_eq!(hash.len(), 64);
    assert!(hash.chars().all(|character| character.is_ascii_hexdigit()));
}

#[test]
fn invalid_utf8_requires_artifact_and_never_uses_replacement_characters() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let rejected = srcq(directory.path())
        .args(["--", "test", "--fixture-invalid-utf8"])
        .output()
        .expect("invalid UTF-8 rejection");
    assert_eq!(rejected.status.code(), Some(121));
    assert!(rejected.stdout.is_empty());

    let artifact = directory.path().join("raw.bin");
    let accepted = srcq(directory.path())
        .args([
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--",
            "test",
            "--fixture-invalid-utf8",
        ])
        .output()
        .expect("binary artifact");
    assert!(accepted.status.success());
    assert_eq!(
        std::fs::read(&artifact).expect("raw artifact"),
        [b'r', 0xff, b'w']
    );
    let document = yaml(&accepted.stdout);
    assert_eq!(document["encoding"], "binary");
    assert!(document.get("text").is_none());
}

#[test]
fn debug_artifact_uses_diagnostic_bytes_not_normal_stdout() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let artifact = directory.path().join("debug.txt");
    let output = srcq(directory.path())
        .args([
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--",
            "run",
            "--debug-query=ast",
        ])
        .output()
        .expect("debug artifact");
    assert!(output.status.success());
    assert_eq!(
        std::fs::read_to_string(&artifact).expect("debug artifact"),
        "fixture debug query\n"
    );
    assert!(String::from_utf8_lossy(&output.stderr).contains("fixture debug query"));
    assert_eq!(yaml(&output.stdout)["media_type"], "text/plain");
}

#[test]
fn stderr_sidecar_inlines_small_utf8_and_externalizes_binary_or_large_bytes() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let text_sidecar = directory.path().join("stderr-text.yaml");
    let text = srcq(directory.path())
        .args([
            "--stderr-yaml",
            text_sidecar.to_str().expect("UTF-8 sidecar path"),
            "--",
            "run",
            "--inspect=summary",
            "--fixture-matches=1",
        ])
        .output()
        .expect("UTF-8 stderr sidecar");
    assert!(text.status.success());
    let document = yaml(&std::fs::read(&text_sidecar).expect("text sidecar"));
    assert_eq!(document["schema"], "sgy.stderr/v1");
    assert_eq!(document["encoding"], "utf-8");
    assert_eq!(document["text"], "fixture inspect summary\n");
    assert!(document.get("raw_path").is_none());

    let binary_sidecar = directory.path().join("stderr-binary.yaml");
    let binary = srcq(directory.path())
        .args([
            "--stderr-yaml",
            binary_sidecar.to_str().expect("UTF-8 sidecar path"),
            "--",
            "test",
            "--fixture-stderr-invalid",
        ])
        .output()
        .expect("binary stderr sidecar");
    assert!(binary.status.success());
    let document = yaml(&std::fs::read(&binary_sidecar).expect("binary sidecar"));
    assert_eq!(document["encoding"], "binary");
    assert!(document.get("text").is_none());
    let raw = Path::new(document["raw_path"].as_str().expect("raw path"));
    assert_eq!(std::fs::read(raw).expect("raw stderr"), [b'e', 0xff, b'\n']);

    let large_sidecar = directory.path().join("stderr-large.yaml");
    let large = srcq(directory.path())
        .args([
            "--stderr-yaml",
            large_sidecar.to_str().expect("UTF-8 sidecar path"),
            "--",
            "test",
            "--fixture-stderr-bytes=1048577",
        ])
        .output()
        .expect("large stderr sidecar");
    assert!(large.status.success());
    let document = yaml(&std::fs::read(&large_sidecar).expect("large sidecar"));
    assert_eq!(document["encoding"], "utf-8");
    assert_eq!(document["bytes"], 1_048_577);
    assert!(document.get("text").is_none());
    let raw = Path::new(document["raw_path"].as_str().expect("large raw path"));
    assert_eq!(
        std::fs::metadata(raw).expect("large raw stderr").len(),
        1_048_577
    );
}

#[test]
fn output_path_collisions_are_rejected_before_native_side_effects() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let collision = directory.path().join("same.out");
    let marker = directory.path().join("must-not-exist.txt");
    let output = srcq(directory.path())
        .args([
            "--yaml-out",
            collision.to_str().expect("UTF-8 collision path"),
            "--artifact-out",
            collision.to_str().expect("UTF-8 collision path"),
            "--",
            "test",
            &format!("--fixture-create={}", marker.display()),
        ])
        .output()
        .expect("path collision");
    assert_eq!(output.status.code(), Some(125));
    assert!(!marker.exists());
    assert!(!collision.exists());
}

#[test]
fn raw_nonzero_keeps_native_exit_and_valid_report() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let output = srcq(directory.path())
        .args(["--", "test", "--fixture-matches=1", "--fixture-exit=7"])
        .output()
        .expect("nonzero raw report");
    assert_eq!(output.status.code(), Some(7));
    assert_eq!(yaml(&output.stdout)["stdout"], "native text output\n");
}

#[test]
fn native_new_side_effect_is_not_rolled_back_when_yaml_commit_loses_a_race() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let yaml_target = directory.path().join("new-output.yaml");
    let output = srcq(directory.path())
        .args([
            "--yaml-out",
            yaml_target.to_str().expect("UTF-8 YAML path"),
            "--",
            "new",
            "project",
            "-y",
            &format!("--fixture-create={}", yaml_target.display()),
        ])
        .output()
        .expect("new output race");
    assert_eq!(output.status.code(), Some(127));
    assert_eq!(
        std::fs::read_to_string(&yaml_target).expect("native side effect"),
        "created by native fixture\n"
    );
    assert!(String::from_utf8_lossy(&output.stderr).contains("may have created or changed files"));
}

#[test]
fn common_text_adapter_can_commit_an_explicit_stderr_sidecar() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let sidecar = directory.path().join("debug-stderr.yaml");
    let output = srcq(directory.path())
        .args([
            "--stderr-yaml",
            sidecar.to_str().expect("UTF-8 sidecar path"),
            "--",
            "run",
            "--debug-query=ast",
        ])
        .output()
        .expect("bounded text stderr sidecar");
    assert!(output.status.success());
    assert_eq!(yaml(&output.stdout)["_sgy"]["kind"], "text");
    assert_eq!(
        yaml(&std::fs::read(&sidecar).expect("debug sidecar"))["text"],
        "fixture debug query\n"
    );
}

#[test]
fn interactive_test_requires_a_real_tty_before_native_start() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let marker = directory.path().join("must-not-exist.txt");
    let output = srcq(directory.path())
        .args([
            "--",
            "test",
            "-i",
            &format!("--fixture-create={}", marker.display()),
        ])
        .output()
        .expect("interactive test rejection");
    assert_eq!(output.status.code(), Some(125));
    assert!(!marker.exists());
    assert!(String::from_utf8_lossy(&output.stderr).contains("E_TTY_UNAVAILABLE"));
}

#[test]
fn test_update_side_effect_survives_raw_output_failure_without_rollback_claim() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let marker = directory.path().join("snapshot.txt");
    let output = srcq(directory.path())
        .args([
            "--",
            "test",
            "-U",
            "--fixture-invalid-utf8",
            &format!("--fixture-create={}", marker.display()),
        ])
        .output()
        .expect("test update output failure");
    assert_eq!(output.status.code(), Some(121));
    assert!(marker.exists());
    assert!(String::from_utf8_lossy(&output.stderr).contains("no transaction or rollback"));
}

#[test]
fn artifact_target_changed_by_native_command_is_not_overwritten() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let artifact = directory.path().join("completion.ps1");
    let manifest = directory.path().join("manifest.yaml");
    let output = srcq(directory.path())
        .args([
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--yaml-out",
            manifest.to_str().expect("UTF-8 manifest path"),
            "--",
            "completions",
            "powershell",
            &format!("--fixture-create={}", artifact.display()),
        ])
        .output()
        .expect("artifact race");
    assert_eq!(output.status.code(), Some(127));
    assert_eq!(
        std::fs::read_to_string(&artifact).expect("native artifact mutation"),
        "created by native fixture\n"
    );
    assert!(!manifest.exists());
}

#[test]
fn explicit_artifact_can_preserve_native_files_output_bytes() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let artifact = directory.path().join("files.txt");
    let output = srcq(directory.path())
        .args([
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--",
            "run",
            "--files-with-matches",
            "--fixture-files=2",
        ])
        .output()
        .expect("files artifact");
    assert!(output.status.success());
    assert_eq!(
        std::fs::read_to_string(&artifact).expect("files artifact"),
        "src/file 0-中文.ts\nsrc/file 1-中文.ts\n"
    );
    assert_eq!(yaml(&output.stdout)["encoding"], "utf-8");
}
