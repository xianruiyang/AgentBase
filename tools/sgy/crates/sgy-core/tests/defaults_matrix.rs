use std::ffi::OsString;

use sgy_core::cache::CacheMode;
use sgy_core::config::{BasicConfig, ConfigSource, ConfigStack};
use sgy_core::defaults::{
    resolve_defaults, CommandClassification, DefaultsError, SuppressionReason,
    DEFAULT_JSON_STREAM_ARG,
};
use sgy_core::invocation::{ExplicitOptions, Profile};

#[derive(Clone, Copy)]
enum WrapperCase {
    Default,
    NoNativeDefaults,
    Lossless,
    Strict,
    StrictTokenSafe,
}

struct MatrixCase {
    id: &'static str,
    wrapper: WrapperCase,
    user: &'static str,
    injects: bool,
    primary_reason: Option<SuppressionReason>,
}

const CASES: [MatrixCase; 30] = [
    case(
        "D01",
        WrapperCase::Default,
        "run -p X -l ts src",
        true,
        None,
    ),
    case("D02", WrapperCase::Default, "scan src", true, None),
    case(
        "D03",
        WrapperCase::Default,
        "run --json -p X",
        false,
        Some(SuppressionReason::ExplicitJson),
    ),
    case(
        "D04",
        WrapperCase::Default,
        "run --json=compact -p X",
        false,
        Some(SuppressionReason::ExplicitJson),
    ),
    case(
        "D05",
        WrapperCase::Default,
        "scan --format sarif src",
        false,
        Some(SuppressionReason::ExplicitFormat),
    ),
    case(
        "D06",
        WrapperCase::Default,
        "scan --format=sarif src",
        false,
        Some(SuppressionReason::ExplicitFormat),
    ),
    case(
        "D07",
        WrapperCase::Default,
        "run --files-with-matches -p X",
        false,
        Some(SuppressionReason::FilesWithMatches),
    ),
    case(
        "D08",
        WrapperCase::Default,
        "scan -i src",
        false,
        Some(SuppressionReason::Interactive),
    ),
    case(
        "D09",
        WrapperCase::Default,
        "run -Ui -r Y -p X",
        false,
        Some(SuppressionReason::Interactive),
    ),
    case(
        "D10",
        WrapperCase::Default,
        "run --help",
        false,
        Some(SuppressionReason::TerminalOutputRequested),
    ),
    case(
        "D11",
        WrapperCase::Default,
        "run --debug-query=ast -p X -l ts",
        false,
        Some(SuppressionReason::DiagnosticOutputRequested),
    ),
    case(
        "D12",
        WrapperCase::Default,
        "run --inspect summary -p X",
        true,
        None,
    ),
    case(
        "D13",
        WrapperCase::Default,
        "run -U -r Y -p X src",
        false,
        Some(SuppressionReason::UpdateAll),
    ),
    case(
        "D14",
        WrapperCase::Default,
        "test -i",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D15",
        WrapperCase::Default,
        "new rule foo",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D16",
        WrapperCase::Default,
        "lsp",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D17",
        WrapperCase::Default,
        "completions powershell",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D18",
        WrapperCase::Default,
        "help run",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D19",
        WrapperCase::Default,
        "future --jsonish",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D20",
        WrapperCase::Default,
        "-p X -l ts src",
        false,
        Some(SuppressionReason::NonBatchOrUnknownCommand),
    ),
    case(
        "D21",
        WrapperCase::Default,
        "run -p X -- --json=compact",
        false,
        Some(SuppressionReason::NativeArgTerminator),
    ),
    case(
        "D22",
        WrapperCase::NoNativeDefaults,
        "run -p X",
        false,
        Some(SuppressionReason::NativeDefaultsDisabled),
    ),
    case("D23", WrapperCase::Lossless, "run -p X", true, None),
    case(
        "D24",
        WrapperCase::Strict,
        "run -p X",
        false,
        Some(SuppressionReason::StrictMode),
    ),
    case("D25", WrapperCase::StrictTokenSafe, "run -p X", false, None),
    case(
        "D26",
        WrapperCase::Default,
        "run --json=bad --json=stream -p X",
        false,
        Some(SuppressionReason::ExplicitJson),
    ),
    case(
        "D27",
        WrapperCase::Default,
        "run --jsonish -p X",
        true,
        None,
    ),
    case(
        "D28",
        WrapperCase::Default,
        "run --format invalid -p X",
        false,
        Some(SuppressionReason::ExplicitFormat),
    ),
    case(
        "D29",
        WrapperCase::Default,
        "scan --max-results 5 src",
        true,
        None,
    ),
    case(
        "D30",
        WrapperCase::Default,
        "run --pattern=--json src",
        true,
        None,
    ),
];

const fn case(
    id: &'static str,
    wrapper: WrapperCase,
    user: &'static str,
    injects: bool,
    primary_reason: Option<SuppressionReason>,
) -> MatrixCase {
    MatrixCase {
        id,
        wrapper,
        user,
        injects,
        primary_reason,
    }
}

fn explicit(wrapper: WrapperCase) -> ExplicitOptions {
    match wrapper {
        WrapperCase::Default => ExplicitOptions::default(),
        WrapperCase::NoNativeDefaults => ExplicitOptions {
            no_native_defaults: true,
            ..ExplicitOptions::default()
        },
        WrapperCase::Lossless => ExplicitOptions {
            profile: Some(Profile::Lossless),
            ..ExplicitOptions::default()
        },
        WrapperCase::Strict => ExplicitOptions {
            strict: true,
            ..ExplicitOptions::default()
        },
        WrapperCase::StrictTokenSafe => ExplicitOptions {
            profile: Some(Profile::TokenSafe),
            strict: true,
            ..ExplicitOptions::default()
        },
    }
}

fn args(value: &str) -> Vec<OsString> {
    value.split_ascii_whitespace().map(OsString::from).collect()
}

#[test]
fn frozen_d01_through_d30_matrix_is_exact() {
    for (index, matrix) in CASES.iter().enumerate() {
        assert_eq!(matrix.id, format!("D{:02}", index + 1));
        let user = args(matrix.user);
        let result = resolve_defaults(&explicit(matrix.wrapper), &ConfigStack::default(), &user);
        if matrix.id == "D25" {
            assert_eq!(result, Err(DefaultsError::StrictProfileConflict));
            continue;
        }
        let decision = result.unwrap_or_else(|error| panic!("{} failed: {error}", matrix.id));
        assert_eq!(
            &decision.effective_argv[..user.len()],
            user.as_slice(),
            "{} prefix",
            matrix.id
        );
        assert_eq!(
            decision.injected == [OsString::from(DEFAULT_JSON_STREAM_ARG)],
            matrix.injects,
            "{} injection",
            matrix.id
        );
        assert_eq!(
            decision.suppressed_by.first().copied(),
            matrix.primary_reason,
            "{} reason",
            matrix.id
        );
        assert_eq!(
            decision.effective_argv.len(),
            user.len() + usize::from(matrix.injects),
            "{} length",
            matrix.id
        );
    }
}

#[test]
fn suppression_reasons_are_unique_and_canonically_ordered() {
    let explicit = ExplicitOptions {
        no_native_defaults: true,
        ..ExplicitOptions::default()
    };
    let user = args("future --help --debug-query -i -U --json --format --files-with-matches");
    let decision = resolve_defaults(&explicit, &ConfigStack::default(), &user)
        .expect("multi-barrier input should resolve");
    assert_eq!(
        decision.suppressed_by,
        [
            SuppressionReason::NativeDefaultsDisabled,
            SuppressionReason::NonBatchOrUnknownCommand,
            SuppressionReason::TerminalOutputRequested,
            SuppressionReason::DiagnosticOutputRequested,
            SuppressionReason::Interactive,
            SuppressionReason::UpdateAll,
            SuppressionReason::ExplicitJson,
            SuppressionReason::ExplicitFormat,
            SuppressionReason::FilesWithMatches,
        ]
    );

    let terminator = resolve_defaults(
        &ExplicitOptions::default(),
        &ConfigStack::default(),
        &args("run --json -- --format -i"),
    )
    .expect("terminator input should resolve");
    assert_eq!(
        terminator.suppressed_by,
        [SuppressionReason::NativeArgTerminator]
    );
}

#[test]
fn settings_follow_explicit_project_user_builtin_priority() {
    let config = ConfigStack {
        project: Some(BasicConfig {
            profile: Some(Profile::Files),
            native_defaults: Some(false),
            max_detail_results: Some(12),
            max_text_chars: Some(200),
            ..BasicConfig::default()
        }),
        user: Some(BasicConfig {
            profile: Some(Profile::Custom),
            native_defaults: Some(true),
            max_detail_results: Some(30),
            max_text_chars: Some(300),
            max_context_bytes: Some(12_000),
            ..BasicConfig::default()
        }),
    };
    let project = resolve_defaults(&ExplicitOptions::default(), &config, &args("run"))
        .expect("project settings should resolve");
    assert_eq!(project.settings.profile, Profile::Files);
    assert_eq!(project.settings.profile_source, ConfigSource::Project);
    assert!(!project.settings.native_defaults_enabled);
    assert_eq!(
        project.settings.native_defaults_source,
        ConfigSource::Project
    );
    assert_eq!(project.settings.budget.max_detail_results(), 12);
    assert_eq!(project.settings.budget.max_text_chars(), 200);
    assert_eq!(project.settings.budget.max_context_bytes(), 12_000);
    assert_eq!(
        project.settings.max_detail_results_source,
        ConfigSource::Project
    );
    assert_eq!(
        project.settings.max_context_bytes_source,
        ConfigSource::User
    );

    let strict = resolve_defaults(
        &ExplicitOptions {
            strict: true,
            ..ExplicitOptions::default()
        },
        &config,
        &args("run"),
    )
    .expect("strict should override configured non-lossless profile");
    assert_eq!(strict.settings.profile, Profile::Lossless);
    assert_eq!(strict.settings.profile_source, ConfigSource::Explicit);
    assert!(!strict.settings.native_defaults_enabled);
}

#[test]
fn higher_priority_non_custom_profile_ignores_lower_priority_custom_fields() {
    let config = ConfigStack {
        project: Some(BasicConfig {
            profile: Some(Profile::Custom),
            keep_fields: Some("file,range".to_owned()),
            ..BasicConfig::default()
        }),
        user: None,
    };
    let decision = resolve_defaults(
        &ExplicitOptions {
            profile: Some(Profile::Files),
            ..ExplicitOptions::default()
        },
        &config,
        &args("scan src"),
    )
    .expect("explicit profile should suppress lower-priority dependent fields");
    assert_eq!(decision.settings.profile, Profile::Files);
    assert_eq!(decision.settings.profile_source, ConfigSource::Explicit);
    assert_eq!(decision.settings.keep_fields, None);
    assert_eq!(decision.settings.keep_fields_source, ConfigSource::BuiltIn);
}

#[test]
fn deterministic_token_corpus_never_mutates_user_prefix_or_injects_other_flags() {
    let corpus = [
        "",
        "run",
        "scan",
        "future",
        "--json",
        "--jsonish",
        "--format=x",
        "-Ui",
        "-Ux",
        "--",
        "--max-results",
        "5",
        "中文",
        "$A",
        "--semantic",
        "--color",
        "--heading",
    ];
    let mut state = 0x5eed_u64;
    for _ in 0..1_000 {
        state = state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1);
        let length = usize::try_from((state >> 32) % 8 + 1).expect("length fits usize");
        let mut user = Vec::with_capacity(length);
        for _ in 0..length {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let index = usize::try_from((state >> 32) % corpus.len() as u64)
                .expect("corpus index fits usize");
            user.push(OsString::from(corpus[index]));
        }
        let decision =
            resolve_defaults(&ExplicitOptions::default(), &ConfigStack::default(), &user)
                .expect("corpus input should resolve");
        assert_eq!(&decision.effective_argv[..user.len()], user.as_slice());
        assert!(
            decision.injected.is_empty()
                || decision.injected == [OsString::from(DEFAULT_JSON_STREAM_ARG)]
        );
        assert_eq!(
            decision.effective_argv.len(),
            user.len() + decision.injected.len()
        );
    }
}

#[test]
fn context_settings_resolve_explicit_values_and_validate_custom_paths() {
    let explicit = ExplicitOptions {
        profile: Some(Profile::Custom),
        cache_mode: Some(CacheMode::On),
        max_detail_results: Some(20),
        max_text_chars: Some(120),
        max_context_bytes: Some(12_288),
        keep_fields: Some("file,range,text".to_owned()),
        prune_fields: Some("text".to_owned()),
        ..ExplicitOptions::default()
    };
    let decision = resolve_defaults(&explicit, &ConfigStack::default(), &args("run"))
        .expect("context settings");
    assert_eq!(decision.settings.cache_mode, CacheMode::On);
    assert_eq!(decision.settings.budget.max_detail_results(), 20);
    assert_eq!(decision.settings.budget.max_text_chars(), 120);
    assert_eq!(decision.settings.budget.max_context_bytes(), 12_288);
    assert_eq!(
        decision
            .settings
            .keep_paths
            .as_ref()
            .map(|paths| paths.len()),
        Some(3)
    );
    assert_eq!(decision.settings.prune_paths.len(), 1);

    let wrong_profile = resolve_defaults(
        &ExplicitOptions {
            keep_fields: Some("file".to_owned()),
            ..ExplicitOptions::default()
        },
        &ConfigStack::default(),
        &args("run"),
    );
    assert_eq!(
        wrong_profile,
        Err(DefaultsError::CustomFieldsRequireCustomProfile)
    );

    let invalid_path = resolve_defaults(
        &ExplicitOptions {
            profile: Some(Profile::Custom),
            keep_fields: Some("file..text".to_owned()),
            ..ExplicitOptions::default()
        },
        &ConfigStack::default(),
        &args("run"),
    );
    assert!(matches!(invalid_path, Err(DefaultsError::FieldPath(_))));
}

#[test]
fn exact_first_token_classification_covers_every_frozen_command_shape() {
    let cases = [
        ("run x", CommandClassification::BatchRun),
        ("scan x", CommandClassification::BatchScan),
        ("test", CommandClassification::NonBatchTest),
        ("new", CommandClassification::NonBatchNew),
        ("lsp", CommandClassification::ProtocolLsp),
        (
            "completions zsh",
            CommandClassification::ArtifactCompletions,
        ),
        ("help run", CommandClassification::TerminalHelp),
        ("--help", CommandClassification::TerminalHelp),
        ("--version", CommandClassification::TerminalHelp),
        ("future", CommandClassification::UnknownOrImplicit),
        ("-p X", CommandClassification::UnknownOrImplicit),
    ];
    for (user, expected) in cases {
        let decision = resolve_defaults(
            &ExplicitOptions::default(),
            &ConfigStack::default(),
            &args(user),
        )
        .expect("classification input should resolve");
        assert_eq!(decision.classification, expected, "{user}");
    }
}

#[test]
fn explicit_artifact_output_suppresses_only_the_native_json_default() {
    let explicit = ExplicitOptions {
        artifact_out: Some("native.bin".into()),
        ..ExplicitOptions::default()
    };
    let user = args("run -p X src");
    let decision =
        resolve_defaults(&explicit, &ConfigStack::default(), &user).expect("artifact defaults");
    assert_eq!(
        decision.suppressed_by,
        [SuppressionReason::ArtifactOutputRequested]
    );
    assert!(decision.injected.is_empty());
    assert_eq!(decision.effective_argv, user);
}
