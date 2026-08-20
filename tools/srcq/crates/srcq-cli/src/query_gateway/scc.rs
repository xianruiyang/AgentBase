use std::cmp::Reverse;

use serde_json::{json, Map, Value};
use srcq_core::invocation::OutputFormat;

use crate::GatewayCommand;

use super::{
    model_page_end, model_representation_key, model_text_cost, render_path_inline_annotations,
    DIRECT_COMPLETE_MAX_UNITS,
};

#[derive(Clone, Debug)]
struct LanguageMetric {
    name: String,
    bytes: u64,
    code_bytes: u64,
    lines: u64,
    code: u64,
    comments: u64,
    blanks: u64,
    complexity: u64,
    files: u64,
    weighted_complexity: u64,
    uloc: u64,
    line_length: Option<Value>,
    file_metrics: Vec<FileMetric>,
}

#[derive(Clone, Debug)]
struct FileMetric {
    path: String,
    language: String,
    possible_languages: Vec<String>,
    bytes: u64,
    lines: u64,
    code: u64,
    comments: u64,
    blanks: u64,
    complexity: u64,
    weighted_complexity: u64,
    uloc: u64,
    generated: bool,
    minified: bool,
    binary: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct Totals {
    languages: u64,
    files: u64,
    bytes: u64,
    code_bytes: u64,
    lines: u64,
    code: u64,
    comments: u64,
    blanks: u64,
    complexity: u64,
    weighted_complexity: u64,
    uloc: u64,
}

#[derive(Debug)]
pub(super) struct SccProjection {
    pub(super) value: Value,
    pub(super) model: String,
    pub(super) displayed: usize,
    pub(super) total: usize,
    pub(super) view: String,
    pub(super) display_complete: bool,
}

pub(super) fn render(
    command: &GatewayCommand,
    by_file: bool,
    stdout: &[u8],
    native_exit: i32,
    offset: usize,
) -> Result<SccProjection, String> {
    if stdout.is_empty() && native_exit != 0 {
        return Ok(SccProjection {
            value: json!({"languages":[]}),
            model: String::new(),
            displayed: 0,
            total: 0,
            view: if by_file { "files" } else { "languages" }.to_owned(),
            display_complete: true,
        });
    }
    let native: Value = serde_json::from_slice(stdout)
        .map_err(|error| format!("scc did not return valid JSON: {error}"))?;
    let languages = parse_languages(&native)?;
    let totals = totals(&languages);

    if command.view == "lossless" {
        if offset != 0 {
            return Err("lossless view does not accept a cursor".to_owned());
        }
        return Ok(SccProjection {
            value: json!({"native":native}),
            model: String::new(),
            displayed: 1,
            total: 1,
            view: "lossless".to_owned(),
            display_complete: true,
        });
    }

    let selected = match command.view.as_str() {
        "auto" if languages.is_empty() => "summary",
        "auto" if by_file => "files",
        "auto" => "languages",
        other => other,
    };
    match selected {
        "summary" => render_summary(totals, offset),
        "languages" => render_languages(command, &languages, totals, offset),
        "files" if by_file => render_files(command, &languages, totals, offset, false),
        "hotspots" if by_file => render_files(command, &languages, totals, offset, true),
        "files" | "hotspots" => Err(format!(
            "{selected} view requires the native --by-file option"
        )),
        other => Err(format!("unsupported scc projection view {other:?}")),
    }
}

fn parse_languages(native: &Value) -> Result<Vec<LanguageMetric>, String> {
    let records = native.as_array().or_else(|| {
        native
            .as_object()
            .and_then(|root| field(root, &["languageSummary", "LanguageSummary"]))
            .and_then(Value::as_array)
    });
    let records = records
        .ok_or_else(|| "scc JSON must be an array or contain a languageSummary array".to_owned())?;
    records
        .iter()
        .enumerate()
        .map(|(index, record)| parse_language(record, index))
        .collect()
}

fn parse_language(record: &Value, index: usize) -> Result<LanguageMetric, String> {
    let object = record
        .as_object()
        .ok_or_else(|| format!("scc language record {index} is not an object"))?;
    let files = field(object, &["Files", "files"])
        .and_then(Value::as_array)
        .map(|records| {
            records
                .iter()
                .enumerate()
                .map(|(file_index, record)| parse_file(record, index, file_index))
                .collect::<Result<Vec<_>, _>>()
        })
        .transpose()?
        .unwrap_or_default();
    Ok(LanguageMetric {
        name: required_string(object, &["Name", "name"], "language name", index)?,
        bytes: required_u64(object, &["Bytes", "bytes"], "Bytes", index)?,
        code_bytes: optional_u64(object, &["CodeBytes", "codeBytes", "code_bytes"]),
        lines: required_u64(object, &["Lines", "lines"], "Lines", index)?,
        code: required_u64(object, &["Code", "code"], "Code", index)?,
        comments: required_u64(
            object,
            &["Comment", "comment", "comments"],
            "Comment",
            index,
        )?,
        blanks: required_u64(object, &["Blank", "blank", "blanks"], "Blank", index)?,
        complexity: required_u64(object, &["Complexity", "complexity"], "Complexity", index)?,
        files: required_u64(object, &["Count", "count", "files"], "Count", index)?,
        weighted_complexity: optional_u64(
            object,
            &[
                "WeightedComplexity",
                "weightedComplexity",
                "weighted_complexity",
            ],
        ),
        uloc: optional_u64(object, &["ULOC", "Uloc", "uloc"]),
        line_length: field(object, &["LineLength", "lineLength", "line_length"])
            .filter(|value| !value.is_null())
            .cloned(),
        file_metrics: files,
    })
}

fn parse_file(
    record: &Value,
    language_index: usize,
    file_index: usize,
) -> Result<FileMetric, String> {
    let object = record
        .as_object()
        .ok_or_else(|| format!("scc file record {language_index}:{file_index} is not an object"))?;
    let identity = language_index
        .saturating_mul(1_000_000)
        .saturating_add(file_index);
    let path = required_string(
        object,
        &["Location", "location", "path"],
        "Location",
        identity,
    )?
    .replace('\\', "/");
    Ok(FileMetric {
        path,
        language: required_string(object, &["Language", "language"], "Language", identity)?,
        possible_languages: field(
            object,
            &[
                "PossibleLanguages",
                "possibleLanguages",
                "possible_languages",
            ],
        )
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(ToOwned::to_owned)
                .collect()
        })
        .unwrap_or_default(),
        bytes: required_u64(object, &["Bytes", "bytes"], "Bytes", identity)?,
        lines: required_u64(object, &["Lines", "lines"], "Lines", identity)?,
        code: required_u64(object, &["Code", "code"], "Code", identity)?,
        comments: required_u64(
            object,
            &["Comment", "comment", "comments"],
            "Comment",
            identity,
        )?,
        blanks: required_u64(object, &["Blank", "blank", "blanks"], "Blank", identity)?,
        complexity: required_u64(
            object,
            &["Complexity", "complexity"],
            "Complexity",
            identity,
        )?,
        weighted_complexity: optional_u64(
            object,
            &[
                "WeightedComplexity",
                "weightedComplexity",
                "weighted_complexity",
            ],
        ),
        uloc: optional_u64(object, &["ULOC", "Uloc", "uloc"]),
        generated: optional_bool(object, &["Generated", "generated"]),
        minified: optional_bool(object, &["Minified", "minified"]),
        binary: optional_bool(object, &["Binary", "binary"]),
    })
}

fn field<'a>(object: &'a Map<String, Value>, names: &[&str]) -> Option<&'a Value> {
    names.iter().find_map(|name| object.get(*name))
}

fn required_string(
    object: &Map<String, Value>,
    names: &[&str],
    label: &str,
    index: usize,
) -> Result<String, String> {
    field(object, names)
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .ok_or_else(|| format!("scc record {index} is missing string field {label}"))
}

fn required_u64(
    object: &Map<String, Value>,
    names: &[&str],
    label: &str,
    index: usize,
) -> Result<u64, String> {
    field(object, names)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("scc record {index} is missing integer field {label}"))
}

fn optional_u64(object: &Map<String, Value>, names: &[&str]) -> u64 {
    field(object, names).and_then(Value::as_u64).unwrap_or(0)
}

fn optional_bool(object: &Map<String, Value>, names: &[&str]) -> bool {
    field(object, names)
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn totals(languages: &[LanguageMetric]) -> Totals {
    languages.iter().fold(
        Totals {
            languages: languages.len() as u64,
            ..Totals::default()
        },
        |mut total, language| {
            total.files = total.files.saturating_add(language.files);
            total.bytes = total.bytes.saturating_add(language.bytes);
            total.code_bytes = total.code_bytes.saturating_add(language.code_bytes);
            total.lines = total.lines.saturating_add(language.lines);
            total.code = total.code.saturating_add(language.code);
            total.comments = total.comments.saturating_add(language.comments);
            total.blanks = total.blanks.saturating_add(language.blanks);
            total.complexity = total.complexity.saturating_add(language.complexity);
            total.weighted_complexity = total
                .weighted_complexity
                .saturating_add(language.weighted_complexity);
            total.uloc = total.uloc.saturating_add(language.uloc);
            total
        },
    )
}

fn totals_value(total: Totals) -> Value {
    json!({
        "languages":total.languages,
        "files":total.files,
        "bytes":total.bytes,
        "code_bytes":total.code_bytes,
        "lines":total.lines,
        "code":total.code,
        "comments":total.comments,
        "blanks":total.blanks,
        "complexity":total.complexity,
        "weighted_complexity":total.weighted_complexity,
        "uloc":total.uloc
    })
}

fn total_model(total: Totals) -> String {
    format!(
        "total languages={} files={} lines={} code={} comments={} blanks={} complexity={} bytes={}",
        total.languages,
        total.files,
        total.lines,
        total.code,
        total.comments,
        total.blanks,
        total.complexity,
        total.bytes
    )
}

fn render_summary(total: Totals, offset: usize) -> Result<SccProjection, String> {
    if offset != 0 {
        return Err("summary view does not accept a cursor".to_owned());
    }
    Ok(SccProjection {
        value: json!({"summary":totals_value(total)}),
        model: total_model(total),
        displayed: 1,
        total: 1,
        view: "summary".to_owned(),
        display_complete: true,
    })
}

fn render_languages(
    command: &GatewayCommand,
    languages: &[LanguageMetric],
    total: Totals,
    offset: usize,
) -> Result<SccProjection, String> {
    if offset > languages.len() {
        return Err("cursor offset exceeds the scc language result set".to_owned());
    }
    let effective_limit = complete_limit(command, languages.len(), |end| {
        languages_model(&languages[..end], total, 0)
    });
    let maximum_end = languages.len().min(offset.saturating_add(effective_limit));
    let end = page_end(command, offset, maximum_end, |candidate| {
        languages_model(&languages[offset..candidate], total, offset)
    });
    let page = &languages[offset..end];
    Ok(SccProjection {
        value: json!({
            "summary":totals_value(total),
            "languages":page.iter().map(language_value).collect::<Vec<_>>()
        }),
        model: languages_model(page, total, offset),
        displayed: page.len(),
        total: languages.len(),
        view: "languages".to_owned(),
        display_complete: end >= languages.len(),
    })
}

fn render_files(
    command: &GatewayCommand,
    languages: &[LanguageMetric],
    total: Totals,
    offset: usize,
    hotspots: bool,
) -> Result<SccProjection, String> {
    let mut files = languages
        .iter()
        .flat_map(|language| language.file_metrics.iter().cloned())
        .collect::<Vec<_>>();
    if hotspots {
        files.sort_by_key(|file| {
            (
                Reverse(file.complexity),
                Reverse(file.code),
                Reverse(file.bytes),
                file.path.to_lowercase(),
                file.path.clone(),
                file.language.clone(),
            )
        });
    } else {
        files.sort_by_key(|file| {
            (
                file.path.to_lowercase(),
                file.path.clone(),
                file.language.clone(),
            )
        });
    }
    if offset > files.len() {
        return Err("cursor offset exceeds the scc file result set".to_owned());
    }
    let view = if hotspots { "hotspots" } else { "files" };
    let effective_limit = complete_limit(command, files.len(), |end| {
        files_model(&files[..end], hotspots)
    });
    let maximum_end = files.len().min(offset.saturating_add(effective_limit));
    let end = page_end(command, offset, maximum_end, |candidate| {
        files_model(&files[offset..candidate], hotspots)
    });
    let page = &files[offset..end];
    let mut value = Map::new();
    value.insert("summary".to_owned(), totals_value(total));
    value.insert(
        view.to_owned(),
        Value::Array(page.iter().map(file_value).collect()),
    );
    Ok(SccProjection {
        value: Value::Object(value),
        model: files_model(page, hotspots),
        displayed: page.len(),
        total: files.len(),
        view: view.to_owned(),
        display_complete: end >= files.len(),
    })
}

fn complete_limit(
    command: &GatewayCommand,
    total: usize,
    render: impl FnOnce(usize) -> String,
) -> usize {
    if command.auto_complete
        && command.output == OutputFormat::Model
        && command.view == "auto"
        && total > command.limit
        && total <= DIRECT_COMPLETE_MAX_UNITS
        && model_text_cost(&render(total)) <= command.model_token_budget
    {
        total
    } else {
        command.limit
    }
}

fn page_end(
    command: &GatewayCommand,
    offset: usize,
    maximum_end: usize,
    render: impl Fn(usize) -> String,
) -> usize {
    if command.output == OutputFormat::Model && command.view != "lossless" {
        model_page_end(offset, maximum_end, command.model_token_budget, |end| {
            model_text_cost(&render(end))
        })
    } else {
        maximum_end
    }
}

fn language_value(language: &LanguageMetric) -> Value {
    let mut value = json!({
        "name":language.name,
        "files":language.files,
        "bytes":language.bytes,
        "code_bytes":language.code_bytes,
        "lines":language.lines,
        "code":language.code,
        "comments":language.comments,
        "blanks":language.blanks,
        "complexity":language.complexity,
        "weighted_complexity":language.weighted_complexity,
        "uloc":language.uloc
    });
    if let Some(line_length) = &language.line_length {
        value["line_length"] = line_length.clone();
    }
    value
}

fn file_value(file: &FileMetric) -> Value {
    json!({
        "path":file.path,
        "language":file.language,
        "possible_languages":file.possible_languages,
        "bytes":file.bytes,
        "lines":file.lines,
        "code":file.code,
        "comments":file.comments,
        "blanks":file.blanks,
        "complexity":file.complexity,
        "weighted_complexity":file.weighted_complexity,
        "uloc":file.uloc,
        "generated":file.generated,
        "minified":file.minified,
        "binary":file.binary
    })
}

fn languages_model(languages: &[LanguageMetric], total: Totals, offset: usize) -> String {
    let mut lines = Vec::new();
    if offset == 0 && total.languages > 1 {
        lines.push(total_model(total));
    }
    lines.extend(languages.iter().map(|language| {
        format!(
            "{} files={} lines={} code={} comments={} blanks={} complexity={} bytes={}",
            model_atom(&language.name),
            language.files,
            language.lines,
            language.code,
            language.comments,
            language.blanks,
            language.complexity,
            language.bytes
        )
    }));
    lines.join("\n")
}

fn files_model(files: &[FileMetric], hotspots: bool) -> String {
    if files.is_empty() {
        return String::new();
    }
    if hotspots {
        return hotspots_model(files);
    }
    // Every candidate grows monotonically across a stable path prefix, and an invalid tree cannot
    // become valid later. The shared binary budget search can therefore maximize the same evidence
    // prefix even when the selected representation changes.
    let mut best = files_labeled_model(files);
    for candidate in [files_table_model(files), files_tree_table_model(files)]
        .into_iter()
        .flatten()
    {
        if model_representation_key(&candidate) < model_representation_key(&best) {
            best = candidate;
        }
    }
    best
}

fn hotspots_model(files: &[FileMetric]) -> String {
    files
        .iter()
        .map(|file| {
            format!(
                "{} complexity={} code={} lines={} language={} bytes={}",
                model_atom(&file.path),
                file.complexity,
                file.code,
                file.lines,
                model_atom(&file.language),
                file.bytes
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn files_labeled_model(files: &[FileMetric]) -> String {
    files
        .iter()
        .map(|file| {
            format!(
                "{} language={} lines={} code={} comments={} blanks={} complexity={} bytes={}",
                model_atom(&file.path),
                model_atom(&file.language),
                file.lines,
                file.code,
                file.comments,
                file.blanks,
                file.complexity,
                file.bytes
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

const FILE_TABLE_COLUMNS: &str = "language\tlines\tcode\tcomments\tblanks\tcomplexity\tbytes";

fn file_table_values(file: &FileMetric) -> String {
    format!(
        "{}\t{}\t{}\t{}\t{}\t{}\t{}",
        model_atom(&file.language),
        file.lines,
        file.code,
        file.comments,
        file.blanks,
        file.complexity,
        file.bytes
    )
}

fn files_table_model(files: &[FileMetric]) -> Option<String> {
    (!files.is_empty()).then(|| {
        let rows = files
            .iter()
            .map(|file| format!("{}\t{}", model_atom(&file.path), file_table_values(file)))
            .collect::<Vec<_>>()
            .join("\n");
        format!("path\t{FILE_TABLE_COLUMNS}\n{rows}")
    })
}

fn files_tree_table_model(files: &[FileMetric]) -> Option<String> {
    let entries = files
        .iter()
        .map(|file| (file.path.clone(), vec![file_table_values(file)]))
        .collect::<Vec<_>>();
    render_path_inline_annotations(&entries)
        .map(|tree| format!("path(tree)\t{FILE_TABLE_COLUMNS}\n{tree}"))
}

fn model_atom(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
        .replace('\t', "\\t")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{GatewayBackend, GatewayOperation};

    fn command(view: &str) -> GatewayCommand {
        GatewayCommand {
            backend: GatewayBackend::Scc,
            operation: GatewayOperation::Exec,
            engine: None,
            cwd: None,
            view: view.to_owned(),
            limit: 1,
            max_text_chars: 240,
            model_token_budget: 2048,
            auto_complete: false,
            output: OutputFormat::Model,
            receipt: "auto".to_owned(),
            artifact_out: None,
            snapshot: None,
            after: None,
            native_argv: Vec::new(),
        }
    }

    fn fixture() -> Vec<u8> {
        serde_json::to_vec(&json!([{
            "Name":"Rust","Bytes":100,"CodeBytes":0,"Lines":10,"Code":8,
            "Comment":1,"Blank":1,"Complexity":3,"Count":2,
            "WeightedComplexity":0,"ULOC":0,"LineLength":null,
            "Files":[
                {"Language":"Rust","PossibleLanguages":["Rust"],"Location":"src\\a.rs",
                 "Bytes":60,"Lines":6,"Code":5,"Comment":0,"Blank":1,"Complexity":2,
                 "WeightedComplexity":0,"Uloc":0,"Generated":false,"Minified":false,"Binary":false},
                {"Language":"Rust","PossibleLanguages":["Rust"],"Location":"src\\b.rs",
                 "Bytes":40,"Lines":4,"Code":3,"Comment":1,"Blank":0,"Complexity":1,
                 "WeightedComplexity":0,"Uloc":0,"Generated":false,"Minified":false,"Binary":false}
            ]
        }]))
        .expect("fixture JSON")
    }

    fn file_metric(path: impl Into<String>, index: u64) -> FileMetric {
        FileMetric {
            path: path.into(),
            language: "Rust".to_owned(),
            possible_languages: vec!["Rust".to_owned()],
            bytes: 100 + index,
            lines: 10 + index,
            code: 8 + index,
            comments: 1,
            blanks: 1,
            complexity: 2 + index,
            weighted_complexity: 0,
            uloc: 0,
            generated: false,
            minified: false,
            binary: false,
        }
    }

    #[test]
    fn summary_omits_cost_estimates_and_keeps_exact_totals() {
        let projection = render(&command("summary"), true, &fixture(), 0, 0).expect("summary");
        assert_eq!(projection.value["summary"]["files"], 2);
        assert_eq!(projection.value["summary"]["code"], 8);
        assert!(!projection.model.contains("cost"));
        assert!(!projection.model.contains("COCOMO"));
    }

    #[test]
    fn file_pages_preserve_paths_and_hotspots_have_stable_order() {
        let first = render(&command("files"), true, &fixture(), 0, 0).expect("files");
        assert_eq!(first.total, 2);
        assert_eq!(first.displayed, 1);
        assert_eq!(first.value["files"][0]["path"], "src/a.rs");
        let hotspot = render(&command("hotspots"), true, &fixture(), 0, 0).expect("hotspot");
        assert_eq!(hotspot.value["hotspots"][0]["path"], "src/a.rs");
    }

    #[test]
    fn first_partial_language_page_keeps_the_global_summary() {
        let data = serde_json::to_vec(&json!([
            {"Name":"Rust","Bytes":10,"Lines":2,"Code":2,"Comment":0,
             "Blank":0,"Complexity":1,"Count":1},
            {"Name":"Python","Bytes":8,"Lines":2,"Code":1,"Comment":0,
             "Blank":1,"Complexity":0,"Count":1}
        ]))
        .expect("language page JSON");
        let projection = render(&command("languages"), false, &data, 0, 0).expect("languages");
        assert_eq!(projection.displayed, 1);
        assert!(projection.model.starts_with("total languages=2 files=2"));
    }

    #[test]
    fn future_lowercase_schema_and_json2_root_are_accepted() {
        let data = serde_json::to_vec(&json!({"languageSummary":[{
            "name":"Text","bytes":4,"lines":1,"code":1,"comments":0,
            "blanks":0,"complexity":0,"count":1,"files":[]
        }]}))
        .expect("json2");
        let projection = render(&command("languages"), false, &data, 0, 0).expect("languages");
        assert_eq!(projection.value["languages"][0]["name"], "Text");
    }

    #[test]
    fn files_are_sorted_by_normalized_path_before_paging() {
        let data = serde_json::to_vec(&json!([{
            "Name":"Rust","Bytes":2,"Lines":2,"Code":2,"Comment":0,
            "Blank":0,"Complexity":2,"Count":2,
            "Files":[
                {"Language":"Rust","Location":"src\\z.rs","Bytes":1,"Lines":1,
                 "Code":1,"Comment":0,"Blank":0,"Complexity":1},
                {"Language":"Rust","Location":"src\\A.rs","Bytes":1,"Lines":1,
                 "Code":1,"Comment":0,"Blank":0,"Complexity":1}
            ]
        }]))
        .expect("file order JSON");
        let projection = render(&command("files"), true, &data, 0, 0).expect("files");
        assert_eq!(projection.value["files"][0]["path"], "src/A.rs");
    }

    #[test]
    fn files_model_selects_the_tree_table_for_shared_directories() {
        let files = (0..12)
            .map(|index| {
                file_metric(
                    format!("src/query_gateway/backends/scc/file-{index:02}.rs"),
                    index,
                )
            })
            .collect::<Vec<_>>();
        let model = files_model(&files, false);
        assert!(model.starts_with(&format!("path(tree)\t{FILE_TABLE_COLUMNS}\n")));
        assert_eq!(model.matches("src/query_gateway/backends/scc").count(), 1);
        assert_eq!(
            model.lines().filter(|line| line.contains(".rs\t")).count(),
            files.len()
        );
        assert!(!model.contains("language="));
        assert!(
            model_representation_key(&model)
                < model_representation_key(&files_labeled_model(&files))
        );
    }

    #[test]
    fn files_model_uses_a_flat_fallback_when_a_tree_is_not_reversible() {
        let singleton = vec![file_metric("README.md", 0)];
        let singleton_model = files_model(&singleton, false);
        assert!(!singleton_model.starts_with("path(tree)"));
        assert!(singleton_model.contains("README.md"));

        let duplicate = vec![file_metric("src/a.rs", 0), file_metric("src/a.rs", 1)];
        assert!(!files_model(&duplicate, false).starts_with("path(tree)"));

        let prefix = vec![file_metric("src/a", 0), file_metric("src/a/b.rs", 1)];
        assert!(!files_model(&prefix, false).starts_with("path(tree)"));
    }

    #[test]
    fn hotspots_keep_the_ranked_flat_format() {
        let files = vec![
            file_metric("src/deep/a.rs", 0),
            file_metric("src/deep/b.rs", 1),
        ];
        let model = files_model(&files, true);
        assert_eq!(
            model,
            "src/deep/a.rs complexity=2 code=8 lines=10 language=Rust bytes=100\n\
             src/deep/b.rs complexity=3 code=9 lines=11 language=Rust bytes=101"
        );
        assert!(!model.contains("path(tree)"));
    }

    #[test]
    fn adaptive_file_model_cost_is_monotonic_across_sorted_prefixes() {
        let files = (0..128)
            .map(|index| {
                file_metric(
                    format!("src/module-{:02}/nested/file-{index:03}.rs", index / 8),
                    index,
                )
            })
            .collect::<Vec<_>>();
        let mut costs = Vec::new();
        let mut previous = 0;
        for end in 1..=files.len() {
            let cost = model_text_cost(&files_model(&files[..end], false));
            assert!(cost >= previous, "model cost decreased at prefix {end}");
            costs.push(cost);
            previous = cost;
        }
        let budgets = costs
            .iter()
            .flat_map(|cost| [cost.saturating_sub(1), *cost])
            .collect::<Vec<_>>();
        for budget in budgets {
            let expected = costs
                .iter()
                .rposition(|cost| *cost <= budget)
                .map(|index| index + 1)
                .unwrap_or(1);
            let actual = model_page_end(0, files.len(), budget, |end| costs[end - 1]);
            assert_eq!(actual, expected, "wrong page end for budget {budget}");
        }
    }

    #[test]
    fn lossless_keeps_native_estimates_but_normalized_views_do_not() {
        let native = json!({"languageSummary":[{
            "Name":"Text","Bytes":4,"Lines":1,"Code":1,"Comment":0,
            "Blank":0,"Complexity":0,"Count":1
        }],"estimatedCost":123.5});
        let data = serde_json::to_vec(&native).expect("lossless JSON");
        let normalized =
            render(&command("languages"), false, &data, 0, 0).expect("normalized languages");
        assert!(normalized.value.get("estimatedCost").is_none());
        let lossless = render(&command("lossless"), false, &data, 0, 0).expect("lossless");
        assert_eq!(lossless.value["native"]["estimatedCost"], 123.5);
    }

    #[test]
    fn malformed_metrics_and_invalid_cursors_fail_locally() {
        let missing = serde_json::to_vec(&json!([{
            "Name":"Rust","Bytes":1,"Lines":1,"Code":1,"Comment":0,
            "Blank":0,"Count":1
        }]))
        .expect("malformed JSON");
        assert!(render(&command("languages"), false, &missing, 0, 0)
            .expect_err("missing complexity")
            .contains("Complexity"));
        assert!(render(&command("summary"), true, &fixture(), 0, 1)
            .expect_err("summary cursor")
            .contains("does not accept a cursor"));
        assert!(render(&command("files"), false, &fixture(), 0, 0)
            .expect_err("files without by-file")
            .contains("requires the native --by-file option"));
    }
}
