use std::{
    fs::File,
    io::{self, BufReader, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    time::SystemTime,
};

use serde_json::{json, Value};
use srcq_core::{
    cache::{default_cache_root, CacheError, CacheLimits, CacheStore, VerifiedCache},
    processors::{
        jsonl_to_yaml, process_yaml, visit_yaml_documents, write_jsonl_value, yaml_to_jsonl,
        CollectionBuilder, CollectionOperation, CollectionSource, ConflictPolicy, Operation,
        ProcessError, ProcessLimits, Processor,
    },
};
use thiserror::Error;

use crate::{ProcessAction, ProcessCommand, ProcessInput};

mod location_projection;

#[derive(Debug, Error)]
pub enum ProcessCommandError {
    #[error(transparent)]
    Process(#[from] ProcessError),
    #[error(transparent)]
    Cache(#[from] CacheError),
    #[error("cannot commit process output: {0}")]
    Output(#[source] io::Error),
}

impl ProcessCommandError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Process(error) => error.wrapper_exit_code(),
            Self::Cache(error) => error.wrapper_exit_code(),
            Self::Output(_) => 127,
        }
    }
}

pub fn execute(
    command: &ProcessCommand,
    launch_cwd: &Path,
    output: &mut impl Write,
) -> Result<(), ProcessCommandError> {
    let mut staged = tempfile::tempfile().map_err(ProcessCommandError::Output)?;
    execute_staged(command, launch_cwd, &mut staged)?;
    staged
        .seek(SeekFrom::Start(0))
        .map_err(ProcessCommandError::Output)?;
    io::copy(&mut staged, output).map_err(ProcessCommandError::Output)?;
    output.flush().map_err(ProcessCommandError::Output)
}

fn execute_staged(
    command: &ProcessCommand,
    launch_cwd: &Path,
    output: &mut impl Write,
) -> Result<(), ProcessCommandError> {
    let limits = ProcessLimits::default();
    match &command.action {
        ProcessAction::Validate
        | ProcessAction::Select { .. }
        | ProcessAction::Filter { .. }
        | ProcessAction::Count
        | ProcessAction::Group { .. } => execute_basic(
            &command.input,
            launch_cwd,
            output,
            basic_operation(&command.action)?,
            limits,
        ),
        ProcessAction::Sort { by, descending } => execute_collection(
            &command.input,
            launch_cwd,
            output,
            CollectionOperation::sort(by, *descending)?,
            limits,
        ),
        ProcessAction::Dedupe { on_conflict } => execute_collection(
            &command.input,
            launch_cwd,
            output,
            CollectionOperation::dedupe(conflict_policy(on_conflict)?),
            limits,
        ),
        ProcessAction::Merge {
            sources,
            on_conflict,
        } => execute_merge(
            sources,
            conflict_policy(on_conflict)?,
            launch_cwd,
            output,
            limits,
        ),
        ProcessAction::Containing {
            file,
            line,
            column,
            include_text,
        } => location_projection::execute_containing(
            &command.input,
            file,
            *line,
            *column,
            *include_text,
            launch_cwd,
            output,
        ),
        ProcessAction::GroupLocations {
            file,
            offset,
            limit,
        } => location_projection::execute_grouped_locations(
            &command.input,
            file.as_deref(),
            *offset,
            *limit,
            launch_cwd,
            output,
        ),
        ProcessAction::ToJsonl => execute_to_jsonl(&command.input, launch_cwd, output, limits),
        ProcessAction::FromJsonl => execute_from_jsonl(&command.input, output, limits),
    }
}

fn execute_basic(
    input: &ProcessInput,
    launch_cwd: &Path,
    output: &mut impl Write,
    operation: Operation,
    limits: ProcessLimits,
) -> Result<(), ProcessCommandError> {
    match input {
        ProcessInput::Stdin => {
            let stdin = io::stdin();
            process_yaml(stdin.lock(), output, operation, limits)?;
        }
        ProcessInput::File(path) if path == Path::new("-") => {
            let stdin = io::stdin();
            process_yaml(stdin.lock(), output, operation, limits)?;
        }
        ProcessInput::File(path) => {
            let file = File::open(path).map_err(ProcessError::Input)?;
            process_yaml(BufReader::new(file), output, operation, limits)?;
        }
        ProcessInput::Cache(cache_id) => {
            let cache = open_cache(cache_id, launch_cwd)?;
            let mut processor = Processor::new(operation, limits);
            for record in cache.iter_records()? {
                let record = record?;
                processor.push(cache.result(record.id)?, output)?;
            }
            processor.finish(output)?;
        }
    }
    Ok(())
}

fn execute_collection(
    input: &ProcessInput,
    launch_cwd: &Path,
    output: &mut impl Write,
    operation: CollectionOperation,
    limits: ProcessLimits,
) -> Result<(), ProcessCommandError> {
    let mut builder = CollectionBuilder::new(operation, limits)?;
    feed_input(&mut builder, input, launch_cwd, limits)?;
    builder.finish(output)?;
    Ok(())
}

fn execute_merge(
    specs: &[String],
    conflicts: ConflictPolicy,
    launch_cwd: &Path,
    output: &mut impl Write,
    limits: ProcessLimits,
) -> Result<(), ProcessCommandError> {
    if specs.len() < 2 {
        return Err(ProcessError::InvalidArgument(
            "merge requires at least two --source values".to_owned(),
        )
        .into());
    }
    let mut builder = CollectionBuilder::new(CollectionOperation::merge(conflicts), limits)?;
    for spec in specs {
        let input = parse_merge_source(spec)?;
        if matches!(&input, ProcessInput::File(path) if path == Path::new("-")) {
            return Err(ProcessError::InvalidArgument(
                "merge does not accept stdin sources; use explicit file= or cache=".to_owned(),
            )
            .into());
        }
        feed_input(&mut builder, &input, launch_cwd, limits)?;
    }
    builder.finish(output)?;
    Ok(())
}

fn feed_input(
    builder: &mut CollectionBuilder,
    input: &ProcessInput,
    launch_cwd: &Path,
    limits: ProcessLimits,
) -> Result<(), ProcessCommandError> {
    match input {
        ProcessInput::Stdin => {
            let source = CollectionSource::new("stdin", "stdin", json!({"kind": "stdin"}))?;
            let id = source.id.clone();
            builder.add_source(source)?;
            let stdin = io::stdin();
            visit_yaml_documents(stdin.lock(), limits, |value| {
                builder.push_document(&id, value)
            })?;
        }
        ProcessInput::File(path) if path == Path::new("-") => {
            return feed_input(builder, &ProcessInput::Stdin, launch_cwd, limits);
        }
        ProcessInput::File(path) => {
            let canonical = std::fs::canonicalize(path).map_err(ProcessError::Input)?;
            let display = path_text(&canonical);
            let source = CollectionSource::new(
                format!("file:{display}"),
                format!("file:{display}"),
                json!({"kind": "file", "path": display}),
            )?;
            let id = source.id.clone();
            builder.add_source(source)?;
            let file = File::open(&canonical).map_err(ProcessError::Input)?;
            visit_yaml_documents(BufReader::new(file), limits, |value| {
                builder.push_document(&id, value)
            })?;
        }
        ProcessInput::Cache(cache_id) => {
            let cache = open_cache(cache_id, launch_cwd)?;
            let source = cache_source(cache_id, &cache)?;
            let id = source.id.clone();
            builder.add_source(source)?;
            for record in cache.iter_records()? {
                let record = record?;
                builder.push_document(&id, cache.result(record.id)?)?;
            }
        }
    }
    Ok(())
}

fn execute_to_jsonl(
    input: &ProcessInput,
    launch_cwd: &Path,
    output: &mut impl Write,
    limits: ProcessLimits,
) -> Result<(), ProcessCommandError> {
    match input {
        ProcessInput::Stdin => {
            let stdin = io::stdin();
            yaml_to_jsonl(stdin.lock(), output, limits)?;
        }
        ProcessInput::File(path) if path == Path::new("-") => {
            let stdin = io::stdin();
            yaml_to_jsonl(stdin.lock(), output, limits)?;
        }
        ProcessInput::File(path) => {
            let file = File::open(path).map_err(ProcessError::Input)?;
            yaml_to_jsonl(BufReader::new(file), output, limits)?;
        }
        ProcessInput::Cache(cache_id) => {
            let cache = open_cache(cache_id, launch_cwd)?;
            for record in cache.iter_records()? {
                let record = record?;
                write_jsonl_value(&cache.result(record.id)?, output)?;
            }
            output.flush().map_err(ProcessCommandError::Output)?;
        }
    }
    Ok(())
}

fn execute_from_jsonl(
    input: &ProcessInput,
    output: &mut impl Write,
    limits: ProcessLimits,
) -> Result<(), ProcessCommandError> {
    match input {
        ProcessInput::Stdin => {
            let stdin = io::stdin();
            jsonl_to_yaml(stdin.lock(), output, limits)?;
        }
        ProcessInput::File(path) if path == Path::new("-") => {
            let stdin = io::stdin();
            jsonl_to_yaml(stdin.lock(), output, limits)?;
        }
        ProcessInput::File(path) => {
            let file = File::open(path).map_err(ProcessError::Input)?;
            jsonl_to_yaml(BufReader::new(file), output, limits)?;
        }
        ProcessInput::Cache(_) => {
            return Err(ProcessError::InvalidArgument(
                "from-jsonl accepts stdin or --input, not --cache-id".to_owned(),
            )
            .into());
        }
    }
    Ok(())
}

fn open_cache(cache_id: &str, launch_cwd: &Path) -> Result<VerifiedCache, ProcessCommandError> {
    let root = default_cache_root()?;
    let store = CacheStore::open(root, Some(launch_cwd), CacheLimits::default())?;
    Ok(store.open_verified(cache_id, SystemTime::now())?)
}

fn cache_source(cache_id: &str, cache: &VerifiedCache) -> Result<CollectionSource, ProcessError> {
    let metadata = cache.metadata();
    let cwd = metadata
        .get("cwd")
        .and_then(Value::as_str)
        .ok_or_else(|| ProcessError::InvalidArgument("cache metadata cwd is missing".to_owned()))?;
    let engine = metadata.get("engine").cloned().ok_or_else(|| {
        ProcessError::InvalidArgument("cache metadata engine is missing".to_owned())
    })?;
    let invocation = metadata.get("invocation").cloned().ok_or_else(|| {
        ProcessError::InvalidArgument("cache metadata invocation is missing".to_owned())
    })?;
    CollectionSource::new(
        format!("cache:{cache_id}"),
        format!("cwd:{cwd}"),
        json!({
            "kind": "cache",
            "cache_id": cache_id,
            "cwd": cwd,
            "engine": engine,
            "invocation": invocation,
        }),
    )
}

fn parse_merge_source(spec: &str) -> Result<ProcessInput, ProcessCommandError> {
    if let Some(path) = spec.strip_prefix("file=") {
        if path.is_empty() {
            return Err(ProcessError::InvalidArgument(
                "merge file source path must not be empty".to_owned(),
            )
            .into());
        }
        return Ok(ProcessInput::File(PathBuf::from(path)));
    }
    if let Some(cache_id) = spec.strip_prefix("cache=") {
        if cache_id.is_empty() {
            return Err(ProcessError::InvalidArgument(
                "merge cache source id must not be empty".to_owned(),
            )
            .into());
        }
        return Ok(ProcessInput::Cache(cache_id.to_owned()));
    }
    Err(
        ProcessError::InvalidArgument("merge --source must use file=PATH or cache=ID".to_owned())
            .into(),
    )
}

fn conflict_policy(value: &str) -> Result<ConflictPolicy, ProcessError> {
    match value {
        "error" => Ok(ConflictPolicy::Error),
        "keep-first" => Ok(ConflictPolicy::KeepFirst),
        _ => Err(ProcessError::InvalidArgument(format!(
            "unknown conflict policy {value:?}"
        ))),
    }
}

fn basic_operation(action: &ProcessAction) -> Result<Operation, ProcessError> {
    match action {
        ProcessAction::Validate => Ok(Operation::Validate),
        ProcessAction::Select { fields } => Operation::select(fields),
        ProcessAction::Filter { field, equals } => Operation::filter(field, equals),
        ProcessAction::Count => Ok(Operation::Count),
        ProcessAction::Group { field } => Operation::group(field),
        ProcessAction::Sort { .. }
        | ProcessAction::Dedupe { .. }
        | ProcessAction::Merge { .. }
        | ProcessAction::Containing { .. }
        | ProcessAction::GroupLocations { .. }
        | ProcessAction::ToJsonl
        | ProcessAction::FromJsonl => Err(ProcessError::InvalidArgument(
            "operation is not a basic YAML processor".to_owned(),
        )),
    }
}

fn path_text(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}
