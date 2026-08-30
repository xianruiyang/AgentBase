use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use serde_json::Value;

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root")
        .to_path_buf()
}

fn fixture_source() -> PathBuf {
    workspace_root().join("tests/fixtures/symbol/source")
}

fn multilang_source() -> PathBuf {
    workspace_root().join("tests/fixtures/symbol/multilang")
}

fn run(arguments: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_srcq"))
        .current_dir(workspace_root())
        .args(arguments)
        .output()
        .expect("srcq symbol definition")
}

#[test]
fn cpp_definition_distinguishes_definitions_calls_declarations_and_lexical_owners() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");

    let duplicate = run(&[
        "symbol",
        "definition",
        "BuildTool",
        "--only-root",
        root,
        "--body",
        "none",
    ]);
    assert!(duplicate.status.success());
    let duplicate = String::from_utf8(duplicate.stdout).expect("UTF-8 model output");
    assert!(duplicate.starts_with("definition-candidates 2\n"));
    assert!(duplicate.contains("function Other::BuildTool"));
    assert!(!duplicate.contains("CanBuildTool"));

    let call_owner = run(&[
        "symbol",
        "definition",
        "CanBuildTool",
        "--only-root",
        root,
        "--body",
        "auto",
    ]);
    assert!(call_owner.status.success());
    let call_owner = String::from_utf8(call_owner.stdout).expect("UTF-8 model output");
    assert!(call_owner.starts_with("definition-candidate function CanBuildTool"));
    assert!(call_owner.contains("return BuildTool(1);"));

    let field = run(&[
        "symbol",
        "definition",
        "Value",
        "--only-root",
        root,
        "--body",
        "none",
    ]);
    assert!(field.status.success());
    assert!(String::from_utf8(field.stdout)
        .expect("UTF-8 field output")
        .contains("field Widget::Value"));

    let declaration = run(&[
        "symbol",
        "definition",
        "DeclaredOnly",
        "--only-root",
        root,
        "--body",
        "none",
    ]);
    assert_eq!(declaration.status.code(), Some(1));
    let declaration = String::from_utf8(declaration.stdout).expect("UTF-8 declaration output");
    assert!(declaration.starts_with("definition-candidate none\n"));
    assert!(declaration.contains("declarations 1\n"));

    let direct_initialized = run(&[
        "symbol",
        "definition",
        "DirectWidget",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(direct_initialized.status.success());
    let direct_initialized: Value =
        serde_json::from_slice(&direct_initialized.stdout).expect("direct-init JSON");
    assert_eq!(direct_initialized["definition_total"], 1);
    assert_eq!(direct_initialized["declaration_total"], 0);
    assert_eq!(
        direct_initialized["definitions"][0]["symbol_kind"],
        "variable"
    );
}

#[test]
fn cpp_definition_position_input_machine_schema_and_missing_result_are_stable() {
    let root = fixture_source();
    let root_text = root.to_str().expect("UTF-8 fixture path");
    let source = root.join("definitions.cpp");
    let at = format!("{}:18:7", source.display());
    let positioned = run(&[
        "symbol",
        "definition",
        "--at",
        &at,
        "--only-root",
        root_text,
        "--body",
        "none",
    ]);
    assert!(positioned.status.success());
    assert!(String::from_utf8(positioned.stdout)
        .expect("UTF-8 position output")
        .starts_with("definition-candidate function BuildTool"));

    let qualified_call_at = format!("{}:53:18", source.display());
    let qualified_call = run(&[
        "symbol",
        "definition",
        "--at",
        &qualified_call_at,
        "--only-root",
        root_text,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(qualified_call.status.success());
    let qualified_call: Value =
        serde_json::from_slice(&qualified_call.stdout).expect("qualified-call JSON");
    assert_eq!(qualified_call["query"]["target"], "Other::BuildTool");
    assert_eq!(qualified_call["definition_total"], 1);
    assert_eq!(
        qualified_call["definitions"][0]["qualified_name"],
        "Other::BuildTool"
    );

    let machine = run(&[
        "symbol",
        "definition",
        "First",
        "--only-root",
        root_text,
        "--output",
        "machine",
    ]);
    assert!(machine.status.success());
    let machine: Value = serde_json::from_slice(&machine.stdout).expect("machine JSON");
    assert_eq!(machine["schema"], "srcq.symbol.definition/v1");
    assert_eq!(machine["definition_total"], 1);
    assert_eq!(machine["definitions"][0]["qualified_name"], "Mode::First");
    assert_eq!(machine["scope"]["status"], "bounded");
    assert_eq!(machine["candidate_scan"], "complete");
    assert_eq!(machine["evidence"], "syntax-direct");

    let missing = run(&[
        "symbol",
        "definition",
        "DefinitelyMissing",
        "--only-root",
        root_text,
    ]);
    assert_eq!(missing.status.code(), Some(1));
    assert!(String::from_utf8(missing.stdout)
        .expect("UTF-8 missing output")
        .starts_with("definition-candidate none\n"));
}

#[test]
fn cpp_references_exclude_definition_sites_and_keep_identity_and_access_roles() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");
    let ambiguous = run(&["symbol", "references", "BuildTool", "--only-root", root]);
    assert!(ambiguous.status.success());
    let ambiguous = String::from_utf8(ambiguous.stdout).expect("UTF-8 references");
    assert!(ambiguous.starts_with("references 2 identity=ambiguous evidence=lexical-candidate\n"));
    assert!(ambiguous.contains("26:12 call"));
    assert!(ambiguous.contains("54:19 call"));
    assert!(!ambiguous.contains("19:5"));
    assert!(!ambiguous.contains("46:5"));

    let qualified = run(&[
        "symbol",
        "references",
        "Other::BuildTool",
        "--only-root",
        root,
        "--output",
        "machine",
    ]);
    assert!(qualified.status.success());
    let qualified: Value = serde_json::from_slice(&qualified.stdout).expect("machine JSON");
    assert_eq!(qualified["schema"], "srcq.symbol.references/v1");
    assert_eq!(qualified["identity"], "qualified-candidate");
    assert_eq!(qualified["definition_total"], 1);
    assert_eq!(qualified["reference_total"], 1);
    assert_eq!(qualified["references"][0]["role"], "call");

    let variable = run(&["symbol", "references", "GlobalValue", "--only-root", root]);
    assert!(variable.status.success());
    let variable = String::from_utf8(variable.stdout).expect("UTF-8 variable references");
    assert!(variable.contains("21:20 reference"));
    assert!(variable.contains("31:5 write"));
}

#[test]
fn cpp_outgoing_calls_expand_unique_nodes_and_stop_on_cycles_and_ambiguity() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");
    let tree = run(&[
        "symbol",
        "calls",
        "Wrapper",
        "--only-root",
        root,
        "--depth",
        "2",
    ]);
    assert!(tree.status.success());
    let tree = String::from_utf8(tree.stdout).expect("UTF-8 call tree");
    assert!(tree.starts_with("calls outgoing depth=2 nodes=3 evidence=qualified-candidate\n"));
    assert!(tree.contains("CanBuildTool [qualified-candidate;direct-candidate]"));
    assert!(tree.contains("BuildTool [direct-candidate]"));

    let shared_file = run(&[
        "symbol",
        "calls",
        "CallSameFileLeaves",
        "--only-root",
        root,
        "--depth",
        "1",
    ]);
    assert!(shared_file.status.success());
    let shared_file = String::from_utf8(shared_file.stdout).expect("UTF-8 shared-file tree");
    assert_eq!(
        shared_file
            .lines()
            .filter(|line| line.contains("definitions.cpp"))
            .count(),
        1,
        "the model view should render a shared sibling path once"
    );
    assert!(shared_file.contains("FirstSameFileLeaf [direct-candidate] :"));
    assert!(shared_file.contains("SecondSameFileLeaf [direct-candidate] :"));

    let cross_file = run(&[
        "symbol",
        "calls",
        "CrossFileTarget",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "1",
    ]);
    assert!(cross_file.status.success());
    let cross_file = String::from_utf8(cross_file.stdout).expect("UTF-8 cross-file tree");
    assert_eq!(
        cross_file
            .lines()
            .filter(|line| line.contains("callers.cpp"))
            .count(),
        1,
        "a sibling path that differs from the parent should still render once"
    );
    assert!(cross_file.contains("FirstCrossFileCaller [lexical-candidate;incoming-candidate]"));
    assert!(cross_file.contains("SecondCrossFileCaller [lexical-candidate;incoming-candidate] :"));

    let cross_file_machine = run(&[
        "symbol",
        "calls",
        "CrossFileTarget",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "1",
        "--output",
        "machine",
    ]);
    assert!(cross_file_machine.status.success());
    let cross_file_machine: Value =
        serde_json::from_slice(&cross_file_machine.stdout).expect("machine cross-file tree");
    let machine_children = cross_file_machine["root"]["children"]
        .as_array()
        .expect("machine cross-file children");
    assert_eq!(machine_children.len(), 2);
    assert!(machine_children.iter().all(|child| child["call"]["path"]
        .as_str()
        .is_some_and(|path| path.ends_with("callers.cpp"))));

    let repeated_owner = run(&[
        "symbol",
        "calls",
        "SharedIncomingLeaf",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "2",
        "--output",
        "machine",
    ]);
    assert!(repeated_owner.status.success());
    let repeated_owner: Value =
        serde_json::from_slice(&repeated_owner.stdout).expect("repeated owner machine tree");
    let owner = &repeated_owner["root"]["children"][0];
    assert_eq!(owner["status"], "qualified-candidate");
    assert_eq!(owner["name"], "RepeatedIncomingOwner");
    assert_eq!(
        owner["definition"]["qualified_name"],
        "RepeatedIncomingOwner"
    );
    assert_eq!(owner["children"][0]["name"], "SharedIncomingTop");

    let cycle = run(&[
        "symbol",
        "calls",
        "Recursive",
        "--only-root",
        root,
        "--depth",
        "3",
        "--output",
        "machine",
    ]);
    assert!(cycle.status.success());
    let cycle: Value = serde_json::from_slice(&cycle.stdout).expect("machine call tree");
    assert_eq!(cycle["schema"], "srcq.symbol.calls/v1");
    assert_eq!(cycle["root"]["children"][0]["status"], "cycle");

    let ambiguous = run(&["symbol", "calls", "BuildTool", "--only-root", root]);
    assert_eq!(ambiguous.status.code(), Some(1));
    assert!(String::from_utf8(ambiguous.stdout)
        .expect("UTF-8 ambiguity output")
        .starts_with("calls unavailable target=BuildTool identity=ambiguous definitions=2\n"));
}

#[test]
fn cpp_incoming_calls_find_callers_and_stop_on_cycles() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");
    let tree = run(&[
        "symbol",
        "calls",
        "CanBuildTool",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "2",
    ]);
    assert!(tree.status.success());
    let tree = String::from_utf8(tree.stdout).expect("UTF-8 incoming call tree");
    assert!(tree.starts_with("calls incoming depth=2 nodes=2 evidence=lexical-candidate\n"));
    assert!(tree.contains("Wrapper [qualified-candidate;incoming-candidate]"));

    let cycle = run(&[
        "symbol",
        "calls",
        "Recursive",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "3",
        "--output",
        "machine",
    ]);
    assert!(cycle.status.success());
    let cycle: Value = serde_json::from_slice(&cycle.stdout).expect("machine incoming tree");
    assert_eq!(cycle["schema"], "srcq.symbol.calls/v1");
    assert_eq!(cycle["query"]["direction"], "incoming");
    assert_eq!(cycle["root"]["children"][0]["status"], "cycle");

    let qualified = run(&[
        "symbol",
        "calls",
        "Other::BuildTool",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "2",
    ]);
    assert!(qualified.status.success());
    assert!(String::from_utf8(qualified.stdout)
        .expect("UTF-8 qualified incoming tree")
        .contains("CallOtherBuildTool [qualified-candidate;incoming-candidate]"));

    let virtual_dispatch = run(&[
        "symbol",
        "calls",
        "RunVirtual",
        "--only-root",
        root,
        "--direction",
        "incoming",
    ]);
    assert!(virtual_dispatch.status.success());
    let virtual_dispatch =
        String::from_utf8(virtual_dispatch.stdout).expect("UTF-8 virtual incoming tree");
    assert!(virtual_dispatch.contains("dynamic callers [semantic-unknown:virtual-dispatch]"));
}

#[test]
fn cpp_nested_namespace_call_trees_match_the_exact_bounded_source_oracle() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");

    let outgoing = run(&[
        "symbol",
        "calls",
        "NestedMiddle",
        "--only-root",
        root,
        "--depth",
        "1",
        "--output",
        "machine",
    ]);
    assert!(outgoing.status.success());
    let outgoing: Value = serde_json::from_slice(&outgoing.stdout).expect("outgoing JSON");
    assert_eq!(outgoing["scope"]["candidate_scan"], "complete");
    assert_eq!(outgoing["nodes"], 2);
    assert_eq!(outgoing["truncated"], false);
    assert_eq!(outgoing["time_limited"], false);
    assert_eq!(
        outgoing["root"]["definition"]["qualified_name"],
        "Alpha::Beta::Gamma::NestedMiddle"
    );
    let outgoing_children = outgoing["root"]["children"]
        .as_array()
        .expect("outgoing children");
    assert_eq!(outgoing_children.len(), 1);
    assert_eq!(outgoing_children[0]["name"], "NestedLeaf");
    assert_eq!(outgoing_children[0]["dispatch"], "direct-candidate");

    let incoming = run(&[
        "symbol",
        "calls",
        "NestedMiddle",
        "--only-root",
        root,
        "--direction",
        "incoming",
        "--depth",
        "1",
        "--output",
        "machine",
    ]);
    assert!(incoming.status.success());
    let incoming: Value = serde_json::from_slice(&incoming.stdout).expect("incoming JSON");
    assert_eq!(incoming["scope"]["candidate_scan"], "complete");
    assert_eq!(incoming["nodes"], 2);
    assert_eq!(incoming["truncated"], false);
    assert_eq!(incoming["time_limited"], false);
    assert_eq!(
        incoming["root"]["definition"]["qualified_name"],
        "Alpha::Beta::Gamma::NestedMiddle"
    );
    let incoming_children = incoming["root"]["children"]
        .as_array()
        .expect("incoming children");
    assert_eq!(incoming_children.len(), 1);
    assert_eq!(incoming_children[0]["name"], "NestedTop");
    assert_eq!(incoming_children[0]["dispatch"], "incoming-candidate");
}

#[test]
fn cpp_explicit_receiver_types_add_owner_and_variable_context_without_claiming_lsp_precision() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");

    let calls = run(&[
        "symbol",
        "calls",
        "UseFixtureWorker",
        "--only-root",
        root,
        "--depth",
        "2",
        "--output",
        "machine",
    ]);
    assert!(calls.status.success());
    let calls: Value = serde_json::from_slice(&calls.stdout).expect("typed call JSON");
    assert_eq!(calls["scope"]["candidate_scan"], "complete");
    assert_eq!(calls["nodes"], 2);
    let children = calls["root"]["children"]
        .as_array()
        .expect("typed member children");
    assert_eq!(children.len(), 1);
    assert_eq!(children[0]["name"], "FixtureWorker::Tick");
    assert_eq!(children[0]["dispatch"], "typed-member-candidate");
    assert_eq!(children[0]["status"], "qualified-candidate");
    assert_eq!(children[0]["receiver"], "Worker");
    assert_eq!(children[0]["receiver_type"], "FixtureWorker");
    assert_eq!(
        children[0]["definition"]["qualified_name"],
        "FixtureWorker::Tick"
    );

    let symbols = [("FixtureWorker", "type"), ("Worker", "variable")];
    for (symbol, kind) in symbols {
        let definition = run(&[
            "symbol",
            "definition",
            symbol,
            "--only-root",
            root,
            "--body",
            "none",
            "--output",
            "machine",
        ]);
        assert!(definition.status.success(), "definition for {symbol}");
        let definition: Value =
            serde_json::from_slice(&definition.stdout).expect("symbol definition JSON");
        assert_eq!(definition["definition_total"], 1);
        assert_eq!(definition["definitions"][0]["symbol_kind"], kind);
    }
}

#[test]
fn outline_definition_adapters_cover_representative_language_mechanisms() {
    let root = multilang_source();
    let cases = [
        ("python", "execute", "sample.py", "method"),
        ("typescript", "value", "sample.ts", "field"),
        ("rust", "rust_wrapper", "sample.rs", "function"),
        ("go", "Value", "sample.go", "field"),
        ("java", "execute", "Sample.java", "method"),
        ("javascript", "execute", "sample.js", "method"),
        ("tsx", "execute", "sample.tsx", "method"),
    ];
    for (language, target, file, kind) in cases {
        let path = root.join(file);
        let path = path.to_str().expect("UTF-8 fixture path");
        let output = run(&[
            "symbol",
            "definition",
            target,
            "--language",
            language,
            "--only-root",
            path,
            "--body",
            "none",
            "--output",
            "machine",
        ]);
        assert!(
            output.status.success(),
            "{language} definition failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let document: Value = serde_json::from_slice(&output.stdout).expect("definition JSON");
        assert_eq!(document["definition_total"], 1, "{language} target");
        assert_eq!(document["definitions"][0]["symbol_kind"], kind);
        assert_eq!(document["evidence"], "outline-candidate");
    }
}

#[test]
fn source_position_selects_a_matching_definition_but_name_queries_keep_ambiguity() {
    let source = multilang_source().join("ambiguous.ts");
    let source = source.to_str().expect("UTF-8 fixture path");
    let named = run(&[
        "symbol",
        "definition",
        "execute",
        "--language",
        "typescript",
        "--only-root",
        source,
        "--body",
        "none",
    ]);
    assert!(named.status.success());
    assert!(String::from_utf8(named.stdout)
        .expect("UTF-8 named candidates")
        .starts_with("definition-candidates 2 evidence=outline-candidate\n"));

    let at = format!("{source}:1:6");
    let positioned = run(&[
        "symbol",
        "definition",
        "--at",
        &at,
        "--language",
        "typescript",
        "--only-root",
        source,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(positioned.status.success());
    let positioned: Value =
        serde_json::from_slice(&positioned.stdout).expect("position definition JSON");
    assert_eq!(positioned["definition_total"], 1);
    assert_eq!(positioned["position_match"], true);
    assert_eq!(
        positioned["definitions"][0]["qualified_name"],
        "LeftWorker::execute"
    );

    let call_at = format!("{source}:13:20");
    let call_site = run(&[
        "symbol",
        "definition",
        "--at",
        &call_at,
        "--language",
        "typescript",
        "--only-root",
        source,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(call_site.status.success());
    let call_site: Value =
        serde_json::from_slice(&call_site.stdout).expect("call-site definition JSON");
    assert_eq!(call_site["definition_total"], 2);
    assert_eq!(call_site["position_match"], false);
}

#[test]
fn explicit_scope_controls_add_replace_and_exclude_without_changing_identity_claims() {
    let root = fixture_source();
    let root_text = root.to_str().expect("UTF-8 fixture path");
    let empty = tempfile::tempdir().expect("temporary source root");
    let empty_text = empty.path().to_str().expect("UTF-8 temporary path");

    let added = run(&[
        "symbol",
        "definition",
        "CanBuildTool",
        "--cwd",
        empty_text,
        "--add-root",
        root_text,
        "--body",
        "none",
    ]);
    assert!(
        added.status.success(),
        "added root failed: stdout={} stderr={}",
        String::from_utf8_lossy(&added.stdout),
        String::from_utf8_lossy(&added.stderr)
    );
    assert!(String::from_utf8(added.stdout)
        .expect("UTF-8 added-root result")
        .starts_with("definition-candidate function CanBuildTool"));

    let excluded = root.join("definitions.cpp");
    let excluded = excluded.to_str().expect("UTF-8 excluded path");
    let bounded = run(&[
        "symbol",
        "definition",
        "BuildTool",
        "--only-root",
        root_text,
        "--exclude",
        excluded,
        "--body",
        "none",
    ]);
    assert_eq!(bounded.status.code(), Some(1));
    let bounded = String::from_utf8(bounded.stdout).expect("UTF-8 excluded result");
    assert!(bounded.starts_with("definition-candidate none\n"));

    let conflicting = run(&[
        "symbol",
        "definition",
        "BuildTool",
        "--add-root",
        root_text,
        "--only-root",
        root_text,
    ]);
    assert_eq!(conflicting.status.code(), Some(125));
}

#[test]
fn symbol_capabilities_cover_every_registered_ast_language_without_false_support() {
    let output = run(&["symbol", "capabilities", "--output", "machine"]);
    assert!(output.status.success());
    let document: Value = serde_json::from_slice(&output.stdout).expect("capability JSON");
    assert_eq!(document["schema"], "srcq.symbol.capabilities/v1");
    assert_eq!(document["languages"].as_array().map(Vec::len), Some(26));
    let python = document["languages"]
        .as_array()
        .and_then(|languages| {
            languages
                .iter()
                .find(|language| language["language"] == "python")
        })
        .expect("python capability");
    assert_eq!(python["definition"], "candidate-only");
    assert_eq!(python["references"], "lexical-candidate");
    let bash = document["languages"]
        .as_array()
        .and_then(|languages| {
            languages
                .iter()
                .find(|language| language["language"] == "bash")
        })
        .expect("Bash capability");
    assert_eq!(bash["definition"], "unadapted");
    let json = document["languages"]
        .as_array()
        .and_then(|languages| {
            languages
                .iter()
                .find(|language| language["language"] == "json")
        })
        .expect("JSON capability");
    assert_eq!(json["definition"], "not-applicable");
}

#[test]
fn generic_relation_adapters_keep_lexical_references_and_incoming_callers_bounded() {
    let root = multilang_source();
    let cases = [
        ("python", "execute", "sample.py", "python_wrapper"),
        ("typescript", "execute", "sample.ts", "typeScriptWrapper"),
        ("rust", "execute", "sample.rs", "rust_wrapper"),
        ("go", "Execute", "sample.go", "goWrapper"),
        ("java", "execute", "Sample.java", "javaWrapper"),
        ("javascript", "execute", "sample.js", "javaScriptWrapper"),
        ("tsx", "execute", "sample.tsx", "tsxWrapper"),
    ];
    for (language, target, file, caller) in cases {
        let path = root.join(file);
        let path = path.to_str().expect("UTF-8 fixture path");
        let references = run(&[
            "symbol",
            "references",
            target,
            "--language",
            language,
            "--only-root",
            path,
        ]);
        assert!(references.status.success(), "{language} references");
        let references = String::from_utf8(references.stdout).expect("UTF-8 references");
        assert!(references
            .starts_with("references 1 identity=outline-candidate evidence=lexical-candidate\n"));

        let incoming = run(&[
            "symbol",
            "calls",
            target,
            "--language",
            language,
            "--only-root",
            path,
            "--direction",
            "incoming",
        ]);
        assert!(incoming.status.success(), "{language} incoming calls");
        let incoming = String::from_utf8(incoming.stdout).expect("UTF-8 incoming calls");
        assert!(incoming.contains(&format!("{caller} [lexical-candidate;incoming-candidate]")));
    }

    let python = root.join("sample.py");
    let python = python.to_str().expect("UTF-8 fixture path");
    let outgoing = run(&[
        "symbol",
        "calls",
        "python_wrapper",
        "--language",
        "python",
        "--only-root",
        python,
    ]);
    assert!(outgoing.status.success());
    let outgoing = String::from_utf8(outgoing.stdout).expect("UTF-8 outgoing calls");
    assert!(outgoing.starts_with("calls outgoing depth=1 nodes=3 evidence=outline-candidate\n"));
    assert!(outgoing.contains("execute [semantic-unknown;member-candidate]"));

    let depth = run(&[
        "symbol",
        "calls",
        "python_middle",
        "--language",
        "python",
        "--only-root",
        python,
        "--depth",
        "2",
    ]);
    assert!(depth.status.success());
    let depth = String::from_utf8(depth.stdout).expect("UTF-8 depth call tree");
    assert!(depth.contains("python_leaf [outline-candidate;direct-candidate]"));
}
