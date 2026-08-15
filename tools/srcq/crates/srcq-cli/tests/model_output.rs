use std::{path::Path, process::Command};

use srcq_core::codec::parse_yaml_documents;

fn srcq(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
    command.current_dir(cwd);
    command
}

#[test]
fn ast_defaults_doctor_and_artifact_use_clean_model_output() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    let engine = env!("CARGO_BIN_EXE_srcq-native-fixture");

    let ast = srcq(directory.path())
        .args([
            "exec",
            "--engine",
            engine,
            "--cache",
            "off",
            "--",
            "run",
            "--fixture-matches=1",
        ])
        .output()
        .expect("model AST query");
    assert!(ast.status.success());
    let ast = String::from_utf8(ast.stdout).expect("UTF-8 AST output");
    assert!(ast.starts_with("src/0.ts:0:0-0:5\nmatch-0-"));
    assert!(ast.contains("ruleId=rule-0"));
    assert!(!ast.contains("_sgy"));
    assert!(!ast.contains("metaVariables"));
    assert!(!ast.contains("schema"));

    let machine = srcq(directory.path())
        .args([
            "exec",
            "--output",
            "machine",
            "--engine",
            engine,
            "--cache",
            "off",
            "--",
            "run",
            "--fixture-matches=1",
        ])
        .output()
        .expect("machine AST query");
    assert!(machine.status.success());
    let machine = parse_yaml_documents(&machine.stdout).expect("machine safe YAML");
    assert_eq!(machine[0]["_sgy"]["schema"], "sgy.context/v1");

    let doctor = srcq(directory.path())
        .args(["doctor", "--engine", engine])
        .output()
        .expect("model doctor");
    assert!(doctor.status.success());
    assert_eq!(doctor.stdout, b"ok\n");

    let defaults = srcq(directory.path())
        .args(["defaults", "--", "run", "-p", "call($A)"])
        .output()
        .expect("model defaults");
    assert!(defaults.status.success());
    let defaults = String::from_utf8(defaults.stdout).expect("UTF-8 defaults");
    assert!(defaults.starts_with("BatchRun + "));
    assert!(defaults.contains("--json=stream"));
    assert!(!defaults.contains("effective_argv"));

    let artifact = directory.path().join("native.bin");
    let artifact_output = srcq(directory.path())
        .args([
            "exec",
            "--engine",
            engine,
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--",
            "future-command",
            "--fixture-invalid-utf8",
        ])
        .output()
        .expect("model artifact");
    assert!(artifact_output.status.success());
    let rendered = String::from_utf8(artifact_output.stdout).expect("UTF-8 artifact output");
    assert_eq!(
        rendered.trim(),
        artifact.to_string_lossy().replace('\\', "/")
    );
    assert!(!rendered.contains("sha256"));
}

#[test]
fn recognizable_wrong_shapes_return_one_unique_recovery_line() {
    let directory = tempfile::tempdir().expect("temporary cwd");
    for (args, expected) in [
        (&["files", "src"][..], "srcq: use: srcq fd <fd argv...>\n"),
        (&["--files", "src"][..], "srcq: use: srcq fd <fd argv...>\n"),
        (
            &["run", "-p", "call($A)"][..],
            "srcq: use: srcq exec -- <ast-grep argv...>\n",
        ),
        (
            &["exec", "run", "-p", "call($A)"][..],
            "srcq: use: srcq exec -- <ast-grep argv...>\n",
        ),
    ] {
        let output = srcq(directory.path())
            .args(args)
            .output()
            .expect("targeted recovery");
        assert_eq!(output.status.code(), Some(125));
        assert!(output.stdout.is_empty());
        assert_eq!(String::from_utf8_lossy(&output.stderr), expected);
    }
}
