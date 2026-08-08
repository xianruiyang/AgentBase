use serde_json::{json, Value};
use sgy_core::{
    budget::{
        fit_context_budget, BudgetError, BudgetSettings, ContextBudgetCandidate, DetailDisposition,
        DetailSelector, GroupDimension, DEFAULT_MAX_CONTEXT_BYTES, DEFAULT_MAX_DETAIL_RESULTS,
        DEFAULT_MAX_TEXT_CHARS,
    },
    codec::write_yaml_document,
    profile::{ProjectedRecord, RecordShape},
};

#[derive(Clone, Debug, Default, PartialEq)]
struct Groups {
    severity: Vec<(String, u64)>,
    rule: Vec<(String, u64)>,
    file: Vec<(String, u64)>,
    severity_rest: u64,
    rule_rest: u64,
    file_rest: u64,
}

#[derive(Clone, Debug, PartialEq)]
struct TestCandidate {
    records: Vec<ProjectedRecord>,
    total: u64,
    omitted: u64,
    groups: Groups,
    trim_log: Vec<GroupDimension>,
    cache_available: bool,
    padding: Option<String>,
    measurement_error: bool,
}

impl TestCandidate {
    fn new(records: Vec<ProjectedRecord>) -> Self {
        Self {
            total: u64::try_from(records.len()).expect("test record count fits u64"),
            records,
            omitted: 0,
            groups: Groups::default(),
            trim_log: Vec::new(),
            cache_available: false,
            padding: None,
            measurement_error: false,
        }
    }

    fn render(&self) -> Value {
        let group = |entries: &[(String, u64)], rest: u64| {
            json!({
                "entries": entries
                    .iter()
                    .map(|(key, count)| json!({ "key": key, "count": count }))
                    .collect::<Vec<_>>(),
                "rest": rest,
            })
        };
        let mut value = json!({
            "_sgy": {
                "total": self.total,
                "shown": self.records.len(),
                "omitted": self.omitted,
            },
            "results": self.records.iter().map(|record| record.value.clone()).collect::<Vec<_>>(),
            "overflow": {
                "by_severity": group(&self.groups.severity, self.groups.severity_rest),
                "by_rule": group(&self.groups.rule, self.groups.rule_rest),
                "by_file": group(&self.groups.file, self.groups.file_rest),
            },
        });
        if self.cache_available {
            value["_sgy"]["cache"] = json!({ "available": true });
        }
        if let Some(padding) = &self.padding {
            value["padding"] = Value::String(padding.clone());
        }
        value
    }

    fn measured_bytes(&self) -> u64 {
        let mut output = Vec::new();
        write_yaml_document(&self.render(), &mut output, false).expect("serialize test envelope");
        u64::try_from(output.len()).expect("test YAML length fits u64")
    }
}

impl ContextBudgetCandidate for TestCandidate {
    fn records(&self) -> &[ProjectedRecord] {
        &self.records
    }

    fn records_mut(&mut self) -> &mut Vec<ProjectedRecord> {
        &mut self.records
    }

    fn pop_last_record_to_overflow(&mut self) -> bool {
        if self.records.pop().is_none() {
            return false;
        }
        self.omitted += 1;
        true
    }

    fn trim_lowest_group_entry(&mut self, dimension: GroupDimension) -> bool {
        let (entries, rest) = match dimension {
            GroupDimension::Severity => (&mut self.groups.severity, &mut self.groups.severity_rest),
            GroupDimension::Rule => (&mut self.groups.rule, &mut self.groups.rule_rest),
            GroupDimension::File => (&mut self.groups.file, &mut self.groups.file_rest),
        };
        let Some((_, count)) = entries.pop() else {
            return false;
        };
        *rest += count;
        self.trim_log.push(dimension);
        true
    }

    fn measure_yaml_bytes(&self) -> Result<u64, String> {
        if self.measurement_error {
            Err("synthetic serializer failure".to_owned())
        } else {
            Ok(self.measured_bytes())
        }
    }

    fn has_minimum_locator(&self) -> bool {
        self.records.iter().any(|record| {
            let root = record.value.as_object();
            let has_file = root
                .and_then(|value| value.get("file"))
                .and_then(Value::as_str)
                .is_some_and(|file| !file.is_empty());
            let has_start = root
                .and_then(|value| value.get("range"))
                .and_then(|range| range.get("start"))
                .is_some_and(|start| start.get("line").is_some() && start.get("column").is_some());
            let has_result_id = root.and_then(|value| value.get("_sgy_result")).is_some();
            (has_file && has_start) || (self.cache_available && has_result_id)
        })
    }
}

fn record(ordinal: u64, text: Option<&str>) -> ProjectedRecord {
    let mut value = json!({
        "file": format!("src/file-{ordinal}.rs"),
        "range": { "start": { "line": ordinal, "column": 0 } },
    });
    if let Some(text) = text {
        value["text"] = Value::String(text.to_owned());
    }
    ProjectedRecord {
        ordinal,
        shape: RecordShape::Match,
        value,
    }
}

#[test]
fn settings_defaults_and_validation_are_frozen() {
    let defaults = BudgetSettings::default();
    assert_eq!(defaults.max_detail_results(), DEFAULT_MAX_DETAIL_RESULTS);
    assert_eq!(defaults.max_text_chars(), DEFAULT_MAX_TEXT_CHARS);
    assert_eq!(defaults.max_context_bytes(), DEFAULT_MAX_CONTEXT_BYTES);
    assert_eq!(
        BudgetSettings::new(2, 0, 99)
            .expect("valid")
            .max_text_chars(),
        0
    );
    assert!(matches!(
        BudgetSettings::new(0, 1, 1),
        Err(BudgetError::InvalidSetting(_))
    ));
    assert!(matches!(
        BudgetSettings::new(1, 1, 0),
        Err(BudgetError::InvalidSetting(_))
    ));
}

#[test]
fn detail_selector_keeps_native_first_n_and_counts_everything() {
    let mut selector = DetailSelector::new(BudgetSettings::new(2, 10, 100).expect("valid"));
    let dispositions = (0..5)
        .map(|_| selector.consider().expect("count record"))
        .collect::<Vec<_>>();
    assert_eq!(
        dispositions,
        vec![
            DetailDisposition::Show,
            DetailDisposition::Show,
            DetailDisposition::Omit,
            DetailDisposition::Omit,
            DetailDisposition::Omit,
        ]
    );
    assert_eq!(
        (selector.total(), selector.shown(), selector.omitted()),
        (5, 2, 3)
    );
}

#[test]
fn unicode_preview_and_capture_text_use_scalar_prefixes_and_markers() {
    let mut item = record(7, Some("a😀中e"));
    item.value["metaVariables"] = json!({
        "single": { "text": "甲😀乙丙" },
        "multi": [{ "text": "αβγδ" }],
    });
    let mut candidate = TestCandidate::new(vec![item]);
    let settings = BudgetSettings::new(40, 3, 1_000_000).expect("valid");
    let report = fit_context_budget(&mut candidate, settings).expect("fit");

    assert_eq!(candidate.records[0].value["text"], "a😀中");
    assert_eq!(
        candidate.records[0].value["metaVariables"]["single"]["text"],
        "甲😀乙"
    );
    assert_eq!(
        candidate.records[0].value["metaVariables"]["multi"][0]["text"],
        "αβγ"
    );
    assert_eq!(candidate.records[0].value["_sgy_result"], 7);
    assert_eq!(report.truncation_markers, 3);
    assert!(report.yaml_bytes <= settings.max_context_bytes());
}

#[test]
fn fit_applies_detail_cap_in_native_order() {
    let mut candidate = TestCandidate::new((0..50).map(|ordinal| record(ordinal, None)).collect());
    let settings = BudgetSettings::new(40, 400, 1_000_000).expect("valid");
    let report = fit_context_budget(&mut candidate, settings).expect("fit");

    assert_eq!(candidate.records.len(), 40);
    assert_eq!(candidate.records.first().expect("first").ordinal, 0);
    assert_eq!(candidate.records.last().expect("last").ordinal, 39);
    assert_eq!(candidate.omitted, 10);
    assert_eq!(report.removed_results, 10);
}

#[test]
fn adaptive_preview_chooses_largest_cap_that_fits_actual_yaml_bytes() {
    let original = TestCandidate::new(vec![record(0, Some(&"x".repeat(400)))]);
    let mut at_eighty = original.clone();
    let eighty = BudgetSettings::new(40, 80, 1_000_000).expect("valid");
    let target = fit_context_budget(&mut at_eighty, eighty)
        .expect("reference fit")
        .yaml_bytes;

    let mut candidate = original;
    let settings = BudgetSettings::new(40, 400, target).expect("valid");
    let report = fit_context_budget(&mut candidate, settings).expect("adaptive fit");
    assert_eq!(report.preview_cap, 80);
    assert_eq!(report.yaml_bytes, target);
    assert_eq!(
        candidate.records[0].value["text"]
            .as_str()
            .expect("text")
            .len(),
        80
    );
}

#[test]
fn byte_budget_drops_only_the_result_tail_and_keeps_one_locator() {
    let original = TestCandidate::new((0..3).map(|ordinal| record(ordinal, None)).collect());
    let mut one = original.clone();
    assert!(one.pop_last_record_to_overflow());
    assert!(one.pop_last_record_to_overflow());
    let target = one.measured_bytes();

    let mut candidate = original;
    let report = fit_context_budget(
        &mut candidate,
        BudgetSettings::new(40, 400, target).expect("valid"),
    )
    .expect("fit by dropping tail");
    assert_eq!(
        candidate
            .records
            .iter()
            .map(|item| item.ordinal)
            .collect::<Vec<_>>(),
        vec![0]
    );
    assert_eq!(report.removed_results, 2);
    assert_eq!(report.yaml_bytes, target);
}

#[test]
fn grouped_overflow_is_trimmed_in_severity_rule_file_cycles() {
    let mut original = TestCandidate::new(vec![record(0, None)]);
    original.groups.severity = vec![("high".to_owned(), 2), ("low".repeat(8), 1)];
    original.groups.rule = vec![("rule-a".to_owned(), 2), ("rule-z".repeat(8), 1)];
    original.groups.file = vec![("src/a.rs".to_owned(), 2), ("src/z.rs".repeat(8), 1)];

    let mut after_cycle = original.clone();
    assert!(after_cycle.trim_lowest_group_entry(GroupDimension::Severity));
    assert!(after_cycle.trim_lowest_group_entry(GroupDimension::Rule));
    assert!(after_cycle.trim_lowest_group_entry(GroupDimension::File));
    let target = after_cycle.measured_bytes();

    let mut candidate = original;
    let report = fit_context_budget(
        &mut candidate,
        BudgetSettings::new(40, 400, target).expect("valid"),
    )
    .expect("fit by trimming groups");
    assert_eq!(
        candidate.trim_log,
        vec![
            GroupDimension::Severity,
            GroupDimension::Rule,
            GroupDimension::File
        ]
    );
    assert_eq!(report.removed_group_entries, 3);
    assert_eq!(
        (
            candidate.groups.severity_rest,
            candidate.groups.rule_rest,
            candidate.groups.file_rest
        ),
        (1, 1, 1)
    );
}

#[test]
fn recovery_truncates_note_before_later_optional_fields() {
    let mut original = TestCandidate::new(vec![record(0, None)]);
    original.records[0].value["note"] = Value::String("n".repeat(60));
    original.records[0].value["labels"] = json!(["label-a", "label-b"]);
    original.records[0].value["message"] = Value::String("message".repeat(8));
    original.records[0].value["replacement"] = Value::String("replacement".repeat(8));

    let mut expected = original.clone();
    expected.records[0].value["note"] = Value::String("n".repeat(5));
    expected.records[0].value["_sgy_note_truncated"] = Value::Bool(true);
    expected.records[0].value["_sgy_result"] = Value::from(0);
    let target = expected.measured_bytes();

    let mut candidate = original;
    let report = fit_context_budget(
        &mut candidate,
        BudgetSettings::new(40, 0, target).expect("valid"),
    )
    .expect("fit by recovery");
    assert_eq!(candidate.records[0].value["note"], "nnnnn");
    assert_eq!(
        candidate.records[0].value["labels"],
        json!(["label-a", "label-b"])
    );
    assert_eq!(
        candidate.records[0].value["message"],
        "messagemessagemessagemessagemessagemessagemessagemessage"
    );
    assert!(candidate.records[0]
        .value
        .get("_sgy_labels_truncated")
        .is_none());
    assert!(report.used_recovery);
}

#[test]
fn impossible_minimum_and_measurement_failures_have_stable_codes() {
    let mut minimum = TestCandidate::new(vec![record(0, None)]);
    let error = fit_context_budget(&mut minimum, BudgetSettings::new(40, 0, 1).expect("valid"))
        .expect_err("minimum must not fit");
    assert!(matches!(error, BudgetError::Minimum { .. }));
    assert_eq!(error.wrapper_exit_code(), 124);

    let mut broken = TestCandidate::new(vec![record(0, None)]);
    broken.measurement_error = true;
    let error = fit_context_budget(&mut broken, BudgetSettings::default())
        .expect_err("measurement must fail");
    assert!(matches!(error, BudgetError::Measure(_)));
    assert_eq!(error.wrapper_exit_code(), 122);
}

#[test]
fn fitting_is_deterministic() {
    let mut first = TestCandidate::new(
        (0..4)
            .map(|ordinal| record(ordinal, Some(&"界".repeat(90))))
            .collect(),
    );
    first.groups.rule = vec![("rule-a".repeat(5), 3), ("rule-b".repeat(5), 1)];
    let limit = 700;
    let mut second = first.clone();
    let settings = BudgetSettings::new(3, 80, limit).expect("valid");
    let first_report = fit_context_budget(&mut first, settings).expect("first fit");
    let second_report = fit_context_budget(&mut second, settings).expect("second fit");
    assert_eq!(first, second);
    assert_eq!(first_report, second_report);
    assert!(first_report.yaml_bytes <= limit);
}
