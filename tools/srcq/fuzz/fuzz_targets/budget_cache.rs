#![no_main]

use libfuzzer_sys::fuzz_target;
use serde_json::json;
use srcq_core::{
    aggregate::{AggregateError, ContextAggregator},
    budget::{BudgetError, BudgetSettings},
    cache::validate_cache_id,
    invocation::Profile,
    profile::project_token_safe,
};

fuzz_target!(|data: &[u8]| {
    let detail = u32::from(data.first().copied().unwrap_or(1) % 32) + 1;
    let text_cap = u32::from(data.get(1).copied().unwrap_or(0));
    let context = 128_u64 + u64::from(data.get(2).copied().unwrap_or(0)) * 128;
    let settings = BudgetSettings::new(detail, text_cap, context)
        .unwrap_or_else(|error| panic!("derived settings are valid: {error}"));
    let mut aggregator = ContextAggregator::new(Profile::TokenSafe, settings)
        .unwrap_or_else(|error| panic!("token-safe aggregator failed: {error}"));

    for (index, chunk) in data.get(3..).unwrap_or_default().chunks(64).take(32).enumerate() {
        let text = String::from_utf8_lossy(chunk).into_owned();
        let native = json!({
            "file": format!("src/{index}.ts"),
            "range": {
                "start": {"line": index, "column": 0},
                "end": {"line": index, "column": text.chars().count()},
            },
            "text": text,
        });
        let record = project_token_safe(index as u64, &native);
        aggregator
            .push_token_safe(record)
            .unwrap_or_else(|error| panic!("native-order push failed: {error}"));
    }

    match aggregator.finish() {
        Ok(result) => {
            assert!(result.budget.yaml_bytes <= context);
            assert!(result.document.shown() <= u64::from(detail));
        }
        Err(AggregateError::Budget(BudgetError::Minimum {
            limit_bytes,
            measured_bytes,
        })) => {
            assert_eq!(limit_bytes, context);
            assert!(measured_bytes > limit_bytes);
        }
        Err(error) => panic!("unexpected budget error: {error}"),
    }

    if let Ok(candidate) = std::str::from_utf8(data) {
        let accepted = validate_cache_id(candidate).is_ok();
        let alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
        let expected = candidate.len() == 26
            && candidate
                .bytes()
                .all(|byte| alphabet.as_bytes().contains(&byte));
        assert_eq!(accepted, expected);
    }
});
