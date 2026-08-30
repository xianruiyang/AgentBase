use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::scope::{normalized_key, SourceUniverse};

pub(crate) fn inline_rules(target: &str, include_scopes: bool) -> String {
    let target = target.rsplit("::").next().unwrap_or(target);
    let regex = regex_escape(target).replace('\'', "''");
    let candidates = [
        ("srcq.cpp.function", "function_definition", "declarator"),
        ("srcq.cpp.class", "class_specifier", "name"),
        ("srcq.cpp.struct", "struct_specifier", "name"),
        ("srcq.cpp.union", "union_specifier", "name"),
        ("srcq.cpp.enum", "enum_specifier", "name"),
        ("srcq.cpp.alias", "alias_declaration", "name"),
        ("srcq.cpp.typedef", "type_definition", "declarator"),
        ("srcq.cpp.declaration", "declaration", "declarator"),
        ("srcq.cpp.field", "field_declaration", "declarator"),
        ("srcq.cpp.parameter", "parameter_declaration", "declarator"),
        ("srcq.cpp.enumerator", "enumerator", "name"),
        ("srcq.cpp.namespace", "namespace_definition", "name"),
    ];
    let mut rules = candidates
        .into_iter()
        .map(|(id, kind, field)| {
            let field = if id == "srcq.cpp.field" {
                String::new()
            } else {
                format!("        field: {field}\n")
            };
            format!(
                "id: {id}\nlanguage: Cpp\nrule:\n  all:\n    - kind: {kind}\n    - has:\n        stopBy: end\n{field}        regex: '^{regex}$'\nseverity: info\nmessage: source definition candidate"
            )
        })
        .collect::<Vec<_>>();
    if include_scopes {
        rules.extend([
            ("srcq.cpp.scope.function", "function_definition"),
            ("srcq.cpp.scope.class", "class_specifier"),
            ("srcq.cpp.scope.struct", "struct_specifier"),
            ("srcq.cpp.scope.union", "union_specifier"),
            ("srcq.cpp.scope.enum", "enum_specifier"),
            ("srcq.cpp.scope.namespace", "namespace_definition"),
        ].into_iter().map(|(id, kind)| {
        format!(
            "id: {id}\nlanguage: Cpp\nrule:\n  all:\n    - kind: {kind}\n    - has:\n        stopBy: end\n        regex: '^{regex}$'\nseverity: info\nmessage: lexical scope candidate"
        )
        }));
    }
    rules.join("\n---\n")
}

fn regex_escape(value: &str) -> String {
    let mut escaped = String::new();
    for character in value.chars() {
        if matches!(
            character,
            '\\' | '.' | '^' | '$' | '|' | '?' | '*' | '+' | '(' | ')' | '[' | ']' | '{' | '}'
        ) {
            escaped.push('\\');
        }
        escaped.push(character);
    }
    escaped
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub(crate) enum DefinitionRole {
    Definition,
    Declaration,
}

impl DefinitionRole {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Definition => "definition",
            Self::Declaration => "declaration",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct SourcePosition {
    pub(crate) line: usize,
    pub(crate) column: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct SourceRange {
    pub(crate) start: SourcePosition,
    pub(crate) end: SourcePosition,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct DefinitionCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) name_position: SourcePosition,
    pub(crate) qualified_name: String,
    pub(crate) symbol_kind: String,
    pub(crate) role: DefinitionRole,
    pub(crate) signature: String,
    pub(crate) text: String,
    pub(crate) ast_kind: String,
    pub(crate) root_alias: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OccurrenceCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) root_alias: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct DirectCallCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) callee: String,
    pub(crate) dispatch: &'static str,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct FunctionOwnerCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) name: String,
    pub(crate) signature: String,
}

#[derive(Clone, Debug)]
struct AstRecord {
    file: PathBuf,
    range: SourceRange,
    text: String,
    rule_id: String,
}

#[derive(Clone, Debug)]
struct ScopeNode {
    file_key: String,
    range: SourceRange,
    name: String,
    kind: ScopeKind,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ScopeKind {
    Namespace,
    Type,
    Function,
}

#[derive(Clone, Debug)]
struct ExtractedName {
    name: String,
    offset: usize,
    symbol_kind: &'static str,
    role: DefinitionRole,
    signature: String,
    ast_kind: &'static str,
}

pub(crate) fn parse_scan_stream(
    bytes: &[u8],
    cwd: &Path,
    target: &str,
    universe: &SourceUniverse,
) -> Result<Vec<DefinitionCandidate>, String> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep definition output was not UTF-8".to_owned())?;
    let mut records = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep definition JSON at record {}: {error}",
                index + 1
            )
        })?;
        records.push(parse_record(&value, cwd)?);
    }
    let scopes = build_scopes(&records);
    let target_last = target.rsplit("::").next().unwrap_or(target);
    let mut candidates = Vec::new();
    for record in &records {
        let Some(extracted) = extract_target(record, target_last) else {
            continue;
        };
        if record.rule_id == "srcq.cpp.namespace" {
            continue;
        }
        let qualified_name = qualify(record, &extracted.name, &scopes);
        if target.contains("::")
            && qualified_name != target
            && !qualified_name.ends_with(&format!("::{target}"))
        {
            continue;
        }
        if !target.contains("::") && qualified_name.rsplit("::").next() != Some(target_last) {
            continue;
        }
        let file = fs::canonicalize(&record.file).unwrap_or_else(|_| record.file.clone());
        let name_position = offset_position(record.range.start, &record.text, extracted.offset);
        candidates.push(DefinitionCandidate {
            root_alias: universe.root_for(&file).map(|root| root.alias.clone()),
            file,
            range: record.range,
            name_position,
            qualified_name,
            symbol_kind: extracted.symbol_kind.to_owned(),
            role: extracted.role,
            signature: extracted.signature,
            text: record.text.clone(),
            ast_kind: extracted.ast_kind.to_owned(),
        });
    }
    candidates.sort_by(|left, right| {
        left.role
            .cmp(&right.role)
            .then_with(|| normalized_key(&left.file).cmp(&normalized_key(&right.file)))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
            .then_with(|| left.qualified_name.cmp(&right.qualified_name))
    });
    let mut seen = BTreeSet::new();
    candidates.retain(|candidate| {
        seen.insert(format!(
            "{}:{}:{}:{}:{}",
            normalized_key(&candidate.file),
            candidate.range.start.line,
            candidate.range.start.column,
            candidate.role.as_str(),
            candidate.qualified_name
        ))
    });
    Ok(candidates)
}

pub(crate) fn parse_header_declarator_stream(
    bytes: &[u8],
    file: &Path,
    target: &str,
    universe: &SourceUniverse,
) -> Result<Vec<DefinitionCandidate>, String> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep header output was not UTF-8".to_owned())?;
    let target_last = target.rsplit("::").next().unwrap_or(target);
    let file = fs::canonicalize(file).unwrap_or_else(|_| file.to_path_buf());
    let mut candidates = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep C++ header JSON at record {}: {error}",
                index + 1
            )
        })?;
        let declarator = value
            .get("text")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep header record is missing text".to_owned())?;
        let Some(open) = declarator.find('(') else {
            continue;
        };
        let head = declarator[..open].trim_end();
        let start = qualified_start(head, head.len());
        let name = head[start..].trim();
        if name.rsplit("::").next() != Some(target_last) {
            continue;
        }
        let qualified_name = if target.contains("::") {
            target.to_owned()
        } else {
            name.to_owned()
        };
        let range = value
            .get("range")
            .ok_or_else(|| "ast-grep header record is missing range".to_owned())?;
        let range = SourceRange {
            start: parse_position(
                range
                    .get("start")
                    .ok_or_else(|| "ast-grep header range is missing start".to_owned())?,
            )?,
            end: parse_position(
                range
                    .get("end")
                    .ok_or_else(|| "ast-grep header range is missing end".to_owned())?,
            )?,
        };
        let signature = value
            .get("lines")
            .and_then(Value::as_str)
            .map(compact_signature)
            .unwrap_or_else(|| compact_signature(declarator));
        candidates.push(DefinitionCandidate {
            root_alias: universe.root_for(&file).map(|root| root.alias.clone()),
            file: file.clone(),
            range,
            name_position: offset_position(range.start, declarator, start),
            qualified_name,
            symbol_kind: "method".to_owned(),
            role: DefinitionRole::Declaration,
            signature,
            text: declarator.to_owned(),
            ast_kind: "function_declarator".to_owned(),
        });
    }
    Ok(candidates)
}

pub(crate) fn occurrence_rules(target: &str) -> String {
    let target = target.rsplit("::").next().unwrap_or(target);
    let regex = regex_escape(target).replace('\'', "''");
    format!(
        "id: srcq.cpp.occurrence\nlanguage: Cpp\nrule:\n  all:\n    - any:\n        - kind: identifier\n        - kind: field_identifier\n        - kind: type_identifier\n        - kind: namespace_identifier\n    - regex: '^{regex}$'\nseverity: info\nmessage: source occurrence candidate"
    )
}

pub(crate) fn parse_occurrence_stream(
    bytes: &[u8],
    cwd: &Path,
    universe: &SourceUniverse,
) -> Result<Vec<OccurrenceCandidate>, String> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep occurrence output was not UTF-8".to_owned())?;
    let mut occurrences = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep occurrence JSON at record {}: {error}",
                index + 1
            )
        })?;
        let record = parse_record(&value, cwd)?;
        let file = fs::canonicalize(&record.file).unwrap_or(record.file);
        occurrences.push(OccurrenceCandidate {
            root_alias: universe.root_for(&file).map(|root| root.alias.clone()),
            file,
            range: record.range,
        });
    }
    occurrences.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    occurrences.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.range.start == right.range.start
            && left.range.end == right.range.end
    });
    Ok(occurrences)
}

pub(crate) fn call_rules() -> &'static str {
    "id: srcq.cpp.call\nlanguage: Cpp\nrule:\n  kind: call_expression\nseverity: info\nmessage: direct call candidate"
}

pub(crate) fn parse_call_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<DirectCallCandidate>, String> {
    let text =
        std::str::from_utf8(bytes).map_err(|_| "ast-grep call output was not UTF-8".to_owned())?;
    let mut calls = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep call JSON at record {}: {error}",
                index + 1
            )
        })?;
        let record = parse_record(&value, cwd)?;
        let (callee, dispatch) = call_name(&record.text);
        calls.push(DirectCallCandidate {
            file: fs::canonicalize(&record.file).unwrap_or(record.file),
            range: record.range,
            callee,
            dispatch,
        });
    }
    calls.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    calls.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.range.start == right.range.start
    });
    Ok(calls)
}

pub(crate) fn containing_function_rules(target: &str) -> String {
    let target = target.rsplit("::").next().unwrap_or(target);
    let regex = regex_escape(target).replace('\'', "''");
    format!(
        "id: srcq.cpp.containing-function\nlanguage: Cpp\nrule:\n  all:\n    - kind: function_definition\n    - has:\n        stopBy: end\n        regex: '^{regex}$'\nseverity: info\nmessage: containing function candidate"
    )
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep containing-function output was not UTF-8".to_owned())?;
    let mut owners = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep containing-function JSON at record {}: {error}",
                index + 1
            )
        })?;
        let record = parse_record(&value, cwd)?;
        let Some((name, _)) = any_function_name(&record.text) else {
            continue;
        };
        owners.push(FunctionOwnerCandidate {
            file: fs::canonicalize(&record.file).unwrap_or(record.file),
            range: record.range,
            name,
            signature: compact_signature(function_header(&record.text)),
        });
    }
    owners.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    owners.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file) && left.range == right.range
    });
    Ok(owners)
}

fn call_name(text: &str) -> (String, &'static str) {
    let mut angle_depth = 0_usize;
    let mut open = None;
    for (offset, character) in text.char_indices() {
        match character {
            '<' => angle_depth += 1,
            '>' => angle_depth = angle_depth.saturating_sub(1),
            '(' if angle_depth == 0 => {
                open = Some(offset);
                break;
            }
            _ => {}
        }
    }
    let Some(open) = open else {
        return ("<indirect>".to_owned(), "unknown");
    };
    let mut callee = text[..open].trim();
    if let Some(template) = callee.find('<') {
        callee = callee[..template].trim_end();
    }
    if let Some((_, method)) = callee.rsplit_once("->") {
        return (method.trim().to_owned(), "member-candidate");
    }
    if let Some((_, method)) = callee.rsplit_once('.') {
        return (method.trim().to_owned(), "member-candidate");
    }
    if callee.is_empty()
        || callee
            .chars()
            .any(|character| matches!(character, '(' | ')' | '[' | ']'))
        || !callee.chars().any(is_identifier_character)
    {
        return ("<indirect>".to_owned(), "unknown");
    }
    (callee.to_owned(), "direct-candidate")
}

fn parse_record(value: &Value, cwd: &Path) -> Result<AstRecord, String> {
    let raw_file = value
        .get("file")
        .and_then(Value::as_str)
        .ok_or_else(|| "ast-grep record is missing file".to_owned())?;
    let file = PathBuf::from(raw_file);
    let file = if file.is_absolute() {
        file
    } else {
        cwd.join(file)
    };
    let range = value
        .get("range")
        .ok_or_else(|| "ast-grep record is missing range".to_owned())?;
    Ok(AstRecord {
        file,
        range: SourceRange {
            start: parse_position(
                range
                    .get("start")
                    .ok_or_else(|| "ast-grep range is missing start".to_owned())?,
            )?,
            end: parse_position(
                range
                    .get("end")
                    .ok_or_else(|| "ast-grep range is missing end".to_owned())?,
            )?,
        },
        text: value
            .get("text")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep record is missing text".to_owned())?
            .to_owned(),
        rule_id: value
            .get("ruleId")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep record is missing ruleId".to_owned())?
            .to_owned(),
    })
}

fn parse_position(value: &Value) -> Result<SourcePosition, String> {
    let line = value
        .get("line")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| "ast-grep position has invalid line".to_owned())?;
    let column = value
        .get("column")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| "ast-grep position has invalid column".to_owned())?;
    Ok(SourcePosition { line, column })
}

fn build_scopes(records: &[AstRecord]) -> Vec<ScopeNode> {
    records
        .iter()
        .filter_map(|record| {
            let (name, kind) = match record.rule_id.as_str() {
                "srcq.cpp.namespace" | "srcq.cpp.scope.namespace" => {
                    (namespace_name(&record.text), ScopeKind::Namespace)
                }
                "srcq.cpp.class" | "srcq.cpp.scope.class" => {
                    (keyword_name(&record.text, &["class"]), ScopeKind::Type)
                }
                "srcq.cpp.struct" | "srcq.cpp.scope.struct" => {
                    (keyword_name(&record.text, &["struct"]), ScopeKind::Type)
                }
                "srcq.cpp.union" | "srcq.cpp.scope.union" => {
                    (keyword_name(&record.text, &["union"]), ScopeKind::Type)
                }
                "srcq.cpp.enum" | "srcq.cpp.scope.enum" => (
                    keyword_name(&record.text, &["enum", "class"])
                        .or_else(|| keyword_name(&record.text, &["enum", "struct"]))
                        .or_else(|| keyword_name(&record.text, &["enum"])),
                    ScopeKind::Type,
                ),
                "srcq.cpp.function" | "srcq.cpp.scope.function" => {
                    (any_function_name(&record.text), ScopeKind::Function)
                }
                _ => return None,
            };
            name.map(|(name, _)| ScopeNode {
                file_key: normalized_key(&record.file),
                range: record.range,
                name,
                kind,
            })
        })
        .collect()
}

fn extract_target(record: &AstRecord, target: &str) -> Option<ExtractedName> {
    match record.rule_id.as_str() {
        "srcq.cpp.function" => function_name(&record.text, target),
        "srcq.cpp.class" => type_name(&record.text, target, "class", "class_specifier"),
        "srcq.cpp.struct" => type_name(&record.text, target, "struct", "struct_specifier"),
        "srcq.cpp.union" => type_name(&record.text, target, "union", "union_specifier"),
        "srcq.cpp.enum" => enum_name(&record.text, target),
        "srcq.cpp.alias" => alias_name(&record.text, target),
        "srcq.cpp.typedef" => declarator_name(
            &record.text,
            target,
            "type",
            DefinitionRole::Definition,
            "type_definition",
        ),
        "srcq.cpp.declaration" => declaration_name(&record.text, target, "declaration"),
        "srcq.cpp.field" => field_name(&record.text, target),
        "srcq.cpp.parameter" => declarator_name(
            &record.text,
            target,
            "parameter",
            DefinitionRole::Definition,
            "parameter_declaration",
        ),
        "srcq.cpp.enumerator" => enumerator_name(&record.text, target),
        "srcq.cpp.namespace" => {
            type_name(&record.text, target, "namespace", "namespace_definition")
        }
        _ => None,
    }
}

fn function_name(text: &str, target: &str) -> Option<ExtractedName> {
    let header = function_header(text);
    for offset in exact_occurrences(header, target) {
        let after = skip_whitespace(header, offset + target.len());
        let after = skip_template_arguments(header, after)?;
        if header.as_bytes().get(after) != Some(&b'(') {
            continue;
        }
        let start = qualified_start(header, offset);
        let name = header[start..offset + target.len()].trim().to_owned();
        return Some(ExtractedName {
            name,
            offset,
            symbol_kind: if header[start..offset].contains("::") {
                "method"
            } else {
                "function"
            },
            role: DefinitionRole::Definition,
            signature: compact_signature(header),
            ast_kind: "function_definition",
        });
    }
    None
}

fn type_name(
    text: &str,
    target: &str,
    keyword: &str,
    ast_kind: &'static str,
) -> Option<ExtractedName> {
    let (name, offset) = keyword_name(text, &[keyword])?;
    (name == target).then(|| ExtractedName {
        name,
        offset,
        symbol_kind: if keyword == "namespace" {
            "namespace"
        } else {
            "type"
        },
        role: DefinitionRole::Definition,
        signature: compact_signature(first_header(text)),
        ast_kind,
    })
}

fn enum_name(text: &str, target: &str) -> Option<ExtractedName> {
    let (name, offset) = keyword_name(text, &["enum", "class"])
        .or_else(|| keyword_name(text, &["enum", "struct"]))
        .or_else(|| keyword_name(text, &["enum"]))?;
    (name == target).then(|| ExtractedName {
        name,
        offset,
        symbol_kind: "type",
        role: DefinitionRole::Definition,
        signature: compact_signature(first_header(text)),
        ast_kind: "enum_specifier",
    })
}

fn alias_name(text: &str, target: &str) -> Option<ExtractedName> {
    let (name, offset) = keyword_name(text, &["using"])?;
    (name == target).then(|| ExtractedName {
        name,
        offset,
        symbol_kind: "type",
        role: DefinitionRole::Definition,
        signature: compact_signature(text),
        ast_kind: "alias_declaration",
    })
}

fn declaration_name(text: &str, target: &str, ast_kind: &'static str) -> Option<ExtractedName> {
    for offset in exact_occurrences(text, target) {
        if !looks_like_declarator(text, offset, target.len()) {
            continue;
        }
        let after = skip_whitespace(text, offset + target.len());
        let role = if text.as_bytes().get(after) == Some(&b'(')
            || text.trim_start().starts_with("extern ")
        {
            DefinitionRole::Declaration
        } else {
            DefinitionRole::Definition
        };
        return Some(ExtractedName {
            name: target.to_owned(),
            offset,
            symbol_kind: if role == DefinitionRole::Declaration
                && text.as_bytes().get(after) == Some(&b'(')
            {
                "function"
            } else {
                "variable"
            },
            role,
            signature: compact_signature(text),
            ast_kind,
        });
    }
    None
}

fn field_name(text: &str, target: &str) -> Option<ExtractedName> {
    for offset in exact_occurrences(text, target) {
        if !looks_like_declarator(text, offset, target.len()) {
            continue;
        }
        let after = skip_whitespace(text, offset + target.len());
        let method = text.as_bytes().get(after) == Some(&b'(');
        return Some(ExtractedName {
            name: target.to_owned(),
            offset,
            symbol_kind: if method { "method" } else { "field" },
            role: if method {
                DefinitionRole::Declaration
            } else {
                DefinitionRole::Definition
            },
            signature: compact_signature(text),
            ast_kind: "field_declaration",
        });
    }
    None
}

fn declarator_name(
    text: &str,
    target: &str,
    symbol_kind: &'static str,
    role: DefinitionRole,
    ast_kind: &'static str,
) -> Option<ExtractedName> {
    for offset in exact_occurrences(text, target) {
        if looks_like_declarator(text, offset, target.len()) {
            return Some(ExtractedName {
                name: target.to_owned(),
                offset,
                symbol_kind,
                role,
                signature: compact_signature(text),
                ast_kind,
            });
        }
    }
    None
}

fn enumerator_name(text: &str, target: &str) -> Option<ExtractedName> {
    let offset = exact_occurrences(text, target).into_iter().next()?;
    (text[..offset].trim().is_empty()).then(|| ExtractedName {
        name: target.to_owned(),
        offset,
        symbol_kind: "enumerator",
        role: DefinitionRole::Definition,
        signature: compact_signature(text),
        ast_kind: "enumerator",
    })
}

fn qualify(record: &AstRecord, extracted: &str, scopes: &[ScopeNode]) -> String {
    let file_key = normalized_key(&record.file);
    let mut containing = scopes
        .iter()
        .filter(|scope| {
            scope.file_key == file_key
                && scope.range != record.range
                && contains(scope.range, record.range)
        })
        .collect::<Vec<_>>();
    containing.sort_by(|left, right| {
        left.range
            .start
            .line
            .cmp(&right.range.start.line)
            .then_with(|| right.range.end.line.cmp(&left.range.end.line))
    });
    let mut parts = Vec::new();
    for scope in containing {
        if extracted.contains("::") && scope.kind == ScopeKind::Type {
            continue;
        }
        if parts.last() != Some(&scope.name) {
            parts.push(scope.name.clone());
        }
    }
    if extracted.contains("::") {
        if parts.is_empty() {
            extracted.to_owned()
        } else {
            format!("{}::{extracted}", parts.join("::"))
        }
    } else if parts.is_empty() {
        extracted.to_owned()
    } else {
        parts.push(extracted.to_owned());
        parts.join("::")
    }
}

fn contains(outer: SourceRange, inner: SourceRange) -> bool {
    position_le(outer.start, inner.start) && position_le(inner.end, outer.end)
}

fn position_le(left: SourcePosition, right: SourcePosition) -> bool {
    (left.line, left.column) <= (right.line, right.column)
}

fn any_function_name(text: &str) -> Option<(String, usize)> {
    let header = function_header(text);
    for (offset, character) in header.char_indices() {
        if character != '(' {
            continue;
        }
        let end = header[..offset].trim_end().len();
        if end == 0 {
            continue;
        }
        let start = qualified_start(header, end);
        let name = header[start..end].trim();
        if !name.is_empty() && name.chars().any(is_identifier_character) {
            return Some((name.to_owned(), start));
        }
    }
    None
}

fn keyword_name(text: &str, keywords: &[&str]) -> Option<(String, usize)> {
    let mut offset = 0_usize;
    for keyword in keywords {
        offset = text[offset..].find(keyword).map(|found| offset + found)?;
        if !boundary_before(text, offset) || !boundary_after(text, offset + keyword.len()) {
            return None;
        }
        offset += keyword.len();
        offset = skip_whitespace(text, offset);
    }
    let start = offset;
    while offset < text.len() {
        let character = text[offset..].chars().next()?;
        if !is_identifier_character(character) {
            break;
        }
        offset += character.len_utf8();
    }
    (offset > start).then(|| (text[start..offset].to_owned(), start))
}

fn namespace_name(text: &str) -> Option<(String, usize)> {
    let namespace = text.find("namespace")?;
    if !boundary_before(text, namespace) || !boundary_after(text, namespace + "namespace".len()) {
        return None;
    }
    let start = skip_whitespace(text, namespace + "namespace".len());
    let mut offset = start;
    let mut parts = Vec::new();
    loop {
        offset = skip_whitespace(text, offset);
        let identifier_start = offset;
        while offset < text.len() {
            let character = text[offset..].chars().next()?;
            if !is_identifier_character(character) {
                break;
            }
            offset += character.len_utf8();
        }
        if offset == identifier_start {
            break;
        }
        let part = &text[identifier_start..offset];
        if part == "inline" {
            continue;
        }
        parts.push(part);
        offset = skip_whitespace(text, offset);
        if !text[offset..].starts_with("::") {
            break;
        }
        offset += 2;
    }
    (!parts.is_empty()).then(|| (parts.join("::"), start))
}

fn looks_like_declarator(text: &str, offset: usize, length: usize) -> bool {
    let after = skip_whitespace(text, offset + length);
    matches!(
        text.as_bytes().get(after).copied(),
        None | Some(b'=' | b',' | b';' | b'[' | b'(' | b'{' | b':')
    )
}

fn exact_occurrences(text: &str, needle: &str) -> Vec<usize> {
    if needle.is_empty() {
        return Vec::new();
    }
    text.match_indices(needle)
        .filter_map(|(offset, _)| {
            (boundary_before(text, offset) && boundary_after(text, offset + needle.len()))
                .then_some(offset)
        })
        .collect()
}

fn boundary_before(text: &str, offset: usize) -> bool {
    text[..offset]
        .chars()
        .next_back()
        .is_none_or(|character| !is_identifier_character(character))
}

fn boundary_after(text: &str, offset: usize) -> bool {
    text[offset..]
        .chars()
        .next()
        .is_none_or(|character| !is_identifier_character(character))
}

fn is_identifier_character(character: char) -> bool {
    character == '_' || character.is_alphanumeric() || !character.is_ascii()
}

fn skip_whitespace(text: &str, mut offset: usize) -> usize {
    while offset < text.len() {
        let Some(character) = text[offset..].chars().next() else {
            break;
        };
        if !character.is_whitespace() {
            break;
        }
        offset += character.len_utf8();
    }
    offset
}

fn skip_template_arguments(text: &str, offset: usize) -> Option<usize> {
    let mut offset = skip_whitespace(text, offset);
    if text.as_bytes().get(offset) != Some(&b'<') {
        return Some(offset);
    }
    let mut depth = 0_usize;
    while offset < text.len() {
        match text.as_bytes()[offset] {
            b'<' => depth += 1,
            b'>' => {
                depth = depth.checked_sub(1)?;
                if depth == 0 {
                    return Some(skip_whitespace(text, offset + 1));
                }
            }
            _ => {}
        }
        offset += 1;
    }
    None
}

fn qualified_start(text: &str, end: usize) -> usize {
    let mut start = end;
    for (offset, character) in text[..end].char_indices().rev() {
        if is_identifier_character(character) || matches!(character, ':' | '~') {
            start = offset;
        } else {
            break;
        }
    }
    start
}

fn function_header(text: &str) -> &str {
    let mut offset = 0_usize;
    for line in text.split_inclusive('\n') {
        let trimmed = line.trim_start();
        if trimmed.starts_with('{') {
            return text[..offset].trim_end();
        }
        offset += line.len();
    }
    text.find('{')
        .map(|offset| text[..offset].trim_end())
        .unwrap_or_else(|| text.trim_end())
}

fn first_header(text: &str) -> &str {
    text.find('{')
        .map(|offset| text[..offset].trim_end())
        .unwrap_or_else(|| text.trim_end())
}

fn compact_signature(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn offset_position(start: SourcePosition, text: &str, offset: usize) -> SourcePosition {
    let prefix = &text[..offset.min(text.len())];
    let extra_lines = prefix.bytes().filter(|byte| *byte == b'\n').count();
    if extra_lines == 0 {
        SourcePosition {
            line: start.line,
            column: start.column + prefix.chars().count(),
        }
    } else {
        SourcePosition {
            line: start.line + extra_lines,
            column: prefix
                .rsplit_once('\n')
                .map_or(0, |(_, tail)| tail.chars().count()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{function_name, keyword_name, namespace_name, DefinitionRole};

    #[test]
    fn function_name_rejects_substrings_body_calls_and_return_types() {
        assert!(function_name("int CanBuildTool() { return BuildTool(); }", "BuildTool").is_none());
        assert!(function_name("BuildTool* Create() { return nullptr; }", "BuildTool").is_none());
        let found = function_name(
            "int Owner::BuildTool(int Value)\n{\n return Value;\n}",
            "BuildTool",
        )
        .expect("method definition");
        assert_eq!(found.name, "Owner::BuildTool");
        assert_eq!(found.role, DefinitionRole::Definition);
    }

    #[test]
    fn keyword_names_keep_the_declared_identifier() {
        assert_eq!(
            keyword_name("enum class Mode { First };", &["enum", "class"]),
            Some(("Mode".to_owned(), 11))
        );
        assert_eq!(
            keyword_name("namespace Other { int Value; }", &["namespace"]),
            Some(("Other".to_owned(), 10))
        );
        assert_eq!(
            namespace_name("namespace UE::UAI::Module { int Value; }"),
            Some(("UE::UAI::Module".to_owned(), 10))
        );
        assert_eq!(
            namespace_name("inline namespace UE :: inline UAI { int Value; }"),
            Some(("UE::UAI".to_owned(), 17))
        );
        assert_eq!(namespace_name("namespace { int Value; }"), None);
    }
}
