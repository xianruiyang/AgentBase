use std::io::{self, Write};
use std::thread;
use std::time::Duration;

fn main() -> io::Result<()> {
    let executable = std::env::current_exe()?;
    let name = executable
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if name.contains("slow-engine") {
        thread::sleep(Duration::from_secs(5));
        println!("ast-grep fixture-slow");
    } else if name.contains("huge-engine") {
        io::stdout().write_all(&vec![b'x'; 70 * 1024])?;
    } else {
        println!("ast-grep fixture-1.0.0");
    }
    Ok(())
}
