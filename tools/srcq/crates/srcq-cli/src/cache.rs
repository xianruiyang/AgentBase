use std::{io::Write, time::SystemTime};

use serde_json::{Map, Value};
use srcq_core::{
    cache::{CacheError, CacheQuery, CacheStore, CachedResult, SourceFormat, VerifiedCache},
    codec::{write_yaml_document, CodecError},
    invocation::OutputFormat,
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
            max_text_chars,
            output: format,
        } => {
            let cache = store.open_verified(cache_id, now)?;
            let result = cache.query(&CacheQuery {
                file: file.clone(),
                rule_id: rule_id.clone(),
                offset: *offset,
                limit: *limit,
            })?;
            if *format == OutputFormat::Model {
                write_query_model(
                    cache_id,
                    *offset,
                    *max_text_chars,
                    result.total,
                    result.shown,
                    &result.results,
                    output,
                )?;
                output.flush().map_err(CacheCommandError::Output)?;
                return Ok(());
            }
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

fn write_query_model(
    cache_id: &str,
    offset: usize,
    max_text_chars: usize,
    total: u64,
    shown: u64,
    results: &[CachedResult],
    output: &mut impl Write,
) -> Result<(), CacheCommandError> {
    let mut lines = Vec::new();
    let mut cut = 0_u64;
    for result in results {
        let mapping = result.value.as_object().ok_or_else(|| {
            CacheError::InvalidSelection(
                "cache query result has no model projection; retry with --output machine"
                    .to_owned(),
            )
        })?;
        let file = mapping.get("file").and_then(Value::as_str).ok_or_else(|| {
            CacheError::InvalidSelection(
                "cache query result has no file; retry with --output machine".to_owned(),
            )
        })?;
        let range = mapping
            .get("range")
            .and_then(Value::as_object)
            .ok_or_else(|| {
                CacheError::InvalidSelection(
                    "cache query result has no range; retry with --output machine".to_owned(),
                )
            })?;
        let position = |name: &str| -> Option<(u64, u64)> {
            let point = range.get(name)?.as_object()?;
            Some((point.get("line")?.as_u64()?, point.get("column")?.as_u64()?))
        };
        let (start_line, start_column) = position("start").ok_or_else(|| {
            CacheError::InvalidSelection(
                "cache query result has no valid range.start; retry with --output machine"
                    .to_owned(),
            )
        })?;
        let (end_line, end_column) = position("end").ok_or_else(|| {
            CacheError::InvalidSelection(
                "cache query result has no valid range.end; retry with --output machine".to_owned(),
            )
        })?;
        lines.push(format!(
            "#{} {}:{start_line}:{start_column}-{end_line}:{end_column}",
            result.id,
            file.replace('\\', "/")
        ));
        if let Some(text) = mapping.get("text").and_then(Value::as_str) {
            let mut chars = text.chars();
            let visible = chars.by_ref().take(max_text_chars).collect::<String>();
            if chars.next().is_some() {
                lines.push(format!("{visible}…"));
                cut = cut.saturating_add(1);
            } else {
                lines.push(text.trim_end_matches(['\r', '\n']).to_owned());
            }
        }
        for field in ["ruleId", "severity", "message", "replacement"] {
            if let Some(value) = mapping.get(field).and_then(Value::as_str) {
                lines.push(format!("{field}={value}"));
            }
        }
    }
    let omitted = total.saturating_sub(
        u64::try_from(offset)
            .unwrap_or(u64::MAX)
            .saturating_add(shown),
    );
    if omitted > 0 {
        let next = u64::try_from(offset)
            .unwrap_or(u64::MAX)
            .saturating_add(shown);
        lines.push(format!(
            "@more shown={shown} omitted={omitted} cache={cache_id} after={next}"
        ));
    }
    if cut > 0 {
        lines.push(format!("@cut text={cut}"));
    }
    if !lines.is_empty() {
        output
            .write_all(lines.join("\n").as_bytes())
            .and_then(|()| output.write_all(b"\n"))
            .map_err(CacheCommandError::Output)?;
    }
    Ok(())
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
    use srcq_core::{
        cache::{CacheAudit, CacheLimits, CacheMode, CacheProcess, CacheStore, SourceFormat},
        codec::{parse_yaml_documents, JsonLines},
        invocation::{OutputFormat, Profile},
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
            "{\"file\":\"src/a.ts\",\"range\":{\"start\":{\"line\":0,\"column\":0},\"end\":{\"line\":0,\"column\":5}},\"ruleId\":\"r\",\"text\":\"alpha\"}\n",
            "{\"file\":\"src/b.ts\",\"range\":{\"start\":{\"line\":1,\"column\":0},\"end\":{\"line\":1,\"column\":4}},\"ruleId\":\"s\",\"text\":\"beta\"}\n"
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
                max_text_chars: 240,
                output: OutputFormat::Machine,
            },
        );
        assert_eq!(query[0]["schema"], "sgy.cache-query/v1");
        assert_eq!(query[0]["total"], 1);
        assert_eq!(query[0]["results"][0]["id"], 1);

        let mut model = Vec::new();
        execute(
            &store,
            &CacheCommand::Query {
                cache_id: cache_id.clone(),
                file: Some("src/b.ts".to_owned()),
                rule_id: None,
                offset: 0,
                limit: 40,
                max_text_chars: 3,
                output: OutputFormat::Model,
            },
            SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_100),
            &mut model,
        )
        .expect("model cache query");
        assert_eq!(
            String::from_utf8(model).expect("UTF-8 model query"),
            "#1 src/b.ts:1:0-1:4\nbet…\nruleId=s\n@cut text=1\n"
        );

        let mut final_page = Vec::new();
        execute(
            &store,
            &CacheCommand::Query {
                cache_id: cache_id.clone(),
                file: None,
                rule_id: None,
                offset: 1,
                limit: 1,
                max_text_chars: 240,
                output: OutputFormat::Model,
            },
            SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_100),
            &mut final_page,
        )
        .expect("final model cache page");
        assert!(!String::from_utf8(final_page)
            .expect("UTF-8 final page")
            .contains("@more"));

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
