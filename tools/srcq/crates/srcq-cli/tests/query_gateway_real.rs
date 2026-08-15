use std::{fs, path::Path, process::Command};

use serde_json::Value;
use srcq_core::codec::parse_yaml_documents;

fn yaml(bytes: &[u8]) -> Value {
    parse_yaml_documents(bytes).expect("safe YAML")[0].clone()
}

fn srcq(cwd: &Path, local_app_data: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
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
        let output = srcq(directory.path(), local.path())
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
    let first = srcq(directory.path(), local.path())
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
    assert_eq!(first["_sgy"]["complete"]["display"], false);
    let snapshot = first["_sgy"]["query_snapshot"]
        .as_str()
        .expect("snapshot id");
    let cursor = first["_sgy"]["next_cursor"].as_str().expect("next cursor");
    let second = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--view",
            "auto",
            "--limit",
            "1",
            "--receipt",
            "full",
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
    assert_eq!(second["_sgy"]["view"], "grouped");
}

#[test]
fn rg_records_view_is_executable_and_keeps_content() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--view",
            "records",
            "--receipt",
            "full",
            "--",
            "-n",
            "-F",
            "alpha",
            ".",
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
fn default_receipt_is_sparse_and_full_receipt_keeps_diagnostics() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let sparse = srcq(directory.path(), local.path())
        .args(["rg", "exec", "--", "-F", "beta", "src/a.ts"])
        .output()
        .expect("sparse receipt");
    assert!(sparse.status.success());
    let sparse = yaml(&sparse.stdout);
    assert_eq!(sparse["_sgy"]["schema"], "sgy.query.result/v2");
    assert_eq!(sparse["_sgy"]["result_total"], 1);
    assert_eq!(sparse["_sgy"]["complete"]["result"], true);
    assert_eq!(sparse["_sgy"]["complete"]["display"], true);
    assert_eq!(sparse["_sgy"]["complete"]["content"], true);
    for omitted in [
        "backend",
        "engine_version",
        "mode",
        "view",
        "native_exit",
        "query_snapshot",
        "displayed",
        "omitted",
        "offset",
        "next_cursor",
        "stdout_bytes",
        "stderr_bytes",
    ] {
        assert!(
            sparse["_sgy"].get(omitted).is_none(),
            "default receipt unexpectedly contains {omitted}"
        );
    }

    let full = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--receipt",
            "full",
            "--",
            "-F",
            "beta",
            "src/a.ts",
        ])
        .output()
        .expect("full receipt");
    assert!(full.status.success());
    let full = yaml(&full.stdout);
    assert_eq!(full["_sgy"]["schema"], "sgy.query.result/v1");
    assert_eq!(full["_sgy"]["backend"], "rg");
    assert!(full["_sgy"]["engine_version"].is_string());
    assert!(full["_sgy"]["query_snapshot"].is_string());
}

#[test]
fn semantic_views_page_their_own_result_units() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");

    let summary = srcq(directory.path(), local.path())
        .args([
            "rg", "exec", "--view", "summary", "--limit", "1", "--", "-n", "-F", "alpha", ".",
        ])
        .output()
        .expect("summary query");
    assert!(summary.status.success());
    let summary = yaml(&summary.stdout);
    assert_eq!(summary["summary"]["matches"], 3);
    assert_eq!(summary["_sgy"]["result_total"], 3);
    assert_eq!(summary["_sgy"]["complete"]["display"], true);
    assert_eq!(summary["_sgy"]["complete"]["content"], false);
    assert!(summary["_sgy"].get("next_cursor").is_none());

    let full_summary = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--view",
            "summary",
            "--limit",
            "1",
            "--receipt",
            "full",
            "--",
            "-n",
            "-F",
            "alpha",
            ".",
        ])
        .output()
        .expect("full summary query");
    assert!(full_summary.status.success());
    let full_summary = yaml(&full_summary.stdout);
    assert_eq!(full_summary["_sgy"]["displayed"], 3);
    assert_eq!(full_summary["_sgy"]["omitted"], 0);
    assert_eq!(full_summary["_sgy"]["display_complete"], true);
    assert!(full_summary["_sgy"]["next_cursor"].is_null());

    let files = srcq(directory.path(), local.path())
        .args([
            "rg", "exec", "--view", "files", "--limit", "1", "--", "-n", "-F", "alpha", ".",
        ])
        .output()
        .expect("files query");
    assert!(files.status.success());
    let files = yaml(&files.stdout);
    assert_eq!(files["_sgy"]["result_total"], 2);
    assert_eq!(files["files"].as_array().expect("files").len(), 1);
    assert!(files["_sgy"]["next_cursor"].is_string());

    let locations = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--view",
            "locations",
            "--limit",
            "1",
            "--",
            "-n",
            "-C",
            "1",
            "-F",
            "alpha",
            ".",
        ])
        .output()
        .expect("locations query");
    assert!(locations.status.success());
    let locations = yaml(&locations.stdout);
    assert_eq!(locations["_sgy"]["result_total"], 3);
    assert_eq!(
        locations["locations"].as_array().expect("locations").len(),
        1
    );
}

#[test]
fn complete_sparse_queries_do_not_leave_unusable_snapshots() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = srcq(directory.path(), local.path())
        .args(["rg", "exec", "--", "-F", "beta", "src/a.ts"])
        .output()
        .expect("complete sparse query");
    assert!(output.status.success());
    assert!(
        !local.path().join("srcq/query-spool-v1").exists(),
        "a complete sparse receipt exposes no cursor and should not persist a snapshot"
    );
}

#[test]
fn summary_views_are_terminal_across_structured_modes() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let cases = [
        vec![
            "fd", "exec", "--view", "summary", "--limit", "1", "--", ".", ".",
        ],
        vec![
            "rg", "exec", "--view", "summary", "--limit", "1", "--", "--files", ".",
        ],
        vec![
            "rg", "exec", "--view", "summary", "--limit", "1", "--", "-c", "-F", "alpha", ".",
        ],
        vec![
            "rg",
            "exec",
            "--view",
            "summary",
            "--limit",
            "1",
            "--",
            "--vimgrep",
            "-F",
            "alpha",
            ".",
        ],
    ];
    for args in cases {
        let output = srcq(directory.path(), local.path())
            .args(args)
            .output()
            .expect("summary mode");
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let document = yaml(&output.stdout);
        assert_eq!(document["_sgy"]["complete"]["display"], true);
        assert!(document["_sgy"].get("next_cursor").is_none());
    }
}

#[test]
fn rg_no_match_is_complete_and_keeps_native_exit_one() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = srcq(directory.path(), local.path())
        .args(["rg", "exec", "--", "-F", "absent", "."])
        .output()
        .expect("no match");
    assert_eq!(output.status.code(), Some(1));
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["result_total"], 0);
    assert_eq!(document["_sgy"]["complete"]["result"], true);
    assert_eq!(document["_sgy"]["native_exit"], 1);
}

#[test]
fn fd_auto_tree_is_complete_and_print0_requires_artifact() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let output = srcq(directory.path(), local.path())
        .args(["fd", "exec", "--view", "auto", "--", ".", "."])
        .output()
        .expect("fd tree");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["complete"]["result"], true);
    assert!(
        document["_sgy"]["result_total"]
            .as_u64()
            .expect("result total")
            >= 4
    );

    let rejected = srcq(directory.path(), local.path())
        .args(["fd", "exec", "--", "--print0", ".", "."])
        .output()
        .expect("print0 rejection");
    assert_eq!(rejected.status.code(), Some(125));
    let artifact = directory.path().join("paths.bin");
    let accepted = srcq(directory.path(), local.path())
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
    let first = srcq(directory.path(), local.path())
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
    let second = srcq(directory.path(), local.path())
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
        .join("srcq/query-spool-v1")
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
    let tampered = srcq(directory.path(), local.path())
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

    let roots = srcq(directory.path(), local.path())
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

    let based = srcq(directory.path(), local.path())
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
    let output = srcq(directory.path(), local.path())
        .args(["rg", "exec", "--limit", "3", "--", "--help"])
        .output()
        .expect("bounded help");
    assert!(output.status.success());
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["schema"], "sgy.query.bounded-text/v2");
    assert_eq!(document["_sgy"]["displayed_lines"], 3);
    assert_eq!(document["_sgy"]["complete"]["display"], false);
    assert!(document["_sgy"].get("backend").is_none());
}

#[test]
fn artifact_is_an_exact_native_escape_for_adaptive_modes() {
    let directory = fixture();
    let local = tempfile::tempdir().expect("local app data");
    let artifact = directory.path().join("rg-native.bin");
    let wrapped = srcq(directory.path(), local.path())
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
    let rg = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--receipt",
            "full",
            "--",
            "-F",
            "--",
            "-needle",
            ".",
        ])
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

    let fd = srcq(directory.path(), local.path())
        .args([
            "fd",
            "exec",
            "--view",
            "flat",
            "--receipt",
            "full",
            "--",
            "--",
            "-dash",
            ".",
        ])
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
    let output = srcq(directory.path(), local.path())
        .args(["rg", "exec", "--max-text-chars", "40", "--", "(", "."])
        .output()
        .expect("invalid rg pattern");
    assert_eq!(output.status.code(), Some(2));
    let document = yaml(&output.stdout);
    assert_eq!(document["_sgy"]["complete"]["result"], false);
    assert_eq!(document["_sgy"]["native_exit"], 2);
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
    let json_output = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--receipt",
            "full",
            "--",
            "--json",
            "--sort",
            "path",
            "-F",
            "alpha",
            ".",
        ])
        .output()
        .expect("json");
    assert!(json_output.status.success());
    assert_eq!(yaml(&json_output.stdout)["_sgy"]["mode"], "RG-SEARCH-JSON");
    let lossless_output = srcq(directory.path(), local.path())
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

    let files_output = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--view",
            "files",
            "--receipt",
            "full",
            "--",
            "--files",
            "--sort",
            "path",
            ".",
        ])
        .output()
        .expect("files");
    assert!(files_output.status.success());
    let files = yaml(&files_output.stdout);
    assert_eq!(files["_sgy"]["mode"], "RG-FILES");
    assert!(files["files"].as_array().expect("files array").len() >= 2);

    let count_output = srcq(directory.path(), local.path())
        .args([
            "rg",
            "exec",
            "--receipt",
            "full",
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

    let invalid_view = srcq(directory.path(), local.path())
        .args(["rg", "exec", "--view", "grouped", "--", "--files", "."])
        .output()
        .expect("invalid mode view");
    assert_eq!(invalid_view.status.code(), Some(125));
}
