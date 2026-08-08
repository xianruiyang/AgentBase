//! Deterministic model-context detail, text, and serialized-byte budgeting.

mod fit;
mod selector;
mod settings;
mod truncate;

pub use fit::{fit_context_budget, BudgetReport, ContextBudgetCandidate, GroupDimension};
pub use selector::{DetailDisposition, DetailSelector};
pub use settings::{
    BudgetSettings, DEFAULT_MAX_CONTEXT_BYTES, DEFAULT_MAX_DETAIL_RESULTS, DEFAULT_MAX_TEXT_CHARS,
    MIN_ADAPTIVE_PREVIEW_CHARS,
};

use thiserror::Error;

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum BudgetError {
    #[error("invalid context budget setting: {0}")]
    InvalidSetting(&'static str),
    #[error("context record count overflow")]
    CountOverflow,
    #[error("cannot measure serialized context YAML: {0}")]
    Measure(String),
    #[error(
        "E_CONTEXT_BUDGET_MINIMUM: minimum locatable context is {measured_bytes} bytes, limit is {limit_bytes} bytes"
    )]
    Minimum {
        limit_bytes: u64,
        measured_bytes: u64,
    },
}

impl BudgetError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::InvalidSetting(_) => 125,
            Self::Measure(_) => 122,
            Self::CountOverflow | Self::Minimum { .. } => 124,
        }
    }
}
