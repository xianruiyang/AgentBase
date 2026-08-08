#![no_main]

use libfuzzer_sys::fuzz_target;
use sgy_core::codec::{
    parse_yaml_config_documents_with_limits, parse_yaml_documents_with_limits,
    write_yaml_document, YamlParseLimits,
};

fuzz_target!(|data: &[u8]| {
    let limits = YamlParseLimits {
        max_input_bytes: 64 * 1024,
        max_depth: 32,
        max_nodes: 4096,
        max_documents: 64,
    };
    if let Ok(documents) = parse_yaml_documents_with_limits(data, limits) {
        let mut encoded = Vec::new();
        for document in &documents {
            write_yaml_document(document, &mut encoded, true)
                .unwrap_or_else(|error| panic!("safe value failed re-encoding: {error}"));
        }
        let reparsed = parse_yaml_documents_with_limits(&encoded, limits)
            .unwrap_or_else(|error| panic!("re-encoded safe YAML failed: {error}"));
        assert_eq!(reparsed, documents);
    }
    let _ = parse_yaml_config_documents_with_limits(data, limits);
});
