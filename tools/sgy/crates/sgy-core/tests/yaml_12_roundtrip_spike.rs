//! Dependency spike only. The production lossless codec belongs to P1-005.

use std::collections::VecDeque;

use saphyr_parser::{Event, EventReceiver, Parser, ScalarStyle};
use serde_json::{Map, Value};

#[derive(Default)]
struct EventSink<'input> {
    events: VecDeque<Event<'input>>,
}

impl<'input> EventReceiver<'input> for EventSink<'input> {
    fn on_event(&mut self, event: Event<'input>) {
        self.events.push_back(event);
    }
}

fn parse_yaml_subset(source: &str) -> Result<Value, String> {
    let mut sink = EventSink::default();
    Parser::new_from_str(source)
        .load(&mut sink, true)
        .map_err(|error| error.to_string())?;

    expect_event(&mut sink.events, |event| {
        matches!(event, Event::StreamStart)
    })?;
    expect_event(&mut sink.events, |event| {
        matches!(event, Event::DocumentStart(_))
    })?;
    let value = parse_value(&mut sink.events)?;
    expect_event(&mut sink.events, |event| {
        matches!(event, Event::DocumentEnd)
    })?;
    expect_event(&mut sink.events, |event| matches!(event, Event::StreamEnd))?;
    Ok(value)
}

fn expect_event<'input>(
    events: &mut VecDeque<Event<'input>>,
    predicate: impl FnOnce(&Event<'input>) -> bool,
) -> Result<(), String> {
    match events.pop_front() {
        Some(event) if predicate(&event) => Ok(()),
        Some(event) => Err(format!("unexpected YAML event: {event:?}")),
        None => Err("unexpected end of YAML event stream".to_owned()),
    }
}

fn parse_value(events: &mut VecDeque<Event<'_>>) -> Result<Value, String> {
    match events.pop_front() {
        Some(Event::Scalar(value, style, 0, None)) => parse_scalar(value.as_ref(), style),
        Some(Event::SequenceStart(0, None)) => parse_sequence(events),
        Some(Event::MappingStart(0, None)) => parse_mapping(events),
        Some(event) => Err(format!("unsupported or unsafe YAML event: {event:?}")),
        None => Err("missing YAML value".to_owned()),
    }
}

fn parse_scalar(value: &str, style: ScalarStyle) -> Result<Value, String> {
    if style == ScalarStyle::Plain {
        serde_json::from_str(value).map_err(|error| error.to_string())
    } else {
        Ok(Value::String(value.to_owned()))
    }
}

fn parse_sequence(events: &mut VecDeque<Event<'_>>) -> Result<Value, String> {
    let mut values = Vec::new();
    while !matches!(events.front(), Some(Event::SequenceEnd)) {
        values.push(parse_value(events)?);
    }
    events.pop_front();
    Ok(Value::Array(values))
}

fn parse_mapping(events: &mut VecDeque<Event<'_>>) -> Result<Value, String> {
    let mut values = Map::new();
    while !matches!(events.front(), Some(Event::MappingEnd)) {
        let key = match events.pop_front() {
            Some(Event::Scalar(key, _, 0, None)) => key.into_owned(),
            Some(event) => return Err(format!("unsupported YAML mapping key: {event:?}")),
            None => return Err("missing YAML mapping key".to_owned()),
        };
        if values.contains_key(&key) {
            return Err(format!("duplicate mapping key: {key}"));
        }
        values.insert(key, parse_value(events)?);
    }
    events.pop_front();
    Ok(Value::Object(values))
}

#[test]
fn json_is_a_lossless_yaml_12_emission_baseline() -> Result<(), String> {
    let source = r#"{
  "huge_integer": 1234567890123456789012345678901234567890,
  "tiny_decimal": 0.000000000000000000000000000000000000000123,
  "unicode": "中文 😀 é",
  "multiline": "first\nsecond\n",
  "null_value": null,
  "empty_array": [],
  "empty_object": {}
}"#;
    let expected: Value = serde_json::from_str(source).map_err(|error| error.to_string())?;
    let yaml = serde_json::to_string_pretty(&expected).map_err(|error| error.to_string())?;
    let actual = parse_yaml_subset(&yaml)?;

    assert_eq!(actual, expected);
    assert_eq!(
        actual["huge_integer"].to_string(),
        "1234567890123456789012345678901234567890"
    );
    assert_eq!(
        actual["tiny_decimal"].to_string(),
        "0.000000000000000000000000000000000000000123"
    );
    Ok(())
}

#[test]
fn yaml_literal_block_round_trips_multiline_unicode() -> Result<(), String> {
    let yaml = "message: |\n  第一行 😀\n  second line\n";
    let actual = parse_yaml_subset(yaml)?;
    assert_eq!(actual["message"], "第一行 😀\nsecond line\n");
    Ok(())
}

#[test]
fn parser_exposes_events_needed_for_security_rejection() {
    let cases = ["value: &anchor 1\ncopy: *anchor\n", "value: !!str tagged\n"];
    for source in cases {
        let error = parse_yaml_subset(source).expect_err("unsafe YAML feature must be rejected");
        assert!(error.contains("unsupported or unsafe YAML event"));
    }
}
