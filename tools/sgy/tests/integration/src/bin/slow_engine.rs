#![forbid(unsafe_code)]

use std::{thread, time::Duration};

fn main() {
    thread::sleep(Duration::from_secs(5));
    println!("ast-grep slow-fixture");
}
