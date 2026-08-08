use std::{ffi::OsString, path::PathBuf};

use sgy_core::{
    batch::{run_lossless_batch, BatchError},
    codec::{parse_yaml_documents, JsonInputKind},
    process::{ProcessRequest, StdinMode},
};

fn fixture_request(arguments: &[&str]) -> ProcessRequest {
    let mut request = ProcessRequest::new(
        PathBuf::from(env!("CARGO_BIN_EXE_sgy-process-fixture")),
        std::env::current_dir().expect("current directory"),
    );
    request.args = arguments.iter().map(OsString::from).collect();
    request.forward_stderr = false;
    request
}

#[test]
fn jsonl_is_staged_only_after_every_record_is_valid() {
    let payload = "{\"ordinal\":0}\n{\"ordinal\":1}\n";
    let outcome = run_lossless_batch(
        fixture_request(&["exit", "0", payload]),
        JsonInputKind::Lines,
    )
    .expect("complete JSONL should convert");

    assert_eq!(outcome.process.exit_code(), 0);
    let yaml = outcome.yaml.expect("complete YAML staging");
    assert_eq!(yaml.stats.records, 2);
    let documents = parse_yaml_documents(&yaml.read().expect("read YAML")).expect("safe YAML");
    assert_eq!(documents.len(), 2);
    assert_eq!(documents[0]["ordinal"], 0);
    assert_eq!(documents[1]["ordinal"], 1);

    let partial = run_lossless_batch(
        fixture_request(&["exit", "9", "{\"ok\":true}\nnot-json\n"]),
        JsonInputKind::Lines,
    )
    .expect_err("invalid trailing record must discard the staged result");
    assert!(matches!(partial, BatchError::Codec(_)));
    assert_eq!(partial.wrapper_exit_code(), 121);
}

#[test]
fn valid_native_output_keeps_nonzero_exit_and_empty_error_output_does_not_make_yaml() {
    let valid = run_lossless_batch(
        fixture_request(&["exit", "7", "{\"finding\":true}"]),
        JsonInputKind::Single,
    )
    .expect("valid JSON on native nonzero");
    assert_eq!(valid.process.exit_code(), 7);
    assert_eq!(
        parse_yaml_documents(&valid.yaml.expect("YAML").read().expect("read YAML"))
            .expect("safe YAML")[0]["finding"],
        true
    );

    let empty = run_lossless_batch(fixture_request(&["exit", "2"]), JsonInputKind::Single)
        .expect("native empty error output bypasses the codec");
    assert_eq!(empty.process.exit_code(), 2);
    assert!(empty.yaml.is_none());
}

#[test]
fn binary_stdin_reaches_the_native_process_and_then_the_codec() {
    let mut request = fixture_request(&["echo-stdin"]);
    request.stdin = StdinMode::Bytes("{\"source\":\"stdin\"}".as_bytes().to_vec());
    let outcome =
        run_lossless_batch(request, JsonInputKind::Single).expect("stdin JSON should convert");
    let documents = parse_yaml_documents(
        &outcome
            .yaml
            .expect("YAML")
            .read()
            .expect("read staged YAML"),
    )
    .expect("safe YAML");
    assert_eq!(documents[0]["source"], "stdin");
}
