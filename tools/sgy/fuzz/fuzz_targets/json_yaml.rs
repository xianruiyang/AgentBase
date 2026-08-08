#![no_main]

use libfuzzer_sys::fuzz_target;
use sgy_core::codec::{parse_single_json, parse_yaml_documents, write_yaml_document};

fuzz_target!(|data: &[u8]| {
    if let Ok(record) = parse_single_json(data) {
        let mut yaml = Vec::new();
        write_yaml_document(&record.value, &mut yaml, false)
            .unwrap_or_else(|error| panic!("valid JSON value failed YAML encoding: {error}"));
        let decoded = parse_yaml_documents(&yaml)
            .unwrap_or_else(|error| panic!("emitted YAML failed safe parsing: {error}"));
        assert_eq!(decoded, vec![record.value]);
    }
});
