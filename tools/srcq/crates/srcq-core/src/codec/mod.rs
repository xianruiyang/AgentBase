//! Generic JSON/JSONL to safe, lossless YAML 1.2 conversion.

mod json;
mod transcode;
mod yaml;

use std::{io, ops::Range};

pub use json::{parse_single_json, JsonLines, SourceRecord};
pub use transcode::{transcode_lossless, JsonInputKind, TranscodeStats};
pub use yaml::{
    parse_yaml_config_documents_with_limits, parse_yaml_documents,
    parse_yaml_documents_with_limits, write_compact_yaml_document, write_yaml_document,
    YamlParseLimits,
};

use thiserror::Error;

/// Half-open byte range in the original native stream.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ByteSpan {
    pub start: u64,
    pub end: u64,
}

impl ByteSpan {
    #[must_use]
    pub const fn new(start: u64, end: u64) -> Self {
        Self { start, end }
    }

    #[must_use]
    pub const fn len(self) -> u64 {
        self.end.saturating_sub(self.start)
    }

    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.start >= self.end
    }
}

impl From<Range<u64>> for ByteSpan {
    fn from(value: Range<u64>) -> Self {
        Self::new(value.start, value.end)
    }
}

#[derive(Debug, Error)]
pub enum CodecError {
    #[error("cannot read native structured output: {0}")]
    InputIo(#[source] io::Error),
    #[error("native structured output is not UTF-8 at byte {byte_offset}")]
    InvalidUtf8 { byte_offset: u64 },
    #[error("native JSON record {ordinal} at bytes {span:?} is invalid: {message}")]
    InvalidJson {
        ordinal: u64,
        span: ByteSpan,
        message: String,
    },
    #[error("native JSON record {ordinal} repeats key {key:?} at byte {byte_offset}")]
    DuplicateJsonKey {
        ordinal: u64,
        key: String,
        byte_offset: u64,
    },
    #[error("cannot write lossless YAML: {0}")]
    OutputIo(#[source] io::Error),
    #[error("cannot encode lossless YAML scalar: {0}")]
    Encode(String),
    #[error("YAML is invalid: {0}")]
    InvalidYaml(String),
    #[error("YAML uses a forbidden feature: {0}")]
    UnsafeYaml(String),
}

impl CodecError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::InputIo(_) => 126,
            Self::InvalidUtf8 { .. } | Self::InvalidJson { .. } | Self::DuplicateJsonKey { .. } => {
                121
            }
            Self::OutputIo(_) | Self::Encode(_) | Self::InvalidYaml(_) | Self::UnsafeYaml(_) => 122,
        }
    }
}

fn usize_to_u64(value: usize) -> Result<u64, CodecError> {
    u64::try_from(value).map_err(|error| CodecError::Encode(error.to_string()))
}
