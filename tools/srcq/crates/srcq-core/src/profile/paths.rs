use serde_json::{Map, Value};
use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq)]
enum PathSegment {
    Name(String),
    Wildcard,
}

impl PathSegment {
    fn matches(&self, key: &str) -> bool {
        match self {
            Self::Name(name) => name == key,
            Self::Wildcard => true,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct FieldPath(Vec<PathSegment>);

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FieldPaths {
    paths: Vec<FieldPath>,
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum FieldPathError {
    #[error("field path list contains an empty path or segment at byte {byte_offset}")]
    Empty { byte_offset: usize },
    #[error("field path contains invalid escape at byte {byte_offset}")]
    InvalidEscape { byte_offset: usize },
    #[error("unescaped wildcard must occupy a whole segment at byte {byte_offset}")]
    WildcardPlacement { byte_offset: usize },
    #[error("field path list contains a duplicate normalized path at index {path_index}")]
    Duplicate { path_index: usize },
}

impl FieldPathError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        125
    }
}

impl FieldPaths {
    pub fn parse(input: &str) -> Result<Self, FieldPathError> {
        let mut paths = Vec::new();
        let mut segments = Vec::new();
        let mut name = String::new();
        let mut wildcard = false;
        let mut escaped_at = None;

        for (offset, character) in input.char_indices() {
            if let Some(backslash) = escaped_at.take() {
                if !matches!(character, '.' | ',' | '*' | '\\') {
                    return Err(FieldPathError::InvalidEscape {
                        byte_offset: backslash,
                    });
                }
                if wildcard {
                    return Err(FieldPathError::WildcardPlacement {
                        byte_offset: offset,
                    });
                }
                name.push(character);
                continue;
            }
            match character {
                '\\' => escaped_at = Some(offset),
                '.' | ',' => {
                    finish_segment(&mut segments, &mut name, &mut wildcard, offset)?;
                    if character == ',' {
                        finish_path(&mut paths, &mut segments)?;
                    }
                }
                '*' => {
                    if wildcard || !name.is_empty() {
                        return Err(FieldPathError::WildcardPlacement {
                            byte_offset: offset,
                        });
                    }
                    wildcard = true;
                }
                _ => {
                    if wildcard {
                        return Err(FieldPathError::WildcardPlacement {
                            byte_offset: offset,
                        });
                    }
                    name.push(character);
                }
            }
        }
        if let Some(byte_offset) = escaped_at {
            return Err(FieldPathError::InvalidEscape { byte_offset });
        }
        finish_segment(&mut segments, &mut name, &mut wildcard, input.len())?;
        finish_path(&mut paths, &mut segments)?;
        Ok(Self { paths })
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.paths.is_empty()
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.paths.len()
    }

    #[must_use]
    pub fn select(&self, source: &Value) -> Value {
        let cursors: Vec<&[PathSegment]> =
            self.paths.iter().map(|path| path.0.as_slice()).collect();
        select_value(source, &cursors).unwrap_or_else(|| empty_like(source))
    }

    #[must_use]
    pub fn values<'a>(&self, source: &'a Value) -> Vec<&'a Value> {
        let mut values = Vec::new();
        for path in &self.paths {
            collect_values(source, &path.0, &mut values);
        }
        values
    }

    pub(crate) fn prune(&self, value: &mut Value) {
        let cursors: Vec<&[PathSegment]> =
            self.paths.iter().map(|path| path.0.as_slice()).collect();
        prune_value(value, &cursors);
    }
}

fn collect_values<'a>(value: &'a Value, path: &[PathSegment], output: &mut Vec<&'a Value>) {
    if path.is_empty() {
        output.push(value);
        return;
    }
    match value {
        Value::Object(mapping) => {
            for (key, child) in mapping {
                if path[0].matches(key) {
                    collect_values(child, &path[1..], output);
                }
            }
        }
        Value::Array(items) => {
            for item in items {
                collect_values(item, path, output);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn finish_segment(
    segments: &mut Vec<PathSegment>,
    name: &mut String,
    wildcard: &mut bool,
    byte_offset: usize,
) -> Result<(), FieldPathError> {
    if *wildcard {
        segments.push(PathSegment::Wildcard);
        *wildcard = false;
        return Ok(());
    }
    if name.is_empty() {
        return Err(FieldPathError::Empty { byte_offset });
    }
    segments.push(PathSegment::Name(std::mem::take(name)));
    Ok(())
}

fn finish_path(
    paths: &mut Vec<FieldPath>,
    segments: &mut Vec<PathSegment>,
) -> Result<(), FieldPathError> {
    let path = FieldPath(std::mem::take(segments));
    if paths.contains(&path) {
        return Err(FieldPathError::Duplicate {
            path_index: paths.len(),
        });
    }
    paths.push(path);
    Ok(())
}

fn select_value(value: &Value, paths: &[&[PathSegment]]) -> Option<Value> {
    match value {
        Value::Object(mapping) => {
            let mut selected = Map::new();
            for (key, child) in mapping {
                let mut exact = false;
                let mut descendants = Vec::new();
                for path in paths {
                    if path.first().is_some_and(|segment| segment.matches(key)) {
                        if path.len() == 1 {
                            exact = true;
                        } else {
                            descendants.push(&path[1..]);
                        }
                    }
                }
                let projected = if exact {
                    Some(child.clone())
                } else if descendants.is_empty() {
                    None
                } else {
                    select_value(child, &descendants)
                };
                if let Some(projected) = projected {
                    selected.insert(key.clone(), projected);
                }
            }
            (!selected.is_empty()).then_some(Value::Object(selected))
        }
        Value::Array(items) => {
            let selected: Vec<Value> = items
                .iter()
                .filter_map(|item| select_value(item, paths))
                .collect();
            (!selected.is_empty()).then_some(Value::Array(selected))
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => None,
    }
}

fn prune_value(value: &mut Value, paths: &[&[PathSegment]]) {
    match value {
        Value::Object(mapping) => {
            mapping.retain(|key, child| {
                let mut remove = false;
                let mut descendants = Vec::new();
                for path in paths {
                    if path.first().is_some_and(|segment| segment.matches(key)) {
                        if path.len() == 1 {
                            remove = true;
                        } else {
                            descendants.push(&path[1..]);
                        }
                    }
                }
                if !remove && !descendants.is_empty() {
                    prune_value(child, &descendants);
                }
                !remove
            });
        }
        Value::Array(items) => {
            for item in items {
                prune_value(item, paths);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn empty_like(value: &Value) -> Value {
    match value {
        Value::Array(_) => Value::Array(Vec::new()),
        Value::Object(_) => Value::Object(Map::new()),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => Value::Null,
    }
}
