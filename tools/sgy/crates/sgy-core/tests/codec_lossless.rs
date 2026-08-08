use std::{
    fs,
    io::{self, BufReader, Cursor, Write},
    path::{Path, PathBuf},
};

use serde_json::{json, Value};
use sgy_core::codec::{
    parse_single_json, parse_yaml_documents, transcode_lossless, ByteSpan, CodecError,
    JsonInputKind, JsonLines,
};

fn fixture(relative: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures")
        .join("codec")
        .join(relative)
}

fn transcode_fixture(relative: &str, kind: JsonInputKind) -> Vec<u8> {
    let input = fs::read(fixture(relative)).expect("read input fixture");
    let mut output = Vec::new();
    transcode_lossless(BufReader::new(Cursor::new(input)), &mut output, kind)
        .expect("transcode fixture");
    output
}

#[test]
fn compact_and_pretty_share_one_lossless_golden() {
    let compact = transcode_fixture("json-values/compact.json", JsonInputKind::Single);
    let pretty = transcode_fixture("json-values/pretty.json", JsonInputKind::Single);
    let expected = fs::read(fixture("json-values/expected.yaml")).expect("read YAML golden");

    assert_eq!(compact, expected);
    assert_eq!(pretty, expected);
    let original = parse_single_json(
        &fs::read(fixture("json-values/compact.json")).expect("read compact fixture"),
    )
    .expect("parse compact fixture");
    assert_eq!(
        parse_yaml_documents(&compact).expect("parse compact YAML"),
        vec![original.value]
    );
    assert!(!compact.windows(4).any(|window| window == b"_sgy"));
    assert!(!compact.starts_with(&[0xef, 0xbb, 0xbf]));
    assert!(!compact.contains(&b'\r'));
    assert_eq!(compact.last(), Some(&b'\n'));
}

#[test]
fn jsonl_writes_independent_explicit_documents_and_spans() {
    let input = fs::read(fixture("jsonl/stream.jsonl")).expect("read JSONL fixture");
    let output = transcode_fixture("jsonl/stream.jsonl", JsonInputKind::Lines);
    let expected = fs::read(fixture("jsonl/expected.yaml")).expect("read JSONL golden");
    assert_eq!(output, expected);

    let records = JsonLines::new(BufReader::new(Cursor::new(&input)))
        .collect::<Result<Vec<_>, _>>()
        .expect("parse JSONL records");
    assert_eq!(records.len(), 2);
    assert_eq!(records[0].ordinal, 0);
    assert_eq!(records[1].ordinal, 1);
    assert_eq!(
        parse_yaml_documents(&output).expect("parse JSONL YAML"),
        records
            .into_iter()
            .map(|record| record.value)
            .collect::<Vec<_>>()
    );
    assert_eq!(
        output.windows(4).filter(|value| *value == b"---\n").count(),
        2
    );
}

#[test]
fn sarif_is_one_complete_generic_document() {
    let input = fs::read(fixture("sarif/report.json")).expect("read SARIF fixture");
    let output = transcode_fixture("sarif/report.json", JsonInputKind::Single);
    let expected = fs::read(fixture("sarif/expected.yaml")).expect("read SARIF golden");
    assert_eq!(output, expected);

    let original = parse_single_json(&input).expect("parse SARIF");
    assert_eq!(
        parse_yaml_documents(&output).expect("parse SARIF YAML"),
        vec![original.value]
    );
}

#[test]
fn arbitrary_numbers_unicode_null_and_empty_containers_round_trip() {
    let input = r#"{
      "huge": 1234567890123456789012345678901234567890,
      "tiny": 0.000000000000000000000000000000000000000123,
      "negativeExponent": -9.876543210123456789e-123,
      "unicode": "中文 😀 é",
      "multiline": "第一行\nsecond\n",
      "null": null,
      "array": [],
      "object": {},
      "ambiguous": "null"
    }"#
    .as_bytes();
    let original = parse_single_json(input).expect("parse values");
    let mut output = Vec::new();
    let stats = transcode_lossless(
        BufReader::new(Cursor::new(input)),
        &mut output,
        JsonInputKind::Single,
    )
    .expect("transcode values");
    assert_eq!(stats.records, 1);
    assert_eq!(stats.input_bytes, input.len() as u64);
    assert_eq!(stats.output_bytes, output.len() as u64);
    assert_eq!(
        parse_yaml_documents(&output).expect("parse value YAML"),
        vec![original.value]
    );
}

#[test]
fn jsonl_offsets_exclude_blank_lines_and_surrounding_whitespace() {
    let input = b" \r\n {\"a\":1}\r\n\n{\"b\":2} \n";
    let records = JsonLines::new(BufReader::new(Cursor::new(input)))
        .collect::<Result<Vec<_>, _>>()
        .expect("parse JSONL");
    assert_eq!(records[0].span, ByteSpan::new(4, 11));
    assert_eq!(records[1].span, ByteSpan::new(14, 21));
    assert_eq!(records[0].value, json!({"a": 1}));
    assert_eq!(records[1].value, json!({"b": 2}));
}

#[test]
fn empty_jsonl_produces_zero_bytes() {
    let mut output = Vec::new();
    let stats = transcode_lossless(
        BufReader::new(Cursor::new(b" \n\r\n")),
        &mut output,
        JsonInputKind::Lines,
    )
    .expect("empty JSONL");
    assert_eq!(stats.records, 0);
    assert_eq!(output, Vec::<u8>::new());
}

#[test]
fn invalid_utf8_json_and_duplicate_keys_have_stable_format_errors() {
    let invalid_cases: [&[u8]; 3] = [
        b"{\"value\":\xff}",
        b"{\"value\":}",
        b"{\"same\":1,\"s\\u0061me\":2}",
    ];
    for input in invalid_cases {
        let error = parse_single_json(input).expect_err("invalid input must fail");
        assert_eq!(error.wrapper_exit_code(), 121);
    }
}

#[test]
fn safe_loader_rejects_advanced_yaml_and_duplicate_keys() {
    let unsafe_cases: [&[u8]; 5] = [
        b"value: &anchor 1\ncopy: *anchor\n",
        b"value: !!str tagged\n",
        b"key: 1\nkey: 2\n",
        b"<<: {}\n",
        b"\xef\xbb\xbfkey: 1\n",
    ];
    for input in unsafe_cases {
        let error = parse_yaml_documents(input).expect_err("unsafe YAML must fail");
        assert_eq!(error.wrapper_exit_code(), 122);
    }
}

#[test]
fn generic_unknown_fields_are_not_projected_or_renamed() {
    let value: Value = json!({
        "futureField": {"nested": [1, null, "value"]},
        "range": {"start": {"line": 1, "column": 2}},
        "metaVariables": {"futureCaptureShape": true}
    });
    let input = serde_json::to_vec(&value).expect("serialize test JSON");
    let mut output = Vec::new();
    transcode_lossless(
        BufReader::new(Cursor::new(input)),
        &mut output,
        JsonInputKind::Single,
    )
    .expect("transcode unknown fields");
    assert_eq!(
        parse_yaml_documents(&output).expect("parse unknown-field YAML"),
        vec![value]
    );
}

#[test]
fn single_mode_rejects_empty_input_while_lines_mode_accepts_it() {
    let error = parse_single_json(b" \r\n").expect_err("single JSON cannot be empty");
    assert!(matches!(error, CodecError::InvalidJson { .. }));
    assert_eq!(error.wrapper_exit_code(), 121);
}

#[test]
fn large_jsonl_is_consumed_record_by_record() {
    let input = "{\"value\":1}\n".repeat(10_000);
    let mut sink = ByteCounter::default();
    let stats = transcode_lossless(
        BufReader::new(Cursor::new(input.as_bytes())),
        &mut sink,
        JsonInputKind::Lines,
    )
    .expect("transcode large JSONL");
    assert_eq!(stats.records, 10_000);
    assert_eq!(stats.input_bytes, input.len() as u64);
    assert_eq!(stats.output_bytes, sink.bytes);
}

#[derive(Default)]
struct ByteCounter {
    bytes: u64,
}

impl Write for ByteCounter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.bytes += buffer.len() as u64;
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
