use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value};
use thiserror::Error;

use crate::budget::{
    DEFAULT_MAX_CONTEXT_BYTES, DEFAULT_MAX_DETAIL_RESULTS, DEFAULT_MAX_TEXT_CHARS,
};
use crate::cache::CacheMode;
use crate::codec::{parse_yaml_config_documents_with_limits, CodecError, YamlParseLimits};
use crate::invocation::{ExplicitOptions, Profile};

pub const CONFIG_SCHEMA: &str = "sgy.config/v1";
pub const PROJECT_CONFIG_NAME: &str = ".sgy.yml";
pub const MAX_CONFIG_BYTES: u64 = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConfigSource {
    Explicit,
    Project,
    User,
    BuiltIn,
    LaunchEnvironment,
}

impl ConfigSource {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Explicit => "explicit",
            Self::Project => "project",
            Self::User => "user",
            Self::BuiltIn => "builtin",
            Self::LaunchEnvironment => "launch_environment",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConfigScope {
    Project,
    User,
}

impl ConfigScope {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Project => "project",
            Self::User => "user",
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct BasicConfig {
    pub engine: Option<PathBuf>,
    pub cwd: Option<PathBuf>,
    pub profile: Option<Profile>,
    pub native_defaults: Option<bool>,
    pub cache_mode: Option<CacheMode>,
    pub max_detail_results: Option<u32>,
    pub max_text_chars: Option<u32>,
    pub max_context_bytes: Option<u64>,
    pub keep_fields: Option<String>,
    pub prune_fields: Option<String>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ConfigStack {
    pub project: Option<BasicConfig>,
    pub user: Option<BasicConfig>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoadedConfigStack {
    pub stack: ConfigStack,
    pub project_path: PathBuf,
    pub project_loaded: bool,
    pub user_path: Option<PathBuf>,
    pub user_loaded: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedPath {
    pub path: PathBuf,
    pub source: ConfigSource,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedSettings {
    pub engine: Option<SelectedPath>,
    pub child_cwd: SelectedPath,
    pub inherit_environment: bool,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("cannot inspect {scope} config {path}: {source}")]
    Metadata {
        scope: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("cannot read {scope} config {path}: {source}")]
    Read {
        scope: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("{scope} config {path} exceeds {MAX_CONFIG_BYTES} bytes")]
    TooLarge { scope: &'static str, path: PathBuf },
    #[error("{scope} config {path} is unsafe or invalid: {source}")]
    Codec {
        scope: &'static str,
        path: PathBuf,
        #[source]
        source: CodecError,
    },
    #[error("{scope} config {path}: {message}")]
    Schema {
        scope: &'static str,
        path: PathBuf,
        message: String,
    },
}

impl ConfigError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> u8 {
        match self {
            Self::Metadata { .. } | Self::Read { .. } => 126,
            Self::TooLarge { .. } | Self::Codec { .. } | Self::Schema { .. } => 125,
        }
    }
}

#[must_use]
pub fn project_config_path(launch_cwd: &Path) -> PathBuf {
    launch_cwd.join(PROJECT_CONFIG_NAME)
}

#[must_use]
pub fn default_user_config_path() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        env::var_os("APPDATA")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .map(|root| root.join("sgy").join("config.yml"))
    }
    #[cfg(target_os = "macos")]
    {
        env::var_os("HOME")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .map(|root| {
                root.join("Library")
                    .join("Application Support")
                    .join("sgy")
                    .join("config.yml")
            })
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        if let Some(root) = env::var_os("XDG_CONFIG_HOME").filter(|value| !value.is_empty()) {
            return Some(PathBuf::from(root).join("sgy").join("config.yml"));
        }
        env::var_os("HOME")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .map(|root| root.join(".config").join("sgy").join("config.yml"))
    }
    #[cfg(not(any(unix, windows)))]
    {
        None
    }
}

pub fn load_standard_config(launch_cwd: &Path) -> Result<LoadedConfigStack, ConfigError> {
    load_config_paths(
        &project_config_path(launch_cwd),
        default_user_config_path().as_deref(),
    )
}

pub fn load_config_paths(
    project_path: &Path,
    user_path: Option<&Path>,
) -> Result<LoadedConfigStack, ConfigError> {
    let project = load_optional_config(project_path, ConfigScope::Project)?;
    let user = user_path
        .map(|path| load_optional_config(path, ConfigScope::User))
        .transpose()?
        .flatten();
    Ok(LoadedConfigStack {
        stack: ConfigStack {
            project: project.clone(),
            user: user.clone(),
        },
        project_path: project_path.to_path_buf(),
        project_loaded: project.is_some(),
        user_path: user_path.map(Path::to_path_buf),
        user_loaded: user.is_some(),
    })
}

fn load_optional_config(
    path: &Path,
    scope: ConfigScope,
) -> Result<Option<BasicConfig>, ConfigError> {
    let metadata = match fs::metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(source) => {
            return Err(ConfigError::Metadata {
                scope: scope.as_str(),
                path: path.to_path_buf(),
                source,
            })
        }
    };
    if !metadata.is_file() {
        return Err(schema_error(
            scope,
            path,
            "config path is not a regular file",
        ));
    }
    if metadata.len() > MAX_CONFIG_BYTES {
        return Err(ConfigError::TooLarge {
            scope: scope.as_str(),
            path: path.to_path_buf(),
        });
    }
    let bytes = fs::read(path).map_err(|source| ConfigError::Read {
        scope: scope.as_str(),
        path: path.to_path_buf(),
        source,
    })?;
    let documents = parse_yaml_config_documents_with_limits(
        &bytes,
        YamlParseLimits {
            max_input_bytes: MAX_CONFIG_BYTES,
            max_depth: 16,
            max_nodes: 256,
            max_documents: 1,
        },
    )
    .map_err(|source| ConfigError::Codec {
        scope: scope.as_str(),
        path: path.to_path_buf(),
        source,
    })?;
    let Some(value) = documents.into_iter().next() else {
        return Err(schema_error(
            scope,
            path,
            "config must contain one YAML document",
        ));
    };
    parse_config(value, scope, path).map(Some)
}

fn parse_config(value: Value, scope: ConfigScope, path: &Path) -> Result<BasicConfig, ConfigError> {
    let object = value
        .as_object()
        .ok_or_else(|| schema_error(scope, path, "config root must be a mapping"))?;
    let schema = string_field(object, "schema", scope, path)?
        .ok_or_else(|| schema_error(scope, path, "missing required string field `schema`"))?;
    if schema != CONFIG_SCHEMA {
        return Err(schema_error(
            scope,
            path,
            format!("unsupported schema {schema:?}; expected {CONFIG_SCHEMA:?}"),
        ));
    }
    let allowed: BTreeSet<&str> = [
        "schema",
        "engine",
        "cwd",
        "profile",
        "native_defaults",
        "cache",
        "max_detail_results",
        "max_text_chars",
        "max_context_bytes",
        "keep_fields",
        "prune_fields",
    ]
    .into_iter()
    .collect();
    if let Some(field) = object
        .keys()
        .find(|field| !allowed.contains(field.as_str()))
    {
        return Err(schema_error(
            scope,
            path,
            format!("unknown field {field:?}"),
        ));
    }
    if scope == ConfigScope::Project {
        for forbidden in ["engine", "cwd", "cache"] {
            if object.contains_key(forbidden) {
                return Err(schema_error(
                    scope,
                    path,
                    format!("field {forbidden:?} is forbidden in project config"),
                ));
            }
        }
    }
    let profile = match string_field(object, "profile", scope, path)? {
        Some("token-safe") => Some(Profile::TokenSafe),
        Some("locations") => Some(Profile::Locations),
        Some("lossless") => Some(Profile::Lossless),
        Some("files") => Some(Profile::Files),
        Some("custom") => Some(Profile::Custom),
        Some(other) => {
            return Err(schema_error(
                scope,
                path,
                format!("invalid profile {other:?}"),
            ))
        }
        None => None,
    };
    let cache_mode = match string_field(object, "cache", scope, path)? {
        Some("auto") => Some(CacheMode::Auto),
        Some("on") => Some(CacheMode::On),
        Some("off") => Some(CacheMode::Off),
        Some(other) => {
            return Err(schema_error(
                scope,
                path,
                format!("invalid cache mode {other:?}"),
            ))
        }
        None => None,
    };
    let config = BasicConfig {
        engine: path_field(object, "engine", scope, path)?,
        cwd: path_field(object, "cwd", scope, path)?,
        profile,
        native_defaults: bool_field(object, "native_defaults", scope, path)?,
        cache_mode,
        max_detail_results: u32_field(object, "max_detail_results", true, scope, path)?,
        max_text_chars: u32_field(object, "max_text_chars", false, scope, path)?,
        max_context_bytes: u64_field(object, "max_context_bytes", true, scope, path)?,
        keep_fields: string_field(object, "keep_fields", scope, path)?.map(str::to_owned),
        prune_fields: string_field(object, "prune_fields", scope, path)?.map(str::to_owned),
    };
    if profile != Some(Profile::Custom)
        && (config.keep_fields.is_some() || config.prune_fields.is_some())
    {
        return Err(schema_error(
            scope,
            path,
            "keep_fields/prune_fields require profile: custom",
        ));
    }
    Ok(config)
}

fn path_field(
    object: &Map<String, Value>,
    field: &str,
    scope: ConfigScope,
    path: &Path,
) -> Result<Option<PathBuf>, ConfigError> {
    string_field(object, field, scope, path)?
        .map(|value| {
            if value.is_empty() {
                Err(schema_error(
                    scope,
                    path,
                    format!("field {field:?} must not be empty"),
                ))
            } else {
                Ok(PathBuf::from(value))
            }
        })
        .transpose()
}

fn string_field<'a>(
    object: &'a Map<String, Value>,
    field: &str,
    scope: ConfigScope,
    path: &Path,
) -> Result<Option<&'a str>, ConfigError> {
    object
        .get(field)
        .map(|value| {
            value.as_str().ok_or_else(|| {
                schema_error(scope, path, format!("field {field:?} must be a string"))
            })
        })
        .transpose()
}

fn bool_field(
    object: &Map<String, Value>,
    field: &str,
    scope: ConfigScope,
    path: &Path,
) -> Result<Option<bool>, ConfigError> {
    object
        .get(field)
        .map(|value| {
            value.as_bool().ok_or_else(|| {
                schema_error(scope, path, format!("field {field:?} must be a boolean"))
            })
        })
        .transpose()
}

fn u32_field(
    object: &Map<String, Value>,
    field: &str,
    positive: bool,
    scope: ConfigScope,
    path: &Path,
) -> Result<Option<u32>, ConfigError> {
    u64_field(object, field, positive, scope, path)?
        .map(|value| {
            u32::try_from(value)
                .map_err(|_| schema_error(scope, path, format!("field {field:?} exceeds u32")))
        })
        .transpose()
}

fn u64_field(
    object: &Map<String, Value>,
    field: &str,
    positive: bool,
    scope: ConfigScope,
    path: &Path,
) -> Result<Option<u64>, ConfigError> {
    object
        .get(field)
        .map(|value| {
            let number = value.as_u64().ok_or_else(|| {
                schema_error(
                    scope,
                    path,
                    format!("field {field:?} must be a non-negative integer"),
                )
            })?;
            if positive && number == 0 {
                return Err(schema_error(
                    scope,
                    path,
                    format!("field {field:?} must be greater than zero"),
                ));
            }
            Ok(number)
        })
        .transpose()
}

fn schema_error(scope: ConfigScope, path: &Path, message: impl Into<String>) -> ConfigError {
    ConfigError::Schema {
        scope: scope.as_str(),
        path: path.to_path_buf(),
        message: message.into(),
    }
}

#[must_use]
pub fn resolve_settings(
    explicit: &ExplicitOptions,
    config: &ConfigStack,
    launch_cwd: &Path,
) -> ResolvedSettings {
    let engine = select_optional_path(
        explicit.engine.as_ref(),
        config
            .project
            .as_ref()
            .and_then(|value| value.engine.as_ref()),
        config.user.as_ref().and_then(|value| value.engine.as_ref()),
    );
    let child_cwd = select_optional_path(
        explicit.cwd.as_ref(),
        config.project.as_ref().and_then(|value| value.cwd.as_ref()),
        config.user.as_ref().and_then(|value| value.cwd.as_ref()),
    )
    .unwrap_or_else(|| SelectedPath {
        path: launch_cwd.to_path_buf(),
        source: ConfigSource::LaunchEnvironment,
    });

    ResolvedSettings {
        engine,
        child_cwd,
        inherit_environment: true,
    }
}

fn select_optional_path(
    explicit: Option<&PathBuf>,
    project: Option<&PathBuf>,
    user: Option<&PathBuf>,
) -> Option<SelectedPath> {
    explicit
        .map(|path| SelectedPath {
            path: path.clone(),
            source: ConfigSource::Explicit,
        })
        .or_else(|| {
            project.map(|path| SelectedPath {
                path: path.clone(),
                source: ConfigSource::Project,
            })
        })
        .or_else(|| {
            user.map(|path| SelectedPath {
                path: path.clone(),
                source: ConfigSource::User,
            })
        })
}

#[must_use]
pub fn builtin_defaults_document() -> Value {
    serde_json::json!({
        "schema": "sgy.builtin-defaults/v1",
        "profile": "token-safe",
        "native_defaults": true,
        "cache": "auto",
        "max_detail_results": DEFAULT_MAX_DETAIL_RESULTS,
        "max_text_chars": DEFAULT_MAX_TEXT_CHARS,
        "max_context_bytes": DEFAULT_MAX_CONTEXT_BYTES,
        "project_config": {
            "filename": PROJECT_CONFIG_NAME,
            "forbidden_fields": ["engine", "cwd", "cache"],
        },
        "config_schema": CONFIG_SCHEMA,
    })
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::{Path, PathBuf};

    use tempfile::tempdir;

    use super::{load_config_paths, resolve_settings, BasicConfig, ConfigSource, ConfigStack};
    use crate::invocation::ExplicitOptions;

    #[test]
    fn explicit_values_beat_project_and_user_config() {
        let explicit = ExplicitOptions {
            engine: Some(PathBuf::from("explicit-engine")),
            cwd: Some(PathBuf::from("explicit-cwd")),
            ..ExplicitOptions::default()
        };
        let config = ConfigStack {
            project: Some(BasicConfig {
                engine: Some(PathBuf::from("project-engine")),
                cwd: Some(PathBuf::from("project-cwd")),
                ..BasicConfig::default()
            }),
            user: Some(BasicConfig {
                engine: Some(PathBuf::from("user-engine")),
                cwd: Some(PathBuf::from("user-cwd")),
                ..BasicConfig::default()
            }),
        };

        let resolved = resolve_settings(&explicit, &config, Path::new("launch"));
        assert_eq!(
            resolved.engine.as_ref().map(|value| value.source),
            Some(ConfigSource::Explicit)
        );
        assert_eq!(resolved.child_cwd.source, ConfigSource::Explicit);
    }

    #[test]
    fn safe_project_and_user_configs_load_with_fixed_scope_rules() {
        let temp = tempdir().expect("tempdir");
        let project = temp.path().join(".sgy.yml");
        let user = temp.path().join("config.yml");
        fs::write(
            &project,
            "schema: sgy.config/v1\nprofile: custom\nmax_detail_results: 12\nkeep_fields: file,range\n",
        )
        .expect("project config");
        fs::write(
            &user,
            "schema: sgy.config/v1\nengine: tools/ast-grep\ncache: off\nmax_detail_results: 20\n",
        )
        .expect("user config");
        let loaded = load_config_paths(&project, Some(&user)).expect("configs");
        assert!(loaded.project_loaded);
        assert!(loaded.user_loaded);
        assert_eq!(
            loaded
                .stack
                .project
                .as_ref()
                .and_then(|v| v.max_detail_results),
            Some(12)
        );
        assert_eq!(
            loaded.stack.user.as_ref().and_then(|v| v.engine.as_deref()),
            Some(Path::new("tools/ast-grep"))
        );
    }

    #[test]
    fn project_config_cannot_select_engine_cwd_cache_or_unknown_output_fields() {
        let temp = tempdir().expect("tempdir");
        for (name, field) in [
            ("engine", "engine: ./owned-engine"),
            ("cwd", "cwd: .."),
            ("cache", "cache: on"),
            ("output", "yaml_out: result.yml"),
        ] {
            let project = temp.path().join(format!("{name}.yml"));
            fs::write(&project, format!("schema: sgy.config/v1\n{field}\n")).expect("config");
            assert!(load_config_paths(&project, None).is_err(), "{name}");
        }
    }
}
