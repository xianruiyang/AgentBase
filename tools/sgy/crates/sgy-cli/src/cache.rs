use std::{io::Write, time::SystemTime};

use serde_json::{Map, Value};
use sgy_core::{
    cache::{CacheError, CacheQuery, CacheStore, SourceFormat, VerifiedCache},
    codec::{write_yaml_document, CodecError},
};
use thiserror::Error;

use crate::CacheCommand;

#[derive(Debug, Error)]
pub enum CacheCommandError {
    #[error(transparent)]
    Cache(#[from] CacheError),
    #[error(transparent)]
    Codec(#[from] CodecError),
    #[error("cannot flush cache YAML output: {0}")]
    Output(#[source] std::io::Error),
}

impl CacheCommandError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Cache(error) => error.wrapper_exit_code(),
            Self::Codec(CodecError::OutputIo(_)) => 127,
            Self::Codec(error) => error.wrapper_exit_code(),
            Self::Output(_) => 127,
        }
    }
}

pub fn execute(
    store: &CacheStore,
    command: &CacheCommand,
    now: SystemTime,
    output: &mut impl Write,
) -> Result<(), CacheCommandError> {
    match command {
        CacheCommand::Get {
            cache_id,
            result,
            field,
        } => {
            let cache = store.open_verified(cache_id, now)?;
            write_get(&cache, *result, field.as_deref(), output)?;
        }
        CacheCommand::Query {
            cache_id,
            file,
            rule_id,
            offset,
            limit,
        } => {
            let cache = store.open_verified(cache_id, now)?;
            let result = cache.query(&CacheQuery {
                file: file.clone(),
                rule_id: rule_id.clone(),
                offset: *offset,
                limit: *limit,
            })?;
            let mut document = Map::new();
            document.insert(
                "schema".to_owned(),
                Value::String("sgy.cache-query/v1".to_owned()),
            );
            document.insert("cache_id".to_owned(), Value::String(cache_id.clone()));
            document.insert("total".to_owned(), Value::from(result.total));
            document.insert("shown".to_owned(), Value::from(result.shown));
            document.insert("offset".to_owned(), Value::from(*offset as u64));
            document.insert("limit".to_owned(), Value::from(*limit as u64));
            document.insert("complete".to_owned(), Value::Bool(result.complete));
            let mut filters = Map::new();
            if let Some(file) = file {
                filters.insert("file".to_owned(), Value::String(file.clone()));
            }
            if let Some(rule_id) = rule_id {
                filters.insert("ruleId".to_owned(), Value::String(rule_id.clone()));
            }
            if !filters.is_empty() {
                document.insert("filters".to_owned(), Value::Object(filters));
            }
            document.insert(
                "results".to_owned(),
                Value::Array(
                    result
                        .results
                        .into_iter()
                        .map(|result| {
                            let mut value = Map::new();
                            value.insert("id".to_owned(), Value::from(result.id));
                            value.insert("value".to_owned(), result.value);
                            Value::Object(value)
                        })
                        .collect(),
                ),
            );
            write_yaml_document(&Value::Object(document), output, false)?;
        }
        CacheCommand::Info { cache_id } => {
            let cache = store.open_verified(cache_id, now)?;
            write_yaml_document(cache.metadata(), output, false)?;
        }
        CacheCommand::Remove { cache_id } => {
            store.remove(cache_id)?;
            let mut document = Map::new();
            document.insert(
                "schema".to_owned(),
                Value::String("sgy.cache-remove/v1".to_owned()),
            );
            document.insert("cache_id".to_owned(), Value::String(cache_id.clone()));
            document.insert("removed".to_owned(), Value::Bool(true));
            write_yaml_document(&Value::Object(document), output, false)?;
        }
        CacheCommand::Gc => {
            let report = store.gc(now)?;
            let mut document = Map::new();
            document.insert(
                "schema".to_owned(),
                Value::String("sgy.cache-gc/v1".to_owned()),
            );
            document.insert(
                "removed_incomplete".to_owned(),
                Value::from(report.removed_incomplete),
            );
            document.insert(
                "removed_expired".to_owned(),
                Value::from(report.removed_expired),
            );
            document.insert("removed_lru".to_owned(), Value::from(report.removed_lru));
            document.insert("freed_bytes".to_owned(), Value::from(report.freed_bytes));
            document.insert(
                "remaining_bytes".to_owned(),
                Value::from(report.remaining_bytes),
            );
            write_yaml_document(&Value::Object(document), output, false)?;
        }
    }
    output.flush().map_err(CacheCommandError::Output)
}

fn write_get(
    cache: &VerifiedCache,
    result: Option<u64>,
    field: Option<&str>,
    output: &mut impl Write,
) -> Result<(), CacheCommandError> {
    if let Some(result) = result {
        let value = match field {
            Some(pointer) => cache.field(result, pointer)?,
            None => cache.result(result)?,
        };
        write_yaml_document(&value, output, false)?;
        return Ok(());
    }
    if field.is_some() {
        return Err(CacheError::InvalidSelection("--field requires --result".to_owned()).into());
    }
    if cache.source_format() == SourceFormat::JsonLines {
        for record in cache.iter_records()? {
            let record = record?;
            write_yaml_document(&cache.result(record.id)?, output, true)?;
        }
        return Ok(());
    }
    let document = cache.source_document().ok_or_else(|| {
        CacheError::Verification("non-JSONL cache has no source document".to_owned())
    })?;
    write_yaml_document(document, output, false)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{
        ffi::OsString,
        io::{BufReader, Cursor},
        time::{Duration, SystemTime},
    };

    use serde_json::Value;
    use sgy_core::{
        cache::{CacheAudit, CacheLimits, CacheMode, CacheProcess, CacheStore, SourceFormat},
        codec::{parse_yaml_documents, JsonLines},
        invocation::Profile,
    };
    use tempfile::tempdir;

    use super::execute;
    use crate::CacheCommand;

    fn committed_store() -> (tempfile::TempDir, CacheStore, String) {
        let directory = tempdir().expect("temp directory");
        let workspace = directory.path().join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let store = CacheStore::open(
            directory.path().join("user-cache"),
            Some(&workspace),
            CacheLimits::default(),
        )
        .expect("cache store");
        let argv = vec![OsString::from("run")];
        let audit = CacheAudit::from_argv(
            "ast-grep",
            "0.42.0",
            &workspace,
            &argv,
            &argv,
            Vec::new(),
            Profile::TokenSafe,
            CacheMode::On,
        );
        let raw = concat!(
            "{\"file\":\"src/a.ts\",\"ruleId\":\"r\",\"text\":\"alpha\"}\n",
            "{\"file\":\"src/b.ts\",\"ruleId\":\"s\",\"text\":\"beta\"}\n"
        )
        .as_bytes();
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_000);
        let mut staging = store
            .begin(SourceFormat::JsonLines, audit, now)
            .expect("staging");
        staging
            .stage_source(Cursor::new(raw))
            .expect("stage source");
        for record in JsonLines::new(BufReader::new(Cursor::new(raw))) {
            staging
                .add_source_record(&record.expect("record"))
                .expect("index");
        }
        let committed = staging
            .commit(CacheProcess::completed(0), now)
            .expect("commit");
        (directory, store, committed.cache_id)
    }

    fn run(store: &CacheStore, command: CacheCommand) -> Vec<Value> {
        let mut output = Vec::new();
        execute(
            store,
            &command,
            SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_100),
            &mut output,
        )
        .expect("cache command");
        parse_yaml_documents(&output).expect("safe YAML")
    }

    #[test]
    fn get_query_info_remove_and_gc_emit_safe_yaml() {
        let (_directory, store, cache_id) = committed_store();

        let field = run(
            &store,
            CacheCommand::Get {
                cache_id: cache_id.clone(),
                result: Some(0),
                field: Some("/text".to_owned()),
            },
        );
        assert_eq!(field, vec![Value::String("alpha".to_owned())]);

        let all = run(
            &store,
            CacheCommand::Get {
                cache_id: cache_id.clone(),
                result: None,
                field: None,
            },
        );
        assert_eq!(all.len(), 2);
        assert_eq!(all[1]["text"], "beta");

        let query = run(
            &store,
            CacheCommand::Query {
                cache_id: cache_id.clone(),
                file: Some("src/b.ts".to_owned()),
                rule_id: None,
                offset: 0,
                limit: 40,
            },
        );
        assert_eq!(query[0]["schema"], "sgy.cache-query/v1");
        assert_eq!(query[0]["total"], 1);
        assert_eq!(query[0]["results"][0]["id"], 1);

        let info = run(
            &store,
            CacheCommand::Info {
                cache_id: cache_id.clone(),
            },
        );
        assert_eq!(info[0]["schema"], "sgy.cache-metadata/v1");
        assert_eq!(info[0]["cache_id"], cache_id);

        let removed = run(
            &store,
            CacheCommand::Remove {
                cache_id: cache_id.clone(),
            },
        );
        assert_eq!(removed[0]["removed"], true);
        assert!(!store.entry_path(&cache_id).expect("path").exists());

        let gc = run(&store, CacheCommand::Gc);
        assert_eq!(gc[0]["schema"], "sgy.cache-gc/v1");
        assert_eq!(gc[0]["remaining_bytes"], 0);
    }
}
