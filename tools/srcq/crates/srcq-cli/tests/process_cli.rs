use std::{
    fs,
    io::Write,
    path::Path,
    process::{Command, Stdio},
};

use serde_json::{json, Value};
use srcq_core::codec::parse_yaml_documents;
use tempfile::tempdir;

fn process(workspace: &Path, cache_root: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
    command.current_dir(workspace).arg("process");
    configure_cache_environment(&mut command, cache_root);
    command
}

fn run_stdin(mut command: Command, input: &[u8]) -> std::process::Output {
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command.spawn().expect("spawn srcq process");
    child
        .stdin
        .take()
        .expect("piped stdin")
        .write_all(input)
        .expect("write process input");
    child.wait_with_output().expect("process output")
}

fn yaml(bytes: &[u8]) -> Vec<Value> {
    parse_yaml_documents(bytes).expect("safe process YAML")
}

#[test]
fn process_commands_read_stdin_without_engine_and_emit_deterministic_yaml() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    fs::create_dir(&workspace).expect("workspace");
    let input = br#"---
"file": "src/a.ts"
"severity": "warning"
---
"file": "src/b.ts"
"severity": "error"
"#;

    let validate = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.arg("validate");
        }),
        input,
    );
    assert!(validate.status.success());
    assert_eq!(yaml(&validate.stdout)[0]["documents"], 2);

    let count = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.arg("count");
        }),
        input,
    );
    assert!(count.status.success());
    assert_eq!(yaml(&count.stdout)[0]["records"], 2);

    let selected = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.args(["select", "--fields", "file"]);
        }),
        input,
    );
    assert!(selected.status.success());
    let selected = yaml(&selected.stdout);
    assert_eq!(selected.len(), 2);
    assert_eq!(selected[0]["file"], "src/a.ts");
    assert!(selected[0].get("severity").is_none());

    let filtered = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.args(["filter", "--field", "severity", "--equals", r#""warning""#]);
        }),
        input,
    );
    assert!(filtered.status.success());
    let filtered = yaml(&filtered.stdout);
    assert_eq!(filtered.len(), 1);
    assert_eq!(filtered[0]["file"], "src/a.ts");

    let grouped = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.args(["group", "--field", "severity"]);
        }),
        input,
    );
    assert!(grouped.status.success());
    assert_eq!(
        yaml(&grouped.stdout)[0]["groups"]
            .as_array()
            .expect("groups")
            .len(),
        2
    );
}

#[test]
fn process_reads_explicit_files_and_rejects_unsafe_or_invalid_inputs() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    fs::create_dir(&workspace).expect("workspace");
    let input = workspace.join("results.yaml");
    fs::write(&input, b"\"severity\": \"warning\"\n").expect("input YAML");

    let output = process(&workspace, &cache_root)
        .args(["count", "--input"])
        .arg(&input)
        .output()
        .expect("file process");
    assert!(output.status.success());
    assert_eq!(yaml(&output.stdout)[0]["records"], 1);

    let unsafe_output = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.arg("validate");
        }),
        b"\"a\": &x \"secret\"\n\"b\": *x\n",
    );
    assert_eq!(unsafe_output.status.code(), Some(122));
    assert!(unsafe_output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&unsafe_output.stderr).contains("forbidden"));

    let late_failure = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.args(["select", "--fields", "severity"]);
        }),
        b"---\n\"severity\": \"warning\"\n---\n\"a\": &x \"secret\"\n\"b\": *x\n",
    );
    assert_eq!(late_failure.status.code(), Some(122));
    assert!(late_failure.stdout.is_empty());

    let expression = run_stdin(
        process(&workspace, &cache_root).tap(|c| {
            c.args([
                "filter",
                "--field",
                "severity",
                "--equals",
                "severity == warning",
            ]);
        }),
        b"\"severity\": \"warning\"\n",
    );
    assert_eq!(expression.status.code(), Some(125));
    assert!(expression.stdout.is_empty());
}

#[test]
fn process_reads_verified_cache_results_without_reexecuting_ast_grep() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    fs::create_dir(&workspace).expect("workspace");

    let mut exec = Command::new(env!("CARGO_BIN_EXE_srcq"));
    exec.current_dir(&workspace).args([
        "exec",
        "--output",
        "machine",
        "--engine",
        env!("CARGO_BIN_EXE_srcq-native-fixture"),
        "--cache",
        "on",
        "--",
        "run",
        "--fixture-matches=3",
    ]);
    configure_cache_environment(&mut exec, &cache_root);
    let generated = exec.output().expect("generate verified cache");
    assert!(generated.status.success());
    let cache_id = yaml(&generated.stdout)[0]["_sgy"]["cache"]
        .as_str()
        .expect("cache id")
        .to_owned();

    let counted = process(&workspace, &cache_root)
        .args(["count", "--cache-id", &cache_id])
        .env("PATH", "")
        .output()
        .expect("count cache");
    assert!(
        counted.status.success(),
        "{}",
        String::from_utf8_lossy(&counted.stderr)
    );
    let report = &yaml(&counted.stdout)[0];
    assert_eq!(report["documents"], 3);
    assert_eq!(report["records"], 3);
}

#[test]
fn location_projection_selects_smallest_current_range_and_groups_one_scan() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    let source_dir = workspace.join("src");
    fs::create_dir_all(&source_dir).expect("source directory");
    let source = source_dir.join("target.ts");
    fs::write(
        &source,
        b"line-0\nline-1\nline-2\nline-3\nline-4\nline-5\nline-6\n",
    )
    .expect("source fixture");

    let mut exec = Command::new(env!("CARGO_BIN_EXE_srcq"));
    exec.current_dir(&workspace).args([
        "exec",
        "--output",
        "machine",
        "--engine",
        env!("CARGO_BIN_EXE_srcq-native-fixture"),
        "--cache",
        "on",
        "--fingerprint-file",
        "src/target.ts",
        "--profile",
        "files",
        "--",
        "run",
        "--fixture-matches=3",
        "--fixture-source-backed=src/target.ts",
    ]);
    configure_cache_environment(&mut exec, &cache_root);
    let generated = exec.output().expect("generate location cache");
    assert!(
        generated.status.success(),
        "{}",
        String::from_utf8_lossy(&generated.stderr)
    );
    let cache_id = yaml(&generated.stdout)[0]["_sgy"]["cache"]
        .as_str()
        .expect("cache id")
        .to_owned();

    let containing = process(&workspace, &cache_root)
        .args([
            "containing",
            "--output",
            "machine",
            "--cache-id",
            &cache_id,
            "--file",
            "src/target.ts",
            "--line",
            "3",
            "--column",
            "0",
            "--include-text",
        ])
        .env("PATH", "")
        .output()
        .expect("select containing location");
    assert!(
        containing.status.success(),
        "{}",
        String::from_utf8_lossy(&containing.stderr)
    );
    let containing = &yaml(&containing.stdout)[0];
    assert_eq!(containing["_sgy"]["candidates"], 3);
    assert_eq!(containing["_sgy"]["selected"], 1);
    assert_eq!(containing["_sgy"]["selection_complete"], true);
    assert_eq!(containing["_sgy"]["source_verified_records"], 1);
    assert_eq!(containing["results"][0]["ordinal"], 2);
    assert_eq!(containing["results"][0]["range"]["start"]["line"], 2);
    assert_eq!(containing["results"][0]["range"]["end"]["line"], 5);
    assert_eq!(containing["results"][0]["text"], "line-2\nline-3\nline-4\n");

    let grouped = process(&workspace, &cache_root)
        .args([
            "group-locations",
            "--output",
            "machine",
            "--cache-id",
            &cache_id,
            "--limit",
            "2",
        ])
        .env("PATH", "")
        .output()
        .expect("group cached locations");
    assert!(
        grouped.status.success(),
        "{}",
        String::from_utf8_lossy(&grouped.stderr)
    );
    let grouped = &yaml(&grouped.stdout)[0];
    assert_eq!(grouped["_sgy"]["total"], 3);
    assert_eq!(grouped["_sgy"]["shown"], 2);
    assert_eq!(grouped["_sgy"]["complete"], false);
    assert_eq!(grouped["_sgy"]["next_offset"], 2);
    assert_eq!(grouped["results"][0]["file"], "src/target.ts");
    assert_eq!(
        grouped["results"][0]["ranges"],
        json!(["0:0-7:0", "1:0-6:0"])
    );

    let model_containing = process(&workspace, &cache_root)
        .args([
            "containing",
            "--cache-id",
            &cache_id,
            "--file",
            "src/target.ts",
            "--line",
            "3",
            "--column",
            "0",
            "--include-text",
        ])
        .env("PATH", "")
        .output()
        .expect("model containing location");
    assert!(model_containing.status.success());
    assert_eq!(
        String::from_utf8(model_containing.stdout).expect("UTF-8 containing output"),
        "src/target.ts:2:0-5:0\nline-2\nline-3\nline-4\n"
    );

    let model_grouped = process(&workspace, &cache_root)
        .args(["group-locations", "--cache-id", &cache_id, "--limit", "2"])
        .env("PATH", "")
        .output()
        .expect("model grouped locations");
    assert!(model_grouped.status.success());
    let model_grouped = String::from_utf8(model_grouped.stdout).expect("UTF-8 grouped output");
    assert!(model_grouped.starts_with("src/target.ts\n  0:0-7:0\n  1:0-6:0\n"));
    assert!(model_grouped.contains(&format!("@more shown=2 omitted=1 cache={cache_id} after=2")));
    assert!(!model_grouped.contains("_sgy"));

    fs::write(
        &source,
        b"line-0\nline-1\nline-2\nline-3\nline-4\nline-5\nchanged-outside-selection\n",
    )
    .expect("mutate source outside the selected range");
    let stale = process(&workspace, &cache_root)
        .args([
            "containing",
            "--cache-id",
            &cache_id,
            "--file",
            "src/target.ts",
            "--line",
            "3",
            "--column",
            "0",
        ])
        .output()
        .expect("reject stale cache");
    assert_eq!(stale.status.code(), Some(125));
    assert!(stale.stdout.is_empty());
    assert!(String::from_utf8_lossy(&stale.stderr).contains("changed; rerun ast-grep"));
}

#[test]
fn merge_uses_verified_cache_cwd_and_engine_provenance_for_conflicts() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    fs::create_dir(&workspace).expect("workspace");

    let create_cache = |text_chars: &str| {
        let mut exec = Command::new(env!("CARGO_BIN_EXE_srcq"));
        exec.current_dir(&workspace).args([
            "exec",
            "--output",
            "machine",
            "--engine",
            env!("CARGO_BIN_EXE_srcq-native-fixture"),
            "--cache",
            "on",
            "--",
            "run",
            "--fixture-matches=3",
            text_chars,
        ]);
        configure_cache_environment(&mut exec, &cache_root);
        let output = exec.output().expect("create cache");
        assert!(output.status.success());
        yaml(&output.stdout)[0]["_sgy"]["cache"]
            .as_str()
            .expect("cache id")
            .to_owned()
    };
    let first = create_cache("--fixture-text-chars=10");
    let second = create_cache("--fixture-text-chars=20");

    let rejected = process(&workspace, &cache_root)
        .args([
            "merge",
            "--source",
            &format!("cache={first}"),
            "--source",
            &format!("cache={second}"),
        ])
        .env("PATH", "")
        .output()
        .expect("conflicting cache merge");
    assert_eq!(rejected.status.code(), Some(122));
    assert!(rejected.stdout.is_empty());

    let accepted = process(&workspace, &cache_root)
        .args([
            "merge",
            "--source",
            &format!("cache={first}"),
            "--source",
            &format!("cache={second}"),
            "--on-conflict",
            "keep-first",
        ])
        .env("PATH", "")
        .output()
        .expect("explicit conflict policy");
    assert!(
        accepted.status.success(),
        "{}",
        String::from_utf8_lossy(&accepted.stderr)
    );
    let accepted = yaml(&accepted.stdout);
    let header = &accepted[0]["_sgy"];
    assert_eq!(header["records"], 3);
    assert_eq!(header["conflicts"], 3);
    assert_eq!(header["sources"].as_array().expect("sources").len(), 2);
    assert_eq!(header["sources"][0]["cwd"], header["sources"][1]["cwd"]);
    assert!(header["sources"][0]["engine"]["path"].is_string());
    assert!(header["sources"][0]["engine"]["version"].is_string());
    assert_eq!(
        accepted[1]["_sgy"]["source_ids"],
        json!([format!("cache:{first}"), format!("cache:{second}")])
    );
}

#[test]
fn composite_commands_sort_dedupe_and_round_trip_without_expressions() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    fs::create_dir(&workspace).expect("workspace");
    let input = br#"---
"file": "src/b.ts"
"range": {"start": {"line": 2}, "end": {"line": 2}}
"ruleId": "rule"
"severity": "warning"
"text": "b"
---
"file": "src/a.ts"
"range": {"start": {"line": 1}, "end": {"line": 1}}
"ruleId": "rule"
"severity": "error"
"text": "a"
---
"file": "src/b.ts"
"range": {"start": {"line": 2}, "end": {"line": 2}}
"ruleId": "rule"
"severity": "warning"
"text": "b"
"#;

    let sorted = run_stdin(
        process(&workspace, &cache_root).tap(|command| {
            command.args(["sort", "--by", "file"]);
        }),
        input,
    );
    assert!(sorted.status.success());
    let sorted = yaml(&sorted.stdout);
    assert_eq!(sorted[0]["_sgy"]["operation"], "sort");
    assert_eq!(sorted[1]["file"], "src/a.ts");
    assert_eq!(sorted[2]["file"], "src/b.ts");
    assert_eq!(sorted[3]["file"], "src/b.ts");

    let deduped = run_stdin(
        process(&workspace, &cache_root).tap(|command| {
            command.arg("dedupe");
        }),
        input,
    );
    assert!(deduped.status.success());
    let deduped = yaml(&deduped.stdout);
    assert_eq!(deduped[0]["_sgy"]["records"], 2);
    assert_eq!(deduped[0]["_sgy"]["duplicates"], 1);
    assert_eq!(deduped[1]["file"], "src/b.ts");
    assert_eq!(deduped[2]["file"], "src/a.ts");

    let jsonl = run_stdin(
        process(&workspace, &cache_root).tap(|command| {
            command.arg("to-jsonl");
        }),
        input,
    );
    assert!(jsonl.status.success());
    assert_eq!(
        jsonl.stdout.iter().filter(|byte| **byte == b'\n').count(),
        3
    );
    let round_trip = run_stdin(
        process(&workspace, &cache_root).tap(|command| {
            command.arg("from-jsonl");
        }),
        &jsonl.stdout,
    );
    assert!(round_trip.status.success());
    assert_eq!(yaml(&round_trip.stdout), yaml(input));
}

#[test]
fn merge_requires_explicit_sources_and_keeps_file_origins_distinct() {
    let directory = tempdir().expect("temporary directory");
    let workspace = directory.path().join("workspace");
    let cache_root = directory.path().join("cache-root");
    fs::create_dir(&workspace).expect("workspace");
    let first = workspace.join("first.yaml");
    let second = workspace.join("second.yaml");
    let record = b"\"file\": \"src/a.ts\"\n\"range\": {\"start\": {\"line\": 1}, \"end\": {\"line\": 1}}\n\"ruleId\": \"rule\"\n";
    fs::write(&first, record).expect("first source");
    fs::write(&second, record).expect("second source");

    let merged = process(&workspace, &cache_root)
        .args([
            "merge",
            "--source",
            &format!("file={}", first.display()),
            "--source",
            &format!("file={}", second.display()),
        ])
        .output()
        .expect("merge files");
    assert!(
        merged.status.success(),
        "{}",
        String::from_utf8_lossy(&merged.stderr)
    );
    let merged = yaml(&merged.stdout);
    assert_eq!(
        merged[0]["_sgy"]["sources"]
            .as_array()
            .expect("sources")
            .len(),
        2
    );
    assert_eq!(merged[0]["_sgy"]["records"], 2);
    assert_ne!(merged[1]["_sgy"]["identity"], merged[2]["_sgy"]["identity"]);

    let invalid = process(&workspace, &cache_root)
        .args(["merge", "--source", "file=only.yaml"])
        .output()
        .expect("invalid merge");
    assert_eq!(invalid.status.code(), Some(125));
    assert!(invalid.stdout.is_empty());
}

trait CommandTap {
    fn tap(self, apply: impl FnOnce(&mut Self)) -> Self;
}

impl CommandTap for Command {
    fn tap(mut self, apply: impl FnOnce(&mut Self)) -> Self {
        apply(&mut self);
        self
    }
}

fn configure_cache_environment(command: &mut Command, root: &Path) {
    command.env("LOCALAPPDATA", root);
}
