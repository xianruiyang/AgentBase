use std::{collections::VecDeque, io::Write};

use saphyr_parser::{Event, EventReceiver, Parser, ScalarStyle};
use serde_json::{Map, Value};

use super::{usize_to_u64, CodecError};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct YamlParseLimits {
    pub max_input_bytes: u64,
    pub max_depth: usize,
    pub max_nodes: u64,
    pub max_documents: u64,
}

impl Default for YamlParseLimits {
    fn default() -> Self {
        Self {
            max_input_bytes: 32 * 1024 * 1024,
            max_depth: 128,
            max_nodes: 1_000_000,
            max_documents: 1_000_000,
        }
    }
}

/// Writes one safe YAML 1.2 document. JSONL callers set `explicit_start=true`.
pub fn write_yaml_document(
    value: &Value,
    output: &mut impl Write,
    explicit_start: bool,
) -> Result<u64, CodecError> {
    let mut writer = CountingWriter::new(output);
    if explicit_start {
        writer.write_all(b"---\n").map_err(CodecError::OutputIo)?;
    }
    emit_value(value, &mut writer, 0)?;
    Ok(writer.bytes)
}

/// Writes one compact JSON document. JSON is a strict subset of the safe YAML
/// 1.2 surface accepted by this codec, so location-only context can avoid the
/// indentation and repeated field overhead of block YAML without adding a
/// second output language.
pub fn write_compact_yaml_document(
    value: &Value,
    output: &mut impl Write,
) -> Result<u64, CodecError> {
    let encoded =
        serde_json::to_vec(value).map_err(|error| CodecError::Encode(error.to_string()))?;
    output.write_all(&encoded).map_err(CodecError::OutputIo)?;
    output.write_all(b"\n").map_err(CodecError::OutputIo)?;
    usize_to_u64(
        encoded.len().checked_add(1).ok_or_else(|| {
            CodecError::Encode("compact YAML output byte count overflow".to_owned())
        })?,
    )
}

/// Parses emitted YAML back into generic JSON values while rejecting advanced YAML features.
pub fn parse_yaml_documents(input: &[u8]) -> Result<Vec<Value>, CodecError> {
    parse_yaml_documents_with_limits(input, YamlParseLimits::default())
}

/// Parses the safe YAML subset with explicit resource limits before recursive value assembly.
pub fn parse_yaml_documents_with_limits(
    input: &[u8],
    limits: YamlParseLimits,
) -> Result<Vec<Value>, CodecError> {
    parse_yaml_documents_mode(input, limits, false)
}

/// Parses safe YAML configuration, additionally accepting untagged plain strings.
pub fn parse_yaml_config_documents_with_limits(
    input: &[u8],
    limits: YamlParseLimits,
) -> Result<Vec<Value>, CodecError> {
    parse_yaml_documents_mode(input, limits, true)
}

fn parse_yaml_documents_mode(
    input: &[u8],
    limits: YamlParseLimits,
    allow_plain_strings: bool,
) -> Result<Vec<Value>, CodecError> {
    let input_bytes = usize_to_u64(input.len())?;
    if input_bytes > limits.max_input_bytes {
        return Err(CodecError::UnsafeYaml(format!(
            "input has {input_bytes} bytes, above limit {}",
            limits.max_input_bytes
        )));
    }
    if input.starts_with(&[0xef, 0xbb, 0xbf]) {
        return Err(CodecError::UnsafeYaml("UTF-8 BOM is forbidden".to_owned()));
    }
    let source = std::str::from_utf8(input).map_err(|error| CodecError::InvalidUtf8 {
        byte_offset: error.valid_up_to() as u64,
    })?;
    let mut receiver = EventSink::default();
    Parser::new_from_str(source)
        .load(&mut receiver, true)
        .map_err(|error| CodecError::InvalidYaml(error.to_string()))?;
    validate_event_limits(&receiver.events, limits)?;
    parse_event_stream(&mut receiver.events, allow_plain_strings)
}

fn validate_event_limits(
    events: &VecDeque<Event<'_>>,
    limits: YamlParseLimits,
) -> Result<(), CodecError> {
    let mut depth = 0_usize;
    let mut nodes = 0_u64;
    let mut documents = 0_u64;
    for event in events {
        match event {
            Event::DocumentStart(_) => {
                documents = documents.saturating_add(1);
                if documents > limits.max_documents {
                    return Err(CodecError::UnsafeYaml(format!(
                        "document count exceeds limit {}",
                        limits.max_documents
                    )));
                }
            }
            Event::Scalar(..) | Event::Alias(_) => {
                nodes = nodes.saturating_add(1);
            }
            Event::SequenceStart(..) | Event::MappingStart(..) => {
                nodes = nodes.saturating_add(1);
                depth = depth.saturating_add(1);
                if depth > limits.max_depth {
                    return Err(CodecError::UnsafeYaml(format!(
                        "nesting depth exceeds limit {}",
                        limits.max_depth
                    )));
                }
            }
            Event::SequenceEnd | Event::MappingEnd => {
                depth = depth.saturating_sub(1);
            }
            _ => {}
        }
        if nodes > limits.max_nodes {
            return Err(CodecError::UnsafeYaml(format!(
                "node count exceeds limit {}",
                limits.max_nodes
            )));
        }
    }
    Ok(())
}

fn emit_value(
    value: &Value,
    output: &mut CountingWriter<'_>,
    indent: usize,
) -> Result<(), CodecError> {
    match value {
        Value::Array(values) if !values.is_empty() => {
            for value in values {
                write_indent(output, indent)?;
                output.write_all(b"-").map_err(CodecError::OutputIo)?;
                if is_nonempty_collection(value) {
                    output.write_all(b"\n").map_err(CodecError::OutputIo)?;
                    emit_value(value, output, indent + 2)?;
                } else {
                    output.write_all(b" ").map_err(CodecError::OutputIo)?;
                    emit_scalar_line(value, output, indent + 2)?;
                }
            }
            Ok(())
        }
        Value::Object(values) if !values.is_empty() => {
            for (key, value) in values {
                write_indent(output, indent)?;
                write_quoted(key, output)?;
                output.write_all(b":").map_err(CodecError::OutputIo)?;
                if is_nonempty_collection(value) {
                    output.write_all(b"\n").map_err(CodecError::OutputIo)?;
                    emit_value(value, output, indent + 2)?;
                } else {
                    output.write_all(b" ").map_err(CodecError::OutputIo)?;
                    emit_scalar_line(value, output, indent + 2)?;
                }
            }
            Ok(())
        }
        _ => emit_scalar_line(value, output, indent),
    }
}

fn emit_scalar_line(
    value: &Value,
    output: &mut CountingWriter<'_>,
    content_indent: usize,
) -> Result<(), CodecError> {
    match value {
        Value::Null => output.write_all(b"null").map_err(CodecError::OutputIo)?,
        Value::Bool(value) => output
            .write_all(if *value { b"true" } else { b"false" })
            .map_err(CodecError::OutputIo)?,
        Value::Number(value) => output
            .write_all(value.to_string().as_bytes())
            .map_err(CodecError::OutputIo)?,
        Value::String(value) if can_use_literal(value) => {
            let chomping: &[u8] = if value.ends_with('\n') { b"|" } else { b"|-" };
            output.write_all(chomping).map_err(CodecError::OutputIo)?;
            output.write_all(b"\n").map_err(CodecError::OutputIo)?;
            for line in value.split_terminator('\n') {
                write_indent(output, content_indent)?;
                output
                    .write_all(line.as_bytes())
                    .map_err(CodecError::OutputIo)?;
                output.write_all(b"\n").map_err(CodecError::OutputIo)?;
            }
            return Ok(());
        }
        Value::String(value) => write_quoted(value, output)?,
        Value::Array(values) if values.is_empty() => {
            output.write_all(b"[]").map_err(CodecError::OutputIo)?;
        }
        Value::Object(values) if values.is_empty() => {
            output.write_all(b"{}").map_err(CodecError::OutputIo)?;
        }
        Value::Array(_) | Value::Object(_) => {
            return Err(CodecError::Encode(
                "non-empty collection reached scalar emitter".to_owned(),
            ));
        }
    }
    output.write_all(b"\n").map_err(CodecError::OutputIo)
}

fn write_quoted(value: &str, output: &mut CountingWriter<'_>) -> Result<(), CodecError> {
    output.write_all(b"\"").map_err(CodecError::OutputIo)?;
    for character in value.chars() {
        let escape: Option<&[u8]> = match character {
            '"' => Some(b"\\\""),
            '\\' => Some(b"\\\\"),
            '\u{0008}' => Some(b"\\b"),
            '\u{000c}' => Some(b"\\f"),
            '\n' => Some(b"\\n"),
            '\r' => Some(b"\\r"),
            '\t' => Some(b"\\t"),
            _ => None,
        };
        if let Some(escape) = escape {
            output.write_all(escape).map_err(CodecError::OutputIo)?;
        } else if character < ' '
            || matches!(
                character,
                '\u{007f}'
                    ..='\u{009f}' | '\u{2028}' | '\u{2029}' | '\u{feff}' | '\u{fffe}' | '\u{ffff}'
            )
        {
            let escaped = format!("\\u{:04X}", u32::from(character));
            output
                .write_all(escaped.as_bytes())
                .map_err(CodecError::OutputIo)?;
        } else {
            let mut buffer = [0_u8; 4];
            output
                .write_all(character.encode_utf8(&mut buffer).as_bytes())
                .map_err(CodecError::OutputIo)?;
        }
    }
    output.write_all(b"\"").map_err(CodecError::OutputIo)
}

fn write_indent(output: &mut CountingWriter<'_>, indent: usize) -> Result<(), CodecError> {
    const SPACES: &[u8; 32] = b"                                ";
    let mut remaining = indent;
    while remaining > 0 {
        let count = remaining.min(SPACES.len());
        output
            .write_all(&SPACES[..count])
            .map_err(CodecError::OutputIo)?;
        remaining -= count;
    }
    Ok(())
}

fn is_nonempty_collection(value: &Value) -> bool {
    matches!(value, Value::Array(values) if !values.is_empty())
        || matches!(value, Value::Object(values) if !values.is_empty())
}

fn can_use_literal(value: &str) -> bool {
    value.contains('\n')
        && value.chars().any(|character| character != '\n')
        && !value.ends_with("\n\n")
        && value
            .split('\n')
            .find(|line| !line.is_empty())
            .is_some_and(|line| !line.starts_with(' ') && !line.starts_with('\t'))
        && value.chars().all(|character| {
            matches!(character, '\n' | '\t' | ' '..='~')
                || (character >= '\u{00a0}'
                    && !matches!(
                        character,
                        '\u{2028}' | '\u{2029}' | '\u{feff}' | '\u{fffe}' | '\u{ffff}'
                    ))
        })
}

struct CountingWriter<'a> {
    inner: &'a mut dyn Write,
    bytes: u64,
}

impl<'a> CountingWriter<'a> {
    fn new(inner: &'a mut dyn Write) -> Self {
        Self { inner, bytes: 0 }
    }
}

impl Write for CountingWriter<'_> {
    fn write(&mut self, buffer: &[u8]) -> std::io::Result<usize> {
        let count = self.inner.write(buffer)?;
        self.bytes = self
            .bytes
            .checked_add(usize_to_u64(count).map_err(std::io::Error::other)?)
            .ok_or_else(|| std::io::Error::other("YAML output byte count overflow"))?;
        Ok(count)
    }

    fn flush(&mut self) -> std::io::Result<()> {
        self.inner.flush()
    }
}

#[derive(Default)]
struct EventSink<'input> {
    events: VecDeque<Event<'input>>,
}

impl<'input> EventReceiver<'input> for EventSink<'input> {
    fn on_event(&mut self, event: Event<'input>) {
        self.events.push_back(event);
    }
}

fn parse_event_stream(
    events: &mut VecDeque<Event<'_>>,
    allow_plain_strings: bool,
) -> Result<Vec<Value>, CodecError> {
    expect_event(events, |event| matches!(event, Event::StreamStart))?;
    let mut documents = Vec::new();
    while matches!(events.front(), Some(Event::DocumentStart(_))) {
        events.pop_front();
        documents.push(parse_value(events, allow_plain_strings)?);
        expect_event(events, |event| matches!(event, Event::DocumentEnd))?;
    }
    expect_event(events, |event| matches!(event, Event::StreamEnd))?;
    if !events.is_empty() {
        return Err(CodecError::InvalidYaml(
            "events remain after YAML stream end".to_owned(),
        ));
    }
    Ok(documents)
}

fn parse_value(
    events: &mut VecDeque<Event<'_>>,
    allow_plain_strings: bool,
) -> Result<Value, CodecError> {
    match events.pop_front() {
        Some(Event::Alias(_)) => Err(CodecError::UnsafeYaml("alias is forbidden".to_owned())),
        Some(Event::Scalar(value, style, 0, None)) => {
            parse_scalar(value.as_ref(), style, allow_plain_strings)
        }
        Some(Event::Scalar(_, _, anchor, tag)) => Err(CodecError::UnsafeYaml(format!(
            "scalar anchor/tag is forbidden: anchor={anchor}, tag={tag:?}"
        ))),
        Some(Event::SequenceStart(0, None)) => parse_sequence(events, allow_plain_strings),
        Some(Event::SequenceStart(anchor, tag)) => Err(CodecError::UnsafeYaml(format!(
            "sequence anchor/tag is forbidden: anchor={anchor}, tag={tag:?}"
        ))),
        Some(Event::MappingStart(0, None)) => parse_mapping(events, allow_plain_strings),
        Some(Event::MappingStart(anchor, tag)) => Err(CodecError::UnsafeYaml(format!(
            "mapping anchor/tag is forbidden: anchor={anchor}, tag={tag:?}"
        ))),
        Some(event) => Err(CodecError::InvalidYaml(format!(
            "unexpected YAML value event: {event:?}"
        ))),
        None => Err(CodecError::InvalidYaml("missing YAML value".to_owned())),
    }
}

fn parse_scalar(
    value: &str,
    style: ScalarStyle,
    allow_plain_strings: bool,
) -> Result<Value, CodecError> {
    if style == ScalarStyle::Plain {
        match serde_json::from_str(value) {
            Ok(parsed @ (Value::Null | Value::Bool(_) | Value::Number(_))) => Ok(parsed),
            _ if allow_plain_strings => Ok(Value::String(value.to_owned())),
            _ => Err(CodecError::InvalidYaml(format!(
                "plain scalar is outside the JSON-compatible YAML core subset: {value:?}"
            ))),
        }
    } else {
        Ok(Value::String(value.to_owned()))
    }
}

fn parse_sequence(
    events: &mut VecDeque<Event<'_>>,
    allow_plain_strings: bool,
) -> Result<Value, CodecError> {
    let mut values = Vec::new();
    while !matches!(events.front(), Some(Event::SequenceEnd)) {
        if events.is_empty() {
            return Err(CodecError::InvalidYaml(
                "unterminated YAML sequence".to_owned(),
            ));
        }
        values.push(parse_value(events, allow_plain_strings)?);
    }
    events.pop_front();
    Ok(Value::Array(values))
}

fn parse_mapping(
    events: &mut VecDeque<Event<'_>>,
    allow_plain_strings: bool,
) -> Result<Value, CodecError> {
    let mut values = Map::new();
    while !matches!(events.front(), Some(Event::MappingEnd)) {
        let key = match events.pop_front() {
            Some(Event::Scalar(key, style, 0, None)) => {
                if style == ScalarStyle::Plain && key == "<<" {
                    return Err(CodecError::UnsafeYaml("merge key is forbidden".to_owned()));
                }
                key.into_owned()
            }
            Some(event) => {
                return Err(CodecError::UnsafeYaml(format!(
                    "mapping key must be an untagged, unanchored scalar: {event:?}"
                )))
            }
            None => return Err(CodecError::InvalidYaml("missing mapping key".to_owned())),
        };
        if values.contains_key(&key) {
            return Err(CodecError::UnsafeYaml(format!(
                "duplicate mapping key: {key:?}"
            )));
        }
        values.insert(key, parse_value(events, allow_plain_strings)?);
    }
    events.pop_front();
    Ok(Value::Object(values))
}

fn expect_event(
    events: &mut VecDeque<Event<'_>>,
    predicate: impl FnOnce(&Event<'_>) -> bool,
) -> Result<(), CodecError> {
    match events.pop_front() {
        Some(event) if predicate(&event) => Ok(()),
        Some(event) => Err(CodecError::InvalidYaml(format!(
            "unexpected YAML event: {event:?}"
        ))),
        None => Err(CodecError::InvalidYaml(
            "unexpected end of YAML event stream".to_owned(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{parse_yaml_documents, write_compact_yaml_document, write_yaml_document};
    use crate::codec::CodecError;

    #[test]
    fn quoted_merge_key_is_data_but_plain_merge_is_rejected() {
        assert_eq!(
            parse_yaml_documents(b"\"<<\": 1\n").expect("quoted merge key"),
            vec![json!({"<<": 1})]
        );
        assert!(matches!(
            parse_yaml_documents(b"<<: {}\n"),
            Err(CodecError::UnsafeYaml(_))
        ));
    }

    #[test]
    fn emitter_uses_literal_only_when_line_endings_remain_exact() {
        let values = ["\n", "one\ntwo", "one\ntwo\n", "one\ntwo\n\n", "one\r\ntwo"];
        for value in values {
            let expected = json!(value);
            let mut yaml = Vec::new();
            write_yaml_document(&expected, &mut yaml, false).expect("emit YAML");
            let actual = parse_yaml_documents(&yaml).expect("parse YAML");
            assert_eq!(actual, vec![expected]);
            assert_eq!(yaml.last(), Some(&b'\n'));
        }
    }

    #[test]
    fn emitter_quotes_multiline_text_whose_first_content_line_is_indented() {
        let expected = json!(" leading\nnext");
        let mut yaml = Vec::new();
        write_yaml_document(&expected, &mut yaml, false).expect("emit quoted YAML");
        assert!(yaml.starts_with(b"\""));
        assert_eq!(
            parse_yaml_documents(&yaml).expect("parse quoted YAML"),
            vec![expected]
        );
    }

    #[test]
    fn quoted_scalars_escape_yaml_line_breaks_and_control_characters() {
        let expected = json!({
            "value": "nul:\u{0000} del:\u{007f} nel:\u{0085} ls:\u{2028} ps:\u{2029} bom:\u{feff} nonchars:\u{fffe}\u{ffff}"
        });
        let mut yaml = Vec::new();
        write_yaml_document(&expected, &mut yaml, false).expect("emit escaped YAML");
        assert!(yaml.windows(6).any(|window| window == b"\\u0085"));
        assert!(yaml.windows(6).any(|window| window == b"\\u2028"));
        assert_eq!(
            parse_yaml_documents(&yaml).expect("parse escaped YAML"),
            vec![expected]
        );
    }

    #[test]
    fn compact_json_is_accepted_as_the_same_safe_yaml_value() {
        let expected = json!({
            "_sgy": {"profile": "locations", "complete": true},
            "results": ["src/main.ts:1:2-3:4"]
        });
        let mut yaml = Vec::new();
        let bytes = write_compact_yaml_document(&expected, &mut yaml).expect("compact YAML");
        assert_eq!(usize::try_from(bytes).expect("byte count"), yaml.len());
        assert_eq!(
            parse_yaml_documents(&yaml).expect("parse compact YAML"),
            vec![expected]
        );
    }
}
