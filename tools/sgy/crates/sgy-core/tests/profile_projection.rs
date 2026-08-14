use serde_json::{json, Value};
use sgy_core::codec::{ByteSpan, SourceRecord};
use sgy_core::profile::{
    project_custom, project_custom_record, project_location_record, project_sarif_token_safe,
    project_token_safe, project_token_safe_record, FieldPathError, FieldPaths, RecordShape,
};

fn native_range() -> Value {
    json!({
        "byteOffset": {"start": 10, "end": 20},
        "start": {"line": 1, "column": 2},
        "end": {"line": 1, "column": 12}
    })
}

#[test]
fn location_projection_is_compact_zero_based_and_keeps_unknowns_explicit() {
    let projected = project_token_safe(
        7,
        &json!({
            "file": "src/main.ts",
            "range": native_range(),
            "text": "function body"
        }),
    );
    let location = project_location_record(&projected);
    assert_eq!(location.ordinal, 7);
    assert_eq!(location.shape, RecordShape::Match);
    assert_eq!(location.value, "src/main.ts:1:2-1:12");

    let unknown = project_location_record(&project_token_safe(8, &json!({"future": true})));
    assert_eq!(unknown.value["_sgy_result"], 8);
    assert_eq!(unknown.value["_sgy_unknown"], true);
}

#[test]
fn run_and_rewrite_projection_keeps_only_context_fields() {
    let native = json!({
        "text": "console.log(alpha)",
        "range": native_range(),
        "file": "src/main.ts",
        "lines": "console.log(alpha);",
        "charCount": {"leading": 0, "trailing": 1},
        "replacement": "logger.info(alpha)",
        "replacementOffsets": {"start": 10, "end": 20},
        "language": "TypeScript",
        "metaVariables": {
            "single": {
                "A": {"text": "alpha", "range": native_range()},
                "EMPTY": {"range": native_range()}
            },
            "multi": {
                "ARGS": [
                    {"text": "alpha", "range": native_range()},
                    {"text": "beta", "range": native_range()}
                ]
            },
            "transformed": {}
        },
        "futureField": {"large": "must not enter context"}
    });
    let original = native.clone();
    let projected = project_token_safe_record(&SourceRecord {
        ordinal: 4,
        span: ByteSpan::new(100, 200),
        value: native.clone(),
    });

    assert_eq!(projected.ordinal, 4);
    assert_eq!(projected.shape, RecordShape::Match);
    assert_eq!(
        projected.value,
        json!({
            "file": "src/main.ts",
            "range": {
                "start": {"line": 1, "column": 2},
                "end": {"line": 1, "column": 12}
            },
            "text": "console.log(alpha)",
            "replacement": "logger.info(alpha)",
            "metaVariables": {
                "single": {"A": {"text": "alpha"}},
                "multi": {"ARGS": [{"text": "alpha"}, {"text": "beta"}]}
            }
        })
    );
    assert_eq!(
        native, original,
        "projection must not mutate lossless source"
    );
}

#[test]
fn finding_projection_preserves_diagnostics_and_cleans_nested_noise() {
    let native = json!({
        "file": "src/main.ts",
        "range": native_range(),
        "text": "console.log(alpha)",
        "ruleId": "no-console",
        "severity": "warning",
        "message": "Avoid console.log",
        "note": null,
        "language": "TypeScript",
        "labels": [
            {
                "text": "console.log(alpha)",
                "style": "primary",
                "range": native_range(),
                "empty": {},
                "nullable": null,
                "zero": 0,
                "flag": false
            },
            null,
            {}
        ],
        "lines": "noise",
        "charCount": {"leading": 0}
    });
    let projected = project_token_safe(0, &native);

    assert_eq!(projected.shape, RecordShape::Finding);
    assert_eq!(projected.value["ruleId"], "no-console");
    assert_eq!(projected.value["severity"], "warning");
    assert_eq!(projected.value["message"], "Avoid console.log");
    assert_eq!(projected.value["language"], "TypeScript");
    assert!(projected.value.get("note").is_none());
    assert!(projected.value.get("lines").is_none());
    assert!(projected.value.get("charCount").is_none());
    assert_eq!(projected.value["labels"].as_array().map(Vec::len), Some(1));
    let label = &projected.value["labels"][0];
    assert!(label["range"].get("byteOffset").is_none());
    assert!(label.get("empty").is_none());
    assert!(label.get("nullable").is_none());
    assert_eq!(label["zero"], 0);
    assert_eq!(label["flag"], false);
}

#[test]
fn sarif_finding_projection_normalizes_location_and_fix() {
    let projected = project_sarif_token_safe(
        6,
        &json!({
            "ruleId": "no-console",
            "level": "warning",
            "message": {"text": "avoid console.log"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": "src/main.ts"},
                    "region": {
                        "startLine": 2,
                        "startColumn": 1,
                        "endLine": 2,
                        "endColumn": 19,
                        "snippet": {"text": "console.log(value)"},
                        "byteOffset": 10
                    }
                }
            }],
            "fixes": [{
                "artifactChanges": [{
                    "artifactLocation": {"uri": "src/main.ts"},
                    "replacements": [{
                        "insertedContent": {"text": "logger.info(value)"}
                    }]
                }]
            }]
        }),
    );

    assert_eq!(projected.ordinal, 6);
    assert_eq!(projected.shape, RecordShape::Finding);
    assert_eq!(
        projected.value,
        json!({
            "file": "src/main.ts",
            "range": {
                "start": {"line": 1, "column": 0},
                "end": {"line": 1, "column": 18}
            },
            "text": "console.log(value)",
            "ruleId": "no-console",
            "severity": "warning",
            "message": "avoid console.log",
            "replacement": "logger.info(value)"
        })
    );
}

#[test]
fn required_empty_values_survive_but_empty_optional_branches_do_not() {
    let projected = project_token_safe(
        3,
        &json!({
            "file": "",
            "range": {
                "start": {"line": 0, "column": 0},
                "end": {"line": 0, "column": 0}
            },
            "text": "",
            "replacement": "",
            "metaVariables": {"single": {}, "multi": []}
        }),
    );
    assert_eq!(projected.shape, RecordShape::Match);
    assert_eq!(projected.value["file"], "");
    assert_eq!(projected.value["text"], "");
    assert_eq!(projected.value["replacement"], "");
    assert_eq!(projected.value["range"]["start"]["line"], 0);
    assert!(projected.value.get("metaVariables").is_none());
}

#[test]
fn partial_or_non_record_shapes_become_opaque_stubs() {
    let cases = [
        (json!({"file": "a", "text": "x"}), "object"),
        (
            json!({
                "file": "a",
                "text": "x",
                "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 1}},
                "ruleId": "partial"
            }),
            "object",
        ),
        (json!([1, 2]), "array"),
        (json!("text"), "string"),
        (json!(1), "number"),
        (json!(false), "boolean"),
        (Value::Null, "null"),
    ];
    for (ordinal, (native, expected_type)) in cases.iter().enumerate() {
        let projected = project_token_safe(ordinal as u64, native);
        assert!(projected.is_opaque_unknown());
        assert_eq!(projected.value["_sgy_result"], ordinal as u64);
        assert_eq!(projected.value["_sgy_unknown"], true);
        assert_eq!(projected.value["json_type"], *expected_type);
        assert_eq!(projected.value.as_object().map(|map| map.len()), Some(3));
    }
}

#[test]
fn custom_keep_supports_escapes_wildcards_and_sequence_inheritance() {
    let native = json!({
        "file": "src/a.ts",
        "labels": [
            {"text": "first", "style": "primary", "drop": 1},
            {"text": "second", "style": "secondary", "drop": 2}
        ],
        "meta.key": "dot",
        "*": "literal-star",
        "comma,key": "comma",
        "slash\\name": "slash",
        "unused": true
    });
    let token_safe = project_token_safe(9, &json!(["unknown"]));
    let keep = FieldPaths::parse(r"labels.*,meta\.key,\*,comma\,key,slash\\name")
        .expect("valid escaped paths");
    let prune = FieldPaths::parse("labels.style").expect("valid prune path");
    let projected = project_custom(&native, &token_safe, Some(&keep), &prune);
    let projected_record = project_custom_record(&native, &token_safe, Some(&keep), &prune);

    assert_eq!(keep.len(), 5);
    assert_eq!(projected_record.ordinal, 9);
    assert_eq!(projected_record.shape, RecordShape::Unknown);
    assert_eq!(projected_record.value, projected);
    assert_eq!(projected["meta.key"], "dot");
    assert_eq!(projected["*"], "literal-star");
    assert_eq!(projected["comma,key"], "comma");
    assert_eq!(projected["slash\\name"], "slash");
    assert!(projected.get("unused").is_none());
    assert_eq!(projected["labels"].as_array().map(Vec::len), Some(2));
    assert!(projected["labels"][0].get("style").is_none());
    assert_eq!(projected["labels"][0]["text"], "first");
    assert_eq!(projected["labels"][1]["drop"], 2);
}

#[test]
fn custom_without_keep_starts_from_token_safe_and_prune_wins() {
    let native = json!({
        "file": "src/a.ts",
        "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 1}},
        "text": "x",
        "lines": "noise"
    });
    let token_safe = project_token_safe(2, &native);
    let prune = FieldPaths::parse("text,lines").expect("valid prune paths");
    let projected = project_custom(&native, &token_safe, None, &prune);
    assert!(projected.get("text").is_none());
    assert!(projected.get("lines").is_none());
    assert_eq!(projected["file"], "src/a.ts");

    let unknown = project_token_safe(7, &json!({"future": true}));
    let marker_prune = FieldPaths::parse("_sgy_result,json_type").expect("valid fields");
    assert_eq!(
        project_custom(&json!({"future": true}), &unknown, None, &marker_prune),
        unknown.value,
        "opaque stub markers must remain inseparable"
    );
}

#[test]
fn invalid_or_duplicate_field_paths_are_rejected() {
    for invalid in ["", "a..b", ".a", "a.", "a,", "a\\q", "a*", "*a"] {
        assert!(FieldPaths::parse(invalid).is_err(), "path {invalid:?}");
    }
    assert!(matches!(
        FieldPaths::parse("a.b,a.b"),
        Err(FieldPathError::Duplicate { path_index: 1 })
    ));
    assert_eq!(
        FieldPaths::parse("a\\q")
            .expect_err("invalid escape")
            .wrapper_exit_code(),
        125
    );
    assert!(FieldPaths::default().is_empty());
}
