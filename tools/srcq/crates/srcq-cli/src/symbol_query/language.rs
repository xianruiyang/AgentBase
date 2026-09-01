use std::path::Path;

use serde_json::json;

use srcq_core::invocation::OutputFormat;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct LanguageCapability {
    pub(crate) key: &'static str,
    pub(crate) ast_grep: &'static str,
    pub(crate) definition: &'static str,
    pub(crate) references: &'static str,
    pub(crate) calls: &'static str,
    pub(crate) scope: &'static str,
}

const CPP: LanguageCapability = LanguageCapability {
    key: "cpp",
    ast_grep: "Cpp",
    definition: "syntax-direct",
    references: "lexical-candidate",
    calls: "candidate",
    scope: "compile-aware",
};

const UNADAPTED: &[(&str, &str)] = &[
    ("bash", "Bash"),
    ("c", "C"),
    ("csharp", "CSharp"),
    ("dart", "Dart"),
    ("elixir", "Elixir"),
    ("go", "Go"),
    ("haskell", "Haskell"),
    ("java", "Java"),
    ("javascript", "JavaScript"),
    ("kotlin", "Kotlin"),
    ("lua", "Lua"),
    ("nix", "Nix"),
    ("php", "Php"),
    ("python", "Python"),
    ("ruby", "Ruby"),
    ("rust", "Rust"),
    ("scala", "Scala"),
    ("solidity", "Solidity"),
    ("swift", "Swift"),
    ("tsx", "Tsx"),
    ("typescript", "TypeScript"),
];

const NOT_APPLICABLE: &[(&str, &str)] = &[
    ("css", "Css"),
    ("html", "Html"),
    ("json", "Json"),
    ("yaml", "Yaml"),
];

fn has_generic_relation_adapter(key: &str) -> bool {
    matches!(
        key,
        "c" | "csharp" | "go" | "java" | "javascript" | "python" | "rust" | "tsx" | "typescript"
    )
}

fn has_outline_adapter(key: &str) -> bool {
    has_generic_relation_adapter(key)
        || matches!(key, "c" | "csharp" | "kotlin" | "php" | "ruby" | "swift")
}

fn code_capability(key: &'static str, ast_grep: &'static str) -> LanguageCapability {
    let adapted = has_generic_relation_adapter(key);
    LanguageCapability {
        key,
        ast_grep,
        definition: if has_outline_adapter(key) {
            "candidate-only"
        } else {
            "unadapted"
        },
        references: if adapted {
            "lexical-candidate"
        } else {
            "unadapted"
        },
        calls: if adapted { "candidate" } else { "unadapted" },
        scope: if key == "csharp" {
            "project-compile-aware"
        } else if matches!(
            key,
            "go" | "javascript" | "python" | "rust" | "tsx" | "typescript"
        ) {
            "project-metadata-aware"
        } else {
            "explicit-or-project"
        },
    }
}

pub(crate) fn find(key: &str) -> Option<LanguageCapability> {
    if key == CPP.key {
        return Some(CPP);
    }
    UNADAPTED
        .iter()
        .find(|(candidate, _)| *candidate == key)
        .map(|(key, ast_grep)| code_capability(key, ast_grep))
        .or_else(|| {
            NOT_APPLICABLE
                .iter()
                .find(|(candidate, _)| *candidate == key)
                .map(|(key, ast_grep)| LanguageCapability {
                    key,
                    ast_grep,
                    definition: "not-applicable",
                    references: "not-applicable",
                    calls: "not-applicable",
                    scope: "explicit-or-project",
                })
        })
}

pub(crate) fn all() -> Vec<LanguageCapability> {
    let mut capabilities = vec![CPP];
    capabilities.extend(
        UNADAPTED
            .iter()
            .map(|(key, ast_grep)| code_capability(key, ast_grep)),
    );
    capabilities.extend(
        NOT_APPLICABLE
            .iter()
            .map(|(key, ast_grep)| LanguageCapability {
                key,
                ast_grep,
                definition: "not-applicable",
                references: "not-applicable",
                calls: "not-applicable",
                scope: "explicit-or-project",
            }),
    );
    capabilities.sort_by_key(|capability| capability.key);
    capabilities
}

pub(crate) fn source_glob(key: &str) -> Option<&'static str> {
    match key {
        "bash" => Some("*.{sh,bash}"),
        "c" => Some("*.{c,h}"),
        "cpp" => Some("*.{c,cc,cpp,cxx,h,hh,hpp,hxx,inl,ipp,ixx,m,mm}"),
        "csharp" => Some("*.cs"),
        "dart" => Some("*.dart"),
        "elixir" => Some("*.{ex,exs}"),
        "go" => Some("*.go"),
        "haskell" => Some("*.{hs,lhs}"),
        "java" => Some("*.java"),
        "javascript" => Some("*.{js,mjs,cjs}"),
        "kotlin" => Some("*.{kt,kts}"),
        "lua" => Some("*.lua"),
        "nix" => Some("*.nix"),
        "php" => Some("*.php"),
        "python" => Some("*.py"),
        "ruby" => Some("*.rb"),
        "rust" => Some("*.rs"),
        "scala" => Some("*.{scala,sc}"),
        "solidity" => Some("*.sol"),
        "swift" => Some("*.swift"),
        "tsx" => Some("*.tsx"),
        "typescript" => Some("*.{ts,mts,cts}"),
        _ => None,
    }
}

pub(crate) fn requires_explicit_parse(key: &str, path: &Path) -> bool {
    if key != "cpp" {
        return false;
    }
    path.extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| {
            matches!(
                extension.to_ascii_lowercase().as_str(),
                "h" | "hh" | "hpp" | "hxx" | "inl" | "ipp" | "ixx"
            )
        })
}

pub(crate) fn normalize_query_target(key: &str, target: String) -> String {
    if key == "csharp" {
        target.replace('.', "::")
    } else {
        target
    }
}

pub(crate) fn occurrence_kinds(key: &str) -> Option<&'static [&'static str]> {
    match key {
        "c" => Some(&["identifier"]),
        "csharp" => Some(&["identifier"]),
        "python" => Some(&["identifier"]),
        "typescript" | "tsx" => Some(&[
            "identifier",
            "property_identifier",
            "type_identifier",
            "shorthand_property_identifier_pattern",
        ]),
        "javascript" => Some(&[
            "identifier",
            "property_identifier",
            "shorthand_property_identifier_pattern",
        ]),
        "rust" => Some(&["identifier", "field_identifier", "type_identifier"]),
        "go" => Some(&[
            "identifier",
            "field_identifier",
            "type_identifier",
            "package_identifier",
        ]),
        "java" => Some(&["identifier", "type_identifier"]),
        _ => None,
    }
}

pub(crate) fn call_kinds(key: &str) -> Option<&'static [&'static str]> {
    match key {
        "c" => Some(&["call_expression"]),
        "csharp" => Some(&["invocation_expression", "object_creation_expression"]),
        "python" => Some(&["call"]),
        "typescript" | "tsx" | "javascript" | "rust" | "go" => Some(&["call_expression"]),
        "java" => Some(&["method_invocation", "object_creation_expression"]),
        _ => None,
    }
}

pub(crate) fn function_kinds(key: &str) -> Option<&'static [&'static str]> {
    match key {
        "c" => Some(&["function_definition"]),
        "csharp" => Some(&["method_declaration", "constructor_declaration"]),
        "python" => Some(&["function_definition"]),
        "typescript" | "tsx" | "javascript" => Some(&[
            "function_declaration",
            "method_definition",
            "generator_function_declaration",
        ]),
        "rust" => Some(&["function_item"]),
        "go" => Some(&["function_declaration", "method_declaration"]),
        "java" => Some(&["method_declaration", "constructor_declaration"]),
        _ => None,
    }
}

pub(crate) fn render(output: OutputFormat) -> Vec<u8> {
    let capabilities = all();
    if output == OutputFormat::Machine {
        let document = json!({
            "schema": "srcq.symbol.capabilities/v1",
            "languages": capabilities.iter().map(|capability| json!({
                "language": capability.key,
                "ast_grep": capability.ast_grep,
                "definition": capability.definition,
                "references": capability.references,
                "calls": capability.calls,
                "scope": capability.scope,
            })).collect::<Vec<_>>(),
            "evidence_boundary": "registered capability; syntax candidates are not semantic-exact",
        });
        let mut bytes = serde_json::to_vec(&document).expect("capability JSON is serializable");
        bytes.push(b'\n');
        return bytes;
    }
    let mut text = String::from("language definition references calls scope\n");
    for capability in capabilities {
        text.push_str(&format!(
            "{} {} {} {} {}\n",
            capability.key,
            capability.definition,
            capability.references,
            capability.calls,
            capability.scope
        ));
    }
    text.into_bytes()
}

#[cfg(test)]
mod tests {
    use super::requires_explicit_parse;
    use std::path::Path;

    #[test]
    fn explicit_parse_routing_is_owned_by_the_language_registry() {
        assert!(requires_explicit_parse("cpp", Path::new("worker.h")));
        assert!(requires_explicit_parse("cpp", Path::new("worker.IPP")));
        assert!(!requires_explicit_parse("cpp", Path::new("worker.cpp")));
        assert!(!requires_explicit_parse("c", Path::new("worker.h")));
    }
}
