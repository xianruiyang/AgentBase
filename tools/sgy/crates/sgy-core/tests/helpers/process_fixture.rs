use std::{
    env,
    fs::OpenOptions,
    io::{self, Read, Write},
    path::Path,
    process::{self, Command},
    thread,
    time::Duration,
};

fn main() -> io::Result<()> {
    let mut arguments = env::args_os().skip(1);
    let mode = arguments
        .next()
        .and_then(|value| value.into_string().ok())
        .unwrap_or_default();
    match mode.as_str() {
        "dual" => {
            let bytes = parse_usize(arguments.next(), "dual byte count")?;
            write_dual(bytes)
        }
        "echo-stdin" => {
            let mut bytes = Vec::new();
            io::stdin().read_to_end(&mut bytes)?;
            io::stdout().write_all(&bytes)
        }
        "exit" => {
            let code = parse_i32(arguments.next(), "exit code")?;
            if let Some(payload) = arguments.next() {
                io::stdout().write_all(payload.to_string_lossy().as_bytes())?;
            }
            process::exit(code);
        }
        "tree" => {
            let heartbeat = arguments.next().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "missing heartbeat path")
            })?;
            Command::new(env::current_exe()?)
                .arg("leaf")
                .arg(&heartbeat)
                .spawn()?;
            loop {
                thread::sleep(Duration::from_secs(1));
            }
        }
        "leaf" => {
            let heartbeat = arguments.next().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "missing heartbeat path")
            })?;
            heartbeat_loop(Path::new(&heartbeat))
        }
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("unknown fixture mode: {mode}"),
        )),
    }
}

fn parse_usize(value: Option<std::ffi::OsString>, label: &str) -> io::Result<usize> {
    value
        .and_then(|value| value.into_string().ok())
        .and_then(|value| value.parse().ok())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, label))
}

fn parse_i32(value: Option<std::ffi::OsString>, label: &str) -> io::Result<i32> {
    value
        .and_then(|value| value.into_string().ok())
        .and_then(|value| value.parse().ok())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, label))
}

fn write_dual(bytes: usize) -> io::Result<()> {
    let stdout = thread::spawn(move || write_repeated(io::stdout(), b'o', bytes));
    let stderr = thread::spawn(move || write_repeated(io::stderr(), b'e', bytes));
    stdout
        .join()
        .map_err(|_| io::Error::other("stdout fixture thread panicked"))??;
    stderr
        .join()
        .map_err(|_| io::Error::other("stderr fixture thread panicked"))??;
    Ok(())
}

fn write_repeated(mut output: impl Write, byte: u8, bytes: usize) -> io::Result<()> {
    let buffer = [byte; 64 * 1024];
    let mut remaining = bytes;
    while remaining > 0 {
        let count = remaining.min(buffer.len());
        output.write_all(&buffer[..count])?;
        remaining -= count;
    }
    output.flush()
}

fn heartbeat_loop(path: &Path) -> io::Result<()> {
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    loop {
        file.write_all(b"x")?;
        file.flush()?;
        thread::sleep(Duration::from_millis(40));
    }
}
