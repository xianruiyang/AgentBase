//! Write-intent detection shared by run/scan adapters and context summaries.

use std::ffi::{OsStr, OsString};

use crate::defaults::CommandClassification;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum WriteIntent {
    #[default]
    None,
    Preview,
    Apply,
}

impl WriteIntent {
    #[must_use]
    pub const fn as_str(self) -> Option<&'static str> {
        match self {
            Self::None => None,
            Self::Preview => Some("preview"),
            Self::Apply => Some("apply"),
        }
    }

    #[must_use]
    pub const fn may_modify_files(self) -> bool {
        matches!(self, Self::Apply)
    }
}

/// Detects only write semantics explicitly present in native argv. Scan rule files are not
/// opened here; their `fix` capability is instead discovered from native replacement records.
#[must_use]
pub fn detect_write_intent(
    args: &[OsString],
    classification: CommandClassification,
) -> WriteIntent {
    let mut rewrite = false;
    let mut update_all = false;
    for token in args
        .iter()
        .take_while(|token| token.as_os_str() != OsStr::new("--"))
    {
        let Some(token) = token.to_str() else {
            continue;
        };
        if long_flag(token, "--update-all") || token == "-U" || short_cluster_has_u(token) {
            update_all = true;
        }
        if classification == CommandClassification::BatchRun
            && (long_flag(token, "--rewrite")
                || token == "-r"
                || (token.starts_with("-r") && !token.starts_with("--")))
        {
            rewrite = true;
        }
    }
    if update_all {
        WriteIntent::Apply
    } else if rewrite {
        WriteIntent::Preview
    } else {
        WriteIntent::None
    }
}

fn long_flag(token: &str, name: &str) -> bool {
    token == name
        || token
            .strip_prefix(name)
            .is_some_and(|rest| rest.starts_with('='))
}

fn short_cluster_has_u(token: &str) -> bool {
    let Some(cluster) = token.strip_prefix('-') else {
        return false;
    };
    !cluster.is_empty()
        && cluster
            .chars()
            .all(|flag| matches!(flag, 'i' | 'U' | 'h' | 'V'))
        && cluster.contains('U')
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use super::{detect_write_intent, WriteIntent};
    use crate::defaults::CommandClassification;

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn detects_preview_apply_and_native_terminator() {
        assert_eq!(
            detect_write_intent(
                &args(&["run", "-r", "logger.info($A)"]),
                CommandClassification::BatchRun,
            ),
            WriteIntent::Preview
        );
        assert_eq!(
            detect_write_intent(
                &args(&["scan", "--update-all"]),
                CommandClassification::BatchScan,
            ),
            WriteIntent::Apply
        );
        assert_eq!(
            detect_write_intent(&args(&["run", "--", "-U"]), CommandClassification::BatchRun,),
            WriteIntent::None
        );
        assert_eq!(
            detect_write_intent(
                &args(&["scan", "-r", "rule.yml"]),
                CommandClassification::BatchScan,
            ),
            WriteIntent::None
        );
    }
}
