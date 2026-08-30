use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::cpp::{DefinitionCandidate, DefinitionRole, SourcePosition, SourceRange};
use super::scope::SourceUniverse;

pub(crate) fn occurrence_rules(ast_language: &str, target: &str, kinds: &[&str]) -> String {
    let kinds = kinds
        .iter()
        .map(|kind| format!("        - kind: {kind}"))
        .collect::<Vec<_>>()
        .join("\n");
    format!(
        "id: srcq.generic.occurrence\nlanguage: {ast_language}\nrule:\n  all:\n    - any:\n{kinds}\n    - regex: '^{}$'\nseverity: info\nmessage: source occurrence candidate",
        regex_escape(target.rsplit("::").next().unwrap_or(target))
    )
}

pub(crate) fn call_rules(ast_language: &str, kinds: &[&str]) -> String {
    let kinds = kinds
        .iter()
        .map(|kind| format!("      - kind: {kind}"))
        .collect::<Vec<_>>()
        .join("\n");
    format!(
        "id: srcq.generic.call\nlanguage: {ast_language}\nrule:\n  any:\n{kinds}\nseverity: info\nmessage: direct call candidate"
    )
}

pub(crate) fn containing_function_rules(
    ast_language: &str,
    target: &str,
    kinds: &[&str],
) -> String {
    let kinds = kinds
        .iter()
        .map(|kind| format!("        - kind: {kind}"))
        .collect::<Vec<_>>()
        .join("\n");
    format!(
        "id: srcq.generic.containing-function\nlanguage: {ast_language}\nrule:\n  all:\n    - any:\n{kinds}\n    - has:\n        stopBy: end\n        regex: '^{}$'\nseverity: info\nmessage: containing function candidate",
        regex_escape(target.rsplit("::").next().unwrap_or(target))
    )
}

pub(crate) fn parse_call_stream(bytes: &[u8], cwd: &Path) -> Result<super::cpp::CallScan, String> {
    let calls = parse_scan_records(bytes, cwd)?
        .into_iter()
        .map(|record| {
            let (callee, dispatch) = direct_callee(&record.text);
            super::cpp::DirectCallCandidate {
                file: record.file,
                range: record.range,
                callee,
                dispatch,
                receiver: None,
                receiver_type: None,
            }
        })
        .collect();
    Ok(super::cpp::CallScan::calls_only(calls))
}

pub(crate) fn parse_function_owner_stream(
    bytes: &[u8],
    cwd: &Path,
    language: &str,
) -> Result<Vec<super::cpp::FunctionOwnerCandidate>, String> {
    let mut owners = Vec::new();
    for record in parse_scan_records(bytes, cwd)? {
        let Some(name) = function_name(language, &record.text) else {
            continue;
        };
        let signature = record
            .text
            .lines()
            .find(|line| !line.trim().is_empty())
            .unwrap_or(&record.text)
            .trim()
            .to_owned();
        owners.push(super::cpp::FunctionOwnerCandidate {
            file: record.file,
            range: record.range,
            name,
            signature,
            definition: None,
        });
    }
    Ok(owners)
}

struct ScanRecord {
    file: PathBuf,
    range: SourceRange,
    text: String,
}

fn parse_scan_records(bytes: &[u8], cwd: &Path) -> Result<Vec<ScanRecord>, String> {
    let stream = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep relation output was not UTF-8".to_owned())?;
    let mut records = Vec::new();
    for (index, line) in stream.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep relation JSON at record {}: {error}",
                index + 1
            )
        })?;
        let raw_file = value
            .get("file")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep relation record is missing file".to_owned())?;
        let file = PathBuf::from(raw_file);
        let file = if file.is_absolute() {
            file
        } else {
            cwd.join(file)
        };
        let file = fs::canonicalize(&file).unwrap_or(file);
        let range = value
            .get("range")
            .ok_or_else(|| "ast-grep relation record is missing range".to_owned())?;
        records.push(ScanRecord {
            file,
            range: SourceRange {
                start: parse_position(
                    range
                        .get("start")
                        .ok_or_else(|| "ast-grep relation range is missing start".to_owned())?,
                )?,
                end: parse_position(
                    range
                        .get("end")
                        .ok_or_else(|| "ast-grep relation range is missing end".to_owned())?,
                )?,
            },
            text: value
                .get("text")
                .and_then(Value::as_str)
                .ok_or_else(|| "ast-grep relation record is missing text".to_owned())?
                .to_owned(),
        });
    }
    Ok(records)
}

fn direct_callee(text: &str) -> (String, &'static str) {
    let text = text.trim();
    let Some(open) = outer_call_open(text) else {
        return ("<indirect>".to_owned(), "unknown");
    };
    let mut callee = text[..open].trim();
    if let Some(stripped) = callee.strip_prefix("new ") {
        callee = stripped.trim();
    }
    if callee.contains('.') || callee.contains("->") {
        let member = callee.rsplit(['.', '>']).next().unwrap_or(callee).trim();
        if !member.is_empty() && member.chars().all(is_identifier) {
            return (member.to_owned(), "member-candidate");
        }
    }
    if callee.is_empty()
        || callee
            .chars()
            .any(|character| matches!(character, '(' | ')' | '[' | ']' | '{' | '}'))
    {
        return ("<indirect>".to_owned(), "unknown");
    }
    if callee.contains('.') || callee.contains("->") {
        return (
            callee
                .rsplit(['.', '>'])
                .next()
                .unwrap_or(callee)
                .to_owned(),
            "member-candidate",
        );
    }
    (callee.to_owned(), "direct-candidate")
}

fn outer_call_open(text: &str) -> Option<usize> {
    let bytes = text.as_bytes();
    for open in bytes
        .iter()
        .enumerate()
        .filter_map(|(index, byte)| (*byte == b'(').then_some(index))
    {
        let mut depth = 0_usize;
        for (index, byte) in bytes.iter().enumerate().skip(open) {
            match byte {
                b'(' => depth += 1,
                b')' => {
                    depth = depth.saturating_sub(1);
                    if depth == 0 {
                        if text[index + 1..].trim().is_empty() {
                            return Some(open);
                        }
                        break;
                    }
                }
                _ => {}
            }
        }
    }
    None
}

fn function_name(language: &str, text: &str) -> Option<String> {
    let header = text.lines().find(|line| !line.trim().is_empty())?.trim();
    let keyword = match language {
        "python" => Some("def "),
        "rust" => Some("fn "),
        "typescript" | "tsx" | "javascript" => header.contains("function ").then_some("function "),
        _ => None,
    };
    if let Some(keyword) = keyword {
        let start = header.find(keyword)? + keyword.len();
        return identifier_from(&header[start..]);
    }
    if language == "go" {
        let mut rest = header.strip_prefix("func ")?.trim_start();
        if rest.starts_with('(') {
            let close = matching_close(rest, 0)?;
            rest = rest[close + 1..].trim_start();
        }
        return identifier_from(rest);
    }
    let open = header.find('(')?;
    let before = header[..open].trim_end();
    before
        .split(|character: char| !is_identifier(character))
        .filter(|part| !part.is_empty())
        .next_back()
        .map(ToOwned::to_owned)
}

fn identifier_from(text: &str) -> Option<String> {
    let name = text
        .chars()
        .take_while(|character| is_identifier(*character))
        .collect::<String>();
    (!name.is_empty()).then_some(name)
}

fn matching_close(text: &str, open: usize) -> Option<usize> {
    let mut depth = 0_usize;
    for (index, character) in text.char_indices().skip(open) {
        match character {
            '(' => depth += 1,
            ')' => {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    return Some(index);
                }
            }
            _ => {}
        }
    }
    None
}

fn regex_escape(value: &str) -> String {
    let mut escaped = String::new();
    for character in value.chars() {
        if matches!(
            character,
            '\\' | '.' | '^' | '$' | '|' | '?' | '*' | '+' | '(' | ')' | '[' | ']' | '{' | '}'
        ) {
            escaped.push('\\');
        }
        escaped.push(character);
    }
    escaped.replace('\'', "''")
}

pub(crate) fn parse_outline_stream(
    bytes: &[u8],
    target: &str,
    universe: &SourceUniverse,
) -> Result<Vec<DefinitionCandidate>, String> {
    let stream = std::str::from_utf8(bytes)
        .map_err(|_| "ast-grep outline output was not UTF-8".to_owned())?;
    let target_last = target.rsplit("::").next().unwrap_or(target);
    let mut candidates = Vec::new();
    for (index, line) in stream.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "invalid ast-grep outline JSON at record {}: {error}",
                index + 1
            )
        })?;
        let raw_file = value
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(|| "ast-grep outline record is missing path".to_owned())?;
        let file = PathBuf::from(raw_file);
        let file = if file.is_absolute() {
            file
        } else {
            universe.cwd.join(file)
        };
        let file = fs::canonicalize(&file).unwrap_or(file);
        let source = fs::read_to_string(&file)
            .map_err(|error| format!("cannot read outlined source {}: {error}", file.display()))?;
        let items = value
            .get("items")
            .and_then(Value::as_array)
            .ok_or_else(|| "ast-grep outline record is missing items".to_owned())?;
        collect_items(
            items,
            &[],
            &file,
            &source,
            target,
            target_last,
            universe,
            &mut candidates,
        )?;
    }
    Ok(candidates)
}

#[allow(clippy::too_many_arguments)]
fn collect_items(
    items: &[Value],
    parents: &[String],
    file: &Path,
    source: &str,
    target: &str,
    target_last: &str,
    universe: &SourceUniverse,
    candidates: &mut Vec<DefinitionCandidate>,
) -> Result<(), String> {
    for item in items {
        let Some(name) = item.get("name").and_then(Value::as_str) else {
            continue;
        };
        let mut qualified_parts = parents.to_vec();
        qualified_parts.push(name.to_owned());
        let qualified_name = qualified_parts.join("::");
        if name == target_last
            && (!target.contains("::")
                || qualified_name == target
                || qualified_name.ends_with(&format!("::{target}")))
        {
            candidates.push(candidate_from_item(
                item,
                file,
                source,
                qualified_name,
                universe,
            )?);
        }
        if let Some(members) = item.get("members").and_then(Value::as_array) {
            collect_items(
                members,
                &qualified_parts,
                file,
                source,
                target,
                target_last,
                universe,
                candidates,
            )?;
        }
    }
    Ok(())
}

fn candidate_from_item(
    item: &Value,
    file: &Path,
    source: &str,
    qualified_name: String,
    universe: &SourceUniverse,
) -> Result<DefinitionCandidate, String> {
    let range_value = item
        .get("range")
        .ok_or_else(|| "ast-grep outline item is missing range".to_owned())?;
    let range = SourceRange {
        start: parse_position(
            range_value
                .get("start")
                .ok_or_else(|| "ast-grep outline range is missing start".to_owned())?,
        )?,
        end: parse_position(
            range_value
                .get("end")
                .ok_or_else(|| "ast-grep outline range is missing end".to_owned())?,
        )?,
    };
    let byte_range = range_value
        .get("byteOffset")
        .ok_or_else(|| "ast-grep outline range is missing byteOffset".to_owned())?;
    let byte_start = parse_usize(byte_range.get("start"), "byte start")?;
    let byte_end = parse_usize(byte_range.get("end"), "byte end")?;
    let text = source
        .get(byte_start..byte_end)
        .ok_or_else(|| "ast-grep outline byte range is outside UTF-8 source".to_owned())?
        .to_owned();
    let name = item
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| "ast-grep outline item is missing name".to_owned())?;
    let name_offset = exact_name_offset(&text, name).unwrap_or(0);
    Ok(DefinitionCandidate {
        file: file.to_path_buf(),
        range,
        name_position: offset_position(range.start, &text, name_offset),
        qualified_name,
        symbol_kind: item
            .get("symbolType")
            .and_then(Value::as_str)
            .unwrap_or("symbol")
            .to_owned(),
        role: DefinitionRole::Definition,
        signature: item
            .get("signature")
            .and_then(Value::as_str)
            .unwrap_or(name)
            .trim()
            .to_owned(),
        text,
        ast_kind: item
            .get("astKind")
            .and_then(Value::as_str)
            .unwrap_or("outline-item")
            .to_owned(),
        root_alias: universe.root_for(file).map(|root| root.alias.clone()),
    })
}

fn parse_position(value: &Value) -> Result<SourcePosition, String> {
    Ok(SourcePosition {
        line: parse_usize(value.get("line"), "line")?,
        column: parse_usize(value.get("column"), "column")?,
    })
}

fn parse_usize(value: Option<&Value>, field: &str) -> Result<usize, String> {
    value
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| format!("ast-grep outline has invalid {field}"))
}

fn exact_name_offset(text: &str, target: &str) -> Option<usize> {
    text.match_indices(target).find_map(|(offset, _)| {
        let before = text[..offset].chars().next_back();
        let after = text[offset + target.len()..].chars().next();
        (!before.is_some_and(is_identifier) && !after.is_some_and(is_identifier)).then_some(offset)
    })
}

fn is_identifier(character: char) -> bool {
    character == '_' || character.is_alphanumeric() || !character.is_ascii()
}

fn offset_position(start: SourcePosition, text: &str, offset: usize) -> SourcePosition {
    let before = &text[..offset.min(text.len())];
    let line_delta = before.bytes().filter(|byte| *byte == b'\n').count();
    let column = before
        .rsplit_once('\n')
        .map_or(start.column + before.chars().count(), |(_, tail)| {
            tail.chars().count()
        });
    SourcePosition {
        line: start.line + line_delta,
        column,
    }
}
