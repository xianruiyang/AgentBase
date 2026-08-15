use std::ffi::OsString;

use proptest::prelude::*;
use srcq_contract_tests::strategies::argv_token;
use srcq_core::{
    config::ConfigStack,
    defaults::{resolve_defaults, DEFAULT_JSON_STREAM_ARG},
    invocation::ExplicitOptions,
};

proptest! {
    #![proptest_config(ProptestConfig::with_cases(256))]

    #[test]
    fn delimiter_parser_preserves_every_native_token(
        tokens in proptest::collection::vec(argv_token(), 1..48),
    ) {
        let expected: Vec<OsString> = tokens.into_iter().map(OsString::from).collect();
        let mut command = vec![
            OsString::from("srcq"),
            OsString::from("exec"),
            OsString::from("--"),
        ];
        command.extend(expected.iter().cloned());

        let parsed = srcq_cli::parse_invocation_from(command)
            .map_err(|error| TestCaseError::fail(error.to_string()))?;
        prop_assert_eq!(parsed.user_argv, expected);
    }

    #[test]
    fn defaults_never_mutate_or_reorder_the_user_prefix(
        tokens in proptest::collection::vec(argv_token(), 0..64),
    ) {
        let user_argv: Vec<OsString> = tokens.into_iter().map(OsString::from).collect();
        let decision = resolve_defaults(
            &ExplicitOptions::default(),
            &ConfigStack::default(),
            &user_argv,
        )
        .map_err(|error| TestCaseError::fail(error.to_string()))?;

        prop_assert_eq!(&decision.user_argv, &user_argv);
        prop_assert!(decision.effective_argv.starts_with(&user_argv));
        prop_assert!(decision.injected.is_empty()
            || decision.injected == [OsString::from(DEFAULT_JSON_STREAM_ARG)]);
        prop_assert_eq!(
            decision.effective_argv.len(),
            user_argv.len() + decision.injected.len(),
        );
    }
}

#[test]
fn every_frozen_output_or_execution_barrier_suppresses_json_injection() {
    let cases: &[&[&str]] = &[
        &["run", "-p", "$A", "--json=compact"],
        &["run", "-p", "$A", "--json", "stream"],
        &["scan", "--format=github"],
        &["scan", "--format", "sarif"],
        &["run", "-p", "$A", "--files-with-matches"],
        &["run", "-p", "$A", "-i"],
        &["run", "-p", "$A", "-U"],
        &["run", "-p", "$A", "--debug-query=ast"],
        &["run", "-p", "$A", "--", "literal"],
    ];

    for case in cases {
        let argv: Vec<OsString> = case.iter().map(OsString::from).collect();
        let decision =
            resolve_defaults(&ExplicitOptions::default(), &ConfigStack::default(), &argv)
                .expect("barrier case must resolve");
        assert!(
            decision.injected.is_empty(),
            "unexpected injection for {case:?}"
        );
        assert_eq!(decision.effective_argv, argv);
    }
}
