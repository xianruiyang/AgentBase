use std::{
    ffi::{OsStr, OsString},
    path::{Path, PathBuf},
    time::Duration,
};

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::{
    codec::{ByteSpan, SourceRecord},
    invocation::Profile,
};

pub const CACHE_INDEX_SCHEMA: &str = "sgy.cache-index/v1";
pub const CACHE_METADATA_SCHEMA: &str = "sgy.cache-metadata/v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceFormat {
    JsonArray,
    JsonValue,
    JsonLines,
    Sarif,
}

impl SourceFormat {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::JsonArray => "json-array",
            Self::JsonValue => "json-value",
            Self::JsonLines => "jsonl",
            Self::Sarif => "sarif",
        }
    }

    #[must_use]
    pub const fn file_name(self) -> &'static str {
        match self {
            Self::JsonLines => "native.jsonl",
            Self::JsonArray | Self::JsonValue | Self::Sarif => "native.json",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, crate::cache::CacheError> {
        match value {
            "json-array" => Ok(Self::JsonArray),
            "json-value" => Ok(Self::JsonValue),
            "jsonl" => Ok(Self::JsonLines),
            "sarif" => Ok(Self::Sarif),
            _ => Err(crate::cache::CacheError::Verification(format!(
                "unknown source format {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CacheMode {
    Auto,
    On,
    Off,
}

impl CacheMode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::On => "on",
            Self::Off => "off",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CacheLimits {
    pub ttl: Duration,
    pub quota_bytes: u64,
    pub max_entry_bytes: u64,
    pub incomplete_ttl: Duration,
}

impl Default for CacheLimits {
    fn default() -> Self {
        Self {
            ttl: Duration::from_secs(7 * 24 * 60 * 60),
            quota_bytes: 1024 * 1024 * 1024,
            max_entry_bytes: 512 * 1024 * 1024,
            incomplete_ttl: Duration::from_secs(24 * 60 * 60),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CacheAudit {
    pub engine_path: PathBuf,
    pub engine_version: String,
    pub cwd: PathBuf,
    pub user_argv_sha256: String,
    pub effective_argv_sha256: String,
    pub injected: Vec<String>,
    pub profile: Profile,
    pub cache_mode: CacheMode,
}

impl CacheAudit {
    #[allow(clippy::too_many_arguments)]
    #[must_use]
    pub fn from_argv(
        engine_path: impl Into<PathBuf>,
        engine_version: impl Into<String>,
        cwd: impl Into<PathBuf>,
        user_argv: &[OsString],
        effective_argv: &[OsString],
        injected: Vec<String>,
        profile: Profile,
        cache_mode: CacheMode,
    ) -> Self {
        Self {
            engine_path: engine_path.into(),
            engine_version: engine_version.into(),
            cwd: cwd.into(),
            user_argv_sha256: hash_argv(user_argv),
            effective_argv_sha256: hash_argv(effective_argv),
            injected,
            profile,
            cache_mode,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CacheProcess {
    pub exit_code: Option<i32>,
    pub failure: Option<String>,
}

impl CacheProcess {
    #[must_use]
    pub const fn completed(exit_code: i32) -> Self {
        Self {
            exit_code: Some(exit_code),
            failure: None,
        }
    }

    #[must_use]
    pub fn incomplete(failure: impl Into<String>, exit_code: Option<i32>) -> Self {
        Self {
            exit_code,
            failure: Some(failure.into()),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct CacheIndexRecord {
    pub id: u64,
    pub byte_span: Option<ByteSpan>,
    pub pointer: Option<String>,
    pub file: Option<String>,
    pub range: Option<Value>,
    pub rule_id: Option<String>,
}

impl CacheIndexRecord {
    #[must_use]
    pub fn from_source(record: &SourceRecord) -> Self {
        let mapping = record.value.as_object();
        Self {
            id: record.ordinal,
            byte_span: Some(record.span),
            pointer: None,
            file: string_hint(mapping, "file"),
            range: mapping
                .and_then(|value| value.get("range"))
                .filter(|value| value.is_object())
                .cloned(),
            rule_id: string_hint(mapping, "ruleId"),
        }
    }

    #[must_use]
    pub fn with_pointer(id: u64, pointer: impl Into<String>, native: &Value) -> Self {
        let mapping = native.as_object();
        Self {
            id,
            byte_span: None,
            pointer: Some(pointer.into()),
            file: string_hint(mapping, "file"),
            range: mapping
                .and_then(|value| value.get("range"))
                .filter(|value| value.is_object())
                .cloned(),
            rule_id: string_hint(mapping, "ruleId"),
        }
    }

    #[must_use]
    pub fn with_sarif_pointer(id: u64, pointer: impl Into<String>, native: &Value) -> Self {
        let mapping = native.as_object();
        let physical = mapping
            .and_then(|value| value.get("locations"))
            .and_then(Value::as_array)
            .and_then(|locations| locations.first())
            .and_then(|location| location.get("physicalLocation"));
        let file = physical
            .and_then(|value| value.get("artifactLocation"))
            .and_then(|value| value.get("uri"))
            .and_then(Value::as_str)
            .map(ToOwned::to_owned);
        let range = physical
            .and_then(|value| value.get("region"))
            .filter(|value| value.is_object())
            .cloned();
        Self {
            id,
            byte_span: None,
            pointer: Some(pointer.into()),
            file,
            range,
            rule_id: string_hint(mapping, "ruleId"),
        }
    }

    pub(crate) fn to_value(&self) -> Value {
        let mut value = Map::new();
        value.insert("id".to_owned(), Value::from(self.id));
        if let Some(span) = self.byte_span {
            value.insert("byte_start".to_owned(), Value::from(span.start));
            value.insert("byte_end".to_owned(), Value::from(span.end));
        }
        if let Some(pointer) = &self.pointer {
            value.insert("pointer".to_owned(), Value::String(pointer.clone()));
        }
        if let Some(file) = &self.file {
            value.insert("file".to_owned(), Value::String(file.clone()));
        }
        if let Some(range) = &self.range {
            value.insert("range".to_owned(), range.clone());
        }
        if let Some(rule_id) = &self.rule_id {
            value.insert("ruleId".to_owned(), Value::String(rule_id.clone()));
        }
        Value::Object(value)
    }
}

fn string_hint(mapping: Option<&Map<String, Value>>, name: &str) -> Option<String> {
    mapping
        .and_then(|value| value.get(name))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
}

#[must_use]
pub fn hash_argv(tokens: &[OsString]) -> String {
    let mut hasher = Sha256::new();
    for token in tokens {
        let bytes = os_token_bytes(token.as_os_str());
        let length = u64::try_from(bytes.len()).unwrap_or(u64::MAX);
        hasher.update(length.to_le_bytes());
        hasher.update(bytes);
    }
    hex_lower(&hasher.finalize())
}

fn os_token_bytes(token: &OsStr) -> Vec<u8> {
    use std::os::windows::ffi::OsStrExt;
    token
        .encode_wide()
        .flat_map(u16::to_le_bytes)
        .collect::<Vec<_>>()
}

pub(crate) fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

pub(crate) fn path_text(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}
