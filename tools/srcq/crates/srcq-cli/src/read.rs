use std::fmt::Write as FmtWrite;
use std::io::{self, Write};
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadCommand {
    pub path: PathBuf,
    pub start: usize,
    pub end: usize,
    pub number: bool,
}

pub fn execute(command: &ReadCommand) -> i32 {
    match read_range(command) {
        Ok(text) => match io::stdout().lock().write_all(text.as_bytes()) {
            Ok(()) => 0,
            Err(error) => {
                eprintln!("srcq read: cannot write output: {error}");
                126
            }
        },
        Err((code, message)) => {
            eprintln!("srcq read: {message}");
            code
        }
    }
}

fn read_range(command: &ReadCommand) -> Result<String, (i32, String)> {
    if command.start == 0 || command.end < command.start {
        return Err((
            125,
            "expected 1 <= start <= end (inclusive line numbers)".into(),
        ));
    }
    let bytes = std::fs::read(&command.path).map_err(|error| {
        (
            126,
            format!("cannot read {}: {error}", command.path.display()),
        )
    })?;
    let text =
        crate::source_text::decode(&command.path, bytes).map_err(|message| (125, message))?;
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
    // EOF naturally ends the selection. Preserve original line endings without
    // manufacturing a final empty line or changing original line numbers.
    let mut selected = String::new();
    for (index, line) in text
        .split_inclusive('\n')
        .enumerate()
        .skip(command.start - 1)
        .take(command.end - command.start + 1)
    {
        if command.number {
            write!(&mut selected, "{}:{line}", index + 1).expect("writing to String cannot fail");
        } else {
            selected.push_str(line);
        }
    }
    Ok(selected)
}
