use crate::profile::ProjectedRecord;

use super::{
    truncate::{
        apply_preview_cap, apply_recovery_cap, count_truncation_markers, max_preview_chars,
        max_recovery_units, RecoveryField,
    },
    BudgetError, BudgetSettings, MIN_ADAPTIVE_PREVIEW_CHARS,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GroupDimension {
    Severity,
    Rule,
    File,
}

/// Adapter implemented by the final context/envelope type in P2-003.
/// Measurement must serialize the exact YAML candidate that would be emitted.
pub trait ContextBudgetCandidate: Clone {
    fn records(&self) -> &[ProjectedRecord];
    fn records_mut(&mut self) -> &mut Vec<ProjectedRecord>;
    fn pop_last_record_to_overflow(&mut self) -> bool;
    fn trim_lowest_group_entry(&mut self, dimension: GroupDimension) -> bool;
    fn measure_yaml_bytes(&self) -> Result<u64, String>;
    fn has_minimum_locator(&self) -> bool;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BudgetReport {
    pub yaml_bytes: u64,
    pub preview_cap: u32,
    pub removed_results: u64,
    pub removed_group_entries: u64,
    pub truncation_markers: u64,
    pub used_recovery: bool,
}

pub fn fit_context_budget<T: ContextBudgetCandidate>(
    candidate: &mut T,
    settings: BudgetSettings,
) -> Result<BudgetReport, BudgetError> {
    let mut removed_results = 0_u64;
    let max_details = usize::try_from(settings.max_detail_results())
        .map_err(|_| BudgetError::InvalidSetting("max_detail_results exceeds platform usize"))?;
    while candidate.records().len() > max_details {
        if !candidate.pop_last_record_to_overflow() {
            return Err(BudgetError::Measure(
                "candidate refused required detail-cap removal".to_owned(),
            ));
        }
        removed_results = removed_results
            .checked_add(1)
            .ok_or(BudgetError::CountOverflow)?;
    }

    let base = candidate.clone();
    let mut preview_cap = settings.max_text_chars();
    apply_preview_cap(
        candidate.records_mut(),
        usize::try_from(preview_cap)
            .map_err(|_| BudgetError::InvalidSetting("max_text_chars exceeds platform usize"))?,
    );
    if let Some(bytes) = fitting_bytes(candidate, settings.max_context_bytes(), false)? {
        return Ok(report(
            candidate,
            bytes,
            preview_cap,
            removed_results,
            0,
            false,
        ));
    }

    let floor = preview_cap.min(MIN_ADAPTIVE_PREVIEW_CHARS);
    if preview_cap > floor {
        let upper =
            preview_cap.min(u32::try_from(max_preview_chars(base.records())).unwrap_or(u32::MAX));
        if upper > floor {
            if let Some((cap, fitted, bytes)) = find_preview_fit(
                &base,
                floor,
                upper.saturating_sub(1),
                settings.max_context_bytes(),
                false,
            )? {
                *candidate = fitted;
                return Ok(report(candidate, bytes, cap, removed_results, 0, false));
            }
        }
        *candidate = base;
        apply_preview_cap(
            candidate.records_mut(),
            usize::try_from(floor).map_err(|_| {
                BudgetError::InvalidSetting("adaptive preview floor exceeds platform usize")
            })?,
        );
        preview_cap = floor;
    }

    while candidate.records().len() > 1 {
        if !candidate.pop_last_record_to_overflow() {
            return Err(BudgetError::Measure(
                "candidate refused byte-budget detail removal".to_owned(),
            ));
        }
        removed_results = removed_results
            .checked_add(1)
            .ok_or(BudgetError::CountOverflow)?;
        if let Some(bytes) = fitting_bytes(candidate, settings.max_context_bytes(), false)? {
            return Ok(report(
                candidate,
                bytes,
                preview_cap,
                removed_results,
                0,
                false,
            ));
        }
    }

    let mut removed_groups = 0_u64;
    loop {
        let mut changed = false;
        for dimension in [
            GroupDimension::Severity,
            GroupDimension::Rule,
            GroupDimension::File,
        ] {
            if candidate.trim_lowest_group_entry(dimension) {
                changed = true;
                removed_groups = removed_groups
                    .checked_add(1)
                    .ok_or(BudgetError::CountOverflow)?;
                if let Some(bytes) = fitting_bytes(candidate, settings.max_context_bytes(), false)?
                {
                    return Ok(report(
                        candidate,
                        bytes,
                        preview_cap,
                        removed_results,
                        removed_groups,
                        false,
                    ));
                }
            }
        }
        if !changed {
            break;
        }
    }

    if preview_cap > 0 {
        let recovery_base = candidate.clone();
        if let Some((cap, fitted, bytes)) = find_preview_fit(
            &recovery_base,
            0,
            preview_cap.saturating_sub(1),
            settings.max_context_bytes(),
            true,
        )? {
            *candidate = fitted;
            return Ok(report(
                candidate,
                bytes,
                cap,
                removed_results,
                removed_groups,
                true,
            ));
        }
        apply_preview_cap(candidate.records_mut(), 0);
        preview_cap = 0;
        if let Some(bytes) = fitting_bytes(candidate, settings.max_context_bytes(), true)? {
            return Ok(report(
                candidate,
                bytes,
                preview_cap,
                removed_results,
                removed_groups,
                true,
            ));
        }
    }

    for field in [
        RecoveryField::Note,
        RecoveryField::Labels,
        RecoveryField::Message,
        RecoveryField::Replacement,
    ] {
        let upper = max_recovery_units(candidate.records(), field);
        if upper == 0 {
            continue;
        }
        let recovery_base = candidate.clone();
        if let Some((fitted, bytes)) = find_recovery_fit(
            &recovery_base,
            field,
            upper.saturating_sub(1),
            settings.max_context_bytes(),
        )? {
            *candidate = fitted;
            return Ok(report(
                candidate,
                bytes,
                preview_cap,
                removed_results,
                removed_groups,
                true,
            ));
        }
        apply_recovery_cap(candidate.records_mut(), field, 0);
        if let Some(bytes) = fitting_bytes(candidate, settings.max_context_bytes(), true)? {
            return Ok(report(
                candidate,
                bytes,
                preview_cap,
                removed_results,
                removed_groups,
                true,
            ));
        }
    }

    let measured_bytes = measure(candidate)?;
    Err(BudgetError::Minimum {
        limit_bytes: settings.max_context_bytes(),
        measured_bytes,
    })
}

fn find_preview_fit<T: ContextBudgetCandidate>(
    base: &T,
    low: u32,
    high: u32,
    limit: u64,
    require_locator: bool,
) -> Result<Option<(u32, T, u64)>, BudgetError> {
    // Measure every candidate from largest to smallest. YAML scalar style can
    // change at a truncation boundary, so serialized size is not guaranteed
    // to be monotonic and binary search could skip the true largest fit.
    for cap in (low..=high).rev() {
        let mut trial = base.clone();
        apply_preview_cap(
            trial.records_mut(),
            usize::try_from(cap)
                .map_err(|_| BudgetError::InvalidSetting("preview cap exceeds platform usize"))?,
        );
        if let Some(bytes) = fitting_bytes(&trial, limit, require_locator)? {
            return Ok(Some((cap, trial, bytes)));
        }
    }
    Ok(None)
}

fn find_recovery_fit<T: ContextBudgetCandidate>(
    base: &T,
    field: RecoveryField,
    high: usize,
    limit: u64,
) -> Result<Option<(T, u64)>, BudgetError> {
    for cap in (0..=high).rev() {
        let mut trial = base.clone();
        apply_recovery_cap(trial.records_mut(), field, cap);
        if let Some(bytes) = fitting_bytes(&trial, limit, true)? {
            return Ok(Some((trial, bytes)));
        }
    }
    Ok(None)
}

fn fitting_bytes<T: ContextBudgetCandidate>(
    candidate: &T,
    limit: u64,
    require_locator: bool,
) -> Result<Option<u64>, BudgetError> {
    let bytes = measure(candidate)?;
    Ok((bytes <= limit && (!require_locator || candidate.has_minimum_locator())).then_some(bytes))
}

fn measure<T: ContextBudgetCandidate>(candidate: &T) -> Result<u64, BudgetError> {
    candidate.measure_yaml_bytes().map_err(BudgetError::Measure)
}

fn report<T: ContextBudgetCandidate>(
    candidate: &T,
    yaml_bytes: u64,
    preview_cap: u32,
    removed_results: u64,
    removed_group_entries: u64,
    used_recovery: bool,
) -> BudgetReport {
    BudgetReport {
        yaml_bytes,
        preview_cap,
        removed_results,
        removed_group_entries,
        truncation_markers: count_truncation_markers(candidate.records()),
        used_recovery,
    }
}
