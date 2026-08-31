use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value as JsonValue;
use toml::Value as TomlValue;

use super::{normalized_key, resolve_metadata_path, RootCandidate, RootSource, ScopeIssue};

const MAX_PROJECTS: usize = 256;
const MAX_BYTES: u64 = 1024 * 1024;

pub(super) fn discover(
    language: &str,
    root: &Path,
    roots: &mut Vec<RootCandidate>,
    issues: &mut Vec<ScopeIssue>,
) {
    match language {
        "typescript" | "tsx" | "javascript" => node(root, roots, issues),
        "rust" => cargo(root, roots, issues),
        "go" => go(root, roots, issues),
        "python" => python(root, roots, issues),
        _ => {}
    }
}

fn node(root: &Path, roots: &mut Vec<RootCandidate>, issues: &mut Vec<ScopeIssue>) {
    let mut pending = vec![root.to_path_buf()];
    let mut seen = BTreeSet::new();
    while let Some(base) = pending.pop() {
        if seen.len() >= MAX_PROJECTS {
            issue(
                issues,
                "project-config-limit",
                base,
                "project limit exceeded",
            );
            break;
        }
        if !seen.insert(normalized_key(&base)) {
            continue;
        }
        for name in ["tsconfig.json", "jsconfig.json"] {
            let file = base.join(name);
            if !file.is_file() {
                continue;
            }
            let value = match jsonc(&file) {
                Ok(v) => v,
                Err(e) => {
                    issue(issues, "project-config-unreadable", file, e);
                    continue;
                }
            };
            if let Some(value) = value.get("references") {
                let Some(values) = value.as_array() else {
                    issue(
                        issues,
                        "project-config-unsupported",
                        file,
                        "references is not an array",
                    );
                    continue;
                };
                for value in values {
                    match value.get("path").and_then(JsonValue::as_str) {
                        Some(raw) => add(root, &base, raw, roots, issues, Some(&mut pending)),
                        None => issue(
                            issues,
                            "project-config-unsupported",
                            file.clone(),
                            "reference path is not a string",
                        ),
                    }
                }
            }
        }
        let file = base.join("package.json");
        if !file.is_file() {
            continue;
        }
        let value = match jsonc(&file) {
            Ok(v) => v,
            Err(e) => {
                issue(issues, "project-config-unreadable", file, e);
                continue;
            }
        };
        for name in [
            "dependencies",
            "devDependencies",
            "optionalDependencies",
            "peerDependencies",
        ] {
            if let Some(table) = value.get(name) {
                let Some(table) = table.as_object() else {
                    issue(
                        issues,
                        "project-config-unsupported",
                        file.clone(),
                        format!("{name} is not an object"),
                    );
                    continue;
                };
                for raw in table.values().filter_map(JsonValue::as_str) {
                    if let Some(raw) = ["file:", "link:", "workspace:"]
                        .iter()
                        .find_map(|p| raw.strip_prefix(p))
                    {
                        if !raw.is_empty() && !matches!(raw, "*" | "^") {
                            add(root, &base, raw, roots, issues, Some(&mut pending));
                        }
                    }
                }
            }
        }
        if let Some(value) = value.get("workspaces") {
            let values = value
                .as_array()
                .or_else(|| value.get("packages").and_then(JsonValue::as_array));
            let Some(values) = values else {
                issue(
                    issues,
                    "project-config-unsupported",
                    file,
                    "workspaces is not an array",
                );
                continue;
            };
            for raw in values.iter().filter_map(JsonValue::as_str) {
                if raw.contains(['*', '?', '[']) {
                    issue(
                        issues,
                        "project-config-unsupported",
                        file.clone(),
                        format!("unsupported workspace pattern: {raw}"),
                    );
                } else {
                    add(root, &base, raw, roots, issues, Some(&mut pending));
                }
            }
        }
    }
}

fn cargo(root: &Path, roots: &mut Vec<RootCandidate>, issues: &mut Vec<ScopeIssue>) {
    let file = root.join("Cargo.toml");
    let Some(value) = toml_file(&file, issues) else {
        return;
    };
    if let Some(members) = value.get("workspace").and_then(|v| v.get("members")) {
        match members.as_array() {
            Some(values) => {
                for value in values {
                    match value.as_str() {
                        Some(raw) if !raw.contains(['*', '?', '[']) => {
                            add(root, root, raw, roots, issues, None)
                        }
                        Some(raw) => issue(
                            issues,
                            "project-config-unsupported",
                            file.clone(),
                            format!("unsupported workspace pattern: {raw}"),
                        ),
                        None => issue(
                            issues,
                            "project-config-unsupported",
                            file.clone(),
                            "workspace member is not a string",
                        ),
                    }
                }
            }
            None => issue(
                issues,
                "project-config-unsupported",
                file.clone(),
                "workspace.members is not an array",
            ),
        }
    }
    let mut paths = Vec::new();
    collect_paths(&value, &mut paths);
    for raw in paths {
        add(root, root, &raw, roots, issues, None);
    }
}

fn python(root: &Path, roots: &mut Vec<RootCandidate>, issues: &mut Vec<ScopeIssue>) {
    let file = root.join("pyproject.toml");
    let Some(value) = toml_file(&file, issues) else {
        return;
    };
    if root.join("src").is_dir() {
        add(root, root, "src", roots, issues, None);
    }
    let mut paths = Vec::new();
    collect_paths(&value, &mut paths);
    if let Some(table) = value
        .get("tool")
        .and_then(|v| v.get("setuptools"))
        .and_then(|v| v.get("package-dir"))
        .and_then(TomlValue::as_table)
    {
        paths.extend(
            table
                .values()
                .filter_map(TomlValue::as_str)
                .map(ToOwned::to_owned),
        );
    }
    for raw in paths {
        add(root, root, &raw, roots, issues, None);
    }
}

fn collect_paths(value: &TomlValue, paths: &mut Vec<String>) {
    match value {
        TomlValue::Table(table) => {
            if let Some(raw) = table.get("path").and_then(TomlValue::as_str) {
                paths.push(raw.to_owned());
            }
            for value in table.values() {
                collect_paths(value, paths);
            }
        }
        TomlValue::Array(values) => {
            for value in values {
                collect_paths(value, paths);
            }
        }
        _ => {}
    }
}

fn go(root: &Path, roots: &mut Vec<RootCandidate>, issues: &mut Vec<ScopeIssue>) {
    let work = root.join("go.work");
    if work.is_file() {
        match text(&work) {
            Ok(value) => go_use(root, &work, &value, roots, issues),
            Err(e) => issue(issues, "project-config-unreadable", work, e),
        }
    }
    let module = root.join("go.mod");
    if module.is_file() {
        match text(&module) {
            Ok(value) => {
                for line in value
                    .lines()
                    .map(str::trim)
                    .filter(|v| v.starts_with("replace "))
                {
                    match line.split_once("=>") {
                        Some((_, raw)) => {
                            let raw = raw.split_whitespace().next().unwrap_or("");
                            if raw.starts_with('.') || Path::new(raw).is_absolute() {
                                add(root, root, raw, roots, issues, None);
                            }
                        }
                        None => issue(
                            issues,
                            "project-config-unsupported",
                            module.clone(),
                            format!("unrecognized replace: {line}"),
                        ),
                    }
                }
            }
            Err(e) => issue(issues, "project-config-unreadable", module, e),
        }
    }
}

fn go_use(
    root: &Path,
    file: &Path,
    value: &str,
    roots: &mut Vec<RootCandidate>,
    issues: &mut Vec<ScopeIssue>,
) {
    let mut block = false;
    for line in value
        .lines()
        .map(|v| v.split("//").next().unwrap_or("").trim())
    {
        if line == "use (" {
            block = true;
            continue;
        }
        if block && line == ")" {
            block = false;
            continue;
        }
        let raw = if block {
            line
        } else {
            line.strip_prefix("use ").unwrap_or("")
        };
        if !raw.is_empty() {
            add(
                root,
                root,
                raw.split_whitespace().next().unwrap_or(""),
                roots,
                issues,
                None,
            );
        }
    }
    if block {
        issue(
            issues,
            "project-config-unsupported",
            file.to_path_buf(),
            "unterminated use block",
        );
    }
}

fn add(
    project: &Path,
    base: &Path,
    raw: &str,
    roots: &mut Vec<RootCandidate>,
    issues: &mut Vec<ScopeIssue>,
    pending: Option<&mut Vec<PathBuf>>,
) {
    let path = resolve_metadata_path(base, raw.trim_matches(['"', '\'']));
    match fs::canonicalize(&path) {
        Ok(path) if path.is_dir() => {
            if !path.starts_with(project) {
                roots.push(RootCandidate {
                    path: path.clone(),
                    source: RootSource::Workspace,
                    alias_hint: None,
                });
            }
            if let Some(pending) = pending {
                pending.push(path);
            }
        }
        _ => issue(
            issues,
            "project-root-missing",
            path,
            "local project root does not exist or is not a directory",
        ),
    }
}

fn text(path: &Path) -> Result<String, String> {
    let size = fs::metadata(path).map_err(|e| e.to_string())?.len();
    if size > MAX_BYTES {
        return Err(format!("metadata exceeds {MAX_BYTES} bytes"));
    }
    fs::read_to_string(path).map_err(|e| e.to_string())
}
fn toml_file(path: &Path, issues: &mut Vec<ScopeIssue>) -> Option<TomlValue> {
    if !path.is_file() {
        return None;
    }
    match text(path).and_then(|v| toml::from_str(&v).map_err(|e| e.to_string())) {
        Ok(v) => Some(v),
        Err(e) => {
            issue(issues, "project-config-unreadable", path.to_path_buf(), e);
            None
        }
    }
}
fn jsonc(path: &Path) -> Result<JsonValue, String> {
    serde_json::from_str(&strip_jsonc(&text(path)?)?).map_err(|e| e.to_string())
}

fn strip_jsonc(value: &str) -> Result<String, String> {
    let mut out = String::new();
    let mut chars = value.chars().peekable();
    let mut quoted = false;
    let mut escape = false;
    while let Some(ch) = chars.next() {
        if quoted {
            out.push(ch);
            if escape {
                escape = false;
            } else if ch == '\\' {
                escape = true;
            } else if ch == '"' {
                quoted = false;
            }
        } else if ch == '"' {
            quoted = true;
            out.push(ch);
        } else if ch == '/' && chars.peek() == Some(&'/') {
            chars.next();
            for next in chars.by_ref() {
                if next == '\n' {
                    out.push('\n');
                    break;
                }
            }
        } else if ch == '/' && chars.peek() == Some(&'*') {
            chars.next();
            let mut closed = false;
            while let Some(next) = chars.next() {
                if next == '*' && chars.peek() == Some(&'/') {
                    chars.next();
                    closed = true;
                    break;
                }
            }
            if !closed {
                return Err("unterminated block comment".to_owned());
            }
        } else if ch == ',' {
            let mut look = chars.clone();
            while look.peek().is_some_and(|v| v.is_whitespace()) {
                look.next();
            }
            if !matches!(look.peek(), Some(']') | Some('}')) {
                out.push(ch);
            }
        } else {
            out.push(ch);
        }
    }
    if quoted {
        Err("unterminated string".to_owned())
    } else {
        Ok(out)
    }
}

fn issue(
    issues: &mut Vec<ScopeIssue>,
    code: &'static str,
    path: PathBuf,
    detail: impl Into<String>,
) {
    issues.push(ScopeIssue {
        code,
        path: Some(path),
        detail: detail.into(),
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;
    fn write(path: &Path, value: &str) {
        fs::create_dir_all(path.parent().expect("parent")).expect("parent");
        fs::write(path, value).expect("write");
    }
    fn run(language: &str, root: &Path) -> (Vec<RootCandidate>, Vec<ScopeIssue>) {
        let mut roots = Vec::new();
        let mut issues = Vec::new();
        discover(language, root, &mut roots, &mut issues);
        (roots, issues)
    }
    #[test]
    fn node_external_roots() {
        let d = tempdir().expect("d");
        let r = d.path().join("app");
        for n in ["one", "two"] {
            fs::create_dir_all(d.path().join(n)).expect("dir");
        }
        write(
            &r.join("tsconfig.json"),
            "{/*c*/\"references\":[{\"path\":\"../one\",}],}",
        );
        write(
            &r.join("package.json"),
            "{\"dependencies\":{\"two\":\"file:../two\"}}",
        );
        let (v, e) = run("typescript", &r);
        assert!(e.is_empty());
        assert_eq!(v.len(), 2);
    }
    #[test]
    fn cargo_external_roots() {
        let d = tempdir().expect("d");
        let r = d.path().join("app");
        for n in ["member", "dep"] {
            fs::create_dir_all(d.path().join(n)).expect("dir");
        }
        write(
            &r.join("Cargo.toml"),
            "[workspace]\nmembers=[\"../member\"]\n[dependencies.dep]\npath=\"../dep\"\n",
        );
        let (v, e) = run("rust", &r);
        assert!(e.is_empty());
        assert_eq!(v.len(), 2);
    }
    #[test]
    fn go_external_roots() {
        let d = tempdir().expect("d");
        let r = d.path().join("app");
        for n in ["use", "replace"] {
            fs::create_dir_all(d.path().join(n)).expect("dir");
        }
        write(&r.join("go.work"), "go 1.23\nuse ../use\n");
        write(&r.join("go.mod"), "module app\nreplace x/y => ../replace\n");
        let (v, e) = run("go", &r);
        assert!(e.is_empty());
        assert_eq!(v.len(), 2);
    }
    #[test]
    fn python_external_roots() {
        let d = tempdir().expect("d");
        let r = d.path().join("app");
        fs::create_dir_all(r.join("src")).expect("src");
        fs::create_dir_all(d.path().join("dep")).expect("dep");
        write(&r.join("pyproject.toml"), "[tool.setuptools.package-dir]\n\"\"=\"src\"\n[tool.poetry.dependencies.dep]\npath=\"../dep\"\n");
        let (v, e) = run("python", &r);
        assert!(e.is_empty());
        assert!(v.iter().any(
            |candidate| candidate.path == fs::canonicalize(d.path().join("dep")).expect("dep")
        ));
    }
    #[test]
    fn malformed_and_missing_are_issues() {
        let d = tempdir().expect("d");
        let r = d.path().join("app");
        write(&r.join("tsconfig.json"), "{/* bad");
        write(
            &r.join("package.json"),
            "{\"dependencies\":{\"x\":\"file:../missing\"}}",
        );
        let (_, e) = run("typescript", &r);
        assert!(e.iter().any(|v| v.code == "project-config-unreadable"));
        assert!(e.iter().any(|v| v.code == "project-root-missing"));
    }
    #[test]
    fn unsupported_glob_is_issue() {
        let d = tempdir().expect("d");
        let r = d.path().join("app");
        write(&r.join("package.json"), "{\"workspaces\":[\"packages/*\"]}");
        let (_, e) = run("javascript", &r);
        assert!(e.iter().any(|v| v.code == "project-config-unsupported"));
    }

    #[test]
    fn node_project_limit_is_incomplete_evidence() {
        let d = tempdir().expect("d");
        for index in 0..=MAX_PROJECTS {
            let project = d.path().join(format!("project-{index}"));
            fs::create_dir_all(&project).expect("project");
            if index < MAX_PROJECTS {
                write(
                    &project.join("tsconfig.json"),
                    &format!(
                        "{{\"references\":[{{\"path\":\"../project-{}\"}}]}}",
                        index + 1
                    ),
                );
            }
        }
        let (_, issues) = run("typescript", &d.path().join("project-0"));
        assert!(issues
            .iter()
            .any(|issue| issue.code == "project-config-limit"));
    }
}
