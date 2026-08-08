//! Private, content-address-verified staging and committed cache entries.

mod model;
mod reader;
mod staging;
mod store;

pub use model::{
    hash_argv, CacheAudit, CacheIndexRecord, CacheLimits, CacheMode, CacheProcess, SourceFormat,
};
pub use reader::{CacheIndexIter, CacheQuery, CacheQueryResult, CachedResult, VerifiedCache};
pub use staging::{CacheStaging, CommittedCache};
pub use store::{default_cache_root, validate_cache_id, CacheEntryLease, CacheStore, GcReport};

use std::{io, path::PathBuf};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("cache environment is unavailable: {0}")]
    Environment(&'static str),
    #[error("cache staging is disabled by cache=off")]
    Disabled,
    #[error("cache path is unsafe: {0}")]
    UnsafePath(PathBuf),
    #[error("cache root {cache_root} must not be inside workspace {workspace}")]
    WorkspaceRoot {
        cache_root: PathBuf,
        workspace: PathBuf,
    },
    #[error("cache I/O failed during {operation} at {path}: {source}")]
    Io {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("cache serialization failed: {0}")]
    Serialization(String),
    #[error("cache source exceeds the {limit} byte entry limit")]
    EntryTooLarge { limit: u64 },
    #[error("cache quota cannot reserve {required} bytes within limit {limit}")]
    Quota { required: u64, limit: u64 },
    #[error("cache index is invalid: {0}")]
    InvalidIndex(String),
    #[error("cache source verification failed: {0}")]
    Verification(String),
    #[error("cache id is invalid: {0}")]
    InvalidId(String),
    #[error("cache entry was not found: {0}")]
    NotFound(String),
    #[error("cache selection is invalid: {0}")]
    InvalidSelection(String),
    #[error("cache entry already exists after id allocation: {0}")]
    Conflict(String),
    #[error("cache lock is busy: {0}")]
    Busy(PathBuf),
    #[error("cache timestamp is invalid: {0}")]
    InvalidTime(String),
}

impl CacheError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        123
    }
}

pub(crate) fn io_error(
    operation: &'static str,
    path: impl Into<PathBuf>,
    source: io::Error,
) -> CacheError {
    CacheError::Io {
        operation,
        path: path.into(),
        source,
    }
}
