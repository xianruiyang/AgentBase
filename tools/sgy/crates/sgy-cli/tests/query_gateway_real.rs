use std::{fs, path::Path, process::Command};

use serde_json::Value;
use sgy_core::codec::parse_yaml_documents;

fn yaml(bytes: &[u8]) -> Value {
    parse_yaml_documents(bytes).expect("safe YAML")[0].clone()
}

fn sgy(cwd: &Path, local_app_data: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command.current_dir(cwd).env("LOCALAPPDATA", local_app_data);
    command
}

fn fixture() -> tempfile::TempDir {
    let directory = tempfile::tempdir().expect("fixture");
    fs::create_dir_all(directory.path().join("src/nested")).expect("nested");
    fs::write(
        directory.path().join("src/a.ts"),
        "alpha one\nalpha two\nbeta\n",
    )
    .expect("a.ts");
    fs::write(directory.path().join("src/nested/b.ts"), "alpha nested\n").expect("b.ts");
    fs::write(directory.path().join("-dash.txt"), "-needle\n").expect("dash");
    directory
}

#[test]
fn doctors_read_exact_supported_engines() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    for backend in ["rg", "fd"] {
        let output = sgy(directory.path(), local.path())
            .args([backend, "doctor"])
            .output()
            .expect("doctor");
        assert!(
            output.status.success(),
            "{backend}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(yaml(&output.stdout)["_sgy"]["ok"], true);
    }
}

#[test]
fn rg_groups_and_resumes_the_same_exact_snapshot() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let first = sgy(directory.path(), local.path())
        .args([
            "rg", "exec", "--view", "auto", "--limit", "1", "--", "-n", "-F", "alpha", ".",
        ])
        .output()
        .expect("first page");
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&first.stdout).lines().count(),
        1,
        "structured query results use one compact JSON line"
    );
    let first = yaml(&first.stdout);
    assert_eq!(first["_sgy"]["result_total"], 3);
    assert_eq!(first["_sgy"]["display_complete"], false);
    let snapshot = first["_sgy"]["query_snapshot"]
        .as_str()
        .expect("snapshot id");
    let cursor = first["_sgy"]["next_cursor"].as_str().expect("next cursor");
    let second = sgy(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--view",
            "auto",
            "--limit",
            "1",
            "--snapshot",
            snapshot,
            "--after",
            cursor,
            "--",
            "-n",
            "-F",
            "alpha",
            ".",
        ])
        .output()
        .expect("second page");
    assert!(second.status.success());
    let second = yaml(&second.stdout);
    assert_eq!(second["_sgy"]["query_snapshot"], snapshot);
    assert_eq!(second["_sgy"]["offset"], 1);
    assert_eq!(second["_sgy"]["view"], first["_sgy"]["view"]);
}

#[test]
fn rg_records_view_is_executable_and_keeps_content() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = sgy(directory.path(), local.path())
        .args([
            "rg", "exec", "--view", "records", "--", "-n", "-F", "alpha", ".",
        ])
        .output()
        .expect("records query");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["view"], "records");
    assert_eq!(document["records"].as_array().expect("records").len(), 3);
}

#[test]
fn rg_no_match_is_complete_and_keeps_native_exit_one() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = sgy(directory.path(), local.path())
        .args(["rg", "exec", "--", "-F", "absent", "."])
        .output()
        .expect("no match");
    assert_eq!(output.status.code(), Some(1));
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["result_total"], 0);
    assert_eq!(document["_sgy"]["result_complete"], true);
}

#[test]
fn fd_auto_tree_is_complete_and_print0_requires_artifact() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = sgy(directory.path(), local.path())
        .args(["fd", "exec", "--view", "auto", "--", ".", "."])
        .output()
        .expect("fd tree");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["result_complete"], true);
    assert!(
        document["_sgy"]["result_total"]
            .as_u64()
            .expect("result total")
            >= 4
    );

    let rejected = sgy(directory.path(), local.path())
        .args(["fd", "exec", "--", "--print0", ".", "."])
        .output()
        .expect("print0 rejection");
    assert_eq!(rejected.status.code(), Some(125));
    let artifact = directory.path().join("paths.bin");
    let accepted = sgy(directory.path(), local.path())
        .args([
            "fd",
            "exec",
            "--artifact-out",
            artifact.to_str().expect("artifact path is UTF-8"),
            "--",
            "--print0",
            ".",
            ".",
        ])
        .output()
        .expect("print0 artifact");
    assert!(accepted.status.success());
    assert!(fs::read(artifact).expect("read artifact").contains(&0));
}

#[test]
fn fd_snapshot_freezes_path_types_and_multi_root_aliases() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let first = sgy(directory.path(), local.path())
        .args([
            "fd", "exec", "--view", "flat", "--limit", "1", "--", "--type", "f", ".", "src",
        ])
        .output()
        .expect("first fd page");
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first = yaml(&first.stdout);
    let snapshot = first["_sgy"]["query_snapshot"]
        .as_str()
        .expect("snapshot id");
    let cursor = first["_sgy"]["next_cursor"].as_str().expect("next cursor");
    fs::remove_file(directory.path().join("src/nested/b.ts"))
        .expect("mutate current filesystem after snapshot");
    let second = sgy(directory.path(), local.path())
        .args([
            "fd",
            "exec",
            "--view",
            "flat",
            "--limit",
            "1",
            "--snapshot",
            snapshot,
            "--after",
            cursor,
            "--",
            "--type",
            "f",
            ".",
            "src",
        ])
        .output()
        .expect("second fd page");
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    let second = yaml(&second.stdout);
    assert_eq!(second["paths"][0]["path"], "src/nested/b.ts");
    assert_eq!(second["paths"][0]["type"], "file");
    let metadata_path = local
        .path()
        .join("sgy/query-spool-v1")
        .join(snapshot)
        .join("meta.json");
    let mut metadata: Value =
        serde_json::from_slice(&fs::read(&metadata_path).expect("read metadata"))
            .expect("parse metadata");
    metadata["fd_types"]["src/nested/b.ts"] = Value::String("dir".to_owned());
    fs::write(
        &metadata_path,
        serde_json::to_vec(&metadata).expect("serialize metadata"),
    )
    .expect("write metadata");
    let tampered = sgy(directory.path(), local.path())
        .args([
            "fd",
            "exec",
            "--view",
            "flat",
            "--snapshot",
            snapshot,
            "--",
            "--type",
            "f",
            ".",
            "src",
        ])
        .output()
        .expect("tampered fd snapshot");
    assert_eq!(tampered.status.code(), Some(125));
    assert!(String::from_utf8_lossy(&tampered.stderr).contains("identity mismatch"));

    let roots = sgy(directory.path(), local.path())
        .args(["fd", "exec", "--view", "tree", "--", ".", "src", "docs"])
        .output()
        .expect("multi-root tree");
    assert!(
        roots.status.success(),
        "{}",
        String::from_utf8_lossy(&roots.stderr)
    );
    let roots = yaml(&roots.stdout);
    assert_eq!(roots["root_aliases"]["R0"], "src");
    assert_eq!(roots["root_aliases"]["R1"], "docs");
    assert_eq!(
        roots["unmapped"].as_array().expect("unmapped array").len(),
        0
    );

    let based = sgy(directory.path(), local.path())
        .args([
            "fd", "exec", "--view", "flat", "--", "-Csrc", "--type", "f", ".", ".",
        ])
        .output()
        .expect("base-directory paths");
    assert!(
        based.status.success(),
        "{}",
        String::from_utf8_lossy(&based.stderr)
    );
    let based = yaml(&based.stdout);
    assert!(based["paths"]
        .as_array()
        .expect("path array")
        .iter()
        .all(|path| path["type"] == "file"));
}

#[test]
fn help_is_bounded_unless_raw_or_artifact_is_explicit() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = sgy(directory.path(), local.path())
        .args(["rg", "exec", "--limit", "3", "--", "--help"])
        .output()
        .expect("bounded help");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["displayed_lines"], 3);
    assert_eq!(document["_sgy"]["display_complete"], false);
}

#[test]
fn artifact_is_an_exact_native_escape_for_adaptive_modes() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let artifact = directory.path().join("rg-native.bin");
    let wrapped = sgy(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--artifact-out",
            artifact.to_str().expect("artifact path is UTF-8"),
            "--",
            "-n",
            "-F",
            "alpha",
            "src/a.ts",
        ])
        .output()
        .expect("artifact escape");
    assert!(
        wrapped.status.success(),
        "{}",
        String::from_utf8_lossy(&wrapped.stderr)
    );
    let native = Command::new("rg.exe")
        .current_dir(directory.path())
        .args(["-n", "-F", "alpha", "src/a.ts"])
        .output()
        .expect("native rg");
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(fs::read(artifact).expect("read artifact"), native.stdout);
    let manifest = yaml(&wrapped.stdout);
    assert_eq!(manifest["_sgy"]["schema"], "sgy.query.artifact/v1");
}

#[test]
fn native_option_delimiter_keeps_dash_prefixed_patterns_positional() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let rg = sgy(directory.path(), local.path())
        .args(["rg", "exec", "--", "-F", "--", "-needle", "."])
        .output()
        .expect("dash rg pattern");
    assert!(
        rg.status.success(),
        "{}",
        String::from_utf8_lossy(&rg.stderr)
    );
    let rg = yaml(&rg.stdout);
    assert_eq!(rg["_sgy"]["result_total"], 1);
    assert_eq!(rg["_sgy"]["mode"], "RG-SEARCH-TEXT");

    let fd = sgy(directory.path(), local.path())
        .args(["fd", "exec", "--view", "flat", "--", "--", "-dash", "."])
        .output()
        .expect("dash fd pattern");
    assert!(
        fd.status.success(),
        "{}",
        String::from_utf8_lossy(&fd.stderr)
    );
    let fd = yaml(&fd.stdout);
    assert_eq!(fd["paths"][0]["path"], "-dash.txt");
    assert_eq!(fd["_sgy"]["mode"], "FD-PATHS");
}

#[test]
fn native_error_is_bounded_and_never_reported_as_a_complete_empty_query() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = sgy(directory.path(), local.path())
        .args(["rg", "exec", "--max-text-chars", "40", "--", "(", "."])
        .output()
        .expect("invalid rg pattern");
    assert_eq!(output.status.code(), Some(2));
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["result_complete"], false);
    assert!(
        output.stderr.len() < 2_000,
        "stderr must remain model-visible bounded"
    );
    assert!(String::from_utf8_lossy(&output.stderr).contains("native:"));
}

#[test]
fn explicit_rg_json_files_and_count_modes_remain_usable() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let json_output = sgy(directory.path(), local.path())
        .args([
            "rg", "exec", "--", "--json", "--sort", "path", "-F", "alpha", ".",
        ])
        .output()
        .expect("json");
    assert!(json_output.status.success());
    assert_eq!(yaml(&json_output.stdout)["_sgy"]["mode"], "RG-SEARCH-JSON");
    let lossless_output = sgy(directory.path(), local.path())
        .args([
            "rg", "exec", "--view", "lossless", "--", "--json", "--sort", "path", "-F", "alpha",
            ".",
        ])
        .output()
        .expect("lossless json");
    assert!(lossless_output.status.success());
    let lossless = yaml(&lossless_output.stdout);
    assert!(lossless["events"]
        .as_array()
        .expect("lossless events")
        .iter()
        .any(|event| event["type"] == "summary"));
    assert!(
        lossless["_sgy"]["result_total"]
            .as_u64()
            .expect("result total")
            > 6
    );

    let files_output = sgy(directory.path(), local.path())
        .args([
            "rg", "exec", "--view", "files", "--", "--files", "--sort", "path", ".",
        ])
        .output()
        .expect("files");
    assert!(files_output.status.success());
    let files = yaml(&files_output.stdout);
    assert_eq!(files["_sgy"]["mode"], "RG-FILES");
    assert!(files["files"].as_array().expect("files array").len() >= 2);

    let count_output = sgy(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--",
            "--count-matches",
            "--sort",
            "path",
            "-F",
            "alpha",
            ".",
        ])
        .output()
        .expect("count");
    assert!(count_output.status.success());
    let counts = yaml(&count_output.stdout);
    assert_eq!(counts["_sgy"]["mode"], "RG-COUNT-MATCHES");
    assert_eq!(counts["counts"].as_array().expect("counts array").len(), 2);

    let invalid_view = sgy(directory.path(), local.path())
        .args(["rg", "exec", "--view", "grouped", "--", "--files", "."])
        .output()
        .expect("invalid mode view");
    assert_eq!(invalid_view.status.code(), Some(125));
}
