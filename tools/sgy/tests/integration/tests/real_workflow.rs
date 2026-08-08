use std::{
    collections::BTreeMap,
    ffi::{OsStr, OsString},
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
};

use serde_json::Value;
use sgy_core::{
    codec::parse_yaml_documents,
    process::{run, CancellationKind, ProcessRequest},
};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

const EXPECTED_VERSION: &str = "ast-grep 0.42.0";

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_run_scan_cache_and_processors_preserve_native_results() {
    let engine = real_engine();
    let fixture = IsolatedFixture::new();
    let before = snapshot(fixture.workspace());

    let run_args = os_args([
        "run",
        "-p",
        "console.log($A)",
        "-l",
        "ts",
        "src",
        "--json=stream",
    ]);
    let native_run = native(fixture.workspace(), &engine, &run_args);
    let wrapped_run = wrapped_lossless(fixture.workspace(), fixture.cache(), &engine, &run_args);
    assert_equivalent_structured(&native_run, &wrapped_run);
    let native_records = parse_json_lines(&native_run.stdout);
    assert_eq!(native_records.len(), 3);
    assert!(native_records.iter().any(|record| {
        record["text"]
            .as_str()
            .is_some_and(|text| text.contains('\n'))
    }));

    let scan_args = os_args(["scan", "-r", "rules/no-console.yml", "src", "--json=stream"]);
    let native_scan = native(fixture.workspace(), &engine, &scan_args);
    let wrapped_scan = wrapped_lossless(fixture.workspace(), fixture.cache(), &engine, &scan_args);
    assert_equivalent_structured(&native_scan, &wrapped_scan);
    assert_eq!(parse_json_lines(&native_scan.stdout).len(), 3);

    let limited_args = os_args(["run", "-p", "console.log($A)", "-l", "ts", "src"]);
    let limited = sgy(fixture.workspace(), fixture.cache())
        .args(["exec", "--engine"])
        .arg(&engine)
        .args([
            "--cache",
            "on",
            "--max-detail-results",
            "1",
            "--max-context-bytes",
            "24576",
            "--",
        ])
        .args(&limited_args)
        .output()
        .expect("run limited wrapper context");
    assert_success(&limited, "limited wrapper context");
    let limited_yaml = parse_yaml_documents(&limited.stdout).expect("limited safe YAML");
    let context = &limited_yaml[0];
    assert_eq!(context["_sgy"]["total"], 3);
    assert_eq!(context["_sgy"]["shown"], 1);
    assert_eq!(context["_sgy"]["omitted"], 2);
    assert_eq!(context["_sgy"]["complete"], false);
    let cache_id = context["_sgy"]["cache"]
        .as_str()
        .expect("limited output cache id");

    let cached = sgy(fixture.workspace(), fixture.cache())
        .args(["cache", "get", cache_id])
        .env("PATH", "")
        .output()
        .expect("retrieve complete cache");
    assert_success(&cached, "cache get");
    assert_record_sets_equal(
        parse_yaml_documents(&cached.stdout).expect("cached safe YAML"),
        native_records,
    );

    let counted = sgy(fixture.workspace(), fixture.cache())
        .args(["process", "count", "--cache-id", cache_id])
        .env("PATH", "")
        .output()
        .expect("count cached results");
    assert_success(&counted, "process count cache");
    let count_report = parse_yaml_documents(&counted.stdout).expect("count report");
    assert_eq!(count_report[0]["records"], 3);

    let grouped = sgy(fixture.workspace(), fixture.cache())
        .args([
            "process",
            "group",
            "--cache-id",
            cache_id,
            "--field",
            "file",
        ])
        .env("PATH", "")
        .output()
        .expect("group cached results");
    assert_success(&grouped, "process group cache");
    let group_report = parse_yaml_documents(&grouped.stdout).expect("group report");
    assert_eq!(group_report[0]["records"], 3);
    assert_eq!(
        group_report[0]["groups"]
            .as_array()
            .expect("file groups")
            .len(),
        2
    );

    let removed = sgy(fixture.workspace(), fixture.cache())
        .args(["cache", "remove", cache_id])
        .env("PATH", "")
        .output()
        .expect("remove integration cache");
    assert_success(&removed, "cache remove");
    assert_eq!(
        parse_yaml_documents(&removed.stdout).expect("remove report")[0]["removed"],
        true
    );
    assert!(!platform_cache_root(fixture.cache()).join(cache_id).exists());
    assert_eq!(snapshot(fixture.workspace()), before);
}

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_files_and_custom_profiles_remain_compatible() {
    let engine = real_engine();
    let fixture = IsolatedFixture::new();
    let before = snapshot(fixture.workspace());
    let native_args = os_args(["run", "-p", "console.log($A)", "-l", "ts", "src"]);

    let files = sgy(fixture.workspace(), fixture.cache())
        .args(["exec", "--engine"])
        .arg(&engine)
        .args(["--profile", "files", "--cache", "off", "--"])
        .args(&native_args)
        .output()
        .expect("run files profile against real ast-grep");
    assert_success(&files, "real files profile");
    let files = parse_yaml_documents(&files.stdout).expect("files profile YAML");
    assert_eq!(files.len(), 1);
    assert_eq!(files[0]["_sgy"]["profile"], "files");
    assert_eq!(files[0]["_sgy"]["total"], 3);
    assert_eq!(files[0]["_sgy"]["files"], 2);
    assert!(files[0].get("results").is_none());

    let custom = sgy(fixture.workspace(), fixture.cache())
        .args(["exec", "--engine"])
        .arg(&engine)
        .args([
            "--profile",
            "custom",
            "--keep-fields",
            "file,range,text",
            "--prune-fields",
            "text",
            "--cache",
            "off",
            "--",
        ])
        .args(&native_args)
        .output()
        .expect("run custom profile against real ast-grep");
    assert_success(&custom, "real custom profile");
    let custom = parse_yaml_documents(&custom.stdout).expect("custom profile YAML");
    assert_eq!(custom.len(), 1);
    assert_eq!(custom[0]["_sgy"]["profile"], "custom");
    assert_eq!(custom[0]["_sgy"]["total"], 3);
    assert_eq!(custom[0]["_sgy"]["complete"], true);
    let results = custom[0]["results"].as_array().expect("custom results");
    assert_eq!(results.len(), 3);
    for result in results {
        assert!(result.get("file").is_some());
        assert!(result.get("range").is_some());
        assert!(result.get("text").is_none());
    }

    assert_eq!(snapshot(fixture.workspace()), before);
}

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_run_and_scan_rewrite_modify_the_same_files_and_bytes_as_native() {
    let engine = real_engine();
    let formal_before = snapshot(&fixture_source());

    for mode in [RewriteMode::Run, RewriteMode::Scan] {
        let directory = tempfile::tempdir().expect("rewrite fixture root");
        let native_root = directory.path().join("native");
        let wrapped_root = directory.path().join("wrapped");
        copy_tree(&fixture_source(), &native_root);
        copy_tree(&fixture_source(), &wrapped_root);
        let native_before = snapshot(&native_root);
        let wrapped_before = snapshot(&wrapped_root);
        assert_eq!(native_before, wrapped_before);

        let args = mode.args();
        let native_output = native(&native_root, &engine, &args);
        let wrapped_output = sgy(&wrapped_root, &directory.path().join("cache"))
            .args(["exec", "--engine"])
            .arg(&engine)
            .args(["--cache", "off", "--"])
            .args(&args)
            .output()
            .expect("run wrapped rewrite");
        assert_eq!(
            wrapped_output.status.code(),
            native_output.status.code(),
            "{mode:?}: {}",
            String::from_utf8_lossy(&wrapped_output.stderr)
        );

        let native_after = snapshot(&native_root);
        let wrapped_after = snapshot(&wrapped_root);
        assert_eq!(wrapped_after, native_after, "{mode:?} bytes differ");
        let changed = changed_files(&native_before, &native_after);
        assert_eq!(changed, vec!["src/a.ts", "src/b.ts"], "{mode:?}");
        assert_eq!(
            fs::read_to_string(native_root.join("src/a.ts")).expect("rewritten a.ts"),
            fs::read_to_string(wrapped_root.join("src/a.ts")).expect("wrapped a.ts")
        );
    }

    assert_eq!(snapshot(&fixture_source()), formal_before);
}

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_failures_timeout_and_cancellation_have_distinct_evidence() {
    let engine = real_engine();
    let fixture = IsolatedFixture::new();
    let before = snapshot(fixture.workspace());

    let cases = [
        (
            "no-match",
            os_args(["run", "-p", "alert($A)", "-l", "ts", "src", "--json=stream"]),
            1,
            true,
            None,
        ),
        (
            "missing-path",
            os_args([
                "run",
                "-p",
                "console.log($A)",
                "-l",
                "ts",
                "missing.ts",
                "--json=stream",
            ]),
            1,
            false,
            Some("missing.ts"),
        ),
        (
            "invalid-rule",
            os_args([
                "scan",
                "--inline-rules",
                "id: broken",
                "src",
                "--json=stream",
            ]),
            8,
            false,
            Some("Cannot parse rule"),
        ),
    ];
    for (name, args, exit_code, stderr_empty, stderr_marker) in cases {
        let native_output = native(fixture.workspace(), &engine, &args);
        let wrapped_output = wrapped_lossless(fixture.workspace(), fixture.cache(), &engine, &args);
        assert_eq!(native_output.status.code(), Some(exit_code), "{name}");
        assert_eq!(wrapped_output.status.code(), Some(exit_code), "{name}");
        assert_eq!(wrapped_output.stdout, native_output.stdout, "{name} stdout");
        assert_eq!(wrapped_output.stderr.is_empty(), stderr_empty, "{name}");
        if let Some(marker) = stderr_marker {
            assert!(
                String::from_utf8_lossy(&wrapped_output.stderr).contains(marker),
                "{name} stderr lacks {marker:?}"
            );
        }
    }

    let bin = fixture.root().join("slow-bin");
    fs::create_dir(&bin).expect("slow PATH directory");
    let slow = copy_binary(Path::new(env!("CARGO_BIN_EXE_sgy-slow-engine")), &bin, "sg");
    assert!(slow.is_file());
    let timed_out = sgy(fixture.workspace(), fixture.cache())
        .args(["exec", "--cache", "off", "--", "--version"])
        .env("PATH", &bin)
        .output()
        .expect("run slow sg discovery");
    assert_eq!(timed_out.status.code(), Some(120));
    assert!(String::from_utf8_lossy(&timed_out.stderr).contains("timed out"));

    let token = sgy_core::process::CancellationToken::new();
    assert!(token.cancel(CancellationKind::External));
    let mut request = ProcessRequest::new(&engine, fixture.workspace());
    request.args = os_args([
        "run",
        "-p",
        "console.log($A)",
        "-l",
        "ts",
        "src",
        "--json=stream",
    ]);
    request.forward_stderr = false;
    request.cancellation = token;
    let cancelled = run(request).expect("cancel and reap real ast-grep");
    assert_eq!(cancelled.exit_code(), 143);
    assert_eq!(
        cancelled.cancellation.map(|report| report.reason),
        Some(CancellationKind::External)
    );
    assert_eq!(snapshot(fixture.workspace()), before);
}

#[derive(Clone, Copy, Debug)]
enum RewriteMode {
    Run,
    Scan,
}

impl RewriteMode {
    fn args(self) -> Vec<OsString> {
        match self {
            Self::Run => os_args([
                "run",
                "-p",
                "console.log($A)",
                "-r",
                "logger.info($A)",
                "-U",
                "-l",
                "ts",
                "src",
            ]),
            Self::Scan => os_args(["scan", "-r", "rules/no-console.yml", "-U", "src"]),
        }
    }
}

struct IsolatedFixture {
    root: TempDir,
    workspace: PathBuf,
    cache: PathBuf,
}

impl IsolatedFixture {
    fn new() -> Self {
        let root = tempfile::tempdir().expect("isolated integration root");
        let workspace = root.path().join("workspace");
        let cache = root.path().join("cache");
        copy_tree(&fixture_source(), &workspace);
        Self {
            root,
            workspace,
            cache,
        }
    }

    fn root(&self) -> &Path {
        self.root.path()
    }

    fn workspace(&self) -> &Path {
        &self.workspace
    }

    fn cache(&self) -> &Path {
        &self.cache
    }
}

fn workspace_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root")
}

fn fixture_source() -> PathBuf {
    workspace_root().join("tests/fixtures/integration/base")
}

fn real_engine() -> PathBuf {
    let path = PathBuf::from(
        std::env::var_os("SGY_AST_GREP").expect("SGY_AST_GREP must name a real ast-grep binary"),
    );
    assert!(path.is_file(), "engine is not a file: {}", path.display());
    let version = Command::new(&path)
        .arg("--version")
        .output()
        .expect("read real engine version");
    assert_success(&version, "ast-grep --version");
    let actual = String::from_utf8(version.stdout)
        .expect("UTF-8 engine version")
        .trim()
        .to_owned();
    let expected = std::env::var("SGY_AST_GREP_EXPECTED_VERSION")
        .unwrap_or_else(|_| EXPECTED_VERSION.to_owned());
    assert_eq!(actual, expected);
    path
}

fn native(cwd: &Path, engine: &Path, args: &[OsString]) -> Output {
    Command::new(engine)
        .current_dir(cwd)
        .args(args)
        .output()
        .expect("run native ast-grep")
}

fn wrapped_lossless(cwd: &Path, cache: &Path, engine: &Path, args: &[OsString]) -> Output {
    sgy(cwd, cache)
        .args(["exec", "--profile", "lossless", "--engine"])
        .arg(engine)
        .args(["--cache", "off", "--"])
        .args(args)
        .output()
        .expect("run lossless wrapper")
}

fn sgy(cwd: &Path, cache: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy-integration-driver"));
    command.current_dir(cwd);
    configure_isolated_environment(&mut command, cache);
    command
}

#[cfg(windows)]
fn configure_isolated_environment(command: &mut Command, root: &Path) {
    command.env("LOCALAPPDATA", root).env("APPDATA", root);
}

#[cfg(target_os = "macos")]
fn configure_isolated_environment(command: &mut Command, root: &Path) {
    command.env("HOME", root).env("XDG_CONFIG_HOME", root);
}

#[cfg(all(unix, not(target_os = "macos")))]
fn configure_isolated_environment(command: &mut Command, root: &Path) {
    command
        .env("XDG_CACHE_HOME", root)
        .env("XDG_CONFIG_HOME", root)
        .env("HOME", root);
}

#[cfg(windows)]
fn platform_cache_root(environment_root: &Path) -> PathBuf {
    environment_root.join("sgy").join("cache").join("v1")
}

#[cfg(target_os = "macos")]
fn platform_cache_root(environment_root: &Path) -> PathBuf {
    environment_root
        .join("Library")
        .join("Caches")
        .join("sgy")
        .join("v1")
}

#[cfg(all(unix, not(target_os = "macos")))]
fn platform_cache_root(environment_root: &Path) -> PathBuf {
    environment_root.join("sgy").join("v1")
}

fn assert_equivalent_structured(native: &Output, wrapped: &Output) {
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_record_sets_equal(
        parse_yaml_documents(&wrapped.stdout).expect("lossless wrapper YAML"),
        parse_json_lines(&native.stdout),
    );
}

fn assert_record_sets_equal(mut actual: Vec<Value>, mut expected: Vec<Value>) {
    actual.sort_by_cached_key(record_sort_key);
    expected.sort_by_cached_key(record_sort_key);
    assert_eq!(actual, expected);
}

fn record_sort_key(record: &Value) -> (String, u64, u64, String, String) {
    (
        record["file"].as_str().unwrap_or_default().to_owned(),
        record["range"]["byteOffset"]["start"]
            .as_u64()
            .unwrap_or_default(),
        record["range"]["byteOffset"]["end"]
            .as_u64()
            .unwrap_or_default(),
        record["ruleId"].as_str().unwrap_or_default().to_owned(),
        record["text"].as_str().unwrap_or_default().to_owned(),
    )
}

fn assert_success(output: &Output, operation: &str) {
    assert!(
        output.status.success(),
        "{operation} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn parse_json_lines(bytes: &[u8]) -> Vec<Value> {
    bytes
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.iter().all(u8::is_ascii_whitespace))
        .map(|line| serde_json::from_slice(line).expect("native JSONL record"))
        .collect()
}

fn os_args<const N: usize>(args: [&str; N]) -> Vec<OsString> {
    args.into_iter().map(OsString::from).collect()
}

fn copy_binary(source: &Path, directory: &Path, stem: &str) -> PathBuf {
    let file_name = source.extension().and_then(OsStr::to_str).map_or_else(
        || stem.to_owned(),
        |extension| format!("{stem}.{extension}"),
    );
    let destination = directory.join(file_name);
    fs::copy(source, &destination).expect("copy slow engine binary");
    destination
}

fn copy_tree(source: &Path, destination: &Path) {
    fs::create_dir_all(destination).expect("create copied fixture directory");
    let mut entries: Vec<_> = fs::read_dir(source)
        .expect("read fixture directory")
        .map(|entry| entry.expect("fixture entry"))
        .collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let target = destination.join(entry.file_name());
        if entry.file_type().expect("fixture file type").is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).expect("copy fixture file");
        }
    }
}

fn snapshot(root: &Path) -> BTreeMap<String, String> {
    let mut output = BTreeMap::new();
    collect_hashes(root, root, &mut output);
    output
}

fn collect_hashes(root: &Path, directory: &Path, output: &mut BTreeMap<String, String>) {
    let mut entries: Vec<_> = fs::read_dir(directory)
        .expect("read snapshot directory")
        .map(|entry| entry.expect("snapshot entry"))
        .collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        if entry.file_type().expect("snapshot file type").is_dir() {
            collect_hashes(root, &path, output);
        } else {
            let bytes = fs::read(&path).expect("snapshot file bytes");
            let digest = format!("{:x}", Sha256::digest(bytes));
            let relative = path
                .strip_prefix(root)
                .expect("relative snapshot path")
                .to_string_lossy()
                .replace('\\', "/");
            output.insert(relative, digest);
        }
    }
}

fn changed_files<'a>(
    before: &'a BTreeMap<String, String>,
    after: &BTreeMap<String, String>,
) -> Vec<&'a str> {
    before
        .iter()
        .filter_map(|(path, digest)| (after.get(path) != Some(digest)).then_some(path.as_str()))
        .collect()
}
