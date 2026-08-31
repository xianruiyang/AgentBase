use std::path::Path;

use super::cpp::{
    CallScan, DirectCallCandidate, FunctionOwnerCandidate, LexicalScopeCandidate,
    TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::{generic, typed};

pub(crate) fn call_rules(ast_language: &str) -> String {
    typed::kind_rules(
        ast_language,
        "srcq.rust",
        &[
            ("call", "call_expression"),
            ("parameter", "parameter"),
            ("binding-let", "let_declaration"),
            ("binding-field", "field_declaration"),
            ("scope-struct", "struct_item"),
            ("scope-impl", "impl_item"),
            ("scope-block", "block"),
            ("callable-closure", "closure_expression"),
            ("callable-function", "function_item"),
        ],
    )
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let mut scan = CallScan::default();
    for record in typed::parse_records(bytes, cwd, "Rust")? {
        match record.id.as_str() {
            "srcq.rust.call" => {
                let (callee, dispatch, receiver, receiver_type) = call_name(&record.text);
                scan.calls.push(DirectCallCandidate {
                    file: record.file,
                    range: record.range,
                    callee,
                    dispatch,
                    receiver,
                    receiver_type,
                });
            }
            "srcq.rust.parameter" | "srcq.rust.binding-let" | "srcq.rust.binding-field" => {
                let binding = if record.id.ends_with("binding-let") {
                    explicit_or_created_binding(&record.text)
                } else {
                    explicit_binding(&record.text)
                };
                if let Some((name, type_name)) = binding {
                    let scope = if record.id.ends_with("parameter") {
                        TypeBindingScope::Parameter
                    } else if record.id.ends_with("field") {
                        TypeBindingScope::Member
                    } else {
                        TypeBindingScope::Local
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
            "srcq.rust.scope-impl" | "srcq.rust.scope-struct" => {
                let type_name = if record.id.ends_with("impl") {
                    impl_type(&record.text)
                } else {
                    struct_type(&record.text)
                };
                if let Some(type_name) = type_name {
                    scan.type_scopes.push(TypeScopeCandidate {
                        file: record.file,
                        range: record.range,
                        type_name,
                    });
                }
            }
            "srcq.rust.scope-block"
            | "srcq.rust.callable-closure"
            | "srcq.rust.callable-function" => scan.lexical_scopes.push(LexicalScopeCandidate {
                file: record.file,
                range: record.range,
                callable: !record.id.ends_with("scope-block"),
            }),
            _ => {}
        }
    }
    let members = scan
        .bindings
        .iter()
        .filter(|binding| binding.scope == TypeBindingScope::Member)
        .cloned()
        .collect::<Vec<_>>();
    for binding in members {
        let owner = scan
            .type_scopes
            .iter()
            .find(|scope| contains(scope.range, binding.range))
            .map(|scope| scope.type_name.clone());
        let Some(owner) = owner else {
            continue;
        };
        let implementation_ranges = scan
            .type_scopes
            .iter()
            .filter(|scope| scope.type_name == owner && !contains(scope.range, binding.range))
            .map(|scope| scope.range)
            .collect::<Vec<_>>();
        for range in implementation_ranges {
            let mut projected = binding.clone();
            projected.range = range;
            scan.bindings.push(projected);
        }
    }
    Ok(scan)
}

pub(crate) fn containing_function_rules(ast_language: &str, target: &str) -> String {
    generic::containing_function_rules(ast_language, target, &["function_item"])
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    generic::parse_function_owner_stream(bytes, cwd, "rust")
}

fn explicit_or_created_binding(text: &str) -> Option<(String, String)> {
    explicit_binding(text).or_else(|| {
        let text = text.trim().strip_prefix("let ")?.trim_start();
        let (name, initializer) = text.split_once('=')?;
        let name = name.trim().trim_start_matches("mut ").trim();
        let type_name = created_type(initializer)?;
        is_identifier(name).then(|| (name.to_owned(), type_name))
    })
}

fn explicit_binding(text: &str) -> Option<(String, String)> {
    let head = text.split('=').next()?.trim().trim_end_matches(',').trim();
    let head = head.strip_prefix("let ").unwrap_or(head).trim_start();
    let head = head.strip_prefix("mut ").unwrap_or(head).trim_start();
    let (name, type_name) = head.split_once(':')?;
    let name = name.trim();
    let type_name = normalize_type(type_name)?;
    is_identifier(name).then(|| (name.to_owned(), type_name))
}

fn created_type(text: &str) -> Option<String> {
    let text = text.trim().trim_end_matches(';').trim();
    if let Some(open) = text.find('{') {
        return normalize_type(text[..open].trim());
    }
    let callee = text.split_once('(')?.0.trim();
    let (type_name, method) = callee.rsplit_once("::")?;
    (method == "new")
        .then(|| normalize_type(type_name))
        .flatten()
}

fn impl_type(text: &str) -> Option<String> {
    let header = text
        .lines()
        .next()?
        .trim()
        .strip_prefix("impl ")?
        .trim_start();
    normalize_type(
        header
            .split('{')
            .next()?
            .trim()
            .rsplit(" for ")
            .next()?
            .trim(),
    )
}

fn struct_type(text: &str) -> Option<String> {
    let rest = text.trim().strip_prefix("struct ")?.trim_start();
    normalize_type(
        rest.split(|character: char| {
            character.is_whitespace() || matches!(character, '{' | '(' | ';')
        })
        .next()?,
    )
}

fn call_name(text: &str) -> (String, &'static str, Option<String>, Option<String>) {
    let text = text.trim();
    let Some(open) = typed::outer_call_open(text) else {
        return ("<indirect>".to_owned(), "unknown", None, None);
    };
    let callee = text[..open].trim();
    if let Some((receiver, member)) = callee.rsplit_once('.') {
        let receiver = receiver.trim();
        if is_identifier(member) {
            if let Some(type_name) = created_type(receiver) {
                return (
                    format!("{type_name}::{member}"),
                    "typed-member-candidate",
                    Some(receiver.to_owned()),
                    Some(type_name),
                );
            }
        }
        let simple_receiver = is_identifier(receiver)
            || receiver == "self"
            || receiver.strip_prefix("self.").is_some_and(is_identifier);
        if is_identifier(member) && simple_receiver {
            return (
                member.to_owned(),
                "member-candidate",
                Some(receiver.to_owned()),
                None,
            );
        }
        return ("<indirect>".to_owned(), "unknown", None, None);
    }
    if let Some((type_name, method)) = callee.rsplit_once("::") {
        if is_identifier(method) {
            if let Some(type_name) = normalize_type(type_name) {
                return (
                    format!("{type_name}::{method}"),
                    "direct-candidate",
                    None,
                    Some(type_name),
                );
            }
        }
        return ("<indirect>".to_owned(), "unknown", None, None);
    }
    if is_identifier(callee) {
        (callee.to_owned(), "direct-candidate", None, None)
    } else {
        ("<indirect>".to_owned(), "unknown", None, None)
    }
}

fn normalize_type(value: &str) -> Option<String> {
    let mut value = value.trim();
    if let Some(referenced) = value.strip_prefix('&') {
        value = referenced.trim_start();
        if value.starts_with('\'') {
            let end = value.find(char::is_whitespace)?;
            value = value[end..].trim_start();
        }
        value = value.strip_prefix("mut ").unwrap_or(value).trim_start();
    }
    if value.is_empty()
        || value.starts_with("dyn ")
        || value.starts_with("impl ")
        || value.contains(['<', '>', '(', ')', '[', ']', ','])
        || value.split("::").any(|part| !is_identifier(part))
    {
        return None;
    }
    Some(value.to_owned())
}

fn is_identifier(value: &str) -> bool {
    !value.is_empty()
        && !value
            .chars()
            .next()
            .is_some_and(|character| character.is_ascii_digit())
        && value
            .chars()
            .all(|character| character == '_' || character.is_alphanumeric())
}

fn contains(outer: super::cpp::SourceRange, inner: super::cpp::SourceRange) -> bool {
    position_le(outer.start, inner.start) && position_le(inner.end, outer.end)
}

fn position_le(left: super::cpp::SourcePosition, right: super::cpp::SourcePosition) -> bool {
    (left.line, left.column) <= (right.line, right.column)
}
