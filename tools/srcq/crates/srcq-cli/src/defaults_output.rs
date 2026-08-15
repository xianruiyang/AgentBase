use std::ffi::OsString;
use std::fmt::Write as _;

use srcq_core::defaults::DefaultsDecision;
use thiserror::Error;

pub const MAX_DEFAULTS_OUTPUT_BYTES: usize = 128 * 1024;

#[derive(Debug, Error)]
pub enum DefaultsOutputError {
    #[error("{field}[{index}] is not valid Unicode and cannot be represented in defaults YAML")]
    NonUnicodeArg { field: &'static str, index: usize },
    #[error("failed to quote defaults YAML string: {0}")]
    Quote(#[from] serde_json::Error),
    #[error("defaults YAML exceeds {MAX_DEFAULTS_OUTPUT_BYTES} bytes")]
    TooLarge,
}

impl DefaultsOutputError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> u8 {
        match self {
            Self::TooLarge => 124,
            Self::NonUnicodeArg { .. } | Self::Quote(_) => 125,
        }
    }
}

pub fn render_defaults_yaml(decision: &DefaultsDecision) -> Result<Vec<u8>, DefaultsOutputError> {
    let mut output = String::from("schema: \"sgy.defaults/v1\"\n");
    push_os_array(&mut output, "user_argv", &decision.user_argv)?;
    writeln!(
        output,
        "classification: {}",
        quote(decision.classification.as_str())?
    )
    .expect("writing to String cannot fail");
    output.push_str("settings:\n");
    writeln!(output, "  strict: {}", decision.settings.strict)
        .expect("writing to String cannot fail");
    writeln!(
        output,
        "  native_defaults_enabled: {}",
        decision.settings.native_defaults_enabled
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "  profile: {}",
        quote(decision.settings.profile.as_str())?
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "  cache: {}",
        quote(decision.settings.cache_mode.as_str())?
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "  max_detail_results: {}",
        decision.settings.budget.max_detail_results()
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "  max_text_chars: {}",
        decision.settings.budget.max_text_chars()
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "  max_context_bytes: {}",
        decision.settings.budget.max_context_bytes()
    )
    .expect("writing to String cannot fail");
    push_optional_string(
        &mut output,
        "  keep_fields",
        decision.settings.keep_fields.as_deref(),
    )?;
    push_optional_string(
        &mut output,
        "  prune_fields",
        decision.settings.prune_fields.as_deref(),
    )?;
    output.push_str("  sources:\n");
    writeln!(
        output,
        "    strict: {}",
        quote(decision.settings.strict_source.as_str())?
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "    native_defaults: {}",
        quote(decision.settings.native_defaults_source.as_str())?
    )
    .expect("writing to String cannot fail");
    writeln!(
        output,
        "    profile: {}",
        quote(decision.settings.profile_source.as_str())?
    )
    .expect("writing to String cannot fail");
    for (field, source) in [
        ("cache", decision.settings.cache_mode_source),
        (
            "max_detail_results",
            decision.settings.max_detail_results_source,
        ),
        ("max_text_chars", decision.settings.max_text_chars_source),
        (
            "max_context_bytes",
            decision.settings.max_context_bytes_source,
        ),
        ("keep_fields", decision.settings.keep_fields_source),
        ("prune_fields", decision.settings.prune_fields_source),
    ] {
        writeln!(output, "    {field}: {}", quote(source.as_str())?)
            .expect("writing to String cannot fail");
    }
    let reasons: Vec<&str> = decision
        .suppressed_by
        .iter()
        .map(|reason| reason.as_str())
        .collect();
    push_str_array(&mut output, "suppressed_by", &reasons)?;
    push_os_array(&mut output, "injected", &decision.injected)?;
    push_os_array(&mut output, "effective_argv", &decision.effective_argv)?;
    if output.len() > MAX_DEFAULTS_OUTPUT_BYTES {
        return Err(DefaultsOutputError::TooLarge);
    }
    Ok(output.into_bytes())
}

fn push_optional_string(
    output: &mut String,
    field: &'static str,
    value: Option<&str>,
) -> Result<(), DefaultsOutputError> {
    match value {
        Some(value) => writeln!(output, "{field}: {}", quote(value)?),
        None => writeln!(output, "{field}: null"),
    }
    .expect("writing to String cannot fail");
    Ok(())
}

fn push_os_array(
    output: &mut String,
    field: &'static str,
    values: &[OsString],
) -> Result<(), DefaultsOutputError> {
    if values.is_empty() {
        writeln!(output, "{field}: []").expect("writing to String cannot fail");
        return Ok(());
    }
    writeln!(output, "{field}:").expect("writing to String cannot fail");
    for (index, value) in values.iter().enumerate() {
        let value = value
            .to_str()
            .ok_or(DefaultsOutputError::NonUnicodeArg { field, index })?;
        writeln!(output, "  - {}", quote(value)?).expect("writing to String cannot fail");
    }
    Ok(())
}

fn push_str_array(
    output: &mut String,
    field: &'static str,
    values: &[&str],
) -> Result<(), DefaultsOutputError> {
    if values.is_empty() {
        writeln!(output, "{field}: []").expect("writing to String cannot fail");
        return Ok(());
    }
    writeln!(output, "{field}:").expect("writing to String cannot fail");
    for value in values {
        writeln!(output, "  - {}", quote(value)?).expect("writing to String cannot fail");
    }
    Ok(())
}

fn quote(value: &str) -> Result<String, serde_json::Error> {
    serde_json::to_string(value)
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use saphyr_parser::{Event, EventReceiver, Parser};
    use srcq_core::config::ConfigStack;
    use srcq_core::defaults::resolve_defaults;
    use srcq_core::invocation::ExplicitOptions;

    use super::{render_defaults_yaml, DefaultsOutputError, MAX_DEFAULTS_OUTPUT_BYTES};

    struct Sink;

    impl EventReceiver<'_> for Sink {
        fn on_event(&mut self, _event: Event<'_>) {}
    }

    #[test]
    fn renders_stable_yaml_without_shell_reconstruction() {
        let args = vec![
            OsString::from("run"),
            OsString::from("-p"),
            OsString::from("console.log($A)\nnext"),
        ];
        let decision =
            resolve_defaults(&ExplicitOptions::default(), &ConfigStack::default(), &args)
                .expect("defaults should resolve");
        let yaml = String::from_utf8(render_defaults_yaml(&decision).expect("YAML should render"))
            .expect("renderer emits UTF-8");

        assert!(yaml.starts_with("schema: \"sgy.defaults/v1\"\n"));
        assert!(yaml.contains("  - \"console.log($A)\\nnext\"\n"));
        assert!(yaml.contains("classification: \"batch_run\"\n"));
        assert!(yaml.contains("  native_defaults_enabled: true\n"));
        assert!(yaml.contains("  cache: \"auto\"\n"));
        assert!(yaml.contains("  max_detail_results: 40\n"));
        assert!(yaml.contains("  max_text_chars: 400\n"));
        assert!(yaml.contains("  max_context_bytes: 24576\n"));
        assert!(yaml.contains("injected:\n  - \"--json=stream\"\n"));
        assert!(yaml.ends_with("  - \"--json=stream\"\n"));
        Parser::new_from_str(&yaml)
            .load(&mut Sink, true)
            .expect("defaults output must be valid YAML 1.2");
    }

    #[test]
    fn rejects_defaults_output_above_the_diagnostic_bound() {
        let args = vec![
            OsString::from("run"),
            OsString::from("x".repeat(MAX_DEFAULTS_OUTPUT_BYTES)),
        ];
        let decision =
            resolve_defaults(&ExplicitOptions::default(), &ConfigStack::default(), &args)
                .expect("defaults should resolve");
        assert!(matches!(
            render_defaults_yaml(&decision),
            Err(DefaultsOutputError::TooLarge)
        ));
    }
}
