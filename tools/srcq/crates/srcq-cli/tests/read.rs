use std::path::Path;
use std::process::{Command, Output};

fn read(cwd: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_srcq"))
        .current_dir(cwd)
        .arg("read")
        .args(args)
        .output()
        .expect("srcq read")
}

#[test]
fn inclusive_ranges_resolve_relative_and_absolute_literal_paths() {
    let dir = tempfile::tempdir().expect("cwd");
    let path = dir.path().join("中文 [literal] file.txt");
    std::fs::write(&path, "first\r\n中文\r\n\r\nlast").expect("fixture");
    for name in [
        "中文 [literal] file.txt",
        path.to_str().expect("absolute path"),
    ] {
        let result = read(dir.path(), &[name, "2", "3"]);
        assert!(result.status.success(), "{:?}", result.stderr);
        assert_eq!(result.stdout, "2:中文\r\n3:\r\n".as_bytes());
        assert!(result.stderr.is_empty());
    }
    let last = read(dir.path(), &[path.to_str().expect("path"), "4", "4"]);
    assert!(last.status.success());
    assert_eq!(last.stdout, b"4:last");
}

#[test]
fn numbering_is_case_insensitive_and_uses_original_lines() {
    let dir = tempfile::tempdir().expect("cwd");
    std::fs::write(dir.path().join("file"), "first\r\n中文\r\n\r\nlast").expect("fixture");
    for flag in ["--Number", "--number", "--NUMBER", "--nUmBeR"] {
        let result = read(dir.path(), &["file", "2", "4", flag]);
        assert!(result.status.success(), "{:?}", result.stderr);
        assert_eq!(result.stdout, "2:中文\r\n3:\r\n4:last".as_bytes());
        assert!(result.stderr.is_empty());
        let over = read(dir.path(), &["file", "2", "5", flag]);
        assert!(over.status.success());
        assert_eq!(over.stdout, result.stdout);
        assert!(over.stderr.is_empty());
    }
    for flag in ["--NoNumber", "--nonumber", "--NONUMBER", "--nOnUmBeR"] {
        let result = read(dir.path(), &["file", "2", "4", flag]);
        assert!(result.status.success(), "{:?}", result.stderr);
        assert_eq!(result.stdout, "中文\r\n\r\nlast".as_bytes());
        assert!(result.stderr.is_empty());
    }
    let conflict = read(dir.path(), &["file", "2", "4", "--number", "--NONUMBER"]);
    assert!(!conflict.status.success());
    assert!(conflict.stdout.is_empty());
    // The option normalizer must not change literal filenames after --.
    std::fs::write(dir.path().join("--nUmBeR"), "literal\n").expect("fixture");
    let literal = read(dir.path(), &["--", "--nUmBeR", "1", "1"]);
    assert!(literal.status.success());
    assert_eq!(literal.stdout, b"1:literal\n");
}

#[test]
fn invalid_ranges_never_emit_partial_content() {
    let dir = tempfile::tempdir().expect("cwd");
    std::fs::write(dir.path().join("file"), "one\ntwo\n").expect("fixture");
    for (start, end) in [("0", "1"), ("2", "1"), ("1", "999999999999999999999999999")] {
        let result = read(dir.path(), &["file", start, end]);
        assert!(!result.status.success());
        assert!(result.stdout.is_empty());
        assert!(!result.stderr.is_empty());
    }
    let end = read(dir.path(), &["file", "2", "2"]);
    assert!(end.status.success());
    assert_eq!(end.stdout, b"2:two\n");
}

#[test]
fn whole_file_and_overread_preserve_content_and_line_numbers() {
    let dir = tempfile::tempdir().expect("cwd");
    std::fs::write(dir.path().join("file"), "first\r\n中文\r\n\r\nlast").expect("fixture");
    for args in [vec!["file"], vec!["file", "1", "10000"]] {
        let result = read(dir.path(), &args);
        assert!(result.status.success(), "{:?}", result.stderr);
        assert_eq!(
            result.stdout,
            "1:first\r\n2:中文\r\n3:\r\n4:last".as_bytes()
        );
        assert!(result.stderr.is_empty());
    }
    for args in [
        vec!["file", "--NoNumber"],
        vec!["file", "1", "10000", "--NoNumber"],
    ] {
        let result = read(dir.path(), &args);
        assert!(result.status.success());
        assert_eq!(result.stdout, "first\r\n中文\r\n\r\nlast".as_bytes());
        assert!(result.stderr.is_empty());
    }
    let maximum = usize::MAX.to_string();
    let tail = read(dir.path(), &["file", "3", &maximum]);
    assert!(tail.status.success());
    assert_eq!(tail.stdout, b"3:\r\n4:last");
    assert!(tail.stderr.is_empty());
    for args in [vec!["file", "5", "10000"], vec!["file", &maximum, &maximum]] {
        let result = read(dir.path(), &args);
        assert!(result.status.success());
        assert!(result.stdout.is_empty());
        assert!(result.stderr.is_empty());
    }
}

#[test]
fn empty_files_succeed_with_empty_output() {
    let dir = tempfile::tempdir().expect("cwd");
    std::fs::write(dir.path().join("empty"), "").expect("fixture");
    for args in [
        vec!["empty"],
        vec!["empty", "1", "1000"],
        vec!["empty", "--NoNumber"],
    ] {
        let result = read(dir.path(), &args);
        assert!(result.status.success());
        assert!(result.stdout.is_empty());
        assert!(result.stderr.is_empty());
    }
}

#[test]
fn missing_files_directories_and_incomplete_ranges_fail_without_stdout() {
    let dir = tempfile::tempdir().expect("cwd");
    std::fs::write(dir.path().join("empty"), "").expect("fixture");
    for args in [
        vec!["missing", "1", "1"],
        vec!["missing"],
        vec![".", "1", "1"],
        vec!["."],
        vec!["empty", "1"],
        vec![],
    ] {
        let result = read(dir.path(), &args);
        assert!(!result.status.success());
        assert!(result.stdout.is_empty());
        assert!(!result.stderr.is_empty());
    }
}

#[test]
fn windows_encodings_preserve_text_and_omit_encoding_bom() {
    let dir = tempfile::tempdir().expect("cwd");
    let text = "中\r\nlast";
    let mut le = vec![0xff, 0xfe];
    let mut be = vec![0xfe, 0xff];
    for unit in text.encode_utf16() {
        le.extend(unit.to_le_bytes());
        be.extend(unit.to_be_bytes());
    }
    let utf8 = format!("\u{feff}{text}").into_bytes();
    let gbk = b"\xd6\xd0\r\nlast".to_vec();
    for bytes in [le, be, utf8, gbk] {
        std::fs::write(dir.path().join("file"), bytes).expect("fixture");
        let result = read(dir.path(), &["file", "1", "2", "--NoNumber"]);
        assert!(result.status.success(), "{:?}", result.stderr);
        assert_eq!(result.stdout, text.as_bytes());
    }
    for bytes in [
        vec![0xff, 0xfe, 0x00],
        vec![0xff, 0xfe, 0x00, 0xd8],
        vec![b'x', 0],
        vec![0xff],
    ] {
        std::fs::write(dir.path().join("file"), bytes).expect("fixture");
        let result = read(dir.path(), &["file", "1", "1"]);
        assert!(!result.status.success());
        assert!(result.stdout.is_empty());
    }
}

#[test]
fn selected_content_is_not_silently_truncated_or_paginated() {
    let dir = tempfile::tempdir().expect("cwd");
    let line = "x".repeat(40_000);
    std::fs::write(dir.path().join("file"), format!("before\n{line}\nafter\n")).expect("fixture");
    let result = read(dir.path(), &["file", "2", "2"]);
    assert!(result.status.success());
    assert_eq!(result.stdout, format!("2:{line}\n").as_bytes());
    assert!(result.stderr.is_empty());
}
