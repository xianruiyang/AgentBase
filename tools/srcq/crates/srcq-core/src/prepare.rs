use std::path::Path;

use thiserror::Error;

use crate::config::{resolve_settings, ConfigStack, ResolvedSettings};
use crate::defaults::{resolve_defaults, DefaultsDecision, DefaultsError};
use crate::engine::{discover_engine, DiscoveredEngine, EngineEnvironment, EngineError};
use crate::invocation::{NativeInvocation, WrapperCommand};

#[derive(Debug)]
pub struct PreparedInvocation {
    pub invocation: NativeInvocation,
    pub settings: ResolvedSettings,
    pub defaults: DefaultsDecision,
    pub engine: Option<DiscoveredEngine>,
}

#[derive(Debug, Error)]
pub enum PrepareError {
    #[error(transparent)]
    Defaults(#[from] DefaultsError),
    #[error(transparent)]
    Engine(#[from] EngineError),
}

pub fn prepare_invocation(
    invocation: NativeInvocation,
    config: &ConfigStack,
    launch_cwd: &Path,
    environment: &impl EngineEnvironment,
) -> Result<PreparedInvocation, PrepareError> {
    let settings = resolve_settings(&invocation.explicit, config, launch_cwd);
    let defaults = resolve_defaults(&invocation.explicit, config, &invocation.user_argv)?;
    let engine = match invocation.command {
        WrapperCommand::Exec => Some(discover_engine(
            settings.engine.as_ref(),
            launch_cwd,
            environment,
        )?),
        WrapperCommand::Defaults => None,
    };
    Ok(PreparedInvocation {
        invocation,
        settings,
        defaults,
        engine,
    })
}

#[cfg(test)]
mod tests {
    use std::path::{Path, PathBuf};

    use crate::config::ConfigStack;
    use crate::engine::{EngineEnvironment, EngineError, VersionProbeOutput};
    use crate::invocation::{ExplicitOptions, NativeInvocation, WrapperCommand};

    use super::prepare_invocation;

    struct NoEngineAccess;

    struct StaticPathEngine;

    impl EngineEnvironment for NoEngineAccess {
        fn resolve_configured(
            &self,
            _path: &Path,
            _launch_cwd: &Path,
        ) -> Result<PathBuf, EngineError> {
            panic!("defaults must not resolve an engine")
        }

        fn find_on_path(&self, _program: &str) -> Option<PathBuf> {
            panic!("defaults must not inspect PATH")
        }

        fn probe_version(&self, _path: &Path) -> Result<VersionProbeOutput, EngineError> {
            panic!("defaults must not start an engine")
        }
    }

    impl EngineEnvironment for StaticPathEngine {
        fn resolve_configured(
            &self,
            path: &Path,
            _launch_cwd: &Path,
        ) -> Result<PathBuf, EngineError> {
            Ok(path.to_path_buf())
        }

        fn find_on_path(&self, program: &str) -> Option<PathBuf> {
            (program == "ast-grep").then(|| PathBuf::from("path/ast-grep"))
        }

        fn probe_version(&self, _path: &Path) -> Result<VersionProbeOutput, EngineError> {
            panic!("PATH ast-grep discovery must not run a version probe")
        }
    }

    #[test]
    fn defaults_resolves_wrapper_settings_without_engine_access() {
        let invocation = NativeInvocation {
            command: WrapperCommand::Defaults,
            explicit: ExplicitOptions::default(),
            user_argv: vec!["run".into()],
        };
        let prepared = prepare_invocation(
            invocation,
            &ConfigStack::default(),
            Path::new("launch"),
            &NoEngineAccess,
        )
        .expect("defaults preparation should be pure");
        assert!(prepared.engine.is_none());
        assert_eq!(
            prepared.defaults.effective_argv,
            vec!["run", "--json=stream"]
        );
    }

    #[test]
    fn defaults_and_exec_share_the_exact_same_decision() {
        let base = NativeInvocation {
            command: WrapperCommand::Exec,
            explicit: ExplicitOptions::default(),
            user_argv: vec!["scan".into(), "src".into()],
        };
        let exec = prepare_invocation(
            base.clone(),
            &ConfigStack::default(),
            Path::new("launch"),
            &StaticPathEngine,
        )
        .expect("exec preparation should resolve");
        let defaults = prepare_invocation(
            NativeInvocation {
                command: WrapperCommand::Defaults,
                ..base
            },
            &ConfigStack::default(),
            Path::new("launch"),
            &NoEngineAccess,
        )
        .expect("defaults preparation should resolve");
        assert_eq!(defaults.defaults, exec.defaults);
    }
}
