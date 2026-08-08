use super::{BudgetError, BudgetSettings};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DetailDisposition {
    Show,
    Omit,
}

/// Streaming first-N selector. Every source record is counted, while callers
/// retain only records reported as `Show` and aggregate `Omit` immediately.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DetailSelector {
    limit: u32,
    total: u64,
    shown: u32,
}

impl DetailSelector {
    #[must_use]
    pub const fn new(settings: BudgetSettings) -> Self {
        Self {
            limit: settings.max_detail_results(),
            total: 0,
            shown: 0,
        }
    }

    pub fn consider(&mut self) -> Result<DetailDisposition, BudgetError> {
        self.total = self
            .total
            .checked_add(1)
            .ok_or(BudgetError::CountOverflow)?;
        if self.shown < self.limit {
            self.shown += 1;
            Ok(DetailDisposition::Show)
        } else {
            Ok(DetailDisposition::Omit)
        }
    }

    #[must_use]
    pub const fn total(&self) -> u64 {
        self.total
    }

    #[must_use]
    pub const fn shown(&self) -> u32 {
        self.shown
    }

    #[must_use]
    pub const fn omitted(&self) -> u64 {
        self.total.saturating_sub(self.shown as u64)
    }
}
