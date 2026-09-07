mod cpp;
mod csharp;
mod generic;
mod go;
mod javascript;
mod language;
mod python;
mod rust_lang;
mod scope;
mod typed;
mod typescript;

use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsString;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use srcq_core::config::{load_standard_config, resolve_settings};
use srcq_core::engine::{discover_engine, EngineEnvironment, SystemEngineEnvironment};
use srcq_core::invocation::{ExplicitOptions, OutputFormat};
use srcq_core::process::{run, ProcessError, ProcessOutcome, ProcessRequest, StdinMode};

use crate::{SymbolBodyMode, SymbolCommand, SymbolOperation};
use cpp::{
    DefinitionCandidate, DefinitionRole, DirectCallCandidate, FunctionOwnerCandidate,
    OccurrenceCandidate, SourcePosition, SourceRange,
};
use scope::{normalized_key, slash_path, SourceUniverse};

const MAX_RG_STDOUT_BYTES: u64 = 32 * 1024 * 1024;
const MAX_AST_STDOUT_BYTES: u64 = 256 * 1024 * 1024;
const MAX_ENGINE_STDERR_BYTES: u64 = 4 * 1024 * 1024;
const MAX_SOURCE_POSITION_BYTES: u64 = 64 * 1024 * 1024;
const WINDOWS_BATCH_CHARS: usize = 24_000;

#[derive(Clone, Copy, Debug)]
struct QueryDeadline {
    started: Instant,
    deadline: Instant,
    budget: Duration,
}

impl QueryDeadline {
    fn new(milliseconds: u64) -> Self {
        let started = Instant::now();
        let budget = Duration::from_millis(milliseconds);
        Self {
            started,
            deadline: started + budget,
            budget,
        }
    }

    fn remaining(self) -> Result<Duration, SymbolFailure> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| SymbolFailure::timeout(self))
    }
}

#[derive(Debug)]
struct SymbolFailure {
    code: i32,
    message: String,
    time_limited: bool,
}

impl SymbolFailure {
    fn new(code: i32, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            time_limited: false,
        }
    }

    fn input(message: impl Into<String>) -> Self {
        Self::new(125, message)
    }

    fn conversion(message: impl Into<String>) -> Self {
        Self::new(124, message)
    }

    fn io(message: impl Into<String>) -> Self {
        Self::new(126, message)
    }

    fn engine(message: impl Into<String>) -> Self {
        Self::new(120, message)
    }

    fn timeout(deadline: QueryDeadline) -> Self {
        Self {
            code: 124,
            message: format!(
                "symbol query reached its {} ms time budget after {} ms; the result is incomplete. Retry from --at or narrow with --only-root/--exclude; raise --time-budget-ms only for a deliberate broader scan",
                deadline.budget.as_millis(),
                deadline.started.elapsed().as_millis()
            ),
            time_limited: true,
        }
    }
}

fn run_budgeted(
    mut request: ProcessRequest,
    deadline: QueryDeadline,
    operation: &'static str,
) -> Result<ProcessOutcome, SymbolFailure> {
    request.timeout = Some(deadline.remaining()?);
    match run(request) {
        Ok(outcome) => Ok(outcome),
        Err(ProcessError::Timeout { .. }) => Err(SymbolFailure::timeout(deadline)),
        Err(error) => Err(SymbolFailure::io(format!("{operation} failed: {error}"))),
    }
}

struct QueryOutcome {
    target: String,
    universe: SourceUniverse,
    candidate_files: usize,
    scanned_roots: BTreeSet<String>,
    scan_complete: bool,
    definitions: Vec<DefinitionCandidate>,
    declarations: Vec<DefinitionCandidate>,
    definition_total: usize,
    declaration_total: usize,
    position_matched: bool,
}

struct ResolvedQuery {
    target: String,
    anchor_file: Option<PathBuf>,
    anchor_position: Option<SourcePosition>,
    universe: SourceUniverse,
    rg: PathBuf,
    ast_grep: PathBuf,
    language: language::LanguageCapability,
}

#[derive(Clone, Debug)]
struct ReferenceCandidate {
    file: PathBuf,
    position: SourcePosition,
    role: &'static str,
    root_alias: Option<String>,
}

struct ReferencesOutcome {
    target: String,
    universe: SourceUniverse,
    candidate_files: usize,
    definitions: Vec<DefinitionCandidate>,
    definition_total: usize,
    references: Vec<ReferenceCandidate>,
    reference_total: usize,
    position_matched: bool,
    scanned_roots: BTreeSet<String>,
    scan_complete: bool,
}

struct SourceDocument {
    text: String,
    line_offsets: Vec<usize>,
}

#[derive(Clone, Debug)]
struct CallTreeNode {
    name: String,
    qualified_name: Option<String>,
    dispatch: &'static str,
    status: String,
    receiver: Option<String>,
    receiver_type: Option<String>,
    call_file: Option<PathBuf>,
    call_position: Option<SourcePosition>,
    definition: Option<DefinitionCandidate>,
    children: Vec<CallTreeNode>,
}

struct CallsOutcome {
    target: String,
    direction: String,
    universe: SourceUniverse,
    root: Option<CallTreeNode>,
    root_definition_total: usize,
    nodes: usize,
    truncated: bool,
    time_limited: bool,
    scan_complete: bool,
}

struct CallsBundleOutcome {
    target: String,
    universe: SourceUniverse,
    incoming: CallsOutcome,
    outgoing: CallsOutcome,
}

#[derive(Clone)]
struct CalleeResolution {
    total: usize,
    definition: Option<DefinitionCandidate>,
}

struct CallQueryContext<'a> {
    ast_grep: &'a Path,
    universe: &'a SourceUniverse,
    language: language::LanguageCapability,
    deadline: QueryDeadline,
    command: &'a SymbolCommand,
}

type IncomingCaller = (
    ReferenceCandidate,
    FunctionOwnerCandidate,
    Option<DirectCallCandidate>,
);

pub fn execute(command: &SymbolCommand) -> i32 {
    match command.operation {
        SymbolOperation::Capabilities => {
            let bytes = language::render(command.output);
            return write_stdout(bytes).map_or_else(
                |error| {
                    eprintln!("srcq: {}", error.message);
                    error.code
                },
                |()| 0,
            );
        }
        SymbolOperation::References => return execute_references(command),
        SymbolOperation::Calls => return execute_calls(command),
        SymbolOperation::Definition => {}
    }
    let deadline = QueryDeadline::new(command.time_budget_ms);
    match execute_inner(command, deadline) {
        Ok(outcome) => {
            let rendered = match command.output {
                OutputFormat::Model => render_model(command, &outcome),
                OutputFormat::Machine => render_machine(command, &outcome),
            };
            match rendered.and_then(write_stdout) {
                Ok(()) if outcome.definition_total > 0 => 0,
                Ok(()) => 1,
                Err(error) => {
                    eprintln!("srcq: {}", error.message);
                    error.code
                }
            }
        }
        Err(error) => {
            eprintln!("srcq: {}", error.message);
            error.code
        }
    }
}

fn execute_references(command: &SymbolCommand) -> i32 {
    let deadline = QueryDeadline::new(command.time_budget_ms);
    match execute_references_inner(command, deadline) {
        Ok(outcome) => {
            let rendered = match command.output {
                OutputFormat::Model => render_references_model(command, &outcome),
                OutputFormat::Machine => render_references_machine(command, &outcome),
            };
            match rendered.and_then(write_stdout) {
                Ok(()) if outcome.reference_total > 0 => 0,
                Ok(()) => 1,
                Err(error) => {
                    eprintln!("srcq: {}", error.message);
                    error.code
                }
            }
        }
        Err(error) => {
            eprintln!("srcq: {}", error.message);
            error.code
        }
    }
}

fn execute_calls(command: &SymbolCommand) -> i32 {
    let deadline = QueryDeadline::new(command.time_budget_ms);
    if command.direction == "both" {
        return match execute_calls_bundle_inner(command, deadline) {
            Ok(outcome) => {
                let rendered = match command.output {
                    OutputFormat::Model => render_calls_bundle_model(command, &outcome),
                    OutputFormat::Machine => render_calls_bundle_machine(command, &outcome),
                };
                match rendered.and_then(write_stdout) {
                    Ok(()) if outcome.incoming.time_limited || outcome.outgoing.time_limited => 124,
                    Ok(())
                        if outcome.incoming.root.is_some() || outcome.outgoing.root.is_some() =>
                    {
                        0
                    }
                    Ok(()) => 1,
                    Err(error) => {
                        eprintln!("srcq: {}", error.message);
                        error.code
                    }
                }
            }
            Err(error) => {
                eprintln!("srcq: {}", error.message);
                error.code
            }
        };
    }
    match execute_calls_inner(command, deadline) {
        Ok(outcome) => {
            let rendered = match command.output {
                OutputFormat::Model => render_calls_model(command, &outcome),
                OutputFormat::Machine => render_calls_machine(command, &outcome),
            };
            match rendered.and_then(write_stdout) {
                Ok(()) if outcome.time_limited => 124,
                Ok(()) if outcome.root.is_some() => 0,
                Ok(()) => 1,
                Err(error) => {
                    eprintln!("srcq: {}", error.message);
                    error.code
                }
            }
        }
        Err(error) => {
            eprintln!("srcq: {}", error.message);
            error.code
        }
    }
}

fn execute_calls_inner(
    command: &SymbolCommand,
    deadline: QueryDeadline,
) -> Result<CallsOutcome, SymbolFailure> {
    let query = resolve_query(command)?;
    let definitions = execute_inner_resolved(command, &query, deadline)?;
    execute_calls_branch(command, &query, &definitions, &command.direction, deadline)
}

fn execute_calls_bundle_inner(
    command: &SymbolCommand,
    deadline: QueryDeadline,
) -> Result<CallsBundleOutcome, SymbolFailure> {
    let query = resolve_query(command)?;
    let definitions = execute_inner_resolved(command, &query, deadline)?;
    let incoming = execute_calls_branch(command, &query, &definitions, "incoming", deadline)?;
    let outgoing = execute_calls_branch(command, &query, &definitions, "outgoing", deadline)?;
    Ok(CallsBundleOutcome {
        target: definitions.target.clone(),
        universe: definitions.universe.clone(),
        incoming,
        outgoing,
    })
}

fn execute_calls_branch(
    command: &SymbolCommand,
    query: &ResolvedQuery,
    definitions: &QueryOutcome,
    direction: &str,
    deadline: QueryDeadline,
) -> Result<CallsOutcome, SymbolFailure> {
    let root_definition_total = definitions.definition_total;
    if root_definition_total != 1 {
        return Ok(CallsOutcome {
            target: definitions.target.clone(),
            direction: direction.to_owned(),
            universe: definitions.universe.clone(),
            root: None,
            root_definition_total,
            nodes: 0,
            truncated: false,
            time_limited: false,
            scan_complete: definitions.scan_complete,
        });
    }
    let has_dynamic_dispatch = definitions.declarations.iter().any(|declaration| {
        declaration.signature.split_whitespace().any(|word| {
            matches!(
                word.trim_matches(|character: char| !character.is_ascii_alphanumeric()),
                "virtual" | "override"
            )
        })
    });
    let root_definition = definitions.definitions[0].clone();
    let mut resolution_cache = BTreeMap::new();
    let mut call_cache = BTreeMap::new();
    let mut active = BTreeSet::new();
    active.insert(definition_identity(&root_definition));
    let mut nodes = 1_usize;
    let mut truncated = false;
    let mut time_limited = false;
    let mut scan_complete = definitions.scan_complete;
    let mut root = CallTreeNode {
        name: root_definition.qualified_name.clone(),
        qualified_name: Some(root_definition.qualified_name.clone()),
        dispatch: "root",
        status: if definitions.position_matched {
            "position-candidate".to_owned()
        } else {
            definition_identity_evidence(command).to_owned()
        },
        receiver: None,
        receiver_type: None,
        call_file: None,
        call_position: None,
        definition: Some(root_definition.clone()),
        children: Vec::new(),
    };
    if direction == "incoming" {
        expand_incoming_node(
            &mut root,
            &root_definition,
            0,
            command,
            query,
            deadline,
            &mut resolution_cache,
            &mut call_cache,
            &mut active,
            &mut nodes,
            &mut truncated,
            &mut time_limited,
            &mut scan_complete,
        )?;
        if has_dynamic_dispatch && command.depth > 0 {
            if nodes < command.max_nodes {
                root.children.push(CallTreeNode {
                    name: "dynamic callers".to_owned(),
                    qualified_name: None,
                    dispatch: "semantic-unknown:virtual-dispatch",
                    status: "semantic-unknown:virtual-dispatch".to_owned(),
                    receiver: None,
                    receiver_type: None,
                    call_file: None,
                    call_position: None,
                    definition: None,
                    children: Vec::new(),
                });
                nodes += 1;
            } else {
                truncated = true;
            }
        }
    } else {
        expand_call_node(
            &mut root,
            &root_definition,
            0,
            command,
            query,
            deadline,
            &mut resolution_cache,
            &mut call_cache,
            &mut active,
            &mut nodes,
            &mut truncated,
            &mut time_limited,
        )?;
    }
    Ok(CallsOutcome {
        target: definitions.target.clone(),
        direction: direction.to_owned(),
        universe: definitions.universe.clone(),
        root: Some(root),
        root_definition_total,
        nodes,
        truncated,
        time_limited,
        scan_complete,
    })
}

#[allow(clippy::too_many_arguments)]
fn expand_call_node(
    node: &mut CallTreeNode,
    definition: &DefinitionCandidate,
    depth: usize,
    command: &SymbolCommand,
    query: &ResolvedQuery,
    deadline: QueryDeadline,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
    call_cache: &mut BTreeMap<String, cpp::CallScan>,
    active: &mut BTreeSet<String>,
    nodes: &mut usize,
    truncated: &mut bool,
    time_limited: &mut bool,
) -> Result<(), SymbolFailure> {
    if depth >= command.depth {
        return Ok(());
    }
    let context = CallQueryContext {
        ast_grep: &query.ast_grep,
        universe: &query.universe,
        language: query.language,
        deadline,
        command,
    };
    let calls = match calls_for_definition(definition, &context, call_cache, resolution_cache) {
        Ok(calls) => calls,
        Err(error) if error.time_limited => {
            *time_limited = true;
            return Ok(());
        }
        Err(error) => return Err(error),
    };
    for call in calls {
        if *nodes >= command.max_nodes {
            *truncated = true;
            break;
        }
        *nodes += 1;
        let mut child = CallTreeNode {
            name: call.callee.clone(),
            qualified_name: call.callee.contains("::").then(|| call.callee.clone()),
            dispatch: call.dispatch,
            status: match call.dispatch {
                "direct-candidate" | "typed-member-candidate" => call.dispatch.to_owned(),
                _ => "semantic-unknown".to_owned(),
            },
            receiver: call.receiver.clone(),
            receiver_type: call.receiver_type.clone(),
            call_file: Some(call.file.clone()),
            call_position: Some(call.range.start),
            definition: None,
            children: Vec::new(),
        };
        if depth + 1 < command.depth
            && matches!(call.dispatch, "direct-candidate" | "typed-member-candidate")
        {
            let resolution = match resolve_callee(
                &call.callee,
                command,
                &query.universe,
                &call.file,
                deadline,
                resolution_cache,
            ) {
                Ok(resolution) => resolution,
                Err(error) if error.time_limited => {
                    child.status = "time-budget".to_owned();
                    node.children.push(child);
                    *time_limited = true;
                    return Ok(());
                }
                Err(error) => return Err(error),
            };
            child.status = match resolution.total {
                0 => "semantic-unknown".to_owned(),
                1 => definition_identity_evidence(command).to_owned(),
                count => format!("ambiguous:{count}"),
            };
            if let Some(child_definition) = resolution.definition {
                let identity = definition_identity(&child_definition);
                child.definition = Some(child_definition.clone());
                if active.contains(&identity) {
                    child.status = "cycle".to_owned();
                } else {
                    active.insert(identity.clone());
                    expand_call_node(
                        &mut child,
                        &child_definition,
                        depth + 1,
                        command,
                        query,
                        deadline,
                        resolution_cache,
                        call_cache,
                        active,
                        nodes,
                        truncated,
                        time_limited,
                    )?;
                    active.remove(&identity);
                }
            }
        }
        node.children.push(child);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn expand_incoming_node(
    node: &mut CallTreeNode,
    definition: &DefinitionCandidate,
    depth: usize,
    command: &SymbolCommand,
    query: &ResolvedQuery,
    deadline: QueryDeadline,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
    call_cache: &mut BTreeMap<String, cpp::CallScan>,
    active: &mut BTreeSet<String>,
    nodes: &mut usize,
    truncated: &mut bool,
    time_limited: &mut bool,
    scan_complete: &mut bool,
) -> Result<(), SymbolFailure> {
    if depth >= command.depth {
        return Ok(());
    }
    let (callers, caller_scan_complete) = match incoming_callers(
        definition,
        command,
        query,
        deadline,
        call_cache,
        resolution_cache,
    ) {
        Ok(result) => result,
        Err(error) if error.time_limited => {
            *time_limited = true;
            *scan_complete = false;
            return Ok(());
        }
        Err(error) => return Err(error),
    };
    *scan_complete &= caller_scan_complete;
    for (reference, owner, matching_call) in callers {
        if *nodes >= command.max_nodes {
            *truncated = true;
            break;
        }
        *nodes += 1;
        let mut child = CallTreeNode {
            name: owner.name.clone(),
            qualified_name: owner.definition.as_ref().map_or_else(
                || owner.qualified_name.clone(),
                |definition| Some(definition.qualified_name.clone()),
            ),
            dispatch: "incoming-candidate",
            status: matching_call.as_ref().map_or_else(
                || "lexical-candidate".to_owned(),
                |call| call.dispatch.to_owned(),
            ),
            receiver: matching_call
                .as_ref()
                .and_then(|call| call.receiver.clone()),
            receiver_type: matching_call
                .as_ref()
                .and_then(|call| call.receiver_type.clone()),
            call_file: Some(reference.file),
            call_position: Some(reference.position),
            definition: owner.definition.clone(),
            children: Vec::new(),
        };
        if depth + 1 < command.depth {
            let resolution = if let Some(definition) = owner.definition.clone() {
                CalleeResolution {
                    total: 1,
                    definition: Some(definition),
                }
            } else {
                match resolve_callee(
                    owner.qualified_name.as_deref().unwrap_or(&owner.name),
                    command,
                    &query.universe,
                    &owner.file,
                    deadline,
                    resolution_cache,
                ) {
                    Ok(resolution) => resolution,
                    Err(error) if error.time_limited => {
                        child.status = "time-budget".to_owned();
                        node.children.push(child);
                        *time_limited = true;
                        *scan_complete = false;
                        return Ok(());
                    }
                    Err(error) => return Err(error),
                }
            };
            child.status = match resolution.total {
                0 => "semantic-unknown".to_owned(),
                1 => definition_identity_evidence(command).to_owned(),
                count => format!("ambiguous:{count}"),
            };
            if let Some(child_definition) = resolution.definition {
                let identity = definition_identity(&child_definition);
                child.definition = Some(child_definition.clone());
                if active.contains(&identity) {
                    child.status = "cycle".to_owned();
                } else {
                    active.insert(identity.clone());
                    expand_incoming_node(
                        &mut child,
                        &child_definition,
                        depth + 1,
                        command,
                        query,
                        deadline,
                        resolution_cache,
                        call_cache,
                        active,
                        nodes,
                        truncated,
                        time_limited,
                        scan_complete,
                    )?;
                    active.remove(&identity);
                }
            }
        }
        node.children.push(child);
    }
    Ok(())
}

fn incoming_callers(
    definition: &DefinitionCandidate,
    command: &SymbolCommand,
    query: &ResolvedQuery,
    deadline: QueryDeadline,
    call_cache: &mut BTreeMap<String, cpp::CallScan>,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<(Vec<IncomingCaller>, bool), SymbolFailure> {
    let (references, scan_complete) =
        references_for_known_definition(definition, command, query, deadline)?;
    let call_references = references
        .into_iter()
        .filter(|reference| reference.role == "call")
        .collect::<Vec<_>>();
    let mut files = call_references
        .iter()
        .map(|reference| reference.file.clone())
        .collect::<Vec<_>>();
    files.sort_by_key(|path| normalized_key(path));
    files.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    let owners = scan_containing_functions(
        &query.ast_grep,
        &definition.qualified_name,
        &files,
        &query.universe,
        query.language,
        deadline,
    )?;
    let mut callers = Vec::new();
    let context = CallQueryContext {
        ast_grep: &query.ast_grep,
        universe: &query.universe,
        language: query.language,
        deadline,
        command,
    };
    cache_call_scans(&files, &context, call_cache)?;
    for reference in call_references {
        let owner = owners
            .iter()
            .filter(|owner| {
                normalized_key(&owner.file) == normalized_key(&reference.file)
                    && position_in_range(reference.position, owner.range)
            })
            .min_by_key(|owner| {
                (
                    owner.range.end.line.saturating_sub(owner.range.start.line),
                    owner
                        .range
                        .end
                        .column
                        .saturating_sub(owner.range.start.column),
                )
            })
            .cloned();
        if let Some(owner) = owner {
            let scan_definition = owner
                .definition
                .clone()
                .unwrap_or_else(|| DefinitionCandidate {
                    file: owner.file.clone(),
                    range: owner.range,
                    name_position: owner.range.start,
                    qualified_name: owner
                        .qualified_name
                        .clone()
                        .unwrap_or_else(|| owner.name.clone()),
                    symbol_kind: "method".to_owned(),
                    role: DefinitionRole::Definition,
                    signature: owner.signature.clone(),
                    text: String::new(),
                    ast_kind: "method_declaration".to_owned(),
                    root_alias: query
                        .universe
                        .root_for(&owner.file)
                        .map(|root| root.alias.clone()),
                });
            let observed_call = call_for_definition_at(
                &scan_definition,
                reference.position,
                &context,
                call_cache,
                resolution_cache,
            )?
            .filter(|call| {
                call.callee.rsplit("::").next() == definition.qualified_name.rsplit("::").next()
            });
            if observed_call.is_none() {
                continue;
            }
            let matching_call = if matches!(
                query.language.key,
                "cpp" | "csharp" | "go" | "javascript" | "python" | "rust" | "typescript" | "tsx"
            ) {
                observed_call
            } else {
                None
            };
            if matching_call.as_ref().is_some_and(|call| {
                call.dispatch == "typed-member-candidate"
                    && !qualified_suffix_matches(&definition.qualified_name, &call.callee)
            }) {
                continue;
            }
            callers.push((reference, owner, matching_call));
        }
    }
    callers.sort_by(|left, right| {
        normalized_key(&left.0.file)
            .cmp(&normalized_key(&right.0.file))
            .then_with(|| left.0.position.line.cmp(&right.0.position.line))
            .then_with(|| left.0.position.column.cmp(&right.0.position.column))
    });
    Ok((callers, scan_complete))
}

fn references_for_known_definition(
    definition: &DefinitionCandidate,
    command: &SymbolCommand,
    query: &ResolvedQuery,
    deadline: QueryDeadline,
) -> Result<(Vec<ReferenceCandidate>, bool), SymbolFailure> {
    let roots = reference_scan_inputs(command, query, std::slice::from_ref(definition));
    let mut scanned_roots = query
        .universe
        .roots
        .iter()
        .filter(|root| {
            roots.iter().any(|selected| {
                normalized_key(selected) == normalized_key(&root.path)
                    || root.path.starts_with(selected)
            })
        })
        .map(|root| normalized_key(&root.path))
        .collect::<BTreeSet<_>>();
    if query
        .universe
        .has_complete_compile_scope(query.language.key)
        && path_set_contains_all(&roots, &query.universe.compile_files)
    {
        scanned_roots.extend(
            query
                .universe
                .roots
                .iter()
                .map(|root| normalized_key(&root.path)),
        );
    }
    let scan_complete = scanned_roots.len() == query.universe.roots.len();
    let lexical_target = definition
        .qualified_name
        .rsplit("::")
        .next()
        .unwrap_or(&definition.qualified_name);
    let candidate_files = find_candidate_files(
        &query.rg,
        lexical_target,
        &roots,
        &query.universe,
        query.language,
        deadline,
    )?;
    let occurrences = scan_occurrences(
        &query.ast_grep,
        lexical_target,
        &candidate_files,
        &query.universe,
        query.language,
        deadline,
    )?;
    let definition_key = (
        normalized_key(&definition.file),
        definition.name_position.line,
        definition.name_position.column,
    );
    let mut documents = BTreeMap::new();
    let mut references = Vec::new();
    for occurrence in occurrences {
        let occurrence_key = (
            normalized_key(&occurrence.file),
            occurrence.range.start.line,
            occurrence.range.start.column,
        );
        if occurrence_key == definition_key {
            continue;
        }
        let document = source_document(&occurrence.file, &mut documents)?;
        references.push(ReferenceCandidate {
            role: reference_role(document, occurrence.range.end),
            file: occurrence.file,
            position: occurrence.range.start,
            root_alias: occurrence.root_alias,
        });
    }
    references.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.position.line.cmp(&right.position.line))
            .then_with(|| left.position.column.cmp(&right.position.column))
    });
    references.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file) && left.position == right.position
    });
    Ok((references, scan_complete))
}

fn qualified_suffix_matches(definition: &str, candidate: &str) -> bool {
    definition == candidate || definition.ends_with(&format!("::{candidate}"))
}

fn source_range_size(range: SourceRange) -> (usize, usize) {
    (
        range.end.line.saturating_sub(range.start.line),
        range.end.column.saturating_sub(range.start.column),
    )
}

fn position_in_range(position: SourcePosition, range: SourceRange) -> bool {
    (range.start.line, range.start.column) <= (position.line, position.column)
        && (position.line, position.column) <= (range.end.line, range.end.column)
}

fn resolve_callee(
    callee: &str,
    command: &SymbolCommand,
    universe: &SourceUniverse,
    local_file: &Path,
    deadline: QueryDeadline,
    cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<CalleeResolution, SymbolFailure> {
    let cache_key = format!("{}|{}", callee, normalized_key(local_file));
    if let Some(cached) = cache.get(&cache_key) {
        return Ok(cached.clone());
    }
    let mut child_command = command.clone();
    child_command.operation = SymbolOperation::Definition;
    child_command.name = Some(callee.to_owned());
    child_command.at = None;
    child_command.body = SymbolBodyMode::None;
    child_command.add_roots.clear();
    child_command.only_roots = bounded_relation_roots(universe, &command.language, local_file);
    let outcome = execute_inner(&child_command, deadline)?;
    let local_definitions = outcome
        .definitions
        .iter()
        .filter(|definition| normalized_key(&definition.file) == normalized_key(local_file))
        .cloned()
        .collect::<Vec<_>>();
    let (total, definition) = if outcome.definition_total > 1 && local_definitions.len() == 1 {
        (1, local_definitions.into_iter().next())
    } else {
        (
            outcome.definition_total,
            (outcome.definition_total == 1).then(|| outcome.definitions[0].clone()),
        )
    };
    let resolution = CalleeResolution { total, definition };
    cache.insert(cache_key, resolution.clone());
    Ok(resolution)
}

fn bounded_relation_roots(
    universe: &SourceUniverse,
    language: &str,
    local_file: &Path,
) -> Vec<PathBuf> {
    let explicit_only = universe.roots.iter().all(|root| root.source == "explicit");
    let mut roots = if explicit_only {
        universe
            .roots
            .iter()
            .map(|root| root.path.clone())
            .collect()
    } else if universe.has_complete_compile_scope(language) {
        universe.compile_files.clone()
    } else {
        relation_source_roots(universe, local_file)
    };
    roots.push(local_file.to_path_buf());
    roots.extend(
        universe
            .roots
            .iter()
            .filter(|root| root.source == "explicit")
            .map(|root| root.path.clone()),
    );
    roots.extend(universe.compile_files.iter().cloned());
    roots.sort_by_key(|path| normalized_key(path));
    roots.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    roots
}

fn relation_source_roots(universe: &SourceUniverse, local_file: &Path) -> Vec<PathBuf> {
    if local_file.starts_with(&universe.project_root) {
        for ancestor in local_file.ancestors().skip(1) {
            if ancestor == universe.project_root {
                break;
            }
            let Some(name) = ancestor.file_name().and_then(|value| value.to_str()) else {
                continue;
            };
            if name.eq_ignore_ascii_case("source") {
                return vec![ancestor.to_path_buf()];
            }
            if name.eq_ignore_ascii_case("src") || name.eq_ignore_ascii_case("include") {
                let Some(parent) = ancestor.parent() else {
                    break;
                };
                let mut roots = ["src", "include", "source"]
                    .into_iter()
                    .map(|candidate| parent.join(candidate))
                    .filter(|candidate| candidate.exists())
                    .collect::<Vec<_>>();
                if roots.is_empty() {
                    roots.push(ancestor.to_path_buf());
                }
                return roots;
            }
        }
    }
    vec![universe.project_root.clone()]
}

fn definition_identity(definition: &DefinitionCandidate) -> String {
    format!(
        "{}:{}:{}",
        normalized_key(&definition.file),
        definition.range.start.line,
        definition.range.start.column
    )
}

fn execute_references_inner(
    command: &SymbolCommand,
    deadline: QueryDeadline,
) -> Result<ReferencesOutcome, SymbolFailure> {
    let mut definition_command = command.clone();
    definition_command.operation = SymbolOperation::Definition;
    definition_command.limit = 10_000;
    let definition_outcome = execute_inner(&definition_command, deadline)?;
    let query = resolve_query(command)?;
    let mut definitions = definition_outcome.definitions;
    definitions.extend(definition_outcome.declarations);
    let position_matched = definition_outcome.position_matched;
    let roots = reference_scan_inputs(command, &query, &definitions);
    let mut scanned_roots = query
        .universe
        .roots
        .iter()
        .filter(|root| {
            roots.iter().any(|selected| {
                normalized_key(selected) == normalized_key(&root.path)
                    || root.path.starts_with(selected)
            })
        })
        .map(|root| normalized_key(&root.path))
        .collect::<BTreeSet<_>>();
    if query
        .universe
        .has_complete_compile_scope(query.language.key)
        && path_set_contains_all(&roots, &query.universe.compile_files)
    {
        scanned_roots.extend(
            query
                .universe
                .roots
                .iter()
                .map(|root| normalized_key(&root.path)),
        );
    }
    let scan_complete = scanned_roots.len() == query.universe.roots.len();
    let lexical_target = query.target.rsplit("::").next().unwrap_or(&query.target);
    let candidate_files = find_candidate_files(
        &query.rg,
        lexical_target,
        &roots,
        &query.universe,
        query.language,
        deadline,
    )?;
    definitions.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.name_position.line.cmp(&right.name_position.line))
            .then_with(|| left.name_position.column.cmp(&right.name_position.column))
    });
    definitions.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.name_position == right.name_position
    });
    let definition_sites = definitions
        .iter()
        .map(|candidate| {
            format!(
                "{}:{}:{}",
                normalized_key(&candidate.file),
                candidate.name_position.line,
                candidate.name_position.column
            )
        })
        .collect::<BTreeSet<_>>();
    let occurrences = scan_occurrences(
        &query.ast_grep,
        &query.target,
        &candidate_files,
        &query.universe,
        query.language,
        deadline,
    )?;
    let mut documents = BTreeMap::new();
    let mut references = Vec::new();
    for occurrence in occurrences {
        let site = format!(
            "{}:{}:{}",
            normalized_key(&occurrence.file),
            occurrence.range.start.line,
            occurrence.range.start.column
        );
        if definition_sites.contains(&site) {
            continue;
        }
        let document = source_document(&occurrence.file, &mut documents)?;
        references.push(ReferenceCandidate {
            role: reference_role(document, occurrence.range.end),
            file: occurrence.file,
            position: occurrence.range.start,
            root_alias: occurrence.root_alias,
        });
    }
    references.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.position.line.cmp(&right.position.line))
            .then_with(|| left.position.column.cmp(&right.position.column))
    });
    references.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file) && left.position == right.position
    });
    let definition_total = definitions
        .iter()
        .filter(|candidate| candidate.role == DefinitionRole::Definition)
        .count();
    let reference_total = references.len();
    definitions.truncate(command.limit);
    references.truncate(command.limit);
    Ok(ReferencesOutcome {
        target: query.target,
        universe: query.universe,
        candidate_files: candidate_files.len(),
        definitions,
        definition_total,
        references,
        reference_total,
        position_matched,
        scanned_roots,
        scan_complete,
    })
}

fn reference_scan_inputs(
    command: &SymbolCommand,
    query: &ResolvedQuery,
    definitions: &[DefinitionCandidate],
) -> Vec<PathBuf> {
    if !command.only_roots.is_empty() {
        return query
            .universe
            .roots
            .iter()
            .map(|root| root.path.clone())
            .collect();
    }
    if query
        .universe
        .has_complete_compile_scope(query.language.key)
    {
        let mut inputs = query.universe.compile_files.clone();
        inputs.extend(query.anchor_file.iter().cloned());
        inputs.extend(definitions.iter().map(|definition| definition.file.clone()));
        inputs.sort_by_key(|path| normalized_key(path));
        inputs.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
        return inputs;
    }
    let mut inputs = Vec::new();
    for local_file in query
        .anchor_file
        .iter()
        .chain(definitions.iter().map(|definition| &definition.file))
    {
        inputs.extend(relation_source_roots(&query.universe, local_file));
    }
    if inputs.is_empty() {
        inputs.push(query.universe.project_root.clone());
    }
    inputs.extend(query.universe.compile_files.iter().cloned());
    inputs.extend(query.anchor_file.iter().cloned());
    inputs.extend(definitions.iter().map(|definition| definition.file.clone()));
    inputs.sort_by_key(|path| normalized_key(path));
    inputs.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    inputs
}

fn execute_inner(
    command: &SymbolCommand,
    deadline: QueryDeadline,
) -> Result<QueryOutcome, SymbolFailure> {
    let query = resolve_query(command)?;
    execute_inner_resolved(command, &query, deadline)
}

fn execute_inner_resolved(
    command: &SymbolCommand,
    query: &ResolvedQuery,
    deadline: QueryDeadline,
) -> Result<QueryOutcome, SymbolFailure> {
    let ResolvedQuery {
        target,
        anchor_file,
        anchor_position,
        universe,
        rg,
        ast_grep,
        language,
    } = query;
    let phases = scan_phases(command, anchor_file.as_deref(), universe);
    let mut candidate_file_keys = BTreeSet::new();
    let mut scanned_roots = BTreeSet::new();
    let mut candidates = Vec::new();
    for phase in phases {
        let candidate_files =
            find_candidate_files(rg, target, &phase, universe, *language, deadline)?;
        candidate_file_keys.extend(candidate_files.iter().map(|path| normalized_key(path)));
        candidates.extend(scan_candidates(
            ast_grep,
            target,
            &candidate_files,
            universe,
            *language,
            deadline,
        )?);
        for root in &universe.roots {
            if phase
                .iter()
                .any(|selected| normalized_key(selected) == normalized_key(&root.path))
            {
                scanned_roots.insert(normalized_key(&root.path));
            }
        }
        if universe.has_complete_compile_scope(&command.language)
            && same_path_set(&phase, &universe.compile_files)
        {
            scanned_roots.extend(universe.roots.iter().map(|root| normalized_key(&root.path)));
        }
        if command.only_roots.is_empty()
            && candidates
                .iter()
                .any(|candidate| candidate.role == DefinitionRole::Definition)
        {
            break;
        }
    }
    finish_definition_outcome(
        command,
        target.clone(),
        universe.clone(),
        anchor_file.as_deref(),
        *anchor_position,
        candidate_file_keys,
        scanned_roots,
        candidates,
    )
}

fn resolve_query(command: &SymbolCommand) -> Result<ResolvedQuery, SymbolFailure> {
    let capability = language::find(&command.language).ok_or_else(|| {
        SymbolFailure::input(format!("unknown symbol language {:?}", command.language))
    })?;
    let operation_capability = match command.operation {
        SymbolOperation::Definition => capability.definition,
        SymbolOperation::References => capability.references,
        SymbolOperation::Calls => capability.calls,
        SymbolOperation::Capabilities => "not-applicable",
    };
    if operation_capability == "unadapted" || operation_capability == "not-applicable" {
        return Err(SymbolFailure::input(format!(
            "symbol language {} has relation capability {}; inspect `srcq symbol capabilities`",
            command.language, operation_capability
        )));
    }
    let launch_cwd = std::env::current_dir()
        .map_err(|error| SymbolFailure::io(format!("cannot read current directory: {error}")))?;
    let cwd = canonical_directory(command.cwd.as_deref().unwrap_or(&launch_cwd), &launch_cwd)?;
    let (target, anchor_file, anchor_position) = resolve_target(command, &cwd)?;
    let target = language::normalize_query_target(capability.key, target);
    let universe =
        scope::resolve(command, &cwd, anchor_file.as_deref()).map_err(SymbolFailure::input)?;
    let environment = SystemEngineEnvironment::from_process_environment();
    let rg = resolve_rg(command.rg_engine.as_deref(), &cwd, &environment)?;
    let ast_grep = resolve_ast_grep(command.ast_grep_engine.as_deref(), &cwd, &environment)?;
    Ok(ResolvedQuery {
        target,
        anchor_file,
        anchor_position,
        universe,
        rg,
        ast_grep,
        language: capability,
    })
}

#[allow(clippy::too_many_arguments)]
fn finish_definition_outcome(
    command: &SymbolCommand,
    target: String,
    universe: SourceUniverse,
    anchor_file: Option<&Path>,
    anchor_position: Option<SourcePosition>,
    candidate_file_keys: BTreeSet<String>,
    scanned_roots: BTreeSet<String>,
    mut candidates: Vec<DefinitionCandidate>,
) -> Result<QueryOutcome, SymbolFailure> {
    if command.language == "cpp" {
        cpp::promote_methods_from_declarations(&mut candidates);
    }
    let position_matched = select_anchor_candidates(&mut candidates, anchor_file, anchor_position);
    candidates.sort_by(|left, right| {
        left.role
            .cmp(&right.role)
            .then_with(|| normalized_key(&left.file).cmp(&normalized_key(&right.file)))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    candidates.dedup_by(|left, right| {
        left.role == right.role
            && normalized_key(&left.file) == normalized_key(&right.file)
            && left.range.start == right.range.start
            && left.qualified_name == right.qualified_name
    });
    let mut definitions = candidates
        .iter()
        .filter(|candidate| candidate.role == DefinitionRole::Definition)
        .cloned()
        .collect::<Vec<_>>();
    let mut declarations = candidates
        .into_iter()
        .filter(|candidate| candidate.role == DefinitionRole::Declaration)
        .collect::<Vec<_>>();
    let definition_total = definitions.len();
    let declaration_total = declarations.len();
    let scan_complete = scanned_roots.len() == universe.roots.len();
    definitions.truncate(command.limit);
    declarations.truncate(command.limit);
    Ok(QueryOutcome {
        target,
        universe,
        candidate_files: candidate_file_keys.len(),
        scan_complete,
        scanned_roots,
        definitions,
        declarations,
        definition_total,
        declaration_total,
        position_matched,
    })
}

fn select_anchor_candidates(
    candidates: &mut Vec<DefinitionCandidate>,
    anchor_file: Option<&Path>,
    anchor_position: Option<SourcePosition>,
) -> bool {
    let Some((anchor_file, anchor_position)) = anchor_file.zip(anchor_position) else {
        return false;
    };
    let anchor_key = normalized_key(anchor_file);
    let matched = candidates
        .iter()
        .filter(|candidate| {
            normalized_key(&candidate.file) == anchor_key
                && candidate.name_position == anchor_position
        })
        .cloned()
        .collect::<Vec<_>>();
    if matched.is_empty() {
        false
    } else {
        *candidates = matched;
        true
    }
}

fn scan_phases(
    command: &SymbolCommand,
    anchor_file: Option<&Path>,
    universe: &SourceUniverse,
) -> Vec<Vec<PathBuf>> {
    if !command.only_roots.is_empty() {
        return vec![universe
            .roots
            .iter()
            .map(|root| root.path.clone())
            .collect()];
    }
    let mut phases = Vec::new();
    if universe.source_manifest.is_some() {
        return vec![universe.compile_files.clone()];
    }
    if let Some(anchor_file) = anchor_file {
        phases.push(vec![anchor_file.to_path_buf()]);
    }
    let complete_compile_scope = universe.has_complete_compile_scope(&command.language);
    if complete_compile_scope {
        phases.push(universe.compile_files.clone());
    } else {
        let primary = universe
            .roots
            .iter()
            .filter(|root| matches!(root.source, "project" | "explicit"))
            .map(|root| root.path.clone())
            .collect::<Vec<_>>();
        if !primary.is_empty() {
            phases.push(primary);
        }
    }
    let external_compile_files = universe
        .compile_files
        .iter()
        .filter(|path| !path.starts_with(&universe.project_root))
        .cloned()
        .collect::<Vec<_>>();
    if !complete_compile_scope && !external_compile_files.is_empty() {
        phases.push(external_compile_files);
    }
    let external_compile_directories = universe
        .compile_directories
        .iter()
        .filter(|path| !path.starts_with(&universe.project_root))
        .cloned()
        .collect::<Vec<_>>();
    if !external_compile_directories.is_empty() {
        phases.push(external_compile_directories);
    }
    let external = universe
        .roots
        .iter()
        .filter(|root| !matches!(root.source, "project" | "explicit"))
        .map(|root| root.path.clone())
        .collect::<Vec<_>>();
    if !external.is_empty() {
        phases.push(external);
    }
    if phases.is_empty() {
        phases.push(
            universe
                .roots
                .iter()
                .map(|root| root.path.clone())
                .collect(),
        );
    }
    phases
}

fn same_path_set(left: &[PathBuf], right: &[PathBuf]) -> bool {
    left.len() == right.len()
        && left
            .iter()
            .map(|path| normalized_key(path))
            .collect::<BTreeSet<_>>()
            == right
                .iter()
                .map(|path| normalized_key(path))
                .collect::<BTreeSet<_>>()
}

fn source_manifest_model_line(universe: &SourceUniverse) -> String {
    universe
        .source_manifest
        .as_ref()
        .map_or_else(String::new, |manifest| {
            format!(
                "manifest {} adapter={} entries={}\n",
                universe.render_path(&manifest.path),
                manifest.adapter,
                manifest.entry_count,
            )
        })
}

fn with_source_manifest_scope(mut scope: Value, universe: &SourceUniverse) -> Value {
    let Some(manifest) = universe.source_manifest.as_ref() else {
        return scope;
    };
    let Some(fields) = scope.as_object_mut() else {
        return scope;
    };
    fields.insert(
        "source_manifest".to_owned(),
        json!({
            "path": slash_path(&manifest.path),
            "adapter": manifest.adapter,
            "entry_count": manifest.entry_count,
        }),
    );
    if !universe.issues.is_empty() && !fields.contains_key("issues") {
        fields.insert(
            "issues".to_owned(),
            Value::Array(
                universe
                    .issues
                    .iter()
                    .map(|issue| {
                        json!({
                            "code": issue.code,
                            "path": issue.path.as_deref().map(slash_path),
                            "detail": issue.detail,
                        })
                    })
                    .collect(),
            ),
        );
    }
    scope
}

fn path_set_contains_all(superset: &[PathBuf], subset: &[PathBuf]) -> bool {
    let superset = superset
        .iter()
        .map(|path| normalized_key(path))
        .collect::<BTreeSet<_>>();
    subset
        .iter()
        .all(|path| superset.contains(&normalized_key(path)))
}

fn canonical_directory(path: &Path, base: &Path) -> Result<PathBuf, SymbolFailure> {
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    };
    let canonical = fs::canonicalize(&path).map_err(|error| {
        SymbolFailure::input(format!(
            "cwd cannot be resolved: {}: {error}",
            path.display()
        ))
    })?;
    if !canonical.is_dir() {
        return Err(SymbolFailure::input(format!(
            "cwd is not a directory: {}",
            canonical.display()
        )));
    }
    Ok(canonical)
}

fn resolve_target(
    command: &SymbolCommand,
    cwd: &Path,
) -> Result<(String, Option<PathBuf>, Option<SourcePosition>), SymbolFailure> {
    if let Some(name) = &command.name {
        let name = name.trim();
        if name.is_empty() {
            return Err(SymbolFailure::input("symbol name cannot be empty"));
        }
        return Ok((name.to_owned(), None, None));
    }
    let raw = command
        .at
        .as_deref()
        .ok_or_else(|| SymbolFailure::input("symbol name or --at is required"))?;
    let (raw_path, line, column) = parse_source_position(raw)?;
    let path = PathBuf::from(raw_path);
    let path = if path.is_absolute() {
        path
    } else {
        cwd.join(path)
    };
    let path = fs::canonicalize(&path).map_err(|error| {
        SymbolFailure::input(format!(
            "--at source cannot be resolved: {}: {error}",
            path.display()
        ))
    })?;
    if !path.is_file() {
        return Err(SymbolFailure::input(format!(
            "--at source is not a file: {}",
            path.display()
        )));
    }
    let (name, position) = identifier_at(&path, line, column)?;
    Ok((name, Some(path), Some(position)))
}

fn parse_source_position(raw: &str) -> Result<(&str, usize, usize), SymbolFailure> {
    let mut parts = raw.rsplitn(3, ':');
    let column = parts
        .next()
        .and_then(|value| value.parse::<usize>().ok())
        .ok_or_else(|| SymbolFailure::input("--at column must be a zero-based integer"))?;
    let line = parts
        .next()
        .and_then(|value| value.parse::<usize>().ok())
        .ok_or_else(|| SymbolFailure::input("--at line must be a zero-based integer"))?;
    let path = parts
        .next()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| SymbolFailure::input("--at must use PATH:LINE:COLUMN"))?;
    Ok((path, line, column))
}

fn identifier_at(
    path: &Path,
    line: usize,
    column: usize,
) -> Result<(String, SourcePosition), SymbolFailure> {
    let metadata = fs::metadata(path).map_err(|error| {
        SymbolFailure::io(format!("cannot inspect {}: {error}", path.display()))
    })?;
    if metadata.len() > MAX_SOURCE_POSITION_BYTES {
        return Err(SymbolFailure::input(format!(
            "--at source exceeds {MAX_SOURCE_POSITION_BYTES} bytes: {}",
            path.display()
        )));
    }
    let source = fs::read(path)
        .map_err(|error| SymbolFailure::io(format!("cannot read {}: {error}", path.display())))?;
    let text = decode_source_text(path, source)?;
    let line_text = text
        .lines()
        .nth(line)
        .ok_or_else(|| SymbolFailure::input(format!("--at line {line} is outside the source")))?;
    let characters = line_text.char_indices().collect::<Vec<_>>();
    if column > characters.len() {
        return Err(SymbolFailure::input(format!(
            "--at column {column} is outside source line {line}"
        )));
    }
    let byte = characters
        .get(column)
        .map_or(line_text.len(), |(byte, _)| *byte);
    let mut start = byte;
    let mut end = byte;
    if end == line_text.len()
        || !line_text[end..]
            .chars()
            .next()
            .is_some_and(is_identifier_char)
    {
        start = line_text[..byte]
            .char_indices()
            .next_back()
            .filter(|(_, character)| is_identifier_char(*character))
            .map_or(byte, |(offset, _)| offset);
        end = byte;
    }
    while start > 0 {
        let Some((offset, character)) = line_text[..start].char_indices().next_back() else {
            break;
        };
        if !is_identifier_char(character) {
            break;
        }
        start = offset;
    }
    while end < line_text.len() {
        let Some(character) = line_text[end..].chars().next() else {
            break;
        };
        if !is_identifier_char(character) {
            break;
        }
        end += character.len_utf8();
    }
    if start == end {
        return Err(SymbolFailure::input(format!(
            "--at does not point to an identifier at {line}:{column}"
        )));
    }
    Ok((
        qualified_identifier(line_text, start, end),
        SourcePosition {
            line,
            column: line_text[..start].chars().count(),
        },
    ))
}

fn qualified_identifier(line: &str, start: usize, end: usize) -> String {
    let mut parts = vec![line[start..end].to_owned()];
    let mut cursor = start;
    loop {
        let prefix = line[..cursor].trim_end();
        let Some(owner) = prefix.strip_suffix("::") else {
            break;
        };
        let owner = owner.trim_end();
        let owner_end = owner.len();
        let mut owner_start = owner_end;
        while owner_start > 0 {
            let Some((offset, character)) = owner[..owner_start].char_indices().next_back() else {
                break;
            };
            if !is_identifier_char(character) {
                break;
            }
            owner_start = offset;
        }
        if owner_start == owner_end {
            break;
        }
        parts.push(owner[owner_start..owner_end].to_owned());
        cursor = owner_start;
    }
    parts.reverse();
    parts.join("::")
}

fn is_identifier_char(character: char) -> bool {
    character == '_' || character.is_alphanumeric() || !character.is_ascii()
}

fn resolve_rg(
    explicit: Option<&Path>,
    cwd: &Path,
    environment: &SystemEngineEnvironment,
) -> Result<PathBuf, SymbolFailure> {
    if let Some(path) = explicit {
        return canonical_engine(path, cwd, "ripgrep");
    }
    environment
        .find_on_path("rg")
        .ok_or_else(|| SymbolFailure::engine("ripgrep was not found on PATH"))
}

fn resolve_ast_grep(
    explicit: Option<&Path>,
    cwd: &Path,
    environment: &SystemEngineEnvironment,
) -> Result<PathBuf, SymbolFailure> {
    let loaded = load_standard_config(cwd).map_err(|error| {
        SymbolFailure::new(
            i32::from(error.wrapper_exit_code()),
            format!("cannot load srcq configuration: {error}"),
        )
    })?;
    let options = ExplicitOptions {
        engine: explicit.map(Path::to_path_buf),
        ..ExplicitOptions::default()
    };
    let settings = resolve_settings(&options, &loaded.stack, cwd);
    discover_engine(settings.engine.as_ref(), cwd, environment)
        .map(|engine| engine.path)
        .map_err(|error| SymbolFailure::engine(error.to_string()))
}

fn canonical_engine(path: &Path, cwd: &Path, name: &str) -> Result<PathBuf, SymbolFailure> {
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        cwd.join(path)
    };
    let canonical = fs::canonicalize(&path).map_err(|error| {
        SymbolFailure::engine(format!(
            "configured {name} engine cannot be resolved: {}: {error}",
            path.display()
        ))
    })?;
    if !canonical.is_file() {
        return Err(SymbolFailure::engine(format!(
            "configured {name} engine is not a file: {}",
            canonical.display()
        )));
    }
    Ok(canonical)
}

fn find_candidate_files(
    rg: &Path,
    target: &str,
    roots: &[PathBuf],
    universe: &SourceUniverse,
    language: language::LanguageCapability,
    deadline: QueryDeadline,
) -> Result<Vec<PathBuf>, SymbolFailure> {
    let search_target = target.rsplit("::").next().unwrap_or(target);
    let mut paths = Vec::new();
    for batch in path_batches(roots, WINDOWS_BATCH_CHARS) {
        let mut request = ProcessRequest::new(rg, &universe.cwd);
        let glob = language::source_glob(language.key).ok_or_else(|| {
            SymbolFailure::input(format!(
                "language {} has no source-file mapping",
                language.key
            ))
        })?;
        request.args = [
            "--files-with-matches",
            "--null",
            "--color=never",
            "--hidden",
            "--max-count=1",
            "--fixed-strings",
            "--word-regexp",
            &format!("--glob={glob}"),
            "--",
            search_target,
        ]
        .into_iter()
        .map(OsString::from)
        .chain(batch.iter().map(|root| root.as_os_str().to_owned()))
        .collect();
        request.forward_stderr = false;
        request.max_stdout_bytes = Some(MAX_RG_STDOUT_BYTES);
        request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
        let outcome = run_budgeted(request, deadline, "ripgrep candidate scan")?;
        let code = outcome.exit_code();
        if code == 1 {
            continue;
        }
        if code != 0 {
            return Err(engine_exit_failure(
                "ripgrep",
                code,
                &outcome.output.read_stderr(),
            ));
        }
        let bytes = outcome
            .output
            .read_stdout()
            .map_err(|error| SymbolFailure::io(format!("cannot read ripgrep output: {error}")))?;
        let text = std::str::from_utf8(&bytes)
            .map_err(|_| SymbolFailure::conversion("ripgrep returned non-UTF-8 file paths"))?;
        paths.extend(
            text.split('\0')
                .filter(|value| !value.is_empty())
                .filter_map(|value| {
                    let path = PathBuf::from(value);
                    let path = if path.is_absolute() {
                        path
                    } else {
                        universe.cwd.join(path)
                    };
                    let canonical = fs::canonicalize(path).ok()?;
                    (!universe.is_excluded(&canonical)).then_some(canonical)
                }),
        );
    }
    paths.sort_by_key(|path| normalized_key(path));
    paths.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    Ok(paths)
}

fn scan_candidates(
    ast_grep: &Path,
    target: &str,
    files: &[PathBuf],
    universe: &SourceUniverse,
    language: language::LanguageCapability,
    deadline: QueryDeadline,
) -> Result<Vec<DefinitionCandidate>, SymbolFailure> {
    if language.key != "cpp" {
        return scan_outline_candidates(ast_grep, target, files, universe, language, deadline);
    }
    let direct_rules = cpp::inline_rules(target, false);
    let direct = run_ast_scan(ast_grep, target, files, universe, &direct_rules, deadline)?;
    if !target.contains("::")
        && !direct.is_empty()
        && !direct
            .iter()
            .any(|candidate| !candidate.qualified_name.contains("::"))
    {
        return Ok(direct);
    }
    let mut scope_files = if target.contains("::") {
        files.to_vec()
    } else {
        direct
            .iter()
            .map(|candidate| candidate.file.clone())
            .collect::<Vec<_>>()
    };
    scope_files.sort_by_key(|path| normalized_key(path));
    scope_files.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    let scoped_rules = cpp::inline_rules(target, true);
    let scoped = run_ast_scan(
        ast_grep,
        target,
        &scope_files,
        universe,
        &scoped_rules,
        deadline,
    )?;
    if scoped.is_empty() {
        Ok(direct)
    } else {
        Ok(scoped)
    }
}

fn scan_outline_candidates(
    ast_grep: &Path,
    target: &str,
    files: &[PathBuf],
    universe: &SourceUniverse,
    language: language::LanguageCapability,
    deadline: QueryDeadline,
) -> Result<Vec<DefinitionCandidate>, SymbolFailure> {
    let mut candidates = Vec::new();
    for batch in path_batches(files, WINDOWS_BATCH_CHARS) {
        let mut request = ProcessRequest::new(ast_grep, &universe.cwd);
        request.args = [
            OsString::from("outline"),
            OsString::from("--lang"),
            OsString::from(language.ast_grep),
            OsString::from("--items"),
            OsString::from("structure"),
            OsString::from("--view"),
            OsString::from("expanded"),
            OsString::from("--json=stream"),
        ]
        .into_iter()
        .chain(batch.iter().map(|path| path.as_os_str().to_owned()))
        .collect();
        request.forward_stderr = false;
        request.max_stdout_bytes = Some(MAX_AST_STDOUT_BYTES);
        request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
        let outcome = run_budgeted(request, deadline, "ast-grep outline")?;
        let code = outcome.exit_code();
        if !matches!(code, 0 | 1) {
            return Err(engine_exit_failure(
                "ast-grep",
                code,
                &outcome.output.read_stderr(),
            ));
        }
        let bytes = outcome
            .output
            .read_stdout()
            .map_err(|error| SymbolFailure::io(format!("cannot read ast-grep outline: {error}")))?;
        candidates.extend(
            generic::parse_outline_stream(&bytes, target, universe, language.key)
                .map_err(SymbolFailure::conversion)?,
        );
    }
    Ok(candidates)
}

fn run_ast_scan(
    ast_grep: &Path,
    target: &str,
    files: &[PathBuf],
    universe: &SourceUniverse,
    inline_rules: &str,
    deadline: QueryDeadline,
) -> Result<Vec<DefinitionCandidate>, SymbolFailure> {
    let mut candidates = Vec::new();
    for batch in path_batches(files, WINDOWS_BATCH_CHARS) {
        let mut request = ProcessRequest::new(ast_grep, &universe.cwd);
        request.args = [
            OsString::from("scan"),
            OsString::from("--inline-rules"),
            OsString::from(inline_rules),
            OsString::from("--json=stream"),
        ]
        .into_iter()
        .chain(batch.iter().map(|path| path.as_os_str().to_owned()))
        .collect();
        request.forward_stderr = false;
        request.max_stdout_bytes = Some(MAX_AST_STDOUT_BYTES);
        request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
        let outcome = run_budgeted(request, deadline, "ast-grep candidate scan")?;
        let code = outcome.exit_code();
        if code != 0 {
            return Err(engine_exit_failure(
                "ast-grep",
                code,
                &outcome.output.read_stderr(),
            ));
        }
        let bytes = outcome
            .output
            .read_stdout()
            .map_err(|error| SymbolFailure::io(format!("cannot read ast-grep output: {error}")))?;
        candidates.extend(
            cpp::parse_scan_stream(&bytes, &universe.cwd, target, universe)
                .map_err(SymbolFailure::conversion)?,
        );
    }
    candidates.extend(scan_cpp_headers(
        ast_grep,
        target,
        files,
        universe,
        inline_rules,
        deadline,
    )?);
    Ok(candidates)
}

fn scan_cpp_headers(
    ast_grep: &Path,
    target: &str,
    files: &[PathBuf],
    universe: &SourceUniverse,
    inline_rules: &str,
    deadline: QueryDeadline,
) -> Result<Vec<DefinitionCandidate>, SymbolFailure> {
    let mut candidates = Vec::new();
    for file in files
        .iter()
        .filter(|file| language::requires_explicit_parse("cpp", file))
    {
        let bytes = run_cpp_header_inline_scan(
            ast_grep,
            file,
            inline_rules,
            universe,
            deadline,
            "ast-grep C++ header definition scan",
        )?;
        candidates.extend(
            cpp::parse_header_scan_stream(&bytes, &universe.cwd, file, target, universe)
                .map_err(SymbolFailure::conversion)?,
        );
    }
    Ok(candidates)
}

fn run_cpp_header_inline_scan(
    ast_grep: &Path,
    file: &Path,
    inline_rules: &str,
    universe: &SourceUniverse,
    deadline: QueryDeadline,
    operation: &'static str,
) -> Result<Vec<u8>, SymbolFailure> {
    let metadata = fs::metadata(file).map_err(|error| {
        SymbolFailure::io(format!(
            "cannot inspect C++ header {}: {error}",
            file.display()
        ))
    })?;
    if metadata.len() > MAX_SOURCE_POSITION_BYTES {
        return Err(SymbolFailure::input(format!(
            "C++ header exceeds the {} byte relation-query limit: {}",
            MAX_SOURCE_POSITION_BYTES,
            file.display()
        )));
    }
    let source = fs::read(file).map_err(|error| {
        SymbolFailure::io(format!(
            "cannot read C++ header {}: {error}",
            file.display()
        ))
    })?;
    let source = normalize_ast_stdin_source(file, source)?;
    let mut request = ProcessRequest::new(ast_grep, &universe.cwd);
    request.args = [
        OsString::from("scan"),
        OsString::from("--stdin"),
        OsString::from("--inline-rules"),
        OsString::from(inline_rules),
        OsString::from("--json=stream"),
    ]
    .into_iter()
    .collect();
    request.stdin = StdinMode::Bytes(source);
    request.forward_stderr = false;
    request.max_stdout_bytes = Some(MAX_AST_STDOUT_BYTES);
    request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
    let outcome = run_budgeted(request, deadline, operation)?;
    let code = outcome.exit_code();
    if code != 0 {
        return Err(engine_exit_failure(
            "ast-grep",
            code,
            &outcome.output.read_stderr(),
        ));
    }
    outcome
        .output
        .read_stdout()
        .map_err(|error| SymbolFailure::io(format!("cannot read ast-grep output: {error}")))
}

fn normalize_ast_stdin_source(file: &Path, source: Vec<u8>) -> Result<Vec<u8>, SymbolFailure> {
    decode_source_text(file, source).map(String::into_bytes)
}

fn decode_source_text(file: &Path, source: Vec<u8>) -> Result<String, SymbolFailure> {
    if let Some(bytes) = source.strip_prefix(&[0xff, 0xfe]) {
        if bytes.len() % 2 != 0 {
            return Err(SymbolFailure::input(format!(
                "UTF-16LE source has an incomplete code unit: {}",
                file.display()
            )));
        }
        let units = bytes
            .chunks_exact(2)
            .map(|chunk| u16::from_le_bytes([chunk[0], chunk[1]]))
            .collect::<Vec<_>>();
        String::from_utf16(&units).map_err(|error| {
            SymbolFailure::input(format!(
                "cannot decode UTF-16LE source {}: {error}",
                file.display()
            ))
        })
    } else if let Some(bytes) = source.strip_prefix(&[0xfe, 0xff]) {
        if bytes.len() % 2 != 0 {
            return Err(SymbolFailure::input(format!(
                "UTF-16BE source has an incomplete code unit: {}",
                file.display()
            )));
        }
        let units = bytes
            .chunks_exact(2)
            .map(|chunk| u16::from_be_bytes([chunk[0], chunk[1]]))
            .collect::<Vec<_>>();
        String::from_utf16(&units).map_err(|error| {
            SymbolFailure::input(format!(
                "cannot decode UTF-16BE source {}: {error}",
                file.display()
            ))
        })
    } else if source.contains(&0) {
        Err(SymbolFailure::input(format!(
            "source contains NUL bytes; UTF-16 text requires a BOM: {}",
            file.display()
        )))
    } else {
        match String::from_utf8(source) {
            Ok(text) => Ok(text),
            Err(error) => {
                let bytes = error.into_bytes();
                let (decoded, had_errors) = encoding_rs::GBK.decode_without_bom_handling(&bytes);
                if had_errors || decoded.contains('\0') {
                    Err(SymbolFailure::input(format!(
                        "source is not valid UTF-8, BOM-marked UTF-16, or Windows GBK text: {}",
                        file.display()
                    )))
                } else {
                    Ok(decoded.into_owned())
                }
            }
        }
    }
}

fn scan_occurrences(
    ast_grep: &Path,
    target: &str,
    files: &[PathBuf],
    universe: &SourceUniverse,
    language: language::LanguageCapability,
    deadline: QueryDeadline,
) -> Result<Vec<OccurrenceCandidate>, SymbolFailure> {
    let inline_rules = if language.key == "cpp" {
        cpp::occurrence_rules(target)
    } else {
        generic::occurrence_rules(
            language.ast_grep,
            target,
            language::occurrence_kinds(language.key).ok_or_else(|| {
                SymbolFailure::input(format!(
                    "language {} has no occurrence adapter",
                    language.key
                ))
            })?,
        )
    };
    let mut occurrences = Vec::new();
    for batch in path_batches(files, WINDOWS_BATCH_CHARS) {
        let mut request = ProcessRequest::new(ast_grep, &universe.cwd);
        request.args = [
            OsString::from("scan"),
            OsString::from("--inline-rules"),
            OsString::from(&inline_rules),
            OsString::from("--json=stream"),
        ]
        .into_iter()
        .chain(batch.iter().map(|path| path.as_os_str().to_owned()))
        .collect();
        request.forward_stderr = false;
        request.max_stdout_bytes = Some(MAX_AST_STDOUT_BYTES);
        request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
        let outcome = run_budgeted(request, deadline, "ast-grep occurrence scan")?;
        let code = outcome.exit_code();
        if code != 0 {
            return Err(engine_exit_failure(
                "ast-grep",
                code,
                &outcome.output.read_stderr(),
            ));
        }
        let bytes = outcome
            .output
            .read_stdout()
            .map_err(|error| SymbolFailure::io(format!("cannot read ast-grep output: {error}")))?;
        occurrences.extend(
            cpp::parse_occurrence_stream(&bytes, &universe.cwd, universe)
                .map_err(SymbolFailure::conversion)?,
        );
    }
    if language.key == "cpp" {
        for file in files
            .iter()
            .filter(|file| language::requires_explicit_parse(language.key, file))
        {
            let bytes = run_cpp_header_inline_scan(
                ast_grep,
                file,
                &inline_rules,
                universe,
                deadline,
                "ast-grep C++ header occurrence scan",
            )?;
            occurrences.extend(
                cpp::parse_header_occurrence_stream(&bytes, &universe.cwd, file, universe)
                    .map_err(SymbolFailure::conversion)?,
            );
        }
    }
    occurrences.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    occurrences.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file)
            && left.range.start == right.range.start
    });
    Ok(occurrences)
}

fn scan_containing_functions(
    ast_grep: &Path,
    target: &str,
    files: &[PathBuf],
    universe: &SourceUniverse,
    language: language::LanguageCapability,
    deadline: QueryDeadline,
) -> Result<Vec<FunctionOwnerCandidate>, SymbolFailure> {
    let inline_rules = if language.key == "cpp" {
        cpp::containing_function_rules(target)
    } else if language.key == "go" {
        go::containing_function_rules(language.ast_grep, target)
    } else if language.key == "javascript" {
        javascript::containing_function_rules(language.ast_grep, target)
    } else if language.key == "python" {
        python::containing_function_rules(language.ast_grep, target)
    } else if language.key == "rust" {
        rust_lang::containing_function_rules(language.ast_grep, target)
    } else if matches!(language.key, "typescript" | "tsx") {
        typescript::containing_function_rules(language.ast_grep, target)
    } else {
        generic::containing_function_rules(
            language.ast_grep,
            target,
            language::function_kinds(language.key).ok_or_else(|| {
                SymbolFailure::input(format!(
                    "language {} has no function-owner adapter",
                    language.key
                ))
            })?,
        )
    };
    let mut owners = Vec::new();
    for batch in path_batches(files, WINDOWS_BATCH_CHARS) {
        let mut request = ProcessRequest::new(ast_grep, &universe.cwd);
        request.args = [
            OsString::from("scan"),
            OsString::from("--inline-rules"),
            OsString::from(&inline_rules),
            OsString::from("--json=stream"),
        ]
        .into_iter()
        .chain(batch.iter().map(|path| path.as_os_str().to_owned()))
        .collect();
        request.forward_stderr = false;
        request.max_stdout_bytes = Some(MAX_AST_STDOUT_BYTES);
        request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
        let outcome = run_budgeted(request, deadline, "ast-grep containing-function scan")?;
        let code = outcome.exit_code();
        if code != 0 {
            return Err(engine_exit_failure(
                "ast-grep",
                code,
                &outcome.output.read_stderr(),
            ));
        }
        let bytes = outcome
            .output
            .read_stdout()
            .map_err(|error| SymbolFailure::io(format!("cannot read ast-grep output: {error}")))?;
        owners.extend(if language.key == "cpp" {
            cpp::parse_function_owner_stream(&bytes, &universe.cwd, universe)
                .map_err(SymbolFailure::conversion)?
        } else if language.key == "go" {
            go::parse_function_owner_stream(&bytes, &universe.cwd)
                .map_err(SymbolFailure::conversion)?
        } else if language.key == "javascript" {
            javascript::parse_function_owner_stream(&bytes, &universe.cwd)
                .map_err(SymbolFailure::conversion)?
        } else if language.key == "python" {
            python::parse_function_owner_stream(&bytes, &universe.cwd)
                .map_err(SymbolFailure::conversion)?
        } else if language.key == "rust" {
            rust_lang::parse_function_owner_stream(&bytes, &universe.cwd)
                .map_err(SymbolFailure::conversion)?
        } else if matches!(language.key, "typescript" | "tsx") {
            typescript::parse_function_owner_stream(&bytes, &universe.cwd)
                .map_err(SymbolFailure::conversion)?
        } else {
            generic::parse_function_owner_stream(&bytes, &universe.cwd, language.key)
                .map_err(SymbolFailure::conversion)?
        });
    }
    if language.key == "cpp" {
        for file in files
            .iter()
            .filter(|file| language::requires_explicit_parse(language.key, file))
        {
            let bytes = run_cpp_header_inline_scan(
                ast_grep,
                file,
                &inline_rules,
                universe,
                deadline,
                "ast-grep C++ header owner scan",
            )?;
            owners.extend(
                cpp::parse_header_function_owner_stream(&bytes, &universe.cwd, file, universe)
                    .map_err(SymbolFailure::conversion)?,
            );
        }
    }
    owners.sort_by(|left, right| {
        normalized_key(&left.file)
            .cmp(&normalized_key(&right.file))
            .then_with(|| left.range.start.line.cmp(&right.range.start.line))
            .then_with(|| left.range.start.column.cmp(&right.range.start.column))
    });
    owners.dedup_by(|left, right| {
        normalized_key(&left.file) == normalized_key(&right.file) && left.range == right.range
    });
    Ok(owners)
}

fn calls_for_definition(
    definition: &DefinitionCandidate,
    context: &CallQueryContext<'_>,
    cache: &mut BTreeMap<String, cpp::CallScan>,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<Vec<DirectCallCandidate>, SymbolFailure> {
    let key = normalized_key(&definition.file);
    if !cache.contains_key(&key) {
        cache_call_scans(std::slice::from_ref(&definition.file), context, cache)?;
    }
    let scan = cache
        .get(&key)
        .ok_or_else(|| SymbolFailure::conversion("call scan cache lost its result"))?;
    let mut calls = scan
        .calls
        .iter()
        .filter(|call| {
            normalized_key(&call.file) == normalized_key(&definition.file)
                && source_range_contains(definition.range, call.range)
        })
        .cloned()
        .collect::<Vec<_>>();
    if context.language.key == "cpp" {
        cpp::annotate_explicit_member_types(&mut calls, scan, definition);
    } else if context.language.key == "csharp" {
        csharp::annotate_explicit_member_types(&mut calls, scan, definition);
        annotate_csharp_cross_file_types(
            &mut calls,
            scan,
            definition,
            context.command,
            context.universe,
            context.deadline,
            resolution_cache,
        )?;
    } else if matches!(
        context.language.key,
        "go" | "javascript" | "python" | "rust" | "typescript" | "tsx"
    ) {
        typed::annotate_explicit_member_types(context.language.key, &mut calls, scan, definition);
    }
    Ok(calls)
}

fn call_for_definition_at(
    definition: &DefinitionCandidate,
    position: SourcePosition,
    context: &CallQueryContext<'_>,
    cache: &mut BTreeMap<String, cpp::CallScan>,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<Option<DirectCallCandidate>, SymbolFailure> {
    let key = normalized_key(&definition.file);
    if !cache.contains_key(&key) {
        cache_call_scans(std::slice::from_ref(&definition.file), context, cache)?;
    }
    let scan = cache
        .get(&key)
        .ok_or_else(|| SymbolFailure::conversion("call scan cache lost its result"))?;
    let Some(call) = scan
        .calls
        .iter()
        .filter(|call| {
            normalized_key(&call.file) == key
                && source_range_contains(definition.range, call.range)
                && position_in_range(position, call.range)
        })
        .min_by_key(|call| source_range_size(call.range))
        .cloned()
    else {
        return Ok(None);
    };
    let mut calls = vec![call];
    if context.language.key == "cpp" {
        cpp::annotate_explicit_member_types(&mut calls, scan, definition);
    } else if context.language.key == "csharp" {
        csharp::annotate_explicit_member_types(&mut calls, scan, definition);
        annotate_csharp_cross_file_types(
            &mut calls,
            scan,
            definition,
            context.command,
            context.universe,
            context.deadline,
            resolution_cache,
        )?;
    } else if matches!(
        context.language.key,
        "go" | "javascript" | "python" | "rust" | "typescript" | "tsx"
    ) {
        typed::annotate_explicit_member_types(context.language.key, &mut calls, scan, definition);
    }
    Ok(calls.pop())
}

fn cache_call_scans(
    files: &[PathBuf],
    context: &CallQueryContext<'_>,
    cache: &mut BTreeMap<String, cpp::CallScan>,
) -> Result<(), SymbolFailure> {
    let mut missing = files
        .iter()
        .filter(|file| !cache.contains_key(&normalized_key(file)))
        .cloned()
        .collect::<Vec<_>>();
    missing.sort_by_key(|file| normalized_key(file));
    missing.dedup_by(|left, right| normalized_key(left) == normalized_key(right));
    if missing.is_empty() {
        return Ok(());
    }
    let rules = match context.language.key {
        "cpp" => cpp::call_rules().to_owned(),
        "csharp" => csharp::call_rules(),
        "go" => go::call_rules(context.language.ast_grep),
        "javascript" => javascript::call_rules(context.language.ast_grep),
        "python" => python::call_rules(context.language.ast_grep),
        "rust" => rust_lang::call_rules(context.language.ast_grep),
        "typescript" | "tsx" => typescript::call_rules(context.language.ast_grep),
        _ => generic::call_rules(
            context.language.ast_grep,
            language::call_kinds(context.language.key).ok_or_else(|| {
                SymbolFailure::input(format!(
                    "language {} has no direct-call adapter",
                    context.language.key
                ))
            })?,
        ),
    };
    let mut combined = cpp::CallScan::default();
    for batch in path_batches(&missing, WINDOWS_BATCH_CHARS) {
        let mut request = ProcessRequest::new(context.ast_grep, &context.universe.cwd);
        request.args = [
            OsString::from("scan"),
            OsString::from("--inline-rules"),
            OsString::from(&rules),
            OsString::from("--json=stream"),
        ]
        .into_iter()
        .chain(batch.iter().map(|path| path.as_os_str().to_owned()))
        .collect();
        request.forward_stderr = false;
        request.max_stdout_bytes = Some(MAX_AST_STDOUT_BYTES);
        request.max_stderr_bytes = Some(MAX_ENGINE_STDERR_BYTES);
        let outcome = run_budgeted(request, context.deadline, "ast-grep call scan")?;
        let code = outcome.exit_code();
        if code != 0 {
            return Err(engine_exit_failure(
                "ast-grep",
                code,
                &outcome.output.read_stderr(),
            ));
        }
        let bytes = outcome
            .output
            .read_stdout()
            .map_err(|error| SymbolFailure::io(format!("cannot read ast-grep output: {error}")))?;
        let mut scan = match context.language.key {
            "cpp" => cpp::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            "csharp" => csharp::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            "go" => go::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            "javascript" => javascript::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            "python" => python::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            "rust" => rust_lang::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            "typescript" | "tsx" => typescript::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
            _ => generic::parse_call_stream(&bytes, &context.universe.cwd)
                .map_err(SymbolFailure::conversion)?,
        };
        combined.calls.append(&mut scan.calls);
        combined.bindings.append(&mut scan.bindings);
        combined
            .unresolved_bindings
            .append(&mut scan.unresolved_bindings);
        combined.type_scopes.append(&mut scan.type_scopes);
        combined.lexical_scopes.append(&mut scan.lexical_scopes);
    }
    if context.language.key == "cpp" {
        for file in missing
            .iter()
            .filter(|file| language::requires_explicit_parse(context.language.key, file))
        {
            let bytes = run_cpp_header_inline_scan(
                context.ast_grep,
                file,
                &rules,
                context.universe,
                context.deadline,
                "ast-grep C++ header call scan",
            )?;
            let key = normalized_key(file);
            combined
                .calls
                .retain(|candidate| normalized_key(&candidate.file) != key);
            combined
                .bindings
                .retain(|candidate| normalized_key(&candidate.file) != key);
            combined
                .type_scopes
                .retain(|candidate| normalized_key(&candidate.file) != key);
            let mut scan = cpp::parse_header_call_stream(&bytes, &context.universe.cwd, file)
                .map_err(SymbolFailure::conversion)?;
            combined.calls.append(&mut scan.calls);
            combined.bindings.append(&mut scan.bindings);
            combined.type_scopes.append(&mut scan.type_scopes);
        }
    }
    for file in missing {
        let key = normalized_key(&file);
        cache.insert(
            key.clone(),
            cpp::CallScan {
                calls: combined
                    .calls
                    .iter()
                    .filter(|candidate| normalized_key(&candidate.file) == key)
                    .cloned()
                    .collect(),
                bindings: combined
                    .bindings
                    .iter()
                    .filter(|candidate| normalized_key(&candidate.file) == key)
                    .cloned()
                    .collect(),
                unresolved_bindings: combined
                    .unresolved_bindings
                    .iter()
                    .filter(|candidate| normalized_key(&candidate.file) == key)
                    .cloned()
                    .collect(),
                type_scopes: combined
                    .type_scopes
                    .iter()
                    .filter(|candidate| normalized_key(&candidate.file) == key)
                    .cloned()
                    .collect(),
                lexical_scopes: combined
                    .lexical_scopes
                    .iter()
                    .filter(|candidate| normalized_key(&candidate.file) == key)
                    .cloned()
                    .collect(),
            },
        );
    }
    Ok(())
}

fn annotate_csharp_cross_file_types(
    calls: &mut [DirectCallCandidate],
    scan: &cpp::CallScan,
    definition: &DefinitionCandidate,
    command: &SymbolCommand,
    universe: &SourceUniverse,
    deadline: QueryDeadline,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<(), SymbolFailure> {
    let lexical_owner = csharp::containing_type_name(scan, definition);
    let qualified_owner = definition
        .qualified_name
        .rsplit_once("::")
        .map(|(owner, _)| owner.to_owned())
        .or_else(|| lexical_owner.clone());
    for call in calls {
        if call.dispatch != "member-candidate" {
            continue;
        }
        let Some(receiver) = call.receiver.as_deref() else {
            continue;
        };
        let Some(chain) = csharp::receiver_chain(receiver) else {
            continue;
        };
        let Some(first) = chain.first() else {
            continue;
        };
        if first == "base" {
            continue;
        }
        let mut current_type =
            csharp::explicit_receiver_type(scan, definition, first, call.range.start);
        if current_type.is_none() && first == "this" {
            current_type = qualified_owner.clone();
        }
        if current_type.is_none() {
            if let Some(owner) = qualified_owner.as_deref() {
                current_type = resolve_csharp_member_type(
                    owner,
                    first,
                    command,
                    universe,
                    &call.file,
                    deadline,
                    resolution_cache,
                )?;
            }
        }
        if current_type.is_none() {
            current_type = resolve_csharp_source_type(
                first,
                command,
                universe,
                &call.file,
                deadline,
                resolution_cache,
            )?;
        }
        for member in chain.iter().skip(1) {
            let Some(owner) = current_type.as_deref() else {
                break;
            };
            current_type = resolve_csharp_member_type(
                owner,
                member,
                command,
                universe,
                &call.file,
                deadline,
                resolution_cache,
            )?;
        }
        if let Some(type_name) = current_type {
            csharp::qualify_call(call, &type_name);
        }
    }
    Ok(())
}

fn resolve_csharp_member_type(
    owner: &str,
    member: &str,
    command: &SymbolCommand,
    universe: &SourceUniverse,
    local_file: &Path,
    deadline: QueryDeadline,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<Option<String>, SymbolFailure> {
    let target = format!("{owner}::{member}");
    let cache_anchor = universe
        .compile_files
        .first()
        .map_or(local_file, PathBuf::as_path);
    let resolution = resolve_callee(
        &target,
        command,
        universe,
        cache_anchor,
        deadline,
        resolution_cache,
    )?;
    Ok(resolution.definition.as_ref().and_then(|definition| {
        matches!(definition.symbol_kind.as_str(), "field" | "property")
            .then(|| csharp::definition_member_type(&definition.signature))
            .flatten()
    }))
}

fn resolve_csharp_source_type(
    target: &str,
    command: &SymbolCommand,
    universe: &SourceUniverse,
    local_file: &Path,
    deadline: QueryDeadline,
    resolution_cache: &mut BTreeMap<String, CalleeResolution>,
) -> Result<Option<String>, SymbolFailure> {
    let resolution = resolve_callee(
        target,
        command,
        universe,
        local_file,
        deadline,
        resolution_cache,
    )?;
    Ok(resolution.definition.and_then(|definition| {
        matches!(
            definition.symbol_kind.as_str(),
            "type" | "class" | "struct" | "record" | "interface" | "enum"
        )
        .then_some(definition.qualified_name)
    }))
}

fn source_range_contains(outer: SourceRange, inner: SourceRange) -> bool {
    (outer.start.line, outer.start.column) <= (inner.start.line, inner.start.column)
        && (inner.end.line, inner.end.column) <= (outer.end.line, outer.end.column)
}

fn source_document<'a>(
    path: &Path,
    documents: &'a mut BTreeMap<String, SourceDocument>,
) -> Result<&'a SourceDocument, SymbolFailure> {
    let key = normalized_key(path);
    if !documents.contains_key(&key) {
        let source = fs::read(path).map_err(|error| {
            SymbolFailure::io(format!("cannot read source {}: {error}", path.display()))
        })?;
        let text = decode_source_text(path, source)?;
        let mut line_offsets = vec![0];
        line_offsets.extend(
            text.bytes()
                .enumerate()
                .filter_map(|(index, byte)| (byte == b'\n').then_some(index + 1)),
        );
        documents.insert(key.clone(), SourceDocument { text, line_offsets });
    }
    documents
        .get(&key)
        .ok_or_else(|| SymbolFailure::io("source document cache lost an inserted entry"))
}

fn reference_role(document: &SourceDocument, end: SourcePosition) -> &'static str {
    let Some(line_start) = document.line_offsets.get(end.line).copied() else {
        return "reference";
    };
    let offset = line_start
        .saturating_add(end.column)
        .min(document.text.len());
    let suffix = document.text[offset..].trim_start();
    if suffix.starts_with('(') || template_call_suffix(suffix) {
        return "call";
    }
    if suffix.starts_with("++")
        || suffix.starts_with("--")
        || suffix.starts_with("+=")
        || suffix.starts_with("-=")
        || suffix.starts_with("*=")
        || suffix.starts_with("/=")
        || suffix.starts_with("%=")
        || suffix
            .strip_prefix('=')
            .is_some_and(|tail| !tail.starts_with('='))
    {
        return "write";
    }
    "reference"
}

fn template_call_suffix(text: &str) -> bool {
    if !text.starts_with('<') {
        return false;
    }
    let mut depth = 0_usize;
    for (index, byte) in text.bytes().enumerate() {
        match byte {
            b'<' => depth += 1,
            b'>' => {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    return text[index + 1..].trim_start().starts_with('(');
                }
            }
            _ => {}
        }
    }
    false
}

fn path_batches(paths: &[PathBuf], budget: usize) -> Vec<&[PathBuf]> {
    let mut batches = Vec::new();
    let mut start = 0_usize;
    let mut used = 0_usize;
    for (index, path) in paths.iter().enumerate() {
        let cost = path.as_os_str().to_string_lossy().chars().count() + 3;
        if index > start && used + cost > budget {
            batches.push(&paths[start..index]);
            start = index;
            used = 0;
        }
        used += cost;
    }
    if start < paths.len() {
        batches.push(&paths[start..]);
    }
    batches
}

fn engine_exit_failure(
    engine: &str,
    code: i32,
    stderr: &Result<Vec<u8>, io::Error>,
) -> SymbolFailure {
    let detail = stderr
        .as_ref()
        .ok()
        .and_then(|bytes| std::str::from_utf8(bytes).ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("no diagnostic output");
    SymbolFailure::new(126, format!("{engine} exited with {code}: {detail}"))
}

fn render_references_model(
    command: &SymbolCommand,
    outcome: &ReferencesOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let identity = if outcome.position_matched {
        "position-candidate"
    } else {
        match outcome.definition_total {
            0 => "semantic-unknown",
            1 => definition_identity_evidence(command),
            _ => "ambiguous",
        }
    };
    let mut output = format!(
        "references {} identity={} evidence=lexical-candidate\n",
        outcome.reference_total, identity
    );
    let mut grouped = BTreeMap::<String, Vec<&ReferenceCandidate>>::new();
    for reference in &outcome.references {
        grouped
            .entry(outcome.universe.render_path(&reference.file))
            .or_default()
            .push(reference);
    }
    let mut shown = 0_usize;
    'files: for (path, references) in grouped {
        let heading = format!("{path}\n");
        if crate::query_gateway::model_text_cost(&output)
            + crate::query_gateway::model_text_cost(&heading)
            > command.model_token_budget
            && shown > 0
        {
            break;
        }
        output.push_str(&heading);
        for reference in references {
            let line = format!(
                "  {}:{} {}\n",
                reference.position.line + 1,
                reference.position.column + 1,
                reference.role
            );
            if crate::query_gateway::model_text_cost(&output)
                + crate::query_gateway::model_text_cost(&line)
                > command.model_token_budget
                && shown > 0
            {
                break 'files;
            }
            output.push_str(&line);
            shown += 1;
        }
    }
    if outcome.reference_total > shown {
        output.push_str(&format!(
            "... {} more (raise --limit or --model-token-budget)\n",
            outcome.reference_total - shown
        ));
    }
    if outcome.universe.status != scope::ScopeStatus::Resolved
        || outcome.universe.roots.len() > 1
        || !outcome.scan_complete
        || outcome.reference_total == 0
    {
        let remaining = outcome
            .universe
            .roots
            .len()
            .saturating_sub(outcome.scanned_roots.len());
        output.push_str(&format!(
            "scope {} scan={} roots={}/+{} files={}\n",
            outcome.universe.status.as_str(),
            if outcome.scan_complete {
                "complete"
            } else {
                "prioritized"
            },
            outcome.scanned_roots.len(),
            remaining,
            outcome.candidate_files
        ));
        output.push_str(&source_manifest_model_line(&outcome.universe));
        for issue in &outcome.universe.issues {
            let path = issue
                .path
                .as_deref()
                .map(|path| outcome.universe.render_path(path))
                .unwrap_or_else(|| "-".to_owned());
            output.push_str(&format!(
                "!scope {} {} {}\n",
                issue.code, path, issue.detail
            ));
        }
    }
    Ok(output.into_bytes())
}

fn render_calls_bundle_model(
    command: &SymbolCommand,
    outcome: &CallsBundleOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let shared_root = outcome
        .incoming
        .root
        .as_ref()
        .or(outcome.outgoing.root.as_ref());
    let Some(root) = shared_root else {
        let identity = if outcome.incoming.root_definition_total == 0 {
            "semantic-unknown"
        } else {
            "ambiguous"
        };
        let mut output = format!(
            "calls both unavailable target={} identity={} definitions={}\n",
            outcome.target, identity, outcome.incoming.root_definition_total
        );
        append_calls_bundle_scope(outcome, &mut output);
        return Ok(output.into_bytes());
    };
    let root_definition = root
        .definition
        .as_ref()
        .ok_or_else(|| SymbolFailure::conversion("call-tree root lost its definition"))?;
    let mut output = format!(
        "calls both depth={} max_nodes={}/branch\n{} {}\n",
        command.depth,
        command.max_nodes,
        root.name,
        locator(&outcome.universe, root_definition)
    );
    render_calls_bundle_branch(command, &outcome.incoming, &mut output)?;
    render_calls_bundle_branch(command, &outcome.outgoing, &mut output)?;
    append_calls_bundle_scope(outcome, &mut output);
    Ok(output.into_bytes())
}

fn render_calls_bundle_branch(
    command: &SymbolCommand,
    outcome: &CallsOutcome,
    output: &mut String,
) -> Result<(), SymbolFailure> {
    let root = outcome
        .root
        .as_ref()
        .ok_or_else(|| SymbolFailure::conversion("call-tree branch lost its root"))?;
    let evidence = if outcome.direction == "incoming" {
        "lexical-candidate"
    } else {
        root.status.as_str()
    };
    output.push_str(&format!(
        "{} nodes={} scan={} evidence={}\n",
        outcome.direction,
        outcome.nodes,
        if outcome.scan_complete {
            "complete"
        } else {
            "prioritized"
        },
        evidence
    ));
    let mut budget_truncated = false;
    render_call_children(
        root,
        "",
        root.definition
            .as_ref()
            .map(|definition| definition.file.as_path()),
        output,
        command.model_token_budget,
        &outcome.universe,
        &mut budget_truncated,
    );
    if outcome.time_limited {
        output.push_str(&format!(
            "@cut direction={} reason=time-budget result=partial recovery=use-depth-1-or-query-a-returned-child-position\n",
            outcome.direction
        ));
    } else if outcome.truncated {
        output.push_str(&format!(
            "... {} node budget reached (raise --max-nodes)\n",
            outcome.direction
        ));
    } else if budget_truncated {
        output.push_str(&format!(
            "... {} output budget reached (raise --model-token-budget)\n",
            outcome.direction
        ));
    }
    Ok(())
}

fn append_calls_bundle_scope(outcome: &CallsBundleOutcome, output: &mut String) {
    if outcome.universe.status == scope::ScopeStatus::Resolved
        && outcome.incoming.scan_complete
        && outcome.outgoing.scan_complete
    {
        return;
    }
    output.push_str(&format!(
        "scope {} incoming={} outgoing={}\n",
        outcome.universe.status.as_str(),
        if outcome.incoming.scan_complete {
            "complete"
        } else {
            "prioritized"
        },
        if outcome.outgoing.scan_complete {
            "complete"
        } else {
            "prioritized"
        }
    ));
    output.push_str(&source_manifest_model_line(&outcome.universe));
    for issue in &outcome.universe.issues {
        let path = issue
            .path
            .as_deref()
            .map(|path| outcome.universe.render_path(path))
            .unwrap_or_else(|| "-".to_owned());
        output.push_str(&format!(
            "!scope {} {} {}\n",
            issue.code, path, issue.detail
        ));
    }
}

fn render_calls_model(
    command: &SymbolCommand,
    outcome: &CallsOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let Some(root) = &outcome.root else {
        let identity = if outcome.root_definition_total == 0 {
            "semantic-unknown"
        } else {
            "ambiguous"
        };
        let mut output = format!(
            "calls unavailable target={} identity={} definitions={}\n",
            outcome.target, identity, outcome.root_definition_total
        );
        if outcome.universe.source_manifest.is_some() {
            output.push_str(&format!(
                "scope {} scan={}\n",
                outcome.universe.status.as_str(),
                if outcome.scan_complete {
                    "complete"
                } else {
                    "prioritized"
                }
            ));
            output.push_str(&source_manifest_model_line(&outcome.universe));
            for issue in &outcome.universe.issues {
                let path = issue
                    .path
                    .as_deref()
                    .map(|path| outcome.universe.render_path(path))
                    .unwrap_or_else(|| "-".to_owned());
                output.push_str(&format!(
                    "!scope {} {} {}\n",
                    issue.code, path, issue.detail
                ));
            }
        }
        return Ok(output.into_bytes());
    };
    let root_definition = root
        .definition
        .as_ref()
        .ok_or_else(|| SymbolFailure::conversion("call-tree root lost its definition"))?;
    let mut output = format!(
        "calls {} depth={} nodes={} evidence={}\n{} {}\n",
        outcome.direction,
        command.depth,
        outcome.nodes,
        if outcome.direction == "incoming" {
            "lexical-candidate"
        } else {
            &root.status
        },
        root.name,
        locator(&outcome.universe, root_definition)
    );
    let mut budget_truncated = false;
    render_call_children(
        root,
        "",
        Some(&root_definition.file),
        &mut output,
        command.model_token_budget,
        &outcome.universe,
        &mut budget_truncated,
    );
    if outcome.time_limited {
        output.push_str(
            "@cut reason=time-budget result=partial recovery=use-depth-1-or-query-a-returned-child-position\n",
        );
    } else if outcome.truncated {
        output.push_str("... node budget reached (raise --max-nodes)\n");
    } else if budget_truncated {
        output.push_str("... output budget reached (raise --model-token-budget)\n");
    }
    if outcome.universe.status != scope::ScopeStatus::Resolved || !outcome.scan_complete {
        output.push_str(&format!(
            "scope {} scan={}\n",
            outcome.universe.status.as_str(),
            if outcome.scan_complete {
                "complete"
            } else {
                "prioritized"
            }
        ));
        if outcome.universe.source_manifest.is_some() {
            output.push_str(&source_manifest_model_line(&outcome.universe));
            for issue in &outcome.universe.issues {
                let path = issue
                    .path
                    .as_deref()
                    .map(|path| outcome.universe.render_path(path))
                    .unwrap_or_else(|| "-".to_owned());
                output.push_str(&format!(
                    "!scope {} {} {}\n",
                    issue.code, path, issue.detail
                ));
            }
        }
    }
    Ok(output.into_bytes())
}

fn render_call_children(
    node: &CallTreeNode,
    prefix: &str,
    visible_parent_file: Option<&Path>,
    output: &mut String,
    budget: usize,
    universe: &SourceUniverse,
    budget_truncated: &mut bool,
) {
    let shared_child_file = node
        .children
        .iter()
        .filter_map(|child| child.call_file.as_deref())
        .try_fold(None::<&Path>, |shared, file| match shared {
            None => Some(Some(file)),
            Some(existing) if normalized_key(existing) == normalized_key(file) => {
                Some(Some(existing))
            }
            Some(_) => None,
        })
        .flatten();
    let mut shared_path_visible = shared_child_file.is_some_and(|shared| {
        visible_parent_file.is_some_and(|parent| normalized_key(parent) == normalized_key(shared))
    });
    for (index, child) in node.children.iter().enumerate() {
        if *budget_truncated {
            return;
        }
        let last = index + 1 == node.children.len();
        let connector = if last { "└─" } else { "├─" };
        let location = child
            .call_file
            .as_deref()
            .zip(child.call_position)
            .map(|(file, position)| {
                if shared_child_file
                    .is_some_and(|shared| normalized_key(shared) == normalized_key(file))
                    && shared_path_visible
                {
                    format!(" :{}:{}", position.line + 1, position.column + 1)
                } else {
                    shared_path_visible = shared_child_file.is_some();
                    format!(
                        " {}:{}:{}",
                        universe.render_path(file),
                        position.line + 1,
                        position.column + 1
                    )
                }
            })
            .unwrap_or_default();
        let evidence = if child.status == child.dispatch {
            child.status.clone()
        } else {
            format!("{};{}", child.status, child.dispatch)
        };
        let receiver = match (&child.receiver, &child.receiver_type) {
            (Some(receiver), Some(type_name)) => format!(" receiver={receiver}:{type_name}"),
            (Some(receiver), None) => format!(" receiver={receiver}:unknown"),
            _ => String::new(),
        };
        let line = format!(
            "{prefix}{connector} {} [{evidence}{receiver}]{}\n",
            child.qualified_name.as_deref().unwrap_or(&child.name),
            location,
        );
        if crate::query_gateway::model_text_cost(output)
            + crate::query_gateway::model_text_cost(&line)
            > budget
        {
            *budget_truncated = true;
            return;
        }
        output.push_str(&line);
        let child_prefix = format!("{prefix}{} ", if last { " " } else { "│" });
        render_call_children(
            child,
            &child_prefix,
            child.call_file.as_deref(),
            output,
            budget,
            universe,
            budget_truncated,
        );
    }
}

fn render_calls_machine(
    command: &SymbolCommand,
    outcome: &CallsOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let evidence = if outcome.direction == "incoming" {
        "lexical-candidate"
    } else {
        outcome
            .root
            .as_ref()
            .map_or("semantic-unknown", |root| root.status.as_str())
    };
    let scope = with_source_manifest_scope(
        json!({
            "status": outcome.universe.status.as_str(),
            "candidate_scan": if outcome.scan_complete { "complete" } else { "prioritized" },
            "roots": outcome.universe.roots.iter().map(|root| json!({
                "alias": root.alias,
                "path": slash_path(&root.path),
                "source": root.source,
            })).collect::<Vec<_>>(),
        }),
        &outcome.universe,
    );
    let document = json!({
        "schema": "srcq.symbol.calls/v1",
        "query": {"target": outcome.target, "language": command.language, "direction": outcome.direction},
        "scope": scope,
        "root_definition_total": outcome.root_definition_total,
        "nodes": outcome.nodes,
        "truncated": outcome.truncated,
        "time_limited": outcome.time_limited,
        "root": outcome.root.as_ref().map(|root| machine_call_node(root, &outcome.universe)),
        "evidence": evidence,
    });
    serde_json::to_vec(&document)
        .map(|mut bytes| {
            bytes.push(b'\n');
            bytes
        })
        .map_err(|error| {
            SymbolFailure::conversion(format!("cannot encode machine output: {error}"))
        })
}

fn calls_branch_document(outcome: &CallsOutcome) -> Value {
    let evidence = if outcome.direction == "incoming" {
        "lexical-candidate"
    } else {
        outcome
            .root
            .as_ref()
            .map_or("semantic-unknown", |root| root.status.as_str())
    };
    let exit_code = if outcome.time_limited {
        124
    } else if outcome.root.is_some() {
        0
    } else {
        1
    };
    json!({
        "direction": outcome.direction,
        "nodes": outcome.nodes,
        "truncated": outcome.truncated,
        "time_limited": outcome.time_limited,
        "scan": if outcome.scan_complete { "complete" } else { "prioritized" },
        "exit_code": exit_code,
        "evidence": evidence,
        "children": outcome.root.as_ref().map(|root| root.children.iter()
            .map(|child| machine_call_node(child, &outcome.universe))
            .collect::<Vec<_>>()),
    })
}

fn render_calls_bundle_machine(
    command: &SymbolCommand,
    outcome: &CallsBundleOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let shared_root = outcome
        .incoming
        .root
        .as_ref()
        .or(outcome.outgoing.root.as_ref());
    let mut root = shared_root.map(|root| machine_call_node(root, &outcome.universe));
    if let Some(fields) = root.as_mut().and_then(Value::as_object_mut) {
        fields.remove("children");
    }
    let scope = with_source_manifest_scope(
        json!({
            "status": outcome.universe.status.as_str(),
            "roots": outcome.universe.roots.iter().map(|root| json!({
                "alias": root.alias,
                "path": slash_path(&root.path),
                "source": root.source,
            })).collect::<Vec<_>>(),
        }),
        &outcome.universe,
    );
    let document = json!({
        "schema": "srcq.symbol.calls/bundle/v1",
        "query": {
            "target": outcome.target,
            "language": command.language,
            "direction": "both",
            "depth": command.depth,
            "max_nodes": command.max_nodes,
            "max_nodes_scope": "per-branch",
            "model_token_budget": command.model_token_budget,
            "model_token_budget_scope": "bundle",
            "time_budget_ms": command.time_budget_ms,
            "time_budget_scope": "bundle",
        },
        "scope": scope,
        "root_definition_total": outcome.incoming.root_definition_total,
        "root": root,
        "branches": {
            "incoming": calls_branch_document(&outcome.incoming),
            "outgoing": calls_branch_document(&outcome.outgoing),
        },
    });
    serde_json::to_vec(&document)
        .map(|mut bytes| {
            bytes.push(b'\n');
            bytes
        })
        .map_err(|error| {
            SymbolFailure::conversion(format!("cannot encode machine output: {error}"))
        })
}

fn machine_call_node(node: &CallTreeNode, universe: &SourceUniverse) -> Value {
    json!({
        "name": node.name,
        "qualified_name": node.qualified_name,
        "dispatch": node.dispatch,
        "status": node.status,
        "receiver": node.receiver,
        "receiver_type": node.receiver_type,
        "call": node.call_file.as_deref().zip(node.call_position).map(|(file, position)| json!({
            "path": universe.render_path(file),
            "line": position.line,
            "column": position.column,
        })),
        "definition": node.definition.as_ref().map(|definition| json!({
            "path": universe.render_path(&definition.file),
            "line": definition.name_position.line,
            "column": definition.name_position.column,
            "qualified_name": definition.qualified_name,
            "signature": definition.signature,
        })),
        "children": node.children.iter().map(|child| machine_call_node(child, universe)).collect::<Vec<_>>(),
    })
}

fn render_references_machine(
    command: &SymbolCommand,
    outcome: &ReferencesOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let references = outcome
        .references
        .iter()
        .map(|reference| {
            json!({
                "root": reference.root_alias,
                "path": outcome.universe.render_path(&reference.file),
                "absolute_path": slash_path(&reference.file),
                "position": {
                    "line": reference.position.line,
                    "column": reference.position.column,
                },
                "role": reference.role,
                "evidence": "lexical-candidate",
            })
        })
        .collect::<Vec<_>>();
    let definitions = outcome
        .definitions
        .iter()
        .filter(|candidate| candidate.role == DefinitionRole::Definition)
        .map(|candidate| {
            json!({
                "root": candidate.root_alias,
                "path": outcome.universe.render_path(&candidate.file),
                "position": {
                    "line": candidate.name_position.line,
                    "column": candidate.name_position.column,
                },
                "qualified_name": candidate.qualified_name,
                "symbol_kind": candidate.symbol_kind,
                "signature": candidate.signature,
            })
        })
        .collect::<Vec<_>>();
    let roots = outcome
        .universe
        .roots
        .iter()
        .map(|root| {
            json!({
                "alias": root.alias,
                "path": slash_path(&root.path),
                "source": root.source,
                "scanned": outcome.scanned_roots.contains(&normalized_key(&root.path)),
            })
        })
        .collect::<Vec<_>>();
    let issues = outcome
        .universe
        .issues
        .iter()
        .map(|issue| {
            json!({
                "code": issue.code,
                "path": issue.path.as_deref().map(slash_path),
                "detail": issue.detail,
            })
        })
        .collect::<Vec<_>>();
    let scope = with_source_manifest_scope(
        json!({
            "status": outcome.universe.status.as_str(),
            "candidate_scan": if outcome.scan_complete { "complete" } else { "prioritized" },
            "roots": roots,
            "issues": issues,
        }),
        &outcome.universe,
    );
    let document = json!({
        "schema": "srcq.symbol.references/v1",
        "query": {"target": outcome.target, "language": command.language},
        "scope": scope,
        "candidate_files": outcome.candidate_files,
        "definition_total": outcome.definition_total,
        "reference_total": outcome.reference_total,
        "identity": if outcome.position_matched {
            "position-candidate"
        } else {
            match outcome.definition_total {
                0 => "semantic-unknown",
                1 => definition_identity_evidence(command),
                _ => "ambiguous",
            }
        },
        "truncated": outcome.reference_total > outcome.references.len(),
        "definitions": definitions,
        "references": references,
        "evidence": "lexical-candidate",
    });
    serde_json::to_vec(&document)
        .map(|mut bytes| {
            bytes.push(b'\n');
            bytes
        })
        .map_err(|error| {
            SymbolFailure::conversion(format!("cannot encode machine output: {error}"))
        })
}

#[allow(clippy::comparison_chain)]
fn render_model(command: &SymbolCommand, outcome: &QueryOutcome) -> Result<Vec<u8>, SymbolFailure> {
    let mut output = String::new();
    if outcome.definition_total == 1 {
        let candidate = &outcome.definitions[0];
        output.push_str(&format!(
            "definition-candidate {} {} {}{}\n",
            candidate.symbol_kind,
            candidate.qualified_name,
            locator(&outcome.universe, candidate),
            if command.language == "cpp" {
                ""
            } else {
                " evidence=outline-candidate"
            }
        ));
        output.push_str(&format!("signature {}\n", candidate.signature));
        let body = should_emit_body(command, &output, candidate);
        if body {
            output.push_str(&format!("```{}\n", command.language));
            output.push_str(candidate.text.trim_end());
            output.push_str("\n```\n");
        } else {
            output.push_str(&format!(
                "@body srcq symbol definition {}{} --only-root {} --body full\n",
                quote_model_arg(&outcome.target),
                if command.language == "cpp" {
                    String::new()
                } else {
                    format!(" --language {}", command.language)
                },
                quote_model_arg(&slash_path(&candidate.file))
            ));
        }
    } else if outcome.definition_total > 1 {
        output.push_str(&format!(
            "definition-candidates {}{}\n",
            outcome.definition_total,
            if command.language == "cpp" {
                ""
            } else {
                " evidence=outline-candidate"
            }
        ));
        let mut shown = 0_usize;
        for candidate in &outcome.definitions {
            let line = format!(
                "- {} {} {} | {}\n",
                candidate.symbol_kind,
                candidate.qualified_name,
                locator(&outcome.universe, candidate),
                candidate.signature
            );
            if crate::query_gateway::model_text_cost(&output)
                + crate::query_gateway::model_text_cost(&line)
                > command.model_token_budget
            {
                break;
            }
            output.push_str(&line);
            shown += 1;
        }
        if outcome.definition_total > shown {
            output.push_str(&format!(
                "... {} more (raise --limit or --model-token-budget)\n",
                outcome.definition_total - shown
            ));
        }
    } else if command.language == "cpp" {
        output.push_str("definition-candidate none\n");
    } else {
        output.push_str(
            "definition-candidate none evidence=outline-candidate coverage=structural-items\n",
        );
    }
    if outcome.declaration_total > 0 {
        output.push_str(&format!("declarations {}\n", outcome.declaration_total));
        let mut shown = 0_usize;
        for candidate in &outcome.declarations {
            let line = format!(
                "- {} {} {} | {}\n",
                candidate.symbol_kind,
                candidate.qualified_name,
                locator(&outcome.universe, candidate),
                candidate.signature
            );
            if crate::query_gateway::model_text_cost(&output)
                + crate::query_gateway::model_text_cost(&line)
                > command.model_token_budget
            {
                break;
            }
            output.push_str(&line);
            shown += 1;
        }
        if outcome.declaration_total > shown {
            output.push_str(&format!(
                "... {} more (raise --limit or --model-token-budget)\n",
                outcome.declaration_total - shown
            ));
        }
    }
    if outcome.universe.status != scope::ScopeStatus::Resolved
        || !outcome.scan_complete
        || outcome.universe.roots.len() > 1
    {
        let mut visible_aliases = outcome
            .universe
            .roots
            .iter()
            .filter(|root| outcome.scanned_roots.contains(&normalized_key(&root.path)))
            .map(|root| root.alias.clone())
            .collect::<BTreeSet<_>>();
        visible_aliases.extend(
            outcome
                .definitions
                .iter()
                .chain(&outcome.declarations)
                .filter_map(|candidate| candidate.root_alias.clone()),
        );
        let visible_count = visible_aliases.len();
        let shown = visible_aliases.into_iter().take(3).collect::<Vec<_>>();
        let remaining = outcome.universe.roots.len().saturating_sub(visible_count);
        let roots = if remaining == 0 {
            shown.join(",")
        } else if shown.is_empty() {
            format!("0/+{remaining}")
        } else {
            format!("{},+{remaining}", shown.join(","))
        };
        output.push_str(&format!(
            "scope {} scan={} roots={} files={} evidence={}\n",
            outcome.universe.status.as_str(),
            if outcome.scan_complete {
                "complete"
            } else {
                "prioritized"
            },
            roots,
            outcome.candidate_files,
            definition_evidence(command)
        ));
        output.push_str(&source_manifest_model_line(&outcome.universe));
        for issue in &outcome.universe.issues {
            let path = issue
                .path
                .as_deref()
                .map(|path| outcome.universe.render_path(path))
                .unwrap_or_else(|| "-".to_owned());
            output.push_str(&format!(
                "!scope {} {} {}\n",
                issue.code, path, issue.detail
            ));
        }
    }
    Ok(output.into_bytes())
}

fn should_emit_body(
    command: &SymbolCommand,
    prefix: &str,
    candidate: &DefinitionCandidate,
) -> bool {
    match command.body {
        SymbolBodyMode::Full => true,
        SymbolBodyMode::None => false,
        SymbolBodyMode::Auto => {
            crate::query_gateway::model_text_cost(prefix)
                + crate::query_gateway::model_text_cost(&candidate.text)
                + 8
                <= command.model_token_budget
        }
    }
}

fn render_machine(
    command: &SymbolCommand,
    outcome: &QueryOutcome,
) -> Result<Vec<u8>, SymbolFailure> {
    let roots = outcome
        .universe
        .roots
        .iter()
        .map(|root| {
            json!({
                "alias": root.alias,
                "path": slash_path(&root.path),
                "source": root.source,
                "scanned": outcome.scanned_roots.contains(&normalized_key(&root.path)),
            })
        })
        .collect::<Vec<_>>();
    let issues = outcome
        .universe
        .issues
        .iter()
        .map(|issue| {
            json!({
                "code": issue.code,
                "path": issue.path.as_deref().map(slash_path),
                "detail": issue.detail,
            })
        })
        .collect::<Vec<_>>();
    let definitions = outcome
        .definitions
        .iter()
        .map(|candidate| {
            machine_candidate(&outcome.universe, candidate, definition_evidence(command))
        })
        .collect::<Vec<_>>();
    let declarations = outcome
        .declarations
        .iter()
        .map(|candidate| {
            machine_candidate(&outcome.universe, candidate, definition_evidence(command))
        })
        .collect::<Vec<_>>();
    let scope = with_source_manifest_scope(
        json!({
            "status": outcome.universe.status.as_str(),
            "project_root": slash_path(&outcome.universe.project_root),
            "roots": roots,
            "excludes": outcome.universe.excludes.iter().map(|path| slash_path(path)).collect::<Vec<_>>(),
            "issues": issues,
            "compile_file_hints": outcome.universe.compile_files.len(),
            "compile_directory_hints": outcome.universe.compile_directories.len(),
        }),
        &outcome.universe,
    );
    let document = json!({
        "schema": "srcq.symbol.definition/v1",
        "query": {
            "target": outcome.target,
            "language": command.language,
        },
        "scope": scope,
        "candidate_files": outcome.candidate_files,
        "candidate_scan": if outcome.scan_complete { "complete" } else { "prioritized" },
        "definition_total": outcome.definition_total,
        "declaration_total": outcome.declaration_total,
        "position_match": outcome.position_matched,
        "truncated": outcome.definition_total > outcome.definitions.len()
            || outcome.declaration_total > outcome.declarations.len(),
        "definitions": definitions,
        "declarations": declarations,
        "evidence": definition_evidence(command),
    });
    serde_json::to_vec(&document)
        .map(|mut bytes| {
            bytes.push(b'\n');
            bytes
        })
        .map_err(|error| {
            SymbolFailure::conversion(format!("cannot encode machine output: {error}"))
        })
}

fn machine_candidate(
    universe: &SourceUniverse,
    candidate: &DefinitionCandidate,
    evidence: &str,
) -> Value {
    json!({
        "root": candidate.root_alias,
        "path": universe.render_path(&candidate.file),
        "absolute_path": slash_path(&candidate.file),
        "range": {
            "start": {"line": candidate.range.start.line, "column": candidate.range.start.column},
            "end": {"line": candidate.range.end.line, "column": candidate.range.end.column},
        },
        "name_position": {
            "line": candidate.name_position.line,
            "column": candidate.name_position.column,
        },
        "qualified_name": candidate.qualified_name,
        "symbol_kind": candidate.symbol_kind,
        "role": candidate.role.as_str(),
        "signature": candidate.signature,
        "text": candidate.text,
        "ast_kind": candidate.ast_kind,
        "evidence": evidence,
    })
}

fn definition_evidence(command: &SymbolCommand) -> &'static str {
    if command.language == "cpp" {
        "syntax-direct"
    } else {
        "outline-candidate"
    }
}

fn definition_identity_evidence(command: &SymbolCommand) -> &'static str {
    if command.language == "cpp" {
        "qualified-candidate"
    } else {
        "outline-candidate"
    }
}

fn locator(universe: &SourceUniverse, candidate: &DefinitionCandidate) -> String {
    format!(
        "{}:{}:{}",
        universe.render_path(&candidate.file),
        candidate.name_position.line + 1,
        candidate.name_position.column + 1
    )
}

fn quote_model_arg(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

fn write_stdout(bytes: Vec<u8>) -> Result<(), SymbolFailure> {
    let mut stdout = io::stdout().lock();
    stdout
        .write_all(&bytes)
        .and_then(|()| stdout.flush())
        .map_err(|error| SymbolFailure::io(format!("cannot write output: {error}")))
}

#[cfg(test)]
mod tests {
    use super::{decode_source_text, parse_source_position, path_batches};
    use std::path::{Path, PathBuf};

    #[test]
    fn windows_source_position_splits_from_the_right() {
        assert_eq!(
            parse_source_position(r#"D:\work\source.cpp:12:7"#).expect("position"),
            (r#"D:\work\source.cpp"#, 12, 7)
        );
    }

    #[test]
    fn path_batches_preserve_every_path_once() {
        let paths = [PathBuf::from("one.cpp"), PathBuf::from("two.cpp")];
        let batches = path_batches(&paths, 12);
        assert_eq!(batches.iter().map(|batch| batch.len()).sum::<usize>(), 2);
    }

    #[test]
    fn source_decoding_supports_common_windows_project_text() {
        let utf16 = [0xff, 0xfe, b'i', 0, b'n', 0, b't', 0, b';', 0];
        assert_eq!(
            decode_source_text(Path::new("utf16.h"), utf16.to_vec()).expect("BOM-marked UTF-16"),
            "int;"
        );
        assert!(decode_source_text(
            Path::new("bomless-utf16.h"),
            [b'i', 0, b'n', 0, b't', 0].to_vec()
        )
        .is_err());
        assert_eq!(
            decode_source_text(Path::new("legacy-code-page.h"), b"// \xd6\xd0\n".to_vec())
                .expect("GBK source"),
            "// 中\n"
        );
    }
}
