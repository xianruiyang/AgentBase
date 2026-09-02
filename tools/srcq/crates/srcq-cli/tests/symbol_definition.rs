use std::fs;
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

fn csharp_scope_source() -> PathBuf {
    workspace_root().join("tests/fixtures/symbol/csharp_scope")
}

fn run(arguments: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_srcq"))
        .current_dir(workspace_root())
        .args(arguments)
        .output()
        .expect("srcq symbol definition")
}

fn machine_calls(language: &str, target: &str, file: &str, incoming: bool) -> Value {
    let mut arguments = vec![
        "symbol",
        "calls",
        target,
        "--language",
        language,
        "--only-root",
        file,
        "--output",
        "machine",
    ];
    if incoming {
        arguments.extend(["--direction", "incoming"]);
    }
    let output = run(&arguments);
    assert!(
        output.status.success(),
        "{language} {target}: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("machine calls JSON")
}

fn manifest_machine(operation: &str, target: &str, manifest: &Path) -> (Output, Value) {
    let output = run(&[
        "symbol",
        operation,
        target,
        "--source-manifest",
        manifest.to_str().expect("UTF-8 manifest path"),
        "--output",
        "machine",
    ]);
    let document = serde_json::from_slice(&output.stdout).expect("manifest machine output");
    (output, document)
}

fn manifest_issue_codes(document: &Value) -> Vec<&str> {
    document["scope"]["issues"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|issue| issue["code"].as_str())
        .collect()
}

#[test]
fn explicit_vcxproj_manifest_is_bounded_across_symbol_outputs() {
    let fixture = tempfile::tempdir().expect("temporary manifest scope");
    let source = fixture.path().join("source.cpp");
    fs::write(
        &source,
        "struct PointCloudCollider { void RayCastTest() {} };\nvoid Caller() { PointCloudCollider collider; collider.RayCastTest(); }\n",
    )
    .expect("source fixture");
    let manifest = fixture.path().join("sample.vcxproj");
    fs::write(
        &manifest,
        "<Project><ItemGroup Label=\"Sources\"><ClCompile Include=\"source.cpp\" /><ClInclude Include=\"source.cpp\"><ExcludedFromBuild Condition=\"'$(Configuration)' == 'Debug'\">false</ExcludedFromBuild></ClInclude></ItemGroup></Project>",
    )
    .expect("manifest fixture");

    for (operation, target) in [
        ("definition", "PointCloudCollider::RayCastTest"),
        ("references", "RayCastTest"),
        ("calls", "PointCloudCollider::RayCastTest"),
    ] {
        let (output, document) = manifest_machine(operation, target, &manifest);
        assert!(
            output.status.success(),
            "{operation}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(document["scope"]["status"], "bounded");
        assert_eq!(
            document["scope"]["source_manifest"]["adapter"],
            "vcxproj-direct-items/v1"
        );
        assert_eq!(document["scope"]["source_manifest"]["entry_count"], 1);
        let scan = if operation == "definition" {
            &document["candidate_scan"]
        } else {
            &document["scope"]["candidate_scan"]
        };
        assert_eq!(scan, "complete");
    }

    let bundle = run(&[
        "symbol",
        "calls",
        "PointCloudCollider::RayCastTest",
        "--source-manifest",
        manifest.to_str().expect("UTF-8 manifest path"),
        "--direction",
        "both",
        "--output",
        "machine",
    ]);
    assert!(bundle.status.success());
    let bundle: Value = serde_json::from_slice(&bundle.stdout).expect("manifest bundle output");
    assert_eq!(bundle["schema"], "srcq.symbol.calls/bundle/v1");
    assert_eq!(bundle["scope"]["status"], "bounded");
    assert_eq!(bundle["scope"]["source_manifest"]["entry_count"], 1);
    assert_eq!(bundle["branches"]["incoming"]["scan"], "complete");
    assert_eq!(bundle["branches"]["outgoing"]["scan"], "complete");
}

#[test]
fn explicit_vcxproj_manifest_rejects_unresolved_direct_items() {
    let fixture = tempfile::tempdir().expect("temporary manifest failures");
    fs::write(fixture.path().join("source.cpp"), "void Present() {}\n").expect("source fixture");
    let manifest = fixture.path().join("sample.vcxproj");
    let cases = [
        (
            "<Project><ItemGroup /></Project>",
            "manifest-source-empty",
            0,
        ),
        (
            "<Project><ItemGroup Condition=\"'$(Configuration)' == 'Debug'\"><ClCompile Include=\"source.cpp\" /></ItemGroup></Project>",
            "manifest-item-group-conditional",
            0,
        ),
        (
            "<Project><ItemGroup><ClCompile Include=\"*.cpp\" /></ItemGroup></Project>",
            "manifest-direct-item-unresolved",
            0,
        ),
        (
            "<Project><ItemGroup><ClCompile Include=\"missing.cpp\" /></ItemGroup></Project>",
            "manifest-source-missing",
            0,
        ),
        (
            "<Project><ItemGroup><ClCompile Include=\"source.cpp\"><ExcludedFromBuild>true</ExcludedFromBuild></ClCompile></ItemGroup></Project>",
            "manifest-source-empty",
            0,
        ),
        (
            "<Project><ItemGroup><ClCompile Include=\"source.cpp\"><ExcludedFromBuild Condition=\"'$(Configuration)' == 'Debug'\">true</ExcludedFromBuild></ClCompile></ItemGroup></Project>",
            "manifest-exclusion-conditional",
            1,
        ),
    ];

    for (xml, expected_issue, entry_count) in cases {
        fs::write(&manifest, xml).expect("manifest variant");
        let (_, document) = manifest_machine("definition", "Missing", &manifest);
        assert_eq!(document["scope"]["status"], "incomplete", "{xml}");
        assert_eq!(
            document["scope"]["source_manifest"]["entry_count"], entry_count,
            "{xml}"
        );
        assert!(
            manifest_issue_codes(&document).contains(&expected_issue),
            "{xml}: {document}"
        );
    }
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
    assert_eq!(qualified["reference_total"], 3);
    assert!(qualified["references"]
        .as_array()
        .expect("qualified lexical references")
        .iter()
        .all(|reference| {
            reference["role"] == "call" && reference["evidence"] == "lexical-candidate"
        }));

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
    assert!(cross_file.contains("FirstCrossFileCaller [direct-candidate;incoming-candidate]"));
    assert!(cross_file.contains("SecondCrossFileCaller [direct-candidate;incoming-candidate] :"));

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
    assert!(cycle["scope"].get("source_manifest").is_none());
    assert!(cycle["scope"].get("issues").is_none());
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
fn cpp_bidirectional_calls_bundle_reconstructs_both_v1_roots_and_branch_state() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");
    let separate = |direction: &str| {
        let output = run(&[
            "symbol",
            "calls",
            "Recursive",
            "--only-root",
            root,
            "--direction",
            direction,
            "--depth",
            "3",
            "--output",
            "machine",
        ]);
        assert!(output.status.success(), "{direction}");
        serde_json::from_slice::<Value>(&output.stdout).expect("v1 call tree")
    };
    let incoming = separate("incoming");
    let outgoing = separate("outgoing");
    let bundle = run(&[
        "symbol",
        "calls",
        "Recursive",
        "--only-root",
        root,
        "--direction",
        "both",
        "--depth",
        "3",
        "--output",
        "machine",
    ]);
    assert!(
        bundle.status.success(),
        "{}",
        String::from_utf8_lossy(&bundle.stderr)
    );
    let bundle: Value = serde_json::from_slice(&bundle.stdout).expect("bundle call tree");
    assert_eq!(bundle["schema"], "srcq.symbol.calls/bundle/v1");
    assert_eq!(bundle["query"]["direction"], "both");
    assert_eq!(bundle["query"]["max_nodes_scope"], "per-branch");
    assert_eq!(bundle["query"]["time_budget_scope"], "bundle");

    for (direction, expected) in [("incoming", incoming), ("outgoing", outgoing)] {
        let branch = &bundle["branches"][direction];
        let mut reconstructed = bundle["root"].clone();
        reconstructed["children"] = branch["children"].clone();
        assert_eq!(reconstructed, expected["root"], "{direction} root");
        assert_eq!(branch["nodes"], expected["nodes"], "{direction} nodes");
        assert_eq!(
            branch["truncated"], expected["truncated"],
            "{direction} truncation"
        );
        assert_eq!(
            branch["time_limited"], expected["time_limited"],
            "{direction} timeout"
        );
        assert_eq!(
            branch["scan"], expected["scope"]["candidate_scan"],
            "{direction} scan"
        );
        assert_eq!(
            branch["evidence"], expected["evidence"],
            "{direction} evidence"
        );
        assert_eq!(branch["exit_code"], 0, "{direction} exit");
    }

    let truncated = run(&[
        "symbol",
        "calls",
        "Recursive",
        "--only-root",
        root,
        "--direction",
        "both",
        "--depth",
        "3",
        "--max-nodes",
        "1",
        "--output",
        "machine",
    ]);
    assert!(truncated.status.success());
    let truncated: Value =
        serde_json::from_slice(&truncated.stdout).expect("truncated bundle call tree");
    assert_eq!(truncated["branches"]["incoming"]["truncated"], true);
    assert_eq!(truncated["branches"]["outgoing"]["truncated"], true);
}

#[test]
fn cpp_header_inline_method_is_a_definition_but_bodyless_method_stays_a_declaration() {
    let root = fixture_source();
    let root = root.to_str().expect("UTF-8 fixture path");

    let definition = run(&[
        "symbol",
        "definition",
        "InlineWorker::RunInline",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(definition.status.success());
    let definition: Value =
        serde_json::from_slice(&definition.stdout).expect("inline method definition JSON");
    assert_eq!(definition["definition_total"], 1);
    assert_eq!(definition["declaration_total"], 0);
    assert_eq!(
        definition["definitions"][0]["qualified_name"],
        "InlineWorker::RunInline"
    );

    let incoming = run(&[
        "symbol",
        "calls",
        "InlineWorker::RunInline",
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
    let incoming: Value =
        serde_json::from_slice(&incoming.stdout).expect("inline incoming calls JSON");
    let callers = incoming["root"]["children"]
        .as_array()
        .expect("inline incoming callers");
    assert_eq!(callers.len(), 6);
    assert!(callers.iter().any(|caller| {
        caller["name"] == "CallInline"
            && caller["qualified_name"] == "InlineWorker::CallInline"
            && caller["definition"]["qualified_name"] == "InlineWorker::CallInline"
    }));
    assert!(callers
        .iter()
        .any(|caller| caller["name"] == "UseInlineWorker"));
    for qualified_name in [
        "InlineWorkerHolder::CallMember",
        "InlineWorkerChain::CallChain",
        "InlineWorkerSharedHolder::CallShared",
        "InlineWorkerLateHolder::CallLate",
    ] {
        assert!(callers
            .iter()
            .any(|caller| caller["qualified_name"] == qualified_name));
    }

    let declaration = run(&[
        "symbol",
        "definition",
        "InlineWorker::DeclaredInline",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert_eq!(declaration.status.code(), Some(1));
    let declaration: Value =
        serde_json::from_slice(&declaration.stdout).expect("inline declaration JSON");
    assert_eq!(declaration["definition_total"], 0);
    assert_eq!(declaration["declaration_total"], 1);

    let out_of_line = run(&[
        "symbol",
        "definition",
        "VirtualWorker::RunVirtual",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(out_of_line.status.success());
    let out_of_line: Value =
        serde_json::from_slice(&out_of_line.stdout).expect("out-of-line method JSON");
    assert_eq!(out_of_line["definition_total"], 1);
    assert_eq!(out_of_line["definitions"][0]["symbol_kind"], "method");

    let friend = run(&[
        "symbol",
        "definition",
        "FriendFree",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(friend.status.success());
    let friend: Value =
        serde_json::from_slice(&friend.stdout).expect("friend function definition JSON");
    assert_eq!(friend["definition_total"], 1);
    assert_eq!(friend["definitions"][0]["qualified_name"], "FriendFree");
    assert_eq!(friend["definitions"][0]["symbol_kind"], "function");

    let ordinary_inline = run(&[
        "symbol",
        "definition",
        "OrdinaryInline",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(ordinary_inline.status.success());
    let ordinary_inline: Value = serde_json::from_slice(&ordinary_inline.stdout)
        .expect("comment-adjacent inline method definition JSON");
    assert_eq!(
        ordinary_inline["definitions"][0]["qualified_name"],
        "CommentFriendHolder::OrdinaryInline"
    );
    assert_eq!(ordinary_inline["definitions"][0]["symbol_kind"], "method");

    let declarator_probe = run(&[
        "symbol",
        "definition",
        "DeclaratorProbe",
        "--only-root",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(declarator_probe.status.success());
    let declarator_probe: Value = serde_json::from_slice(&declarator_probe.stdout)
        .expect("declarator prefix noise definition JSON");
    assert_eq!(declarator_probe["definition_total"], 1);
    assert_eq!(declarator_probe["declaration_total"], 0);
    assert_eq!(declarator_probe["definitions"][0]["symbol_kind"], "type");
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
        ("c", "c_execute", "sample.c", "function"),
        ("csharp", "CSharpWorker.Execute", "sample.cs", "method"),
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
    assert_eq!(python["calls"], "candidate");
    assert_eq!(python["scope"], "project-metadata-aware");
    for key in ["go", "javascript", "rust", "tsx", "typescript"] {
        let language = document["languages"]
            .as_array()
            .and_then(|languages| {
                languages
                    .iter()
                    .find(|language| language["language"] == key)
            })
            .unwrap_or_else(|| panic!("{key} capability"));
        assert_eq!(language["calls"], "candidate", "{key}");
        assert_eq!(language["scope"], "project-metadata-aware", "{key}");
    }
    let c = document["languages"]
        .as_array()
        .and_then(|languages| {
            languages
                .iter()
                .find(|language| language["language"] == "c")
        })
        .expect("C capability");
    assert_eq!(c["definition"], "candidate-only");
    assert_eq!(c["references"], "lexical-candidate");
    assert_eq!(c["calls"], "candidate");
    let csharp = document["languages"]
        .as_array()
        .and_then(|languages| {
            languages
                .iter()
                .find(|language| language["language"] == "csharp")
        })
        .expect("C# capability");
    assert_eq!(csharp["definition"], "candidate-only");
    assert_eq!(csharp["references"], "lexical-candidate");
    assert_eq!(csharp["calls"], "candidate");
    assert_eq!(csharp["scope"], "project-compile-aware");
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
        ("c", "c_execute", "sample.c", "c_wrapper"),
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
        let edge = if matches!(
            language,
            "go" | "javascript" | "python" | "rust" | "tsx" | "typescript"
        ) {
            "typed-member-candidate"
        } else {
            "lexical-candidate"
        };
        assert!(
            incoming.contains(&format!("{caller} [{edge};incoming-candidate")),
            "{language} incoming:\n{incoming}"
        );
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
    assert!(outgoing.contains(
        "PythonWorker::execute [typed-member-candidate receiver=PythonWorker():PythonWorker]"
    ));

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

    let c = root.join("sample.c");
    let c = c.to_str().expect("UTF-8 fixture path");
    let c_outgoing = run(&[
        "symbol",
        "calls",
        "c_middle",
        "--language",
        "c",
        "--only-root",
        c,
        "--depth",
        "2",
    ]);
    assert!(c_outgoing.status.success());
    let c_outgoing = String::from_utf8(c_outgoing.stdout).expect("UTF-8 C outgoing calls");
    assert!(c_outgoing.contains("c_leaf [outline-candidate;direct-candidate]"));

    let csharp = root.join("sample.cs");
    let csharp = csharp.to_str().expect("UTF-8 fixture path");
    let csharp_outgoing = run(&[
        "symbol",
        "calls",
        "CSharpMiddle",
        "--language",
        "csharp",
        "--only-root",
        csharp,
        "--depth",
        "2",
    ]);
    assert!(csharp_outgoing.status.success());
    let csharp_outgoing =
        String::from_utf8(csharp_outgoing.stdout).expect("UTF-8 C# outgoing calls");
    assert!(csharp_outgoing.contains("CSharpLeaf [outline-candidate;direct-candidate]"));
}

#[test]
fn typescript_typed_relations_respect_scope_and_disambiguate_calls() {
    let typescript = multilang_source().join("typed_receivers.ts");
    let typescript = typescript.to_str().expect("UTF-8 fixture path");
    let outgoing = run(&[
        "symbol",
        "calls",
        "Owner::run",
        "--language",
        "typescript",
        "--only-root",
        typescript,
        "--depth",
        "2",
        "--output",
        "machine",
    ]);
    assert!(
        outgoing.status.success(),
        "{}",
        String::from_utf8_lossy(&outgoing.stderr)
    );
    let outgoing: Value =
        serde_json::from_slice(&outgoing.stdout).expect("TypeScript outgoing JSON");
    let children = outgoing["root"]["children"]
        .as_array()
        .expect("outgoing children");
    assert!(
        children
            .iter()
            .filter(|call| call["name"] == "PrimaryWorker::execute"
                && call["dispatch"] == "typed-member-candidate"
                && call["status"] == "outline-candidate")
            .count()
            >= 4
    );
    assert!(children.iter().any(
        |call| call["name"] == "Owner::execute" && call["dispatch"] == "typed-member-candidate"
    ));
    assert!(children
        .iter()
        .any(|call| call["name"] == "PrimaryWorker::create"
            && call["dispatch"] == "typed-member-candidate"));
    assert!(children
        .iter()
        .any(|call| call["name"] == "AlternateWorker::execute" && call["receiver"] == "scoped"));
    assert!(children
        .iter()
        .filter(|call| call["receiver"] == "scoped")
        .any(|call| call["status"] == "semantic-unknown"));
    assert!(children
        .iter()
        .any(|call| call["receiver"] == "conflict" && call["status"] == "semantic-unknown"));

    let incoming = run(&[
        "symbol",
        "calls",
        "PrimaryWorker::execute",
        "--language",
        "typescript",
        "--only-root",
        typescript,
        "--direction",
        "incoming",
        "--output",
        "machine",
    ]);
    assert!(
        incoming.status.success(),
        "{}",
        String::from_utf8_lossy(&incoming.stderr)
    );
    let incoming: Value =
        serde_json::from_slice(&incoming.stdout).expect("TypeScript incoming JSON");
    let children = incoming["root"]["children"]
        .as_array()
        .expect("incoming children");
    assert!(children
        .iter()
        .any(|call| call["name"] == "arrowCaller" && call["receiver_type"] == "PrimaryWorker"));
    assert!(children.iter().any(|call| call["name"] == "#privateCaller"
        && call["qualified_name"] == "Owner::#privateCaller"
        && call["receiver_type"] == "PrimaryWorker"));
    assert!(children.iter().any(|call| call["name"] == "run"
        && call["qualified_name"] == "Owner::run"
        && call["receiver_type"] == "PrimaryWorker"));
    assert!(!children
        .iter()
        .any(|call| call["receiver_type"] == "AlternateWorker"));

    let incoming_model = run(&[
        "symbol",
        "calls",
        "PrimaryWorker::execute",
        "--language",
        "typescript",
        "--only-root",
        typescript,
        "--direction",
        "incoming",
    ]);
    assert!(
        incoming_model.status.success(),
        "{}",
        String::from_utf8_lossy(&incoming_model.stderr)
    );
    let incoming_model = String::from_utf8_lossy(&incoming_model.stdout);
    assert!(incoming_model.contains("Owner::run"));
    assert!(incoming_model.contains("Owner::#privateCaller"));
}

#[test]
fn typed_language_adapters_preserve_static_identity_and_dynamic_unknowns() {
    let root = multilang_source();

    let go = root.join("typed_go.go");
    let go = go.to_str().expect("UTF-8 Go fixture path");
    let outgoing = machine_calls("go", "consume", go, false);
    let children = outgoing["root"]["children"].as_array().expect("Go calls");
    for receiver in ["a", "b", "c", "local", "created", "Alpha"] {
        assert!(children.iter().any(|call| call["receiver"] == receiver
            && call["name"] == "Alpha::Ping"
            && call["dispatch"] == "typed-member-candidate"));
    }
    assert!(children
        .iter()
        .any(|call| call["receiver"] == "any" && call["status"] == "semantic-unknown"));
    assert!(children
        .iter()
        .any(|call| call["name"] == "<indirect>" && call["status"] == "semantic-unknown"));
    let shadowed = machine_calls("go", "uppercaseShadow", go, false);
    let shadowed = shadowed["root"]["children"]
        .as_array()
        .expect("Go shadowed calls");
    assert!(shadowed.iter().any(|call| call["receiver"] == "Alpha"
        && call["name"] == "Ping"
        && call["status"] == "semantic-unknown"
        && call["receiver_type"].is_null()));
    let incoming = machine_calls("go", "Alpha::Ping", go, true);
    let children = incoming["root"]["children"]
        .as_array()
        .expect("Go incoming calls");
    assert!(children
        .iter()
        .any(|call| call["name"] == "Run" && call["receiver_type"] == "Alpha"));
    assert!(!children.iter().any(|call| call["receiver_type"] == "Beta"));

    let python = root.join("typed_python.py");
    let python = python.to_str().expect("UTF-8 Python fixture path");
    let outgoing = machine_calls("python", "Holder::exercise", python, false);
    let children = outgoing["root"]["children"]
        .as_array()
        .expect("Python calls");
    for receiver in ["local", "self.member"] {
        assert!(children.iter().any(|call| call["receiver"] == receiver
            && call["name"] == "Alpha::ping"
            && call["dispatch"] == "typed-member-candidate"));
    }
    assert!(children.iter().any(|call| call["receiver"] == "self"
        && call["name"] == "Holder::exercise"
        && call["dispatch"] == "typed-member-candidate"));
    assert!(children
        .iter()
        .any(|call| call["receiver"] == "dynamic" && call["status"] == "semantic-unknown"));
    assert!(children.iter().any(|call| call["receiver"] == "value"
        && call["status"] == "semantic-unknown"
        && call["receiver_type"].is_null()));
    let incoming = machine_calls("python", "Alpha::ping", python, true);
    let children = incoming["root"]["children"]
        .as_array()
        .expect("Python incoming calls");
    assert!(children
        .iter()
        .any(|call| call["name"] == "nested" && call["receiver_type"] == "Alpha"));
    assert!(!children.iter().any(|call| call["receiver_type"] == "Beta"));

    let rust = root.join("typed_rust.rs");
    let rust = rust.to_str().expect("UTF-8 Rust fixture path");
    let outgoing = machine_calls("rust", "Alpha::exercise", rust, false);
    let children = outgoing["root"]["children"].as_array().expect("Rust calls");
    for receiver in ["explicit", "borrowed", "local", "made", "built", "self"] {
        assert!(children.iter().any(|call| call["receiver"] == receiver
            && call["name"] == "Alpha::ping"
            && call["receiver_type"] == "Alpha"));
    }
    assert!(children
        .iter()
        .any(|call| call["receiver"] == "opaque" && call["status"] == "semantic-unknown"));
    let incoming = machine_calls("rust", "Alpha::ping", rust, true);
    let children = incoming["root"]["children"]
        .as_array()
        .expect("Rust incoming calls");
    assert!(children.iter().any(|call| call["name"] == "field_call"
        && call["receiver"] == "self.child"
        && call["receiver_type"] == "Alpha"));
    assert!(!children.iter().any(|call| call["receiver_type"] == "Beta"));

    let javascript = root.join("typed_javascript.js");
    let javascript = javascript.to_str().expect("UTF-8 JavaScript fixture path");
    let outgoing = machine_calls("javascript", "Harness::execute", javascript, false);
    let children = outgoing["root"]["children"]
        .as_array()
        .expect("JavaScript calls");
    for receiver in ["local", "this.field", "Alpha"] {
        assert!(children.iter().any(|call| call["receiver"] == receiver
            && call["name"] == "Alpha::run"
            && call["receiver_type"] == "Alpha"));
    }
    assert!(children
        .iter()
        .any(|call| call["name"] == "<indirect>" && call["status"] == "semantic-unknown"));
    let incoming = machine_calls("javascript", "Alpha::run", javascript, true);
    let children = incoming["root"]["children"]
        .as_array()
        .expect("JavaScript incoming calls");
    assert!(children
        .iter()
        .any(|call| call["name"] == "expressionOwner" && call["receiver_type"] == "Alpha"));
    assert!(children.iter().any(|call| call["name"] == "#privateCaller"
        && call["qualified_name"] == "Harness::#privateCaller"
        && call["receiver_type"] == "Alpha"));
    assert!(children.iter().any(|call| call["name"] == "execute"
        && call["qualified_name"] == "Harness::execute"
        && call["receiver_type"] == "Alpha"));
    assert!(!children.iter().any(|call| call["receiver_type"] == "Beta"));
}

#[test]
fn csharp_explicit_receiver_types_bound_same_named_calls_without_lsp() {
    let root = multilang_source();
    let csharp = root.join("sample.cs");
    let csharp = csharp.to_str().expect("UTF-8 fixture path");

    let outgoing = run(&[
        "symbol",
        "calls",
        "CSharpTypedReceivers",
        "--language",
        "csharp",
        "--only-root",
        csharp,
        "--depth",
        "2",
        "--output",
        "machine",
    ]);
    assert!(outgoing.status.success());
    let outgoing: Value = serde_json::from_slice(&outgoing.stdout).expect("C# outgoing JSON");
    let outgoing_children = outgoing["root"]["children"]
        .as_array()
        .expect("C# outgoing children");
    for receiver in ["worker", "_worker", "local"] {
        let call = outgoing_children
            .iter()
            .find(|child| child["receiver"] == receiver)
            .unwrap_or_else(|| panic!("typed C# call for {receiver}"));
        assert_eq!(call["name"], "CSharpWorker::Execute");
        assert_eq!(call["dispatch"], "typed-member-candidate");
        assert_eq!(call["receiver_type"], "CSharpWorker");
        assert_eq!(call["status"], "outline-candidate");
        assert_eq!(
            call["definition"]["qualified_name"],
            "SrcqSamples::CSharpWorker::Execute"
        );
    }
    let alternate_call = outgoing_children
        .iter()
        .find(|child| child["receiver"] == "_alternate")
        .expect("alternate typed C# call");
    assert_eq!(alternate_call["name"], "CSharpAlternateWorker::Execute");
    assert_eq!(alternate_call["receiver_type"], "CSharpAlternateWorker");
    assert_eq!(alternate_call["status"], "outline-candidate");

    let incoming = run(&[
        "symbol",
        "calls",
        "CSharpWorker.Execute",
        "--language",
        "csharp",
        "--only-root",
        csharp,
        "--direction",
        "incoming",
        "--output",
        "machine",
    ]);
    assert!(incoming.status.success());
    let incoming: Value = serde_json::from_slice(&incoming.stdout).expect("C# incoming JSON");
    assert_eq!(
        incoming["root"]["definition"]["qualified_name"],
        "SrcqSamples::CSharpWorker::Execute"
    );
    let incoming_children = incoming["root"]["children"]
        .as_array()
        .expect("C# incoming children");
    assert_eq!(incoming_children.len(), 5);
    assert_eq!(
        incoming_children
            .iter()
            .filter(|child| child["receiver_type"] == "CSharpWorker")
            .count(),
        4
    );
    assert!(incoming_children.iter().any(|child| {
        child["name"] == "CSharpUnknownReceiver"
            && child["receiver"] == "worker"
            && child["receiver_type"].is_null()
    }));
    assert!(incoming_children
        .iter()
        .all(|child| child["receiver_type"] != "CSharpAlternateWorker"));

    let alternate_incoming = run(&[
        "symbol",
        "calls",
        "CSharpAlternateWorker.Execute",
        "--language",
        "csharp",
        "--only-root",
        csharp,
        "--direction",
        "incoming",
        "--output",
        "machine",
    ]);
    assert!(alternate_incoming.status.success());
    let alternate_incoming: Value =
        serde_json::from_slice(&alternate_incoming.stdout).expect("alternate C# incoming JSON");
    let alternate_children = alternate_incoming["root"]["children"]
        .as_array()
        .expect("alternate C# incoming children");
    assert_eq!(alternate_children.len(), 2);
    assert!(alternate_children.iter().any(|child| {
        child["receiver"] == "_alternate" && child["receiver_type"] == "CSharpAlternateWorker"
    }));
    assert!(alternate_children.iter().any(|child| {
        child["name"] == "CSharpUnknownReceiver" && child["receiver_type"].is_null()
    }));
}

#[test]
fn csharp_local_and_lambda_bindings_respect_lexical_scope_without_lsp() {
    let source = multilang_source().join("csharp_lexical.cs");
    let source = source.to_str().expect("UTF-8 fixture path");

    let siblings = run(&[
        "symbol",
        "calls",
        "CSharpSiblingScopes",
        "--language",
        "csharp",
        "--only-root",
        source,
        "--output",
        "machine",
    ]);
    assert!(siblings.status.success());
    let siblings: Value = serde_json::from_slice(&siblings.stdout).expect("C# sibling-scope JSON");
    let sibling_calls = siblings["root"]["children"]
        .as_array()
        .expect("C# sibling-scope calls")
        .iter()
        .filter(|call| call["receiver"] == "scoped")
        .collect::<Vec<_>>();
    assert_eq!(sibling_calls.len(), 2);
    assert_eq!(sibling_calls[0]["receiver_type"], "CSharpLexicalWorker");
    assert_eq!(
        sibling_calls[1]["receiver_type"],
        "CSharpLexicalAlternateWorker"
    );

    let lambda = run(&[
        "symbol",
        "calls",
        "CSharpLambdaScope",
        "--language",
        "csharp",
        "--only-root",
        source,
        "--output",
        "machine",
    ]);
    assert!(lambda.status.success());
    let lambda: Value = serde_json::from_slice(&lambda.stdout).expect("C# lambda-scope JSON");
    let worker_calls = lambda["root"]["children"]
        .as_array()
        .expect("C# lambda-scope calls")
        .iter()
        .filter(|call| call["receiver"] == "worker")
        .collect::<Vec<_>>();
    assert_eq!(worker_calls.len(), 2);
    assert_eq!(
        worker_calls[0]["receiver_type"],
        "CSharpLexicalAlternateWorker"
    );
    assert_eq!(worker_calls[1]["receiver_type"], "CSharpLexicalWorker");

    let exited = run(&[
        "symbol",
        "calls",
        "CSharpExitedScope",
        "--language",
        "csharp",
        "--only-root",
        source,
        "--output",
        "machine",
    ]);
    assert!(exited.status.success());
    let exited: Value = serde_json::from_slice(&exited.stdout).expect("C# exited-scope JSON");
    let exited_call = exited["root"]["children"]
        .as_array()
        .expect("C# exited-scope calls")
        .iter()
        .find(|call| call["receiver"] == "scoped")
        .expect("out-of-scope receiver remains visible");
    assert!(exited_call["receiver_type"].is_null());
    assert_eq!(exited_call["status"], "semantic-unknown");
}

#[test]
fn csharp_partial_members_property_chains_and_source_static_types_resolve_without_lsp() {
    let root = multilang_source();
    let root = root.to_str().expect("UTF-8 fixture path");

    let property_chain = run(&[
        "symbol",
        "calls",
        "CSharpPropertyChain",
        "--language",
        "csharp",
        "--only-root",
        root,
        "--depth",
        "2",
        "--output",
        "machine",
    ]);
    assert!(property_chain.status.success());
    let property_chain: Value =
        serde_json::from_slice(&property_chain.stdout).expect("C# property-chain JSON");
    let property_children = property_chain["root"]["children"]
        .as_array()
        .expect("C# property-chain children");
    assert_eq!(property_children.len(), 1);
    assert_eq!(property_children[0]["name"], "CSharpWorker::Execute");
    assert_eq!(property_children[0]["dispatch"], "typed-member-candidate");
    assert_eq!(property_children[0]["receiver"], "_services.Worker");
    assert_eq!(property_children[0]["receiver_type"], "CSharpWorker");
    assert_eq!(property_children[0]["status"], "outline-candidate");
    assert_eq!(
        property_children[0]["definition"]["qualified_name"],
        "SrcqSamples::CSharpWorker::Execute"
    );

    let static_call = run(&[
        "symbol",
        "calls",
        "CSharpStaticCall",
        "--language",
        "csharp",
        "--only-root",
        root,
        "--depth",
        "2",
        "--output",
        "machine",
    ]);
    assert!(static_call.status.success());
    let static_call: Value =
        serde_json::from_slice(&static_call.stdout).expect("C# static-call JSON");
    let static_children = static_call["root"]["children"]
        .as_array()
        .expect("C# static-call children");
    assert_eq!(static_children.len(), 1);
    assert_eq!(
        static_children[0]["name"],
        "SrcqSamples::CSharpStaticWorker::Execute"
    );
    assert_eq!(
        static_children[0]["receiver_type"],
        "SrcqSamples::CSharpStaticWorker"
    );
    assert_eq!(static_children[0]["status"], "outline-candidate");
}

#[test]
fn csharp_solution_compile_items_exclude_removed_and_unowned_repository_files() {
    let root = csharp_scope_source();
    let root = root.to_str().expect("UTF-8 fixture path");

    for target in ["LinkedOnly", "LibraryOnly"] {
        let definition = run(&[
            "symbol",
            "definition",
            target,
            "--language",
            "csharp",
            "--cwd",
            root,
            "--body",
            "none",
            "--output",
            "machine",
        ]);
        assert!(definition.status.success(), "definition for {target}");
        let definition: Value =
            serde_json::from_slice(&definition.stdout).expect("C# scoped definition JSON");
        assert_eq!(definition["scope"]["status"], "resolved");
        assert_eq!(definition["scope"]["compile_file_hints"], 3);
        assert_eq!(definition["scope"]["issues"], serde_json::json!([]));
        assert_eq!(definition["candidate_scan"], "complete");
        assert_eq!(definition["definition_total"], 1);
    }

    for target in ["LegacyOnly", "RepositoryOnly"] {
        let definition = run(&[
            "symbol",
            "definition",
            target,
            "--language",
            "csharp",
            "--cwd",
            root,
            "--body",
            "none",
            "--output",
            "machine",
        ]);
        assert_eq!(definition.status.code(), Some(1), "definition for {target}");
        let definition: Value =
            serde_json::from_slice(&definition.stdout).expect("C# excluded definition JSON");
        assert_eq!(definition["scope"]["status"], "resolved");
        assert_eq!(definition["scope"]["compile_file_hints"], 3);
        assert_eq!(definition["candidate_scan"], "complete");
        assert_eq!(definition["definition_total"], 0);
    }

    let references = run(&[
        "symbol",
        "references",
        "LibraryOnly",
        "--language",
        "csharp",
        "--cwd",
        root,
        "--output",
        "machine",
    ]);
    assert!(references.status.success());
    let references: Value =
        serde_json::from_slice(&references.stdout).expect("C# scoped references JSON");
    assert_eq!(references["scope"]["candidate_scan"], "complete");
    assert_eq!(references["reference_total"], 1);
}

#[test]
fn csharp_conditional_compile_items_report_incomplete_instead_of_claiming_msbuild_precision() {
    let root = tempfile::tempdir().expect("temporary C# scope");
    let project = root.path().join("Conditional");
    fs::create_dir_all(&project).expect("conditional project directory");
    fs::write(
        root.path().join("Conditional.sln"),
        "Microsoft Visual Studio Solution File, Format Version 12.00\n\
Project(\"{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}\") = \"Conditional\", \"Conditional\\Conditional.csproj\", \"{33333333-3333-3333-3333-333333333333}\"\n\
EndProject\nGlobal\nEndGlobal\n",
    )
    .expect("conditional solution");
    fs::write(
        project.join("Conditional.csproj"),
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n\
  <ItemGroup Condition=\"'$(Configuration)' == 'Release'\">\n\
    <Compile Remove=\"ConditionalOnly.cs\" />\n\
  </ItemGroup>\n\
</Project>\n",
    )
    .expect("conditional project");
    fs::write(
        project.join("Stable.cs"),
        "namespace ConditionalScope; class Stable { }\n",
    )
    .expect("stable source");
    fs::write(
        project.join("ConditionalOnly.cs"),
        "namespace ConditionalScope; class ConditionalOnly { }\n",
    )
    .expect("conditional source");
    let root = root.path().to_str().expect("UTF-8 temporary C# scope");
    let definition = run(&[
        "symbol",
        "definition",
        "Stable",
        "--language",
        "csharp",
        "--cwd",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(definition.status.success());
    let definition: Value =
        serde_json::from_slice(&definition.stdout).expect("conditional C# scope JSON");
    assert_eq!(definition["scope"]["status"], "incomplete");
    assert!(definition["scope"]["issues"]
        .as_array()
        .expect("C# scope issues")
        .iter()
        .any(|issue| issue["code"] == "csharp-item-condition-unresolved"));
    assert_eq!(definition["definition_total"], 1);
}

#[test]
fn csharp_resolved_empty_compile_scope_does_not_fall_back_to_repository_files() {
    let root = tempfile::tempdir().expect("temporary empty C# scope");
    let project = root.path().join("Empty");
    fs::create_dir_all(&project).expect("empty project directory");
    fs::write(
        root.path().join("Empty.sln"),
        "Microsoft Visual Studio Solution File, Format Version 12.00\n\
Project(\"{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}\") = \"Empty\", \"Empty\\Empty.csproj\", \"{44444444-4444-4444-4444-444444444444}\"\n\
EndProject\nGlobal\nEndGlobal\n",
    )
    .expect("empty solution");
    fs::write(
        project.join("Empty.csproj"),
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n\
  <PropertyGroup><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup>\n\
</Project>\n",
    )
    .expect("empty project");
    fs::write(
        project.join("Stray.cs"),
        "namespace EmptyScope; class MustNotBeScanned { }\n",
    )
    .expect("stray source");

    let root = root.path().to_str().expect("UTF-8 temporary C# scope");
    let definition = run(&[
        "symbol",
        "definition",
        "MustNotBeScanned",
        "--language",
        "csharp",
        "--cwd",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert_eq!(definition.status.code(), Some(1));
    let definition: Value =
        serde_json::from_slice(&definition.stdout).expect("empty C# scope JSON");
    assert_eq!(definition["scope"]["status"], "resolved");
    assert_eq!(definition["scope"]["compile_file_hints"], 0);
    assert_eq!(definition["scope"]["issues"], serde_json::json!([]));
    assert_eq!(definition["candidate_scan"], "complete");
    assert_eq!(definition["definition_total"], 0);
}

#[test]
fn csharp_ambiguous_and_unevaluated_msbuild_inputs_never_claim_complete_scope() {
    let root = tempfile::tempdir().expect("temporary ambiguous C# scope");
    let project = root.path().join("App");
    fs::create_dir_all(&project).expect("ambiguous project directory");
    let solution = "Microsoft Visual Studio Solution File, Format Version 12.00\n\
Project(\"{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}\") = \"App\", \"App\\App.csproj\", \"{55555555-5555-5555-5555-555555555555}\"\n\
EndProject\nGlobal\nEndGlobal\n";
    fs::write(root.path().join("One.sln"), solution).expect("first solution");
    fs::write(root.path().join("Two.sln"), solution).expect("second solution");
    fs::write(root.path().join("Directory.Build.props"), "<Project />\n")
        .expect("Directory.Build input");
    fs::write(project.join("Custom.props"), "<Project />\n").expect("custom import");
    fs::write(
        project.join("App.csproj"),
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n\
  <Import Project=\"Custom.props\" />\n\
</Project>\n",
    )
    .expect("ambiguous project");
    fs::write(
        project.join("Stable.cs"),
        "namespace App; class Stable { }\n",
    )
    .expect("stable source");

    let root = root.path().to_str().expect("UTF-8 temporary C# scope");
    let definition = run(&[
        "symbol",
        "definition",
        "Stable",
        "--language",
        "csharp",
        "--cwd",
        root,
        "--body",
        "none",
        "--output",
        "machine",
    ]);
    assert!(definition.status.success());
    let definition: Value =
        serde_json::from_slice(&definition.stdout).expect("ambiguous C# scope JSON");
    assert_eq!(definition["scope"]["status"], "incomplete");
    let issues = definition["scope"]["issues"]
        .as_array()
        .expect("ambiguous C# scope issues");
    for expected in [
        "csharp-solution-selection-ambiguous",
        "csharp-directory-build-unresolved",
        "csharp-project-import-unresolved",
    ] {
        assert!(issues.iter().any(|issue| issue["code"] == expected));
    }
    assert_eq!(definition["definition_total"], 1);
}
