use super::BudgetError;

pub const DEFAULT_MAX_DETAIL_RESULTS: u32 = 40;
pub const DEFAULT_MAX_TEXT_CHARS: u32 = 400;
pub const DEFAULT_MAX_CONTEXT_BYTES: u64 = 24 * 1024;
pub const MIN_ADAPTIVE_PREVIEW_CHARS: u32 = 40;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BudgetSettings {
    max_detail_results: u32,
    max_text_chars: u32,
    max_context_bytes: u64,
}

impl BudgetSettings {
    pub const fn new(
        max_detail_results: u32,
        max_text_chars: u32,
        max_context_bytes: u64,
    ) -> Result<Self, BudgetError> {
        if max_detail_results == 0 {
            return Err(BudgetError::InvalidSetting(
                "max_detail_results must be at least 1",
            ));
        }
        if max_context_bytes == 0 {
            return Err(BudgetError::InvalidSetting(
                "max_context_bytes must be at least 1",
            ));
        }
        Ok(Self {
            max_detail_results,
            max_text_chars,
            max_context_bytes,
        })
    }

    #[must_use]
    pub const fn max_detail_results(self) -> u32 {
        self.max_detail_results
    }

    #[must_use]
    pub const fn max_text_chars(self) -> u32 {
        self.max_text_chars
    }

    #[must_use]
    pub const fn max_context_bytes(self) -> u64 {
        self.max_context_bytes
    }
}

impl Default for BudgetSettings {
    fn default() -> Self {
        Self {
            max_detail_results: DEFAULT_MAX_DETAIL_RESULTS,
            max_text_chars: DEFAULT_MAX_TEXT_CHARS,
            max_context_bytes: DEFAULT_MAX_CONTEXT_BYTES,
        }
    }
}
