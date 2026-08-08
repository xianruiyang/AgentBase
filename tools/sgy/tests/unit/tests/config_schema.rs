use std::fs;

use proptest::prelude::*;
use serde_json::{Map, Value};
use sgy_contract_tests::strategies::{unicode_string, valid_field_name};
use sgy_core::{
    codec::write_yaml_document,
    config::{load_config_paths, ConfigError, CONFIG_SCHEMA},
    invocation::Profile,
};

proptest! {
    #![proptest_config(ProptestConfig::with_cases(128))]

    #[test]
    fn valid_project_schema_values_load_without_expanding_authority(
        profile in prop_oneof![
            Just("token-safe"), Just("lossless"), Just("files")
        ],
        native_defaults in any::<bool>(),
        max_details in 1_u32..10_000,
        max_text in any::<u16>(),
        max_bytes in 1_u64..1_000_000,
    ) {
        let value = serde_json::json!({
            "schema": CONFIG_SCHEMA,
            "profile": profile,
            "native_defaults": native_defaults,
            "max_detail_results": max_details,
            "max_text_chars": max_text,
            "max_context_bytes": max_bytes,
        });
        let directory = tempfile::tempdir().map_err(|error| TestCaseError::fail(error.to_string()))?;
        let project = directory.path().join(".sgy.yml");
        write_value(&project, &value).map_err(TestCaseError::fail)?;
        let loaded = load_config_paths(&project, None)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        let config = loaded.stack.project.ok_or_else(|| TestCaseError::fail("project config missing"))?;
        prop_assert!(config.engine.is_none());
        prop_assert!(config.cwd.is_none());
        prop_assert!(config.cache_mode.is_none());
        prop_assert_eq!(config.native_defaults, Some(native_defaults));
        prop_assert_eq!(config.max_detail_results, Some(max_details));
        prop_assert_eq!(config.max_text_chars, Some(u32::from(max_text)));
        prop_assert_eq!(config.max_context_bytes, Some(max_bytes));
        prop_assert_eq!(
            config.profile,
            Some(match profile {
                "token-safe" => Profile::TokenSafe,
                "lossless" => Profile::Lossless,
                "files" => Profile::Files,
                _ => unreachable!("strategy only emits known profiles"),
            }),
        );
    }

    #[test]
    fn unknown_schema_fields_are_always_rejected(
        field in valid_field_name().prop_filter("must be unknown", |field| {
            !matches!(field.as_str(),
                "schema" | "engine" | "cwd" | "profile" | "native_defaults" | "cache"
                | "max_detail_results" | "max_text_chars" | "max_context_bytes"
                | "keep_fields" | "prune_fields")
        }),
        value in unicode_string(24),
    ) {
        let mut mapping = Map::new();
        mapping.insert("schema".to_owned(), Value::String(CONFIG_SCHEMA.to_owned()));
        mapping.insert(field, Value::String(value));
        let directory = tempfile::tempdir().map_err(|error| TestCaseError::fail(error.to_string()))?;
        let project = directory.path().join(".sgy.yml");
        write_value(&project, &Value::Object(mapping)).map_err(TestCaseError::fail)?;
        let result = load_config_paths(&project, None);
        let rejected_by_schema = matches!(result, Err(ConfigError::Schema { .. }));
        prop_assert!(rejected_by_schema);
    }
}

#[test]
fn project_schema_forbids_engine_cwd_cache_and_duplicate_keys() {
    for field in ["engine", "cwd", "cache"] {
        let directory = tempfile::tempdir().expect("tempdir");
        let project = directory.path().join(".sgy.yml");
        let source = format!("schema: {CONFIG_SCHEMA}\n{field}: value\n");
        fs::write(&project, source).expect("write config");
        assert!(matches!(
            load_config_paths(&project, None),
            Err(ConfigError::Schema { .. })
        ));
    }

    let directory = tempfile::tempdir().expect("tempdir");
    let project = directory.path().join(".sgy.yml");
    fs::write(
        &project,
        format!("schema: {CONFIG_SCHEMA}\nprofile: files\nprofile: lossless\n"),
    )
    .expect("write duplicate config");
    assert!(matches!(
        load_config_paths(&project, None),
        Err(ConfigError::Codec { .. })
    ));
}

fn write_value(path: &std::path::Path, value: &Value) -> Result<(), String> {
    let mut yaml = Vec::new();
    write_yaml_document(value, &mut yaml, false).map_err(|error| error.to_string())?;
    fs::write(path, yaml).map_err(|error| error.to_string())
}
