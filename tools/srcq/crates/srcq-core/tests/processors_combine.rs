use std::io::Cursor;

use serde_json::{json, Value};
use srcq_core::{
    codec::parse_yaml_documents,
    processors::{
        jsonl_to_yaml, yaml_to_jsonl, CollectionBuilder, CollectionOperation, CollectionSource,
        ConflictPolicy, ProcessError, ProcessLimits,
    },
};

fn source(id: &str, scope: &str, engine: &str) -> CollectionSource {
    CollectionSource::new(
        id,
        scope,
        json!({"kind": "fixture", "engine": engine, "cwd": scope}),
    )
    .expect("source")
}

fn range(line: u64) -> Value {
    json!({
        "start": {"line": line, "column": 0},
        "end": {"line": line, "column": 1},
    })
}

fn finding(file: &str, line: u64, severity: &str, text: &str) -> Value {
    json!({
        "file": file,
        "range": range(line),
        "ruleId": "rule",
        "severity": severity,
        "text": text,
    })
}

fn finish(builder: CollectionBuilder) -> Result<Vec<Value>, ProcessError> {
    let mut output = Vec::new();
    builder.finish(&mut output)?;
    Ok(parse_yaml_documents(&output).expect("collection YAML"))
}

#[test]
fn sort_is_stable_and_external_runs_preserve_global_order() {
    let mut builder = CollectionBuilder::new(
        CollectionOperation::sort("severity", false).expect("sort"),
        ProcessLimits::default(),
    )
    .expect("builder");
    builder
        .add_source(source("input", "cwd:A", "engine-1"))
        .expect("add source");
    let mut values = Vec::new();
    for ordinal in 0..20_050_u64 {
        values.push(json!({
            "ordinal": ordinal,
            "severity": if ordinal % 2 == 0 { "warning" } else { "error" },
        }));
    }
    builder
        .push_document("input", Value::Array(values))
        .expect("records");
    let documents = finish(builder).expect("sort output");
    assert_eq!(documents[0]["_sgy"]["operation"], "sort");
    assert_eq!(documents[0]["_sgy"]["records"], 20_050);
    let records = &documents[1..];
    assert_eq!(records[0]["severity"], "error");
    assert_eq!(records[0]["ordinal"], 1);
    assert_eq!(records[1]["ordinal"], 3);
    assert_eq!(records[10_024]["ordinal"], 20_049);
    assert_eq!(records[10_025]["severity"], "warning");
    assert_eq!(records[10_025]["ordinal"], 0);
    assert_eq!(records.last().expect("last")["ordinal"], 20_048);
}

#[test]
fn numeric_sort_is_exact_and_descending_keeps_equal_values_stable() {
    let values = json!([
        {"id": "ten", "number": 10},
        {"id": "two-a", "number": 2},
        {"id": "negative", "number": -10},
        {"id": "fraction-a", "number": 1.201},
        {"id": "fraction-b", "number": 1.2},
        {"id": "two-b", "number": 2},
        {"id": "zero", "number": 0},
    ]);
    let mut ascending = CollectionBuilder::new(
        CollectionOperation::sort("number", false).expect("sort"),
        ProcessLimits::default(),
    )
    .expect("builder");
    ascending
        .add_source(source("input", "cwd:A", "engine-1"))
        .expect("source");
    ascending
        .push_document("input", values.clone())
        .expect("values");
    let ascending = finish(ascending).expect("ascending");
    assert_eq!(
        ascending[1..]
            .iter()
            .map(|value| value["id"].as_str().expect("id"))
            .collect::<Vec<_>>(),
        [
            "negative",
            "zero",
            "fraction-b",
            "fraction-a",
            "two-a",
            "two-b",
            "ten",
        ]
    );

    let mut descending = CollectionBuilder::new(
        CollectionOperation::sort("number", true).expect("sort"),
        ProcessLimits::default(),
    )
    .expect("builder");
    descending
        .add_source(source("input", "cwd:A", "engine-1"))
        .expect("source");
    descending.push_document("input", values).expect("values");
    let descending = finish(descending).expect("descending");
    assert_eq!(
        descending[1..]
            .iter()
            .map(|value| value["id"].as_str().expect("id"))
            .collect::<Vec<_>>(),
        [
            "ten",
            "two-a",
            "two-b",
            "fraction-a",
            "fraction-b",
            "zero",
            "negative",
        ]
    );
}

#[test]
fn dedupe_preserves_first_order_and_refuses_non_identical_identity_collisions() {
    let first = finding("src/a.ts", 1, "warning", "first");
    let second = finding("src/b.ts", 2, "error", "second");
    let mut builder = CollectionBuilder::new(
        CollectionOperation::dedupe(ConflictPolicy::Error),
        ProcessLimits::default(),
    )
    .expect("builder");
    builder
        .add_source(source("input", "cwd:A", "engine-1"))
        .expect("source");
    builder
        .push_document(
            "input",
            json!([first.clone(), second.clone(), first.clone()]),
        )
        .expect("duplicates");
    let documents = finish(builder).expect("dedupe");
    assert_eq!(documents[0]["_sgy"]["input_records"], 3);
    assert_eq!(documents[0]["_sgy"]["records"], 2);
    assert_eq!(documents[0]["_sgy"]["duplicates"], 1);
    assert_eq!(documents[1], first);
    assert_eq!(documents[2], second);

    let mut conflict = CollectionBuilder::new(
        CollectionOperation::dedupe(ConflictPolicy::Error),
        ProcessLimits::default(),
    )
    .expect("conflict builder");
    conflict
        .add_source(source("input", "cwd:A", "engine-1"))
        .expect("source");
    conflict
        .push_document(
            "input",
            json!([
                finding("src/a.ts", 1, "warning", "first"),
                finding("src/a.ts", 1, "warning", "changed"),
            ]),
        )
        .expect("conflicting records");
    let error = finish(conflict).expect_err("identity conflict");
    assert!(matches!(error, ProcessError::Conflict { .. }));
}

#[test]
fn merge_tracks_engine_sources_conflicts_and_scopes_different_workspaces() {
    let record = finding("src/a.ts", 1, "warning", "first");
    let changed = finding("src/a.ts", 1, "warning", "changed");
    let mut builder = CollectionBuilder::new(
        CollectionOperation::merge(ConflictPolicy::KeepFirst),
        ProcessLimits::default(),
    )
    .expect("builder");
    builder
        .add_source(source("cache:A", "cwd:same", "engine-1"))
        .expect("source A");
    builder
        .add_source(source("cache:B", "cwd:same", "engine-2"))
        .expect("source B");
    builder
        .add_source(source("cache:C", "cwd:other", "engine-1"))
        .expect("source C");
    builder
        .push_document("cache:A", record.clone())
        .expect("record A");
    builder.push_document("cache:B", changed).expect("record B");
    builder
        .push_document("cache:C", record.clone())
        .expect("record C");
    let documents = finish(builder).expect("merge");
    let header = &documents[0]["_sgy"];
    assert_eq!(header["input_records"], 3);
    assert_eq!(header["records"], 2);
    assert_eq!(header["conflicts"], 1);
    assert_eq!(header["sources"][0]["engine"], "engine-1");
    assert_eq!(header["sources"][1]["engine"], "engine-2");
    assert_eq!(
        documents[1]["_sgy"]["source_ids"],
        json!(["cache:A", "cache:B"])
    );
    assert_eq!(documents[1]["_sgy"]["conflicts"], 1);
    assert_eq!(documents[1]["value"], record);
    assert_eq!(documents[2]["_sgy"]["source_ids"], json!(["cache:C"]));

    let mut chained = CollectionBuilder::new(
        CollectionOperation::sort("file", false).expect("sort"),
        ProcessLimits::default(),
    )
    .expect("chained builder");
    chained
        .add_source(source("pipeline", "pipeline", "srcq"))
        .expect("pipeline source");
    for document in documents {
        chained
            .push_document("pipeline", document)
            .expect("chained document");
    }
    let chained = finish(chained).expect("chained output");
    assert_eq!(chained[0]["_sgy"]["records"], 2);
    assert_eq!(
        chained[0]["_sgy"]["sources"][0]["upstream_sources"]
            .as_array()
            .expect("upstream sources")
            .len(),
        3
    );
    assert_eq!(chained[1]["file"], "src/a.ts");
}

#[test]
fn yaml_jsonl_round_trip_preserves_every_document_value_and_rejects_duplicate_keys() {
    let input = r#"---
"nested":
  "array":
    - 1
    - true
    - null
"text": "中文"
---
- "file": "src/a.ts"
  "range":
    "start":
      "line": 1
"#
    .as_bytes();
    let expected = parse_yaml_documents(input).expect("input YAML");
    let mut jsonl = Vec::new();
    yaml_to_jsonl(Cursor::new(input), &mut jsonl, ProcessLimits::default()).expect("to JSONL");
    assert_eq!(jsonl.iter().filter(|byte| **byte == b'\n').count(), 2);
    let mut yaml = Vec::new();
    jsonl_to_yaml(Cursor::new(&jsonl), &mut yaml, ProcessLimits::default()).expect("from JSONL");
    assert_eq!(
        parse_yaml_documents(&yaml).expect("round-trip YAML"),
        expected
    );

    let error = jsonl_to_yaml(
        Cursor::new(b"{\"a\":1,\"a\":2}\n"),
        &mut Vec::new(),
        ProcessLimits::default(),
    )
    .expect_err("duplicate JSON key");
    assert!(matches!(error, ProcessError::Codec(_)));

    let deeply_nested = format!("{}0{}\n", "[".repeat(129), "]".repeat(129));
    let error = jsonl_to_yaml(
        Cursor::new(deeply_nested.as_bytes()),
        &mut Vec::new(),
        ProcessLimits::default(),
    )
    .expect_err("deep JSON nesting");
    assert!(matches!(error, ProcessError::Codec(_)));

    let limits = ProcessLimits {
        max_document_bytes: 16,
        ..ProcessLimits::default()
    };
    let error = jsonl_to_yaml(
        Cursor::new(b"{\"value\":\"this line exceeds the limit\"}\n"),
        &mut Vec::new(),
        limits,
    )
    .expect_err("oversized JSONL record");
    assert!(matches!(error, ProcessError::Limit(_)));
}

#[test]
fn keep_first_conflict_is_explicit_and_source_metadata_survives_reordering() {
    let mut builder = CollectionBuilder::new(
        CollectionOperation::dedupe(ConflictPolicy::KeepFirst),
        ProcessLimits::default(),
    )
    .expect("builder");
    builder
        .add_source(source("input", "cwd:A", "engine-1"))
        .expect("source");
    builder
        .push_document(
            "input",
            json!({
                "_sgy": {
                    "complete": false,
                    "omitted": 9,
                    "write": {"requested": "preview", "transactional": false},
                },
                "results": [
                    finding("src/a.ts", 1, "warning", "first"),
                    finding("src/a.ts", 1, "warning", "changed"),
                ],
            }),
        )
        .expect("input");
    let documents = finish(builder).expect("keep-first");
    let source = &documents[0]["_sgy"]["sources"][0];
    assert_eq!(documents[0]["_sgy"]["conflicts"], 1);
    assert_eq!(source["complete"], false);
    assert_eq!(source["omitted"], 9);
    assert_eq!(source["write"][0]["requested"], "preview");
}
