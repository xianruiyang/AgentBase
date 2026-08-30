use std::collections::{BTreeSet, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::SymbolCommand;

const MAX_METADATA_BYTES: u64 = 64 * 1024 * 1024;
const MAX_RESPONSE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_RESPONSE_DEPTH: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ScopeStatus {
    Resolved,
    Bounded,
    Incomplete,
}

impl ScopeStatus {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::Bounded => "bounded",
            Self::Incomplete => "incomplete",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
enum RootSource {
    Explicit,
    Project,
    CompileDirectory,
    CompileInclude,
    Workspace,
}

impl RootSource {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Explicit => "explicit",
            Self::Project => "project",
            Self::CompileDirectory => "compile_directory",
            Self::CompileInclude => "compile_include",
            Self::Workspace => "workspace",
        }
    }

    const fn priority(self) -> u8 {
        match self {
            Self::Explicit => 0,
            Self::Project => 1,
            Self::Workspace => 2,
            Self::CompileDirectory => 3,
            Self::CompileInclude => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RootCandidate {
    path: PathBuf,
    source: RootSource,
    alias_hint: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SourceRoot {
    pub(crate) alias: String,
    pub(crate) path: PathBuf,
    pub(crate) source: &'static str,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ScopeIssue {
    pub(crate) code: &'static str,
    pub(crate) path: Option<PathBuf>,
    pub(crate) detail: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SourceUniverse {
    pub(crate) cwd: PathBuf,
    pub(crate) project_root: PathBuf,
    pub(crate) roots: Vec<SourceRoot>,
    pub(crate) compile_files: Vec<PathBuf>,
    pub(crate) compile_directories: Vec<PathBuf>,
    pub(crate) excludes: Vec<PathBuf>,
    pub(crate) issues: Vec<ScopeIssue>,
    pub(crate) status: ScopeStatus,
}

impl SourceUniverse {
    pub(crate) fn render_path(&self, path: &Path) -> String {
        if let Ok(relative) = path.strip_prefix(&self.project_root) {
            return slash_path(relative);
        }
        slash_path(path)
    }

    pub(crate) fn root_for(&self, path: &Path) -> Option<&SourceRoot> {
        self.roots
            .iter()
            .filter(|root| path.starts_with(&root.path))
            .max_by_key(|root| root.path.components().count())
    }

    pub(crate) fn is_excluded(&self, path: &Path) -> bool {
        self.excludes
            .iter()
            .any(|excluded| path.starts_with(excluded))
    }
}

pub(crate) fn resolve(
    command: &SymbolCommand,
    cwd: &Path,
    anchor_file: Option<&Path>,
) -> Result<SourceUniverse, String> {
    let discovery_start = anchor_file.and_then(Path::parent).unwrap_or(cwd);
    let cwd_project = anchor_file
        .filter(|anchor| anchor.starts_with(cwd))
        .and_then(|_| find_project_root(cwd));
    let project_root = cwd_project
        .or_else(|| find_project_root(discovery_start))
        .unwrap_or_else(|| cwd.to_path_buf());
    let project_root = canonical_existing(&project_root, cwd, "project root")?;
    let mut candidates = Vec::new();
    let mut compile_files = Vec::new();
    let mut compile_directories = Vec::new();
    let mut issues = Vec::new();
    let explicitly_bounded = !command.only_roots.is_empty() || !command.excludes.is_empty();

    if command.only_roots.is_empty() {
        candidates.push(RootCandidate {
            path: project_root.clone(),
            source: RootSource::Project,
            alias_hint: Some("project".to_owned()),
        });
        discover_workspace_roots(&project_root, &mut candidates, &mut issues);
        if command.language == "cpp" {
            discover_compile_roots(
                &project_root,
                &mut candidates,
                &mut compile_files,
                &mut compile_directories,
                &mut issues,
            );
        }
        for root in &command.add_roots {
            candidates.push(RootCandidate {
                path: canonical_existing(root, cwd, "added root")?,
                source: RootSource::Explicit,
                alias_hint: None,
            });
        }
    } else {
        for root in &command.only_roots {
            candidates.push(RootCandidate {
                path: canonical_existing(root, cwd, "only root")?,
                source: RootSource::Explicit,
                alias_hint: None,
            });
        }
    }

    let mut excludes = Vec::new();
    for excluded in &command.excludes {
        excludes.push(canonical_existing(excluded, cwd, "excluded path")?);
    }
    dedupe_paths(&mut excludes);
    dedupe_paths(&mut compile_files);
    dedupe_paths(&mut compile_directories);

    candidates.retain(|candidate| {
        !excludes
            .iter()
            .any(|excluded| candidate.path.starts_with(excluded))
    });
    dedupe_candidates(&mut candidates);
    let candidates = minimize_roots(candidates);
    if candidates.is_empty() {
        return Err("selected source scope contains no existing files or directories".to_owned());
    }
    let roots = assign_aliases(candidates, &project_root);
    let status = if !issues.is_empty() {
        ScopeStatus::Incomplete
    } else if explicitly_bounded {
        ScopeStatus::Bounded
    } else {
        ScopeStatus::Resolved
    };
    Ok(SourceUniverse {
        cwd: cwd.to_path_buf(),
        project_root,
        roots,
        compile_files,
        compile_directories,
        excludes,
        issues,
        status,
    })
}

fn find_project_root(start: &Path) -> Option<PathBuf> {
    let mut fallback = None;
    for directory in start.ancestors() {
        if has_strong_project_marker(directory) {
            return Some(directory.to_path_buf());
        }
        if fallback.is_none() && has_weak_project_marker(directory) {
            fallback = Some(directory.to_path_buf());
        }
    }
    fallback
}

fn has_strong_project_marker(directory: &Path) -> bool {
    if directory.join(".git").exists()
        || directory.join("compile_commands.json").is_file()
        || !compile_databases(directory).is_empty()
    {
        return true;
    }
    read_directory(directory).is_some_and(|entries| {
        entries.iter().any(|path| {
            matches!(
                lower_extension(path).as_deref(),
                Some("uproject" | "sln" | "code-workspace")
            )
        })
    })
}

fn has_weak_project_marker(directory: &Path) -> bool {
    [
        "Cargo.toml",
        "package.json",
        "pyproject.toml",
        "go.mod",
        "build.gradle",
        "pom.xml",
    ]
    .iter()
    .any(|name| directory.join(name).is_file())
}

fn discover_workspace_roots(
    project_root: &Path,
    candidates: &mut Vec<RootCandidate>,
    issues: &mut Vec<ScopeIssue>,
) {
    let Some(entries) = read_directory(project_root) else {
        return;
    };
    for workspace in entries
        .into_iter()
        .filter(|path| lower_extension(path).as_deref() == Some("code-workspace"))
    {
        let value = match read_json_bounded(&workspace, MAX_METADATA_BYTES) {
            Ok(value) => value,
            Err(detail) => {
                issues.push(ScopeIssue {
                    code: "workspace-unreadable",
                    path: Some(workspace),
                    detail,
                });
                continue;
            }
        };
        let Some(folders) = value.get("folders").and_then(Value::as_array) else {
            continue;
        };
        let base = workspace.parent().unwrap_or(project_root);
        for folder in folders {
            let Some(raw) = folder.get("path").and_then(Value::as_str) else {
                continue;
            };
            let path = resolve_metadata_path(base, raw);
            match fs::canonicalize(&path) {
                Ok(path) if path.is_dir() || path.is_file() => candidates.push(RootCandidate {
                    path,
                    source: RootSource::Workspace,
                    alias_hint: folder
                        .get("name")
                        .and_then(Value::as_str)
                        .map(ToOwned::to_owned),
                }),
                _ => issues.push(ScopeIssue {
                    code: "workspace-root-missing",
                    path: Some(path),
                    detail: "workspace folder does not exist".to_owned(),
                }),
            }
        }
    }
}

fn discover_compile_roots(
    project_root: &Path,
    candidates: &mut Vec<RootCandidate>,
    compile_files: &mut Vec<PathBuf>,
    compile_directories: &mut Vec<PathBuf>,
    issues: &mut Vec<ScopeIssue>,
) {
    for database in compile_databases(project_root) {
        let value = match read_json_bounded(&database, MAX_METADATA_BYTES) {
            Ok(value) => value,
            Err(detail) => {
                issues.push(ScopeIssue {
                    code: "compile-database-unreadable",
                    path: Some(database),
                    detail,
                });
                continue;
            }
        };
        let Some(entries) = value.as_array() else {
            issues.push(ScopeIssue {
                code: "compile-database-invalid",
                path: Some(database),
                detail: "compile database root is not an array".to_owned(),
            });
            continue;
        };
        let mut response_visited = HashSet::new();
        let mut response_active = HashSet::new();
        for entry in entries {
            let Some(raw_directory) = entry.get("directory").and_then(Value::as_str) else {
                continue;
            };
            let directory =
                resolve_metadata_path(database.parent().unwrap_or(project_root), raw_directory);
            let Ok(directory) = fs::canonicalize(&directory) else {
                issues.push(ScopeIssue {
                    code: "compile-directory-missing",
                    path: Some(directory),
                    detail: "compile command working directory does not exist".to_owned(),
                });
                continue;
            };
            if directory.is_dir() {
                compile_directories.push(directory.clone());
                candidates.push(RootCandidate {
                    path: directory.clone(),
                    source: RootSource::CompileDirectory,
                    alias_hint: None,
                });
            }
            if let Some(raw_file) = entry.get("file").and_then(Value::as_str) {
                let file = resolve_metadata_path(&directory, raw_file);
                if let Ok(file) = fs::canonicalize(file) {
                    if file.is_file() {
                        compile_files.push(file);
                    }
                }
            }
            let tokens = compile_tokens(entry);
            inspect_compile_tokens(
                &tokens,
                &directory,
                0,
                &mut response_visited,
                &mut response_active,
                candidates,
                issues,
            );
        }
    }
}

fn compile_databases(project_root: &Path) -> Vec<PathBuf> {
    let mut databases = Vec::new();
    let direct = project_root.join("compile_commands.json");
    if direct.is_file() {
        databases.push(direct);
    }
    let vscode = project_root.join(".vscode");
    if let Some(entries) = read_directory(&vscode) {
        for path in entries {
            let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
                continue;
            };
            let normalized = name.to_ascii_lowercase();
            if path.is_file()
                && normalized.ends_with(".json")
                && (normalized.starts_with("compilecommands")
                    || normalized.starts_with("compile_commands"))
            {
                databases.push(path);
            }
        }
    }
    databases.sort_by_key(|path| normalized_key(path));
    databases.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    databases
}

fn compile_tokens(entry: &Value) -> Vec<String> {
    if let Some(arguments) = entry.get("arguments").and_then(Value::as_array) {
        return arguments
            .iter()
            .filter_map(Value::as_str)
            .map(ToOwned::to_owned)
            .collect();
    }
    entry
        .get("command")
        .and_then(Value::as_str)
        .map(split_windows_command_line)
        .unwrap_or_default()
}

fn inspect_compile_tokens(
    tokens: &[String],
    base: &Path,
    depth: usize,
    response_visited: &mut HashSet<String>,
    response_active: &mut HashSet<String>,
    candidates: &mut Vec<RootCandidate>,
    issues: &mut Vec<ScopeIssue>,
) {
    let mut index = 0;
    while index < tokens.len() {
        let token = tokens[index].trim();
        if let Some(raw) = token.strip_prefix('@') {
            inspect_response_file(
                raw,
                base,
                depth,
                response_visited,
                response_active,
                candidates,
                issues,
            );
            index += 1;
            continue;
        }
        let (inline, consumes_next) = include_value(token, tokens.get(index + 1));
        if let Some(raw) = inline {
            let path = resolve_metadata_path(base, raw);
            if let Ok(path) = fs::canonicalize(&path) {
                if path.is_dir() || path.is_file() {
                    candidates.push(RootCandidate {
                        path,
                        source: RootSource::CompileInclude,
                        alias_hint: None,
                    });
                }
            }
        }
        index += if consumes_next { 2 } else { 1 };
    }
}

fn inspect_response_file(
    raw: &str,
    base: &Path,
    depth: usize,
    response_visited: &mut HashSet<String>,
    response_active: &mut HashSet<String>,
    candidates: &mut Vec<RootCandidate>,
    issues: &mut Vec<ScopeIssue>,
) {
    let path = resolve_metadata_path(base, trim_quotes(raw));
    if depth >= MAX_RESPONSE_DEPTH {
        issues.push(ScopeIssue {
            code: "response-depth",
            path: Some(path),
            detail: "response-file nesting exceeded the bounded depth".to_owned(),
        });
        return;
    }
    let canonical = match fs::canonicalize(&path) {
        Ok(path) if path.is_file() => path,
        _ => {
            issues.push(ScopeIssue {
                code: "response-missing",
                path: Some(path),
                detail: "referenced compiler response file does not exist".to_owned(),
            });
            return;
        }
    };
    let key = normalized_key(&canonical);
    if response_active.contains(&key) {
        issues.push(ScopeIssue {
            code: "response-cycle",
            path: Some(canonical),
            detail: "compiler response files contain a cycle".to_owned(),
        });
        return;
    }
    if response_visited.contains(&key) {
        return;
    }
    let metadata = match fs::metadata(&canonical) {
        Ok(metadata) => metadata,
        Err(error) => {
            issues.push(ScopeIssue {
                code: "response-unreadable",
                path: Some(canonical),
                detail: error.to_string(),
            });
            return;
        }
    };
    if metadata.len() > MAX_RESPONSE_BYTES {
        issues.push(ScopeIssue {
            code: "response-too-large",
            path: Some(canonical),
            detail: format!("response file exceeds {MAX_RESPONSE_BYTES} bytes"),
        });
        return;
    }
    let text = match fs::read_to_string(&canonical) {
        Ok(text) => text,
        Err(error) => {
            issues.push(ScopeIssue {
                code: "response-unreadable",
                path: Some(canonical),
                detail: error.to_string(),
            });
            return;
        }
    };
    response_visited.insert(key.clone());
    response_active.insert(key.clone());
    inspect_compile_tokens(
        &split_windows_command_line(&text),
        base,
        depth + 1,
        response_visited,
        response_active,
        candidates,
        issues,
    );
    response_active.remove(&key);
}

fn include_value<'a>(token: &'a str, next: Option<&'a String>) -> (Option<&'a str>, bool) {
    let lower = token.to_ascii_lowercase();
    if matches!(lower.as_str(), "/i" | "-i" | "/external:i" | "-isystem") {
        return (next.map(|value| trim_quotes(value)), next.is_some());
    }
    for prefix in ["/external:i", "/i", "-isystem", "-i"] {
        if lower.starts_with(prefix) && token.len() > prefix.len() {
            return (Some(trim_quotes(&token[prefix.len()..])), false);
        }
    }
    (None, false)
}

fn split_windows_command_line(input: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let mut token = String::new();
    let mut quoted = false;
    let mut backslashes = 0_usize;
    for character in input.chars() {
        if character == '\\' {
            backslashes += 1;
            continue;
        }
        if character == '"' {
            token.extend(std::iter::repeat_n('\\', backslashes / 2));
            if backslashes % 2 == 1 {
                token.push('"');
            } else {
                quoted = !quoted;
            }
            backslashes = 0;
            continue;
        }
        token.extend(std::iter::repeat_n('\\', backslashes));
        backslashes = 0;
        if character.is_whitespace() && !quoted {
            if !token.is_empty() {
                tokens.push(std::mem::take(&mut token));
            }
        } else {
            token.push(character);
        }
    }
    token.extend(std::iter::repeat_n('\\', backslashes));
    if !token.is_empty() {
        tokens.push(token);
    }
    tokens
}

fn minimize_roots(mut candidates: Vec<RootCandidate>) -> Vec<RootCandidate> {
    candidates.sort_by(|left, right| {
        left.path
            .components()
            .count()
            .cmp(&right.path.components().count())
            .then_with(|| left.source.priority().cmp(&right.source.priority()))
            .then_with(|| normalized_key(&left.path).cmp(&normalized_key(&right.path)))
    });
    let mut selected: Vec<RootCandidate> = Vec::new();
    for candidate in candidates {
        if selected
            .iter()
            .any(|root| candidate.path.starts_with(&root.path))
        {
            continue;
        }
        selected.push(candidate);
    }
    selected
}

fn assign_aliases(candidates: Vec<RootCandidate>, project_root: &Path) -> Vec<SourceRoot> {
    let mut used = BTreeSet::new();
    let mut serial = 1_usize;
    candidates
        .into_iter()
        .map(|candidate| {
            let base = if candidate.path == project_root {
                "project".to_owned()
            } else {
                candidate
                    .alias_hint
                    .as_deref()
                    .map(sanitize_alias)
                    .filter(|value| !value.is_empty())
                    .unwrap_or_else(|| {
                        candidate
                            .path
                            .file_name()
                            .and_then(|value| value.to_str())
                            .map(sanitize_alias)
                            .filter(|value| !value.is_empty())
                            .unwrap_or_else(|| "root".to_owned())
                    })
            };
            let mut alias = base.clone();
            while !used.insert(alias.to_ascii_lowercase()) {
                serial += 1;
                alias = format!("{base}{serial}");
            }
            SourceRoot {
                alias,
                path: candidate.path,
                source: candidate.source.as_str(),
            }
        })
        .collect()
}

fn dedupe_candidates(candidates: &mut Vec<RootCandidate>) {
    candidates.sort_by(|left, right| {
        normalized_key(&left.path)
            .cmp(&normalized_key(&right.path))
            .then_with(|| left.source.priority().cmp(&right.source.priority()))
    });
    candidates.dedup_by(|left, right| normalized_key(&left.path) == normalized_key(&right.path));
}

fn dedupe_paths(paths: &mut Vec<PathBuf>) {
    paths.sort_by_key(|path| normalized_key(path));
    paths.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
}

fn canonical_existing(path: &Path, base: &Path, role: &str) -> Result<PathBuf, String> {
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    };
    let canonical = fs::canonicalize(&path).map_err(|error| {
        format!(
            "{role} does not exist or cannot be resolved: {}: {error}",
            path.display()
        )
    })?;
    if !canonical.is_dir() && !canonical.is_file() {
        return Err(format!(
            "{role} is not a file or directory: {}",
            canonical.display()
        ));
    }
    Ok(canonical)
}

fn read_json_bounded(path: &Path, limit: u64) -> Result<Value, String> {
    let metadata = fs::metadata(path).map_err(|error| error.to_string())?;
    if metadata.len() > limit {
        return Err(format!("metadata exceeds {limit} bytes"));
    }
    let bytes = fs::read(path).map_err(|error| error.to_string())?;
    serde_json::from_slice(&bytes).map_err(|error| error.to_string())
}

fn read_directory(directory: &Path) -> Option<Vec<PathBuf>> {
    let mut paths = fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    paths.sort_by_key(|path| normalized_key(path));
    Some(paths)
}

fn resolve_metadata_path(base: &Path, raw: &str) -> PathBuf {
    let path = PathBuf::from(trim_quotes(raw));
    if path.is_absolute() {
        path
    } else {
        base.join(path)
    }
}

fn trim_quotes(value: &str) -> &str {
    value
        .trim()
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or_else(|| value.trim())
}

fn lower_extension(path: &Path) -> Option<String> {
    path.extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
}

pub(crate) fn normalized_key(path: &Path) -> String {
    slash_path(path).to_ascii_lowercase()
}

pub(crate) fn slash_path(path: &Path) -> String {
    let value = path.to_string_lossy();
    if let Some(value) = value.strip_prefix(r"\\?\UNC\") {
        return format!("//{}", value.replace('\\', "/"));
    }
    value
        .strip_prefix(r"\\?\")
        .unwrap_or(&value)
        .replace('\\', "/")
}

fn sanitize_alias(value: &str) -> String {
    let alias = value
        .chars()
        .filter_map(|character| {
            if character.is_ascii_alphanumeric() {
                Some(character.to_ascii_lowercase())
            } else if matches!(character, '-' | '_') {
                Some(character)
            } else {
                None
            }
        })
        .collect::<String>();
    alias.trim_matches(['-', '_']).to_owned()
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::{Path, PathBuf};

    use srcq_core::invocation::OutputFormat;
    use tempfile::tempdir;

    use super::{include_value, resolve, split_windows_command_line, ScopeStatus};
    use crate::{SymbolBodyMode, SymbolCommand, SymbolOperation};

    fn command() -> SymbolCommand {
        SymbolCommand {
            operation: SymbolOperation::Definition,
            name: Some("Target".to_owned()),
            at: None,
            add_roots: Vec::new(),
            only_roots: Vec::new(),
            excludes: Vec::new(),
            cwd: None,
            language: "cpp".to_owned(),
            body: SymbolBodyMode::Auto,
            output: OutputFormat::Model,
            limit: 40,
            model_token_budget: 2048,
            time_budget_ms: 7_500,
            depth: 1,
            max_nodes: 40,
            direction: "outgoing".to_owned(),
            rg_engine: None,
            ast_grep_engine: None,
        }
    }

    fn write(path: &Path, text: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("parent");
        }
        fs::write(path, text).expect("fixture");
    }

    #[test]
    fn windows_tokens_preserve_quoted_paths_and_nested_response_markers() {
        let tokens = split_windows_command_line(
            r#"cl.exe @"D:\work tree\one.rsp" /I "D:\SDK Path\include" -Irelative"#,
        );
        assert_eq!(
            tokens,
            [
                "cl.exe",
                "@D:\\work tree\\one.rsp",
                "/I",
                "D:\\SDK Path\\include",
                "-Irelative",
            ]
        );
    }

    #[test]
    fn include_flags_keep_separate_and_inline_values_distinct() {
        let next = "D:\\SDK Path\\include".to_owned();
        assert_eq!(
            include_value("/I", Some(&next)),
            (Some(next.as_str()), true)
        );
        assert_eq!(
            include_value("/external:Irelative", None),
            (Some("relative"), false)
        );
        assert_eq!(include_value("/DVALUE", None), (None, false));
    }

    #[test]
    fn source_universe_recovers_workspace_compile_file_and_nested_response_inputs() {
        let fixture = tempdir().expect("fixture");
        let project = fixture.path().join("project");
        let external = fixture.path().join("external");
        let dependency = fixture.path().join("dependency");
        fs::create_dir_all(project.join(".git")).expect("git marker");
        fs::create_dir_all(&external).expect("external");
        fs::create_dir_all(&dependency).expect("dependency");
        write(
            &project.join("src/main.cpp"),
            "int Target() { return 1; }\n",
        );
        write(
            &project.join("project.code-workspace"),
            &format!(
                r#"{{"folders":[{{"name":"project","path":"."}},{{"name":"external","path":{}}}]}}"#,
                serde_json::to_string(&external.to_string_lossy()).expect("path JSON")
            ),
        );
        write(&project.join("one.rsp"), "@nested.rsp /I src\n");
        write(
            &project.join("nested.rsp"),
            &format!("/I \"{}\"\n", dependency.display()),
        );
        let database = serde_json::json!([{
            "directory": project,
            "file": "src/main.cpp",
            "arguments": ["cl.exe", "@one.rsp", "src/main.cpp"]
        }]);
        write(
            &project.join(".vscode/compileCommands_test.json"),
            &serde_json::to_string(&database).expect("database JSON"),
        );

        let universe = resolve(&command(), &project, None).expect("source universe");
        assert_eq!(universe.status, ScopeStatus::Resolved);
        assert_eq!(universe.compile_files.len(), 1);
        assert_eq!(
            universe.compile_directories,
            [fs::canonicalize(&project).expect("canonical project")]
        );
        assert!(universe
            .roots
            .iter()
            .any(|root| root.path == fs::canonicalize(&external).expect("canonical external")));
        assert!(universe.issues.is_empty());
    }

    #[test]
    fn missing_response_file_marks_the_automatic_scope_incomplete() {
        let fixture = tempdir().expect("fixture");
        let project = fixture.path().join("project");
        fs::create_dir_all(project.join(".git")).expect("git marker");
        write(&project.join("src/main.cpp"), "int Target;\n");
        let database = serde_json::json!([{
            "directory": project,
            "file": "src/main.cpp",
            "arguments": ["cl.exe", "@missing.rsp", "src/main.cpp"]
        }]);
        write(
            &project.join(".vscode/compileCommands_test.json"),
            &serde_json::to_string(&database).expect("database JSON"),
        );

        let universe = resolve(&command(), &project, None).expect("source universe");
        assert_eq!(universe.status, ScopeStatus::Incomplete);
        assert!(universe
            .issues
            .iter()
            .any(|issue| issue.code == "response-missing"));
    }

    #[test]
    fn response_cycle_is_reported_instead_of_silently_deduplicated() {
        let fixture = tempdir().expect("fixture");
        let project = fixture.path().join("project");
        fs::create_dir_all(project.join(".git")).expect("git marker");
        write(&project.join("src/main.cpp"), "int Target;\n");
        write(&project.join("one.rsp"), "@two.rsp\n");
        write(&project.join("two.rsp"), "@one.rsp\n");
        let database = serde_json::json!([{
            "directory": project,
            "file": "src/main.cpp",
            "arguments": ["cl.exe", "@one.rsp", "src/main.cpp"]
        }]);
        write(
            &project.join(".vscode/compileCommands_test.json"),
            &serde_json::to_string(&database).expect("database JSON"),
        );

        let universe = resolve(&command(), &project, None).expect("source universe");
        assert_eq!(universe.status, ScopeStatus::Incomplete);
        assert!(universe
            .issues
            .iter()
            .any(|issue| issue.code == "response-cycle"));
    }

    #[test]
    fn only_root_is_bounded_and_does_not_consume_automatic_metadata() {
        let fixture = tempdir().expect("fixture");
        let project = fixture.path().join("project");
        let selected = fixture.path().join("selected");
        fs::create_dir_all(project.join(".git")).expect("git marker");
        fs::create_dir_all(&selected).expect("selected");
        let mut command = command();
        command.only_roots = vec![PathBuf::from(&selected)];

        let universe = resolve(&command, &project, None).expect("source universe");
        assert_eq!(universe.status, ScopeStatus::Bounded);
        assert_eq!(universe.roots.len(), 1);
        assert!(universe.compile_files.is_empty());
        assert!(universe.compile_directories.is_empty());
    }

    #[test]
    fn enclosing_workspace_scope_wins_over_a_nested_repository_for_anchored_queries() {
        let directory = tempdir().expect("temporary workspace");
        let workspace = directory.path();
        write(&workspace.join("Game.uproject"), "{}\n");
        let nested = workspace.join("Plugins/NestedPlugin");
        fs::create_dir_all(nested.join(".git")).expect("nested repository marker");
        let source = nested.join("Source/Nested/Private/File.cpp");
        write(&source, "int Target() { return 1; }\n");

        let universe = resolve(&command(), workspace, Some(&source)).expect("source universe");
        assert_eq!(
            universe.project_root,
            workspace.canonicalize().expect("canonical workspace")
        );
        assert!(universe.roots.iter().any(|root| root.source == "project"));
    }
}
