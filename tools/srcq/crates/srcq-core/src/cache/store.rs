use std::{
    env,
    ffi::OsString,
    fs::{self, File, OpenOptions},
    io,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, SystemTime},
};

use fs2::FileExt;
use serde_json::Value;

use crate::codec::parse_yaml_documents;

use super::{io_error, CacheAudit, CacheError, CacheLimits, CacheStaging, SourceFormat};

const STAGING_DIR: &str = ".staging";
const INCOMPLETE_DIR: &str = ".incomplete";
const GC_LOCK: &str = "gc.lock";
const ACCESS_LOCK: &str = "access.lock";

#[derive(Clone, Debug)]
pub struct CacheStore {
    root: Arc<PathBuf>,
    limits: CacheLimits,
}

impl CacheStore {
    pub fn open(
        root: impl AsRef<Path>,
        workspace: Option<&Path>,
        limits: CacheLimits,
    ) -> Result<Self, CacheError> {
        if root
            .as_ref()
            .components()
            .any(|component| matches!(component, std::path::Component::ParentDir))
        {
            return Err(CacheError::UnsafePath(root.as_ref().to_path_buf()));
        }
        let workspace = workspace
            .map(|workspace| {
                workspace.canonicalize().map_err(|source| {
                    io_error(
                        "canonicalize workspace for cache boundary",
                        workspace,
                        source,
                    )
                })
            })
            .transpose()?;
        let anticipated = anticipate_canonical_path(root.as_ref())?;
        if let Some(workspace) = &workspace {
            if anticipated.starts_with(workspace) {
                return Err(CacheError::WorkspaceRoot {
                    cache_root: anticipated,
                    workspace: workspace.clone(),
                });
            }
        }
        if let Ok(metadata) = fs::symlink_metadata(root.as_ref()) {
            if metadata.file_type().is_symlink() || is_windows_reparse(&metadata) {
                return Err(CacheError::UnsafePath(root.as_ref().to_path_buf()));
            }
        }
        create_private_directory(root.as_ref())?;
        let root = root
            .as_ref()
            .canonicalize()
            .map_err(|source| io_error("canonicalize cache root", root.as_ref(), source))?;
        ensure_safe_directory(&root)?;
        if let Some(workspace) = workspace {
            if root.starts_with(&workspace) {
                return Err(CacheError::WorkspaceRoot {
                    cache_root: root,
                    workspace,
                });
            }
        }
        create_private_directory(&root.join(STAGING_DIR))?;
        create_private_directory(&root.join(INCOMPLETE_DIR))?;
        let gc_lock = root.join(GC_LOCK);
        let _ = open_private_lock(&gc_lock)?;
        Ok(Self {
            root: Arc::new(root),
            limits,
        })
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        self.root.as_path()
    }

    #[must_use]
    pub const fn limits(&self) -> CacheLimits {
        self.limits
    }

    pub fn begin(
        &self,
        format: SourceFormat,
        audit: CacheAudit,
        now: SystemTime,
    ) -> Result<CacheStaging, CacheError> {
        if audit.cache_mode == super::CacheMode::Off {
            return Err(CacheError::Disabled);
        }
        CacheStaging::create(self.clone(), format, audit, now)
    }

    pub fn entry_path(&self, cache_id: &str) -> Result<PathBuf, CacheError> {
        validate_cache_id(cache_id)?;
        Ok(self.root.join(cache_id))
    }

    pub fn acquire_entry(&self, cache_id: &str) -> Result<CacheEntryLease, CacheError> {
        let path = self.entry_path(cache_id)?;
        if !path.exists() {
            return Err(CacheError::NotFound(cache_id.to_owned()));
        }
        ensure_safe_directory(&path)?;
        let lock_path = path.join(ACCESS_LOCK);
        ensure_safe_file(&lock_path)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|source| io_error("open cache entry lock", &lock_path, source))?;
        FileExt::try_lock_shared(&lock).map_err(|source| {
            if is_lock_contended(&source) {
                CacheError::Busy(path.clone())
            } else {
                io_error("lock cache entry for reading", &lock_path, source)
            }
        })?;
        Ok(CacheEntryLease { path, lock })
    }

    pub fn remove(&self, cache_id: &str) -> Result<(), CacheError> {
        let path = self.entry_path(cache_id)?;
        let _gc_lock = self.acquire_gc_lock()?;
        if !path.exists() {
            return Err(CacheError::NotFound(cache_id.to_owned()));
        }
        ensure_safe_directory(&path)?;
        if remove_committed_entry(&self.root, &path)? {
            Ok(())
        } else {
            Err(CacheError::Busy(path))
        }
    }

    pub fn gc(&self, now: SystemTime) -> Result<GcReport, CacheError> {
        let lock = self.acquire_gc_lock()?;
        let mut report = GcReport::default();
        self.cleanup_ephemeral_locked(now, &mut report)?;
        self.enforce_quota_locked(now, 0, &mut report)?;
        drop(lock);
        Ok(report)
    }

    pub(super) fn staging_root(&self) -> PathBuf {
        self.root.join(STAGING_DIR)
    }

    pub(super) fn incomplete_root(&self) -> PathBuf {
        self.root.join(INCOMPLETE_DIR)
    }

    pub(super) fn acquire_gc_lock(&self) -> Result<GcLock, CacheError> {
        let path = self.root.join(GC_LOCK);
        let file = open_private_lock(&path)?;
        FileExt::lock_exclusive(&file)
            .map_err(|source| io_error("acquire cache GC lock", &path, source))?;
        Ok(GcLock { file })
    }

    pub(super) fn available_id_locked(&self, preferred: &str) -> Result<String, CacheError> {
        if !self.root.join(preferred).exists() {
            return Ok(preferred.to_owned());
        }
        for _ in 0..16 {
            let candidate = ulid::Ulid::new().to_string();
            if !self.root.join(&candidate).exists() {
                return Ok(candidate);
            }
        }
        Err(CacheError::Conflict(preferred.to_owned()))
    }

    pub(super) fn reserve_locked(
        &self,
        now: SystemTime,
        reserve: u64,
    ) -> Result<GcReport, CacheError> {
        let mut report = GcReport::default();
        self.cleanup_ephemeral_locked(now, &mut report)?;
        self.enforce_quota_locked(now, reserve, &mut report)?;
        Ok(report)
    }

    fn cleanup_ephemeral_locked(
        &self,
        now: SystemTime,
        report: &mut GcReport,
    ) -> Result<(), CacheError> {
        for parent in [self.staging_root(), self.incomplete_root()] {
            for item in read_directory(&parent)? {
                let metadata = fs::symlink_metadata(&item)
                    .map_err(|source| io_error("inspect ephemeral cache entry", &item, source))?;
                if !is_plain_directory(&metadata) {
                    continue;
                }
                let modified = metadata.modified().unwrap_or(SystemTime::UNIX_EPOCH);
                if now.duration_since(modified).unwrap_or(Duration::ZERO)
                    < self.limits.incomplete_ttl
                {
                    continue;
                }
                if remove_directory_if_unlocked(&parent, &item)? {
                    report.removed_incomplete += 1;
                }
            }
        }
        Ok(())
    }

    fn enforce_quota_locked(
        &self,
        now: SystemTime,
        reserve: u64,
        report: &mut GcReport,
    ) -> Result<(), CacheError> {
        if reserve > self.limits.quota_bytes {
            return Err(CacheError::Quota {
                required: reserve,
                limit: self.limits.quota_bytes,
            });
        }
        let mut entries = self.collect_entries()?;
        let mut current = entries.iter().try_fold(0_u64, |total, entry| {
            total
                .checked_add(entry.bytes)
                .ok_or_else(|| CacheError::Verification("cache byte total overflow".to_owned()))
        })?;

        entries.sort_by(|left, right| {
            left.last_access
                .cmp(&right.last_access)
                .then_with(|| left.id.cmp(&right.id))
        });
        for entry in entries
            .iter()
            .filter(|entry| entry.removable && entry.expires_at <= now)
        {
            if remove_committed_entry(&self.root, &entry.path)? {
                current = current.saturating_sub(entry.bytes);
                report.removed_expired += 1;
                report.freed_bytes = report.freed_bytes.saturating_add(entry.bytes);
            }
        }

        if current.saturating_add(reserve) > self.limits.quota_bytes {
            for entry in entries
                .iter()
                .filter(|entry| entry.removable && entry.expires_at > now)
            {
                if current.saturating_add(reserve) <= self.limits.quota_bytes {
                    break;
                }
                if remove_committed_entry(&self.root, &entry.path)? {
                    current = current.saturating_sub(entry.bytes);
                    report.removed_lru += 1;
                    report.freed_bytes = report.freed_bytes.saturating_add(entry.bytes);
                }
            }
        }
        report.remaining_bytes = current;
        if current.saturating_add(reserve) > self.limits.quota_bytes {
            return Err(CacheError::Quota {
                required: current.saturating_add(reserve),
                limit: self.limits.quota_bytes,
            });
        }
        Ok(())
    }

    fn collect_entries(&self) -> Result<Vec<EntryInfo>, CacheError> {
        let mut entries = Vec::new();
        for path in read_directory(&self.root)? {
            let Some(id) = path.file_name().and_then(|value| value.to_str()) else {
                continue;
            };
            if validate_cache_id(id).is_err() {
                continue;
            }
            if ensure_safe_directory(&path).is_err() {
                continue;
            }
            let bytes = directory_size_no_links(&path)?;
            let metadata_path = path.join("metadata.yaml");
            let metadata = read_metadata(&metadata_path).ok();
            let removable = metadata
                .as_ref()
                .is_some_and(|metadata| metadata.cache_id == id);
            entries.push(EntryInfo {
                id: id.to_owned(),
                path,
                bytes,
                last_access: metadata
                    .as_ref()
                    .map_or(SystemTime::UNIX_EPOCH, |metadata| metadata.last_access),
                expires_at: metadata
                    .as_ref()
                    .map_or(SystemTime::UNIX_EPOCH, |metadata| metadata.expires_at),
                removable,
            });
        }
        Ok(entries)
    }
}

#[derive(Debug)]
pub struct CacheEntryLease {
    path: PathBuf,
    lock: File,
}

impl CacheEntryLease {
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn source_path(&self, format: SourceFormat) -> PathBuf {
        self.path.join(format.file_name())
    }

    #[must_use]
    pub fn index_path(&self) -> PathBuf {
        self.path.join("index.json")
    }

    #[must_use]
    pub fn metadata_path(&self) -> PathBuf {
        self.path.join("metadata.yaml")
    }
}

impl Drop for CacheEntryLease {
    fn drop(&mut self) {
        let _ = FileExt::unlock(&self.lock);
    }
}

pub(super) struct GcLock {
    file: File,
}

impl Drop for GcLock {
    fn drop(&mut self) {
        let _ = FileExt::unlock(&self.file);
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct GcReport {
    pub removed_incomplete: u64,
    pub removed_expired: u64,
    pub removed_lru: u64,
    pub freed_bytes: u64,
    pub remaining_bytes: u64,
}

struct EntryInfo {
    id: String,
    path: PathBuf,
    bytes: u64,
    last_access: SystemTime,
    expires_at: SystemTime,
    removable: bool,
}

struct MetadataTimes {
    cache_id: String,
    last_access: SystemTime,
    expires_at: SystemTime,
}

pub fn validate_cache_id(cache_id: &str) -> Result<(), CacheError> {
    const ALLOWED: &str = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    if cache_id.len() == 26
        && cache_id
            .bytes()
            .all(|byte| ALLOWED.as_bytes().contains(&byte))
    {
        Ok(())
    } else {
        Err(CacheError::InvalidId(cache_id.to_owned()))
    }
}

pub fn default_cache_root() -> Result<PathBuf, CacheError> {
    env::var_os("LOCALAPPDATA")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .map(|root| root.join("srcq").join("cache").join("v1"))
        .ok_or(CacheError::Environment("LOCALAPPDATA is not set"))
}

fn read_metadata(path: &Path) -> Result<MetadataTimes, CacheError> {
    let bytes = fs::read(path).map_err(|source| io_error("read cache metadata", path, source))?;
    let documents = parse_yaml_documents(&bytes)
        .map_err(|error| CacheError::Serialization(error.to_string()))?;
    if documents.len() != 1 {
        return Err(CacheError::Serialization(
            "metadata must contain exactly one YAML document".to_owned(),
        ));
    }
    let value = &documents[0];
    let text = |field| {
        value
            .get(field)
            .and_then(Value::as_str)
            .ok_or_else(|| CacheError::Serialization(format!("metadata missing {field}")))
    };
    Ok(MetadataTimes {
        cache_id: text("cache_id")?.to_owned(),
        last_access: parse_time(text("last_access_at")?)?,
        expires_at: parse_time(text("expires_at")?)?,
    })
}

fn parse_time(value: &str) -> Result<SystemTime, CacheError> {
    humantime::parse_rfc3339(value).map_err(|error| CacheError::InvalidTime(error.to_string()))
}

fn anticipate_canonical_path(path: &Path) -> Result<PathBuf, CacheError> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        env::current_dir()
            .map_err(|source| io_error("resolve cache root", path, source))?
            .join(path)
    };
    let mut ancestor = absolute.as_path();
    let mut suffix = Vec::<OsString>::new();
    while !ancestor.exists() {
        let name = ancestor
            .file_name()
            .ok_or_else(|| CacheError::UnsafePath(absolute.clone()))?;
        suffix.push(name.to_os_string());
        ancestor = ancestor
            .parent()
            .ok_or_else(|| CacheError::UnsafePath(absolute.clone()))?;
    }
    let mut resolved = ancestor
        .canonicalize()
        .map_err(|source| io_error("canonicalize cache root ancestor", ancestor, source))?;
    for component in suffix.into_iter().rev() {
        resolved.push(component);
    }
    Ok(resolved)
}

fn create_private_directory(path: &Path) -> Result<(), CacheError> {
    fs::create_dir_all(path).map_err(|source| io_error("create cache directory", path, source))?;
    ensure_safe_directory(path)?;
    Ok(())
}

pub(super) fn open_private_lock(path: &Path) -> Result<File, CacheError> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true);
    let file = options
        .open(path)
        .map_err(|source| io_error("open cache lock", path, source))?;
    ensure_safe_file(path)?;
    Ok(file)
}

pub(super) fn ensure_safe_directory(path: &Path) -> Result<(), CacheError> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|source| io_error("inspect cache directory", path, source))?;
    if is_plain_directory(&metadata) {
        Ok(())
    } else {
        Err(CacheError::UnsafePath(path.to_path_buf()))
    }
}

pub(super) fn ensure_safe_file(path: &Path) -> Result<(), CacheError> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|source| io_error("inspect cache file", path, source))?;
    if is_plain_file(&metadata) {
        Ok(())
    } else {
        Err(CacheError::UnsafePath(path.to_path_buf()))
    }
}

fn is_plain_directory(metadata: &fs::Metadata) -> bool {
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return false;
    }
    !is_windows_reparse(metadata)
}

fn is_plain_file(metadata: &fs::Metadata) -> bool {
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return false;
    }
    !is_windows_reparse(metadata)
}

fn is_windows_reparse(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
    metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

fn read_directory(path: &Path) -> Result<Vec<PathBuf>, CacheError> {
    fs::read_dir(path)
        .map_err(|source| io_error("read cache directory", path, source))?
        .map(|entry| {
            entry
                .map(|entry| entry.path())
                .map_err(|source| io_error("read cache directory entry", path, source))
        })
        .collect()
}

fn directory_size_no_links(path: &Path) -> Result<u64, CacheError> {
    ensure_safe_directory(path)?;
    let mut total = 0_u64;
    for child in read_directory(path)? {
        let metadata = fs::symlink_metadata(&child)
            .map_err(|source| io_error("inspect cache entry content", &child, source))?;
        let bytes = if is_plain_directory(&metadata) {
            directory_size_no_links(&child)?
        } else if is_plain_file(&metadata) {
            metadata.len()
        } else {
            return Err(CacheError::UnsafePath(child));
        };
        total = total
            .checked_add(bytes)
            .ok_or_else(|| CacheError::Verification("cache entry size overflow".to_owned()))?;
    }
    Ok(total)
}

fn remove_directory_if_unlocked(parent: &Path, path: &Path) -> Result<bool, CacheError> {
    if path.parent() != Some(parent) {
        return Err(CacheError::UnsafePath(path.to_path_buf()));
    }
    let lock_path = path.join(ACCESS_LOCK);
    if !lock_path.exists() {
        safe_remove_tree(parent, path)?;
        return Ok(true);
    }
    let lock = open_private_lock(&lock_path)?;
    if let Err(error) = FileExt::try_lock_exclusive(&lock) {
        if is_lock_contended(&error) {
            return Ok(false);
        }
        return Err(io_error("lock ephemeral cache entry", &lock_path, error));
    }
    remove_contents_except_lock(path)?;
    let _ = FileExt::unlock(&lock);
    drop(lock);
    fs::remove_file(&lock_path)
        .map_err(|source| io_error("remove cache access lock", &lock_path, source))?;
    fs::remove_dir(path)
        .map_err(|source| io_error("remove cache entry directory", path, source))?;
    Ok(true)
}

fn is_lock_contended(error: &io::Error) -> bool {
    if error.kind() == io::ErrorKind::WouldBlock {
        return true;
    }
    const ERROR_LOCK_VIOLATION: i32 = 33;
    error.raw_os_error() == Some(ERROR_LOCK_VIOLATION)
}

fn remove_committed_entry(root: &Path, path: &Path) -> Result<bool, CacheError> {
    if path.parent() != Some(root) {
        return Err(CacheError::UnsafePath(path.to_path_buf()));
    }
    remove_directory_if_unlocked(root, path)
}

fn remove_contents_except_lock(path: &Path) -> Result<(), CacheError> {
    for child in read_directory(path)? {
        if child.file_name().and_then(|value| value.to_str()) == Some(ACCESS_LOCK) {
            continue;
        }
        let metadata = fs::symlink_metadata(&child)
            .map_err(|source| io_error("inspect cache removal target", &child, source))?;
        if is_plain_file(&metadata) {
            fs::remove_file(&child)
                .map_err(|source| io_error("remove cache file", &child, source))?;
        } else if is_plain_directory(&metadata) {
            safe_remove_tree(path, &child)?;
        } else {
            return Err(CacheError::UnsafePath(child));
        }
    }
    Ok(())
}

fn safe_remove_tree(parent: &Path, path: &Path) -> Result<(), CacheError> {
    if path.parent() != Some(parent) {
        return Err(CacheError::UnsafePath(path.to_path_buf()));
    }
    ensure_safe_directory(path)?;
    for child in read_directory(path)? {
        let metadata = fs::symlink_metadata(&child)
            .map_err(|source| io_error("inspect recursive cache removal", &child, source))?;
        if is_plain_file(&metadata) {
            fs::remove_file(&child)
                .map_err(|source| io_error("remove cache file", &child, source))?;
        } else if is_plain_directory(&metadata) {
            safe_remove_tree(path, &child)?;
        } else {
            return Err(CacheError::UnsafePath(child));
        }
    }
    fs::remove_dir(path).map_err(|source| io_error("remove cache directory", path, source))
}
