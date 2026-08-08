use std::fs;
use std::path::Path;
use std::process::Command;

use sgy_core::codec::parse_yaml_documents;

fn isolated_command(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.current_dir(cwd);
    isolate_config_and_cache(&mut command, cwd);
    command
}

fn isolate_config_and_cache(command: &mut Command, root: &Path) {
    #[cfg(windows)]
    {
        command.env("APPDATA", root.join("appdata"));
        command.env("LOCALAPPDATA", root.join("localappdata"));
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        command.env("XDG_CONFIG_HOME", root.join("config"));
        command.env("XDG_CACHE_HOME", root.join("cache"));
    }
    #[cfg(target_os = "macos")]
    {
        command.env("HOME", root.join("home"));
    }
}

fn user_config_path(root: &Path) -> std::path::PathBuf {
    #[cfg(windows)]
    {
        root.join("appdata").join("sgy").join("config.yml")
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        root.join("config").join("sgy").join("config.yml")
    }
    #[cfg(target_os = "macos")]
    {
        root.join("home")
            .join("Library")
            .join("Application Support")
            .join("sgy")
            .join("config.yml")
    }
}

fn yaml(stdout: &[u8]) -> serde_json::Value {
    let documents = parse_yaml_documents(stdout).expect("safe YAML");
    assert_eq!(documents.len(), 1);
    documents.into_iter().next().expect("document")
}

#[test]
fn schema_and_capabilities_are_bounded_and_do_not_need_an_engine() {
    let temp = tempfile::tempdir().expect("tempdir");
    for (command_name, expected_schema) in [
        ("schema", "sgy.schema/v1"),
        ("capabilities", "sgy.capabilities/v1"),
    ] {
        let output = isolated_command(temp.path())
            .arg(command_name)
            .env("PATH", "")
            .output()
            .expect("inspection command");
        assert!(
            output.status.success(),
            "{command_name}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.len() < 128 * 1024);
        assert_eq!(yaml(&output.stdout)["schema"], expected_schema);
    }
}

#[test]
fn defaults_uses_explicit_project_user_builtin_priority_with_source_metadata() {
    let temp = tempfile::tempdir().expect("tempdir");
    fs::write(
        temp.path().join(".sgy.yml"),
        "schema: sgy.config/v1\nprofile: files\nmax_detail_results: 12\nmax_text_chars: 200\n",
    )
    .expect("project config");
    let user = user_config_path(temp.path());
    fs::create_dir_all(user.parent().expect("user parent")).expect("user config directory");
    fs::write(
        &user,
        "schema: sgy.config/v1\nprofile: lossless\ncache: off\nmax_detail_results: 30\nmax_text_chars: 300\nmax_context_bytes: 12000\n",
    )
    .expect("user config");

    let output = isolated_command(temp.path())
        .args(["defaults", "--max-detail-results", "7", "--", "scan", "src"])
        .output()
        .expect("defaults");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value = yaml(&output.stdout);
    assert_eq!(value["settings"]["profile"], "files");
    assert_eq!(value["settings"]["max_detail_results"], 7);
    assert_eq!(value["settings"]["max_text_chars"], 200);
    assert_eq!(value["settings"]["max_context_bytes"], 12000);
    assert_eq!(value["settings"]["cache"], "off");
    assert_eq!(value["settings"]["sources"]["profile"], "project");
    assert_eq!(
        value["settings"]["sources"]["max_detail_results"],
        "explicit"
    );
    assert_eq!(value["settings"]["sources"]["max_text_chars"], "project");
    assert_eq!(value["settings"]["sources"]["max_context_bytes"], "user");
    assert_eq!(value["settings"]["sources"]["cache"], "user");
}

#[test]
fn project_config_cannot_select_engine_expand_cwd_or_enable_cache_writes() {
    let temp = tempfile::tempdir().expect("tempdir");
    for field in ["engine: owned-engine", "cwd: ..", "cache: on"] {
        fs::write(
            temp.path().join(".sgy.yml"),
            format!("schema: sgy.config/v1\n{field}\n"),
        )
        .expect("project config");
        let output = isolated_command(temp.path())
            .args(["defaults", "--", "run"])
            .output()
            .expect("defaults");
        assert_eq!(output.status.code(), Some(125), "{field}");
        assert!(output.stdout.is_empty());
        assert!(String::from_utf8_lossy(&output.stderr).contains("forbidden in project config"));
    }
}

#[test]
fn doctor_separates_engine_config_cache_yaml_and_protocol_checks_without_scanning() {
    let temp = tempfile::tempdir().expect("tempdir");
    let output = isolated_command(temp.path())
        .args([
            "doctor",
            "--engine",
            env!("CARGO_BIN_EXE_sgy-native-fixture"),
        ])
        .output()
        .expect("doctor");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value = yaml(&output.stdout);
    assert_eq!(value["schema"], "sgy.doctor/v1");
    assert_eq!(value["ok"], true);
    assert_eq!(value["scan_executed"], false);
    assert_eq!(value["checks"]["config"]["status"], "ok");
    assert_eq!(value["checks"]["engine"]["status"], "ok");
    assert_eq!(value["checks"]["cache"]["status"], "not_created");
    assert_eq!(value["checks"]["yaml"]["status"], "ok");
    assert_eq!(value["checks"]["protocol"]["status"], "limited");
}

#[test]
fn doctor_returns_structured_failure_when_engine_is_missing_or_config_is_invalid() {
    let temp = tempfile::tempdir().expect("tempdir");
    let missing = isolated_command(temp.path())
        .arg("doctor")
        .env("PATH", "")
        .output()
        .expect("doctor missing engine");
    assert_eq!(missing.status.code(), Some(1));
    assert_eq!(
        yaml(&missing.stdout)["checks"]["engine"]["status"],
        "missing_or_invalid"
    );

    fs::write(temp.path().join(".sgy.yml"), "schema: future/v9\n").expect("invalid config");
    let invalid = isolated_command(temp.path())
        .args([
            "doctor",
            "--engine",
            env!("CARGO_BIN_EXE_sgy-native-fixture"),
        ])
        .output()
        .expect("doctor invalid config");
    assert_eq!(invalid.status.code(), Some(1));
    let value = yaml(&invalid.stdout);
    assert_eq!(value["checks"]["config"]["status"], "invalid");
    assert_eq!(value["scan_executed"], false);

    fs::write(
        temp.path().join(".sgy.yml"),
        "schema: sgy.config/v1\nprofile: token-safe\n",
    )
    .expect("valid config");
    let bad_cwd = isolated_command(temp.path())
        .args([
            "doctor",
            "--engine",
            env!("CARGO_BIN_EXE_sgy-native-fixture"),
            "--cwd",
            "missing-workspace",
        ])
        .output()
        .expect("doctor invalid cwd");
    assert_eq!(bad_cwd.status.code(), Some(1));
    assert_eq!(
        yaml(&bad_cwd.stdout)["checks"]["workspace"]["status"],
        "missing_or_inaccessible"
    );
}
