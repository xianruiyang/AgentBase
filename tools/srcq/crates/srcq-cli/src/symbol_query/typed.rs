use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::cpp::{
    CallScan, DefinitionCandidate, DirectCallCandidate, NameBindingCandidate, SourcePosition,
    SourceRange, TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::scope::normalized_key;

pub(crate) struct RelationRecord {
    pub(crate) file: PathBuf,
    pub(crate) range: SourceRange,
    pub(crate) text: String,
    pub(crate) id: String,
}

pub(crate) fn kind_rules(ast_language: &str, prefix: &str, kinds: &[(&str, &str)]) -> String {
    kinds
        .iter()
        .map(|(id, kind)| {
            format!(
                "id: {prefix}.{id}\nlanguage: {ast_language}\nrule:\n  kind: {kind}\nseverity: info\nmessage: typed relation candidate"
            )
        })
        .collect::<Vec<_>>()
        .join("\n---\n")
}

pub(crate) fn parse_records(
    bytes: &[u8],
    cwd: &Path,
    language: &str,
) -> Result<Vec<RelationRecord>, String> {
    let stream = std::str::from_utf8(bytes)
        .map_err(|_| format!("ast-grep {language} relation output was not UTF-8"))?;
    let mut records = Vec::new();
    for (index, line) in stream.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep {language} relation JSON at record {}: {error}",
                index + 1
            )
        })?;
        let raw = value
            .get("file")
            .and_then(Value::as_str)
            .ok_or_else(|| "typed relation record is missing file".to_owned())?;
        let raw_path = PathBuf::from(raw);
        let joined = if raw_path.is_absolute() {
            raw_path
        } else {
            cwd.join(raw_path)
        };
        let file = fs::canonicalize(&joined).unwrap_or(joined);
        let range = value
            .get("range")
            .ok_or_else(|| "typed relation record is missing range".to_owned())?;
        records.push(RelationRecord {
            file,
            range: SourceRange {
                start: record_position(range.get("start"))?,
                end: record_position(range.get("end"))?,
            },
            text: value
                .get("text")
                .and_then(Value::as_str)
                .ok_or_else(|| "typed relation record is missing text".to_owned())?
                .to_owned(),
            id: value
                .get("ruleId")
                .or_else(|| value.get("rule_id"))
                .and_then(Value::as_str)
                .ok_or_else(|| "typed relation record is missing rule id".to_owned())?
                .to_owned(),
        });
    }
    Ok(records)
}

fn record_position(value: Option<&Value>) -> Result<SourcePosition, String> {
    let value = value.ok_or_else(|| "typed relation record is missing position".to_owned())?;
    Ok(SourcePosition {
        line: value
            .get("line")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| "typed relation position has invalid line".to_owned())?,
        column: value
            .get("column")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| "typed relation position has invalid column".to_owned())?,
    })
}

pub(crate) fn annotate_explicit_member_types(
    language: &str,
    calls: &mut [DirectCallCandidate],
    scan: &CallScan,
    definition: &DefinitionCandidate,
) {
    for call in calls {
        if call.dispatch != "member-candidate" {
            continue;
        }
        let Some(receiver) = call.receiver.as_deref() else {
            continue;
        };
        let Some(type_name) = receiver_type(language, scan, definition, receiver, call.range.start)
        else {
            continue;
        };
        call.callee = format!("{type_name}::{}", call.callee);
        call.dispatch = "typed-member-candidate";
        call.receiver_type = Some(type_name);
    }
}

fn receiver_type(
    language: &str,
    scan: &CallScan,
    definition: &DefinitionCandidate,
    receiver: &str,
    call_position: SourcePosition,
) -> Option<String> {
    if let Some(created) = created_type(receiver) {
        return Some(created);
    }
    let containing_type = smallest_containing_type(scan, definition);
    let current_receivers = match language {
        "javascript" | "typescript" | "tsx" => &["this"][..],
        "python" => &["self", "cls"][..],
        "rust" => &["self"][..],
        _ => &[][..],
    };
    if current_receivers.contains(&receiver) {
        return containing_type.map(|scope| scope.type_name.clone());
    }
    for current in current_receivers {
        if let Some(field) = receiver
            .strip_prefix(current)
            .and_then(|value| value.strip_prefix('.'))
            .filter(|name| is_identifier(name))
        {
            return unique_member_type(scan, containing_type?, field);
        }
    }
    if !is_identifier(receiver) {
        return None;
    }
    let mut candidates = scan
        .bindings
        .iter()
        .filter(|binding| {
            binding.scope != TypeBindingScope::Member
                && normalized_key(&binding.file) == normalized_key(&definition.file)
                && contains(definition.range, binding.range)
                && position_le(binding.range.start, call_position)
                && binding.name == receiver
        })
        .filter_map(|binding| {
            binding_scope(scan, definition, binding)
                .filter(|range| contains_position(*range, call_position))
                .map(|range| (range_size(range), binding.type_name.clone()))
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|candidate| candidate.0);
    if let Some((smallest, _)) = candidates.first() {
        let types = candidates
            .iter()
            .take_while(|(size, _)| size == smallest)
            .map(|(_, type_name)| type_name.clone())
            .collect::<BTreeSet<_>>();
        return (types.len() == 1)
            .then(|| types.into_iter().next())
            .flatten();
    }
    if scan.unresolved_bindings.iter().any(|binding| {
        normalized_key(&binding.file) == normalized_key(&definition.file)
            && contains(definition.range, binding.range)
            && position_le(binding.range.start, call_position)
            && binding.name == receiver
            && name_binding_scope(scan, definition, binding)
                .is_some_and(|range| contains_position(range, call_position))
    }) {
        return None;
    }
    if scan
        .type_scopes
        .iter()
        .any(|scope| scope.type_name == receiver)
    {
        return Some(receiver.to_owned());
    }
    containing_type.and_then(|scope| unique_member_type(scan, scope, receiver))
}

fn binding_scope(
    scan: &CallScan,
    definition: &DefinitionCandidate,
    binding: &TypeBindingCandidate,
) -> Option<SourceRange> {
    if binding.scope == TypeBindingScope::Parameter {
        return scan
            .lexical_scopes
            .iter()
            .filter(|scope| {
                scope.callable
                    && normalized_key(&scope.file) == normalized_key(&binding.file)
                    && contains(scope.range, binding.range)
            })
            .min_by_key(|scope| range_size(scope.range))
            .map(|scope| scope.range)
            .or(Some(definition.range));
    }
    scan.lexical_scopes
        .iter()
        .filter(|scope| {
            normalized_key(&scope.file) == normalized_key(&binding.file)
                && contains(scope.range, binding.range)
        })
        .min_by_key(|scope| range_size(scope.range))
        .map(|scope| scope.range)
}

fn name_binding_scope(
    scan: &CallScan,
    definition: &DefinitionCandidate,
    binding: &NameBindingCandidate,
) -> Option<SourceRange> {
    if binding.scope == TypeBindingScope::Parameter {
        return scan
            .lexical_scopes
            .iter()
            .filter(|scope| {
                scope.callable
                    && normalized_key(&scope.file) == normalized_key(&binding.file)
                    && contains(scope.range, binding.range)
            })
            .min_by_key(|scope| range_size(scope.range))
            .map(|scope| scope.range)
            .or(Some(definition.range));
    }
    scan.lexical_scopes
        .iter()
        .filter(|scope| {
            normalized_key(&scope.file) == normalized_key(&binding.file)
                && contains(scope.range, binding.range)
        })
        .min_by_key(|scope| range_size(scope.range))
        .map(|scope| scope.range)
}

fn unique_member_type(scan: &CallScan, scope: &TypeScopeCandidate, name: &str) -> Option<String> {
    let types = scan
        .bindings
        .iter()
        .filter(|binding| {
            binding.scope == TypeBindingScope::Member
                && normalized_key(&binding.file) == normalized_key(&scope.file)
                && contains(scope.range, binding.range)
                && binding.name == name
        })
        .map(|binding| binding.type_name.clone())
        .collect::<BTreeSet<_>>();
    (types.len() == 1)
        .then(|| types.into_iter().next())
        .flatten()
}

fn smallest_containing_type<'a>(
    scan: &'a CallScan,
    definition: &DefinitionCandidate,
) -> Option<&'a TypeScopeCandidate> {
    scan.type_scopes
        .iter()
        .filter(|scope| {
            normalized_key(&scope.file) == normalized_key(&definition.file)
                && contains(scope.range, definition.range)
        })
        .min_by_key(|scope| range_size(scope.range))
}

pub(crate) fn created_type(value: &str) -> Option<String> {
    let type_name = value
        .trim()
        .strip_prefix("new ")?
        .trim()
        .split_once('(')?
        .0
        .trim();
    is_type_name(type_name).then(|| type_name.to_owned())
}

pub(crate) fn outer_call_open(text: &str) -> Option<usize> {
    let bytes = text.as_bytes();
    for open in bytes
        .iter()
        .enumerate()
        .filter_map(|(index, byte)| (*byte == b'(').then_some(index))
    {
        let mut depth = 0_usize;
        for (index, byte) in bytes.iter().enumerate().skip(open) {
            match byte {
                b'(' => depth += 1,
                b')' => {
                    depth = depth.saturating_sub(1);
                    if depth == 0 {
                        if text[index + 1..].trim().is_empty() {
                            return Some(open);
                        }
                        break;
                    }
                }
                _ => {}
            }
        }
    }
    None
}
fn contains(outer: SourceRange, inner: SourceRange) -> bool {
    position_le(outer.start, inner.start) && position_le(inner.end, outer.end)
}
fn contains_position(range: SourceRange, position: SourcePosition) -> bool {
    position_le(range.start, position) && position_le(position, range.end)
}
fn range_size(range: SourceRange) -> (usize, usize) {
    (
        range.end.line.saturating_sub(range.start.line),
        range.end.column.saturating_sub(range.start.column),
    )
}
fn position_le(left: SourcePosition, right: SourcePosition) -> bool {
    left.line < right.line || (left.line == right.line && left.column <= right.column)
}
pub(crate) fn is_identifier(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|c| c == '_' || c == '$' || c.is_alphanumeric())
}
pub(crate) fn is_type_name(value: &str) -> bool {
    !value.is_empty() && value.split('.').all(is_identifier)
}
