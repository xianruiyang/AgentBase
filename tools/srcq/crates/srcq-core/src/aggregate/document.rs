use std::io::Write;

use serde_json::{Map, Value};

use crate::{
    adapters::write::WriteIntent,
    budget::{
        fit_context_budget, BudgetError, BudgetReport, BudgetSettings, ContextBudgetCandidate,
        GroupDimension,
    },
    codec::{write_compact_yaml_document, write_yaml_document, CodecError},
    invocation::Profile,
    profile::ProjectedRecord,
};

use super::{
    groups::{OverflowGroups, RecordGroups, RenderedGroup},
    AggregateError, CONTEXT_SCHEMA,
};

#[derive(Clone, Debug, PartialEq)]
pub struct ContextDocument {
    profile: Profile,
    total: u64,
    distinct_files: u64,
    records: Vec<ProjectedRecord>,
    record_groups: Vec<RecordGroups>,
    groups: OverflowGroups,
    cache_id: Option<String>,
    write_intent: WriteIntent,
    replacement_records: u64,
}

impl ContextDocument {
    #[allow(clippy::too_many_arguments)]
    pub(super) fn new(
        profile: Profile,
        total: u64,
        distinct_files: u64,
        records: Vec<ProjectedRecord>,
        record_groups: Vec<RecordGroups>,
        groups: OverflowGroups,
        cache_id: Option<String>,
        write_intent: WriteIntent,
        replacement_records: u64,
    ) -> Self {
        Self {
            profile,
            total,
            distinct_files,
            records,
            record_groups,
            groups,
            cache_id,
            write_intent,
            replacement_records,
        }
    }

    #[must_use]
    pub const fn profile(&self) -> Profile {
        self.profile
    }

    #[must_use]
    pub const fn total(&self) -> u64 {
        self.total
    }

    #[must_use]
    pub fn shown(&self) -> u64 {
        u64::try_from(self.records.len()).unwrap_or(u64::MAX)
    }

    #[must_use]
    pub fn omitted(&self) -> u64 {
        self.total.saturating_sub(self.shown())
    }

    #[must_use]
    pub fn complete(&self) -> bool {
        match self.profile {
            Profile::Files => self.total == 0,
            Profile::TokenSafe | Profile::Locations | Profile::Custom => {
                self.omitted() == 0
                    && !self.records.iter().any(|record| {
                        has_true_marker(&record.value, "_sgy_unknown")
                            || has_truncation_marker(&record.value)
                    })
            }
            Profile::Lossless => false,
        }
    }

    #[must_use]
    pub fn to_value(&self) -> Value {
        let mut metadata = Map::new();
        metadata.insert(
            "schema".to_owned(),
            Value::String(CONTEXT_SCHEMA.to_owned()),
        );
        metadata.insert(
            "profile".to_owned(),
            Value::String(self.profile.as_str().to_owned()),
        );
        metadata.insert("total".to_owned(), Value::from(self.total));
        metadata.insert("shown".to_owned(), Value::from(self.shown()));
        metadata.insert("omitted".to_owned(), Value::from(self.omitted()));
        metadata.insert("files".to_owned(), Value::from(self.distinct_files));
        metadata.insert("complete".to_owned(), Value::Bool(self.complete()));
        if let Some(cache_id) = &self.cache_id {
            metadata.insert("cache".to_owned(), Value::String(cache_id.clone()));
        }
        if let Some(write) = self.write_summary() {
            metadata.insert("write".to_owned(), write);
        }

        let mut root = Map::new();
        root.insert("_sgy".to_owned(), Value::Object(metadata));
        match self.profile {
            Profile::TokenSafe | Profile::Locations | Profile::Custom => {
                root.insert(
                    "results".to_owned(),
                    Value::Array(
                        self.records
                            .iter()
                            .map(|record| record.value.clone())
                            .collect(),
                    ),
                );
                if self.omitted() > 0 {
                    root.insert("overflow".to_owned(), self.render_overflow());
                }
            }
            Profile::Files => self.render_files(&mut root),
            Profile::Lossless => {}
        }
        Value::Object(root)
    }

    pub fn write_yaml(&self, output: &mut impl Write) -> Result<u64, CodecError> {
        if self.profile == Profile::Locations {
            write_compact_yaml_document(&self.to_value(), output)
        } else {
            write_yaml_document(&self.to_value(), output, false)
        }
    }

    #[must_use]
    pub fn with_cache_id(mut self, cache_id: impl Into<String>) -> Self {
        self.cache_id = Some(cache_id.into());
        self
    }

    pub fn fit(self, settings: BudgetSettings) -> Result<AggregatedContext, AggregateError> {
        AggregatedContext::fit(self, settings).map_err(AggregateError::from)
    }

    fn render_overflow(&self) -> Value {
        let mut groups = self.groups.clone();
        for keys in &self.record_groups {
            groups.subtract(keys);
        }
        let mut overflow = Map::new();
        insert_dimension(&mut overflow, "file", groups.file.render());
        insert_dimension(&mut overflow, "rule", groups.rule.render());
        insert_dimension(&mut overflow, "severity", groups.severity.render());
        Value::Object(overflow)
    }

    fn write_summary(&self) -> Option<Value> {
        let requested = self
            .write_intent
            .as_str()
            .or_else(|| (self.replacement_records > 0).then_some("preview"))?;
        let mut write = Map::new();
        write.insert("requested".to_owned(), Value::String(requested.to_owned()));
        write.insert("matches".to_owned(), Value::from(self.total));
        write.insert(
            "affected_files".to_owned(),
            Value::from(self.distinct_files),
        );
        write.insert(
            "replacement_records".to_owned(),
            Value::from(self.replacement_records),
        );
        write.insert("transactional".to_owned(), Value::Bool(false));
        Some(Value::Object(write))
    }

    fn render_files(&self, root: &mut Map<String, Value>) {
        if let Some(rendered) = self.groups.file.render() {
            root.insert("files".to_owned(), Value::Object(rendered.mapping));
            if rendered.rest > 0 {
                root.insert("files_rest".to_owned(), Value::from(rendered.rest));
            }
            if rendered.unattributed > 0 {
                root.insert(
                    "files_unattributed".to_owned(),
                    Value::from(rendered.unattributed),
                );
            }
        } else {
            root.insert("files".to_owned(), Value::Object(Map::new()));
            if self.total > 0 {
                root.insert("files_unattributed".to_owned(), Value::from(self.total));
            }
        }
    }
}

impl ContextBudgetCandidate for ContextDocument {
    fn records(&self) -> &[ProjectedRecord] {
        &self.records
    }

    fn records_mut(&mut self) -> &mut Vec<ProjectedRecord> {
        &mut self.records
    }

    fn pop_last_record_to_overflow(&mut self) -> bool {
        if self.records.is_empty() || self.record_groups.len() != self.records.len() {
            return false;
        }
        if self.record_groups.pop().is_none() {
            return false;
        }
        if self.records.pop().is_none() {
            return false;
        }
        true
    }

    fn trim_lowest_group_entry(&mut self, dimension: GroupDimension) -> bool {
        match (self.profile, dimension) {
            (Profile::Files, GroupDimension::File) => self.groups.file.trim_lowest_visible(),
            (Profile::Files, GroupDimension::Severity | GroupDimension::Rule) => false,
            (
                Profile::TokenSafe | Profile::Locations | Profile::Custom,
                GroupDimension::Severity,
            ) => self.groups.severity.trim_lowest_visible(),
            (Profile::TokenSafe | Profile::Locations | Profile::Custom, GroupDimension::Rule) => {
                self.groups.rule.trim_lowest_visible()
            }
            (Profile::TokenSafe | Profile::Locations | Profile::Custom, GroupDimension::File) => {
                self.groups.file.trim_lowest_visible()
            }
            (Profile::Lossless, _) => false,
        }
    }

    fn measure_yaml_bytes(&self) -> Result<u64, String> {
        let mut output = Vec::new();
        self.write_yaml(&mut output)
            .map_err(|error| error.to_string())
    }

    fn has_minimum_locator(&self) -> bool {
        if self.total == 0 {
            return true;
        }
        if self.profile == Profile::Files {
            return self.cache_id.is_some();
        }
        self.records.iter().any(|record| {
            if self.profile == Profile::Locations {
                return record.value.as_str().is_some_and(|value| !value.is_empty())
                    || self.cache_id.is_some()
                        && record
                            .value
                            .get("_sgy_result")
                            .and_then(Value::as_u64)
                            .is_some();
            }
            let root = record.value.as_object();
            let direct = root
                .and_then(|value| value.get("file"))
                .and_then(Value::as_str)
                .is_some_and(|file| !file.is_empty())
                && root
                    .and_then(|value| value.get("range"))
                    .and_then(|range| range.get("start"))
                    .is_some_and(|start| {
                        start.get("line").and_then(Value::as_u64).is_some()
                            && start.get("column").and_then(Value::as_u64).is_some()
                    });
            let cached = self.cache_id.is_some()
                && root
                    .and_then(|value| value.get("_sgy_result"))
                    .and_then(Value::as_u64)
                    .is_some();
            direct || cached
        })
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct AggregatedContext {
    pub document: ContextDocument,
    pub budget: BudgetReport,
}

impl AggregatedContext {
    pub(super) fn fit(
        mut document: ContextDocument,
        settings: BudgetSettings,
    ) -> Result<Self, BudgetError> {
        let budget = fit_context_budget(&mut document, settings)?;
        Ok(Self { document, budget })
    }
}

fn insert_dimension(target: &mut Map<String, Value>, name: &str, rendered: Option<RenderedGroup>) {
    let Some(rendered) = rendered else {
        return;
    };
    target.insert(format!("by_{name}"), Value::Object(rendered.mapping));
    if rendered.rest > 0 {
        target.insert(format!("by_{name}_rest"), Value::from(rendered.rest));
    }
    if rendered.unattributed > 0 {
        target.insert(
            format!("by_{name}_unattributed"),
            Value::from(rendered.unattributed),
        );
    }
}

fn has_true_marker(value: &Value, marker: &str) -> bool {
    match value {
        Value::Object(mapping) => {
            mapping.get(marker).and_then(Value::as_bool) == Some(true)
                || mapping.values().any(|child| has_true_marker(child, marker))
        }
        Value::Array(items) => items.iter().any(|item| has_true_marker(item, marker)),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => false,
    }
}

fn has_truncation_marker(value: &Value) -> bool {
    match value {
        Value::Object(mapping) => mapping.iter().any(|(key, child)| {
            (key.starts_with("_sgy_")
                && key.ends_with("_truncated")
                && child.as_bool() == Some(true))
                || has_truncation_marker(child)
        }),
        Value::Array(items) => items.iter().any(has_truncation_marker),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => false,
    }
}
