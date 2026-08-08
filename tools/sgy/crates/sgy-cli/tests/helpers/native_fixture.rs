use std::{
    env, fs,
    io::{self, Read, Write},
    process::{self, Command},
    thread,
    time::{Duration, Instant},
};

use serde_json::json;

fn main() -> io::Result<()> {
    let args: Vec<String> = env::args_os()
        .skip(1)
        .map(|value| value.to_string_lossy().into_owned())
        .collect();
    if let Some(path) = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--fixture-child-ready="))
    {
        fs::write(path, b"ready\n")?;
    }
    if let Some(path) = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--fixture-delayed-create="))
    {
        thread::sleep(Duration::from_secs(2));
        fs::write(path, b"descendant survived\n")?;
        return Ok(());
    }
    if let Some(path) = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--fixture-spawn-delayed="))
    {
        let ready = args
            .iter()
            .find_map(|arg| arg.strip_prefix("--fixture-spawn-ready="))
            .ok_or_else(|| io::Error::other("missing --fixture-spawn-ready"))?;
        Command::new(env::current_exe()?)
            .arg(format!("--fixture-child-ready={ready}"))
            .arg(format!("--fixture-delayed-create={path}"))
            .spawn()?;
        let deadline = Instant::now() + Duration::from_secs(1);
        while !std::path::Path::new(ready).exists() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
    }
    if args.iter().any(|arg| arg == "--fixture-stderr-invalid") {
        io::stderr().write_all(&[b'e', 0xff, b'\n'])?;
    }
    if let Some(bytes) = numeric_flag(&args, "--fixture-stderr-bytes=") {
        let chunk = vec![b'e'; 64 * 1024];
        let mut remaining = bytes;
        let mut stderr = io::stderr().lock();
        while remaining > 0 {
            let count = remaining.min(chunk.len());
            stderr.write_all(&chunk[..count])?;
            remaining -= count;
        }
    }
    if let Some(path) = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--fixture-create="))
    {
        fs::write(path, b"created by native fixture\n")?;
    }
    if args.iter().any(|arg| arg == "--fixture-empty") {
        process::exit(2);
    }
    if args.iter().any(|arg| arg == "--fixture-no-match") {
        process::exit(1);
    }
    if args.iter().any(|arg| arg == "--fixture-invalid-utf8") {
        io::stdout().write_all(&[b'r', 0xff, b'w'])?;
        process::exit(exit_flag(&args));
    }
    if args.iter().any(|arg| arg == "--fixture-invalid") {
        io::stdout().write_all(b"{\"valid\":true}\nnot-json\n")?;
        process::exit(9);
    }
    if args.first().is_some_and(|arg| arg == "completions") {
        io::stdout().write_all(b"# completion fixture\ncomplete -c ast-grep\n")?;
        process::exit(exit_flag(&args));
    }
    if args
        .first()
        .is_some_and(|arg| arg == "--version" || arg == "-V")
    {
        io::stdout().write_all(b"ast-grep fixture 0.0.0\n")?;
        process::exit(exit_flag(&args));
    }
    if args
        .first()
        .is_some_and(|arg| arg == "--help" || arg == "-h")
    {
        io::stdout().write_all(b"ast-grep fixture help\nUsage: ast-grep [COMMAND]\n")?;
        process::exit(exit_flag(&args));
    }
    if args.first().is_some_and(|arg| arg == "lsp") {
        let mut input = Vec::new();
        io::stdin().read_to_end(&mut input)?;
        io::stdout().write_all(&input)?;
        io::stdout().flush()?;
        process::exit(exit_flag(&args));
    }

    let mut stdin = Vec::new();
    if args
        .iter()
        .any(|arg| arg == "--stdin" || arg == "--fixture-read-stdin")
    {
        io::stdin().read_to_end(&mut stdin)?;
    }
    if args
        .iter()
        .any(|arg| arg == "--debug-query" || arg.starts_with("--debug-query="))
    {
        io::stderr().write_all(b"fixture debug query\n")?;
    }
    if args.iter().any(|arg| arg == "--inspect")
        || args.iter().any(|arg| arg.starts_with("--inspect="))
    {
        io::stderr().write_all(b"fixture inspect summary\n")?;
    }
    if args.iter().any(|arg| arg == "--fixture-read-stdin") {
        io::stdout().write_all(&stdin)?;
        process::exit(exit_flag(&args));
    }
    if args
        .iter()
        .any(|arg| arg == "--files-with-matches" || arg.starts_with("--files-with-matches="))
    {
        let count = numeric_flag(&args, "--fixture-files=").unwrap_or(1);
        let mut stdout = io::stdout().lock();
        for ordinal in 0..count {
            writeln!(stdout, "src/file {ordinal}-中文.ts")?;
        }
        process::exit(exit_flag(&args));
    }
    let style = args
        .iter()
        .find_map(|arg| arg.strip_prefix("--json="))
        .or_else(|| args.iter().any(|arg| arg == "--json").then_some("pretty"));
    let format = format_flag(&args);
    if let Some(count) = numeric_flag(&args, "--fixture-matches=") {
        let text_chars = numeric_flag(&args, "--fixture-text-chars=").unwrap_or(24);
        let metadata = args
            .iter()
            .any(|arg| arg == "--include-metadata")
            .then(|| json!({"category": "fixture", "technology": ["test"]}));
        let replacements = args.iter().any(|arg| arg == "--fixture-replacements");
        let records: Vec<serde_json::Value> = (0..count)
            .map(|ordinal| {
                let mut record = json!({
                    "file": format!("src/{}.ts", ordinal % 3),
                    "range": {
                        "start": {"line": ordinal, "column": 0},
                        "end": {"line": ordinal, "column": 5},
                    },
                    "text": format!("match-{ordinal}-{}", "x".repeat(text_chars)),
                    "metaVariables": {"single": {"A": {"text": format!("capture-{ordinal}")}}},
                    "ruleId": format!("rule-{}", ordinal % 2),
                    "severity": if ordinal % 2 == 0 { "warning" } else { "error" },
                    "message": format!("finding {ordinal}"),
                    "ordinal": ordinal,
                    "futureField": {"preserved": true, "ordinal": ordinal},
                    "metadata": metadata.clone(),
                    "argv": &args,
                });
                if replacements {
                    record["replacement"] = json!(format!("replacement-{ordinal}"));
                }
                record
            })
            .collect();
        match style {
            Some("stream") => {
                let mut stdout = io::stdout().lock();
                for record in &records {
                    serde_json::to_writer(&mut stdout, record)?;
                    stdout.write_all(b"\n")?;
                }
            }
            Some("compact") => serde_json::to_writer(io::stdout().lock(), &records)?,
            Some("pretty") => serde_json::to_writer_pretty(io::stdout().lock(), &records)?,
            _ if format == Some("sarif") => {
                let sarif_results: Vec<serde_json::Value> = records
                    .iter()
                    .enumerate()
                    .map(|(ordinal, record)| {
                        let file = record["file"].as_str().expect("fixture file");
                        let text = record["text"].as_str().expect("fixture text");
                        let mut result = json!({
                            "ruleId": record["ruleId"],
                            "level": record["severity"],
                            "message": {"text": record["message"]},
                            "locations": [{
                                "physicalLocation": {
                                    "artifactLocation": {"uri": file},
                                    "region": {
                                        "startLine": ordinal + 1,
                                        "startColumn": 1,
                                        "endLine": ordinal + 1,
                                        "endColumn": 6,
                                        "snippet": {"text": text}
                                    }
                                }
                            }]
                        });
                        if replacements {
                            result["fixes"] = json!([{
                                "artifactChanges": [{
                                    "artifactLocation": {"uri": file},
                                    "replacements": [{
                                        "insertedContent": {"text": record["replacement"]}
                                    }]
                                }]
                            }]);
                        }
                        result
                    })
                    .collect();
                serde_json::to_writer(
                    io::stdout().lock(),
                    &json!({"version": "2.1.0", "runs": [{"results": sarif_results}]}),
                )?;
            }
            _ if format == Some("github") => {
                let mut stdout = io::stdout().lock();
                for ordinal in 0..count {
                    writeln!(
                        stdout,
                        "::warning file=src/{}.ts,line={},endLine={},title=rule-{}::finding {}",
                        ordinal % 3,
                        ordinal + 1,
                        ordinal + 1,
                        ordinal % 2,
                        ordinal
                    )?;
                }
            }
            _ => io::stdout().write_all(b"native text output")?,
        }
        io::stdout().write_all(b"\n")?;
        let exit = exit_flag(&args);
        if exit == 0 && args.iter().any(|arg| arg == "-U" || arg == "--update-all") {
            writeln!(io::stderr().lock(), "Applied {count} changes")?;
        }
        process::exit(exit);
    }
    let record = json!({
        "argv": args,
        "stdin": String::from_utf8_lossy(&stdin),
        "style": style,
    });
    match style {
        Some("stream") => serde_json::to_writer(io::stdout().lock(), &record)?,
        Some("compact") => serde_json::to_writer(io::stdout().lock(), &[record])?,
        Some("pretty") => serde_json::to_writer_pretty(io::stdout().lock(), &[record])?,
        _ if format == Some("sarif") => serde_json::to_writer(io::stdout().lock(), &record)?,
        _ if format == Some("github") => io::stdout().write_all(
            b"::warning file=src/default.ts,line=1,endLine=1,title=fixture::finding\n",
        )?,
        _ => io::stdout().write_all(b"native text output")?,
    }
    io::stdout().write_all(b"\n")?;

    process::exit(exit_flag(&args));
}

fn numeric_flag(args: &[String], prefix: &str) -> Option<usize> {
    args.iter()
        .find_map(|arg| arg.strip_prefix(prefix))
        .and_then(|value| value.parse().ok())
}

fn format_flag(args: &[String]) -> Option<&str> {
    args.iter()
        .find_map(|arg| arg.strip_prefix("--format="))
        .or_else(|| {
            args.windows(2)
                .find(|pair| pair[0] == "--format")
                .map(|pair| pair[1].as_str())
        })
}

fn exit_flag(args: &[String]) -> i32 {
    args.iter()
        .find_map(|arg| arg.strip_prefix("--fixture-exit="))
        .and_then(|value| value.parse::<i32>().ok())
        .unwrap_or(0)
}
