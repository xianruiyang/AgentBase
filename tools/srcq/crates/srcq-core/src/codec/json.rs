use std::{collections::HashSet, io::BufRead};

use serde_json::Value;

use super::{usize_to_u64, ByteSpan, CodecError};

/// One generic JSON value and its location in the native byte stream.
#[derive(Clone, Debug, PartialEq)]
pub struct SourceRecord {
    pub ordinal: u64,
    pub span: ByteSpan,
    pub value: Value,
}

/// Parses one compact/pretty JSON value after rejecting duplicate object keys.
pub fn parse_single_json(input: &[u8]) -> Result<SourceRecord, CodecError> {
    let (start, end) = trim_json_whitespace(input);
    if start == end {
        return Err(CodecError::InvalidJson {
            ordinal: 0,
            span: ByteSpan::new(0, usize_to_u64(input.len())?),
            message: "expected one JSON value, found empty input".to_owned(),
        });
    }
    parse_record(&input[start..end], 0, usize_to_u64(start)?)
}

/// Streaming JSONL reader. Only one physical line/value is retained at a time.
#[derive(Debug)]
pub struct JsonLines<R> {
    reader: R,
    buffer: Vec<u8>,
    consumed: u64,
    next_ordinal: u64,
    finished: bool,
}

impl<R: BufRead> JsonLines<R> {
    #[must_use]
    pub fn new(reader: R) -> Self {
        Self {
            reader,
            buffer: Vec::new(),
            consumed: 0,
            next_ordinal: 0,
            finished: false,
        }
    }

    #[must_use]
    pub const fn consumed_bytes(&self) -> u64 {
        self.consumed
    }

    fn read_record(&mut self) -> Result<Option<SourceRecord>, CodecError> {
        loop {
            self.buffer.clear();
            let line_start = self.consumed;
            let count = self
                .reader
                .read_until(b'\n', &mut self.buffer)
                .map_err(CodecError::InputIo)?;
            if count == 0 {
                self.finished = true;
                return Ok(None);
            }
            self.consumed = self
                .consumed
                .checked_add(usize_to_u64(count)?)
                .ok_or_else(|| CodecError::Encode("input byte offset overflow".to_owned()))?;
            let (start, end) = trim_json_whitespace(&self.buffer);
            if start == end {
                continue;
            }
            let record_offset = line_start
                .checked_add(usize_to_u64(start)?)
                .ok_or_else(|| CodecError::Encode("record byte offset overflow".to_owned()))?;
            let record = parse_record(&self.buffer[start..end], self.next_ordinal, record_offset)?;
            self.next_ordinal = self
                .next_ordinal
                .checked_add(1)
                .ok_or_else(|| CodecError::Encode("record ordinal overflow".to_owned()))?;
            return Ok(Some(record));
        }
    }
}

impl<R: BufRead> Iterator for JsonLines<R> {
    type Item = Result<SourceRecord, CodecError>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.finished {
            return None;
        }
        match self.read_record() {
            Ok(Some(record)) => Some(Ok(record)),
            Ok(None) => None,
            Err(error) => {
                self.finished = true;
                Some(Err(error))
            }
        }
    }
}

fn parse_record(input: &[u8], ordinal: u64, base_offset: u64) -> Result<SourceRecord, CodecError> {
    let source = std::str::from_utf8(input).map_err(|error| CodecError::InvalidUtf8 {
        byte_offset: base_offset.saturating_add(error.valid_up_to() as u64),
    })?;
    DuplicateScanner::new(source, ordinal, base_offset).validate()?;
    let mut value = serde_json::from_str(source).map_err(|error| CodecError::InvalidJson {
        ordinal,
        span: ByteSpan::new(base_offset, base_offset.saturating_add(input.len() as u64)),
        message: error.to_string(),
    })?;
    // `preserve_order` is required by constructed context envelopes, while
    // native lossless output has an established recursively sorted golden.
    // Keep that codec boundary stable instead of changing prior YAML bytes.
    sort_mapping_keys(&mut value);
    Ok(SourceRecord {
        ordinal,
        span: ByteSpan::new(base_offset, base_offset.saturating_add(input.len() as u64)),
        value,
    })
}

fn sort_mapping_keys(value: &mut Value) {
    match value {
        Value::Object(mapping) => {
            for child in mapping.values_mut() {
                sort_mapping_keys(child);
            }
            let mut entries: Vec<(String, Value)> = std::mem::take(mapping).into_iter().collect();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            mapping.extend(entries);
        }
        Value::Array(items) => {
            for item in items {
                sort_mapping_keys(item);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn trim_json_whitespace(input: &[u8]) -> (usize, usize) {
    let mut start = 0;
    while start < input.len() && is_json_whitespace(input[start]) {
        start += 1;
    }
    let mut end = input.len();
    while end > start && is_json_whitespace(input[end - 1]) {
        end -= 1;
    }
    (start, end)
}

const fn is_json_whitespace(byte: u8) -> bool {
    matches!(byte, b' ' | b'\t' | b'\r' | b'\n')
}

struct DuplicateScanner<'a> {
    source: &'a str,
    bytes: &'a [u8],
    position: usize,
    ordinal: u64,
    base_offset: u64,
    depth: usize,
}

impl<'a> DuplicateScanner<'a> {
    fn new(source: &'a str, ordinal: u64, base_offset: u64) -> Self {
        Self {
            source,
            bytes: source.as_bytes(),
            position: 0,
            ordinal,
            base_offset,
            depth: 0,
        }
    }

    fn validate(mut self) -> Result<(), CodecError> {
        self.skip_whitespace();
        self.value()?;
        self.skip_whitespace();
        if self.position != self.bytes.len() {
            return self.invalid("trailing characters after JSON value");
        }
        Ok(())
    }

    fn value(&mut self) -> Result<(), CodecError> {
        self.skip_whitespace();
        match self.peek() {
            Some(b'{') => self.collection(Self::object),
            Some(b'[') => self.collection(Self::array),
            Some(b'\"') => self.string().map(drop),
            Some(b't') => self.keyword(b"true"),
            Some(b'f') => self.keyword(b"false"),
            Some(b'n') => self.keyword(b"null"),
            Some(b'-' | b'0'..=b'9') => self.number(),
            _ => self.invalid("expected JSON value"),
        }
    }

    fn collection(
        &mut self,
        parse: fn(&mut Self) -> Result<(), CodecError>,
    ) -> Result<(), CodecError> {
        let Some(depth) = self.depth.checked_add(1) else {
            return self.invalid("JSON nesting depth overflow");
        };
        self.depth = depth;
        if self.depth > 128 {
            self.depth -= 1;
            return self.invalid("JSON nesting depth exceeds 128");
        }
        let result = parse(self);
        self.depth -= 1;
        result
    }

    fn object(&mut self) -> Result<(), CodecError> {
        self.position += 1;
        self.skip_whitespace();
        if self.take(b'}') {
            return Ok(());
        }
        let mut keys = HashSet::new();
        loop {
            self.skip_whitespace();
            let key_offset = self.position;
            let key = self.string()?;
            if !keys.insert(key.clone()) {
                return Err(CodecError::DuplicateJsonKey {
                    ordinal: self.ordinal,
                    key,
                    byte_offset: self.base_offset.saturating_add(key_offset as u64),
                });
            }
            self.skip_whitespace();
            self.expect(b':', "expected ':' after object key")?;
            self.value()?;
            self.skip_whitespace();
            if self.take(b'}') {
                return Ok(());
            }
            self.expect(b',', "expected ',' or '}' after object value")?;
        }
    }

    fn array(&mut self) -> Result<(), CodecError> {
        self.position += 1;
        self.skip_whitespace();
        if self.take(b']') {
            return Ok(());
        }
        loop {
            self.value()?;
            self.skip_whitespace();
            if self.take(b']') {
                return Ok(());
            }
            self.expect(b',', "expected ',' or ']' after array value")?;
        }
    }

    fn string(&mut self) -> Result<String, CodecError> {
        if !self.take(b'\"') {
            return self.invalid("expected quoted JSON object key or string");
        }
        let start = self.position - 1;
        while let Some(byte) = self.peek() {
            match byte {
                b'\"' => {
                    self.position += 1;
                    return serde_json::from_str(&self.source[start..self.position]).map_err(
                        |error| CodecError::InvalidJson {
                            ordinal: self.ordinal,
                            span: ByteSpan::new(
                                self.base_offset.saturating_add(start as u64),
                                self.base_offset.saturating_add(self.position as u64),
                            ),
                            message: error.to_string(),
                        },
                    );
                }
                b'\\' => {
                    self.position += 1;
                    if self.position >= self.bytes.len() {
                        return self.invalid("unterminated JSON escape");
                    }
                    self.position += 1;
                }
                0x00..=0x1f => return self.invalid("control byte in JSON string"),
                _ => self.position += 1,
            }
        }
        self.invalid("unterminated JSON string")
    }

    fn keyword(&mut self, keyword: &[u8]) -> Result<(), CodecError> {
        if self.bytes.get(self.position..self.position + keyword.len()) == Some(keyword) {
            self.position += keyword.len();
            Ok(())
        } else {
            self.invalid("invalid JSON literal")
        }
    }

    fn number(&mut self) -> Result<(), CodecError> {
        let start = self.position;
        while matches!(
            self.peek(),
            Some(b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9')
        ) {
            self.position += 1;
        }
        if self.position == start {
            self.invalid("invalid JSON number")
        } else {
            Ok(())
        }
    }

    fn expect(&mut self, expected: u8, message: &str) -> Result<(), CodecError> {
        if self.take(expected) {
            Ok(())
        } else {
            self.invalid(message)
        }
    }

    fn take(&mut self, expected: u8) -> bool {
        if self.peek() == Some(expected) {
            self.position += 1;
            true
        } else {
            false
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.position).copied()
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\r' | b'\n')) {
            self.position += 1;
        }
    }

    fn invalid<T>(&self, message: &str) -> Result<T, CodecError> {
        Err(CodecError::InvalidJson {
            ordinal: self.ordinal,
            span: ByteSpan::new(
                self.base_offset,
                self.base_offset.saturating_add(self.bytes.len() as u64),
            ),
            message: format!("{message} at byte {}", self.position),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::parse_single_json;
    use crate::codec::CodecError;

    #[test]
    fn duplicate_scanner_decodes_escaped_keys() {
        let error = parse_single_json(br#"{"key": 1, "\u006bey": 2}"#)
            .expect_err("escaped duplicate must be rejected");
        assert!(matches!(
            error,
            CodecError::DuplicateJsonKey { key, .. } if key == "key"
        ));
    }

    #[test]
    fn nested_objects_have_independent_key_sets() {
        parse_single_json(br#"{"key": 1, "nested": {"key": 2}}"#)
            .expect("same key in nested object is valid");
    }
}
