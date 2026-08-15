#![no_main]

use libfuzzer_sys::fuzz_target;
use srcq_core::{config::load_config_paths, profile::FieldPaths};

fuzz_target!(|data: &[u8]| {
    if data.len() <= 64 * 1024 {
        if let Ok(directory) = tempfile::tempdir() {
            let path = directory.path().join(".srcq.yml");
            if std::fs::write(&path, data).is_ok() {
                let _ = load_config_paths(&path, None);
            }
        }
    }

    if let Ok(text) = std::str::from_utf8(data) {
        if let Ok(paths) = FieldPaths::parse(text) {
            let sample = serde_json::json!({
                "file": "src/main.ts",
                "range": {"start": {"line": 1, "column": 2}},
                "items": [{"name": "alpha"}, {"name": "beta"}],
            });
            let _ = paths.select(&sample);
            let _ = paths.values(&sample);
        }
    }
});
