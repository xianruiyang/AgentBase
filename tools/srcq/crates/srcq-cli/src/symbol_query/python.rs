use std::path::Path;

use super::cpp::{
    CallScan, DirectCallCandidate, FunctionOwnerCandidate, LexicalScopeCandidate,
    TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::scope::normalized_key;
use super::{generic, typed};

pub(crate) fn call_rules(ast_language: &str) -> String {
    typed::kind_rules(
        ast_language,
        "srcq.python",
        &[
            ("call", "call"),
            ("binding.parameter", "typed_parameter"),
            ("binding.default-parameter", "typed_default_parameter"),
            ("binding.assignment", "assignment"),
            ("scope.class", "class_definition"),
            ("scope.function", "function_definition"),
            ("scope.lambda", "lambda"),
            ("lexical.block", "block"),
        ],
    )
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let mut scan = CallScan::default();
    for record in typed::parse_records(bytes, cwd, "Python")? {
        match record.id.as_str() {
            "srcq.python.call" => {
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
            "srcq.python.binding.parameter" | "srcq.python.binding.default-parameter" => {
                if let Some((name, type_name)) = annotated_binding(&record.text) {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope: TypeBindingScope::Parameter,
                    });
                }
            }
            "srcq.python.binding.assignment" => {
                if let Some((name, type_name, member)) = assignment_binding(&record.text) {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope: if member {
                            TypeBindingScope::Member
                        } else {
                            TypeBindingScope::Local
                        },
                    });
                }
            }
            "srcq.python.scope.class" => {
                if let Some(type_name) = class_name(&record.text) {
                    scan.type_scopes.push(TypeScopeCandidate {
                        file: record.file,
                        range: record.range,
                        type_name,
                    });
                }
            }
            "srcq.python.scope.function" | "srcq.python.scope.lambda" => {
                scan.lexical_scopes.push(LexicalScopeCandidate {
                    file: record.file,
                    range: record.range,
                    callable: true,
                })
            }
            "srcq.python.lexical.block" => scan.lexical_scopes.push(LexicalScopeCandidate {
                file: record.file,
                range: record.range,
                callable: false,
            }),
            _ => {}
        }
    }
    scan.calls.sort_by_key(|call| {
        (
            normalized_key(&call.file),
            call.range.start.line,
            call.range.start.column,
        )
    });
    scan.calls.dedup_by(|a, b| {
        normalized_key(&a.file) == normalized_key(&b.file)
            && a.range == b.range
            && a.callee == b.callee
    });
    scan.bindings.sort_by_key(|binding| {
        (
            normalized_key(&binding.file),
            binding.range.start.line,
            binding.range.start.column,
            binding.name.clone(),
        )
    });
    scan.bindings.dedup();
    scan.type_scopes.dedup();
    scan.lexical_scopes.dedup();
    Ok(scan)
}

pub(crate) fn containing_function_rules(ast_language: &str, target: &str) -> String {
    generic::containing_function_rules(
        ast_language,
        target,
        &["function_definition", "assignment", "lambda"],
    )
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    let mut owners = Vec::new();
    for record in typed::parse_records(bytes, cwd, "Python")? {
        let text = record.text.trim();
        let name = if let Some(rest) = text.strip_prefix("def ") {
            rest.chars()
                .take_while(|character| *character == '_' || character.is_alphanumeric())
                .collect::<String>()
        } else if let Some((left, right)) = text.split_once('=') {
            let left = left.trim();
            if right.trim_start().starts_with("lambda") && typed::is_identifier(left) {
                left.to_owned()
            } else {
                String::new()
            }
        } else {
            String::new()
        };
        if name.is_empty() {
            continue;
        }
        let signature = text.lines().next().unwrap_or(text).trim().to_owned();
        owners.push(FunctionOwnerCandidate {
            file: record.file,
            range: record.range,
            name,
            signature,
            definition: None,
        });
    }
    Ok(owners)
}

fn call_name(text: &str) -> (String, &'static str, Option<String>, Option<String>) {
    let text = text.trim();
    let Some(open) = typed::outer_call_open(text) else {
        return unknown_call();
    };
    let callee = text[..open].trim();
    if let Some((receiver, member)) = callee.rsplit_once('.') {
        if typed::is_identifier(member) && !receiver.is_empty() {
            if let Some(type_name) = constructed_type(receiver) {
                return (
                    format!("{type_name}::{member}"),
                    "typed-member-candidate",
                    Some(receiver.to_owned()),
                    Some(type_name),
                );
            }
            return (
                member.to_owned(),
                "member-candidate",
                Some(receiver.to_owned()),
                None,
            );
        }
        return unknown_call();
    }
    if typed::is_identifier(callee) {
        (callee.to_owned(), "direct-candidate", None, None)
    } else {
        unknown_call()
    }
}

fn unknown_call() -> (String, &'static str, Option<String>, Option<String>) {
    ("<indirect>".to_owned(), "unknown", None, None)
}

fn annotated_binding(text: &str) -> Option<(String, String)> {
    let head = text.split('=').next()?.trim();
    let (name, annotation) = head.split_once(':')?;
    let name = name.trim().trim_start_matches("self.");
    let type_name = simple_type(annotation)?;
    typed::is_identifier(name).then(|| (name.to_owned(), type_name))
}

fn assignment_binding(text: &str) -> Option<(String, String, bool)> {
    let (left, right) = text.split_once('=')?;
    let left = left.trim();
    let (name, annotation) = left
        .split_once(':')
        .map_or((left, None), |(name, annotation)| {
            (name.trim(), Some(annotation))
        });
    let member = name.starts_with("self.");
    let name = name.strip_prefix("self.").unwrap_or(name);
    if !typed::is_identifier(name) {
        return None;
    }
    let type_name = annotation
        .and_then(simple_type)
        .or_else(|| constructed_type(right.trim()))?;
    Some((name.to_owned(), type_name, member))
}

fn constructed_type(value: &str) -> Option<String> {
    let type_name = value.trim().split_once('(')?.0.trim();
    typed::is_type_name(type_name).then(|| type_name.to_owned())
}

fn simple_type(value: &str) -> Option<String> {
    let value = value.trim();
    typed::is_type_name(value).then(|| value.to_owned())
}

fn class_name(text: &str) -> Option<String> {
    let rest = text.trim_start().strip_prefix("class ")?;
    let name = rest
        .chars()
        .take_while(|character| *character == '_' || character.is_alphanumeric())
        .collect::<String>();
    (!name.is_empty()).then_some(name)
}
