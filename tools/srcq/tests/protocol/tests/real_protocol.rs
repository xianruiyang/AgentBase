use std::{
    ffi::OsString,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

use portable_pty::{native_pty_system, CommandBuilder, ExitStatus, PtySize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use srcq_core::codec::parse_yaml_documents;

const EXPECTED_VERSION: &str = "ast-grep 0.42.0";

#[test]
#[ignore = "requires SRCQ_AST_GREP and a real platform PTY"]
fn real_interactive_run_and_scan_use_the_platform_pty_without_yaml() {
    let engine = real_engine();
    for mode in [InteractiveMode::Run, InteractiveMode::Scan] {
        let directory = tempfile::tempdir().expect("interactive fixture");
        let source = directory.path().join("input.ts");
        let original = b"const value = 1;\nconsole.log(value);\n";
        fs::write(&source, original).expect("interactive source");
        let rule = directory.path().join("rule.yml");
        fs::write(
            &rule,
            b"id: no-console\nlanguage: TypeScript\nrule:\n  pattern: console.log($A)\nfix: logger.info($A)\nmessage: avoid console.log\nseverity: warning\n",
        )
        .expect("interactive rule");

        let outcome = run_pty(
            directory.path(),
            &engine,
            mode.args(&source, &rule),
            &[PtyAction::Write(
                Duration::from_millis(350),
                b"\x1b[1;1Rn\r\n",
            )],
        );
        assert_ne!(outcome.status.exit_code(), 125, "{mode:?} lacked TTY");
        assert_ne!(outcome.status.exit_code(), 130, "{mode:?} was cancelled");
        assert_eq!(fs::read(&source).expect("source after reject"), original);
        let terminal = String::from_utf8_lossy(&outcome.output);
        assert!(!terminal.contains("_sgy"), "{mode:?} emitted YAML");
        assert!(!terminal.contains("E_TTY_UNAVAILABLE"), "{mode:?}");
        #[cfg(windows)]
        {
            assert!(
                terminal.contains("\x1b[6n"),
                "{mode:?} made no terminal query"
            );
            assert!(terminal.contains("\x1b[25l"), "{mode:?} did not enter TUI");
            assert!(
                terminal.contains("\x1b[?25h"),
                "{mode:?} did not restore cursor"
            );
        }
        assert!(
            outcome.output.contains(&0x1b),
            "{mode:?} lost terminal ANSI"
        );
    }
}

#[cfg(windows)]
#[test]
#[ignore = "requires SRCQ_AST_GREP and a real Windows Console"]
fn real_windows_console_ctrl_c_is_normalized_to_130() {
    let engine = real_engine();
    let directory = tempfile::tempdir().expect("Windows Console Ctrl+C fixture");
    let source = directory.path().join("input.ts");
    let original = b"const value = 1;\nconsole.log(value);\n";
    fs::write(&source, original).expect("Windows Console Ctrl+C source");
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("scripts")
        .join("windows-console-ctrl-c.ps1");
    let output = Command::new("pwsh")
        .args(["-NoLogo", "-NoProfile", "-NonInteractive", "-File"])
        .arg(script)
        .arg("-Driver")
        .arg(env!("CARGO_BIN_EXE_srcq-protocol-driver"))
        .arg("-Engine")
        .arg(&engine)
        .arg("-Source")
        .arg(&source)
        .output()
        .expect("run Windows Console Ctrl+C probe");
    assert!(
        output.status.success(),
        "Windows Console probe failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(fs::read(&source).expect("source after Ctrl+C"), original);
}

#[test]
#[ignore = "requires SRCQ_AST_GREP to point to a real ast-grep binary"]
fn real_lsp_is_bidirectionally_byte_identical_and_meta_is_private() {
    let engine = real_engine();
    let directory = tempfile::tempdir().expect("real LSP fixture");
    initialize_project(directory.path(), &engine);
    let input = lsp_session();

    let native = output_with_input(
        Command::new(&engine)
            .current_dir(directory.path())
            .arg("lsp"),
        &input,
    );
    let meta = directory.path().join("lsp-meta.yml");
    let wrapped = output_with_input(
        srcq(directory.path())
            .args(["exec", "--engine"])
            .arg(&engine)
            .args(["--cache", "off", "--meta-out"])
            .arg(&meta)
            .args(["--", "lsp"]),
        &input,
    );
    assert_eq!(wrapped.status.code(), native.status.code());
    assert_eq!(wrapped.stdout, native.stdout);
    assert_eq!(
        normalize_lsp_stderr(&wrapped.stderr),
        normalize_lsp_stderr(&native.stderr),
        "LSP stderr differs after removing renderer ANSI and nondeterministic timestamps"
    );
    assert!(!wrapped.stdout.is_empty());
    assert_eq!(sha256(&wrapped.stdout), sha256(&native.stdout));
    assert_eq!(sha256(&input).len(), 64);

    let metadata = parse_yaml_documents(&fs::read(&meta).expect("LSP meta"))
        .expect("safe LSP meta")
        .remove(0);
    assert_eq!(metadata["schema"], "sgy.protocol-meta/v1");
    assert_eq!(metadata["channel"], "lsp");
    assert_eq!(metadata["stdin_bytes"], input.len() as u64);
    assert_eq!(metadata["stdout_bytes"], native.stdout.len() as u64);
    assert_eq!(metadata["stderr_bytes"], native.stderr.len() as u64);
    let meta_text = fs::read_to_string(meta).expect("UTF-8 LSP meta");
    for secret in [
        "initialize",
        "workspace/symbol",
        "协议-中文-λ",
        "file:///protocol/%E4%B8%AD%E6%96%87",
        "jsonrpc",
    ] {
        assert!(!meta_text.contains(secret), "metadata leaked {secret:?}");
    }
    assert!(!String::from_utf8_lossy(&wrapped.stdout).contains("sgy.protocol-meta"));
}

#[test]
#[ignore = "requires SRCQ_AST_GREP and the target shell"]
fn real_completion_artifact_is_exact_and_loadable_by_the_target_shell() {
    let engine = real_engine();
    let directory = tempfile::tempdir().expect("completion fixture");
    let (shell, extension, media_type) = completion_target();
    let artifact = directory.path().join(format!("ast-grep.{extension}"));
    let native = Command::new(&engine)
        .current_dir(directory.path())
        .args(["completions", shell])
        .output()
        .expect("native completion");
    assert!(native.status.success());
    let wrapped = srcq(directory.path())
        .args(["exec", "--output", "machine", "--engine"])
        .arg(&engine)
        .args(["--cache", "off", "--artifact-out"])
        .arg(&artifact)
        .args(["--", "completions", shell])
        .output()
        .expect("wrapped completion");
    assert_eq!(wrapped.status.code(), native.status.code());
    let artifact_bytes = fs::read(&artifact).expect("completion artifact");
    assert_eq!(artifact_bytes, native.stdout);

    let manifest = parse_yaml_documents(&wrapped.stdout)
        .expect("completion manifest")
        .remove(0);
    assert_eq!(manifest["bytes"], artifact_bytes.len() as u64);
    assert_eq!(manifest["sha256"], sha256(&artifact_bytes));
    assert_eq!(manifest["media_type"], media_type);
    assert_eq!(manifest["encoding"], "utf-8");
    load_completion(&artifact);
}

#[test]
#[ignore = "requires SRCQ_AST_GREP to point to a real ast-grep binary"]
fn real_new_and_test_preserve_native_status_and_side_effects() {
    let engine = real_engine();
    let directory = tempfile::tempdir().expect("new/test fixture");
    let native_root = directory.path().join("native");
    let wrapped_root = directory.path().join("wrapped");
    fs::create_dir(&native_root).expect("native project root");
    fs::create_dir(&wrapped_root).expect("wrapped project root");

    let native_new = Command::new(&engine)
        .current_dir(&native_root)
        .args(["new", "project", "-y"])
        .output()
        .expect("native new");
    let wrapped_new = srcq(&wrapped_root)
        .args(["exec", "--output", "machine", "--engine"])
        .arg(&engine)
        .args(["--cache", "off", "--", "new", "project", "-y"])
        .output()
        .expect("wrapped new");
    assert_eq!(wrapped_new.status.code(), native_new.status.code());
    assert_eq!(snapshot_tree(&wrapped_root), snapshot_tree(&native_root));
    let new_document = parse_yaml_documents(&wrapped_new.stdout)
        .expect("new YAML")
        .remove(0);
    assert_eq!(
        new_document["stdout"],
        String::from_utf8(native_new.stdout).expect("native new UTF-8")
    );

    let native_test = Command::new(&engine)
        .current_dir(&native_root)
        .args(["test", "-c", "sgconfig.yml"])
        .output()
        .expect("native test");
    let wrapped_test = srcq(&wrapped_root)
        .args(["exec", "--output", "machine", "--engine"])
        .arg(&engine)
        .args(["--cache", "off", "--", "test", "-c", "sgconfig.yml"])
        .output()
        .expect("wrapped test");
    assert_eq!(wrapped_test.status.code(), native_test.status.code());
    let test_document = parse_yaml_documents(&wrapped_test.stdout)
        .expect("test YAML")
        .remove(0);
    assert_eq!(test_document["_sgy"]["kind"], "test");
    assert!(String::from_utf8(native_test.stdout)
        .expect("native test UTF-8")
        .starts_with(test_document["stdout"].as_str().expect("wrapped test text")));
}

#[derive(Clone, Copy, Debug)]
enum InteractiveMode {
    Run,
    Scan,
}

impl InteractiveMode {
    fn args(self, source: &Path, rule: &Path) -> Vec<OsString> {
        match self {
            Self::Run => os_args([
                "run",
                "-p",
                "console.log($A)",
                "-r",
                "logger.info($A)",
                "-i",
                "-l",
                "ts",
            ])
            .into_iter()
            .chain([source.as_os_str().to_owned()])
            .collect(),
            Self::Scan => os_args(["scan", "-r"])
                .into_iter()
                .chain([rule.as_os_str().to_owned()])
                .chain(os_args(["-i"]))
                .chain([source.as_os_str().to_owned()])
                .collect(),
        }
    }
}

struct PtyOutcome {
    status: ExitStatus,
    output: Vec<u8>,
}

enum PtyAction<'a> {
    Write(Duration, &'a [u8]),
}

enum OwnedPtyAction {
    Write(Duration, Vec<u8>),
}

fn run_pty(
    cwd: &Path,
    engine: &Path,
    native_args: Vec<OsString>,
    input: &[PtyAction<'_>],
) -> PtyOutcome {
    let pair = native_pty_system()
        .openpty(PtySize {
            rows: 40,
            cols: 120,
            pixel_width: 0,
            pixel_height: 0,
        })
        .expect("open native PTY");
    let mut command = CommandBuilder::new(env!("CARGO_BIN_EXE_srcq-protocol-driver"));
    command.cwd(cwd);
    command.args(os_args(["exec", "--engine"]));
    command.arg(engine);
    command.args(os_args(["--cache", "off", "--"]));
    command.args(native_args);
    command.env("TERM", "xterm-256color");
    configure_pty_environment(&mut command, cwd);
    let mut child = pair
        .slave
        .spawn_command(command)
        .expect("spawn srcq in native PTY");
    drop(pair.slave);

    let mut reader = pair.master.try_clone_reader().expect("clone PTY reader");
    let (output_tx, output_rx) = mpsc::channel();
    let _reader_thread = thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(count) => {
                    if output_tx.send(buffer[..count].to_vec()).is_err() {
                        break;
                    }
                }
            }
        }
    });
    let mut writer = pair.master.take_writer().expect("take PTY writer");
    let input = input
        .iter()
        .map(|action| match action {
            PtyAction::Write(delay, bytes) => OwnedPtyAction::Write(*delay, bytes.to_vec()),
        })
        .collect::<Vec<_>>();
    let (writer_tx, writer_rx) = mpsc::channel();
    let _writer_thread = thread::spawn(move || {
        for action in input {
            match action {
                OwnedPtyAction::Write(delay, bytes) => {
                    thread::sleep(delay);
                    if let Err(error) = writer.write_all(&bytes) {
                        let _ = writer_tx.send(Err(error));
                        return;
                    }
                }
            }
        }
        let _ = writer_tx.send(Ok(()));
    });
    writer_rx
        .recv_timeout(Duration::from_secs(3))
        .expect("PTY input writer timed out")
        .expect("write PTY input");

    let deadline = Instant::now() + Duration::from_secs(20);
    let status = loop {
        if let Some(status) = child.try_wait().expect("poll PTY child") {
            break status;
        }
        if Instant::now() >= deadline {
            child.kill().expect("kill timed out PTY child");
            let _ = child.wait();
            std::mem::forget(pair.master);
            let captured: Vec<u8> = output_rx.try_iter().flatten().collect();
            panic!(
                "PTY child timed out; output={:?}",
                String::from_utf8_lossy(&captured)
            );
        }
        thread::sleep(Duration::from_millis(20));
    };
    // portable-pty 0.9's Windows ConPTY master drop can wait forever while a cloned reader is
    // blocked. The process is already reaped; retain this test-only handle until process exit.
    std::mem::forget(pair.master);
    let mut output = Vec::new();
    let output_deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < output_deadline {
        match output_rx.recv_timeout(Duration::from_millis(50)) {
            Ok(chunk) => output.extend_from_slice(&chunk),
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                if !output.is_empty() {
                    break;
                }
            }
        }
    }
    PtyOutcome { status, output }
}

fn configure_pty_environment(command: &mut CommandBuilder, root: &Path) {
    command.env("LOCALAPPDATA", root);
    command.env("APPDATA", root);
}

fn output_with_input(command: &mut Command, input: &[u8]) -> Output {
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn protocol process");
    child
        .stdin
        .take()
        .expect("protocol stdin")
        .write_all(input)
        .expect("write protocol input");
    child.wait_with_output().expect("wait protocol process")
}

fn lsp_session() -> Vec<u8> {
    let bodies = [
        json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": Value::Null,
                "rootUri": "file:///protocol/%E4%B8%AD%E6%96%87",
                "capabilities": {},
                "clientInfo": {"name": "协议-中文-λ", "version": "1"}
            }
        }),
        json!({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
        json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "workspace/symbol",
            "params": {"query": "协议-中文-λ"}
        }),
        json!({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": Value::Null}),
        json!({"jsonrpc": "2.0", "method": "exit", "params": Value::Null}),
    ];
    let mut stream = Vec::new();
    for (ordinal, body) in bodies.into_iter().enumerate() {
        let body = serde_json::to_vec(&body).expect("serialize LSP body");
        stream.extend_from_slice(format!("Content-Length: {}\r\n", body.len()).as_bytes());
        if ordinal % 2 == 0 {
            stream
                .extend_from_slice(b"Content-TYPE: application/vscode-jsonrpc; charset=utf-8\r\n");
        }
        stream.extend_from_slice(b"\r\n");
        stream.extend_from_slice(&body);
    }
    stream
}

fn initialize_project(cwd: &Path, engine: &Path) {
    let output = Command::new(engine)
        .current_dir(cwd)
        .args(["new", "project", "-y"])
        .output()
        .expect("initialize real ast-grep project");
    assert!(
        output.status.success(),
        "project init failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn real_engine() -> PathBuf {
    let engine = PathBuf::from(
        std::env::var_os("SRCQ_AST_GREP").expect("SRCQ_AST_GREP must name real ast-grep"),
    );
    assert!(
        engine.is_file(),
        "engine is not a file: {}",
        engine.display()
    );
    let output = Command::new(&engine)
        .arg("--version")
        .output()
        .expect("real ast-grep version");
    assert!(output.status.success());
    let actual = String::from_utf8(output.stdout)
        .expect("UTF-8 version")
        .trim()
        .to_owned();
    let expected = std::env::var("SRCQ_AST_GREP_EXPECTED_VERSION")
        .unwrap_or_else(|_| EXPECTED_VERSION.to_owned());
    assert_eq!(actual, expected);
    engine
}

fn srcq(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq-protocol-driver"));
    command.current_dir(cwd);
    configure_command_environment(&mut command, cwd);
    command
}

fn configure_command_environment(command: &mut Command, root: &Path) {
    command.env("LOCALAPPDATA", root).env("APPDATA", root);
}

fn completion_target() -> (&'static str, &'static str, &'static str) {
    ("powershell", "ps1", "text/x-powershell")
}

fn load_completion(path: &Path) {
    let output = Command::new("pwsh")
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference='Stop'; . $env:SRCQ_COMPLETION",
        ])
        .env("SRCQ_COMPLETION", path)
        .output()
        .expect("load PowerShell completion");
    assert!(
        output.status.success(),
        "PowerShell rejected completion: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn normalize_lsp_stderr(bytes: &[u8]) -> Vec<String> {
    let plain = strip_ansi_csi(bytes);
    String::from_utf8_lossy(&plain)
        .lines()
        .map(|line| {
            ["TRACE", "DEBUG", "INFO", "WARN", "ERROR"]
                .iter()
                .filter_map(|level| line.find(level))
                .min()
                .map_or_else(|| line.to_owned(), |start| line[start..].to_owned())
        })
        .collect()
}

fn strip_ansi_csi(bytes: &[u8]) -> Vec<u8> {
    let mut plain = Vec::with_capacity(bytes.len());
    let mut position = 0;
    while position < bytes.len() {
        if bytes[position] == 0x1b && bytes.get(position + 1) == Some(&b'[') {
            position += 2;
            while position < bytes.len() {
                let byte = bytes[position];
                position += 1;
                if (0x40..=0x7e).contains(&byte) {
                    break;
                }
            }
        } else {
            plain.push(bytes[position]);
            position += 1;
        }
    }
    plain
}

fn os_args<const N: usize>(args: [&str; N]) -> Vec<OsString> {
    args.into_iter().map(OsString::from).collect()
}

fn snapshot_tree(root: &Path) -> Vec<(String, Vec<u8>)> {
    let mut files = Vec::new();
    collect_files(root, root, &mut files);
    files.sort_by(|left, right| left.0.cmp(&right.0));
    files
}

fn collect_files(root: &Path, directory: &Path, files: &mut Vec<(String, Vec<u8>)>) {
    let mut entries: Vec<_> = fs::read_dir(directory)
        .expect("read generated directory")
        .map(|entry| entry.expect("generated entry"))
        .collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            collect_files(root, &path, files);
        } else {
            let bytes = fs::read(&path).expect("generated file bytes");
            let bytes = String::from_utf8(bytes).map_or_else(
                |error| error.into_bytes(),
                |text| {
                    text.replace(&root.to_string_lossy().to_string(), "<ROOT>")
                        .into_bytes()
                },
            );
            files.push((
                path.strip_prefix(root)
                    .expect("generated relative path")
                    .to_string_lossy()
                    .replace('\\', "/"),
                bytes,
            ));
        }
    }
}
