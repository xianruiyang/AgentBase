use std::{
    path::{Path, PathBuf},
    process::Command,
};

use srcq_core::codec::parse_yaml_documents;

#[test]
#[ignore = "requires SRCQ_AST_GREP to point to a real ast-grep binary"]
fn real_help_version_completions_and_new_match_native_044() {
    let engine = PathBuf::from(
        std::env::var_os("SRCQ_AST_GREP").expect("SRCQ_AST_GREP must name ast-grep 0.44.1"),
    );
    let directory = tempfile::tempdir().expect("temporary raw fixture");

    for args in [vec!["--version"], vec!["--help"]] {
        let native = Command::new(&engine)
            .current_dir(directory.path())
            .args(&args)
            .output()
            .expect("native raw command");
        let wrapped = srcq(directory.path(), &engine)
            .arg("--")
            .args(&args)
            .output()
            .expect("wrapped raw command");
        assert_eq!(wrapped.status.code(), native.status.code());
        let document = &parse_yaml_documents(&wrapped.stdout).expect("raw YAML")[0];
        let native_text = String::from_utf8(native.stdout).expect("native UTF-8");
        let wrapped_text = document["stdout"].as_str().expect("wrapped UTF-8");
        assert!(native_text.starts_with(wrapped_text));
        assert_eq!(
            document["_sgy"]["total_chars"],
            native_text.chars().count() as u64
        );
        if args == ["--version"] {
            assert_eq!(wrapped_text, native_text);
            assert_eq!(document["_sgy"]["complete"], true);
        }
    }

    let artifact = directory.path().join("ast-grep.ps1");
    let native_completion = Command::new(&engine)
        .current_dir(directory.path())
        .args(["completions", "powershell"])
        .output()
        .expect("native completions");
    let wrapped_completion = srcq(directory.path(), &engine)
        .args([
            "--artifact-out",
            artifact.to_str().expect("UTF-8 artifact path"),
            "--",
            "completions",
            "powershell",
        ])
        .output()
        .expect("wrapped completions");
    assert_eq!(
        wrapped_completion.status.code(),
        native_completion.status.code()
    );
    assert_eq!(
        std::fs::read(&artifact).expect("completion artifact"),
        native_completion.stdout
    );
    let manifest = &parse_yaml_documents(&wrapped_completion.stdout).expect("manifest YAML")[0];
    assert_eq!(manifest["media_type"], "text/x-powershell");
    assert_eq!(manifest["encoding"], "utf-8");

    let native_root = directory.path().join("native-new");
    let wrapped_root = directory.path().join("wrapped-new");
    std::fs::create_dir(&native_root).expect("native new root");
    std::fs::create_dir(&wrapped_root).expect("wrapped new root");
    let native_new = Command::new(&engine)
        .current_dir(&native_root)
        .args(["new", "project", "-y"])
        .output()
        .expect("native new");
    let wrapped_new = srcq(&wrapped_root, &engine)
        .args(["--", "new", "project", "-y"])
        .output()
        .expect("wrapped new");
    assert_eq!(wrapped_new.status.code(), native_new.status.code());
    assert_eq!(snapshot_tree(&wrapped_root), snapshot_tree(&native_root));
    let document = &parse_yaml_documents(&wrapped_new.stdout).expect("new YAML")[0];
    assert_eq!(
        document["stdout"],
        String::from_utf8(native_new.stdout).expect("native new UTF-8")
    );

    let native_test = Command::new(&engine)
        .current_dir(&native_root)
        .args(["test", "-c", "sgconfig.yml"])
        .output()
        .expect("native test");
    let wrapped_test = srcq(&wrapped_root, &engine)
        .args(["--", "test", "-c", "sgconfig.yml"])
        .output()
        .expect("wrapped test");
    assert_eq!(wrapped_test.status.code(), native_test.status.code());
    let document = &parse_yaml_documents(&wrapped_test.stdout).expect("test YAML")[0];
    assert_eq!(document["_sgy"]["kind"], "test");
    let native_text = String::from_utf8(native_test.stdout).expect("native test UTF-8");
    assert!(native_text.starts_with(document["stdout"].as_str().expect("wrapped test text")));
}

fn srcq(cwd: &Path, engine: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_srcq"));
    command
        .current_dir(cwd)
        .args(["exec", "--output", "machine", "--engine"])
        .arg(engine)
        .args(["--cache", "off"]);
    command
}

fn snapshot_tree(root: &Path) -> Vec<(String, Vec<u8>)> {
    let mut files = Vec::new();
    collect_files(root, root, &mut files);
    files.sort_by(|left, right| left.0.cmp(&right.0));
    files
}

fn collect_files(root: &Path, directory: &Path, files: &mut Vec<(String, Vec<u8>)>) {
    let mut entries: Vec<_> = std::fs::read_dir(directory)
        .expect("read generated directory")
        .map(|entry| entry.expect("generated entry"))
        .collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            collect_files(root, &path, files);
        } else {
            let bytes = std::fs::read(&path).expect("generated file bytes");
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
