use proptest::prelude::*;
use serde_json::Value;
use srcq_contract_tests::strategies::json_value;
use srcq_core::codec::{
    parse_single_json, parse_yaml_documents, parse_yaml_documents_with_limits, write_yaml_document,
    CodecError, YamlParseLimits,
};

proptest! {
    #![proptest_config(ProptestConfig::with_cases(384))]

    #[test]
    fn every_generated_json_value_round_trips_through_safe_yaml(value in json_value()) {
        let json = serde_json::to_vec(&value)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        let parsed_json = parse_single_json(&json)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        prop_assert_eq!(&parsed_json.value, &value);

        let mut yaml = Vec::new();
        write_yaml_document(&value, &mut yaml, false)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        let parsed_yaml = parse_yaml_documents(&yaml)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        prop_assert_eq!(parsed_yaml, vec![value]);
    }
}

#[test]
fn arbitrary_precision_numbers_unicode_and_empty_shapes_round_trip() {
    let source = r#"{"huge":1234567890123456789012345678901234567890,"tiny":1e-999,"text":"emoji \ud83e\uddea 中文","empty":{},"list":[],"nothing":null}"#.as_bytes();
    let record = parse_single_json(source).expect("valid arbitrary precision JSON");
    let mut yaml = Vec::new();
    write_yaml_document(&record.value, &mut yaml, false).expect("encode safe YAML");
    let parsed = parse_yaml_documents(&yaml).expect("parse emitted YAML");
    assert_eq!(parsed, vec![record.value]);
}

#[test]
fn duplicate_keys_and_depth_overflow_are_rejected_with_stable_classes() {
    let duplicate_json = parse_single_json(br#"{"a":1,"a":2}"#);
    assert!(matches!(
        duplicate_json,
        Err(CodecError::DuplicateJsonKey { .. })
    ));

    let duplicate_yaml = parse_yaml_documents(b"\"a\": 1\n\"a\": 2\n");
    assert!(matches!(duplicate_yaml, Err(CodecError::UnsafeYaml(_))));

    let mut nested = Value::Null;
    for _ in 0..20 {
        nested = Value::Array(vec![nested]);
    }
    let mut yaml = Vec::new();
    write_yaml_document(&nested, &mut yaml, false).expect("encode nested YAML");
    let result = parse_yaml_documents_with_limits(
        &yaml,
        YamlParseLimits {
            max_input_bytes: 64 * 1024,
            max_depth: 8,
            max_nodes: 1024,
            max_documents: 1,
        },
    );
    assert!(matches!(result, Err(CodecError::UnsafeYaml(_))));
}
