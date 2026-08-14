use std::{fs, path::Path, process::Command};

use serde_json::Value;
use sgy_core::codec::parse_yaml_documents;
use tempfile::tempdir;

fn exec_command(workspace: &Path, cache_root: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.current_dir(workspace).args([
        "exec",
        "--engine",
        env!("CARGO_BIN_EXE_sgy-native-fixture"),
    ]);
    configure_cache_environment(&mut command, cache_root);
    command
}

fn cache_command(workspace: &Path, cache_root: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.current_dir(workspace).arg("cache");
    configure_cache_environment(&mut command, cache_root);
    command
}

fn yaml(bytes: &[u8]) -> Vec<Value> {
    parse_yaml_documents(bytes).expect("safe YAML")
}

#[test]
fn token_safe_cache_modes_and_recovery_form_a_closed_loop() {
    let directory = tempdir().expect("temp directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("user-cache");
    fs::create_dir(&workspace).expect("workspace");

    let small = exec_command(&workspace, &cache_root)
        .args(["--", "run", "--fixture-matches=2"])
        .output()
        .expect("small token-safe run");
    assert_eq!(small.status.code(), Some(0));
    let small = yaml(&small.stdout);
    assert_eq!(small[0]["_sgy"]["total"], 2);
    assert_eq!(small[0]["_sgy"]["shown"], 2);
    assert_eq!(small[0]["_sgy"]["complete"], true);
    assert!(small[0]["_sgy"].get("cache").is_none());

    let large = exec_command(&workspace, &cache_root)
        .args([
            "--max-text-chars",
            "20",
            "--",
            "run",
            "--fixture-matches=45",
            "--fixture-text-chars=80",
        ])
        .output()
        .expect("large token-safe run");
    assert_eq!(large.status.code(), Some(0));
    let large = yaml(&large.stdout);
    assert_eq!(large[0]["_sgy"]["total"], 45);
    assert!(large[0]["_sgy"]["shown"].as_u64().expect("shown") <= 40);
    assert_eq!(large[0]["_sgy"]["complete"], false);
    let cache_id = large[0]["_sgy"]["cache"]
        .as_str()
        .expect("committed cache")
        .to_owned();

    let cache_info = cache_command(&workspace, &cache_root)
        .args(["info", &cache_id])
        .output()
        .expect("cache metadata");
    assert_eq!(cache_info.status.code(), Some(0));
    assert_eq!(
        yaml(&cache_info.stdout)[0]["engine"]["version"],
        "ast-grep fixture 0.0.0"
    );

    let recovered = cache_command(&workspace, &cache_root)
        .args(["get", &cache_id, "--result", "44", "--field", "/ordinal"])
        .output()
        .expect("recover omitted result");
    assert_eq!(recovered.status.code(), Some(0));
    assert_eq!(yaml(&recovered.stdout), vec![Value::from(44)]);

    let native_argv = cache_command(&workspace, &cache_root)
        .args(["get", &cache_id, "--result", "44", "--field", "/argv"])
        .output()
        .expect("recover native argv");
    assert_eq!(native_argv.status.code(), Some(0));
    let native_argv = yaml(&native_argv.stdout);
    assert!(native_argv[0]
        .as_array()
        .expect("argv array")
        .iter()
        .all(|value| !value
            .as_str()
            .is_some_and(|arg| arg.contains("max-results"))));

    let off = exec_command(&workspace, &cache_root)
        .args([
            "--cache",
            "off",
            "--max-detail-results",
            "3",
            "--",
            "run",
            "--fixture-matches=8",
        ])
        .output()
        .expect("cache-off run");
    assert_eq!(off.status.code(), Some(0));
    let off = yaml(&off.stdout);
    assert_eq!(off[0]["_sgy"]["total"], 8);
    assert_eq!(off[0]["_sgy"]["complete"], false);
    assert!(off[0]["_sgy"].get("cache").is_none());

    let on = exec_command(&workspace, &cache_root)
        .args(["--cache", "on", "--", "run", "--fixture-matches=1"])
        .output()
        .expect("cache-on run");
    assert_eq!(on.status.code(), Some(0));
    let on = yaml(&on.stdout);
    assert_eq!(on[0]["_sgy"]["complete"], true);
    assert!(on[0]["_sgy"]["cache"].is_string());

    let native_nonzero = exec_command(&workspace, &cache_root)
        .args([
            "--cache",
            "off",
            "--",
            "scan",
            "--fixture-matches=2",
            "--fixture-exit=7",
        ])
        .output()
        .expect("valid native nonzero context");
    assert_eq!(native_nonzero.status.code(), Some(7));
    assert_eq!(yaml(&native_nonzero.stdout)[0]["_sgy"]["total"], 2);
}

#[test]
fn lossless_remains_equivalent_and_cache_on_commits_native_bytes() {
    let directory = tempdir().expect("temp directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("user-cache");
    fs::create_dir(&workspace).expect("workspace");

    let automatic = exec_command(&workspace, &cache_root)
        .args(["--profile", "lossless", "--", "run", "--fixture-matches=2"])
        .output()
        .expect("automatic lossless run");
    assert_eq!(automatic.status.code(), Some(0));
    assert_eq!(yaml(&automatic.stdout).len(), 2);
    assert!(committed_cache_ids(&cache_root).is_empty());

    let cached = exec_command(&workspace, &cache_root)
        .args([
            "--profile",
            "lossless",
            "--cache",
            "on",
            "--",
            "run",
            "--fixture-matches=2",
        ])
        .output()
        .expect("cached lossless run");
    assert_eq!(cached.status.code(), Some(0));
    let documents = yaml(&cached.stdout);
    assert_eq!(documents.len(), 2);
    assert_eq!(documents[1]["ordinal"], 1);
    let ids = committed_cache_ids(&cache_root);
    assert_eq!(ids.len(), 1);
    assert!(platform_cache_root(&cache_root)
        .join(&ids[0])
        .join("native.jsonl")
        .is_file());
}

#[test]
fn profiles_formats_and_cache_failure_policy_are_end_to_end() {
    let directory = tempdir().expect("temp directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("user-cache");
    fs::create_dir(&workspace).expect("workspace");

    let files = exec_command(&workspace, &cache_root)
        .args([
            "--profile",
            "files",
            "--cache",
            "off",
            "--",
            "scan",
            "--fixture-matches=5",
        ])
        .output()
        .expect("files profile");
    assert_eq!(files.status.code(), Some(0));
    let files = yaml(&files.stdout);
    assert_eq!(files[0]["_sgy"]["profile"], "files");
    assert_eq!(files[0]["_sgy"]["total"], 5);
    assert!(files[0].get("results").is_none());

    let custom = exec_command(&workspace, &cache_root)
        .args([
            "--profile",
            "custom",
            "--keep-fields",
            "file,range,text,ordinal",
            "--prune-fields",
            "text",
            "--",
            "run",
            "--fixture-matches=2",
        ])
        .output()
        .expect("custom profile");
    assert_eq!(custom.status.code(), Some(0));
    let custom_bytes = custom.stdout.len();
    let custom = yaml(&custom.stdout);
    assert_eq!(custom[0]["_sgy"]["profile"], "custom");
    assert_eq!(custom[0]["_sgy"]["complete"], true);
    assert!(custom[0]["_sgy"].get("cache").is_none());
    assert_eq!(custom[0]["results"][1]["ordinal"], 1);
    assert!(custom[0]["results"][0].get("text").is_none());

    let locations = exec_command(&workspace, &cache_root)
        .args([
            "--profile",
            "locations",
            "--cache",
            "off",
            "--",
            "run",
            "--fixture-matches=2",
        ])
        .output()
        .expect("locations profile");
    assert_eq!(locations.status.code(), Some(0));
    assert!(locations.stdout.len() < custom_bytes);
    let locations = yaml(&locations.stdout);
    assert_eq!(locations[0]["_sgy"]["profile"], "locations");
    assert_eq!(locations[0]["_sgy"]["complete"], true);
    assert_eq!(
        locations[0]["results"],
        serde_json::json!(["src/0.ts:0:0-0:5", "src/1.ts:1:0-1:5"])
    );

    let limited_locations = exec_command(&workspace, &cache_root)
        .args([
            "--profile",
            "locations",
            "--max-detail-results",
            "1",
            "--",
            "run",
            "--fixture-matches=2",
        ])
        .output()
        .expect("limited locations profile");
    assert_eq!(limited_locations.status.code(), Some(0));
    let limited_locations = yaml(&limited_locations.stdout);
    assert_eq!(limited_locations[0]["_sgy"]["total"], 2);
    assert_eq!(limited_locations[0]["_sgy"]["shown"], 1);
    assert_eq!(limited_locations[0]["_sgy"]["omitted"], 1);
    assert_eq!(limited_locations[0]["_sgy"]["complete"], false);
    assert!(limited_locations[0]["_sgy"]["cache"].is_string());

    for native_format in ["--json=compact", "--format=sarif"] {
        let formatted = exec_command(&workspace, &cache_root)
            .args([
                "--cache",
                "off",
                "--",
                "scan",
                native_format,
                "--fixture-matches=3",
            ])
            .output()
            .expect("formatted context");
        assert_eq!(formatted.status.code(), Some(0), "{native_format}");
        let formatted = yaml(&formatted.stdout);
        assert_eq!(formatted[0]["_sgy"]["total"], 3, "{native_format}");
        assert_eq!(formatted[0]["_sgy"]["complete"], true, "{native_format}");
        assert_eq!(formatted[0]["results"][0]["file"], "src/0.ts");
        assert_eq!(formatted[0]["results"][0]["ruleId"], "rule-0");
        assert_eq!(formatted[0]["results"][0]["severity"], "warning");
        assert!(formatted[0]["results"][0].get("_sgy_unknown").is_none());
    }

    let unavailable_root = workspace.join("forbidden-cache-root");
    let small = exec_command(&workspace, &unavailable_root)
        .args(["--", "run", "--fixture-matches=1"])
        .output()
        .expect("small auto cache failure");
    assert_eq!(small.status.code(), Some(0));
    assert_eq!(yaml(&small.stdout)[0]["_sgy"]["complete"], true);

    let incomplete = exec_command(&workspace, &unavailable_root)
        .args([
            "--max-detail-results",
            "1",
            "--",
            "run",
            "--fixture-matches=2",
        ])
        .output()
        .expect("required auto cache failure");
    assert_eq!(incomplete.status.code(), Some(123));
    assert!(incomplete.stdout.is_empty());

    let required = exec_command(&workspace, &unavailable_root)
        .args(["--cache", "on", "--", "run", "--fixture-matches=1"])
        .output()
        .expect("cache-on preflight failure");
    assert_eq!(required.status.code(), Some(123));
    assert!(required.stdout.is_empty());

    let invalid_stream = exec_command(&workspace, &cache_root)
        .args(["--cache", "on", "--", "run", "--fixture-invalid"])
        .output()
        .expect("invalid context stream");
    assert_eq!(invalid_stream.status.code(), Some(121));
    assert!(invalid_stream.stdout.is_empty());
}

fn configure_cache_environment(command: &mut Command, root: &Path) {
    command.env("LOCALAPPDATA", root);
}

fn committed_cache_ids(environment_root: &Path) -> Vec<String> {
    let root = platform_cache_root(environment_root);
    let Ok(entries) = fs::read_dir(root) else {
        return Vec::new();
    };
    entries
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_dir()))
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|name| name.len() == 26)
        .collect()
}

fn platform_cache_root(environment_root: &Path) -> std::path::PathBuf {
    environment_root.join("sgy").join("cache").join("v1")
}
