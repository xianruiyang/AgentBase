use std::collections::BTreeSet;
use std::path::Path;

use super::cpp::{
    CallScan, DirectCallCandidate, FunctionOwnerCandidate, LexicalScopeCandidate,
    NameBindingCandidate, TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::{generic, typed};

pub(crate) fn call_rules(ast_language: &str) -> String {
    typed::kind_rules(
        ast_language,
        "srcq.go",
        &[
            ("call", "call_expression"),
            ("parameter", "parameter_declaration"),
            ("var", "var_spec"),
            ("short-var", "short_var_declaration"),
            ("method", "method_declaration"),
            ("type", "type_declaration"),
            ("block", "block"),
            ("function-literal", "func_literal"),
            ("callable-function", "function_declaration"),
            ("callable-method", "method_declaration"),
        ],
    )
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let mut scan = CallScan::default();
    let mut indirect_names = BTreeSet::new();
    for record in typed::parse_records(bytes, cwd, "Go")? {
        match record.id.as_str() {
            "srcq.go.call" => {
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
            "srcq.go.parameter" | "srcq.go.var" | "srcq.go.short-var" | "srcq.go.method" => {
                if let Some(name) = indirect_binding_name(&record.text) {
                    indirect_names.insert(name);
                }
                let bindings = match record.id.as_str() {
                    "srcq.go.parameter" => explicit_bindings(&record.text),
                    "srcq.go.var" => var_binding(&record.text).into_iter().collect(),
                    "srcq.go.short-var" => short_binding(&record.text).into_iter().collect(),
                    _ => method_receiver(&record.text).into_iter().collect(),
                };
                let binding_scope =
                    if record.id == "srcq.go.parameter" || record.id == "srcq.go.method" {
                        TypeBindingScope::Parameter
                    } else {
                        TypeBindingScope::Local
                    };
                let known_names = bindings
                    .iter()
                    .map(|(name, _)| name.as_str())
                    .collect::<BTreeSet<_>>();
                for name in binding_names(&record.id, &record.text) {
                    if !known_names.contains(name.as_str()) {
                        scan.unresolved_bindings.push(NameBindingCandidate {
                            file: record.file.clone(),
                            range: record.range,
                            name,
                            scope: binding_scope,
                        });
                    }
                }
                for (name, type_name) in bindings {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file.clone(),
                        range: record.range,
                        name,
                        type_name,
                        scope: binding_scope,
                    });
                }
            }
            "srcq.go.type" => {
                if let Some(type_name) = declared_type(&record.text) {
                    scan.type_scopes.push(TypeScopeCandidate {
                        file: record.file,
                        range: record.range,
                        type_name,
                    });
                }
            }
            "srcq.go.block"
            | "srcq.go.function-literal"
            | "srcq.go.callable-function"
            | "srcq.go.callable-method" => scan.lexical_scopes.push(LexicalScopeCandidate {
                file: record.file,
                range: record.range,
                callable: !record.id.ends_with("block"),
            }),
            _ => {}
        }
    }
    for call in &mut scan.calls {
        if call.dispatch == "direct-candidate" && indirect_names.contains(&call.callee) {
            call.callee = "<indirect>".to_owned();
            call.dispatch = "unknown";
        }
    }
    Ok(scan)
}

fn indirect_binding_name(text: &str) -> Option<String> {
    let mut parts = text.split_whitespace();
    let name = parts.next()?;
    let type_name = parts.next()?;
    (typed::is_identifier(name)
        && (type_name.starts_with("func") || type_name.starts_with("interface")))
    .then(|| name.to_owned())
}

fn call_name(text: &str) -> (String, &'static str, Option<String>, Option<String>) {
    let text = text.trim();
    let Some(open) = typed::outer_call_open(text) else {
        return ("<indirect>".to_owned(), "unknown", None, None);
    };
    let callee = text[..open].trim();
    if let Some((receiver, member)) = callee.rsplit_once('.') {
        let (receiver, member) = (receiver.trim(), member.trim());
        if !typed::is_identifier(member) {
            return ("<indirect>".to_owned(), "unknown", None, None);
        }
        if let Some(type_name) = composite_type(receiver) {
            return (
                format!("{type_name}::{member}"),
                "typed-member-candidate",
                Some(receiver.to_owned()),
                Some(type_name),
            );
        }
        if !typed::is_identifier(receiver) {
            return ("<indirect>".to_owned(), "unknown", None, None);
        }
        return (
            member.to_owned(),
            "member-candidate",
            Some(receiver.to_owned()),
            None,
        );
    }
    if typed::is_identifier(callee) {
        (callee.to_owned(), "direct-candidate", None, None)
    } else {
        ("<indirect>".to_owned(), "unknown", None, None)
    }
}

fn binding_names(id: &str, text: &str) -> Vec<String> {
    let names = if id.ends_with("short-var") {
        text.split_once(":=").map(|(names, _)| names)
    } else if id.ends_with("var") {
        text.split_once('=')
            .map_or_else(|| text.split_whitespace().next(), |(names, _)| Some(names))
    } else if id.ends_with("method") {
        text.trim()
            .strip_prefix("func")
            .and_then(|text| text.trim_start().strip_prefix('('))
            .and_then(|text| text.split_once(')').map(|(receiver, _)| receiver))
            .and_then(|receiver| receiver.split_whitespace().next())
    } else {
        text.split_whitespace().next()
    };
    names
        .into_iter()
        .flat_map(|names| names.split(','))
        .map(str::trim)
        .filter(|name| typed::is_identifier(name))
        .map(ToOwned::to_owned)
        .collect()
}

fn declared_type(text: &str) -> Option<String> {
    let name = text
        .trim()
        .strip_prefix("type ")?
        .split_whitespace()
        .next()?;
    typed::is_identifier(name).then(|| name.to_owned())
}

fn explicit_binding(text: &str) -> Option<(String, String)> {
    let mut bindings = explicit_bindings(text);
    (bindings.len() == 1).then(|| bindings.remove(0))
}
fn explicit_bindings(text: &str) -> Vec<(String, String)> {
    let parts = text.split_whitespace().collect::<Vec<_>>();
    let Some(type_name) = parts.last().and_then(|value| normalize_type(value)) else {
        return Vec::new();
    };
    if parts.len() < 2 {
        return Vec::new();
    }
    parts[..parts.len() - 1]
        .join("")
        .split(',')
        .map(str::trim)
        .filter(|name| typed::is_identifier(name))
        .map(|name| (name.to_owned(), type_name.clone()))
        .collect()
}
fn var_binding(text: &str) -> Option<(String, String)> {
    let head = text.split('=').next()?.trim();
    explicit_binding(head).or_else(|| {
        let (name, value) = text.split_once('=')?;
        let name = name.trim();
        let ty = composite_type(value)?;
        typed::is_identifier(name).then(|| (name.to_owned(), ty))
    })
}
fn short_binding(text: &str) -> Option<(String, String)> {
    let (name, value) = text.split_once(":=")?;
    let name = name.trim();
    let ty = composite_type(value)?;
    typed::is_identifier(name).then(|| (name.to_owned(), ty))
}
fn composite_type(text: &str) -> Option<String> {
    let value = text.trim().strip_prefix('&').unwrap_or(text.trim()).trim();
    normalize_type(value.split_once('{')?.0.trim())
}
fn method_receiver(text: &str) -> Option<(String, String)> {
    let rest = text
        .trim()
        .strip_prefix("func")?
        .trim_start()
        .strip_prefix('(')?;
    explicit_binding(rest.split_once(')')?.0.trim())
}

pub(crate) fn method_receiver_type(signature: &str) -> Option<String> {
    method_receiver(signature).map(|(_, type_name)| type_name)
}
fn normalize_type(text: &str) -> Option<String> {
    let text = text.trim().strip_prefix('*').unwrap_or(text.trim()).trim();
    if text.starts_with("interface") || text.starts_with("func") || text.starts_with("...") {
        return None;
    }
    typed::is_type_name(text).then(|| text.replace('.', "::"))
}

pub(crate) fn containing_function_rules(ast_language: &str, target: &str) -> String {
    generic::containing_function_rules(
        ast_language,
        target,
        &["function_declaration", "method_declaration"],
    )
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    generic::parse_function_owner_stream(bytes, cwd, "go")
}
