use std::io::{BufRead, Write};

use super::{parse_single_json, write_yaml_document, CodecError, JsonLines};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JsonInputKind {
    /// One compact/pretty JSON value, including a SARIF object or result array.
    Single,
    /// One JSON value per non-empty physical line.
    Lines,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TranscodeStats {
    pub records: u64,
    pub input_bytes: u64,
    pub output_bytes: u64,
}

pub fn transcode_lossless<R: BufRead, W: Write>(
    mut input: R,
    output: &mut W,
    kind: JsonInputKind,
) -> Result<TranscodeStats, CodecError> {
    match kind {
        JsonInputKind::Single => {
            let mut bytes = Vec::new();
            input.read_to_end(&mut bytes).map_err(CodecError::InputIo)?;
            let record = parse_single_json(&bytes)?;
            let output_bytes = write_yaml_document(&record.value, output, false)?;
            Ok(TranscodeStats {
                records: 1,
                input_bytes: u64::try_from(bytes.len())
                    .map_err(|error| CodecError::Encode(error.to_string()))?,
                output_bytes,
            })
        }
        JsonInputKind::Lines => {
            let mut lines = JsonLines::new(input);
            let mut records = 0_u64;
            let mut output_bytes = 0_u64;
            for record in lines.by_ref() {
                let record = record?;
                output_bytes = output_bytes
                    .checked_add(write_yaml_document(&record.value, output, true)?)
                    .ok_or_else(|| CodecError::Encode("output byte count overflow".to_owned()))?;
                records = records
                    .checked_add(1)
                    .ok_or_else(|| CodecError::Encode("record count overflow".to_owned()))?;
            }
            Ok(TranscodeStats {
                records,
                input_bytes: lines.consumed_bytes(),
                output_bytes,
            })
        }
    }
}
