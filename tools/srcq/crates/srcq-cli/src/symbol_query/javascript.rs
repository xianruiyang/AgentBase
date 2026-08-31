use std::path::Path;

use super::cpp::{
    CallScan, DirectCallCandidate, FunctionOwnerCandidate, LexicalScopeCandidate,
    TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::typed;

pub(crate) fn call_rules(ast_language: &str) -> String {
    typed::kind_rules(
        ast_language,
        "srcq.typed",
        &[
            ("call", "call_expression"),
            ("binding-variable", "variable_declarator"),
            ("binding-field", "field_definition"),
            ("binding-assignment", "assignment_expression"),
            ("scope-class", "class_declaration"),
            ("scope-block", "statement_block"),
            ("callable-arrow", "arrow_function"),
            ("callable-expression", "function_expression"),
            ("callable-function", "function_declaration"),
            ("callable-method", "method_definition"),
        ],
    )
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let mut scan = CallScan::default();
    for record in typed::parse_records(bytes, cwd, "JavaScript")? {
        match record.id.as_str() {
            "srcq.typed.call" => {
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
            "srcq.typed.binding-variable" => {
                if let Some((name, type_name)) = created_binding(&record.text) {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope: TypeBindingScope::Local,
                    });
                }
            }
            "srcq.typed.binding-field" | "srcq.typed.binding-assignment" => {
                let binding = if record.id.ends_with("binding-field") {
                    created_field_binding(&record.text)
                } else {
                    created_member_binding(&record.text)
                };
                if let Some((name, type_name)) = binding {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope: TypeBindingScope::Member,
                    });
                }
            }
            "srcq.typed.scope-class" => {
                if let Some(type_name) = class_name(&record.text) {
                    scan.type_scopes.push(TypeScopeCandidate {
                        file: record.file,
                        range: record.range,
                        type_name,
                    });
                }
            }
            "srcq.typed.scope-block" => scan.lexical_scopes.push(LexicalScopeCandidate {
                file: record.file,
                range: record.range,
                callable: false,
            }),
            "srcq.typed.callable-arrow"
            | "srcq.typed.callable-expression"
            | "srcq.typed.callable-function"
            | "srcq.typed.callable-method" => scan.lexical_scopes.push(LexicalScopeCandidate {
                file: record.file,
                range: record.range,
                callable: true,
            }),
            _ => {}
        }
    }
    Ok(scan)
}

pub(crate) fn containing_function_rules(ast_language: &str, target: &str) -> String {
    let escaped = regex_escape(target.rsplit("::").next().unwrap_or(target));
    [("function", "function_declaration"), ("method", "method_definition"), ("variable", "variable_declarator")].into_iter().map(|(id, kind)| format!("id: srcq.typed.owner.{id}\nlanguage: {ast_language}\nrule:\n  all:\n    - kind: {kind}\n    - has:\n        stopBy: end\n        regex: '^{escaped}$'\nseverity: info\nmessage: typed callable owner candidate")).collect::<Vec<_>>().join("\n---\n")
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    let mut owners = Vec::new();
    for record in typed::parse_records(bytes, cwd, "JavaScript owner")? {
        let Some(name) = owner_name(&record.id, &record.text) else {
            continue;
        };
        owners.push(FunctionOwnerCandidate {
            file: record.file,
            range: record.range,
            name,
            signature: record
                .text
                .lines()
                .next()
                .unwrap_or(&record.text)
                .trim()
                .to_owned(),
            definition: None,
        });
    }
    Ok(owners)
}

fn created_binding(text: &str) -> Option<(String, String)> {
    let (name, value) = text.split_once('=')?;
    let name = name.trim();
    let ty = typed::created_type(value)?;
    typed::is_identifier(name).then(|| (name.to_owned(), ty))
}
fn created_member_binding(text: &str) -> Option<(String, String)> {
    let (name, value) = text.split_once('=')?;
    let name = name.trim().strip_prefix("this.")?;
    let ty = typed::created_type(value)?;
    typed::is_identifier(name).then(|| (name.to_owned(), ty))
}
fn created_field_binding(text: &str) -> Option<(String, String)> {
    let (name, value) = text.split_once('=')?;
    let name = name.trim();
    let ty = typed::created_type(value)?;
    typed::is_identifier(name).then(|| (name.to_owned(), ty))
}
fn class_name(text: &str) -> Option<String> {
    identifier_prefix(text.trim().strip_prefix("class ")?.trim_start())
}
fn owner_name(id: &str, text: &str) -> Option<String> {
    let text = text.trim();
    if id.ends_with("variable") {
        identifier_prefix(text)
    } else if id.ends_with("function") {
        identifier_prefix(text.strip_prefix("function ")?.trim_start())
    } else {
        identifier_prefix(text.split_once('(')?.0.trim())
    }
}
fn call_name(text: &str) -> (String, &'static str, Option<String>, Option<String>) {
    let text = text.trim();
    let Some(open) = typed::outer_call_open(text) else {
        return ("<indirect>".to_owned(), "unknown", None, None);
    };
    let callee = text[..open].trim();
    if let Some((receiver, member)) = callee.rsplit_once('.') {
        let receiver = receiver.trim();
        let member = member.trim();
        if typed::is_identifier(member) {
            if let Some(ty) = typed::created_type(receiver) {
                return (
                    format!("{ty}::{member}"),
                    "typed-member-candidate",
                    Some(receiver.to_owned()),
                    Some(ty),
                );
            }
            if typed::is_identifier(receiver)
                || receiver == "this"
                || receiver
                    .strip_prefix("this.")
                    .is_some_and(typed::is_identifier)
            {
                return (
                    member.to_owned(),
                    "member-candidate",
                    Some(receiver.to_owned()),
                    None,
                );
            }
        }
        return ("<indirect>".to_owned(), "unknown", None, None);
    }
    if typed::is_identifier(callee) {
        (callee.to_owned(), "direct-candidate", None, None)
    } else {
        ("<indirect>".to_owned(), "unknown", None, None)
    }
}
fn identifier_prefix(value: &str) -> Option<String> {
    let name = value
        .chars()
        .take_while(|c| *c == '_' || *c == '$' || c.is_alphanumeric())
        .collect::<String>();
    (!name.is_empty()).then_some(name)
}
fn regex_escape(value: &str) -> String {
    let mut out = String::new();
    for c in value.chars() {
        if matches!(
            c,
            '\\' | '.' | '^' | '$' | '|' | '?' | '*' | '+' | '(' | ')' | '[' | ']' | '{' | '}'
        ) {
            out.push('\\');
        }
        out.push(c);
    }
    out.replace('\'', "''")
}
