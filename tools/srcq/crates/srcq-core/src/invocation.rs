use std::ffi::OsString;
use std::path::PathBuf;

use crate::cache::CacheMode;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WrapperCommand {
    Exec,
    Defaults,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Profile {
    TokenSafe,
    Locations,
    Lossless,
    Files,
    Custom,
}

impl Profile {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TokenSafe => "token-safe",
            Self::Locations => "locations",
            Self::Lossless => "lossless",
            Self::Files => "files",
            Self::Custom => "custom",
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ExplicitOptions {
    pub engine: Option<PathBuf>,
    pub cwd: Option<PathBuf>,
    pub yaml_out: Option<PathBuf>,
    pub artifact_out: Option<PathBuf>,
    pub stderr_yaml: Option<PathBuf>,
    pub meta_out: Option<PathBuf>,
    pub profile: Option<Profile>,
    pub cache_mode: Option<CacheMode>,
    pub fingerprint_files: Vec<PathBuf>,
    pub max_detail_results: Option<u32>,
    pub max_text_chars: Option<u32>,
    pub max_context_bytes: Option<u64>,
    pub keep_fields: Option<String>,
    pub prune_fields: Option<String>,
    pub no_native_defaults: bool,
    pub strict: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeInvocation {
    pub command: WrapperCommand,
    pub explicit: ExplicitOptions,
    pub user_argv: Vec<OsString>,
}
