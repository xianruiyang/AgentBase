use serde_json::{json, Value};
use sgy_core::{
    aggregate::{AggregateError, ContextAggregator, MAX_AGGREGATION_KEYS, MAX_GROUP_ENTRIES},
    budget::BudgetSettings,
    invocation::Profile,
    profile::{project_location_record, project_token_safe, ProjectedRecord},
};

fn native_match(file: &str, text: &str) -> Value {
    json!({
        "file": file,
        "range": {
            "start": { "line": 0, "column": 1 },
            "end": { "line": 0, "column": 2 },
        },
        "text": text,
    })
}

fn native_finding(file: &str, rule: &str, severity: &str) -> Value {
    let mut value = native_match(file, "finding");
    value["ruleId"] = Value::String(rule.to_owned());
    value["severity"] = Value::String(severity.to_owned());
    value["message"] = Value::String("message".to_owned());
    value
}

fn projected(ordinal: u64, native: Value) -> ProjectedRecord {
    project_token_safe(ordinal, &native)
}

fn roomy_settings(max_details: u32) -> BudgetSettings {
    BudgetSettings::new(max_details, 400, 1_000_000).expect("valid roomy settings")
}

#[test]
fn distinct_group_keys_are_explicitly_bounded() {
    let mut aggregate =
        ContextAggregator::new(Profile::Files, roomy_settings(1)).expect("aggregator");
    for ordinal in 0..=MAX_AGGREGATION_KEYS {
        let record = projected(
            ordinal as u64,
            native_match(&format!("src/{ordinal}.ts"), "match"),
        );
        let outcome = aggregate.push_file(&record);
        if ordinal < MAX_AGGREGATION_KEYS {
            outcome.expect("key below cardinality limit");
        } else {
            assert_eq!(
                outcome,
                Err(AggregateError::GroupCardinality {
                    dimension: "file",
                    limit: MAX_AGGREGATION_KEYS,
                })
            );
        }
    }
}

#[test]
fn small_token_safe_context_has_fixed_envelope_and_no_overflow() {
    let mut aggregate =
        ContextAggregator::new(Profile::TokenSafe, roomy_settings(40)).expect("aggregator");
    aggregate
        .push_token_safe(projected(0, native_match("src/a.ts", "a")))
        .expect("first");
    aggregate
        .push_token_safe(projected(1, native_match("src/b.ts", "b")))
        .expect("second");
    aggregate
        .push_token_safe(projected(2, native_match("src/a.ts", "c")))
        .expect("third");

    let outcome = aggregate.finish().expect("finish");
    let value = outcome.document.to_value();
    assert_eq!(
        value["_sgy"],
        json!({
            "schema": "sgy.context/v1",
            "profile": "token-safe",
            "total": 3,
            "shown": 3,
            "omitted": 0,
            "files": 2,
            "complete": true,
        })
    );
    assert_eq!(value["results"].as_array().expect("results").len(), 3);
    assert!(value.get("overflow").is_none());
    assert_eq!(outcome.document.total(), 3);
    assert_eq!(outcome.document.shown(), 3);
    assert_eq!(outcome.document.omitted(), 0);
}

#[test]
fn locations_context_keeps_completeness_and_uses_compact_safe_yaml() {
    let mut aggregate =
        ContextAggregator::new(Profile::Locations, roomy_settings(40)).expect("aggregator");
    for (ordinal, native) in [
        native_match("src/a.ts", "first"),
        native_match("src/b.ts", "second"),
    ]
    .into_iter()
    .enumerate()
    {
        let token_safe = projected(ordinal as u64, native);
        aggregate
            .push_location(&token_safe, project_location_record(&token_safe))
            .expect("location");
    }

    let outcome = aggregate.finish().expect("finish");
    let value = outcome.document.to_value();
    assert_eq!(value["_sgy"]["profile"], "locations");
    assert_eq!(value["_sgy"]["complete"], true);
    assert_eq!(
        value["results"],
        json!(["src/a.ts:0:1-0:2", "src/b.ts:0:1-0:2"])
    );

    let mut encoded = Vec::new();
    outcome
        .document
        .write_yaml(&mut encoded)
        .expect("compact YAML");
    assert_eq!(encoded.first(), Some(&b'{'));
    assert!(!encoded.windows(7).any(|window| window == b"\"text\""));
}

#[test]
fn overflow_counts_only_omitted_records_and_preserves_native_detail_order() {
    let mut aggregate =
        ContextAggregator::new(Profile::TokenSafe, roomy_settings(2)).expect("aggregator");
    for (ordinal, native) in [
        native_finding("shown-a.ts", "shown", "info"),
        native_finding("shown-b.ts", "shown", "info"),
        native_finding("src/a.ts", "rule-a", "warning"),
        native_finding("src/a.ts", "rule-a", "warning"),
        native_finding("src/b.ts", "rule-b", "error"),
    ]
    .into_iter()
    .enumerate()
    {
        aggregate
            .push_token_safe(projected(ordinal as u64, native))
            .expect("push");
    }

    let value = aggregate.finish().expect("finish").document.to_value();
    let results = value["results"].as_array().expect("results");
    assert_eq!(results[0]["file"], "shown-a.ts");
    assert_eq!(results[1]["file"], "shown-b.ts");
    assert_eq!(
        value["overflow"]["by_file"],
        json!({"src/a.ts": 2, "src/b.ts": 1})
    );
    assert_eq!(
        value["overflow"]["by_rule"],
        json!({"rule-a": 2, "rule-b": 1})
    );
    assert_eq!(
        value["overflow"]["by_severity"],
        json!({"warning": 2, "error": 1})
    );
    assert_eq!(value["_sgy"]["total"], 5);
    assert_eq!(value["_sgy"]["omitted"], 3);
    assert_eq!(value["_sgy"]["complete"], false);
}

#[test]
fn top_groups_are_bounded_sorted_and_keep_exact_rest_and_unattributed() {
    let mut aggregate =
        ContextAggregator::new(Profile::TokenSafe, roomy_settings(1)).expect("aggregator");
    aggregate
        .push_token_safe(projected(0, native_match("shown.ts", "")))
        .expect("shown");
    aggregate
        .push_token_safe(projected(1, native_match("a.ts", "")))
        .expect("a1");
    aggregate
        .push_token_safe(projected(2, native_match("a.ts", "")))
        .expect("a2");
    let mut ordinal = 3_u64;
    for index in 0..20 {
        aggregate
            .push_token_safe(projected(
                ordinal,
                native_match(&format!("f{index:02}.ts"), ""),
            ))
            .expect("file");
        ordinal += 1;
    }
    aggregate
        .push_token_safe(projected(ordinal, json!({"unknown": true})))
        .expect("unknown");

    let value = aggregate.finish().expect("finish").document.to_value();
    let by_file = value["overflow"]["by_file"].as_object().expect("file map");
    assert_eq!(by_file.len(), MAX_GROUP_ENTRIES);
    let keys = by_file.keys().cloned().collect::<Vec<_>>();
    assert_eq!(keys[0], "a.ts");
    assert_eq!(keys[1], "f00.ts");
    assert_eq!(keys.last().expect("last"), "f18.ts");
    assert_eq!(value["overflow"]["by_file_rest"], 1);
    assert_eq!(value["overflow"]["by_file_unattributed"], 1);
    let displayed: u64 = by_file
        .values()
        .map(|count| count.as_u64().expect("count"))
        .sum();
    assert_eq!(
        displayed + 1 + 1,
        value["_sgy"]["omitted"].as_u64().expect("omitted")
    );
    assert!(value["overflow"].get("by_rule").is_none());
    assert!(value["overflow"].get("by_rule_unattributed").is_none());
}

#[test]
fn byte_budget_tail_removal_updates_overflow_without_losing_totals() {
    let file = format!("src/{}.ts", "long-path-".repeat(20));
    let build = |settings| {
        let mut aggregate = ContextAggregator::new(Profile::TokenSafe, settings).expect("builder");
        for ordinal in 0..3 {
            aggregate
                .push_token_safe(projected(ordinal, native_match(&file, "")))
                .expect("push");
        }
        aggregate.finish().expect("finish")
    };

    let reference = build(BudgetSettings::new(1, 0, 1_000_000).expect("valid"));
    let target = reference.budget.yaml_bytes;
    let fitted = build(BudgetSettings::new(40, 0, target).expect("valid"));
    let value = fitted.document.to_value();
    assert_eq!(value["_sgy"]["total"], 3);
    assert_eq!(value["_sgy"]["shown"], 1);
    assert_eq!(value["_sgy"]["omitted"], 2);
    assert_eq!(value["overflow"]["by_file"][&file], 2);
    assert_eq!(fitted.budget.removed_results, 2);
    assert!(fitted.budget.yaml_bytes <= target);
}

#[test]
fn real_document_group_trimming_moves_counts_to_rest_exactly() {
    let build = |limit| {
        let mut aggregate = ContextAggregator::new(
            Profile::TokenSafe,
            BudgetSettings::new(1, 0, limit).expect("valid"),
        )
        .expect("builder");
        aggregate
            .push_token_safe(projected(0, native_match("shown.ts", "")))
            .expect("shown");
        for ordinal in 1..=25 {
            aggregate
                .push_token_safe(projected(
                    ordinal,
                    native_match(&format!("src/{}-{ordinal}.ts", "group-key".repeat(5)), ""),
                ))
                .expect("omitted");
        }
        aggregate.finish().expect("finish")
    };

    let full = build(1_000_000);
    let trimmed = build(full.budget.yaml_bytes - 1);
    let value = trimmed.document.to_value();
    let by_file = value["overflow"]["by_file"]
        .as_object()
        .expect("file group");
    let displayed: u64 = by_file
        .values()
        .map(|count| count.as_u64().expect("count"))
        .sum();
    let rest = value["overflow"]["by_file_rest"].as_u64().expect("rest");
    let unattributed = value["overflow"]
        .get("by_file_unattributed")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    assert!(trimmed.budget.removed_group_entries > 0);
    assert_eq!(displayed + rest + unattributed, 25);
    assert_eq!(trimmed.document.total(), 26);
    assert_eq!(trimmed.document.shown(), 1);
}

#[test]
fn unknown_and_value_truncation_make_context_incomplete() {
    let mut unknown =
        ContextAggregator::new(Profile::TokenSafe, roomy_settings(40)).expect("aggregator");
    unknown
        .push_token_safe(projected(0, json!({"unknown": true})))
        .expect("push unknown");
    let unknown_value = unknown
        .finish()
        .expect("finish unknown")
        .document
        .to_value();
    assert_eq!(unknown_value["_sgy"]["complete"], false);
    assert_eq!(unknown_value["_sgy"]["omitted"], 0);

    let mut truncated = ContextAggregator::new(
        Profile::TokenSafe,
        BudgetSettings::new(40, 3, 1_000_000).expect("valid"),
    )
    .expect("aggregator");
    truncated
        .push_token_safe(projected(0, native_match("src/a.ts", "a😀中e")))
        .expect("push truncated");
    let truncated_value = truncated
        .finish()
        .expect("finish truncated")
        .document
        .to_value();
    assert_eq!(truncated_value["_sgy"]["complete"], false);
    assert_eq!(truncated_value["results"][0]["text"], "a😀中");
    assert_eq!(truncated_value["results"][0]["_sgy_result"], 0);
}

#[test]
fn custom_explicit_projection_does_not_inherit_unknown_incompleteness() {
    let source = projected(0, json!({"custom": "source"}));
    let displayed = ProjectedRecord {
        ordinal: 0,
        shape: source.shape,
        value: json!({"custom": "source"}),
    };
    let mut aggregate =
        ContextAggregator::new(Profile::Custom, roomy_settings(40)).expect("aggregator");
    aggregate
        .push_custom(&source, displayed)
        .expect("custom record");
    let value = aggregate.finish().expect("finish").document.to_value();
    assert_eq!(value["_sgy"]["profile"], "custom");
    assert_eq!(value["_sgy"]["complete"], true);
    assert_eq!(value["results"][0], json!({"custom": "source"}));
}

#[test]
fn files_profile_uses_the_same_source_pass_and_never_emits_results_or_overflow() {
    let mut aggregate =
        ContextAggregator::new(Profile::Files, roomy_settings(40)).expect("aggregator");
    for (ordinal, native) in [
        native_match("src/b.ts", ""),
        native_match("src/a.ts", ""),
        native_match("src/a.ts", ""),
        json!({"unknown": true}),
    ]
    .into_iter()
    .enumerate()
    {
        let source = projected(ordinal as u64, native);
        aggregate.push_file(&source).expect("file record");
    }
    let value = aggregate.finish().expect("finish").document.to_value();
    assert_eq!(value["_sgy"]["profile"], "files");
    assert_eq!(value["_sgy"]["total"], 4);
    assert_eq!(value["_sgy"]["shown"], 0);
    assert_eq!(value["_sgy"]["omitted"], 4);
    assert_eq!(value["_sgy"]["files"], 2);
    assert_eq!(value["_sgy"]["complete"], false);
    assert_eq!(value["files"], json!({"src/a.ts": 2, "src/b.ts": 1}));
    assert_eq!(value["files_unattributed"], 1);
    assert!(value.get("results").is_none());
    assert!(value.get("overflow").is_none());
}

#[test]
fn empty_files_profile_is_complete_and_keeps_an_empty_file_map() {
    let aggregate = ContextAggregator::new(Profile::Files, roomy_settings(40)).expect("aggregator");
    let value = aggregate.finish().expect("finish").document.to_value();
    assert_eq!(value["_sgy"]["total"], 0);
    assert_eq!(value["_sgy"]["complete"], true);
    assert_eq!(value["files"], json!({}));
    assert!(value.get("files_rest").is_none());
    assert!(value.get("files_unattributed").is_none());
}

#[test]
fn committed_cache_reference_is_emitted_only_when_supplied() {
    let mut aggregate =
        ContextAggregator::new(Profile::TokenSafe, roomy_settings(40)).expect("aggregator");
    aggregate.set_cache_id("01JTESTCACHE000000000000000");
    aggregate
        .push_token_safe(projected(0, native_match("src/a.ts", "a")))
        .expect("record");
    let value = aggregate.finish().expect("finish").document.to_value();
    assert_eq!(
        value["_sgy"]["cache"],
        Value::String("01JTESTCACHE000000000000000".to_owned())
    );
}

#[test]
fn yaml_preserves_fixed_envelope_and_count_ranked_mapping_order() {
    let mut aggregate =
        ContextAggregator::new(Profile::Files, roomy_settings(40)).expect("aggregator");
    for (ordinal, file) in ["z.ts", "a.ts", "z.ts"].into_iter().enumerate() {
        let source = projected(ordinal as u64, native_match(file, ""));
        aggregate.push_file(&source).expect("file");
    }
    let outcome = aggregate.finish().expect("finish");
    let mut yaml = Vec::new();
    outcome.document.write_yaml(&mut yaml).expect("yaml");
    let yaml = String::from_utf8(yaml).expect("UTF-8");
    let schema = yaml.find("\"schema\"").expect("schema");
    let profile = yaml.find("\"profile\"").expect("profile");
    let total = yaml.find("\"total\"").expect("total");
    let z_file = yaml.rfind("\"z.ts\"").expect("z file");
    let a_file = yaml.rfind("\"a.ts\"").expect("a file");
    assert!(schema < profile && profile < total);
    assert!(z_file < a_file, "higher count must render first: {yaml}");
}

#[test]
fn profile_operations_and_native_order_fail_deterministically() {
    assert!(matches!(
        ContextAggregator::new(Profile::Lossless, roomy_settings(40)),
        Err(AggregateError::LosslessProfile)
    ));
    let mut files = ContextAggregator::new(Profile::Files, roomy_settings(40)).expect("files");
    let error = files
        .push_token_safe(projected(0, native_match("a.ts", "")))
        .expect_err("wrong operation");
    assert!(matches!(error, AggregateError::ProfileOperation { .. }));
    assert_eq!(error.wrapper_exit_code(), 122);

    let mut token = ContextAggregator::new(Profile::TokenSafe, roomy_settings(40)).expect("token");
    let error = token
        .push_token_safe(projected(1, native_match("a.ts", "")))
        .expect_err("out of order");
    assert!(matches!(
        error,
        AggregateError::NativeOrder {
            expected: 0,
            actual: 1
        }
    ));
}
