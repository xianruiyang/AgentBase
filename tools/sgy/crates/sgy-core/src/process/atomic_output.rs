use std::{
    fs::{self, File},
    io::{self, BufReader, Read, Write},
    path::{Path, PathBuf},
    time::SystemTime,
};

use atomic_write_file::AtomicWriteFile;
use file_id::{get_file_id, FileId};
use sha2::{Digest, Sha256};
use tempfile::NamedTempFile;
use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq)]
enum Fingerprint {
    Missing,
    File {
        id: FileId,
        size: u64,
        modified: Option<SystemTime>,
        sha256: [u8; 32],
    },
}

/// An output path validated and fingerprinted before the engine starts.
#[derive(Clone, Debug)]
pub struct PreparedOutput {
    final_path: PathBuf,
    before: Fingerprint,
}

#[derive(Debug, Error)]
pub enum OutputCommitError {
    #[error("output parent does not exist or cannot be canonicalized: {path}: {source}")]
    Parent {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("output path has no file name: {0}")]
    MissingFileName(PathBuf),
    #[error("output target is not a regular file or is a link/reparse point: {0}")]
    UnsafeTarget(PathBuf),
    #[error("cannot fingerprint output target {path}: {source}")]
    Fingerprint {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("output target changed after engine start: {0}")]
    Changed(PathBuf),
    #[error("cannot stage or atomically commit output {path}: {source}")]
    Commit {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
}

impl OutputCommitError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        127
    }
}

impl PreparedOutput {
    /// Resolves the parent and records file identity, size, mtime, and SHA-256.
    pub fn prepare(path: impl AsRef<Path>) -> Result<Self, OutputCommitError> {
        let requested = path.as_ref();
        let name = requested
            .file_name()
            .ok_or_else(|| OutputCommitError::MissingFileName(requested.to_path_buf()))?;
        let parent = requested.parent().unwrap_or_else(|| Path::new("."));
        let parent = parent
            .canonicalize()
            .map_err(|source| OutputCommitError::Parent {
                path: parent.to_path_buf(),
                source,
            })?;
        let final_path = parent.join(name);
        if !is_safe_target(&final_path).map_err(|source| OutputCommitError::Fingerprint {
            path: final_path.clone(),
            source,
        })? {
            return Err(OutputCommitError::UnsafeTarget(final_path));
        }
        let before = fingerprint(&final_path).map_err(|source| OutputCommitError::Fingerprint {
            path: final_path.clone(),
            source,
        })?;
        Ok(Self { final_path, before })
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.final_path
    }

    /// Rechecks the pre-run fingerprint, stages in the final directory, fsyncs, and atomically
    /// replaces the target. No delete-then-rename fallback is used.
    pub fn commit_from_reader(&self, mut source: impl Read) -> Result<u64, OutputCommitError> {
        let after =
            fingerprint(&self.final_path).map_err(|source| OutputCommitError::Fingerprint {
                path: self.final_path.clone(),
                source,
            })?;
        if after != self.before {
            return Err(OutputCommitError::Changed(self.final_path.clone()));
        }

        if self.before == Fingerprint::Missing {
            return self.commit_new(source);
        }

        let mut staged = AtomicWriteFile::open(&self.final_path).map_err(|source| {
            OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            }
        })?;
        let bytes =
            io::copy(&mut source, &mut staged).map_err(|source| OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            })?;
        staged.flush().map_err(|source| OutputCommitError::Commit {
            path: self.final_path.clone(),
            source,
        })?;
        staged
            .sync_all()
            .map_err(|source| OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            })?;
        let before_commit =
            fingerprint(&self.final_path).map_err(|source| OutputCommitError::Fingerprint {
                path: self.final_path.clone(),
                source,
            })?;
        if before_commit != self.before {
            return Err(OutputCommitError::Changed(self.final_path.clone()));
        }
        staged
            .commit()
            .map_err(|source| OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            })?;
        Ok(bytes)
    }

    fn commit_new(&self, mut source: impl Read) -> Result<u64, OutputCommitError> {
        let parent = self
            .final_path
            .parent()
            .ok_or_else(|| OutputCommitError::MissingFileName(self.final_path.clone()))?;
        let mut staged =
            NamedTempFile::new_in(parent).map_err(|source| OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            })?;
        let bytes =
            io::copy(&mut source, &mut staged).map_err(|source| OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            })?;
        staged.flush().map_err(|source| OutputCommitError::Commit {
            path: self.final_path.clone(),
            source,
        })?;
        staged
            .as_file()
            .sync_all()
            .map_err(|source| OutputCommitError::Commit {
                path: self.final_path.clone(),
                source,
            })?;
        if fingerprint(&self.final_path).map_err(|source| OutputCommitError::Fingerprint {
            path: self.final_path.clone(),
            source,
        })? != Fingerprint::Missing
        {
            return Err(OutputCommitError::Changed(self.final_path.clone()));
        }
        staged
            .persist_noclobber(&self.final_path)
            .map_err(|error| {
                if error.error.kind() == io::ErrorKind::AlreadyExists {
                    OutputCommitError::Changed(self.final_path.clone())
                } else {
                    OutputCommitError::Commit {
                        path: self.final_path.clone(),
                        source: error.error,
                    }
                }
            })?;
        Ok(bytes)
    }

    pub fn commit_from_path(&self, source: impl AsRef<Path>) -> Result<u64, OutputCommitError> {
        let file = File::open(source.as_ref()).map_err(|source| OutputCommitError::Commit {
            path: self.final_path.clone(),
            source,
        })?;
        self.commit_from_reader(BufReader::new(file))
    }
}

fn is_safe_target(path: &Path) -> io::Result<bool> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(true),
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Ok(false);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Ok(false);
        }
    }
    Ok(true)
}

fn fingerprint(path: &Path) -> io::Result<Fingerprint> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Fingerprint::Missing),
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "target is not a regular file",
        ));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "target is a reparse point",
            ));
        }
    }

    let mut reader = BufReader::new(File::open(path)?);
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    let sha256: [u8; 32] = hasher.finalize().into();
    Ok(Fingerprint::File {
        id: get_file_id(path)?,
        size: metadata.len(),
        modified: metadata.modified().ok(),
        sha256,
    })
}

#[cfg(test)]
mod tests {
    use std::{fs, io::Cursor};

    use tempfile::tempdir;

    use super::{OutputCommitError, PreparedOutput};

    #[test]
    fn atomically_creates_and_replaces_output() {
        let directory = tempdir().expect("temp directory");
        let path = directory.path().join("result.yaml");
        let prepared = PreparedOutput::prepare(&path).expect("prepare missing output");
        assert_eq!(
            prepared
                .commit_from_reader(Cursor::new(b"first"))
                .expect("commit new output"),
            5
        );
        assert_eq!(fs::read(&path).expect("read committed output"), b"first");

        let prepared = PreparedOutput::prepare(&path).expect("prepare existing output");
        prepared
            .commit_from_reader(Cursor::new(b"second"))
            .expect("replace output");
        assert_eq!(fs::read(&path).expect("read replaced output"), b"second");
    }

    #[test]
    fn refuses_to_overwrite_concurrent_change() {
        let directory = tempdir().expect("temp directory");
        let path = directory.path().join("result.yaml");
        fs::write(&path, b"before").expect("seed output");
        let prepared = PreparedOutput::prepare(&path).expect("prepare output");
        fs::write(&path, b"concurrent").expect("mutate output");
        let error = prepared
            .commit_from_reader(Cursor::new(b"wrapper"))
            .expect_err("concurrent change must fail");
        assert!(matches!(error, OutputCommitError::Changed(_)));
        assert_eq!(fs::read(&path).expect("read target"), b"concurrent");
    }

    #[test]
    fn refuses_to_overwrite_file_that_appeared_after_prepare() {
        let directory = tempdir().expect("temp directory");
        let path = directory.path().join("result.yaml");
        let prepared = PreparedOutput::prepare(&path).expect("prepare missing output");
        fs::write(&path, b"other writer").expect("create concurrent output");
        let error = prepared
            .commit_from_reader(Cursor::new(b"wrapper"))
            .expect_err("new concurrent output must fail");
        assert!(matches!(error, OutputCommitError::Changed(_)));
        assert_eq!(fs::read(&path).expect("read target"), b"other writer");
    }

    #[test]
    fn rejects_directory_as_output_target() {
        let directory = tempdir().expect("temp directory");
        let error = PreparedOutput::prepare(directory.path())
            .expect_err("directory target must be rejected");
        assert!(matches!(error, OutputCommitError::UnsafeTarget(_)));
    }
}
