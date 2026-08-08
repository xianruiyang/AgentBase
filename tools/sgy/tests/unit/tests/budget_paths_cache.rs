use std::{path::Path, time::Duration};

use proptest::prelude::*;
use serde_json::{json, Value};
use sgy_contract_tests::strategies::{unicode_string, valid_field_name};
use sgy_core::{
    aggregate::{AggregateError, ContextAggregator},
    budget::{BudgetError, BudgetSettings},
    cache::{validate_cache_id, CacheError, CacheLimits, CacheStore},
    codec::parse_yaml_documents,
    invocation::Profile,
    profile::{project_token_safe, FieldPaths},
};

proptest! {
    #![proptest_config(ProptestConfig::with_cases(256))]

    #[test]
    fn valid_field_paths_select_only_requested_top_level_fields(
        fields in proptest::collection::btree_set(valid_field_name(), 1..8),
    ) {
        let expression = fields.iter().cloned().collect::<Vec<_>>().join(",");
        let paths = FieldPaths::parse(&expression)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        let source = Value::Object(
            fields
                .iter()
                .cloned()
                .map(|field| (field.clone(), Value::String(format!("value-{field}"))))
                .chain(std::iter::once(("not_selected".to_owned(), Value::Bool(true))))
                .collect(),
        );
        let selected = paths.select(&source);
        let mapping = selected.as_object().ok_or_else(|| TestCaseError::fail("selection is not an object"))?;
        prop_assert!(!mapping.contains_key("not_selected"));
        prop_assert_eq!(mapping.len(), fields.len());
        for field in fields {
            prop_assert!(mapping.contains_key(&field));
        }
    }

    #[test]
    fn token_safe_budget_is_deterministic_bounded_and_unicode_safe(
        texts in proptest::collection::vec(unicode_string(96), 0..24),
        max_details in 1_u32..20,
        max_text in 0_u32..128,
        max_bytes in 256_u64..16_384,
    ) {
        let settings = BudgetSettings::new(max_details, max_text, max_bytes)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        let mut first = ContextAggregator::new(Profile::TokenSafe, settings)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        let mut second = ContextAggregator::new(Profile::TokenSafe, settings)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;

        for (index, text) in texts.iter().enumerate() {
            let ordinal = u64::try_from(index).map_err(|error| TestCaseError::fail(error.to_string()))?;
            let native = json!({
                "file": format!("src/{index:04}.ts"),
                "range": {
                    "start": {"line": index, "column": 0},
                    "end": {"line": index, "column": text.chars().count()},
                },
                "text": text,
                "metaVariables": {"single": {"A": {"text": text}}},
            });
            let projected = project_token_safe(ordinal, &native);
            first.push_token_safe(projected.clone())
                .map_err(|error| TestCaseError::fail(error.to_string()))?;
            second.push_token_safe(projected)
                .map_err(|error| TestCaseError::fail(error.to_string()))?;
        }

        let left = first.finish();
        let right = second.finish();
        prop_assert_eq!(&left, &right);
        match left {
            Ok(context) => {
                prop_assert!(context.budget.yaml_bytes <= max_bytes);
                prop_assert!(context.document.shown() <= u64::from(max_details));
                prop_assert_eq!(context.document.total(), texts.len() as u64);
                let mut yaml = Vec::new();
                context.document.write_yaml(&mut yaml)
                    .map_err(|error| TestCaseError::fail(error.to_string()))?;
                parse_yaml_documents(&yaml)
                    .map_err(|error| TestCaseError::fail(error.to_string()))?;
            }
            Err(AggregateError::Budget(BudgetError::Minimum { limit_bytes, measured_bytes })) => {
                prop_assert_eq!(limit_bytes, max_bytes);
                prop_assert!(measured_bytes > limit_bytes);
            }
            Err(error) => return Err(TestCaseError::fail(error.to_string())),
        }
    }

    #[test]
    fn cache_id_acceptance_exactly_matches_the_ulid_alphabet(candidate in unicode_string(40)) {
        let allowed = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
        let expected = candidate.len() == 26 && candidate.bytes().all(|byte| allowed.as_bytes().contains(&byte));
        prop_assert_eq!(validate_cache_id(&candidate).is_ok(), expected);
    }
}

#[test]
fn cache_paths_reject_parent_segments_workspace_roots_and_invalid_ids() {
    let workspace = tempfile::tempdir().expect("workspace");
    let unsafe_root = workspace.path().join("cache");
    let result = CacheStore::open(&unsafe_root, Some(workspace.path()), limits());
    assert!(matches!(result, Err(CacheError::WorkspaceRoot { .. })));

    let outside = tempfile::tempdir().expect("outside cache");
    let root = outside.path().join("cache");
    let store = CacheStore::open(&root, Some(workspace.path()), limits()).expect("safe cache");
    for invalid in ["../escape", "..", "A", "01ARZ3NDEKTSV4RRFFQ69G5FAI/child"] {
        assert!(matches!(
            store.entry_path(invalid),
            Err(CacheError::InvalidId(_))
        ));
    }

    let parent_root = Path::new("safe").join("..").join("escape");
    assert!(matches!(
        CacheStore::open(parent_root, None, limits()),
        Err(CacheError::UnsafePath(_))
    ));
}

fn limits() -> CacheLimits {
    CacheLimits {
        ttl: Duration::from_secs(60),
        quota_bytes: 1024 * 1024,
        max_entry_bytes: 512 * 1024,
        incomplete_ttl: Duration::from_secs(60),
    }
}
