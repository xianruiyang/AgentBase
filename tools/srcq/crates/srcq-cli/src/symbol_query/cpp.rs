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
        rules.extend(lexical_scope_rules(&regex));
    }
    rules.push(format!(
        "id: srcq.cpp.declaration.init\nlanguage: Cpp\nrule:\n  all:\n    - kind: declaration\n    - has:\n        stopBy: end\n        kind: init_declarator\n    - has:\n        stopBy: end\n        regex: '^{regex}$'\nseverity: info\nmessage: direct-initialized variable marker"
    ));
    rules.join("\n---\n")
}

fn lexical_scope_rules(regex: &str) -> Vec<String> {
    [
        ("srcq.cpp.scope.function", "function_definition"),
        ("srcq.cpp.scope.class", "class_specifier"),
        ("srcq.cpp.scope.struct", "struct_specifier"),
        ("srcq.cpp.scope.union", "union_specifier"),
        ("srcq.cpp.scope.enum", "enum_specifier"),
        ("srcq.cpp.scope.namespace", "namespace_definition"),
    ]
    .into_iter()
    .map(|(id, kind)| {
        format!(
            "id: {id}\nlanguage: Cpp\nrule:\n  all:\n    - kind: {kind}\n    - has:\n        stopBy: end\n        regex: '^{regex}$'\nseverity: info\nmessage: lexical scope candidate"
        )
    })
    .collect()
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
    pub(crate) receiver: Option<String>,
    pub(crate) receiver_type: Option<String>,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct CallScan {
    pub(crate) calls: Vec<DirectCallCandidate>,
    pub(crate) bindings: Vec<TypeBindingCandidate>,
    pub(crate) unresolved_bindings: Vec<NameBindingCandidate>,
    pub(crate) type_scopes: Vec<TypeScopeCandidate>,
    pub(crate) lexical_scopes: Vec<LexicalScopeCandidate>,
}

impl CallScan {
    pub(crate) fn calls_only(calls: Vec<DirectCallCandidate>) -> Self {
        Self {
            calls,
            bindings: Vec::new(),
            unresolved_bindings: Vec::new(),
            type_scopes: Vec::new(),
            lexical_scopes: Vec::new(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub(crate) enum TypeBindingScope {
    Lexical,
    Local,
    Parameter,
    Member,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TypeBindingCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) name: String,
    pub(crate) type_name: String,
    pub(crate) scope: TypeBindingScope,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct NameBindingCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) name: String,
    pub(crate) scope: TypeBindingScope,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TypeScopeCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) type_name: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct LexicalScopeCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) callable: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct FunctionOwnerCandidate {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) name: String,
    pub(crate) qualified_name: Option<String>,
    pub(crate) signature: String,
    pub(crate) definition: Option<DefinitionCandidate>,
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
    text: String,
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
    let records = parse_records(bytes, cwd, None, "definition")?;
    parse_definition_records(&records, target, universe)
}

pub(crate) fn parse_header_scan_stream(
    bytes: &[u8],
    cwd: &Path,
    file: &Path,
    target: &str,
    universe: &SourceUniverse,
) -> Result<Vec<DefinitionCandidate>, String> {
    let records = parse_records(bytes, cwd, Some(file), "C++ header definition")?;
    parse_definition_records(&records, target, universe)
}

fn parse_definition_records(
    records: &[AstRecord],
    target: &str,
    universe: &SourceUniverse,
) -> Result<Vec<DefinitionCandidate>, String> {
    let scopes = build_scopes(records);
    let target_last = target.rsplit("::").next().unwrap_or(target);
    let mut candidates = Vec::new();
    for record in records {
        let direct_initialized = records.iter().any(|candidate| {
            candidate.rule_id == "srcq.cpp.declaration.init"
                && normalized_key(&candidate.file) == normalized_key(&record.file)
                && candidate.range == record.range
        });
        let Some(extracted) = extract_target(record, target_last, direct_initialized) else {
            continue;
        };
        if matches!(
            record.rule_id.as_str(),
            "srcq.cpp.namespace" | "srcq.cpp.declaration.init"
        ) {
            continue;
        }
        let friend_function =
            extracted.ast_kind == "function_definition" && is_friend_function(record, &scopes);
        let qualified_name = if friend_function {
            qualify_excluding_type_scopes(record, &extracted.name, &scopes)
        } else {
            qualify(record, &extracted.name, &scopes)
        };
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
        let symbol_kind = if extracted.ast_kind == "function_definition" {
            if is_inside_type_scope(record, &scopes) && !friend_function {
                "method"
            } else {
                "function"
            }
        } else {
            extracted.symbol_kind
        };
        candidates.push(DefinitionCandidate {
            root_alias: universe.root_for(&file).map(|root| root.alias.clone()),
            file,
            range: record.range,
            name_position,
            qualified_name,
            symbol_kind: symbol_kind.to_owned(),
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

pub(crate) fn promote_methods_from_declarations(candidates: &mut [DefinitionCandidate]) {
    let declared_methods = candidates
        .iter()
        .filter(|candidate| {
            candidate.role == DefinitionRole::Declaration && candidate.symbol_kind == "method"
        })
        .map(|candidate| candidate.qualified_name.clone())
        .collect::<BTreeSet<_>>();
    for candidate in candidates {
        if candidate.role == DefinitionRole::Definition
            && candidate.symbol_kind == "function"
            && declared_methods.contains(&candidate.qualified_name)
        {
            candidate.symbol_kind = "method".to_owned();
        }
    }
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
    let records = parse_records(bytes, cwd, None, "occurrence")?;
    parse_occurrence_records(records, universe)
}

pub(crate) fn parse_header_occurrence_stream(
    bytes: &[u8],
    cwd: &Path,
    file: &Path,
    universe: &SourceUniverse,
) -> Result<Vec<OccurrenceCandidate>, String> {
    let records = parse_records(bytes, cwd, Some(file), "C++ header occurrence")?;
    parse_occurrence_records(records, universe)
}

fn parse_occurrence_records(
    records: Vec<AstRecord>,
    universe: &SourceUniverse,
) -> Result<Vec<OccurrenceCandidate>, String> {
    let mut occurrences = Vec::new();
    for record in records {
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
    "id: srcq.cpp.call\nlanguage: Cpp\nrule:\n  kind: call_expression\nseverity: info\nmessage: direct call candidate\n---\nid: srcq.cpp.binding.declaration\nlanguage: Cpp\nrule:\n  kind: declaration\nseverity: info\nmessage: explicit type binding candidate\n---\nid: srcq.cpp.binding.parameter\nlanguage: Cpp\nrule:\n  kind: parameter_declaration\nseverity: info\nmessage: explicit parameter type candidate\n---\nid: srcq.cpp.binding.field\nlanguage: Cpp\nrule:\n  kind: field_declaration\nseverity: info\nmessage: explicit field type binding candidate\n---\nid: srcq.cpp.type.class\nlanguage: Cpp\nrule:\n  kind: class_specifier\nseverity: info\nmessage: class type scope candidate\n---\nid: srcq.cpp.type.struct\nlanguage: Cpp\nrule:\n  kind: struct_specifier\nseverity: info\nmessage: struct type scope candidate\n---\nid: srcq.cpp.type.union\nlanguage: Cpp\nrule:\n  kind: union_specifier\nseverity: info\nmessage: union type scope candidate"
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let records = parse_records(bytes, cwd, None, "call")?;
    parse_call_records(records)
}

pub(crate) fn parse_header_call_stream(
    bytes: &[u8],
    cwd: &Path,
    file: &Path,
) -> Result<CallScan, String> {
    let records = parse_records(bytes, cwd, Some(file), "C++ header call")?;
    parse_call_records(records)
}

fn parse_call_records(records: Vec<AstRecord>) -> Result<CallScan, String> {
    let mut scan = CallScan::default();
    for record in records {
        let file = fs::canonicalize(&record.file).unwrap_or(record.file);
        if record.rule_id == "srcq.cpp.call" {
            let (callee, dispatch, receiver) = call_name(&record.text);
            scan.calls.push(DirectCallCandidate {
                file,
                range: record.range,
                callee,
                dispatch,
                receiver,
                receiver_type: None,
            });
        } else if matches!(
            record.rule_id.as_str(),
            "srcq.cpp.binding.declaration"
                | "srcq.cpp.binding.parameter"
                | "srcq.cpp.binding.field"
        ) {
            if let Some((type_name, name)) = simple_type_binding(&record.text) {
                let scope = match record.rule_id.as_str() {
                    "srcq.cpp.binding.parameter" => TypeBindingScope::Parameter,
                    "srcq.cpp.binding.field" => TypeBindingScope::Member,
                    _ => TypeBindingScope::Lexical,
                };
                scan.bindings.push(TypeBindingCandidate {
                    file,
                    range: record.range,
                    name,
                    type_name,
                    scope,
                });
            }
        } else if matches!(
            record.rule_id.as_str(),
            "srcq.cpp.type.class" | "srcq.cpp.type.struct" | "srcq.cpp.type.union"
        ) {
            let keyword = match record.rule_id.as_str() {
                "srcq.cpp.type.class" => "class",
                "srcq.cpp.type.struct" => "struct",
                _ => "union",
            };
            if let Some((type_name, _)) = keyword_name(&record.text, &[keyword]) {
                scan.type_scopes.push(TypeScopeCandidate {
                    file,
                    range: record.range,
                    type_name,
                });
            }
        }
    }
    scan.calls.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    scan.calls.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.range.start == right.range.start
    });
    scan.bindings.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
            .then_with(|| left.name.cmp(&right.name))
    });
    scan.bindings.dedup();
    scan.type_scopes.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
            .then_with(|| left.type_name.cmp(&right.type_name))
    });
    scan.type_scopes.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.range == right.range
            && left.type_name == right.type_name
    });
    Ok(scan)
}

pub(crate) fn annotate_explicit_member_types(
    calls: &mut [DirectCallCandidate],
    scan: &CallScan,
    definition: &DefinitionCandidate,
) {
    let implicit_receiver_type = (definition.symbol_kind == "method")
        .then(|| {
            definition
                .qualified_name
                .rsplit_once("::")
                .map(|(owner, _)| owner)
        })
        .flatten();
    for call in calls {
        if call.dispatch == "direct-candidate"
            && !call.callee.contains("::")
            && implicit_receiver_type.is_some()
        {
            let receiver_type = implicit_receiver_type.expect("checked implicit receiver type");
            call.callee = format!("{receiver_type}::{}", call.callee);
            call.dispatch = "typed-member-candidate";
            call.receiver_type = Some(receiver_type.to_owned());
            continue;
        }
        if call.dispatch != "member-candidate" {
            continue;
        }
        let Some(receiver) = call.receiver.as_deref() else {
            continue;
        };
        if receiver == "this" && implicit_receiver_type.is_some() {
            let receiver_type = implicit_receiver_type.expect("checked implicit receiver type");
            call.callee = format!("{receiver_type}::{}", call.callee);
            call.dispatch = "typed-member-candidate";
            call.receiver_type = Some(receiver_type.to_owned());
            continue;
        }
        let Some(type_name) = receiver_type(receiver, scan, definition, call) else {
            continue;
        };
        call.callee = format!("{type_name}::{}", call.callee);
        call.dispatch = "typed-member-candidate";
        call.receiver_type = Some(type_name);
    }
}

fn receiver_type(
    receiver: &str,
    scan: &CallScan,
    definition: &DefinitionCandidate,
    call: &DirectCallCandidate,
) -> Option<String> {
    let chain = simple_member_chain(receiver)?;
    let mut current_type = visible_binding_type(chain[0], scan, definition, call)?;
    for member in chain.into_iter().skip(1) {
        current_type = member_binding_type(member, &current_type, scan, &call.file)?;
    }
    Some(current_type)
}

fn simple_member_chain(receiver: &str) -> Option<Vec<&str>> {
    let mut offset = skip_whitespace(receiver, 0);
    let mut chain = Vec::new();
    loop {
        let start = offset;
        let first = receiver[offset..].chars().next()?;
        if first.is_ascii_digit() || !is_identifier_character(first) {
            return None;
        }
        offset += first.len_utf8();
        while let Some(character) = receiver[offset..].chars().next() {
            if !is_identifier_character(character) {
                break;
            }
            offset += character.len_utf8();
        }
        chain.push(&receiver[start..offset]);
        offset = skip_whitespace(receiver, offset);
        if offset == receiver.len() {
            return Some(chain);
        }
        if receiver[offset..].starts_with("->") {
            offset += 2;
        } else if receiver[offset..].starts_with('.') {
            offset += 1;
        } else {
            return None;
        }
        offset = skip_whitespace(receiver, offset);
    }
}

fn visible_binding_type(
    name: &str,
    scan: &CallScan,
    definition: &DefinitionCandidate,
    call: &DirectCallCandidate,
) -> Option<String> {
    let types = scan
        .bindings
        .iter()
        .filter(|binding| {
            normalized_key(&binding.file) == normalized_key(&call.file)
                && binding.name == name
                && match binding.scope {
                    TypeBindingScope::Member => scan.type_scopes.iter().any(|scope| {
                        normalized_key(&scope.file) == normalized_key(&call.file)
                            && contains(scope.range, definition.range)
                            && contains(scope.range, binding.range)
                    }),
                    _ => {
                        contains(definition.range, binding.range)
                            && position_le(binding.range.start, call.range.start)
                    }
                }
        })
        .map(|binding| binding.type_name.clone())
        .collect::<BTreeSet<_>>();
    (types.len() == 1)
        .then(|| types.into_iter().next())
        .flatten()
}

fn member_binding_type(
    name: &str,
    owner_type: &str,
    scan: &CallScan,
    file: &Path,
) -> Option<String> {
    let types = scan
        .bindings
        .iter()
        .filter(|binding| {
            binding.scope == TypeBindingScope::Member
                && normalized_key(&binding.file) == normalized_key(file)
                && binding.name == name
                && scan.type_scopes.iter().any(|scope| {
                    normalized_key(&scope.file) == normalized_key(file)
                        && (scope.type_name == owner_type
                            || owner_type.ends_with(&format!("::{}", scope.type_name)))
                        && contains(scope.range, binding.range)
                })
        })
        .map(|binding| binding.type_name.clone())
        .collect::<BTreeSet<_>>();
    (types.len() == 1)
        .then(|| types.into_iter().next())
        .flatten()
}

pub(crate) fn containing_function_rules(target: &str) -> String {
    let target = target.rsplit("::").next().unwrap_or(target);
    let regex = regex_escape(target).replace('\'', "''");
    let mut rules = vec![format!(
        "id: srcq.cpp.containing-function\nlanguage: Cpp\nrule:\n  all:\n    - kind: function_definition\n    - has:\n        stopBy: end\n        regex: '^{regex}$'\nseverity: info\nmessage: containing function candidate"
    )];
    rules.extend(lexical_scope_rules(&regex));
    rules.join("\n---\n")
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
    universe: &SourceUniverse,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    parse_function_owner_stream_impl(bytes, cwd, universe)
}

pub(crate) fn parse_header_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
    file: &Path,
    universe: &SourceUniverse,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    let records = parse_records(bytes, cwd, Some(file), "C++ header owner")?;
    parse_function_owner_records(records, universe)
}

fn parse_function_owner_stream_impl(
    bytes: &[u8],
    cwd: &Path,
    universe: &SourceUniverse,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    let records = parse_records(bytes, cwd, None, "containing-function")?;
    parse_function_owner_records(records, universe)
}

fn parse_function_owner_records(
    records: Vec<AstRecord>,
    universe: &SourceUniverse,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    let scopes = build_scopes(&records);
    let mut owners = Vec::new();
    for record in records {
        if record.rule_id != "srcq.cpp.containing-function" {
            continue;
        }
        let Some((name, offset)) = any_function_name(&record.text) else {
            continue;
        };
        let friend_function = is_friend_function(&record, &scopes);
        let qualified_name = if friend_function {
            qualify_excluding_type_scopes(&record, &name, &scopes)
        } else {
            qualify(&record, &name, &scopes)
        };
        let file = fs::canonicalize(&record.file).unwrap_or_else(|_| record.file.clone());
        let signature = compact_signature(function_header(&record.text));
        let symbol_kind = if is_inside_type_scope(&record, &scopes) && !friend_function {
            "method"
        } else {
            "function"
        };
        let definition = DefinitionCandidate {
            root_alias: universe.root_for(&file).map(|root| root.alias.clone()),
            file: file.clone(),
            range: record.range,
            name_position: offset_position(record.range.start, &record.text, offset),
            qualified_name,
            symbol_kind: symbol_kind.to_owned(),
            role: DefinitionRole::Definition,
            signature: signature.clone(),
            text: record.text,
            ast_kind: "function_definition".to_owned(),
        };
        owners.push(FunctionOwnerCandidate {
            file,
            range: record.range,
            name,
            qualified_name: Some(definition.qualified_name.clone()),
            signature,
            definition: Some(definition),
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

fn call_name(text: &str) -> (String, &'static str, Option<String>) {
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
        return ("<indirect>".to_owned(), "unknown", None);
    };
    let mut callee = text[..open].trim();
    if let Some(template) = callee.find('<') {
        callee = callee[..template].trim_end();
    }
    if callee.contains("->") {
        let (receiver, method) = callee.rsplit_once("->").expect("member split");
        return (
            method.trim().to_owned(),
            "member-candidate",
            Some(receiver.trim().to_owned()),
        );
    }
    if let Some((receiver, method)) = callee.rsplit_once('.') {
        return (
            method.trim().to_owned(),
            "member-candidate",
            Some(receiver.trim().to_owned()),
        );
    }
    if callee.is_empty()
        || callee
            .chars()
            .any(|character| matches!(character, '(' | ')' | '[' | ']'))
        || !callee.chars().any(is_identifier_character)
    {
        return ("<indirect>".to_owned(), "unknown", None);
    }
    (callee.to_owned(), "direct-candidate", None)
}

fn simple_type_binding(text: &str) -> Option<(String, String)> {
    let mut angle_depth = 0_usize;
    let mut end = text.trim_end_matches(';').len();
    for (offset, character) in text.char_indices() {
        match character {
            '<' => angle_depth += 1,
            '>' => angle_depth = angle_depth.saturating_sub(1),
            '=' | '{' if angle_depth == 0 => {
                end = offset;
                break;
            }
            ',' | '(' | ')' | '[' | ']' if angle_depth == 0 => return None,
            _ => {}
        }
    }
    let head = text[..end].trim();
    let mut identifiers = Vec::new();
    let mut start = None;
    for (offset, character) in head.char_indices() {
        if is_identifier_character(character) {
            start.get_or_insert(offset);
        } else if let Some(identifier_start) = start.take() {
            identifiers.push((identifier_start, offset));
        }
    }
    if let Some(identifier_start) = start {
        identifiers.push((identifier_start, head.len()));
    }
    let (name_start, name_end) = identifiers.pop()?;
    let name = head[name_start..name_end].to_owned();
    let type_name = explicit_base_type(&head[..name_start])?;
    Some((type_name, name))
}

fn explicit_base_type(prefix: &str) -> Option<String> {
    if let Some(inner) = pointer_like_template_argument(prefix) {
        return explicit_base_type(inner);
    }
    let mut without_templates = String::new();
    let mut angle_depth = 0_usize;
    for character in prefix.chars() {
        match character {
            '<' => angle_depth += 1,
            '>' => angle_depth = angle_depth.saturating_sub(1),
            '*' | '&' if angle_depth == 0 => without_templates.push(' '),
            _ if angle_depth == 0 => without_templates.push(character),
            _ => {}
        }
    }
    let candidate = without_templates
        .split_whitespace()
        .filter(|token| {
            !matches!(
                *token,
                "const"
                    | "volatile"
                    | "static"
                    | "constexpr"
                    | "mutable"
                    | "register"
                    | "struct"
                    | "class"
                    | "enum"
            )
        })
        .next_back()?;
    if matches!(candidate, "auto" | "decltype" | "typename")
        || !candidate
            .chars()
            .all(|character| is_identifier_character(character) || character == ':')
    {
        return None;
    }
    Some(candidate.to_owned())
}

fn pointer_like_template_argument(prefix: &str) -> Option<&str> {
    let open = prefix.find('<')?;
    let close = prefix.rfind('>')?;
    if close <= open {
        return None;
    }
    let wrapper = prefix[..open]
        .split_whitespace()
        .filter(|token| !matches!(*token, "const" | "volatile" | "static" | "mutable"))
        .next_back()?;
    if !matches!(
        wrapper,
        "std::shared_ptr" | "std::unique_ptr" | "std::weak_ptr" | "std::optional"
    ) {
        return None;
    }
    let arguments = &prefix[open + 1..close];
    let mut depth = 0_usize;
    let end = arguments
        .char_indices()
        .find_map(|(offset, character)| match character {
            '<' => {
                depth += 1;
                None
            }
            '>' => {
                depth = depth.saturating_sub(1);
                None
            }
            ',' if depth == 0 => Some(offset),
            _ => None,
        })
        .unwrap_or(arguments.len());
    Some(arguments[..end].trim())
}

fn parse_records(
    bytes: &[u8],
    cwd: &Path,
    file_override: Option<&Path>,
    stream_name: &str,
) -> Result<Vec<AstRecord>, String> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| format!("ast-grep {stream_name} output was not UTF-8"))?;
    let canonical_override =
        file_override.map(|file| fs::canonicalize(file).unwrap_or_else(|_| file.to_path_buf()));
    let mut records = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep {stream_name} JSON at record {}: {error}",
                index + 1
            )
        })?;
        let mut record = parse_record(&value, cwd)?;
        if let Some(file) = &canonical_override {
            record.file = file.clone();
        }
        records.push(record);
    }
    Ok(records)
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
                text: record.text.clone(),
            })
        })
        .collect()
}

fn is_inside_type_scope(record: &AstRecord, scopes: &[ScopeNode]) -> bool {
    scopes.iter().any(|scope| {
        scope.kind == ScopeKind::Type
            && scope.file_key == normalized_key(&record.file)
            && contains(scope.range, record.range)
    })
}

fn extract_target(
    record: &AstRecord,
    target: &str,
    direct_initialized: bool,
) -> Option<ExtractedName> {
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
        "srcq.cpp.declaration" => {
            declaration_name(&record.text, target, "declaration", direct_initialized)
        }
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
            symbol_kind: "function",
            role: DefinitionRole::Definition,
            signature: compact_signature(header),
            ast_kind: "function_definition",
        });
    }
    None
}

fn is_friend_function(record: &AstRecord, scopes: &[ScopeNode]) -> bool {
    let header = function_header(&record.text);
    let Some((_, name_offset)) = any_function_name(header) else {
        return false;
    };
    if contains_cpp_keyword(&header[..name_offset], "friend") {
        return true;
    }
    scopes.iter().any(|scope| {
        scope.kind == ScopeKind::Type
            && scope.file_key == normalized_key(&record.file)
            && contains(scope.range, record.range)
            && byte_offset_at_position(scope.range.start, &scope.text, record.range.start)
                .and_then(|offset| scope.text.get(..offset))
                .and_then(|prefix| {
                    prefix
                        .rsplit([';', '{', '}'])
                        .next()
                        .map(|declaration_prefix| {
                            contains_cpp_keyword(declaration_prefix, "friend")
                        })
                })
                .unwrap_or(false)
    })
}

fn byte_offset_at_position(
    start: SourcePosition,
    text: &str,
    target: SourcePosition,
) -> Option<usize> {
    let mut position = start;
    for (offset, character) in text.char_indices() {
        if position == target {
            return Some(offset);
        }
        if character == '\n' {
            position.line += 1;
            position.column = 0;
        } else {
            position.column += 1;
        }
    }
    (position == target).then_some(text.len())
}

fn contains_cpp_keyword(text: &str, keyword: &str) -> bool {
    let bytes = text.as_bytes();
    let mut offset = 0_usize;
    while offset < bytes.len() {
        if bytes[offset..].starts_with(b"//") {
            offset += 2;
            while offset < bytes.len() && bytes[offset] != b'\n' {
                offset += 1;
            }
            continue;
        }
        if bytes[offset..].starts_with(b"/*") {
            offset += 2;
            while offset + 1 < bytes.len() && !bytes[offset..].starts_with(b"*/") {
                offset += 1;
            }
            offset = (offset + 2).min(bytes.len());
            continue;
        }
        if matches!(bytes[offset], b'\'' | b'"') {
            let quote = bytes[offset];
            offset += 1;
            while offset < bytes.len() {
                if bytes[offset] == b'\\' {
                    offset = (offset + 2).min(bytes.len());
                } else if bytes[offset] == quote {
                    offset += 1;
                    break;
                } else {
                    offset += 1;
                }
            }
            continue;
        }
        let Some(character) = text[offset..].chars().next() else {
            break;
        };
        if !character.is_ascii_digit() && is_identifier_character(character) {
            let start = offset;
            offset += character.len_utf8();
            while offset < bytes.len() {
                let Some(next) = text[offset..].chars().next() else {
                    break;
                };
                if !is_identifier_character(next) {
                    break;
                }
                offset += next.len_utf8();
            }
            if &text[start..offset] == keyword {
                return true;
            }
            continue;
        }
        offset += character.len_utf8();
    }
    false
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

fn declaration_name(
    text: &str,
    target: &str,
    ast_kind: &'static str,
    direct_initialized: bool,
) -> Option<ExtractedName> {
    let header = first_header(text);
    let offset = declarator_occurrence(header, target)?;
    let after = skip_whitespace(header, offset + target.len());
    let role = if !direct_initialized
        && (header.as_bytes().get(after) == Some(&b'(')
            || header.trim_start().starts_with("extern "))
    {
        DefinitionRole::Declaration
    } else {
        DefinitionRole::Definition
    };
    Some(ExtractedName {
        name: target.to_owned(),
        offset,
        symbol_kind: if role == DefinitionRole::Declaration
            && header.as_bytes().get(after) == Some(&b'(')
        {
            "function"
        } else {
            "variable"
        },
        role,
        signature: compact_signature(header),
        ast_kind,
    })
}

fn field_name(text: &str, target: &str) -> Option<ExtractedName> {
    let header = first_header(text);
    let offset = declarator_occurrence(header, target)?;
    let after = skip_whitespace(header, offset + target.len());
    let method = header.as_bytes().get(after) == Some(&b'(');
    Some(ExtractedName {
        name: target.to_owned(),
        offset,
        symbol_kind: if method { "method" } else { "field" },
        role: if method {
            DefinitionRole::Declaration
        } else {
            DefinitionRole::Definition
        },
        signature: compact_signature(header),
        ast_kind: "field_declaration",
    })
}

fn declarator_occurrence(text: &str, target: &str) -> Option<usize> {
    if let Some((name, offset)) = any_function_name(text) {
        if name.rsplit("::").next() == Some(target)
            && is_top_level_declarator_position(text, offset)
        {
            return Some(offset);
        }
    }
    exact_occurrences(text, target).into_iter().find(|offset| {
        is_top_level_declarator_position(text, *offset)
            && !has_later_identifier_before_declarator_boundary(text, *offset + target.len())
            && text
                .as_bytes()
                .get(skip_whitespace(text, *offset + target.len()))
                != Some(&b'(')
    })
}

fn has_later_identifier_before_declarator_boundary(text: &str, start: usize) -> bool {
    let mut offset = start;
    let mut parentheses = 0_usize;
    let mut angles = 0_usize;
    while offset < text.len() {
        let character = text[offset..]
            .chars()
            .next()
            .expect("offset remains on a character boundary");
        if parentheses == 0 && angles == 0 && matches!(character, '=' | '{' | ',' | ';' | '[') {
            return false;
        }
        if !character.is_ascii_digit() && is_identifier_character(character) {
            return true;
        }
        match character {
            '(' => parentheses += 1,
            ')' => parentheses = parentheses.saturating_sub(1),
            '<' if parentheses == 0 => angles += 1,
            '>' if parentheses == 0 => angles = angles.saturating_sub(1),
            _ => {}
        }
        offset += character.len_utf8();
    }
    false
}

fn is_top_level_declarator_position(text: &str, target_offset: usize) -> bool {
    let mut parentheses = 0_usize;
    let mut brackets = 0_usize;
    let mut angles = 0_usize;
    let mut braces = 0_usize;
    let mut initialized = false;
    for character in text[..target_offset].chars() {
        match character {
            '(' => parentheses += 1,
            ')' => parentheses = parentheses.saturating_sub(1),
            '[' => brackets += 1,
            ']' => brackets = brackets.saturating_sub(1),
            '<' if parentheses == 0 && brackets == 0 => angles += 1,
            '>' if parentheses == 0 && brackets == 0 => angles = angles.saturating_sub(1),
            '{' if parentheses == 0 && brackets == 0 && angles == 0 => {
                initialized = true;
                braces += 1;
            }
            '}' if parentheses == 0 && brackets == 0 && angles == 0 => {
                braces = braces.saturating_sub(1)
            }
            ',' if parentheses == 0 && brackets == 0 && angles == 0 && braces == 0 => {
                initialized = false
            }
            '=' if parentheses == 0 && brackets == 0 && angles == 0 && braces == 0 => {
                initialized = true
            }
            _ => {}
        }
    }
    parentheses == 0 && brackets == 0 && angles == 0 && braces == 0 && !initialized
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
    qualify_with_scope_filter(record, extracted, scopes, false)
}

fn qualify_excluding_type_scopes(
    record: &AstRecord,
    extracted: &str,
    scopes: &[ScopeNode],
) -> String {
    qualify_with_scope_filter(record, extracted, scopes, true)
}

fn qualify_with_scope_filter(
    record: &AstRecord,
    extracted: &str,
    scopes: &[ScopeNode],
    exclude_type_scopes: bool,
) -> String {
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
        if (exclude_type_scopes || extracted.contains("::")) && scope.kind == ScopeKind::Type {
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
    use super::{
        call_name, declaration_name, field_name, function_name, keyword_name, namespace_name,
        simple_member_chain, simple_type_binding, DefinitionRole,
    };

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
    fn field_name_only_accepts_the_declared_header() {
        assert!(field_name("void Select() { object->RayCastTest(); }", "RayCastTest").is_none());
        let declaration =
            field_name("int RayCastTest();", "RayCastTest").expect("bodyless member declaration");
        assert_eq!(declaration.role, DefinitionRole::Declaration);
        assert!(field_name("int Value = RayCastTest();", "RayCastTest").is_none());
        assert!(field_name("int Call(int value = RayCastTest());", "RayCastTest").is_none());
        assert!(declaration_name(
            "int Value = RayCastTest();",
            "RayCastTest",
            "declaration",
            false
        )
        .is_none());
        assert!(field_name("RayCastTest* Value;", "RayCastTest").is_none());
        assert!(field_name("const RayCastTest Value;", "RayCastTest").is_none());
        assert!(
            declaration_name("RayCastTest* Make();", "RayCastTest", "declaration", false,)
                .is_none()
        );
        assert!(declaration_name(
            "const RayCastTest Value;",
            "RayCastTest",
            "declaration",
            false,
        )
        .is_none());
        let variable = declaration_name(
            "int RayCastTest = BuildValue();",
            "RayCastTest",
            "declaration",
            false,
        )
        .expect("declared variable before initializer");
        assert_eq!(variable.symbol_kind, "variable");
    }

    #[test]
    fn member_chain_accepts_only_plain_member_access() {
        assert_eq!(
            simple_member_chain("instance->testCloud"),
            Some(vec!["instance", "testCloud"])
        );
        assert_eq!(
            simple_member_chain(" owner . child -> value "),
            Some(vec!["owner", "child", "value"])
        );
        assert_eq!(simple_member_chain("factory()->value"), None);
        assert_eq!(simple_member_chain("items[index].value"), None);
        assert_eq!(simple_member_chain("wrapper<T>->value"), None);
        assert_eq!(simple_member_chain("(*holder).value"), None);
        assert_eq!(simple_member_chain("ns::holder->value"), None);
        assert_eq!(
            simple_member_chain("static_cast<Owner*>(value)->child"),
            None
        );
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

    #[test]
    fn member_calls_and_explicit_bindings_preserve_only_direct_source_facts() {
        assert_eq!(
            call_name("WorkspaceRoot.TrimStartAndEndInline()"),
            (
                "TrimStartAndEndInline".to_owned(),
                "member-candidate",
                Some("WorkspaceRoot".to_owned())
            )
        );
        assert_eq!(
            simple_type_binding("const FString& WorkspaceRootInput"),
            Some(("FString".to_owned(), "WorkspaceRootInput".to_owned()))
        );
        assert_eq!(
            simple_type_binding("TSharedPtr<FJsonObject> ObjectToSave = Object.IsValid();"),
            Some(("TSharedPtr".to_owned(), "ObjectToSave".to_owned()))
        );
        assert_eq!(simple_type_binding("auto Value = MakeValue();"), None);
        assert_eq!(simple_type_binding("int Function(int Value);"), None);
    }
}
