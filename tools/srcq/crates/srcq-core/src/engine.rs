use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use thiserror::Error;

use crate::config::{ConfigSource, SelectedPath};

pub const VERSION_PROBE_TIMEOUT: Duration = Duration::from_secs(2);
pub const VERSION_STREAM_LIMIT: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EngineSource {
    Explicit,
    ProjectConfig,
    UserConfig,
    PathAstGrep,
    PathSg,
}

impl EngineSource {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Explicit => "explicit",
            Self::ProjectConfig => "project_config",
            Self::UserConfig => "user_config",
            Self::PathAstGrep => "path_ast_grep",
            Self::PathSg => "path_sg",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiscoveredEngine {
    pub path: PathBuf,
    pub source: EngineSource,
    pub version_line: Option<String>,
}

#[derive(Clone, Debug)]
pub struct VersionProbeOutput {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
}

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("configured ast-grep engine does not exist or is not a file: {0}")]
    ConfiguredEngineMissing(PathBuf),
    #[error("configured Windows engine is not a native .exe or recognized ast-grep npm shim: {0}")]
    ConfiguredEngineNotNative(PathBuf),
    #[error("no ast-grep engine was found on PATH and no trusted sg fallback was available")]
    NotFound,
    #[error("failed to start ast-grep version probe for {path}: {source}")]
    ProbeSpawn {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("ast-grep version probe timed out for {0}")]
    ProbeTimeout(PathBuf),
    #[error("ast-grep version probe failed for {path} with exit code {code:?}")]
    ProbeExit { path: PathBuf, code: Option<i32> },
    #[error("ast-grep version probe returned invalid UTF-8 or no non-empty stdout line for {0}")]
    InvalidVersion(PathBuf),
    #[error("PATH candidate sg is not ast-grep: {0}")]
    UntrustedSg(PathBuf),
    #[error("failed to read ast-grep version probe output for {path}: {source}")]
    ProbeIo {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("ast-grep version probe reader failed for {0}")]
    ProbeReader(PathBuf),
    #[error("launch-environment cwd cannot be used as a configured engine source")]
    InvalidConfiguredSource,
}

impl EngineError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> u8 {
        120
    }
}

pub trait EngineEnvironment {
    fn resolve_configured(&self, path: &Path, launch_cwd: &Path) -> Result<PathBuf, EngineError>;
    fn find_on_path(&self, program: &str) -> Option<PathBuf>;
    fn probe_version(&self, path: &Path) -> Result<VersionProbeOutput, EngineError>;
}

pub fn discover_engine(
    configured: Option<&SelectedPath>,
    launch_cwd: &Path,
    environment: &impl EngineEnvironment,
) -> Result<DiscoveredEngine, EngineError> {
    if let Some(configured) = configured {
        let path = environment.resolve_configured(&configured.path, launch_cwd)?;
        let source = match configured.source {
            ConfigSource::Explicit => EngineSource::Explicit,
            ConfigSource::Project => EngineSource::ProjectConfig,
            ConfigSource::User => EngineSource::UserConfig,
            ConfigSource::BuiltIn | ConfigSource::LaunchEnvironment => {
                return Err(EngineError::InvalidConfiguredSource)
            }
        };
        return Ok(DiscoveredEngine {
            path,
            source,
            version_line: None,
        });
    }

    if let Some(path) = environment.find_on_path("ast-grep") {
        return Ok(DiscoveredEngine {
            path,
            source: EngineSource::PathAstGrep,
            version_line: None,
        });
    }
    if let Some(path) = environment.find_on_path("sg") {
        return inspect_sg_candidate(path, environment);
    }
    Err(EngineError::NotFound)
}

fn inspect_sg_candidate(
    path: PathBuf,
    environment: &impl EngineEnvironment,
) -> Result<DiscoveredEngine, EngineError> {
    let probe = environment.probe_version(&path)?;
    if !probe.status.success() {
        return Err(EngineError::ProbeExit {
            path,
            code: probe.status.code(),
        });
    }
    let stdout = std::str::from_utf8(&probe.stdout)
        .map_err(|_| EngineError::InvalidVersion(path.clone()))?;
    let version_line = stdout
        .lines()
        .find(|line| !line.trim().is_empty())
        .map(str::trim)
        .ok_or_else(|| EngineError::InvalidVersion(path.clone()))?;
    if !version_line.starts_with("ast-grep ") {
        return Err(EngineError::UntrustedSg(path));
    }
    Ok(DiscoveredEngine {
        path,
        source: EngineSource::PathSg,
        version_line: Some(version_line.to_owned()),
    })
}

#[derive(Clone, Debug)]
pub struct SystemEngineEnvironment {
    path: Option<OsString>,
}

impl SystemEngineEnvironment {
    #[must_use]
    pub fn from_process_environment() -> Self {
        Self {
            path: std::env::var_os("PATH"),
        }
    }

    #[must_use]
    pub fn from_path(path: Option<OsString>) -> Self {
        Self { path }
    }

    fn path_candidates(&self, directory: &Path, program: &str) -> Vec<PathBuf> {
        let direct = directory.join(format!("{program}.exe"));
        let npm_shim = directory.join(format!("{program}.cmd"));
        let npm_binary = directory
            .join("node_modules")
            .join("@ast-grep")
            .join("cli")
            .join(format!("{program}.exe"));
        if npm_shim.is_file() {
            vec![direct, npm_binary]
        } else {
            vec![direct]
        }
    }
}

impl EngineEnvironment for SystemEngineEnvironment {
    fn resolve_configured(&self, path: &Path, launch_cwd: &Path) -> Result<PathBuf, EngineError> {
        let candidate = if path.is_absolute() {
            path.to_path_buf()
        } else {
            launch_cwd.join(path)
        };
        let candidate = resolve_windows_configured_candidate(candidate)?;
        let canonical = fs::canonicalize(&candidate)
            .map_err(|_| EngineError::ConfiguredEngineMissing(candidate.clone()))?;
        if !canonical.is_file() {
            return Err(EngineError::ConfiguredEngineMissing(canonical));
        }
        Ok(canonical)
    }

    fn find_on_path(&self, program: &str) -> Option<PathBuf> {
        let path = self.path.as_ref()?;
        for directory in std::env::split_paths(path) {
            for candidate in self.path_candidates(&directory, program) {
                if is_executable_file(&candidate) {
                    return fs::canonicalize(&candidate).ok().or(Some(candidate));
                }
            }
        }
        None
    }

    fn probe_version(&self, path: &Path) -> Result<VersionProbeOutput, EngineError> {
        probe_version_bounded(path, VERSION_PROBE_TIMEOUT, VERSION_STREAM_LIMIT)
    }
}

fn resolve_windows_configured_candidate(candidate: PathBuf) -> Result<PathBuf, EngineError> {
    let extension = candidate
        .extension()
        .and_then(OsStr::to_str)
        .map(str::to_ascii_lowercase);
    match extension.as_deref() {
        Some("exe") => Ok(candidate),
        Some("cmd") => {
            let stem = candidate
                .file_stem()
                .and_then(OsStr::to_str)
                .map(str::to_ascii_lowercase);
            if !matches!(stem.as_deref(), Some("ast-grep" | "sg")) {
                return Err(EngineError::ConfiguredEngineNotNative(candidate));
            }
            let directory = candidate
                .parent()
                .ok_or_else(|| EngineError::ConfiguredEngineNotNative(candidate.clone()))?;
            Ok(directory
                .join("node_modules")
                .join("@ast-grep")
                .join("cli")
                .join(format!("{}.exe", stem.as_deref().unwrap_or("ast-grep"))))
        }
        _ => Err(EngineError::ConfiguredEngineNotNative(candidate)),
    }
}

fn is_executable_file(path: &Path) -> bool {
    path.is_file()
}

fn probe_version_bounded(
    path: &Path,
    timeout: Duration,
    stream_limit: usize,
) -> Result<VersionProbeOutput, EngineError> {
    let mut child = Command::new(path)
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|source| EngineError::ProbeSpawn {
            path: path.to_path_buf(),
            source,
        })?;
    let stdout = child.stdout.take().ok_or_else(|| EngineError::ProbeIo {
        path: path.to_path_buf(),
        source: io::Error::other("stdout pipe was not available"),
    })?;
    let stderr = child.stderr.take().ok_or_else(|| EngineError::ProbeIo {
        path: path.to_path_buf(),
        source: io::Error::other("stderr pipe was not available"),
    })?;
    let stdout_reader = thread::spawn(move || read_capped(stdout, stream_limit));
    let stderr_reader = thread::spawn(move || read_capped(stderr, stream_limit));
    let started = Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait().map_err(|source| EngineError::ProbeIo {
            path: path.to_path_buf(),
            source,
        })? {
            break status;
        }
        if started.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_reader.join();
            let _ = stderr_reader.join();
            return Err(EngineError::ProbeTimeout(path.to_path_buf()));
        }
        thread::sleep(Duration::from_millis(10));
    };
    let (stdout, stdout_truncated) = stdout_reader
        .join()
        .map_err(|_| EngineError::ProbeReader(path.to_path_buf()))?
        .map_err(|source| EngineError::ProbeIo {
            path: path.to_path_buf(),
            source,
        })?;
    let (stderr, stderr_truncated) = stderr_reader
        .join()
        .map_err(|_| EngineError::ProbeReader(path.to_path_buf()))?
        .map_err(|source| EngineError::ProbeIo {
            path: path.to_path_buf(),
            source,
        })?;

    Ok(VersionProbeOutput {
        status,
        stdout,
        stderr,
        stdout_truncated,
        stderr_truncated,
    })
}

fn read_capped(reader: impl Read, limit: usize) -> io::Result<(Vec<u8>, bool)> {
    let read_limit = u64::try_from(limit).unwrap_or(u64::MAX).saturating_add(1);
    let mut bytes = Vec::with_capacity(limit.min(8192));
    reader.take(read_limit).read_to_end(&mut bytes)?;
    let truncated = bytes.len() > limit;
    bytes.truncate(limit);
    Ok((bytes, truncated))
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::process::ExitStatus;
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::{
        discover_engine, EngineEnvironment, EngineError, EngineSource, SystemEngineEnvironment,
        VersionProbeOutput,
    };
    use crate::config::{ConfigSource, SelectedPath};

    struct FakeEnvironment {
        ast_grep: Option<PathBuf>,
        sg: Option<PathBuf>,
        version_line: &'static str,
        probe_count: Cell<usize>,
    }

    impl FakeEnvironment {
        fn new(ast_grep: Option<&str>, sg: Option<&str>, version_line: &'static str) -> Self {
            Self {
                ast_grep: ast_grep.map(PathBuf::from),
                sg: sg.map(PathBuf::from),
                version_line,
                probe_count: Cell::new(0),
            }
        }
    }

    impl EngineEnvironment for FakeEnvironment {
        fn resolve_configured(
            &self,
            path: &Path,
            launch_cwd: &Path,
        ) -> Result<PathBuf, EngineError> {
            Ok(if path.is_absolute() {
                path.to_path_buf()
            } else {
                launch_cwd.join(path)
            })
        }

        fn find_on_path(&self, program: &str) -> Option<PathBuf> {
            match program {
                "ast-grep" => self.ast_grep.clone(),
                "sg" => self.sg.clone(),
                _ => None,
            }
        }

        fn probe_version(&self, _path: &Path) -> Result<VersionProbeOutput, EngineError> {
            self.probe_count.set(self.probe_count.get() + 1);
            Ok(VersionProbeOutput {
                status: success_status(),
                stdout: format!("\n{}\n", self.version_line).into_bytes(),
                stderr: Vec::new(),
                stdout_truncated: false,
                stderr_truncated: false,
            })
        }
    }

    fn success_status() -> ExitStatus {
        use std::os::windows::process::ExitStatusExt;

        ExitStatus::from_raw(0)
    }

    #[test]
    fn configured_engine_beats_path_and_resolves_from_launch_cwd() {
        let environment =
            FakeEnvironment::new(Some("path/ast-grep"), Some("path/sg"), "ast-grep 0.44.1");
        let configured = SelectedPath {
            path: PathBuf::from("tools/ast-grep"),
            source: ConfigSource::Explicit,
        };
        let discovered = discover_engine(Some(&configured), Path::new("launch"), &environment)
            .expect("configured engine should resolve");

        assert_eq!(discovered.path, Path::new("launch/tools/ast-grep"));
        assert_eq!(discovered.source, EngineSource::Explicit);
        assert_eq!(discovered.version_line, None);
        assert_eq!(environment.probe_count.get(), 0);
    }

    #[test]
    fn ast_grep_path_name_wins_without_touching_sg() {
        let environment =
            FakeEnvironment::new(Some("path/ast-grep"), Some("path/sg"), "ast-grep 0.42.0");
        let discovered = discover_engine(None, Path::new("launch"), &environment)
            .expect("ast-grep PATH candidate should resolve");
        assert_eq!(discovered.source, EngineSource::PathAstGrep);
        assert_eq!(discovered.path, Path::new("path/ast-grep"));
        assert_eq!(discovered.version_line, None);
        assert_eq!(environment.probe_count.get(), 0);
    }

    #[test]
    fn sg_fallback_requires_ast_grep_identity() {
        let trusted = FakeEnvironment::new(None, Some("path/sg"), "ast-grep 0.41.1");
        let discovered = discover_engine(None, Path::new("launch"), &trusted)
            .expect("trusted sg should resolve");
        assert_eq!(discovered.source, EngineSource::PathSg);
        assert_eq!(discovered.version_line.as_deref(), Some("ast-grep 0.41.1"));
        assert_eq!(trusted.probe_count.get(), 1);

        let untrusted = FakeEnvironment::new(None, Some("path/sg"), "sg 1.0.0");
        assert!(matches!(
            discover_engine(None, Path::new("launch"), &untrusted),
            Err(EngineError::UntrustedSg(_))
        ));
    }

    #[test]
    fn missing_candidates_have_stable_engine_error() {
        let environment = FakeEnvironment::new(None, None, "ast-grep 0.44.1");
        let error = discover_engine(None, Path::new("launch"), &environment)
            .expect_err("missing engine should fail");
        assert!(matches!(error, EngineError::NotFound));
        assert_eq!(error.wrapper_exit_code(), 120);
        assert_eq!(environment.probe_count.get(), 0);
    }

    #[test]
    fn system_path_search_is_limited_to_the_supplied_path() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock should be after Unix epoch")
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "srcq-engine-path-test-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).expect("create isolated PATH directory");
        let executable = directory.join("ast-grep.EXE");
        fs::write(&executable, []).expect("create PATH candidate");
        let path = std::env::join_paths([&directory]).expect("encode isolated PATH");
        let environment = SystemEngineEnvironment::from_path(Some(path));
        let discovered = environment
            .find_on_path("ast-grep")
            .expect("candidate should be found");
        assert_eq!(
            discovered,
            fs::canonicalize(&executable).expect("canonical test executable")
        );
        fs::remove_dir_all(&directory).expect("remove isolated PATH directory");
    }

    #[test]
    fn windows_npm_shim_resolves_to_native_binary_without_running_cmd() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock should be after Unix epoch")
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "srcq-engine-npm-test-{}-{nonce}",
            std::process::id()
        ));
        let package = directory.join("node_modules").join("@ast-grep").join("cli");
        fs::create_dir_all(&package).expect("create isolated npm package directory");
        fs::write(directory.join("ast-grep.cmd"), "must not execute")
            .expect("create npm shim marker");
        let native = package.join("ast-grep.exe");
        fs::write(&native, []).expect("create native binary marker");
        let path = std::env::join_paths([&directory]).expect("encode isolated PATH");
        let environment = SystemEngineEnvironment::from_path(Some(path));

        let discovered = environment
            .find_on_path("ast-grep")
            .expect("npm native binary should be found");
        assert_eq!(
            discovered,
            fs::canonicalize(&native).expect("canonical npm binary marker")
        );
        let configured = environment
            .resolve_configured(&directory.join("ast-grep.cmd"), Path::new("unused"))
            .expect("explicit npm shim should resolve to the native binary");
        assert_eq!(configured, discovered);
        fs::remove_dir_all(&directory).expect("remove isolated npm test directory");
    }

    #[test]
    fn capped_reader_marks_and_limits_oversized_output() {
        let input = vec![b'x'; 65_540];
        let (output, truncated) = super::read_capped(input.as_slice(), 65_536)
            .expect("in-memory bounded read should succeed");
        assert_eq!(output.len(), 65_536);
        assert!(truncated);
    }
}
