#![forbid(unsafe_code)]

#[cfg(not(windows))]
compile_error!("sgy is maintained and supported only on Windows");

pub mod cache;
pub mod defaults_output;
pub mod diagnostics;
pub mod processor;

use std::ffi::{OsStr, OsString};
use std::fmt;
use std::path::PathBuf;

use clap::builder::PossibleValuesParser;
use clap::{Arg, ArgAction, ArgMatches, Command};
use sgy_core::invocation::{ExplicitOptions, NativeInvocation, Profile, WrapperCommand};

const NATIVE_DELIMITER: &str = "--";

#[must_use]
pub fn command() -> Command {
    let build = sgy_core::build_info();
    Command::new("sgy")
        .version(build.package_version)
        .about("Token-safe YAML adapter for ast-grep")
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
        .subcommand(
            Command::new("schema")
                .about("Print the bounded sgy configuration schema")
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
            "Operational syntax: sgy <exec|defaults> [wrapper options] -- <ast-grep argv...>\nInspection syntax: sgy <schema|capabilities|doctor> ...\nCache syntax: sgy cache <get|query|info|remove|gc> ...\nProcess syntax: sgy process <validate|select|filter|count|group|sort|dedupe|merge|to-jsonl|from-jsonl> ...",
        )
}

fn process_subcommand() -> Command {
    Command::new("process")
        .about("Safely process sgy YAML or verified cache results")
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InspectionCommand {
    Schema,
    Capabilities,
    Doctor {
        engine: Option<PathBuf>,
        cwd: Option<PathBuf>,
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
                eprintln!("sgy: {other}");
                Ok(())
            }
        }
    }
}

impl fmt::Display for CliParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Clap(error) => error.fmt(formatter),
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
    }) {
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
            })),
            _ => Err(CliParseError::MissingDelimiter),
        };
    }
    parse_invocation_from(raw).map(|invocation| CliAction::Native(Box::new(invocation)))
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
    Ok(ProcessCommand { input, action })
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
                "auto" => Some(sgy_core::cache::CacheMode::Auto),
                "on" => Some(sgy_core::cache::CacheMode::On),
                "off" => Some(sgy_core::cache::CacheMode::Off),
                _ => None,
            }),
        max_detail_results: matches.get_one::<u32>("max-detail-results").copied(),
        max_text_chars: matches.get_one::<u32>("max-text-chars").copied(),
        max_context_bytes: matches.get_one::<u64>("max-context-bytes").copied(),
        keep_fields: matches.get_one::<String>("keep-fields").cloned(),
        prune_fields: matches.get_one::<String>("prune-fields").cloned(),
        no_native_defaults: matches.get_flag("no-native-defaults"),
        strict: matches.get_flag("strict"),
    }
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;
    use std::path::Path;

    use sgy_core::invocation::{Profile, WrapperCommand};

    use super::{
        parse_cli_from, parse_invocation_from, CacheCommand, CliAction, CliParseError,
        ProcessAction, ProcessCommand, ProcessInput,
    };

    fn os_args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn preserves_native_tokens_after_first_delimiter() {
        let invocation = parse_invocation_from(os_args(&[
            "sgy",
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
            Some(sgy_core::cache::CacheMode::Off)
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
            "sgy",
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
            parse_invocation_from(os_args(&["sgy", "exec", "run"])),
            Err(CliParseError::MissingDelimiter)
        ));
        assert!(matches!(
            parse_invocation_from(os_args(&["sgy", "exec", "--"])),
            Err(CliParseError::EmptyNativeArgv)
        ));
    }

    #[test]
    fn rejects_unknown_wrapper_options_but_not_native_options() {
        assert!(matches!(
            parse_invocation_from(os_args(&["sgy", "exec", "--wrapper-unknown", "--", "run"])),
            Err(CliParseError::Clap(_))
        ));
        assert!(
            parse_invocation_from(os_args(&["sgy", "exec", "--", "run", "--native-unknown"]))
                .is_ok()
        );
    }

    #[test]
    fn parses_cache_commands_without_a_native_delimiter() {
        let action = parse_cli_from(os_args(&[
            "sgy",
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
            "sgy",
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
    fn parses_process_sources_and_operations_without_a_native_delimiter() {
        assert_eq!(
            parse_cli_from(os_args(&[
                "sgy",
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
            })
        );
        assert_eq!(
            parse_cli_from(os_args(&[
                "sgy",
                "process",
                "count",
                "--cache-id",
                "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            ]))
            .expect("process cache count"),
            CliAction::Process(ProcessCommand {
                input: ProcessInput::Cache("01ARZ3NDEKTSV4RRFFQ69G5FAV".to_owned()),
                action: ProcessAction::Count,
            })
        );
    }

    #[test]
    fn help_and_version_remain_display_operations() {
        let help = parse_invocation_from(os_args(&["sgy", "--help"]))
            .expect_err("help is represented as a clap display error");
        let version = parse_invocation_from(os_args(&["sgy", "--version"]))
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
            OsString::from("sgy"),
            OsString::from("exec"),
            OsString::from("--"),
            OsString::from("run"),
            opaque.clone(),
        ])
        .expect("non-Unicode native token must stay opaque");
        assert_eq!(invocation.user_argv[1], opaque);
    }
}
