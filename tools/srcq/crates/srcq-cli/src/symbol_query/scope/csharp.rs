use std::collections::{BTreeSet, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use globset::GlobBuilder;
use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;

use super::{lower_extension, normalized_key, resolve_metadata_path, ScopeIssue};

const MAX_PROJECT_FILES: usize = 100_000;
const MAX_PROJECTS: usize = 4_096;

#[derive(Default)]
struct ProjectSpec {
    default_compile_items: bool,
    includes: Vec<String>,
    removes: Vec<String>,
    references: Vec<String>,
}

pub(super) fn discover_compile_files(
    project_root: &Path,
    anchor_file: Option<&Path>,
    compile_files: &mut Vec<PathBuf>,
    issues: &mut Vec<ScopeIssue>,
) -> bool {
    let mut projects = solution_projects(project_root, issues);
    if projects.is_empty() {
        if let Some(anchor_project) =
            anchor_file.and_then(|anchor| nearest_project(anchor, project_root, issues))
        {
            projects.push(anchor_project);
        } else {
            collect_project_files(project_root, &mut projects, issues);
            if projects.is_empty() {
                issues.push(ScopeIssue {
                    code: "csharp-project-selection-missing",
                    path: Some(project_root.to_path_buf()),
                    detail: "no C# project or solution was discovered".to_owned(),
                });
            } else if projects.len() > 1 {
                issues.push(ScopeIssue {
                    code: "csharp-project-selection-ambiguous",
                    path: Some(project_root.to_path_buf()),
                    detail: format!(
                        "{} C# projects were discovered without a solution or anchor",
                        projects.len()
                    ),
                });
            }
        }
    }
    let scope_resolved = !projects.is_empty();
    let mut pending = VecDeque::from(projects);
    let mut visited = BTreeSet::new();
    while let Some(project) = pending.pop_front() {
        let project = match fs::canonicalize(&project) {
            Ok(project) if project.is_file() => project,
            _ => {
                issues.push(ScopeIssue {
                    code: "csharp-project-missing",
                    path: Some(project),
                    detail: "C# project does not exist or cannot be resolved".to_owned(),
                });
                continue;
            }
        };
        if !visited.insert(normalized_key(&project)) {
            continue;
        }
        if visited.len() > MAX_PROJECTS {
            issues.push(ScopeIssue {
                code: "csharp-project-limit",
                path: Some(project_root.to_path_buf()),
                detail: format!("C# project graph exceeded {MAX_PROJECTS} projects"),
            });
            break;
        }
        inspect_directory_build_inputs(&project, issues);
        let spec = match parse_project(&project, issues) {
            Some(spec) => spec,
            None => continue,
        };
        let Some(project_directory) = project.parent() else {
            continue;
        };
        let mut project_files = Vec::new();
        let needs_project_candidates =
            spec.default_compile_items || spec.includes.iter().any(|include| has_wildcard(include));
        let mut project_candidates = Vec::new();
        if needs_project_candidates {
            collect_default_compile_files(project_directory, &mut project_candidates, issues);
        }
        if spec.default_compile_items {
            project_files.extend(project_candidates.iter().cloned());
        }
        for include in &spec.includes {
            expand_include(
                project_directory,
                include,
                &project_candidates,
                &mut project_files,
                issues,
            );
        }
        let supported_removes = spec
            .removes
            .iter()
            .filter(|pattern| remove_pattern_supported(project_directory, pattern, issues))
            .collect::<Vec<_>>();
        project_files.retain(|path| {
            !supported_removes
                .iter()
                .any(|pattern| item_matches(path, project_directory, pattern, issues))
        });
        project_files.sort_by_key(|path| normalized_key(path));
        project_files.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
        let remaining = MAX_PROJECT_FILES.saturating_sub(compile_files.len());
        if project_files.len() > remaining {
            compile_files.extend(project_files.into_iter().take(remaining));
            issues.push(ScopeIssue {
                code: "csharp-scan-limit",
                path: Some(project_root.to_path_buf()),
                detail: format!(
                    "C# compile graph exceeded the global limit of {MAX_PROJECT_FILES} files"
                ),
            });
            break;
        }
        compile_files.extend(project_files);
        for reference in spec.references {
            if contains_msbuild_property(&reference) {
                issues.push(ScopeIssue {
                    code: "csharp-project-reference-unresolved",
                    path: Some(project.clone()),
                    detail: format!("ProjectReference uses an unresolved property: {reference}"),
                });
                continue;
            }
            pending.push_back(resolve_metadata_path(project_directory, &reference));
        }
    }
    scope_resolved
}

fn solution_projects(project_root: &Path, issues: &mut Vec<ScopeIssue>) -> Vec<PathBuf> {
    let mut projects = Vec::new();
    let Some(entries) = read_directory_checked(project_root, issues, "C# solution discovery")
    else {
        return projects;
    };
    for solution in entries
        .iter()
        .filter(|path| lower_extension(path).as_deref() == Some("slnx"))
    {
        issues.push(ScopeIssue {
            code: "csharp-solution-format-unresolved",
            path: Some(solution.clone()),
            detail: ".slnx is not statically parsed".to_owned(),
        });
    }
    let solutions = entries
        .into_iter()
        .filter(|path| lower_extension(path).as_deref() == Some("sln"))
        .collect::<Vec<_>>();
    if solutions.len() > 1 {
        issues.push(ScopeIssue {
            code: "csharp-solution-selection-ambiguous",
            path: Some(project_root.to_path_buf()),
            detail: format!("{} solution files were discovered", solutions.len()),
        });
    }
    for solution in solutions {
        let text = match read_bounded_utf8(&solution) {
            Ok(text) => text,
            Err(detail) => {
                issues.push(ScopeIssue {
                    code: "csharp-solution-unreadable",
                    path: Some(solution),
                    detail,
                });
                continue;
            }
        };
        let base = solution.parent().unwrap_or(project_root);
        let initial_count = projects.len();
        for line in text.lines() {
            let Some(raw) = line
                .split('"')
                .find(|part| part.trim().to_ascii_lowercase().ends_with(".csproj"))
            else {
                continue;
            };
            projects.push(resolve_metadata_path(base, raw.trim()));
        }
        if projects.len() == initial_count {
            issues.push(ScopeIssue {
                code: "csharp-solution-projects-unresolved",
                path: Some(solution),
                detail: "solution contains no statically recognizable C# project entries"
                    .to_owned(),
            });
        }
    }
    projects.sort_by_key(|path| normalized_key(path));
    projects.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    projects
}

fn nearest_project(
    anchor: &Path,
    project_root: &Path,
    issues: &mut Vec<ScopeIssue>,
) -> Option<PathBuf> {
    let start = anchor.parent().unwrap_or(anchor);
    for directory in start.ancestors() {
        let mut projects =
            read_directory_checked(directory, issues, "C# anchored project discovery")?
                .into_iter()
                .filter(|path| path.is_file() && lower_extension(path).as_deref() == Some("csproj"))
                .collect::<Vec<_>>();
        projects.sort_by_key(|path| normalized_key(path));
        if projects.len() > 1 {
            issues.push(ScopeIssue {
                code: "csharp-project-selection-ambiguous",
                path: Some(directory.to_path_buf()),
                detail: format!(
                    "{} C# projects contain the anchored source directory",
                    projects.len()
                ),
            });
        }
        if let Some(project) = projects.into_iter().next() {
            return Some(project);
        }
        if directory == project_root {
            break;
        }
    }
    None
}

fn collect_project_files(root: &Path, projects: &mut Vec<PathBuf>, issues: &mut Vec<ScopeIssue>) {
    collect_files(
        root,
        Some("csproj"),
        projects,
        issues,
        "C# project discovery",
    );
}

fn parse_project(project: &Path, issues: &mut Vec<ScopeIssue>) -> Option<ProjectSpec> {
    let text = match read_bounded_utf8(project) {
        Ok(text) => text,
        Err(detail) => {
            issues.push(ScopeIssue {
                code: "csharp-project-unreadable",
                path: Some(project.to_path_buf()),
                detail,
            });
            return None;
        }
    };
    let mut reader = Reader::from_str(&text);
    reader.config_mut().trim_text(true);
    let mut buffer = Vec::new();
    let mut conditional_stack = Vec::new();
    let mut conditional_depth = 0_usize;
    let mut sdk_style = false;
    let mut includes = Vec::new();
    let mut removes = Vec::new();
    let mut references = Vec::new();
    let mut conditional_properties = BTreeSet::new();
    let mut import_reported = false;
    loop {
        match reader.read_event_into(&mut buffer) {
            Ok(Event::Start(element)) => {
                let own_condition = match xml_attribute(&reader, &element, b"Condition") {
                    Ok(condition) => condition.is_some(),
                    Err(error) => {
                        report_project_xml_error(project, error, issues);
                        return None;
                    }
                };
                conditional_stack.push(own_condition);
                if own_condition {
                    conditional_depth += 1;
                }
                if let Err(error) = inspect_project_element(
                    &reader,
                    &element,
                    conditional_depth > 0,
                    project,
                    &mut sdk_style,
                    &mut includes,
                    &mut removes,
                    &mut references,
                    &mut conditional_properties,
                    &mut import_reported,
                    issues,
                ) {
                    report_project_xml_error(project, error, issues);
                    return None;
                }
            }
            Ok(Event::Empty(element)) => {
                let own_condition = match xml_attribute(&reader, &element, b"Condition") {
                    Ok(condition) => condition.is_some(),
                    Err(error) => {
                        report_project_xml_error(project, error, issues);
                        return None;
                    }
                };
                let conditional = conditional_depth > 0 || own_condition;
                if let Err(error) = inspect_project_element(
                    &reader,
                    &element,
                    conditional,
                    project,
                    &mut sdk_style,
                    &mut includes,
                    &mut removes,
                    &mut references,
                    &mut conditional_properties,
                    &mut import_reported,
                    issues,
                ) {
                    report_project_xml_error(project, error, issues);
                    return None;
                }
            }
            Ok(Event::End(_)) => {
                if conditional_stack.pop().unwrap_or(false) {
                    conditional_depth = conditional_depth.saturating_sub(1);
                }
            }
            Ok(Event::Eof) => break,
            Ok(_) => {}
            Err(error) => {
                issues.push(ScopeIssue {
                    code: "csharp-project-invalid",
                    path: Some(project.to_path_buf()),
                    detail: error.to_string(),
                });
                return None;
            }
        }
        buffer.clear();
    }
    let mut default_compile_items = sdk_style;
    for property in ["EnableDefaultItems", "EnableDefaultCompileItems"] {
        let values = property_values(&text, property);
        if values.len() > 1 {
            issues.push(ScopeIssue {
                code: "csharp-property-unresolved",
                path: Some(project.to_path_buf()),
                detail: format!("{property} is assigned more than once"),
            });
        }
        if let Some(value) = values.last() {
            if conditional_properties.contains(&property.to_ascii_lowercase()) {
                issues.push(ScopeIssue {
                    code: "csharp-property-condition-unresolved",
                    path: Some(project.to_path_buf()),
                    detail: format!("{property} is conditional"),
                });
            } else if value.eq_ignore_ascii_case("false") {
                default_compile_items = false;
            } else if !value.eq_ignore_ascii_case("true") {
                issues.push(ScopeIssue {
                    code: "csharp-property-unresolved",
                    path: Some(project.to_path_buf()),
                    detail: format!("{property} has unsupported value {value:?}"),
                });
            }
        }
    }
    for property in [
        "DefaultItemExcludes",
        "DefaultItemExcludesInProjectFolder",
        "DefaultExcludesInProjectFolder",
    ] {
        let values = property_values(&text, property);
        if values.len() > 1 {
            issues.push(ScopeIssue {
                code: "csharp-property-unresolved",
                path: Some(project.to_path_buf()),
                detail: format!("{property} is assigned more than once"),
            });
        }
        if let Some(value) = values.last() {
            if conditional_properties.contains(&property.to_ascii_lowercase()) {
                issues.push(ScopeIssue {
                    code: "csharp-property-condition-unresolved",
                    path: Some(project.to_path_buf()),
                    detail: format!("{property} is conditional"),
                });
            } else if contains_msbuild_property(value) {
                issues.push(ScopeIssue {
                    code: "csharp-property-unresolved",
                    path: Some(project.to_path_buf()),
                    detail: format!("{property} contains an unresolved property"),
                });
            } else {
                removes.extend(split_items(value));
            }
        }
    }
    Some(ProjectSpec {
        default_compile_items,
        includes,
        removes,
        references,
    })
}

#[allow(clippy::too_many_arguments)]
fn inspect_project_element(
    reader: &Reader<&[u8]>,
    element: &BytesStart<'_>,
    conditional: bool,
    project: &Path,
    sdk_style: &mut bool,
    includes: &mut Vec<String>,
    removes: &mut Vec<String>,
    references: &mut Vec<String>,
    conditional_properties: &mut BTreeSet<String>,
    import_reported: &mut bool,
    issues: &mut Vec<ScopeIssue>,
) -> Result<(), String> {
    let qualified_name = element.name();
    let name = local_xml_name(qualified_name.as_ref());
    if name.eq_ignore_ascii_case(b"Project") {
        if let Some(sdk) = xml_attribute(reader, element, b"Sdk")? {
            register_sdk(&sdk, project, sdk_style, issues);
        }
    }
    if name.eq_ignore_ascii_case(b"Sdk") {
        if let Some(sdk) = xml_attribute(reader, element, b"Name")? {
            register_sdk(&sdk, project, sdk_style, issues);
        } else {
            *sdk_style = true;
            issues.push(ScopeIssue {
                code: "csharp-sdk-unresolved",
                path: Some(project.to_path_buf()),
                detail: "MSBuild Sdk element has no static Name".to_owned(),
            });
        }
    }
    if name.eq_ignore_ascii_case(b"Import") && !*import_reported {
        issues.push(ScopeIssue {
            code: "csharp-project-import-unresolved",
            path: Some(project.to_path_buf()),
            detail: "explicit MSBuild imports are not evaluated".to_owned(),
        });
        *import_reported = true;
    }
    if matches_ascii_case(
        name,
        &[
            b"EnableDefaultItems",
            b"EnableDefaultCompileItems",
            b"DefaultItemExcludes",
            b"DefaultItemExcludesInProjectFolder",
            b"DefaultExcludesInProjectFolder",
        ],
    ) && conditional
    {
        conditional_properties.insert(String::from_utf8_lossy(name).to_ascii_lowercase());
    }
    if matches_ascii_case(
        name,
        &[
            b"BaseOutputPath",
            b"BaseIntermediateOutputPath",
            b"OutputPath",
            b"IntermediateOutputPath",
            b"MSBuildProjectExtensionsPath",
            b"ArtifactsPath",
            b"UseArtifactsOutput",
            b"PublishDir",
        ],
    ) {
        issues.push(ScopeIssue {
            code: "csharp-property-unresolved",
            path: Some(project.to_path_buf()),
            detail: format!(
                "{} can change the SDK default Compile exclusions",
                String::from_utf8_lossy(name)
            ),
        });
    }
    if name.eq_ignore_ascii_case(b"Compile") {
        if let Some(include) = xml_attribute(reader, element, b"Include")? {
            includes.extend(split_items(&include));
            if conditional {
                report_conditional_item(project, "Compile Include", issues);
            }
        }
        if let Some(remove) = xml_attribute(reader, element, b"Remove")? {
            if conditional {
                report_conditional_item(project, "Compile Remove", issues);
            } else {
                removes.extend(split_items(&remove));
            }
        }
        if xml_attribute(reader, element, b"Exclude")?.is_some() {
            issues.push(ScopeIssue {
                code: "csharp-compile-exclude-unresolved",
                path: Some(project.to_path_buf()),
                detail: "Compile Exclude is not statically evaluated".to_owned(),
            });
        }
    }
    if name.eq_ignore_ascii_case(b"ProjectReference") {
        if let Some(include) = xml_attribute(reader, element, b"Include")? {
            references.extend(split_items(&include));
            if conditional {
                report_conditional_item(project, "ProjectReference", issues);
            }
        }
    }
    Ok(())
}

fn report_project_xml_error(project: &Path, error: String, issues: &mut Vec<ScopeIssue>) {
    issues.push(ScopeIssue {
        code: "csharp-project-invalid",
        path: Some(project.to_path_buf()),
        detail: error,
    });
}

fn report_conditional_item(project: &Path, item: &str, issues: &mut Vec<ScopeIssue>) {
    issues.push(ScopeIssue {
        code: "csharp-item-condition-unresolved",
        path: Some(project.to_path_buf()),
        detail: format!("conditional {item} is included only as a conservative candidate"),
    });
}

fn xml_attribute(
    reader: &Reader<&[u8]>,
    element: &BytesStart<'_>,
    wanted: &[u8],
) -> Result<Option<String>, String> {
    for attribute in element.attributes().with_checks(false) {
        let attribute = attribute.map_err(|error| error.to_string())?;
        if local_xml_name(attribute.key.as_ref()).eq_ignore_ascii_case(wanted) {
            return attribute
                .decoded_and_normalized_value(quick_xml::XmlVersion::Implicit1_0, reader.decoder())
                .map(|value| Some(value.into_owned()))
                .map_err(|error| error.to_string());
        }
    }
    Ok(None)
}

fn local_xml_name(name: &[u8]) -> &[u8] {
    name.rsplit(|byte| *byte == b':').next().unwrap_or(name)
}

fn matches_ascii_case(value: &[u8], candidates: &[&[u8]]) -> bool {
    candidates
        .iter()
        .any(|candidate| value.eq_ignore_ascii_case(candidate))
}

fn property_values(text: &str, property: &str) -> Vec<String> {
    let lowercase = text.to_ascii_lowercase();
    let open = format!("<{}", property.to_ascii_lowercase());
    let close = format!("</{}>", property.to_ascii_lowercase());
    let mut values = Vec::new();
    let mut offset = 0_usize;
    while let Some(relative_start) = lowercase[offset..].find(&open) {
        let open_start = offset + relative_start;
        let boundary = lowercase.as_bytes().get(open_start + open.len()).copied();
        if !boundary.is_some_and(|byte| byte == b'>' || byte.is_ascii_whitespace()) {
            offset = open_start + open.len();
            continue;
        }
        let Some(relative_value_start) = lowercase[open_start..].find('>') else {
            break;
        };
        let value_start = open_start + relative_value_start + 1;
        let Some(relative_value_end) = lowercase[value_start..].find(&close) else {
            break;
        };
        let value_end = value_start + relative_value_end;
        values.push(text[value_start..value_end].trim().to_owned());
        offset = value_end + close.len();
    }
    values
}

fn inspect_directory_build_inputs(project: &Path, issues: &mut Vec<ScopeIssue>) {
    let Some(project_directory) = project.parent() else {
        return;
    };
    for directory in project_directory.ancestors() {
        for name in ["Directory.Build.props", "Directory.Build.targets"] {
            let input = directory.join(name);
            if input.is_file() {
                issues.push(ScopeIssue {
                    code: "csharp-directory-build-unresolved",
                    path: Some(input),
                    detail: "Directory.Build input is not evaluated".to_owned(),
                });
            }
        }
    }
}

fn collect_default_compile_files(
    project_directory: &Path,
    files: &mut Vec<PathBuf>,
    issues: &mut Vec<ScopeIssue>,
) {
    collect_files(
        project_directory,
        Some("cs"),
        files,
        issues,
        "C# default compile discovery",
    );
}

fn collect_files(
    root: &Path,
    extension: Option<&str>,
    files: &mut Vec<PathBuf>,
    issues: &mut Vec<ScopeIssue>,
    role: &str,
) {
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        let entries = match fs::read_dir(&directory) {
            Ok(entries) => entries,
            Err(error) => {
                issues.push(ScopeIssue {
                    code: "csharp-directory-unreadable",
                    path: Some(directory),
                    detail: format!("{role}: {error}"),
                });
                continue;
            }
        };
        for entry in entries {
            let entry = match entry {
                Ok(entry) => entry,
                Err(error) => {
                    issues.push(ScopeIssue {
                        code: "csharp-directory-entry-unreadable",
                        path: Some(directory.clone()),
                        detail: format!("{role}: {error}"),
                    });
                    continue;
                }
            };
            let path = entry.path();
            let file_type = match entry.file_type() {
                Ok(file_type) => file_type,
                Err(error) => {
                    issues.push(ScopeIssue {
                        code: "csharp-file-type-unreadable",
                        path: Some(path),
                        detail: format!("{role}: {error}"),
                    });
                    continue;
                }
            };
            if file_type.is_dir() {
                let direct_default_output = path.parent() == Some(root)
                    && path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .is_some_and(|name| {
                            matches!(name.to_ascii_lowercase().as_str(), "bin" | "obj")
                        });
                let skipped = path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name.starts_with('.'))
                    || direct_default_output;
                if !skipped && !file_type.is_symlink() {
                    pending.push(path);
                }
                continue;
            }
            if !file_type.is_file()
                || extension
                    .is_some_and(|expected| lower_extension(&path).as_deref() != Some(expected))
            {
                continue;
            }
            if files.len() >= MAX_PROJECT_FILES {
                issues.push(ScopeIssue {
                    code: "csharp-scan-limit",
                    path: Some(root.to_path_buf()),
                    detail: format!("{role} exceeded {MAX_PROJECT_FILES} files"),
                });
                return;
            }
            files.push(fs::canonicalize(&path).unwrap_or(path));
        }
    }
}

fn expand_include(
    project_directory: &Path,
    raw: &str,
    project_candidates: &[PathBuf],
    files: &mut Vec<PathBuf>,
    issues: &mut Vec<ScopeIssue>,
) {
    if contains_msbuild_property(raw) {
        issues.push(ScopeIssue {
            code: "csharp-compile-include-unresolved",
            path: Some(project_directory.to_path_buf()),
            detail: format!("Compile Include uses an unresolved property: {raw}"),
        });
        return;
    }
    if has_wildcard(raw) {
        let normalized = raw.replace('\\', "/");
        if normalized.split('/').any(|part| part == "..") {
            issues.push(ScopeIssue {
                code: "csharp-compile-include-unresolved",
                path: Some(project_directory.to_path_buf()),
                detail: format!("external wildcard Compile Include is not expanded: {raw}"),
            });
            return;
        }
        files.extend(
            project_candidates
                .iter()
                .filter(|path| item_matches(path, project_directory, raw, issues))
                .cloned(),
        );
        return;
    }
    let path = resolve_metadata_path(project_directory, raw);
    match fs::canonicalize(&path) {
        Ok(path) if path.is_file() => files.push(path),
        _ => issues.push(ScopeIssue {
            code: "csharp-compile-item-missing",
            path: Some(path),
            detail: "Compile Include does not resolve to an existing file".to_owned(),
        }),
    }
}

fn item_matches(
    path: &Path,
    project_directory: &Path,
    raw: &str,
    issues: &mut Vec<ScopeIssue>,
) -> bool {
    if contains_msbuild_property(raw) {
        issues.push(ScopeIssue {
            code: "csharp-compile-remove-unresolved",
            path: Some(project_directory.to_path_buf()),
            detail: format!("Compile Remove uses an unresolved property: {raw}"),
        });
        return false;
    }
    if !has_wildcard(raw) {
        let expected = resolve_metadata_path(project_directory, raw);
        let expected = fs::canonicalize(&expected).unwrap_or(expected);
        return normalized_key(path) == normalized_key(&expected);
    }
    let Ok(relative) = path.strip_prefix(project_directory) else {
        return false;
    };
    let pattern = raw.replace('\\', "/");
    let matcher = match GlobBuilder::new(&pattern)
        .case_insensitive(true)
        .literal_separator(true)
        .build()
    {
        Ok(glob) => glob.compile_matcher(),
        Err(error) => {
            issues.push(ScopeIssue {
                code: "csharp-item-pattern-invalid",
                path: Some(project_directory.to_path_buf()),
                detail: format!("invalid MSBuild item pattern {raw:?}: {error}"),
            });
            return false;
        }
    };
    matcher.is_match(relative.to_string_lossy().replace('\\', "/"))
}

fn remove_pattern_supported(
    project_directory: &Path,
    raw: &str,
    issues: &mut Vec<ScopeIssue>,
) -> bool {
    if contains_msbuild_property(raw) {
        issues.push(ScopeIssue {
            code: "csharp-compile-remove-unresolved",
            path: Some(project_directory.to_path_buf()),
            detail: format!("Compile Remove uses an unresolved property: {raw}"),
        });
        return false;
    }
    let normalized = raw.replace('\\', "/");
    if has_wildcard(raw) && normalized.split('/').any(|part| part == "..") {
        issues.push(ScopeIssue {
            code: "csharp-compile-remove-unresolved",
            path: Some(project_directory.to_path_buf()),
            detail: format!("external wildcard Compile Remove is not expanded: {raw}"),
        });
        return false;
    }
    true
}

fn read_directory_checked(
    directory: &Path,
    issues: &mut Vec<ScopeIssue>,
    role: &str,
) -> Option<Vec<PathBuf>> {
    let entries = match fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(error) => {
            issues.push(ScopeIssue {
                code: "csharp-directory-unreadable",
                path: Some(directory.to_path_buf()),
                detail: format!("{role}: {error}"),
            });
            return None;
        }
    };
    let mut paths = Vec::new();
    for entry in entries {
        match entry {
            Ok(entry) => paths.push(entry.path()),
            Err(error) => issues.push(ScopeIssue {
                code: "csharp-directory-entry-unreadable",
                path: Some(directory.to_path_buf()),
                detail: format!("{role}: {error}"),
            }),
        }
    }
    paths.sort_by_key(|path| normalized_key(path));
    Some(paths)
}

fn register_sdk(raw: &str, project: &Path, sdk_style: &mut bool, issues: &mut Vec<ScopeIssue>) {
    *sdk_style = true;
    let sdks = raw
        .split(';')
        .map(str::trim)
        .filter(|sdk| !sdk.is_empty())
        .collect::<Vec<_>>();
    if sdks.is_empty() {
        issues.push(ScopeIssue {
            code: "csharp-sdk-unresolved",
            path: Some(project.to_path_buf()),
            detail: "MSBuild Sdk identity is empty".to_owned(),
        });
    }
    for sdk in sdks {
        let name = sdk.split('/').next().unwrap_or(sdk);
        let name = name.to_ascii_lowercase();
        if name != "microsoft.net.sdk" && !name.starts_with("microsoft.net.sdk.") {
            issues.push(ScopeIssue {
                code: "csharp-sdk-unresolved",
                path: Some(project.to_path_buf()),
                detail: format!("SDK {sdk:?} is not a statically supported .NET SDK"),
            });
        }
    }
}

fn split_items(value: &str) -> Vec<String> {
    value
        .split(';')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn contains_msbuild_property(value: &str) -> bool {
    value.contains("$(") || value.contains("@(") || value.contains("%(")
}

fn has_wildcard(value: &str) -> bool {
    value.contains('*') || value.contains('?') || value.contains('[')
}

fn read_bounded_utf8(path: &Path) -> Result<String, String> {
    let metadata = fs::metadata(path).map_err(|error| error.to_string())?;
    if metadata.len() > super::MAX_METADATA_BYTES {
        return Err(format!(
            "metadata exceeds {} bytes",
            super::MAX_METADATA_BYTES
        ));
    }
    fs::read_to_string(path).map_err(|error| error.to_string())
}
