use std::ffi::{OsStr, OsString};

use thiserror::Error;

use crate::budget::{
    BudgetError, BudgetSettings, DEFAULT_MAX_CONTEXT_BYTES, DEFAULT_MAX_DETAIL_RESULTS,
    DEFAULT_MAX_TEXT_CHARS,
};
use crate::cache::CacheMode;
use crate::config::{ConfigSource, ConfigStack};
use crate::invocation::{ExplicitOptions, Profile};
use crate::profile::{FieldPathError, FieldPaths};

pub const DEFAULT_JSON_STREAM_ARG: &str = "--json=stream";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CommandClassification {
    BatchRun,
    BatchScan,
    NonBatchTest,
    NonBatchNew,
    ProtocolLsp,
    ArtifactCompletions,
    TerminalHelp,
    UnknownOrImplicit,
}

impl CommandClassification {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BatchRun => "batch_run",
            Self::BatchScan => "batch_scan",
            Self::NonBatchTest => "non_batch_test",
            Self::NonBatchNew => "non_batch_new",
            Self::ProtocolLsp => "protocol_lsp",
            Self::ArtifactCompletions => "artifact_completions",
            Self::TerminalHelp => "terminal_help",
            Self::UnknownOrImplicit => "unknown_or_implicit",
        }
    }

    const fn is_batch(self) -> bool {
        matches!(self, Self::BatchRun | Self::BatchScan)
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum SuppressionReason {
    StrictMode,
    NativeDefaultsDisabled,
    NonBatchOrUnknownCommand,
    NativeArgTerminator,
    ArtifactOutputRequested,
    TerminalOutputRequested,
    DiagnosticOutputRequested,
    Interactive,
    UpdateAll,
    ExplicitJson,
    ExplicitFormat,
    FilesWithMatches,
}

impl SuppressionReason {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::StrictMode => "strict_mode",
            Self::NativeDefaultsDisabled => "native_defaults_disabled",
            Self::NonBatchOrUnknownCommand => "non_batch_or_unknown_command",
            Self::NativeArgTerminator => "native_arg_terminator",
            Self::ArtifactOutputRequested => "artifact_output_requested",
            Self::TerminalOutputRequested => "terminal_output_requested",
            Self::DiagnosticOutputRequested => "diagnostic_output_requested",
            Self::Interactive => "interactive",
            Self::UpdateAll => "update_all",
            Self::ExplicitJson => "explicit_json",
            Self::ExplicitFormat => "explicit_format",
            Self::FilesWithMatches => "files_with_matches",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectiveDefaultsSettings {
    pub strict: bool,
    pub strict_source: ConfigSource,
    pub native_defaults_enabled: bool,
    pub native_defaults_source: ConfigSource,
    pub profile: Profile,
    pub profile_source: ConfigSource,
    pub cache_mode: CacheMode,
    pub cache_mode_source: ConfigSource,
    pub budget: BudgetSettings,
    pub max_detail_results_source: ConfigSource,
    pub max_text_chars_source: ConfigSource,
    pub max_context_bytes_source: ConfigSource,
    pub keep_fields: Option<String>,
    pub keep_fields_source: ConfigSource,
    pub prune_fields: Option<String>,
    pub prune_fields_source: ConfigSource,
    pub keep_paths: Option<FieldPaths>,
    pub prune_paths: FieldPaths,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DefaultsDecision {
    pub user_argv: Vec<OsString>,
    pub classification: CommandClassification,
    pub settings: EffectiveDefaultsSettings,
    pub suppressed_by: Vec<SuppressionReason>,
    pub injected: Vec<OsString>,
    pub effective_argv: Vec<OsString>,
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum DefaultsError {
    #[error("--strict conflicts with explicit non-lossless --profile")]
    StrictProfileConflict,
    #[error("--keep-fields/--prune-fields require --profile custom")]
    CustomFieldsRequireCustomProfile,
    #[error(transparent)]
    FieldPath(#[from] FieldPathError),
    #[error(transparent)]
    Budget(#[from] BudgetError),
}

impl DefaultsError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> u8 {
        match self {
            Self::StrictProfileConflict
            | Self::CustomFieldsRequireCustomProfile
            | Self::FieldPath(_)
            | Self::Budget(_) => 125,
        }
    }
}

pub fn resolve_defaults(
    explicit: &ExplicitOptions,
    config: &ConfigStack,
    user_argv: &[OsString],
) -> Result<DefaultsDecision, DefaultsError> {
    let settings = effective_settings(explicit, config)?;
    let classification = classify(user_argv.first().map(OsString::as_os_str));
    let mut suppressed_by = Vec::new();

    if settings.strict {
        suppressed_by.push(SuppressionReason::StrictMode);
    } else if !settings.native_defaults_enabled {
        suppressed_by.push(SuppressionReason::NativeDefaultsDisabled);
    }
    if !classification.is_batch() {
        suppressed_by.push(SuppressionReason::NonBatchOrUnknownCommand);
    }
    if explicit.artifact_out.is_some() {
        suppressed_by.push(SuppressionReason::ArtifactOutputRequested);
    }
    if user_argv.iter().any(|token| token == OsStr::new("--")) {
        suppressed_by.push(SuppressionReason::NativeArgTerminator);
    } else {
        scan_barriers(user_argv, &mut suppressed_by);
    }
    suppressed_by.sort_unstable();
    suppressed_by.dedup();

    let injected = if suppressed_by.is_empty() {
        vec![OsString::from(DEFAULT_JSON_STREAM_ARG)]
    } else {
        Vec::new()
    };
    let mut effective_argv = Vec::with_capacity(user_argv.len() + injected.len());
    effective_argv.extend_from_slice(user_argv);
    effective_argv.extend(injected.iter().cloned());

    Ok(DefaultsDecision {
        user_argv: user_argv.to_vec(),
        classification,
        settings,
        suppressed_by,
        injected,
        effective_argv,
    })
}

fn effective_settings(
    explicit: &ExplicitOptions,
    config: &ConfigStack,
) -> Result<EffectiveDefaultsSettings, DefaultsError> {
    if explicit.strict && matches!(explicit.profile, Some(profile) if profile != Profile::Lossless)
    {
        return Err(DefaultsError::StrictProfileConflict);
    }
    let (mut profile, mut profile_source) = explicit
        .profile
        .map(|value| (value, ConfigSource::Explicit))
        .or_else(|| {
            config
                .project
                .as_ref()
                .and_then(|value| value.profile)
                .map(|value| (value, ConfigSource::Project))
        })
        .or_else(|| {
            config
                .user
                .as_ref()
                .and_then(|value| value.profile)
                .map(|value| (value, ConfigSource::User))
        })
        .unwrap_or((Profile::TokenSafe, ConfigSource::BuiltIn));
    if explicit.strict {
        profile = Profile::Lossless;
        profile_source = ConfigSource::Explicit;
    }
    let (native_defaults_enabled, native_defaults_source) =
        if explicit.strict || explicit.no_native_defaults {
            (false, ConfigSource::Explicit)
        } else {
            config
                .project
                .as_ref()
                .and_then(|value| value.native_defaults)
                .map(|value| (value, ConfigSource::Project))
                .or_else(|| {
                    config
                        .user
                        .as_ref()
                        .and_then(|value| value.native_defaults)
                        .map(|value| (value, ConfigSource::User))
                })
                .unwrap_or((true, ConfigSource::BuiltIn))
        };

    let (cache_mode, cache_mode_source) = select_copy(
        explicit.cache_mode,
        config.project.as_ref().and_then(|value| value.cache_mode),
        config.user.as_ref().and_then(|value| value.cache_mode),
        CacheMode::Auto,
    );
    let (max_detail_results, max_detail_results_source) = select_copy(
        explicit.max_detail_results,
        config
            .project
            .as_ref()
            .and_then(|value| value.max_detail_results),
        config
            .user
            .as_ref()
            .and_then(|value| value.max_detail_results),
        DEFAULT_MAX_DETAIL_RESULTS,
    );
    let (max_text_chars, max_text_chars_source) = select_copy(
        explicit.max_text_chars,
        config
            .project
            .as_ref()
            .and_then(|value| value.max_text_chars),
        config.user.as_ref().and_then(|value| value.max_text_chars),
        DEFAULT_MAX_TEXT_CHARS,
    );
    let (max_context_bytes, max_context_bytes_source) = select_copy(
        explicit.max_context_bytes,
        config
            .project
            .as_ref()
            .and_then(|value| value.max_context_bytes),
        config
            .user
            .as_ref()
            .and_then(|value| value.max_context_bytes),
        DEFAULT_MAX_CONTEXT_BYTES,
    );
    let budget = BudgetSettings::new(max_detail_results, max_text_chars, max_context_bytes)?;
    let (mut keep_fields, mut keep_fields_source) = select_clone(
        explicit.keep_fields.as_ref(),
        config
            .project
            .as_ref()
            .and_then(|value| value.keep_fields.as_ref()),
        config
            .user
            .as_ref()
            .and_then(|value| value.keep_fields.as_ref()),
    );
    let (mut prune_fields, mut prune_fields_source) = select_clone(
        explicit.prune_fields.as_ref(),
        config
            .project
            .as_ref()
            .and_then(|value| value.prune_fields.as_ref()),
        config
            .user
            .as_ref()
            .and_then(|value| value.prune_fields.as_ref()),
    );
    if profile != Profile::Custom {
        if explicit.keep_fields.is_some() || explicit.prune_fields.is_some() {
            return Err(DefaultsError::CustomFieldsRequireCustomProfile);
        }
        keep_fields = None;
        keep_fields_source = ConfigSource::BuiltIn;
        prune_fields = None;
        prune_fields_source = ConfigSource::BuiltIn;
    }
    let keep_paths = keep_fields.as_deref().map(FieldPaths::parse).transpose()?;
    let prune_paths = prune_fields
        .as_deref()
        .map(FieldPaths::parse)
        .transpose()?
        .unwrap_or_default();

    Ok(EffectiveDefaultsSettings {
        strict: explicit.strict,
        strict_source: if explicit.strict {
            ConfigSource::Explicit
        } else {
            ConfigSource::BuiltIn
        },
        native_defaults_enabled,
        native_defaults_source,
        profile,
        profile_source,
        cache_mode,
        cache_mode_source,
        budget,
        max_detail_results_source,
        max_text_chars_source,
        max_context_bytes_source,
        keep_fields,
        keep_fields_source,
        prune_fields,
        prune_fields_source,
        keep_paths,
        prune_paths,
    })
}

fn select_copy<T: Copy>(
    explicit: Option<T>,
    project: Option<T>,
    user: Option<T>,
    builtin: T,
) -> (T, ConfigSource) {
    explicit
        .map(|value| (value, ConfigSource::Explicit))
        .or_else(|| project.map(|value| (value, ConfigSource::Project)))
        .or_else(|| user.map(|value| (value, ConfigSource::User)))
        .unwrap_or((builtin, ConfigSource::BuiltIn))
}

fn select_clone<T: Clone>(
    explicit: Option<&T>,
    project: Option<&T>,
    user: Option<&T>,
) -> (Option<T>, ConfigSource) {
    explicit
        .map(|value| (Some(value.clone()), ConfigSource::Explicit))
        .or_else(|| project.map(|value| (Some(value.clone()), ConfigSource::Project)))
        .or_else(|| user.map(|value| (Some(value.clone()), ConfigSource::User)))
        .unwrap_or((None, ConfigSource::BuiltIn))
}

fn classify(first: Option<&OsStr>) -> CommandClassification {
    match first.and_then(OsStr::to_str) {
        Some("run") => CommandClassification::BatchRun,
        Some("scan") => CommandClassification::BatchScan,
        Some("test") => CommandClassification::NonBatchTest,
        Some("new") => CommandClassification::NonBatchNew,
        Some("lsp") => CommandClassification::ProtocolLsp,
        Some("completions") => CommandClassification::ArtifactCompletions,
        Some("help" | "--help" | "-h" | "--version" | "-V") => CommandClassification::TerminalHelp,
        _ => CommandClassification::UnknownOrImplicit,
    }
}

fn scan_barriers(user_argv: &[OsString], reasons: &mut Vec<SuppressionReason>) {
    for token in user_argv {
        let Some(token) = token.to_str() else {
            continue;
        };
        if long_flag(token, "--help")
            || long_flag(token, "--version")
            || short_cluster_has(token, 'h')
            || short_cluster_has(token, 'V')
        {
            reasons.push(SuppressionReason::TerminalOutputRequested);
        }
        if long_flag(token, "--debug-query") {
            reasons.push(SuppressionReason::DiagnosticOutputRequested);
        }
        if token == "-i" || long_flag(token, "--interactive") || short_cluster_has(token, 'i') {
            reasons.push(SuppressionReason::Interactive);
        }
        if token == "-U" || long_flag(token, "--update-all") || short_cluster_has(token, 'U') {
            reasons.push(SuppressionReason::UpdateAll);
        }
        if long_flag(token, "--json") {
            reasons.push(SuppressionReason::ExplicitJson);
        }
        if long_flag(token, "--format") {
            reasons.push(SuppressionReason::ExplicitFormat);
        }
        if long_flag(token, "--files-with-matches") {
            reasons.push(SuppressionReason::FilesWithMatches);
        }
    }
}

fn long_flag(token: &str, name: &str) -> bool {
    token == name
        || token
            .strip_prefix(name)
            .is_some_and(|rest| rest.starts_with('='))
}

fn short_cluster_has(token: &str, target: char) -> bool {
    let Some(cluster) = token.strip_prefix('-') else {
        return false;
    };
    !cluster.is_empty()
        && cluster
            .chars()
            .all(|flag| matches!(flag, 'i' | 'U' | 'h' | 'V'))
        && cluster.contains(target)
}
