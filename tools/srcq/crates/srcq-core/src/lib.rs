#![forbid(unsafe_code)]

#[cfg(not(windows))]
compile_error!("srcq is maintained and supported only on Windows");

pub mod adapters;
pub mod aggregate;
pub mod batch;
pub mod budget;
pub mod cache;
pub mod codec;
pub mod config;
pub mod context_batch;
pub mod defaults;
pub mod engine;
pub mod invocation;
pub mod passthrough;
pub mod prepare;
pub mod process;
pub mod processors;
pub mod profile;

/// Versioned boundary exposed by the protocol-independent core crate.
pub const CORE_API_LEVEL: u32 = 1;

/// Build metadata that adapters may report without importing CLI concerns.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BuildInfo {
    pub package_name: &'static str,
    pub package_version: &'static str,
    pub core_api_level: u32,
}

/// Returns compile-time metadata for diagnostics and adapter version output.
#[must_use]
pub const fn build_info() -> BuildInfo {
    BuildInfo {
        package_name: env!("CARGO_PKG_NAME"),
        package_version: env!("SRCQ_BUILD_VERSION"),
        core_api_level: CORE_API_LEVEL,
    }
}

#[cfg(test)]
mod tests {
    use super::{build_info, CORE_API_LEVEL};

    #[test]
    fn exposes_stable_core_boundary() {
        let info = build_info();
        assert_eq!(info.package_name, "srcq-core");
        assert_eq!(info.core_api_level, CORE_API_LEVEL);
    }
}
