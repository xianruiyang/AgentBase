use std::collections::HashMap;

use serde_json::{Map, Value};

use super::{AggregateError, MAX_AGGREGATION_KEYS, MAX_GROUP_ENTRIES};

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(super) struct RecordGroups {
    pub file: Option<String>,
    pub rule: Option<String>,
    pub severity: Option<String>,
}

impl RecordGroups {
    pub fn from_projected(value: &Value) -> Self {
        let field = |name| {
            value
                .get(name)
                .and_then(Value::as_str)
                .filter(|text| !text.is_empty())
                .map(ToOwned::to_owned)
        };
        Self {
            file: field("file"),
            rule: field("ruleId"),
            severity: field("severity"),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct GroupCounts {
    counts: HashMap<String, u64>,
    unattributed: u64,
    visible_limit: usize,
}

impl Default for GroupCounts {
    fn default() -> Self {
        Self {
            counts: HashMap::new(),
            unattributed: 0,
            visible_limit: MAX_GROUP_ENTRIES,
        }
    }
}

impl GroupCounts {
    pub fn observe(
        &mut self,
        dimension: &'static str,
        key: Option<&str>,
    ) -> Result<(), AggregateError> {
        // Each observation belongs to one already count-checked source record,
        // so no dimension count can exceed the document's u64 total.
        if let Some(key) = key.filter(|key| !key.is_empty()) {
            if !self.counts.contains_key(key) && self.counts.len() >= MAX_AGGREGATION_KEYS {
                return Err(AggregateError::GroupCardinality {
                    dimension,
                    limit: MAX_AGGREGATION_KEYS,
                });
            }
            let count = self.counts.entry(key.to_owned()).or_default();
            *count += 1;
        } else {
            self.unattributed += 1;
        }
        Ok(())
    }

    pub fn subtract(&mut self, key: Option<&str>) {
        if let Some(key) = key.filter(|key| !key.is_empty()) {
            match self.counts.get(key).copied() {
                Some(0 | 1) => {
                    self.counts.remove(key);
                }
                Some(count) => {
                    self.counts.insert(key.to_owned(), count - 1);
                }
                None => {}
            }
        } else {
            self.unattributed = self.unattributed.saturating_sub(1);
        }
    }

    pub fn distinct_len(&self) -> usize {
        self.counts.len()
    }

    pub fn trim_lowest_visible(&mut self) -> bool {
        let shown = self.visible_limit.min(self.counts.len());
        if shown == 0 {
            return false;
        }
        self.visible_limit = shown - 1;
        true
    }

    pub fn render(&self) -> Option<RenderedGroup> {
        if self.counts.is_empty() {
            return None;
        }
        let mut entries: Vec<(&String, &u64)> = self.counts.iter().collect();
        entries.sort_by(|(left_key, left_count), (right_key, right_count)| {
            right_count
                .cmp(left_count)
                .then_with(|| left_key.as_bytes().cmp(right_key.as_bytes()))
        });

        let mut mapping = Map::new();
        let mut displayed = 0_u64;
        for (key, count) in entries.iter().take(self.visible_limit) {
            mapping.insert((*key).clone(), Value::from(**count));
            displayed += **count;
        }
        let keyed_total = self.counts.values().copied().sum::<u64>();
        Some(RenderedGroup {
            mapping,
            rest: keyed_total.saturating_sub(displayed),
            unattributed: self.unattributed,
        })
    }
}

pub(super) struct RenderedGroup {
    pub mapping: Map<String, Value>,
    pub rest: u64,
    pub unattributed: u64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(super) struct OverflowGroups {
    pub file: GroupCounts,
    pub rule: GroupCounts,
    pub severity: GroupCounts,
}

impl OverflowGroups {
    pub fn observe(&mut self, keys: &RecordGroups) -> Result<(), AggregateError> {
        self.file.observe("file", keys.file.as_deref())?;
        self.rule.observe("rule", keys.rule.as_deref())?;
        self.severity
            .observe("severity", keys.severity.as_deref())?;
        Ok(())
    }

    pub fn subtract(&mut self, keys: &RecordGroups) {
        self.file.subtract(keys.file.as_deref());
        self.rule.subtract(keys.rule.as_deref());
        self.severity.subtract(keys.severity.as_deref());
    }
}
