#![forbid(unsafe_code)]

#[cfg(not(windows))]
compile_error!("srcq is maintained and supported only on Windows");

pub mod cache;
pub mod defaults_output;
pub mod diagnostics;
pub mod processor;
pub mod query_gateway;
pub mod symbol_query;

use std::ffi::{OsStr, OsString};
use std::fmt;
use std::path::PathBuf;

use clap::builder::{OsStringValueParser, PossibleValuesParser};
use clap::{Arg, ArgAction, ArgMatches, Command};
use srcq_core::invocation::{
    ExplicitOptions, NativeInvocation, OutputFormat, Profile, WrapperCommand,
};

const NATIVE_DELIMITER: &str = "--";

#[must_use]
pub fn command() -> Command {
    let build = srcq_core::build_info();
    Command::new("srcq")
        .version(build.package_version)
        .about("Low-context source query gateway")
        .arg_required_else_help(true)
        .disable_help_subcommand(true)
        .subcommand(wrapper_subcommand(
            "exec",
            "Execute ast-grep and convert its output",
        ))
        .subcommand(wrapper_subcommand(
            "defaults",
            "Preview wrapper defaults without discovering or starting ast-grep",
        ))
        .subcommand(cache_subcommand())
        .subcommand(process_subcommand())
        .subcommand(direct_gateway_subcommand("rg", "ripgrep"))
        .subcommand(direct_gateway_subcommand("fd", "fd"))
        .subcommand(direct_gateway_subcommand("scc", "scc"))
        .subcommand(symbol_subcommand())
        .subcommand(
            Command::new("more")
                .about("Continue a model query from its short handle")
                .arg(Arg::new("handle").value_name("HANDLE").required(true)),
        )
        .subcommand(query_subcommand())
        .subcommand(
            Command::new("schema")
                .about("Print the bounded srcq configuration schema")
                .arg(
                    Arg::new("subject")
                        .value_name("SUBJECT")
                        .default_value("config")
                        .value_parser(PossibleValuesParser::new(["config"])),
                ),
        )
        .subcommand(Command::new("capabilities").about("Print bounded wrapper capabilities"))
        .subcommand(
            Command::new("doctor")
                .about("Diagnose config, engine, cache, YAML, and protocol limits without scanning")
                .arg(output_arg())
                .arg(
                    Arg::new("engine")
                        .long("engine")
                        .value_name("PATH")
                        .value_parser(clap::value_parser!(PathBuf)),
                )
                .arg(
                    Arg::new("cwd")
                        .long("cwd")
                        .value_name("PATH")
                        .value_parser(clap::value_parser!(PathBuf)),
                ),
        )
        .after_help(
            "Operational syntax: srcq <exec|defaults> [wrapper options] -- <ast-grep argv...>\nInspection syntax: srcq <schema|capabilities|doctor> ...\nCache syntax: srcq cache <get|query|info|remove|gc> ...\nProcess syntax: srcq process <validate|select|filter|count|group|containing|group-locations|sort|dedupe|merge|to-jsonl|from-jsonl> ...\nSource syntax: srcq <rg|fd|scc> <native argv...>\nSymbol syntax: srcq symbol definition [NAME|--at PATH:LINE:COLUMN] ...\nModel continuation: srcq more <HANDLE>\nExplicit query controls: srcq query <rg|fd|scc> <exec|defaults|doctor> [options] -- <native argv...>",
        )
}

fn symbol_subcommand() -> Command {
    Command::new("symbol")
        .about("Query bounded source symbol relations")
        .subcommand_required(true)
        .subcommand(
            Command::new("capabilities")
                .about("List explicit relation capability for every ast-grep language")
                .arg(output_arg()),
        )
        .subcommand(symbol_relation_subcommand(
            "definition",
            "Find source definition candidates by name or source position",
            true,
        ))
        .subcommand(symbol_relation_subcommand(
            "references",
            "Find bounded source reference candidates by name or source position",
            false,
        ))
        .subcommand(
            symbol_relation_subcommand("calls", "Build a bounded source call tree", false)
                .arg(
                    Arg::new("depth")
                        .long("depth")
                        .value_name("N")
                        .default_value("1")
                        .value_parser(clap::value_parser!(u64).range(1..=8))
                        .help("Maximum call-tree depth"),
                )
                .arg(
                    Arg::new("direction")
                        .long("direction")
                        .value_name("DIRECTION")
                        .default_value("outgoing")
                        .value_parser(PossibleValuesParser::new(["outgoing", "incoming"]))
                        .help("Call-tree direction"),
                )
                .arg(
                    Arg::new("max-nodes")
                        .long("max-nodes")
                        .value_name("N")
                        .default_value("40")
                        .value_parser(clap::value_parser!(u64).range(1..=10000))
                        .help("Maximum call-tree nodes expanded or displayed"),
                ),
        )
}

fn symbol_relation_subcommand(
    name: &'static str,
    about: &'static str,
    include_body: bool,
) -> Command {
    let command = Command::new(name)
        .about(about)
        .arg(
            Arg::new("name")
                .value_name("NAME")
                .required_unless_present("at")
                .conflicts_with("at")
                .allow_hyphen_values(true),
        )
        .arg(
            Arg::new("at")
                .long("at")
                .value_name("PATH:LINE:COLUMN")
                .help("Resolve the zero-based source position before querying the relation"),
        )
        .arg(
            Arg::new("add-root")
                .long("add-root")
                .value_name("PATH")
                .action(ArgAction::Append)
                .value_parser(clap::value_parser!(PathBuf))
                .conflicts_with("only-root")
                .help("Add one file or directory to the automatically resolved roots"),
        )
        .arg(
            Arg::new("only-root")
                .long("only-root")
                .value_name("PATH")
                .action(ArgAction::Append)
                .value_parser(clap::value_parser!(PathBuf))
                .help("Use only the explicitly supplied files or directories"),
        )
        .arg(
            Arg::new("exclude")
                .long("exclude")
                .value_name("PATH")
                .action(ArgAction::Append)
                .value_parser(clap::value_parser!(PathBuf))
                .help("Exclude one root or subtree from the selected scope"),
        )
        .arg(
            Arg::new("cwd")
                .long("cwd")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf))
                .help("Resolve relative inputs and automatic scope from this directory"),
        )
        .arg(
            Arg::new("language")
                .long("language")
                .value_name("LANGUAGE")
                .default_value("cpp")
                .value_parser(PossibleValuesParser::new([
                    "bash",
                    "c",
                    "cpp",
                    "csharp",
                    "css",
                    "dart",
                    "elixir",
                    "go",
                    "haskell",
                    "html",
                    "java",
                    "javascript",
                    "json",
                    "kotlin",
                    "lua",
                    "nix",
                    "php",
                    "python",
                    "ruby",
                    "rust",
                    "scala",
                    "solidity",
                    "swift",
                    "tsx",
                    "typescript",
                    "yaml",
                ]))
                .help("Language adapter used for relation classification"),
        )
        .arg(output_arg())
        .arg(
            Arg::new("limit")
                .long("limit")
                .value_name("N")
                .default_value("40")
                .value_parser(clap::value_parser!(u64).range(1..=10000))
                .help("Maximum relation candidates shown"),
        )
        .arg(
            Arg::new("model-token-budget")
                .long("model-token-budget")
                .value_name("N")
                .default_value("2048")
                .value_parser(clap::value_parser!(u64).range(32..=1_000_000))
                .help("Soft estimated-token budget for model output"),
        )
        .arg(
            Arg::new("time-budget-ms")
                .long("time-budget-ms")
                .value_name("MILLISECONDS")
                .default_value("7500")
                .value_parser(clap::value_parser!(u64).range(1..=600_000))
                .help("End-to-end symbol-query scan budget; expiry reports an incomplete result"),
        )
        .arg(
            Arg::new("rg-engine")
                .long("rg-engine")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf))
                .help("Explicit ripgrep executable for diagnostics or controlled tests"),
        )
        .arg(
            Arg::new("ast-grep-engine")
                .long("ast-grep-engine")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf))
                .help("Explicit ast-grep executable for diagnostics or controlled tests"),
        );
    if include_body {
        command.arg(
            Arg::new("body")
                .long("body")
                .value_name("MODE")
                .default_value("auto")
                .value_parser(PossibleValuesParser::new(["auto", "none", "full"]))
                .help("Definition body projection"),
        )
    } else {
        command
    }
}

fn direct_gateway_subcommand(name: &'static str, engine_name: &'static str) -> Command {
    Command::new(name)
        .about(format!("Query through {engine_name} with native arguments"))
        .disable_help_flag(true)
        .arg(
            Arg::new("native")
                .value_name("NATIVE_ARGV")
                .value_parser(OsStringValueParser::new())
                .num_args(0..)
                .allow_hyphen_values(true)
                .trailing_var_arg(true),
        )
        .after_help(format!(
            "All arguments after `{name}` belong to {engine_name}. Use `srcq query {name} exec ...` only for explicit projection, machine, native, artifact, or continuation controls."
        ))
}

fn query_subcommand() -> Command {
    Command::new("query")
        .about("Explicit rg/fd/scc projection and diagnostic controls")
        .subcommand_required(true)
        .subcommand(gateway_backend_subcommand("rg", "ripgrep"))
        .subcommand(gateway_backend_subcommand("fd", "fd"))
        .subcommand(gateway_backend_subcommand("scc", "scc"))
}

fn gateway_backend_subcommand(name: &'static str, engine_name: &'static str) -> Command {
    Command::new(name)
        .about(format!("Token-safe {engine_name} gateway"))
        .subcommand_required(true)
        .subcommand(gateway_operation_subcommand("exec", name))
        .subcommand(gateway_operation_subcommand("defaults", name))
        .subcommand(
            Command::new("doctor")
                .about("Diagnose the exact native engine without searching")
                .arg(output_arg())
                .arg(gateway_engine_arg())
                .arg(gateway_cwd_arg()),
        )
        .after_help(
            "Wrapper options belong before --; native arguments belong after --.\nUse `srcq <backend> --help` for native engine help.",
        )
}

fn gateway_operation_subcommand(name: &'static str, backend: &'static str) -> Command {
    let views = match backend {
        "rg" => vec![
            "auto",
            "grouped",
            "records",
            "locations",
            "files",
            "summary",
            "lossless",
            "raw",
        ],
        "fd" => vec!["auto", "tree", "flat", "summary", "lossless", "raw"],
        "scc" => vec![
            "auto",
            "summary",
            "languages",
            "files",
            "hotspots",
            "lossless",
            "raw",
        ],
        _ => unreachable!("gateway backend is fixed by command construction"),
    };
    let native = Arg::new("native")
        .value_name("NATIVE_ARGV")
        .value_parser(OsStringValueParser::new())
        .num_args(0..)
        .allow_hyphen_values(true)
        .trailing_var_arg(true);
    Command::new(name)
        .arg(gateway_engine_arg())
        .arg(gateway_cwd_arg())
        .arg(output_arg())
        .arg(
            Arg::new("view")
                .long("view")
                .value_name("VIEW")
                .default_value("auto")
                .value_parser(PossibleValuesParser::new(views))
                .help("Result projection"),
        )
        .arg(
            Arg::new("limit")
                .long("limit")
                .visible_alias("max-items")
                .value_name("N")
                .default_value("80")
                .help("Maximum records or bounded text lines displayed in this page")
                .value_parser(clap::value_parser!(u64).range(1..=10000)),
        )
        .arg(
            Arg::new("max-text-chars")
                .long("max-text-chars")
                .visible_alias("max-line-length")
                .value_name("N")
                .default_value("240")
                .help("Maximum displayed characters per text field")
                .value_parser(clap::value_parser!(u64).range(1..=1_000_000)),
        )
        .arg(
            Arg::new("model-token-budget")
                .long("model-token-budget")
                .value_name("N")
                .default_value("2048")
                .help("Soft estimated-token budget for one model-visible page")
                .value_parser(clap::value_parser!(u64).range(32..=1_000_000)),
        )
        .arg(
            Arg::new("receipt")
                .long("receipt")
                .value_name("DETAIL")
                .default_value("auto")
                .value_parser(PossibleValuesParser::new(["auto", "full"]))
                .help("Structured result receipt detail"),
        )
        .arg(
            Arg::new("artifact-out")
                .long("artifact-out")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(Arg::new("snapshot").long("snapshot").value_name("SHA256"))
        .arg(Arg::new("after").long("after").value_name("CURSOR"))
        .arg(native)
}

fn gateway_engine_arg() -> Arg {
    Arg::new("engine")
        .long("engine")
        .value_name("PATH")
        .value_parser(clap::value_parser!(PathBuf))
}

fn gateway_cwd_arg() -> Arg {
    Arg::new("cwd")
        .long("cwd")
        .value_name("PATH")
        .value_parser(clap::value_parser!(PathBuf))
}

fn output_arg() -> Arg {
    Arg::new("output")
        .long("output")
        .value_name("FORMAT")
        .default_value("model")
        .value_parser(PossibleValuesParser::new(["model", "machine"]))
        .help("Model evidence text or stable machine output")
}

fn process_subcommand() -> Command {
    Command::new("process")
        .about("Safely process srcq YAML or verified cache results")
        .subcommand_required(true)
        .subcommand(process_source_args(
            Command::new("validate").about("Validate safe YAML and schemas"),
        ))
        .subcommand(
            process_source_args(Command::new("select").about("Select record fields")).arg(
                Arg::new("fields")
                    .long("fields")
                    .value_name("PATHS")
                    .required(true),
            ),
        )
        .subcommand(
            process_source_args(
                Command::new("filter").about("Keep records equal to one JSON value"),
            )
            .arg(
                Arg::new("field")
                    .long("field")
                    .value_name("PATH")
                    .required(true),
            )
            .arg(
                Arg::new("equals")
                    .long("equals")
                    .value_name("JSON")
                    .required(true)
                    .allow_hyphen_values(true),
            ),
        )
        .subcommand(process_source_args(
            Command::new("count").about("Count input records"),
        ))
        .subcommand(
            process_source_args(Command::new("group").about("Count records by one scalar field"))
                .arg(
                    Arg::new("field")
                        .long("field")
                        .value_name("PATH")
                        .required(true),
                ),
        )
        .subcommand(
            process_cache_args(
                Command::new("containing")
                    .about("Select the smallest cached ranges containing one 0-based position"),
            )
            .arg(
                Arg::new("file")
                    .long("file")
                    .value_name("PATH")
                    .required(true),
            )
            .arg(
                Arg::new("line")
                    .long("line")
                    .value_name("N")
                    .required(true)
                    .value_parser(clap::value_parser!(u64)),
            )
            .arg(
                Arg::new("column")
                    .long("column")
                    .value_name("N")
                    .required(true)
                    .value_parser(clap::value_parser!(u64)),
            )
            .arg(
                Arg::new("include-text")
                    .long("include-text")
                    .action(ArgAction::SetTrue),
            ),
        )
        .subcommand(
            process_cache_args(
                Command::new("group-locations")
                    .about("Group verified cached locations without repeating file paths"),
            )
            .arg(Arg::new("file").long("file").value_name("PATH"))
            .arg(
                Arg::new("offset")
                    .long("offset")
                    .value_name("N")
                    .default_value("0")
                    .value_parser(clap::value_parser!(usize)),
            )
            .arg(
                Arg::new("limit")
                    .long("limit")
                    .value_name("N")
                    .default_value("40")
                    .value_parser(clap::value_parser!(u64).range(1..=1000)),
            ),
        )
        .subcommand(
            process_source_args(
                Command::new("sort").about("Stably sort records by one scalar field"),
            )
            .arg(Arg::new("by").long("by").value_name("PATH").required(true))
            .arg(
                Arg::new("descending")
                    .long("descending")
                    .action(ArgAction::SetTrue),
            ),
        )
        .subcommand(
            process_source_args(
                Command::new("dedupe").about("Stably remove duplicate record identities"),
            )
            .arg(conflict_arg()),
        )
        .subcommand(
            Command::new("merge")
                .about("Merge explicit file/cache sources with provenance")
                .arg(
                    Arg::new("source")
                        .long("source")
                        .value_name("file=PATH|cache=ID")
                        .action(ArgAction::Append)
                        .required(true)
                        .num_args(1),
                )
                .arg(conflict_arg()),
        )
        .subcommand(process_source_args(
            Command::new("to-jsonl").about("Convert safe YAML documents to compact JSONL"),
        ))
        .subcommand(process_source_args(
            Command::new("from-jsonl").about("Convert bounded JSONL records to safe YAML"),
        ))
}

fn conflict_arg() -> Arg {
    Arg::new("on-conflict")
        .long("on-conflict")
        .value_name("POLICY")
        .default_value("error")
        .value_parser(PossibleValuesParser::new(["error", "keep-first"]))
}

fn process_source_args(command: Command) -> Command {
    command
        .arg(
            Arg::new("input")
                .long("input")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf))
                .conflicts_with("cache-id"),
        )
        .arg(
            Arg::new("cache-id")
                .long("cache-id")
                .value_name("ID")
                .conflicts_with("input"),
        )
}

fn process_cache_args(command: Command) -> Command {
    command.arg(output_arg()).arg(
        Arg::new("cache-id")
            .long("cache-id")
            .value_name("ID")
            .required(true),
    )
}

fn cache_subcommand() -> Command {
    Command::new("cache")
        .about("Retrieve and maintain committed native-result caches")
        .subcommand_required(true)
        .subcommand(
            Command::new("get")
                .about("Retrieve a complete cache, one result, or one result field")
                .arg(Arg::new("cache-id").required(true))
                .arg(
                    Arg::new("result")
                        .long("result")
                        .value_name("N")
                        .value_parser(clap::value_parser!(u64)),
                )
                .arg(
                    Arg::new("field")
                        .long("field")
                        .value_name("JSON_POINTER")
                        .requires("result"),
                ),
        )
        .subcommand(
            Command::new("query")
                .about("Filter cached results by indexed file and rule id")
                .arg(output_arg())
                .arg(Arg::new("cache-id").required(true))
                .arg(Arg::new("file").long("file").value_name("PATH"))
                .arg(Arg::new("rule-id").long("rule-id").value_name("ID"))
                .arg(
                    Arg::new("offset")
                        .long("offset")
                        .value_name("N")
                        .default_value("0")
                        .value_parser(clap::value_parser!(usize)),
                )
                .arg(
                    Arg::new("limit")
                        .long("limit")
                        .value_name("N")
                        .default_value("40")
                        .value_parser(clap::value_parser!(u64).range(1..=1000)),
                )
                .arg(
                    Arg::new("max-text-chars")
                        .long("max-text-chars")
                        .value_name("N")
                        .default_value("240")
                        .value_parser(clap::value_parser!(u64).range(1..=1_000_000)),
                ),
        )
        .subcommand(
            Command::new("info")
                .about("Show verified cache metadata")
                .arg(Arg::new("cache-id").required(true)),
        )
        .subcommand(
            Command::new("remove")
                .about("Remove one inactive cache")
                .arg(Arg::new("cache-id").required(true)),
        )
        .subcommand(Command::new("gc").about("Run TTL and quota garbage collection"))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CacheCommand {
    Get {
        cache_id: String,
        result: Option<u64>,
        field: Option<String>,
    },
    Query {
        cache_id: String,
        file: Option<String>,
        rule_id: Option<String>,
        offset: usize,
        limit: usize,
        max_text_chars: usize,
        output: OutputFormat,
    },
    Info {
        cache_id: String,
    },
    Remove {
        cache_id: String,
    },
    Gc,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CliAction {
    Native(Box<NativeInvocation>),
    Cache(CacheCommand),
    Process(ProcessCommand),
    Inspect(InspectionCommand),
    Gateway(GatewayCommand),
    Symbol(SymbolCommand),
    More(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SymbolBodyMode {
    Auto,
    None,
    Full,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SymbolOperation {
    Capabilities,
    Definition,
    References,
    Calls,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SymbolCommand {
    pub operation: SymbolOperation,
    pub name: Option<String>,
    pub at: Option<String>,
    pub add_roots: Vec<PathBuf>,
    pub only_roots: Vec<PathBuf>,
    pub excludes: Vec<PathBuf>,
    pub cwd: Option<PathBuf>,
    pub language: String,
    pub body: SymbolBodyMode,
    pub output: OutputFormat,
    pub limit: usize,
    pub model_token_budget: usize,
    pub time_budget_ms: u64,
    pub depth: usize,
    pub max_nodes: usize,
    pub direction: String,
    pub rg_engine: Option<PathBuf>,
    pub ast_grep_engine: Option<PathBuf>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GatewayBackend {
    Rg,
    Fd,
    Scc,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GatewayOperation {
    Exec,
    Defaults,
    Doctor,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GatewayCommand {
    pub backend: GatewayBackend,
    pub operation: GatewayOperation,
    pub engine: Option<PathBuf>,
    pub cwd: Option<PathBuf>,
    pub view: String,
    pub limit: usize,
    pub max_text_chars: usize,
    pub model_token_budget: usize,
    pub auto_complete: bool,
    pub output: OutputFormat,
    pub receipt: String,
    pub artifact_out: Option<PathBuf>,
    pub snapshot: Option<String>,
    pub after: Option<String>,
    pub native_argv: Vec<OsString>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InspectionCommand {
    Schema,
    Capabilities,
    Doctor {
        engine: Option<PathBuf>,
        cwd: Option<PathBuf>,
        output: OutputFormat,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProcessInput {
    Stdin,
    File(PathBuf),
    Cache(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProcessAction {
    Validate,
    Select {
        fields: String,
    },
    Filter {
        field: String,
        equals: String,
    },
    Count,
    Group {
        field: String,
    },
    Containing {
        file: String,
        line: u64,
        column: u64,
        include_text: bool,
    },
    GroupLocations {
        file: Option<String>,
        offset: usize,
        limit: usize,
    },
    Sort {
        by: String,
        descending: bool,
    },
    Dedupe {
        on_conflict: String,
    },
    Merge {
        sources: Vec<String>,
        on_conflict: String,
    },
    ToJsonl,
    FromJsonl,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessCommand {
    pub input: ProcessInput,
    pub action: ProcessAction,
    pub output: OutputFormat,
}

fn wrapper_subcommand(name: &'static str, about: &'static str) -> Command {
    Command::new(name)
        .about(about)
        .arg(
            Arg::new("engine")
                .long("engine")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(
            Arg::new("cwd")
                .long("cwd")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(output_arg())
        .arg(
            Arg::new("yaml-out")
                .long("yaml-out")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(
            Arg::new("artifact-out")
                .long("artifact-out")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(
            Arg::new("stderr-yaml")
                .long("stderr-yaml")
                .value_name("PATH")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(
            Arg::new("meta-out")
                .long("meta-out")
                .value_name("PATH")
                .help("Write bounded execution metadata for batch, TTY, or LSP execution")
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(
            Arg::new("profile")
                .long("profile")
                .value_name("PROFILE")
                .value_parser(PossibleValuesParser::new([
                    "token-safe",
                    "locations",
                    "lossless",
                    "files",
                    "custom",
                ])),
        )
        .arg(
            Arg::new("cache")
                .long("cache")
                .value_name("MODE")
                .value_parser(PossibleValuesParser::new(["auto", "on", "off"])),
        )
        .arg(
            Arg::new("fingerprint-file")
                .long("fingerprint-file")
                .value_name("PATH")
                .help("Snapshot one source file before execution for verified cache reuse")
                .action(ArgAction::Append)
                .value_parser(clap::value_parser!(PathBuf)),
        )
        .arg(
            Arg::new("max-detail-results")
                .long("max-detail-results")
                .value_name("N")
                .value_parser(clap::value_parser!(u32).range(1..)),
        )
        .arg(
            Arg::new("max-text-chars")
                .long("max-text-chars")
                .value_name("N")
                .value_parser(clap::value_parser!(u32)),
        )
        .arg(
            Arg::new("max-context-bytes")
                .long("max-context-bytes")
                .value_name("N")
                .value_parser(clap::value_parser!(u64).range(1..)),
        )
        .arg(
            Arg::new("keep-fields")
                .long("keep-fields")
                .value_name("PATHS"),
        )
        .arg(
            Arg::new("prune-fields")
                .long("prune-fields")
                .value_name("PATHS"),
        )
        .arg(
            Arg::new("no-native-defaults")
                .long("no-native-defaults")
                .action(ArgAction::SetTrue),
        )
        .arg(Arg::new("strict").long("strict").action(ArgAction::SetTrue))
}

#[derive(Debug)]
pub enum CliParseError {
    Clap(clap::Error),
    Guidance(&'static str),
    MissingDelimiter,
    EmptyNativeArgv,
    MissingProgramName,
}

impl CliParseError {
    #[must_use]
    pub fn is_display(&self) -> bool {
        matches!(
            self,
            Self::Clap(error)
                if matches!(
                    error.kind(),
                    clap::error::ErrorKind::DisplayHelp
                        | clap::error::ErrorKind::DisplayVersion
                )
        )
    }

    #[must_use]
    pub fn wrapper_exit_code(&self) -> u8 {
        if self.is_display() {
            0
        } else {
            125
        }
    }

    pub fn print(self) -> std::io::Result<()> {
        match self {
            Self::Clap(error) => error.print(),
            other => {
                eprintln!("srcq: {other}");
                Ok(())
            }
        }
    }
}

impl fmt::Display for CliParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Clap(error) => error.fmt(formatter),
            Self::Guidance(message) => formatter.write_str(message),
            Self::MissingDelimiter => formatter
                .write_str("missing required `--` delimiter before the native ast-grep arguments"),
            Self::EmptyNativeArgv => {
                formatter.write_str("native ast-grep argument list must not be empty")
            }
            Self::MissingProgramName => formatter.write_str("missing argv[0] program name"),
        }
    }
}

impl std::error::Error for CliParseError {}

pub fn parse_invocation_from(
    args: impl IntoIterator<Item = OsString>,
) -> Result<NativeInvocation, CliParseError> {
    let raw: Vec<OsString> = args.into_iter().collect();
    if raw.is_empty() {
        return Err(CliParseError::MissingProgramName);
    }

    let delimiter = raw
        .iter()
        .enumerate()
        .skip(1)
        .find_map(|(index, token)| (token == OsStr::new(NATIVE_DELIMITER)).then_some(index));
    let Some(delimiter) = delimiter else {
        return match command().try_get_matches_from(raw) {
            Err(error)
                if matches!(
                    error.kind(),
                    clap::error::ErrorKind::DisplayHelp | clap::error::ErrorKind::DisplayVersion
                ) =>
            {
                Err(CliParseError::Clap(error))
            }
            _ => Err(CliParseError::MissingDelimiter),
        };
    };
    let user_argv = raw[(delimiter + 1)..].to_vec();
    if user_argv.is_empty() {
        return Err(CliParseError::EmptyNativeArgv);
    }

    let wrapper_argv = raw[..delimiter].to_vec();
    let matches = command()
        .try_get_matches_from(wrapper_argv)
        .map_err(CliParseError::Clap)?;
    let (command, matches) = match matches.subcommand() {
        Some(("exec", matches)) => (WrapperCommand::Exec, matches),
        Some(("defaults", matches)) => (WrapperCommand::Defaults, matches),
        _ => return Err(CliParseError::MissingDelimiter),
    };

    Ok(NativeInvocation {
        command,
        explicit: explicit_options(matches),
        user_argv,
    })
}

pub fn parse_cli_from(
    args: impl IntoIterator<Item = OsString>,
) -> Result<CliAction, CliParseError> {
    let raw: Vec<OsString> = args.into_iter().collect();
    if raw.get(1).is_some_and(|value| {
        value == OsStr::new("cache")
            || value == OsStr::new("process")
            || value == OsStr::new("schema")
            || value == OsStr::new("capabilities")
            || value == OsStr::new("doctor")
            || value == OsStr::new("rg")
            || value == OsStr::new("fd")
            || value == OsStr::new("scc")
            || value == OsStr::new("symbol")
            || value == OsStr::new("more")
            || value == OsStr::new("query")
    }) {
        if matches!(raw.get(1).and_then(|value| value.to_str()), Some("query"))
            && matches!(
                raw.get(3).and_then(|value| value.to_str()),
                Some("exec" | "defaults")
            )
            && !raw
                .iter()
                .skip(4)
                .any(|value| value == OsStr::new(NATIVE_DELIMITER))
            && !raw
                .iter()
                .skip(4)
                .any(|value| value == OsStr::new("--help") || value == OsStr::new("-h"))
        {
            return Err(CliParseError::MissingDelimiter);
        }
        let matches = command()
            .try_get_matches_from(raw)
            .map_err(CliParseError::Clap)?;
        return match matches.subcommand() {
            Some(("cache", cache)) => parse_cache_command(cache).map(CliAction::Cache),
            Some(("process", process)) => parse_process_command(process).map(CliAction::Process),
            Some(("schema", _)) => Ok(CliAction::Inspect(InspectionCommand::Schema)),
            Some(("capabilities", _)) => Ok(CliAction::Inspect(InspectionCommand::Capabilities)),
            Some(("doctor", values)) => Ok(CliAction::Inspect(InspectionCommand::Doctor {
                engine: values.get_one::<PathBuf>("engine").cloned(),
                cwd: values.get_one::<PathBuf>("cwd").cloned(),
                output: parse_output(values),
            })),
            Some(("rg", values)) => Ok(CliAction::Gateway(parse_direct_gateway_command(
                GatewayBackend::Rg,
                values,
            ))),
            Some(("fd", values)) => Ok(CliAction::Gateway(parse_direct_gateway_command(
                GatewayBackend::Fd,
                values,
            ))),
            Some(("scc", values)) => Ok(CliAction::Gateway(parse_direct_gateway_command(
                GatewayBackend::Scc,
                values,
            ))),
            Some(("symbol", values)) => parse_symbol_command(values).map(CliAction::Symbol),
            Some(("more", values)) => values
                .get_one::<String>("handle")
                .cloned()
                .map(CliAction::More)
                .ok_or(CliParseError::MissingDelimiter),
            Some(("query", values)) => match values.subcommand() {
                Some(("rg", backend)) => {
                    parse_gateway_command(GatewayBackend::Rg, backend).map(CliAction::Gateway)
                }
                Some(("fd", backend)) => {
                    parse_gateway_command(GatewayBackend::Fd, backend).map(CliAction::Gateway)
                }
                Some(("scc", backend)) => {
                    parse_gateway_command(GatewayBackend::Scc, backend).map(CliAction::Gateway)
                }
                _ => Err(CliParseError::MissingDelimiter),
            },
            _ => Err(CliParseError::MissingDelimiter),
        };
    }
    if let Some(recovery) = targeted_recovery(&raw) {
        return Err(CliParseError::Guidance(recovery));
    }
    parse_invocation_from(raw).map(|invocation| CliAction::Native(Box::new(invocation)))
}

fn parse_symbol_command(matches: &ArgMatches) -> Result<SymbolCommand, CliParseError> {
    let Some((operation, values)) = matches.subcommand() else {
        return Err(CliParseError::MissingDelimiter);
    };
    let operation = match operation {
        "capabilities" => SymbolOperation::Capabilities,
        "definition" => SymbolOperation::Definition,
        "references" => SymbolOperation::References,
        "calls" => SymbolOperation::Calls,
        _ => return Err(CliParseError::MissingDelimiter),
    };
    if operation == SymbolOperation::Capabilities {
        return Ok(SymbolCommand {
            operation,
            name: None,
            at: None,
            add_roots: Vec::new(),
            only_roots: Vec::new(),
            excludes: Vec::new(),
            cwd: None,
            language: "cpp".to_owned(),
            body: SymbolBodyMode::None,
            output: parse_output(values),
            limit: 40,
            model_token_budget: 2048,
            time_budget_ms: 7_500,
            depth: 1,
            max_nodes: 40,
            direction: "outgoing".to_owned(),
            rg_engine: None,
            ast_grep_engine: None,
        });
    }
    let body = match values
        .try_get_one::<String>("body")
        .ok()
        .flatten()
        .map(String::as_str)
        .unwrap_or("auto")
    {
        "auto" => SymbolBodyMode::Auto,
        "none" => SymbolBodyMode::None,
        "full" => SymbolBodyMode::Full,
        _ => return Err(CliParseError::MissingDelimiter),
    };
    let paths = |name: &str| {
        values
            .get_many::<PathBuf>(name)
            .map(|items| items.cloned().collect())
            .unwrap_or_default()
    };
    Ok(SymbolCommand {
        operation,
        name: values.get_one::<String>("name").cloned(),
        at: values.get_one::<String>("at").cloned(),
        add_roots: paths("add-root"),
        only_roots: paths("only-root"),
        excludes: paths("exclude"),
        cwd: values.get_one::<PathBuf>("cwd").cloned(),
        language: values
            .get_one::<String>("language")
            .cloned()
            .unwrap_or_else(|| "cpp".to_owned()),
        body,
        output: parse_output(values),
        limit: values
            .get_one::<u64>("limit")
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(40),
        model_token_budget: values
            .get_one::<u64>("model-token-budget")
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(2048),
        time_budget_ms: values
            .get_one::<u64>("time-budget-ms")
            .copied()
            .unwrap_or(7_500),
        depth: values
            .try_get_one::<u64>("depth")
            .ok()
            .flatten()
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(1),
        max_nodes: values
            .try_get_one::<u64>("max-nodes")
            .ok()
            .flatten()
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(40),
        direction: values
            .try_get_one::<String>("direction")
            .ok()
            .flatten()
            .cloned()
            .unwrap_or_else(|| "outgoing".to_owned()),
        rg_engine: values.get_one::<PathBuf>("rg-engine").cloned(),
        ast_grep_engine: values.get_one::<PathBuf>("ast-grep-engine").cloned(),
    })
}

fn targeted_recovery(raw: &[OsString]) -> Option<&'static str> {
    let first = raw.get(1)?.to_str()?;
    if matches!(first, "files" | "--files") {
        return Some("use: srcq fd <fd argv...>");
    }
    if matches!(
        first,
        "run" | "scan" | "test" | "new" | "lsp" | "completions" | "--"
    ) {
        return Some("use: srcq exec -- <ast-grep argv...>");
    }
    if matches!(first, "exec" | "defaults")
        && !raw
            .iter()
            .skip(2)
            .any(|value| value == OsStr::new(NATIVE_DELIMITER))
        && !raw
            .iter()
            .skip(2)
            .any(|value| value == OsStr::new("--help") || value == OsStr::new("-h"))
    {
        return Some(if first == "exec" {
            "use: srcq exec -- <ast-grep argv...>"
        } else {
            "use: srcq defaults -- <ast-grep argv...>"
        });
    }
    None
}

fn parse_direct_gateway_command(backend: GatewayBackend, values: &ArgMatches) -> GatewayCommand {
    GatewayCommand {
        backend,
        operation: GatewayOperation::Exec,
        engine: None,
        cwd: None,
        view: "auto".to_owned(),
        limit: 80,
        max_text_chars: 240,
        model_token_budget: 2048,
        auto_complete: true,
        output: OutputFormat::Model,
        receipt: "auto".to_owned(),
        artifact_out: None,
        snapshot: None,
        after: None,
        native_argv: values
            .try_get_many::<OsString>("native")
            .ok()
            .flatten()
            .map(|items| items.cloned().collect())
            .unwrap_or_default(),
    }
}

fn parse_gateway_command(
    backend: GatewayBackend,
    matches: &ArgMatches,
) -> Result<GatewayCommand, CliParseError> {
    let Some((name, values)) = matches.subcommand() else {
        return Err(CliParseError::MissingDelimiter);
    };
    let operation = match name {
        "exec" => GatewayOperation::Exec,
        "defaults" => GatewayOperation::Defaults,
        "doctor" => GatewayOperation::Doctor,
        _ => return Err(CliParseError::MissingDelimiter),
    };
    let native_argv = values
        .try_get_many::<OsString>("native")
        .ok()
        .flatten()
        .map(|items| items.cloned().collect())
        .unwrap_or_default();
    Ok(GatewayCommand {
        backend,
        operation,
        engine: values
            .try_get_one::<PathBuf>("engine")
            .ok()
            .flatten()
            .cloned(),
        cwd: values.try_get_one::<PathBuf>("cwd").ok().flatten().cloned(),
        view: values
            .try_get_one::<String>("view")
            .ok()
            .flatten()
            .cloned()
            .unwrap_or_else(|| "auto".to_owned()),
        limit: values
            .try_get_one::<u64>("limit")
            .ok()
            .flatten()
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(80),
        max_text_chars: values
            .try_get_one::<u64>("max-text-chars")
            .ok()
            .flatten()
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(240),
        model_token_budget: values
            .try_get_one::<u64>("model-token-budget")
            .ok()
            .flatten()
            .and_then(|value| usize::try_from(*value).ok())
            .unwrap_or(2048),
        auto_complete: false,
        output: parse_output(values),
        receipt: values
            .try_get_one::<String>("receipt")
            .ok()
            .flatten()
            .cloned()
            .unwrap_or_else(|| "auto".to_owned()),
        artifact_out: values
            .try_get_one::<PathBuf>("artifact-out")
            .ok()
            .flatten()
            .cloned(),
        snapshot: values
            .try_get_one::<String>("snapshot")
            .ok()
            .flatten()
            .cloned(),
        after: values
            .try_get_one::<String>("after")
            .ok()
            .flatten()
            .cloned(),
        native_argv,
    })
}

fn parse_process_command(matches: &ArgMatches) -> Result<ProcessCommand, CliParseError> {
    let Some((name, values)) = matches.subcommand() else {
        return Err(CliParseError::MissingDelimiter);
    };
    let input = if let Some(path) = values.try_get_one::<PathBuf>("input").ok().flatten() {
        ProcessInput::File(path.clone())
    } else if let Some(cache_id) = values.try_get_one::<String>("cache-id").ok().flatten() {
        ProcessInput::Cache(cache_id.clone())
    } else {
        ProcessInput::Stdin
    };
    let required = |field: &str| {
        values
            .get_one::<String>(field)
            .cloned()
            .ok_or(CliParseError::MissingDelimiter)
    };
    let action = match name {
        "validate" => ProcessAction::Validate,
        "select" => ProcessAction::Select {
            fields: required("fields")?,
        },
        "filter" => ProcessAction::Filter {
            field: required("field")?,
            equals: required("equals")?,
        },
        "count" => ProcessAction::Count,
        "group" => ProcessAction::Group {
            field: required("field")?,
        },
        "containing" => ProcessAction::Containing {
            file: required("file")?,
            line: values
                .get_one::<u64>("line")
                .copied()
                .ok_or(CliParseError::MissingDelimiter)?,
            column: values
                .get_one::<u64>("column")
                .copied()
                .ok_or(CliParseError::MissingDelimiter)?,
            include_text: values.get_flag("include-text"),
        },
        "group-locations" => ProcessAction::GroupLocations {
            file: values.get_one::<String>("file").cloned(),
            offset: values.get_one::<usize>("offset").copied().unwrap_or(0),
            limit: values
                .get_one::<u64>("limit")
                .and_then(|value| usize::try_from(*value).ok())
                .unwrap_or(40),
        },
        "sort" => ProcessAction::Sort {
            by: required("by")?,
            descending: values.get_flag("descending"),
        },
        "dedupe" => ProcessAction::Dedupe {
            on_conflict: required("on-conflict")?,
        },
        "merge" => ProcessAction::Merge {
            sources: values
                .get_many::<String>("source")
                .ok_or(CliParseError::MissingDelimiter)?
                .cloned()
                .collect(),
            on_conflict: required("on-conflict")?,
        },
        "to-jsonl" => ProcessAction::ToJsonl,
        "from-jsonl" => ProcessAction::FromJsonl,
        _ => return Err(CliParseError::MissingDelimiter),
    };
    let output = if matches!(
        action,
        ProcessAction::Containing { .. } | ProcessAction::GroupLocations { .. }
    ) {
        parse_output(values)
    } else {
        OutputFormat::Machine
    };
    Ok(ProcessCommand {
        input,
        action,
        output,
    })
}

fn parse_cache_command(matches: &ArgMatches) -> Result<CacheCommand, CliParseError> {
    let required_id = |matches: &ArgMatches| {
        matches
            .get_one::<String>("cache-id")
            .cloned()
            .ok_or(CliParseError::MissingDelimiter)
    };
    match matches.subcommand() {
        Some(("get", values)) => Ok(CacheCommand::Get {
            cache_id: required_id(values)?,
            result: values.get_one::<u64>("result").copied(),
            field: values.get_one::<String>("field").cloned(),
        }),
        Some(("query", values)) => Ok(CacheCommand::Query {
            cache_id: required_id(values)?,
            file: values.get_one::<String>("file").cloned(),
            rule_id: values.get_one::<String>("rule-id").cloned(),
            offset: values.get_one::<usize>("offset").copied().unwrap_or(0),
            limit: values
                .get_one::<u64>("limit")
                .and_then(|value| usize::try_from(*value).ok())
                .unwrap_or(40),
            max_text_chars: values
                .get_one::<u64>("max-text-chars")
                .and_then(|value| usize::try_from(*value).ok())
                .unwrap_or(240),
            output: parse_output(values),
        }),
        Some(("info", values)) => Ok(CacheCommand::Info {
            cache_id: required_id(values)?,
        }),
        Some(("remove", values)) => Ok(CacheCommand::Remove {
            cache_id: required_id(values)?,
        }),
        Some(("gc", _)) => Ok(CacheCommand::Gc),
        _ => Err(CliParseError::MissingDelimiter),
    }
}

fn explicit_options(matches: &ArgMatches) -> ExplicitOptions {
    ExplicitOptions {
        engine: matches.get_one::<PathBuf>("engine").cloned(),
        cwd: matches.get_one::<PathBuf>("cwd").cloned(),
        yaml_out: matches.get_one::<PathBuf>("yaml-out").cloned(),
        artifact_out: matches.get_one::<PathBuf>("artifact-out").cloned(),
        stderr_yaml: matches.get_one::<PathBuf>("stderr-yaml").cloned(),
        meta_out: matches.get_one::<PathBuf>("meta-out").cloned(),
        output: parse_output(matches),
        profile: matches
            .get_one::<String>("profile")
            .and_then(|value| match value.as_str() {
                "token-safe" => Some(Profile::TokenSafe),
                "locations" => Some(Profile::Locations),
                "lossless" => Some(Profile::Lossless),
                "files" => Some(Profile::Files),
                "custom" => Some(Profile::Custom),
                _ => None,
            }),
        cache_mode: matches
            .get_one::<String>("cache")
            .and_then(|value| match value.as_str() {
                "auto" => Some(srcq_core::cache::CacheMode::Auto),
                "on" => Some(srcq_core::cache::CacheMode::On),
                "off" => Some(srcq_core::cache::CacheMode::Off),
                _ => None,
            }),
        fingerprint_files: matches
            .get_many::<PathBuf>("fingerprint-file")
            .map(|values| values.cloned().collect())
            .unwrap_or_default(),
        max_detail_results: matches.get_one::<u32>("max-detail-results").copied(),
        max_text_chars: matches.get_one::<u32>("max-text-chars").copied(),
        max_context_bytes: matches.get_one::<u64>("max-context-bytes").copied(),
        keep_fields: matches.get_one::<String>("keep-fields").cloned(),
        prune_fields: matches.get_one::<String>("prune-fields").cloned(),
        no_native_defaults: matches.get_flag("no-native-defaults"),
        strict: matches.get_flag("strict"),
    }
}

fn parse_output(matches: &ArgMatches) -> OutputFormat {
    match matches
        .try_get_one::<String>("output")
        .ok()
        .flatten()
        .map(String::as_str)
    {
        Some("machine") => OutputFormat::Machine,
        _ => OutputFormat::Model,
    }
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;
    use std::path::Path;

    use srcq_core::invocation::{OutputFormat, Profile, WrapperCommand};

    use super::{
        parse_cli_from, parse_invocation_from, CacheCommand, CliAction, CliParseError,
        GatewayBackend, GatewayOperation, ProcessAction, ProcessCommand, ProcessInput,
    };

    fn os_args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn preserves_native_tokens_after_first_delimiter() {
        let invocation = parse_invocation_from(os_args(&[
            "srcq",
            "exec",
            "--engine",
            "tools/ast-grep",
            "--cwd",
            "repo",
            "--yaml-out",
            "result.yaml",
            "--artifact-out",
            "native.bin",
            "--stderr-yaml",
            "stderr.yaml",
            "--meta-out",
            "meta.yaml",
            "--profile",
            "custom",
            "--cache",
            "off",
            "--fingerprint-file",
            "src/a.ts",
            "--fingerprint-file",
            "src/b.ts",
            "--max-detail-results",
            "20",
            "--max-text-chars",
            "120",
            "--max-context-bytes",
            "12288",
            "--keep-fields",
            "file,range,text",
            "--prune-fields",
            "text",
            "--strict",
            "--no-native-defaults",
            "--",
            "run",
            "-p",
            "console.log($A)",
            "quote'\"token",
            "中文",
            "",
            "--json=stream",
            "--json=stream",
            "--",
            "tail",
        ]))
        .expect("valid invocation");

        assert_eq!(invocation.command, WrapperCommand::Exec);
        assert_eq!(
            invocation.explicit.engine.as_deref(),
            Some(Path::new("tools/ast-grep"))
        );
        assert_eq!(invocation.explicit.cwd.as_deref(), Some(Path::new("repo")));
        assert_eq!(
            invocation.explicit.yaml_out.as_deref(),
            Some(Path::new("result.yaml"))
        );
        assert_eq!(
            invocation.explicit.artifact_out.as_deref(),
            Some(Path::new("native.bin"))
        );
        assert_eq!(
            invocation.explicit.stderr_yaml.as_deref(),
            Some(Path::new("stderr.yaml"))
        );
        assert_eq!(
            invocation.explicit.meta_out.as_deref(),
            Some(Path::new("meta.yaml"))
        );
        assert_eq!(invocation.explicit.profile, Some(Profile::Custom));
        assert_eq!(
            invocation.explicit.cache_mode,
            Some(srcq_core::cache::CacheMode::Off)
        );
        assert_eq!(
            invocation.explicit.fingerprint_files,
            vec![
                Path::new("src/a.ts").to_path_buf(),
                Path::new("src/b.ts").to_path_buf()
            ]
        );
        assert_eq!(invocation.explicit.max_detail_results, Some(20));
        assert_eq!(invocation.explicit.max_text_chars, Some(120));
        assert_eq!(invocation.explicit.max_context_bytes, Some(12_288));
        assert_eq!(
            invocation.explicit.keep_fields.as_deref(),
            Some("file,range,text")
        );
        assert_eq!(invocation.explicit.prune_fields.as_deref(), Some("text"));
        assert!(invocation.explicit.strict);
        assert!(invocation.explicit.no_native_defaults);
        assert_eq!(
            invocation.user_argv,
            os_args(&[
                "run",
                "-p",
                "console.log($A)",
                "quote'\"token",
                "中文",
                "",
                "--json=stream",
                "--json=stream",
                "--",
                "tail",
            ])
        );
    }

    #[test]
    fn defaults_uses_the_same_opaque_native_boundary() {
        let invocation = parse_invocation_from(os_args(&[
            "srcq",
            "defaults",
            "--",
            "future-command",
            "--unknown",
        ]))
        .expect("unknown native arguments are opaque");
        assert_eq!(invocation.command, WrapperCommand::Defaults);
        assert_eq!(
            invocation.user_argv,
            os_args(&["future-command", "--unknown"])
        );
    }

    #[test]
    fn rejects_missing_or_empty_native_boundary() {
        assert!(matches!(
            parse_invocation_from(os_args(&["srcq", "exec", "run"])),
            Err(CliParseError::MissingDelimiter)
        ));
        assert!(matches!(
            parse_invocation_from(os_args(&["srcq", "exec", "--"])),
            Err(CliParseError::EmptyNativeArgv)
        ));
    }

    #[test]
    fn rejects_unknown_wrapper_options_but_not_native_options() {
        assert!(matches!(
            parse_invocation_from(os_args(&["srcq", "exec", "--wrapper-unknown", "--", "run"])),
            Err(CliParseError::Clap(_))
        ));
        assert!(
            parse_invocation_from(os_args(&["srcq", "exec", "--", "run", "--native-unknown"]))
                .is_ok()
        );
    }

    #[test]
    fn parses_cache_commands_without_a_native_delimiter() {
        let action = parse_cli_from(os_args(&[
            "srcq",
            "cache",
            "get",
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "--result",
            "7",
            "--field",
            "/text",
        ]))
        .expect("cache get");
        assert_eq!(
            action,
            CliAction::Cache(CacheCommand::Get {
                cache_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV".to_owned(),
                result: Some(7),
                field: Some("/text".to_owned()),
            })
        );

        let query = parse_cli_from(os_args(&[
            "srcq",
            "cache",
            "query",
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "--file",
            "src/a.ts",
        ]))
        .expect("cache query");
        assert!(matches!(
            query,
            CliAction::Cache(CacheCommand::Query {
                offset: 0,
                limit: 40,
                ..
            })
        ));
    }

    #[test]
    fn parses_default_and_explicit_symbol_time_budgets() {
        let default = parse_cli_from(os_args(&["srcq", "symbol", "definition", "Target"]))
            .expect("default symbol query");
        let CliAction::Symbol(default) = default else {
            panic!("expected symbol command")
        };
        assert_eq!(default.time_budget_ms, 7_500);

        let explicit = parse_cli_from(os_args(&[
            "srcq",
            "symbol",
            "references",
            "Target",
            "--time-budget-ms",
            "9000",
        ]))
        .expect("explicit symbol query");
        let CliAction::Symbol(explicit) = explicit else {
            panic!("expected symbol command")
        };
        assert_eq!(explicit.time_budget_ms, 9_000);
    }

    #[test]
    fn parses_gateway_native_argv_without_reordering_or_deduplication() {
        let action = parse_cli_from(os_args(&[
            "srcq", "query", "rg", "exec", "--view", "grouped", "--limit", "7", "--", "-e", "a b",
            "-g", "*.rs", "-e", "a b", "", "--", "tail",
        ]))
        .expect("rg gateway");
        let CliAction::Gateway(command) = action else {
            panic!("expected gateway")
        };
        assert_eq!(GatewayBackend::Rg, command.backend);
        assert_eq!(GatewayOperation::Exec, command.operation);
        assert_eq!(7, command.limit);
        assert_eq!("grouped", command.view);
        assert_eq!("auto", command.receipt);
        assert_eq!(
            os_args(&["-e", "a b", "-g", "*.rs", "-e", "a b", "", "--", "tail"]),
            command.native_argv
        );
    }

    #[test]
    fn parses_short_model_continuation_without_query_syntax() {
        let action = parse_cli_from(os_args(&["srcq", "more", "q17"])).expect("short continuation");
        assert_eq!(action, CliAction::More("q17".to_owned()));
    }

    #[test]
    fn parses_explicit_full_gateway_receipt() {
        let action = parse_cli_from(os_args(&[
            "srcq",
            "query",
            "rg",
            "exec",
            "--receipt",
            "full",
            "--",
            "needle",
            ".",
        ]))
        .expect("rg full receipt");
        assert!(matches!(
            action,
            CliAction::Gateway(command) if command.receipt == "full"
        ));
    }

    #[test]
    fn parses_scc_direct_and_explicit_metric_views() {
        let direct = parse_cli_from(os_args(&[
            "srcq",
            "scc",
            "--by-file",
            "--sort",
            "complexity",
            ".",
        ]))
        .expect("direct scc");
        let CliAction::Gateway(direct) = direct else {
            panic!("expected scc gateway")
        };
        assert_eq!(GatewayBackend::Scc, direct.backend);
        assert_eq!("auto", direct.view);
        assert_eq!(
            os_args(&["--by-file", "--sort", "complexity", "."]),
            direct.native_argv
        );

        let explicit = parse_cli_from(os_args(&[
            "srcq",
            "query",
            "scc",
            "exec",
            "--view",
            "hotspots",
            "--limit",
            "12",
            "--",
            "--by-file",
            ".",
        ]))
        .expect("explicit scc");
        assert!(matches!(
            explicit,
            CliAction::Gateway(command)
                if command.backend == GatewayBackend::Scc
                    && command.view == "hotspots"
                    && command.limit == 12
        ));
    }

    #[test]
    fn gateway_help_does_not_require_a_native_delimiter() {
        let error = parse_cli_from(os_args(&["srcq", "query", "rg", "exec", "--help"]))
            .expect_err("wrapper help exits through clap");
        assert!(matches!(
            error,
            CliParseError::Clap(error)
                if error.kind() == clap::error::ErrorKind::DisplayHelp
        ));
    }

    #[test]
    fn gateway_accepts_budget_aliases_without_leaking_them_to_native_argv() {
        let action = parse_cli_from(os_args(&[
            "srcq",
            "query",
            "rg",
            "exec",
            "--max-items",
            "7",
            "--max-line-length",
            "120",
            "--",
            "needle",
            ".",
        ]))
        .expect("rg gateway aliases");
        let CliAction::Gateway(command) = action else {
            panic!("expected gateway")
        };
        assert_eq!(7, command.limit);
        assert_eq!(120, command.max_text_chars);
        assert_eq!(os_args(&["needle", "."]), command.native_argv);
    }

    #[test]
    fn explicit_gateway_requires_the_boundary_but_preserves_an_empty_native_invocation() {
        assert!(matches!(
            parse_cli_from(os_args(&["srcq", "query", "fd", "exec"])),
            Err(CliParseError::MissingDelimiter)
        ));
        let action = parse_cli_from(os_args(&["srcq", "query", "fd", "exec", "--"]))
            .expect("empty native fd invocation");
        assert!(
            matches!(action, CliAction::Gateway(command) if command.backend == GatewayBackend::Fd && command.native_argv.is_empty())
        );
    }

    #[test]
    fn parses_gateway_doctor_without_native_argv() {
        let action = parse_cli_from(os_args(&[
            "srcq", "query", "fd", "doctor", "--engine", "fd.exe",
        ]))
        .expect("fd doctor");
        assert!(
            matches!(action, CliAction::Gateway(command) if command.backend == GatewayBackend::Fd && command.operation == GatewayOperation::Doctor && command.native_argv.is_empty())
        );
    }

    #[test]
    fn direct_gateway_treats_every_backend_token_as_native_argv() {
        let action = parse_cli_from(os_args(&[
            "srcq", "rg", "exec", "--view", "grouped", "--help", "", "--", "tail",
        ]))
        .expect("direct rg invocation");
        let CliAction::Gateway(command) = action else {
            panic!("expected gateway")
        };
        assert_eq!(GatewayBackend::Rg, command.backend);
        assert_eq!(GatewayOperation::Exec, command.operation);
        assert_eq!("auto", command.view);
        assert_eq!(80, command.limit);
        assert_eq!(2048, command.model_token_budget);
        assert_eq!(
            os_args(&["exec", "--view", "grouped", "--help", "", "--", "tail"]),
            command.native_argv
        );
    }

    #[test]
    fn parses_process_sources_and_operations_without_a_native_delimiter() {
        assert_eq!(
            parse_cli_from(os_args(&[
                "srcq",
                "process",
                "filter",
                "--input",
                "results.yaml",
                "--field",
                "severity",
                "--equals",
                "\"warning\"",
            ]))
            .expect("process filter"),
            CliAction::Process(ProcessCommand {
                input: ProcessInput::File("results.yaml".into()),
                action: ProcessAction::Filter {
                    field: "severity".to_owned(),
                    equals: "\"warning\"".to_owned(),
                },
                output: OutputFormat::Machine,
            })
        );
        assert_eq!(
            parse_cli_from(os_args(&[
                "srcq",
                "process",
                "count",
                "--cache-id",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            ]))
            .expect("process cache count"),
            CliAction::Process(ProcessCommand {
                input: ProcessInput::Cache("01ARZ3NDEKTSV4RRFFQ69G5FAV".to_owned()),
                action: ProcessAction::Count,
                output: OutputFormat::Machine,
            })
        );
        assert_eq!(
            parse_cli_from(os_args(&[
                "srcq",
                "process",
                "containing",
                "--cache-id",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "--file",
                "src/a.ts",
                "--line",
                "12",
                "--column",
                "3",
                "--include-text",
            ]))
            .expect("process containing"),
            CliAction::Process(ProcessCommand {
                input: ProcessInput::Cache("01ARZ3NDEKTSV4RRFFQ69G5FAV".to_owned()),
                action: ProcessAction::Containing {
                    file: "src/a.ts".to_owned(),
                    line: 12,
                    column: 3,
                    include_text: true,
                },
                output: OutputFormat::Model,
            })
        );
        assert_eq!(
            parse_cli_from(os_args(&[
                "srcq",
                "process",
                "group-locations",
                "--cache-id",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "--offset",
                "2",
                "--limit",
                "5",
            ]))
            .expect("process grouped locations"),
            CliAction::Process(ProcessCommand {
                input: ProcessInput::Cache("01ARZ3NDEKTSV4RRFFQ69G5FAV".to_owned()),
                action: ProcessAction::GroupLocations {
                    file: None,
                    offset: 2,
                    limit: 5,
                },
                output: OutputFormat::Model,
            })
        );
    }

    #[test]
    fn help_and_version_remain_display_operations() {
        let help = parse_invocation_from(os_args(&["srcq", "--help"]))
            .expect_err("help is represented as a clap display error");
        let version = parse_invocation_from(os_args(&["srcq", "--version"]))
            .expect_err("version is represented as a clap display error");
        assert!(help.is_display());
        assert!(version.is_display());
        assert_eq!(help.wrapper_exit_code(), 0);
    }

    #[test]
    fn preserves_unpaired_surrogate_native_token_on_windows() {
        use std::os::windows::ffi::OsStringExt;

        let opaque = OsString::from_wide(&[0xd800, u16::from(b'a')]);
        let invocation = parse_invocation_from(vec![
            OsString::from("srcq"),
            OsString::from("exec"),
            OsString::from("--"),
            OsString::from("run"),
            opaque.clone(),
        ])
        .expect("non-Unicode native token must stay opaque");
        assert_eq!(invocation.user_argv[1], opaque);
    }
}
