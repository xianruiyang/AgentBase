use std::{
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
};

use sgy_core::codec::parse_yaml_documents;

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_ast_grep_run_scan_stdin_and_exit_gate() {
    let engine = PathBuf::from(
        std::env::var_os("SGY_AST_GREP").expect("SGY_AST_GREP must name ast-grep 0.42.0"),
    );
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root");
    let version = Command::new(&engine)
        .arg("--version")
        .output()
        .expect("read ast-grep version");
    assert!(version.status.success());
    let expected_version = std::env::var("SGY_AST_GREP_EXPECTED_VERSION")
        .unwrap_or_else(|_| "ast-grep 0.42.0".to_owned());
    assert_eq!(
        String::from_utf8(version.stdout)
            .expect("UTF-8 version")
            .trim(),
        expected_version
    );

    let run_input = root.join("tests/fixtures/native/run/input.ts");
    let base_run = vec![
        "run".into(),
        "-p".into(),
        "console.log($A)".into(),
        "-l".into(),
        "ts".into(),
        run_input.into_os_string(),
    ];
    for style in ["pretty", "compact", "stream"] {
        let mut native_args = base_run.clone();
        native_args.push(format!("--json={style}").into());
        let native = Command::new(&engine)
            .current_dir(root)
            .args(&native_args)
            .output()
            .expect("native run");
        let wrapped = sgy(root, &engine, &native_args).output().expect("sgy run");
        assert_eq!(wrapped.status.code(), native.status.code(), "style {style}");
        assert_eq!(
            parse_yaml_documents(&wrapped.stdout).expect("lossless YAML"),
            parse_native(&native.stdout, style),
            "style {style}"
        );
    }

    let mut native_default = base_run.clone();
    native_default.push("--json=stream".into());
    let native = Command::new(&engine)
        .current_dir(root)
        .args(&native_default)
        .output()
        .expect("native default equivalent");
    let wrapped = sgy(root, &engine, &base_run)
        .output()
        .expect("sgy default run");
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped.stdout).expect("default YAML"),
        parse_native(&native.stdout, "stream")
    );

    let mut files_args = base_run.clone();
    files_args.push("--files-with-matches".into());
    let native_files = Command::new(&engine)
        .current_dir(root)
        .args(&files_args)
        .output()
        .expect("native files-with-matches");
    let wrapped_files = sgy(root, &engine, &files_args)
        .output()
        .expect("wrapped files-with-matches");
    assert_eq!(wrapped_files.status.code(), native_files.status.code());
    let files_yaml = parse_yaml_documents(&wrapped_files.stdout).expect("files YAML");
    let native_paths: Vec<_> = String::from_utf8(native_files.stdout)
        .expect("UTF-8 native paths")
        .lines()
        .map(serde_json::Value::from)
        .collect();
    assert_eq!(
        files_yaml[0]["files"],
        serde_json::Value::Array(native_paths)
    );
    assert_eq!(files_yaml[0]["_sgy"]["complete"], true);

    let mut debug_args = base_run.clone();
    debug_args.extend(["--debug-query=ast".into(), "--json=stream".into()]);
    let wrapped_debug = sgy(root, &engine, &debug_args)
        .output()
        .expect("wrapped debug query");
    assert!(wrapped_debug.status.success());
    assert!(String::from_utf8_lossy(&wrapped_debug.stderr).contains("Debug AST:"));
    assert!(!String::from_utf8_lossy(&wrapped_debug.stdout).contains("Debug AST:"));
    assert!(!parse_yaml_documents(&wrapped_debug.stdout)
        .expect("debug result YAML")
        .is_empty());

    let mut inspect_native_args = base_run.clone();
    inspect_native_args.extend(["--inspect".into(), "summary".into(), "--json=stream".into()]);
    let native_inspect = Command::new(&engine)
        .current_dir(root)
        .args(&inspect_native_args)
        .output()
        .expect("native inspect");
    let mut inspect_wrapped_args = base_run.clone();
    inspect_wrapped_args.extend(["--inspect".into(), "summary".into()]);
    let wrapped_inspect = sgy(root, &engine, &inspect_wrapped_args)
        .output()
        .expect("wrapped inspect");
    assert_eq!(wrapped_inspect.status.code(), native_inspect.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped_inspect.stdout).expect("inspect YAML"),
        parse_native(&native_inspect.stdout, "stream")
    );
    assert!(String::from_utf8_lossy(&wrapped_inspect.stderr).contains("summary|"));
    assert!(!String::from_utf8_lossy(&wrapped_inspect.stdout).contains("summary|"));

    let scan_rule = root.join("tests/fixtures/native/scan/no-console.yml");
    let scan_input = root.join("tests/fixtures/native/scan/input.ts");
    let base_scan = vec![
        "scan".into(),
        "-r".into(),
        scan_rule.into_os_string(),
        scan_input.into_os_string(),
    ];
    let mut native_scan_args = base_scan.clone();
    native_scan_args.push("--json=stream".into());
    let native = Command::new(&engine)
        .current_dir(root)
        .args(&native_scan_args)
        .output()
        .expect("native scan");
    let wrapped = sgy(root, &engine, &base_scan).output().expect("sgy scan");
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped.stdout).expect("scan YAML"),
        parse_native(&native.stdout, "stream")
    );

    let stdin_args = vec![
        "run".into(),
        "-p".into(),
        "console.log($A)".into(),
        "-l".into(),
        "ts".into(),
        "--stdin".into(),
    ];
    let mut native_stdin_args = stdin_args.clone();
    native_stdin_args.push("--json=stream".into());
    let native = output_with_stdin(
        Command::new(&engine)
            .current_dir(root)
            .args(&native_stdin_args),
        b"console.log(\"stdin\");",
    );
    let wrapped = output_with_stdin(
        &mut sgy(root, &engine, &stdin_args),
        b"console.log(\"stdin\");",
    );
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped.stdout).expect("stdin YAML"),
        parse_native(&native.stdout, "stream")
    );

    for args in [
        vec![
            "run".into(),
            "-p".into(),
            "alert($A)".into(),
            "-l".into(),
            "ts".into(),
            root.join("tests/fixtures/native/run/input.ts")
                .into_os_string(),
        ],
        vec![
            "run".into(),
            "-p".into(),
            "console.log($A)".into(),
            "-l".into(),
            "definitely-not-a-language".into(),
        ],
    ] {
        let mut native_args = args.clone();
        native_args.push("--json=stream".into());
        let native = Command::new(&engine)
            .current_dir(root)
            .args(&native_args)
            .output()
            .expect("native exit case");
        let wrapped = sgy(root, &engine, &args)
            .output()
            .expect("wrapped exit case");
        assert_eq!(wrapped.status.code(), native.status.code());
        assert_eq!(wrapped.stdout, native.stdout);
    }
}

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_scan_formats_severity_and_native_limit_match_the_wrapper() {
    let engine = PathBuf::from(
        std::env::var_os("SGY_AST_GREP").expect("SGY_AST_GREP must name ast-grep 0.42.0"),
    );
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root");
    let directory = tempfile::tempdir().expect("temporary scan fixture");
    let source = directory.path().join("input.ts");
    std::fs::write(
        &source,
        "console.log(one);\nconsole.log(two);\nconsole.log(three);\n",
    )
    .expect("write source fixture");
    let rule = root.join("tests/fixtures/native/scan/no-console.yml");
    let base = vec![
        "scan".into(),
        "-r".into(),
        rule.into_os_string(),
        source.into_os_string(),
    ];

    let mut limited = base.clone();
    limited.extend([
        "--error=no-console".into(),
        "--max-results=1".into(),
        "--include-metadata".into(),
        "--json=stream".into(),
    ]);
    let native_limited = Command::new(&engine)
        .current_dir(root)
        .args(&limited)
        .output()
        .expect("native limited scan");
    let wrapped_limited = sgy(root, &engine, &limited)
        .output()
        .expect("wrapped limited scan");
    assert_eq!(wrapped_limited.status.code(), native_limited.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped_limited.stdout).expect("limited YAML"),
        parse_native(&native_limited.stdout, "stream")
    );
    let limited_values = parse_native(&native_limited.stdout, "stream");
    assert_eq!(limited_values.len(), 1);
    assert_eq!(limited_values[0]["severity"], "error");

    let mut sarif = base.clone();
    sarif.push("--format=sarif".into());
    let native_sarif = Command::new(&engine)
        .current_dir(root)
        .args(&sarif)
        .output()
        .expect("native SARIF scan");
    let wrapped_sarif = sgy(root, &engine, &sarif)
        .output()
        .expect("wrapped SARIF scan");
    assert_eq!(wrapped_sarif.status.code(), native_sarif.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped_sarif.stdout).expect("SARIF YAML"),
        vec![
            serde_json::from_slice::<serde_json::Value>(&native_sarif.stdout)
                .expect("native SARIF JSON")
        ]
    );

    let mut github = base.clone();
    github.push("--format=github".into());
    let native_github = Command::new(&engine)
        .current_dir(root)
        .args(&github)
        .output()
        .expect("native GitHub scan");
    let wrapped_github = sgy(root, &engine, &github)
        .output()
        .expect("wrapped GitHub scan");
    assert_eq!(wrapped_github.status.code(), native_github.status.code());
    let github_yaml = parse_yaml_documents(&wrapped_github.stdout).expect("GitHub YAML");
    assert_eq!(github_yaml[0]["_sgy"]["kind"], "github");
    assert_eq!(
        github_yaml[0]["stdout"],
        String::from_utf8(native_github.stdout).expect("native GitHub UTF-8")
    );

    let mut text = base.clone();
    text.extend(["--report-style=short".into(), "--color=never".into()]);
    let native_text = Command::new(&engine)
        .current_dir(root)
        .args(&text)
        .output()
        .expect("native text scan");
    let wrapped_text = sgy_with_wrapper(root, &engine, &["--no-native-defaults"], &text)
        .output()
        .expect("wrapped text scan");
    assert_eq!(wrapped_text.status.code(), native_text.status.code());
    let text_yaml = parse_yaml_documents(&wrapped_text.stdout).expect("text YAML");
    assert_eq!(text_yaml[0]["_sgy"]["kind"], "text");
    assert_eq!(
        text_yaml[0]["stdout"],
        String::from_utf8(native_text.stdout).expect("native text UTF-8")
    );

    let mut files = base.clone();
    files.push("--files-with-matches".into());
    let native_files = Command::new(&engine)
        .current_dir(root)
        .args(&files)
        .output()
        .expect("native files scan");
    let wrapped_files = sgy(root, &engine, &files)
        .output()
        .expect("wrapped files scan");
    assert_eq!(wrapped_files.status.code(), native_files.status.code());
    let expected_files: Vec<_> = String::from_utf8(native_files.stdout)
        .expect("native file UTF-8")
        .lines()
        .map(serde_json::Value::from)
        .collect();
    let files_yaml = parse_yaml_documents(&wrapped_files.stdout).expect("files YAML");
    assert_eq!(
        files_yaml[0]["files"],
        serde_json::Value::Array(expected_files)
    );

    let mut native_inspect_args = base.clone();
    native_inspect_args.extend(["--inspect=summary".into(), "--json=stream".into()]);
    let native_inspect = Command::new(&engine)
        .current_dir(root)
        .args(&native_inspect_args)
        .output()
        .expect("native inspect scan");
    let mut wrapped_inspect_args = base;
    wrapped_inspect_args.push("--inspect=summary".into());
    let wrapped_inspect = sgy(root, &engine, &wrapped_inspect_args)
        .output()
        .expect("wrapped inspect scan");
    assert_eq!(wrapped_inspect.status.code(), native_inspect.status.code());
    assert_eq!(
        parse_yaml_documents(&wrapped_inspect.stdout).expect("inspect YAML"),
        parse_native(&native_inspect.stdout, "stream")
    );
    assert!(String::from_utf8_lossy(&wrapped_inspect.stderr).contains("summary|"));
    assert!(!String::from_utf8_lossy(&wrapped_inspect.stdout).contains("summary|"));

    let mut conflicting_output = wrapped_inspect_args;
    conflicting_output.extend(["--format=github".into(), "--json=stream".into()]);
    let native_conflict = Command::new(&engine)
        .current_dir(root)
        .args(&conflicting_output)
        .output()
        .expect("native output conflict");
    let wrapped_conflict = sgy(root, &engine, &conflicting_output)
        .output()
        .expect("wrapped output conflict");
    assert_eq!(
        wrapped_conflict.status.code(),
        native_conflict.status.code()
    );
    assert!(wrapped_conflict.stdout.is_empty());
}

#[test]
#[ignore = "requires SGY_AST_GREP to point to a real ast-grep binary"]
fn real_update_all_preserves_run_and_scan_file_modifications() {
    let engine = PathBuf::from(
        std::env::var_os("SGY_AST_GREP").expect("SGY_AST_GREP must name ast-grep 0.42.0"),
    );
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root");
    let directory = tempfile::tempdir().expect("temporary write fixture");
    let input = "console.log(one);\nconsole.log(two);\n";

    let native_run = directory.path().join("native-run.ts");
    let wrapped_run = directory.path().join("wrapped-run.ts");
    std::fs::write(&native_run, input).expect("write native run input");
    std::fs::write(&wrapped_run, input).expect("write wrapped run input");
    let run_prefix: Vec<std::ffi::OsString> = vec![
        "run".into(),
        "-p".into(),
        "console.log($A)".into(),
        "-r".into(),
        "logger.info($A)".into(),
        "-U".into(),
        "-l".into(),
        "ts".into(),
    ];
    let mut native_run_args = run_prefix.clone();
    native_run_args.push(native_run.clone().into_os_string());
    let mut wrapped_run_args = run_prefix;
    wrapped_run_args.push(wrapped_run.clone().into_os_string());
    let native = Command::new(&engine)
        .current_dir(root)
        .args(&native_run_args)
        .output()
        .expect("native run update");
    let wrapped = sgy(root, &engine, &wrapped_run_args)
        .output()
        .expect("wrapped run update");
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(
        std::fs::read_to_string(&wrapped_run).expect("read wrapped run result"),
        std::fs::read_to_string(&native_run).expect("read native run result")
    );
    let run_yaml = parse_yaml_documents(&wrapped.stdout).expect("run update YAML");
    assert_eq!(run_yaml[0]["_sgy"]["kind"], "update-all");
    assert_eq!(run_yaml[0]["_sgy"]["write"]["transactional"], false);

    let rule = directory.path().join("no-console.yml");
    std::fs::write(
        &rule,
        "id: no-console\nlanguage: TypeScript\nrule:\n  pattern: console.log($A)\nfix: logger.info($A)\nmessage: avoid console.log\nseverity: warning\n",
    )
    .expect("write scan fix rule");
    let native_scan = directory.path().join("native-scan.ts");
    let wrapped_scan = directory.path().join("wrapped-scan.ts");
    std::fs::write(&native_scan, input).expect("write native scan input");
    std::fs::write(&wrapped_scan, input).expect("write wrapped scan input");
    let scan_prefix: Vec<std::ffi::OsString> = vec![
        "scan".into(),
        "--rule".into(),
        rule.into_os_string(),
        "-U".into(),
    ];
    let mut native_scan_args = scan_prefix.clone();
    native_scan_args.push(native_scan.clone().into_os_string());
    let mut wrapped_scan_args = scan_prefix;
    wrapped_scan_args.push(wrapped_scan.clone().into_os_string());
    let native = Command::new(&engine)
        .current_dir(root)
        .args(&native_scan_args)
        .output()
        .expect("native scan update");
    let wrapped = sgy(root, &engine, &wrapped_scan_args)
        .output()
        .expect("wrapped scan update");
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(
        std::fs::read_to_string(&wrapped_scan).expect("read wrapped scan result"),
        std::fs::read_to_string(&native_scan).expect("read native scan result")
    );
    let scan_yaml = parse_yaml_documents(&wrapped.stdout).expect("scan update YAML");
    assert_eq!(scan_yaml[0]["_sgy"]["kind"], "update-all");
    assert_eq!(scan_yaml[0]["_sgy"]["write"]["transactional"], false);
}

fn sgy(root: &Path, engine: &Path, native_args: &[std::ffi::OsString]) -> Command {
    sgy_with_wrapper(root, engine, &[], native_args)
}

fn sgy_with_wrapper(
    root: &Path,
    engine: &Path,
    wrapper_args: &[&str],
    native_args: &[std::ffi::OsString],
) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_sgy"));
    command
        .current_dir(root)
        .args(["exec", "--profile", "lossless", "--engine"])
        .arg(engine)
        .args(wrapper_args)
        .arg("--")
        .args(native_args);
    command
}

fn parse_native(input: &[u8], style: &str) -> Vec<serde_json::Value> {
    if style == "stream" {
        input
            .split(|byte| *byte == b'\n')
            .filter(|line| !line.iter().all(u8::is_ascii_whitespace))
            .map(|line| serde_json::from_slice(line).expect("native JSONL record"))
            .collect()
    } else {
        vec![serde_json::from_slice(input).expect("native JSON value")]
    }
}

fn output_with_stdin(command: &mut Command, input: &[u8]) -> Output {
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("spawn stdin command");
    child
        .stdin
        .take()
        .expect("stdin pipe")
        .write_all(input)
        .expect("write stdin");
    child.wait_with_output().expect("wait stdin command")
}
