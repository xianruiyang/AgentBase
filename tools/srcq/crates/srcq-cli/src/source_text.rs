use std::path::Path;

/// Shared decoding contract for Windows source files. Keep UTF-8 BOM handling
/// with the consumer so existing symbol byte offsets are unchanged.
pub(crate) fn decode(file: &Path, source: Vec<u8>) -> Result<String, String> {
    let utf16 = source
        .strip_prefix(&[0xff, 0xfe])
        .map(|bytes| (bytes, true, "UTF-16LE"))
        .or_else(|| {
            source
                .strip_prefix(&[0xfe, 0xff])
                .map(|bytes| (bytes, false, "UTF-16BE"))
        });
    if let Some((bytes, little_endian, name)) = utf16 {
        if bytes.len() % 2 != 0 {
            return Err(format!(
                "{name} source has an incomplete code unit: {}",
                file.display()
            ));
        }
        let units: Vec<_> = bytes
            .chunks_exact(2)
            .map(|chunk| {
                if little_endian {
                    u16::from_le_bytes([chunk[0], chunk[1]])
                } else {
                    u16::from_be_bytes([chunk[0], chunk[1]])
                }
            })
            .collect();
        return String::from_utf16(&units)
            .map_err(|error| format!("cannot decode {name} source {}: {error}", file.display()));
    }
    if source.contains(&0) {
        return Err(format!(
            "source contains NUL bytes; UTF-16 text requires a BOM: {}",
            file.display()
        ));
    }
    match String::from_utf8(source) {
        Ok(text) => Ok(text),
        Err(error) => {
            let bytes = error.into_bytes();
            let (decoded, had_errors) = encoding_rs::GBK.decode_without_bom_handling(&bytes);
            if had_errors || decoded.contains('\0') {
                Err(format!(
                    "source is not valid UTF-8, BOM-marked UTF-16, or Windows GBK text: {}",
                    file.display()
                ))
            } else {
                Ok(decoded.into_owned())
            }
        }
    }
}
