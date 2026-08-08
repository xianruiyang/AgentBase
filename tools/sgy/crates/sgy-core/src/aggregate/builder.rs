use crate::{
    adapters::write::WriteIntent,
    budget::{BudgetSettings, DetailDisposition, DetailSelector},
    invocation::Profile,
    profile::ProjectedRecord,
};

use super::{
    document::{AggregatedContext, ContextDocument},
    groups::{OverflowGroups, RecordGroups},
    AggregateError,
};

/// Consumes one native-order source stream and retains only bounded detail.
#[derive(Clone, Debug)]
pub struct ContextAggregator {
    profile: Profile,
    settings: BudgetSettings,
    selector: DetailSelector,
    total: u64,
    records: Vec<ProjectedRecord>,
    record_groups: Vec<RecordGroups>,
    groups: OverflowGroups,
    cache_id: Option<String>,
    write_intent: WriteIntent,
    replacement_records: u64,
}

impl ContextAggregator {
    pub fn new(profile: Profile, settings: BudgetSettings) -> Result<Self, AggregateError> {
        if profile == Profile::Lossless {
            return Err(AggregateError::LosslessProfile);
        }
        Ok(Self {
            profile,
            settings,
            selector: DetailSelector::new(settings),
            total: 0,
            records: Vec::new(),
            record_groups: Vec::new(),
            groups: OverflowGroups::default(),
            cache_id: None,
            write_intent: WriteIntent::None,
            replacement_records: 0,
        })
    }

    pub fn set_write_intent(&mut self, write_intent: WriteIntent) {
        self.write_intent = write_intent;
    }

    pub fn set_cache_id(&mut self, cache_id: impl Into<String>) {
        self.cache_id = Some(cache_id.into());
    }

    /// Adds one Token-Safe record. Its projected fields are also the complete
    /// aggregation source for file/rule/severity.
    pub fn push_token_safe(&mut self, record: ProjectedRecord) -> Result<(), AggregateError> {
        if self.profile != Profile::TokenSafe {
            return Err(self.profile_operation("push_token_safe"));
        }
        let keys = RecordGroups::from_projected(&record.value);
        let has_replacement = has_replacement(&record);
        self.push_detail(record.ordinal, keys, record, has_replacement)
    }

    /// Adds one custom record while retaining aggregation keys from the
    /// unpruned Token-Safe source projection.
    pub fn push_custom(
        &mut self,
        token_safe: &ProjectedRecord,
        displayed: ProjectedRecord,
    ) -> Result<(), AggregateError> {
        if self.profile != Profile::Custom {
            return Err(self.profile_operation("push_custom"));
        }
        if token_safe.ordinal != displayed.ordinal {
            return Err(AggregateError::NativeOrder {
                expected: token_safe.ordinal,
                actual: displayed.ordinal,
            });
        }
        self.push_detail(
            token_safe.ordinal,
            RecordGroups::from_projected(&token_safe.value),
            displayed,
            has_replacement(token_safe),
        )
    }

    /// Adds one source record to the files profile without retaining detail.
    pub fn push_file(&mut self, token_safe: &ProjectedRecord) -> Result<(), AggregateError> {
        if self.profile != Profile::Files {
            return Err(self.profile_operation("push_file"));
        }
        let keys = RecordGroups::from_projected(&token_safe.value);
        self.observe_native_order(token_safe.ordinal, &keys, has_replacement(token_safe))?;
        Ok(())
    }

    pub fn finish(self) -> Result<AggregatedContext, AggregateError> {
        let settings = self.settings;
        self.into_document()?.fit(settings)
    }

    pub fn into_document(self) -> Result<ContextDocument, AggregateError> {
        Ok(ContextDocument::new(
            self.profile,
            self.total,
            u64::try_from(self.groups.file.distinct_len())
                .map_err(|_| AggregateError::CountOverflow)?,
            self.records,
            self.record_groups,
            self.groups,
            self.cache_id,
            self.write_intent,
            self.replacement_records,
        ))
    }

    fn push_detail(
        &mut self,
        ordinal: u64,
        keys: RecordGroups,
        record: ProjectedRecord,
        has_replacement: bool,
    ) -> Result<(), AggregateError> {
        self.observe_native_order(ordinal, &keys, has_replacement)?;
        match self.selector.consider()? {
            DetailDisposition::Show => {
                self.records.push(record);
                self.record_groups.push(keys);
            }
            DetailDisposition::Omit => {}
        }
        Ok(())
    }

    fn observe_native_order(
        &mut self,
        ordinal: u64,
        keys: &RecordGroups,
        has_replacement: bool,
    ) -> Result<(), AggregateError> {
        if ordinal != self.total {
            return Err(AggregateError::NativeOrder {
                expected: self.total,
                actual: ordinal,
            });
        }
        self.total = self
            .total
            .checked_add(1)
            .ok_or(AggregateError::CountOverflow)?;
        self.groups.observe(keys)?;
        if has_replacement {
            self.replacement_records = self
                .replacement_records
                .checked_add(1)
                .ok_or(AggregateError::CountOverflow)?;
        }
        Ok(())
    }

    fn profile_operation(&self, operation: &'static str) -> AggregateError {
        AggregateError::ProfileOperation {
            actual: self.profile.as_str(),
            operation,
        }
    }
}

fn has_replacement(record: &ProjectedRecord) -> bool {
    record
        .value
        .get("replacement")
        .and_then(serde_json::Value::as_str)
        .is_some()
}
