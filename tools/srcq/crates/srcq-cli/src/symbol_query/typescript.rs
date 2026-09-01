use super::cpp::{
    CallScan, DirectCallCandidate, FunctionOwnerCandidate, LexicalScopeCandidate,
    TypeBindingCandidate, TypeBindingScope, TypeScopeCandidate,
};
use super::typed;
use std::path::Path;

pub(crate) fn call_rules(ast_language: &str) -> String {
    typed::kind_rules(
        ast_language,
        "srcq.typed",
        &[
            ("call", "call_expression"),
            ("parameter", "required_parameter"),
            ("parameter-optional", "optional_parameter"),
            ("binding-variable", "variable_declarator"),
            ("binding-field", "public_field_definition"),
            ("scope-class", "class_declaration"),
            ("scope-block", "statement_block"),
            ("callable-arrow", "arrow_function"),
            ("callable-expression", "function_expression"),
            ("callable-function", "function_declaration"),
            ("callable-method", "method_definition"),
        ],
    )
}

pub(crate) fn containing_function_rules(ast_language: &str, target: &str) -> String {
    typed::ecmascript_containing_function_rules(ast_language, target)
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
) -> Result<Vec<FunctionOwnerCandidate>, String> {
    typed::parse_ecmascript_function_owner_stream(bytes, cwd, "TypeScript", true)
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<CallScan, String> {
    let mut scan = CallScan::default();
    for record in typed::parse_records(bytes, cwd, "TypeScript")? {
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
            "srcq.typed.parameter" | "srcq.typed.parameter-optional" => {
                if let Some((name, type_name)) = explicit_binding(&record.text, false) {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope: TypeBindingScope::Parameter,
                    });
                }
            }
            "srcq.typed.binding-variable" | "srcq.typed.binding-field" => {
                let member = record.id.ends_with("field");
                if let Some((name, type_name)) = explicit_or_created_binding(&record.text, member) {
                    scan.bindings.push(TypeBindingCandidate {
                        file: record.file,
                        range: record.range,
                        name,
                        type_name,
                        scope: if record.id.ends_with("field") {
                            TypeBindingScope::Member
                        } else {
                            TypeBindingScope::Local
                        },
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

fn explicit_or_created_binding(text: &str, member: bool) -> Option<(String, String)> {
    explicit_binding(text, member).or_else(|| {
        let (name, initializer) = text.split_once('=')?;
        let name = binding_name(name, member)?;
        let type_name = typed::created_type(initializer)?;
        Some((name, type_name))
    })
}
fn explicit_binding(text: &str, member: bool) -> Option<(String, String)> {
    let head = text.split('=').next()?.trim();
    let (name, type_name) = head.split_once(':')?;
    let name = binding_name(name, member)?;
    let type_name = type_name.trim();
    typed::is_type_name(type_name).then(|| (name, type_name.to_owned()))
}
fn binding_name(value: &str, member: bool) -> Option<String> {
    let value = value.trim().trim_end_matches(['?', '!']).trim();
    if member {
        typed::ecmascript_member_declaration_name(value)
    } else {
        typed::is_identifier(value).then(|| value.to_owned())
    }
}
fn class_name(text: &str) -> Option<String> {
    identifier_prefix(text.trim().strip_prefix("class ")?.trim_start())
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
        if typed::is_ecmascript_identifier(member) {
            if let Some(receiver_type) = typed::created_type(receiver) {
                return (
                    format!("{receiver_type}::{member}"),
                    "typed-member-candidate",
                    Some(receiver.to_owned()),
                    Some(receiver_type),
                );
            }
            if simple_receiver(receiver) {
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
fn simple_receiver(value: &str) -> bool {
    typed::is_identifier(value)
        || value == "this"
        || value
            .strip_prefix("this.")
            .is_some_and(typed::is_ecmascript_identifier)
}
