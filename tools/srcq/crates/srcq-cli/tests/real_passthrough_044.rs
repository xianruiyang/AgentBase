use std::{
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
};

use srcq_core::codec::parse_yaml_documents;

#[test]
#[ignore = "requires SRCQ_AST_GREP to point to a real ast-grep binary"]
fn real_lsp_initialize_request_shutdown_exit_is_byte_identical() {
    let engine = PathBuf::from(
        std::env::var_os("SRCQ_AST_GREP").expect("SRCQ_AST_GREP must name ast-grep 0.44.1"),
    );
    let version = Command::new(&engine)
        .arg("--version")
        .output()
        .expect("read ast-grep version");
    let expected_version = std::env::var("SRCQ_AST_GREP_EXPECTED_VERSION")
        .unwrap_or_else(|_| "ast-grep 0.44.1".to_owned());
    assert_eq!(
        String::from_utf8(version.stdout)
            .expect("UTF-8 version")
            .trim(),
        expected_version
    );

    let directory = tempfile::tempdir().expect("temporary LSP project");
    let initialized = Command::new(&engine)
        .current_dir(directory.path())
        .args(["new", "project", "-y"])
        .output()
        .expect("initialize ast-grep project");
    assert!(initialized.status.success());

    let input = lsp_session();
    let native = output_with_input(
        Command::new(&engine)
            .current_dir(directory.path())
            .arg("lsp"),
        &input,
    );
    let meta = directory.path().join("lsp-meta.yaml");
    let wrapped = output_with_input(
        srcq(directory.path(), &engine)
            .args(["--meta-out"])
            .arg(&meta)
            .args(["--", "lsp"]),
        &input,
    );
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(wrapped.stdout, native.stdout);
    assert_eq!(wrapped.stderr, native.stderr);

    let metadata = &parse_yaml_documents(&std::fs::read(meta).expect("read LSP metadata"))
        .expect("parse LSP metadata")[0];
    assert_eq!(metadata["schema"], "sgy.protocol-meta/v1");
    assert_eq!(metadata["engine_version"], expected_version);
    assert_eq!(metadata["stdin_bytes"], input.len() as u64);
    assert_eq!(metadata["stdout_bytes"], native.stdout.len() as u64);
    assert_eq!(metadata["stderr_bytes"], native.stderr.len() as u64);
}

fn srcq(root: &Path, engine: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
    command
        .current_dir(root)
        .args(["exec", "--engine"])
        .arg(engine)
        .args(["--cache", "off"]);
    command
}

fn output_with_input(command: &mut Command, input: &[u8]) -> Output {
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn LSP process");
    child
        .stdin
        .take()
        .expect("stdin pipe")
        .write_all(input)
        .expect("write LSP stream");
    child.wait_with_output().expect("wait LSP process")
}

fn lsp_session() -> Vec<u8> {
    let mut stream = Vec::new();
    for body in [
        br#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"processId":null,"rootUri":null,"capabilities":{}}}"#.as_slice(),
        br#"{"jsonrpc":"2.0","method":"initialized","params":{}}"#.as_slice(),
        br#"{"jsonrpc":"2.0","id":2,"method":"workspace/symbol","params":{"query":"fixture"}}"#.as_slice(),
        br#"{"jsonrpc":"2.0","id":3,"method":"shutdown","params":null}"#.as_slice(),
        br#"{"jsonrpc":"2.0","method":"exit","params":null}"#.as_slice(),
    ] {
        stream.extend_from_slice(format!("Content-Length: {}\r\n\r\n", body.len()).as_bytes());
        stream.extend_from_slice(body);
    }
    stream
}
