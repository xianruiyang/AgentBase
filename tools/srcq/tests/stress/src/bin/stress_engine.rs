use std::{
    env,
    io::{self, Write},
    process, thread,
};

fn main() -> io::Result<()> {
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args
        .first()
        .is_some_and(|arg| arg == "--version" || arg == "-V")
    {
        println!("ast-grep 0.44.1");
        return Ok(());
    }
    let records = numeric_flag(&args, "--stress-records=").unwrap_or(1);
    let stderr_bytes = numeric_flag(&args, "--stress-stderr=").unwrap_or(0);
    let stderr = thread::spawn(move || -> io::Result<()> {
        let chunk = [b'e'; 64 * 1024];
        let mut remaining = stderr_bytes;
        let mut output = io::stderr().lock();
        while remaining > 0 {
            let count = remaining.min(chunk.len());
            output.write_all(&chunk[..count])?;
            remaining -= count;
        }
        output.flush()
    });
    let mut output = io::stdout().lock();
    for ordinal in 0..records {
        writeln!(
            output,
            "{{\"file\":\"src/f{}.ts\",\"range\":{{\"start\":{{\"line\":{},\"column\":0}},\"end\":{{\"line\":{},\"column\":1}}}},\"text\":\"match\",\"privateSource\":\"SOURCE_LEAK_SENTINEL\"}}",
            ordinal % 64,
            ordinal,
            ordinal
        )?;
    }
    output.flush()?;
    stderr
        .join()
        .map_err(|_| io::Error::other("stderr writer panicked"))??;
    process::exit(0);
}

fn numeric_flag(args: &[String], prefix: &str) -> Option<usize> {
    args.iter()
        .find_map(|arg| arg.strip_prefix(prefix))
        .and_then(|value| value.parse().ok())
}
