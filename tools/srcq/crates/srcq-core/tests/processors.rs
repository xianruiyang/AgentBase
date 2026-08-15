use std::io::Cursor;

use serde_json::{json, Value};
use srcq_core::{
    codec::parse_yaml_documents,
    processors::{process_yaml, Operation, ProcessError, ProcessLimits, Processor},
};

fn run(input: &[u8], operation: Operation) -> Result<Vec<Value>, ProcessError> {
    let mut output = Vec::new();
    process_yaml(
        Cursor::new(input),
        &mut output,
        operation,
        ProcessLimits::default(),
    )?;
    Ok(parse_yaml_documents(&output).expect("processor output is safe YAML"))
}

#[test]
fn validate_accepts_streams_reports_schemas_and_does_not_guess_unknown_sgy_data() {
    let input = br#"---
"file": "src/a.ts"
"severity": "warning"
---
"_sgy":
  "schema": "sgy.future/v9"
"payload": true
"#;
    let report = &run(input, Operation::Validate).expect("validate")[0];
    assert_eq!(report["valid"], true);
    assert_eq!(report["documents"], 2);
    assert_eq!(report["records"], 2);
    assert_eq!(report["schemas"][0]["name"], "generic");
    assert_eq!(report["schemas"][0]["recognized"], true);
    assert_eq!(report["schemas"][1]["name"], "sgy.future/v9");
    assert_eq!(report["schemas"][1]["recognized"], false);

    let error = run(input, Operation::Count).expect_err("unknown schema must not be guessed");
    assert!(matches!(error, ProcessError::Schema { document: 2, .. }));
}

#[test]
fn select_and_filter_transform_records_but_preserve_completeness_and_write_metadata() {
    let input = br#""_sgy":
  "complete": false
  "omitted": 7
  "write":
    "requested": "preview"
"results":
  - "file": "src/a.ts"
    "severity": "warning"
    "text": "a"
  - "file": "src/b.ts"
    "severity": "error"
    "text": "b"
"#;
    let selected = &run(
        input,
        Operation::select("file,severity").expect("select fields"),
    )
    .expect("select")[0];
    assert_eq!(selected["_sgy"]["complete"], false);
    assert_eq!(selected["_sgy"]["omitted"], 7);
    assert_eq!(selected["_sgy"]["write"]["requested"], "preview");
    assert_eq!(selected["_sgy"]["process"]["operation"], "select");
    assert!(selected["results"][0].get("text").is_none());
    assert_eq!(selected["results"][1]["file"], "src/b.ts");

    let filtered = &run(
        input,
        Operation::filter("severity", r#""warning""#).expect("filter operation"),
    )
    .expect("filter")[0];
    assert_eq!(filtered["results"].as_array().expect("results").len(), 1);
    assert_eq!(filtered["results"][0]["file"], "src/a.ts");
    assert_eq!(filtered["_sgy"]["complete"], false);
    assert_eq!(filtered["_sgy"]["process"]["input_records"], 2);
    assert_eq!(filtered["_sgy"]["process"]["output_records"], 1);
}

#[test]
fn count_and_group_are_deterministic_for_documents_arrays_and_missing_values() {
    let input = br#"---
- "severity": "warning"
- "severity": "error"
---
"severity": "warning"
---
"file": "missing.ts"
"#;
    let count = &run(input, Operation::Count).expect("count")[0];
    assert_eq!(count["documents"], 3);
    assert_eq!(count["records"], 4);

    let grouped =
        &run(input, Operation::group("severity").expect("group field")).expect("group")[0];
    assert_eq!(
        grouped["groups"],
        json!([
            {"missing": true, "count": 1},
            {"key": "error", "count": 1},
            {"key": "warning", "count": 2},
        ])
    );
}

#[test]
fn empty_stream_is_a_valid_empty_result() {
    let count = &run(b"", Operation::Count).expect("empty count")[0];
    assert_eq!(count["documents"], 0);
    assert_eq!(count["records"], 0);
    let validate = &run(b"", Operation::Validate).expect("empty validate")[0];
    assert_eq!(validate["valid"], true);
}

#[test]
fn streamed_processing_keeps_only_one_bounded_document_at_a_time() {
    let mut input = Vec::new();
    for ordinal in 0..20_000 {
        input.extend_from_slice(format!("---\n\"ordinal\": {ordinal}\n").as_bytes());
    }
    let mut output = Vec::new();
    process_yaml(
        Cursor::new(input),
        &mut output,
        Operation::Count,
        ProcessLimits {
            max_document_bytes: 64,
            max_total_bytes: 2 * 1024 * 1024,
            ..ProcessLimits::default()
        },
    )
    .expect("bounded large stream");
    let report = &parse_yaml_documents(&output).expect("count YAML")[0];
    assert_eq!(report["documents"], 20_000);
    assert_eq!(report["records"], 20_000);
}

#[test]
fn unsafe_yaml_depth_size_nodes_and_group_cardinality_are_rejected() {
    for unsafe_yaml in [
        b"\"a\": &anchor \"value\"\n\"b\": *anchor\n".as_slice(),
        b"\"a\": !!str \"value\"\n".as_slice(),
    ] {
        let error = run(unsafe_yaml, Operation::Validate).expect_err("unsafe YAML");
        assert!(matches!(error, ProcessError::Codec(_)));
    }

    let mut nested = String::new();
    for depth in 0..12 {
        nested.push_str(&format!("{}\"d{depth}\":\n", "  ".repeat(depth)));
    }
    nested.push_str(&format!("{}\"leaf\": true\n", "  ".repeat(12)));
    let mut output = Vec::new();
    let error = process_yaml(
        Cursor::new(nested),
        &mut output,
        Operation::Validate,
        ProcessLimits {
            max_depth: 8,
            ..ProcessLimits::default()
        },
    )
    .expect_err("depth limit");
    assert!(matches!(error, ProcessError::Codec(_)));

    let error = process_yaml(
        Cursor::new(b"\"field\": \"value longer than limit\"\n"),
        &mut Vec::new(),
        Operation::Validate,
        ProcessLimits {
            max_document_bytes: 16,
            ..ProcessLimits::default()
        },
    )
    .expect_err("size limit");
    assert!(matches!(error, ProcessError::Limit(_)));

    let node_heavy = br#"- 1
- 2
- 3
- 4
"#;
    let error = process_yaml(
        Cursor::new(node_heavy),
        &mut Vec::new(),
        Operation::Validate,
        ProcessLimits {
            max_nodes_per_document: 3,
            ..ProcessLimits::default()
        },
    )
    .expect_err("node limit");
    assert!(matches!(error, ProcessError::Codec(_)));

    let mut processor = Processor::new(
        Operation::group("kind").expect("group"),
        ProcessLimits {
            max_groups: 2,
            ..ProcessLimits::default()
        },
    );
    let mut sink = Vec::new();
    processor
        .push(json!({"kind": "a"}), &mut sink)
        .expect("group a");
    processor
        .push(json!({"kind": "b"}), &mut sink)
        .expect("group b");
    let error = processor
        .push(json!({"kind": "c"}), &mut sink)
        .expect_err("group cardinality");
    assert!(matches!(error, ProcessError::Limit(_)));
}

#[test]
fn filter_is_json_equality_only_and_group_rejects_complex_keys() {
    assert!(Operation::filter("severity", "severity == 'warning'").is_err());
    assert!(Operation::filter("a,b", "true").is_err());
    let error = run(
        b"\"labels\":\n  \"kind\": \"warning\"\n",
        Operation::group("labels").expect("group operation"),
    )
    .expect_err("complex group key");
    assert!(matches!(error, ProcessError::InvalidArgument(_)));
}
