use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use srcq_core::cache::default_cache_root;
use srcq_core::codec::{parse_yaml_documents, write_yaml_document, CodecError};
use srcq_core::config::{
    builtin_defaults_document, load_standard_config, ConfigStack, LoadedConfigStack,
    MAX_CONFIG_BYTES, PROJECT_CONFIG_NAME,
};
use srcq_core::engine::{discover_engine, EngineEnvironment, EngineError};
use srcq_core::invocation::ExplicitOptions;
use srcq_core::{build_info, config};
use thiserror::Error;

const MAX_DIAGNOSTIC_BYTES: usize = 128 * 1024;

#[derive(Debug, Error)]
pub enum DiagnosticError {
    #[error("cannot encode diagnostic YAML: {0}")]
    Codec(#[from] CodecError),
    #[error("diagnostic YAML exceeds {MAX_DIAGNOSTIC_BYTES} bytes")]
    TooLarge,
}

impl DiagnosticError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> u8 {
        match self {
            Self::Codec(_) => 122,
            Self::TooLarge => 124,
        }
    }
}

#[derive(Debug)]
pub struct DoctorOutput {
    pub yaml: Vec<u8>,
    pub model: Vec<u8>,
    pub ok: bool,
}

pub fn render_config_schema() -> Result<Vec<u8>, DiagnosticError> {
    render(&json!({
        "schema": "sgy.schema/v1",
        "subject": "sgy.config/v1",
        "document": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://sgy.local/schema/config-v1",
            "type": "object",
            "additionalProperties": false,
            "required": ["schema"],
            "properties": {
                "schema": {"const": "sgy.config/v1"},
                "engine": {"type": "string", "minLength": 1},
                "cwd": {"type": "string", "minLength": 1},
                "profile": {"enum": ["token-safe", "locations", "lossless", "files", "custom"]},
                "native_defaults": {"type": "boolean"},
                "cache": {"enum": ["auto", "on", "off"]},
                "max_detail_results": {"type": "integer", "minimum": 1, "maximum": 4294967295_u64},
                "max_text_chars": {"type": "integer", "minimum": 0, "maximum": 4294967295_u64},
                "max_context_bytes": {"type": "integer", "minimum": 1},
                "keep_fields": {"type": "string"},
                "prune_fields": {"type": "string"}
            }
        },
        "scope_rules": {
            "project": {
                "filename": PROJECT_CONFIG_NAME,
                "forbidden_fields": ["engine", "cwd", "cache"],
                "reason": "project config cannot select executables, expand cwd, or enable writes"
            },
            "user": {"filename": "srcq/config.yml"}
        },
        "parser_limits": {
            "max_bytes": MAX_CONFIG_BYTES,
            "max_depth": 16,
            "max_nodes": 256,
            "documents": 1,
            "aliases_anchors_tags": "forbidden"
        }
    }))
}

pub fn render_capabilities() -> Result<Vec<u8>, DiagnosticError> {
    let build = build_info();
    render(&json!({
        "schema": "sgy.capabilities/v1",
        "wrapper": {"version": build.package_version},
        "commands": {
            "native": ["exec", "defaults"],
            "inspection": ["schema", "capabilities", "doctor"],
            "cache": ["get", "query", "info", "remove", "gc"],
            "process": ["validate", "select", "filter", "count", "group", "sort", "dedupe", "merge", "to-jsonl", "from-jsonl", "containing", "group-locations"]
        },
        "config": {
            "schema": config::CONFIG_SCHEMA,
            "precedence": ["explicit_native_argv", "explicit_sgy", "project", "user", "builtin"],
            "project_forbidden": ["engine", "cwd", "cache"]
        },
        "formats": {
            "input": ["json", "jsonl", "sarif", "safe_yaml"],
            "output": {
                "model": "payload-only-text",
                "machine": "yaml-1.2-safe-subset",
                "native": "passthrough-or-artifact"
            },
            "jsonl_round_trip": "common_data_model"
        },
        "yaml": {
            "aliases_anchors_tags": false,
            "duplicate_json_keys": false,
            "streaming_documents": true
        },
        "protocols": {
            "lsp": {"mode": "byte_passthrough", "yaml_output": false},
            "interactive_tty": {"mode": "inherited", "yaml_output": false}
        },
        "defaults": builtin_defaults_document(),
        "diagnostic_output_limit_bytes": MAX_DIAGNOSTIC_BYTES
    }))
}

pub fn run_doctor(
    engine: Option<PathBuf>,
    cwd: Option<PathBuf>,
    launch_cwd: &Path,
    environment: &impl EngineEnvironment,
) -> Result<DoctorOutput, DiagnosticError> {
    let loaded = load_standard_config(launch_cwd);
    let (config_check, stack, config_ok) = match loaded {
        Ok(loaded) => (config_check(&loaded), loaded.stack, true),
        Err(error) => (
            json!({"status": "invalid", "error": error.to_string()}),
            ConfigStack::default(),
            false,
        ),
    };
    let explicit = ExplicitOptions {
        engine,
        cwd,
        ..ExplicitOptions::default()
    };
    let settings = config::resolve_settings(&explicit, &stack, launch_cwd);
    let (workspace_check, workspace_ok) = diagnose_workspace(
        &settings.child_cwd.path,
        settings.child_cwd.source.as_str(),
        launch_cwd,
    );
    let (engine_check, engine_ok) = diagnose_engine(
        discover_engine(settings.engine.as_ref(), launch_cwd, environment),
        environment,
    );
    let (cache_check, cache_ok) = diagnose_cache();
    let (yaml_check, yaml_ok) = diagnose_yaml();
    let ok = config_ok && workspace_ok && engine_ok && cache_ok && yaml_ok;
    let document = json!({
        "schema": "sgy.doctor/v1",
        "ok": ok,
        "checks": {
            "config": config_check,
            "workspace": workspace_check,
            "engine": engine_check,
            "cache": cache_check,
            "yaml": yaml_check,
            "protocol": {
                "status": "limited",
                "lsp": "byte_passthrough_only",
                "interactive_tty": "inherited_no_yaml",
                "note": "protocol channels are intentionally excluded from YAML conversion"
            }
        },
        "scan_executed": false
    });
    Ok(DoctorOutput {
        yaml: render(&document)?,
        model: render_doctor_model(&document, ok),
        ok,
    })
}

fn render_doctor_model(document: &Value, ok: bool) -> Vec<u8> {
    if ok {
        return b"ok\n".to_vec();
    }
    let mut lines = Vec::new();
    if let Some(checks) = document.get("checks").and_then(Value::as_object) {
        for (name, check) in checks {
            let Some(mapping) = check.as_object() else {
                continue;
            };
            let status = mapping
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            if matches!(status, "ok" | "writable" | "not_created" | "limited") {
                continue;
            }
            let detail = mapping
                .get("error")
                .or_else(|| mapping.get("version"))
                .or_else(|| mapping.get("path"))
                .and_then(Value::as_str);
            lines.push(match detail {
                Some(detail) => format!("{name} {status}: {detail}"),
                None => format!("{name} {status}"),
            });
        }
    }
    lines.push("retry: srcq doctor --output machine".to_owned());
    format!("{}\n", lines.join("\n")).into_bytes()
}

fn diagnose_yaml() -> (Value, bool) {
    let expected = json!({"unicode": "中文", "values": [null, false, 1, "line\ntext"]});
    let mut encoded = Vec::new();
    let result = write_yaml_document(&expected, &mut encoded, false)
        .and_then(|_| parse_yaml_documents(&encoded))
        .map(|documents| documents == [expected]);
    match result {
        Ok(true) => (
            json!({
                "status": "ok",
                "round_trip_probe": "passed",
                "parser": "safe_yaml_1.2_subset",
                "aliases_anchors_tags": "rejected",
                "output": "bounded"
            }),
            true,
        ),
        Ok(false) => (
            json!({"status": "failed", "round_trip_probe": "semantic_mismatch"}),
            false,
        ),
        Err(error) => (
            json!({"status": "failed", "round_trip_probe": "codec_error", "error": error.to_string()}),
            false,
        ),
    }
}

fn diagnose_workspace(path: &Path, source: &str, launch_cwd: &Path) -> (Value, bool) {
    let resolved = if path.is_absolute() {
        path.to_path_buf()
    } else {
        launch_cwd.join(path)
    };
    match resolved.canonicalize() {
        Ok(canonical) if canonical.is_dir() => (
            json!({
                "status": "ok",
                "path": canonical.to_string_lossy(),
                "source": source
            }),
            true,
        ),
        Ok(canonical) => (
            json!({
                "status": "not_directory",
                "path": canonical.to_string_lossy(),
                "source": source
            }),
            false,
        ),
        Err(error) => (
            json!({
                "status": "missing_or_inaccessible",
                "path": resolved.to_string_lossy(),
                "source": source,
                "error": error.to_string()
            }),
            false,
        ),
    }
}

fn config_check(loaded: &LoadedConfigStack) -> Value {
    json!({
        "status": "ok",
        "project": {
            "path": loaded.project_path.to_string_lossy(),
            "loaded": loaded.project_loaded,
            "security": "context_only"
        },
        "user": {
            "path": loaded.user_path.as_ref().map(|path| path.to_string_lossy().into_owned()),
            "loaded": loaded.user_loaded
        }
    })
}

fn diagnose_engine(
    discovered: Result<srcq_core::engine::DiscoveredEngine, EngineError>,
    environment: &impl EngineEnvironment,
) -> (Value, bool) {
    let engine = match discovered {
        Ok(engine) => engine,
        Err(error) => {
            return (
                json!({"status": "missing_or_invalid", "error": error.to_string()}),
                false,
            )
        }
    };
    let version = if let Some(version) = engine.version_line.clone() {
        Ok(version)
    } else {
        environment.probe_version(&engine.path).and_then(|probe| {
            if !probe.status.success() {
                return Err(EngineError::ProbeExit {
                    path: engine.path.clone(),
                    code: probe.status.code(),
                });
            }
            String::from_utf8(probe.stdout)
                .ok()
                .and_then(|text| {
                    text.lines()
                        .find(|line| !line.trim().is_empty())
                        .map(str::trim)
                        .map(str::to_owned)
                })
                .ok_or_else(|| EngineError::InvalidVersion(engine.path.clone()))
        })
    };
    match version {
        Ok(version) if version.starts_with("ast-grep ") => (
            json!({
                "status": "ok",
                "path": engine.path.to_string_lossy(),
                "source": engine.source.as_str(),
                "version": version,
                "compatibility": "version_reported; command capabilities remain runtime-dependent"
            }),
            true,
        ),
        Ok(version) => (
            json!({
                "status": "unexpected_version",
                "path": engine.path.to_string_lossy(),
                "source": engine.source.as_str(),
                "version": version
            }),
            false,
        ),
        Err(error) => (
            json!({
                "status": "version_probe_failed",
                "path": engine.path.to_string_lossy(),
                "source": engine.source.as_str(),
                "error": error.to_string()
            }),
            false,
        ),
    }
}

fn diagnose_cache() -> (Value, bool) {
    let root = match default_cache_root() {
        Ok(root) => root,
        Err(error) => {
            return (
                json!({"status": "unavailable", "error": error.to_string()}),
                false,
            )
        }
    };
    if !root.exists() {
        let parent = nearest_existing_parent(&root);
        let read_only = parent
            .as_ref()
            .and_then(|path| path.metadata().ok())
            .is_some_and(|metadata| metadata.permissions().readonly());
        return (
            json!({
                "status": "not_created",
                "path": root.to_string_lossy(),
                "nearest_existing_parent": parent.map(|path| path.to_string_lossy().into_owned()),
                "parent_read_only": read_only,
                "permission": "unknown_until_cache_root_is_created",
                "write_probe": "not_run_outside_cache_root"
            }),
            !read_only,
        );
    }
    if !root.is_dir() {
        return (
            json!({"status": "invalid", "path": root.to_string_lossy(), "error": "cache root is not a directory"}),
            false,
        );
    }
    match tempfile::Builder::new()
        .prefix(".srcq-doctor-")
        .tempfile_in(&root)
    {
        Ok(probe) => {
            drop(probe);
            (
                json!({"status": "writable", "path": root.to_string_lossy(), "write_probe": "temporary_file_removed"}),
                true,
            )
        }
        Err(error) => (
            json!({"status": "not_writable", "path": root.to_string_lossy(), "error": error.to_string()}),
            false,
        ),
    }
}

fn nearest_existing_parent(path: &Path) -> Option<PathBuf> {
    path.ancestors()
        .find(|candidate| candidate.exists())
        .map(Path::to_path_buf)
}

fn render(document: &Value) -> Result<Vec<u8>, DiagnosticError> {
    let mut output = Vec::new();
    write_yaml_document(document, &mut output, false)?;
    if output.len() > MAX_DIAGNOSTIC_BYTES {
        return Err(DiagnosticError::TooLarge);
    }
    Ok(output)
}

#[cfg(test)]
mod tests {
    use std::path::{Path, PathBuf};
    use std::process::ExitStatus;

    use srcq_core::engine::{EngineEnvironment, EngineError, VersionProbeOutput};

    use super::{diagnose_engine, render_capabilities, render_config_schema};

    struct NoEngine;
    struct WrongVersion;

    impl EngineEnvironment for NoEngine {
        fn resolve_configured(&self, path: &Path, _: &Path) -> Result<PathBuf, EngineError> {
            Ok(path.to_path_buf())
        }
        fn find_on_path(&self, _: &str) -> Option<PathBuf> {
            None
        }
        fn probe_version(&self, _: &Path) -> Result<VersionProbeOutput, EngineError> {
            panic!("missing engine must not be probed")
        }
    }

    impl EngineEnvironment for WrongVersion {
        fn resolve_configured(&self, path: &Path, _: &Path) -> Result<PathBuf, EngineError> {
            Ok(path.to_path_buf())
        }
        fn find_on_path(&self, program: &str) -> Option<PathBuf> {
            (program == "ast-grep").then(|| PathBuf::from("ast-grep"))
        }
        fn probe_version(&self, _: &Path) -> Result<VersionProbeOutput, EngineError> {
            Ok(VersionProbeOutput {
                status: success_status(),
                stdout: b"not-ast-grep 1.0\n".to_vec(),
                stderr: Vec::new(),
                stdout_truncated: false,
                stderr_truncated: false,
            })
        }
    }

    #[test]
    fn static_inspection_outputs_are_bounded_safe_yaml() {
        for bytes in [
            render_config_schema().expect("schema"),
            render_capabilities().expect("capabilities"),
        ] {
            assert!(bytes.len() < 128 * 1024);
            let docs = srcq_core::codec::parse_yaml_documents(&bytes).expect("safe YAML");
            assert_eq!(docs.len(), 1);
        }
    }

    #[test]
    fn engine_diagnostic_distinguishes_missing_engine() {
        let (check, ok) = diagnose_engine(Err(EngineError::NotFound), &NoEngine);
        assert!(!ok);
        assert_eq!(check["status"], "missing_or_invalid");
    }

    #[test]
    fn doctor_distinguishes_an_unexpected_engine_version() {
        let discovered = srcq_core::engine::discover_engine(None, Path::new("."), &WrongVersion)
            .expect("engine discovery");
        let (check, ok) = diagnose_engine(Ok(discovered), &WrongVersion);
        assert!(!ok);
        assert_eq!(check["status"], "unexpected_version");
    }

    fn success_status() -> ExitStatus {
        use std::os::windows::process::ExitStatusExt;
        ExitStatus::from_raw(0)
    }
}
