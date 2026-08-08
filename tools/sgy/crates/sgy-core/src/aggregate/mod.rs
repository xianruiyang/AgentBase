//! Single-pass context aggregation and versioned `_sgy` envelope rendering.

mod builder;
mod document;
mod groups;

pub use builder::ContextAggregator;
pub use document::{AggregatedContext, ContextDocument};

use thiserror::Error;

use crate::budget::BudgetError;

pub const CONTEXT_SCHEMA: &str = "sgy.context/v1";
pub const MAX_GROUP_ENTRIES: usize = 20;
pub const MAX_AGGREGATION_KEYS: usize = 100_000;

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum AggregateError {
    #[error("lossless profile must bypass context aggregation")]
    LosslessProfile,
    #[error("profile {actual} cannot use aggregation operation {operation}")]
    ProfileOperation {
        actual: &'static str,
        operation: &'static str,
    },
    #[error("source ordinal {actual} is not the expected native-order ordinal {expected}")]
    NativeOrder { expected: u64, actual: u64 },
    #[error("source record count overflow")]
    CountOverflow,
    #[error("aggregation dimension {dimension} exceeds the {limit} distinct-key limit")]
    GroupCardinality {
        dimension: &'static str,
        limit: usize,
    },
    #[error(transparent)]
    Budget(#[from] BudgetError),
}

impl AggregateError {
    #[must_use]
    pub const fn wrapper_exit_code(&self) -> i32 {
        match self {
            Self::Budget(error) => error.wrapper_exit_code(),
            Self::LosslessProfile
            | Self::ProfileOperation { .. }
            | Self::NativeOrder { .. }
            | Self::CountOverflow
            | Self::GroupCardinality { .. } => 122,
        }
    }
}
