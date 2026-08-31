use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::cpp::{
    CallScan, DefinitionCandidate, DirectCallCandidate, LexicalScopeCandidate, SourcePosition,
    SourceRange, TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::scope::normalized_key;

pub(crate) fn call_rules() -> String {
    [
        ("srcq.csharp.call.invocation", "invocation_expression"),
        ("srcq.csharp.call.creation", "object_creation_expression"),
        ("srcq.csharp.binding.variable", "variable_declaration"),
        ("srcq.csharp.binding.parameter", "parameter"),
        ("srcq.csharp.binding.field", "field_declaration"),
        ("srcq.csharp.binding.property", "property_declaration"),
        ("srcq.csharp.scope.class", "class_declaration"),
        ("srcq.csharp.scope.struct", "struct_declaration"),
        ("srcq.csharp.scope.record", "record_declaration"),
        ("srcq.csharp.lexical.block", "block"),
        ("srcq.csharp.lexical.for", "for_statement"),
        ("srcq.csharp.lexical.foreach", "foreach_statement"),
        ("srcq.csharp.lexical.using", "using_statement"),
        ("srcq.csharp.lexical.fixed", "fixed_statement"),
        ("srcq.csharp.lexical.catch", "catch_clause"),
        ("srcq.csharp.lexical.switch", "switch_section"),
        ("srcq.csharp.callable.lambda", "lambda_expression"),
        (
            "srcq.csharp.callable.anonymous",
            "anonymous_method_expression",
        ),
        (
            "srcq.csharp.callable.local-function",
            "local_function_statement",
        ),
    ]
    .into_iter()
    .map(|(id, kind)| {
        format!(
            "id: {id}\nlanguage: CSharp\nrule:\n  kind: {kind}\nseverity: info\nmessage: C# relation candidate"
        )
    })
    .collect::<Vec<_>>()
    .join("\n---\n")
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let stream = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep C# relation output was not UTF-8".to_owned())?;
    let mut scan = CallScan::default();
    for (index, line) in stream.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep C# relation JSON at record {}: {error}",
                index + 1
            )
        })?;
        let record = parse_record(&value, cwd)?;
        match record.rule_id.as_str() {
            "srcq.csharp.call.invocation" => {
                let (callee, dispatch, receiver, receiver_type) = invocation_name(&record.text);
                scan.calls.push(DirectCallCandidate {
                    file: record.file,
                    range: record.range,
                    callee,
                    dispatch,
                    receiver,
                    receiver_type,
                });
            }
            "srcq.csharp.call.creation" => {
                let callee = created_type(&record.text)
                    .map(|type_name| {
                        let constructor = type_name.rsplit("::").next().unwrap_or(&type_name);
                        format!("{type_name}::{constructor}")
                    })
                    .unwrap_or_else(|| "<indirect>".to_owned());
                let dispatch = if callee == "<indirect>" {
                    "unknown"
                } else {
                    "direct-candidate"
                };
                scan.calls.push(DirectCallCandidate {
                    file: record.file,
                    range: record.range,
                    callee,
                    dispatch,
                    receiver: None,
                    receiver_type: None,
                });
            }
            "srcq.csharp.binding.variable"
            | "srcq.csharp.binding.parameter"
            | "srcq.csharp.binding.field"
            | "srcq.csharp.binding.property" => {
                if let Some((type_name, name)) = explicit_binding(&record.text) {
                    let scope = match record.rule_id.as_str() {
                        "srcq.csharp.binding.field" | "srcq.csharp.binding.property" => {
                            TypeBindingScope::Member
                        }
                        "srcq.csharp.binding.parameter" => TypeBindingScope::Parameter,
                        _ => TypeBindingScope::Local,
                    };
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope,
                    });
                }
            }
            "srcq.csharp.scope.class" | "srcq.csharp.scope.struct" | "srcq.csharp.scope.record" => {
                if let Some(type_name) = declared_type_name(&record.text) {
                    scan.type_scopes.push(TypeScopeCandidate {
                        file: record.file,
                        range: record.range,
                        type_name,
                    });
                }
            }
            id if id.starts_with("srcq.csharp.lexical.")
                || id.starts_with("srcq.csharp.callable.") =>
            {
                scan.lexical_scopes.push(LexicalScopeCandidate {
                    file: record.file,
                    range: record.range,
                    callable: id.starts_with("srcq.csharp.callable."),
                });
            }
            _ => {}
        }
    }
    scan.calls.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
            .then_with(|| left.range.end.line.cmp(&right.range.end.line))
            .then_with(|| left.range.end.column.cmp(&right.range.end.column))
    });
    scan.calls.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.range == right.range
            && left.callee == right.callee
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
    });
    scan.type_scopes.dedup();
    scan.lexical_scopes.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
            .then_with(|| left.range.end.line.cmp(&right.range.end.line))
            .then_with(|| left.range.end.column.cmp(&right.range.end.column))
            .then_with(|| left.callable.cmp(&right.callable))
    });
    scan.lexical_scopes.dedup();
    Ok(scan)
}

pub(crate) fn annotate_explicit_member_types(
    calls: &mut [DirectCallCandidate],
    scan: &CallScan,
    definition: &DefinitionCandidate,
) {
    for call in calls {
        if call.dispatch == "typed-member-candidate" {
            continue;
        }
        if call.dispatch != "member-candidate" {
            continue;
        }
        let Some(receiver) = call.receiver.as_deref() else {
            continue;
        };
        if let Some(type_name) =
            explicit_receiver_type(scan, definition, receiver, call.range.start)
        {
            qualify_call(call, &type_name);
        }
    }
}

pub(crate) fn explicit_receiver_type(
    scan: &CallScan,
    definition: &DefinitionCandidate,
    receiver: &str,
    call_position: SourcePosition,
) -> Option<String> {
    let containing_type = smallest_containing_type(scan, definition);
    if receiver == "this" {
        return containing_type.map(|scope| scope.type_name.clone());
    }
    if !is_simple_identifier(receiver) {
        return None;
    }
    let mut lexical_bindings = scan
        .bindings
        .iter()
        .filter_map(|binding| {
            (binding.scope != TypeBindingScope::Member
                && normalized_key(&binding.file) == normalized_key(&definition.file)
                && contains(definition.range, binding.range)
                && position_le(binding.range.start, call_position)
                && binding.name == receiver)
                .then(|| {
                    binding_scope_range(scan, definition, binding)
                        .filter(|range| contains_position(*range, call_position))
                        .map(|range| (range_size(range), binding.type_name.clone()))
                })
                .flatten()
        })
        .collect::<Vec<_>>();
    lexical_bindings.sort_by(|left, right| left.0.cmp(&right.0));
    if let Some((smallest_scope, _)) = lexical_bindings.first() {
        let types = lexical_bindings
            .iter()
            .take_while(|(scope, _)| scope == smallest_scope)
            .map(|(_, type_name)| type_name.clone())
            .collect::<BTreeSet<_>>();
        return (types.len() == 1)
            .then(|| types.into_iter().next())
            .flatten();
    }
    let scope = containing_type?;
    let member_types = scan
        .bindings
        .iter()
        .filter(|binding| {
            binding.scope == TypeBindingScope::Member
                && normalized_key(&binding.file) == normalized_key(&definition.file)
                && contains(scope.range, binding.range)
                && binding.name == receiver
        })
        .map(|binding| binding.type_name.clone())
        .collect::<BTreeSet<_>>();
    (member_types.len() == 1)
        .then(|| member_types.into_iter().next())
        .flatten()
}

fn binding_scope_range(
    scan: &CallScan,
    definition: &DefinitionCandidate,
    binding: &TypeBindingCandidate,
) -> Option<SourceRange> {
    let callable_only = binding.scope == TypeBindingScope::Parameter;
    let lexical_scope = scan
        .lexical_scopes
        .iter()
        .filter(|scope| {
            normalized_key(&scope.file) == normalized_key(&binding.file)
                && (!callable_only || scope.callable)
                && contains(scope.range, binding.range)
        })
        .min_by_key(|scope| range_size(scope.range))
        .map(|scope| scope.range);
    if binding.scope == TypeBindingScope::Local {
        lexical_scope
    } else {
        lexical_scope.or(Some(definition.range))
    }
}

pub(crate) fn containing_type_name(
    scan: &CallScan,
    definition: &DefinitionCandidate,
) -> Option<String> {
    smallest_containing_type(scan, definition).map(|scope| scope.type_name.clone())
}

pub(crate) fn receiver_chain(receiver: &str) -> Option<Vec<String>> {
    let parts = receiver
        .split('.')
        .map(|part| part.trim().trim_end_matches('?').trim())
        .collect::<Vec<_>>();
    if parts.is_empty()
        || parts
            .iter()
            .any(|part| part.is_empty() || !is_simple_identifier(part))
    {
        return None;
    }
    Some(parts.into_iter().map(ToOwned::to_owned).collect())
}

pub(crate) fn definition_member_type(signature: &str) -> Option<String> {
    explicit_binding(signature).map(|(type_name, _)| type_name)
}

pub(crate) fn qualify_call(call: &mut DirectCallCandidate, type_name: &str) {
    call.callee = format!("{type_name}::{}", call.callee);
    call.dispatch = "typed-member-candidate";
    call.receiver_type = Some(type_name.to_owned());
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

fn invocation_name(text: &str) -> (String, &'static str, Option<String>, Option<String>) {
    let text = text.trim();
    let Some(open) = outer_call_open(text) else {
        return ("<indirect>".to_owned(), "unknown", None, None);
    };
    let callee = text[..open].trim();
    if let Some((receiver, member)) = split_member(callee) {
        let member = strip_type_arguments(member).trim();
        if member.is_empty() || !member.chars().all(is_identifier) {
            return ("<indirect>".to_owned(), "unknown", None, None);
        }
        let receiver = receiver.trim().trim_end_matches('?').trim();
        if let Some(receiver_type) = created_type(receiver) {
            return (
                format!("{receiver_type}::{member}"),
                "typed-member-candidate",
                Some(receiver.to_owned()),
                Some(receiver_type),
            );
        }
        return (
            member.to_owned(),
            "member-candidate",
            Some(receiver.to_owned()),
            None,
        );
    }
    let callee = strip_type_arguments(callee).trim();
    if callee.is_empty() || !callee.chars().all(is_identifier) {
        return ("<indirect>".to_owned(), "unknown", None, None);
    }
    (callee.to_owned(), "direct-candidate", None, None)
}

fn split_member(text: &str) -> Option<(&str, &str)> {
    let bytes = text.as_bytes();
    let mut paren = 0_usize;
    let mut bracket = 0_usize;
    let mut angle = 0_usize;
    for index in (0..bytes.len()).rev() {
        match bytes[index] {
            b')' => paren += 1,
            b'(' => paren = paren.saturating_sub(1),
            b']' => bracket += 1,
            b'[' => bracket = bracket.saturating_sub(1),
            b'>' => angle += 1,
            b'<' => angle = angle.saturating_sub(1),
            b'.' if paren == 0 && bracket == 0 && angle == 0 => {
                return Some((&text[..index], &text[index + 1..]));
            }
            _ => {}
        }
    }
    None
}

fn created_type(text: &str) -> Option<String> {
    let text = text.trim();
    let rest = text.strip_prefix("new ")?.trim_start();
    let mut end = 0_usize;
    let mut angle = 0_usize;
    for (offset, character) in rest.char_indices() {
        match character {
            '<' => angle += 1,
            '>' => angle = angle.saturating_sub(1),
            '(' | '[' | '{' | ' ' if angle == 0 => break,
            _ => end = offset + character.len_utf8(),
        }
    }
    normalize_type_name(&rest[..end])
}

fn explicit_binding(text: &str) -> Option<(String, String)> {
    let trimmed = text.trim().trim_end_matches(';').trim();
    let head_end = top_level_separator(trimmed).unwrap_or(trimmed.len());
    let head = trimmed[..head_end].trim();
    if has_top_level_comma(head) {
        return None;
    }
    let (name_start, name_end) = last_identifier(head)?;
    let name = head[name_start..name_end].to_owned();
    let prefix = head[..name_start].trim_end();
    let declared = declared_type(prefix)?;
    let type_name = if declared == "var" {
        let initializer = trimmed[head_end..]
            .trim_start_matches([' ', '='])
            .trim_start();
        created_type(initializer)?
    } else {
        declared
    };
    Some((type_name, name))
}

fn declared_type(prefix: &str) -> Option<String> {
    let mut rest = prefix.trim();
    loop {
        let Some((token, tail)) = split_first_token(rest) else {
            break;
        };
        if !matches!(
            token,
            "public"
                | "private"
                | "protected"
                | "internal"
                | "static"
                | "readonly"
                | "volatile"
                | "const"
                | "required"
                | "ref"
                | "out"
                | "in"
                | "params"
                | "this"
                | "scoped"
        ) {
            break;
        }
        rest = tail.trim_start();
    }
    normalize_type_name(rest)
}

fn normalize_type_name(value: &str) -> Option<String> {
    let mut value = value.trim().trim_start_matches("global::").trim();
    while let Some(stripped) = value.strip_suffix('?') {
        value = stripped.trim_end();
    }
    if value.is_empty()
        || value == "dynamic"
        || value.contains(char::is_whitespace)
        || value.contains(['[', ']', '<', '>', '(', ')', ','])
        || !value
            .chars()
            .all(|character| is_identifier(character) || matches!(character, '.' | ':'))
    {
        return None;
    }
    Some(value.replace('.', "::"))
}

fn declared_type_name(text: &str) -> Option<String> {
    let header = text.lines().find(|line| !line.trim().is_empty())?.trim();
    for keyword in [
        "class ",
        "struct ",
        "record class ",
        "record struct ",
        "record ",
    ] {
        if let Some(offset) = header.find(keyword) {
            let rest = &header[offset + keyword.len()..];
            let name = rest
                .chars()
                .take_while(|character| is_identifier(*character))
                .collect::<String>();
            if !name.is_empty() {
                return Some(name);
            }
        }
    }
    None
}

fn top_level_separator(text: &str) -> Option<usize> {
    let mut angle = 0_usize;
    for (offset, character) in text.char_indices() {
        match character {
            '<' => angle += 1,
            '>' => angle = angle.saturating_sub(1),
            '=' | '{' if angle == 0 => return Some(offset),
            _ => {}
        }
    }
    None
}

fn has_top_level_comma(text: &str) -> bool {
    let mut angle = 0_usize;
    text.chars().any(|character| match character {
        '<' => {
            angle += 1;
            false
        }
        '>' => {
            angle = angle.saturating_sub(1);
            false
        }
        ',' if angle == 0 => true,
        _ => false,
    })
}

fn split_first_token(text: &str) -> Option<(&str, &str)> {
    let end = text.find(char::is_whitespace).unwrap_or(text.len());
    (!text.is_empty()).then_some((&text[..end], &text[end..]))
}

fn last_identifier(text: &str) -> Option<(usize, usize)> {
    let end = text
        .char_indices()
        .rev()
        .find(|(_, character)| is_identifier(*character))
        .map(|(offset, character)| offset + character.len_utf8())?;
    let mut start = end;
    while start > 0 {
        let Some((offset, character)) = text[..start].char_indices().next_back() else {
            break;
        };
        if !is_identifier(character) {
            break;
        }
        start = offset;
    }
    Some((start, end))
}

fn outer_call_open(text: &str) -> Option<usize> {
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

fn strip_type_arguments(text: &str) -> &str {
    text.find('<').map_or(text, |offset| &text[..offset])
}

fn parse_record(value: &Value, cwd: &Path) -> Result<AstRecord, String> {
    let raw_file = value
        .get("file")
        .and_then(Value::as_str)
        .ok_or_else(|| "ast-grep C# relation record is missing file".to_owned())?;
    let file = PathBuf::from(raw_file);
    let file = if file.is_absolute() {
        file
    } else {
        cwd.join(file)
    };
    let file = fs::canonicalize(&file).unwrap_or(file);
    let range = value
        .get("range")
        .ok_or_else(|| "ast-grep C# relation record is missing range".to_owned())?;
    Ok(AstRecord {
        file,
        range: SourceRange {
            start: parse_position(
                range
                    .get("start")
                    .ok_or_else(|| "ast-grep C# relation range is missing start".to_owned())?,
            )?,
            end: parse_position(
                range
                    .get("end")
                    .ok_or_else(|| "ast-grep C# relation range is missing end".to_owned())?,
            )?,
        },
        text: value
            .get("text")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep C# relation record is missing text".to_owned())?
            .to_owned(),
        rule_id: value
            .get("ruleId")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep C# relation record is missing ruleId".to_owned())?
            .to_owned(),
    })
}

fn parse_position(value: &Value) -> Result<SourcePosition, String> {
    Ok(SourcePosition {
        line: parse_usize(value.get("line"), "line")?,
        column: parse_usize(value.get("column"), "column")?,
    })
}

fn parse_usize(value: Option<&Value>, field: &str) -> Result<usize, String> {
    value
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| format!("ast-grep C# relation has invalid {field}"))
}

fn is_simple_identifier(value: &str) -> bool {
    value
        .chars()
        .next()
        .is_some_and(|character| !character.is_ascii_digit() && is_identifier(character))
        && value.chars().all(is_identifier)
}

fn is_identifier(character: char) -> bool {
    character == '_' || character.is_alphanumeric() || !character.is_ascii()
}

fn contains(outer: SourceRange, inner: SourceRange) -> bool {
    position_le(outer.start, inner.start) && position_le(inner.end, outer.end)
}

fn contains_position(range: SourceRange, position: SourcePosition) -> bool {
    position_le(range.start, position) && position_le(position, range.end)
}

fn position_le(left: SourcePosition, right: SourcePosition) -> bool {
    (left.line, left.column) <= (right.line, right.column)
}

fn range_size(range: SourceRange) -> (usize, usize) {
    (
        range.end.line.saturating_sub(range.start.line),
        range.end.column.saturating_sub(range.start.column),
    )
}

struct AstRecord {
    file: PathBuf,
    range: SourceRange,
    text: String,
    rule_id: String,
}
