use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};

use thiserror::Error;

const RUNNING: u8 = 0;
const CTRL_C: u8 = 1;
const TERMINATION: u8 = 2;
const EXTERNAL: u8 = 3;

/// The first cancellation reason observed by a process invocation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CancellationKind {
    CtrlC,
    Termination,
    External,
}

impl CancellationKind {
    #[must_use]
    pub const fn exit_code(self) -> i32 {
        match self {
            Self::CtrlC => 130,
            Self::Termination | Self::External => 143,
        }
    }

    const fn encoded(self) -> u8 {
        match self {
            Self::CtrlC => CTRL_C,
            Self::Termination => TERMINATION,
            Self::External => EXTERNAL,
        }
    }

    const fn decoded(value: u8) -> Option<Self> {
        match value {
            CTRL_C => Some(Self::CtrlC),
            TERMINATION => Some(Self::Termination),
            EXTERNAL => Some(Self::External),
            _ => None,
        }
    }
}

/// Cloneable first-writer-wins cancellation state.
#[derive(Clone, Debug, Default)]
pub struct CancellationToken {
    state: Arc<AtomicU8>,
}

impl CancellationToken {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Records a cancellation request. Later requests never overwrite the first reason.
    pub fn cancel(&self, reason: CancellationKind) -> bool {
        self.state
            .compare_exchange(
                RUNNING,
                reason.encoded(),
                Ordering::AcqRel,
                Ordering::Acquire,
            )
            .is_ok()
    }

    #[must_use]
    pub fn reason(&self) -> Option<CancellationKind> {
        CancellationKind::decoded(self.state.load(Ordering::Acquire))
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.reason().is_some()
    }
}

#[derive(Debug, Error)]
pub enum SignalRelayError {
    #[error("failed to install process signal relay: {0}")]
    Install(String),
}

/// Owns the Windows console signal registration for one active CLI invocation.
/// Console handlers are process-global and cannot be unregistered through `ctrlc`; the CLI
/// therefore installs the relay once for its process lifetime.
#[derive(Debug)]
pub struct SignalRelay {}

impl SignalRelay {
    pub fn install(token: CancellationToken) -> Result<Self, SignalRelayError> {
        ctrlc::try_set_handler(move || {
            token.cancel(CancellationKind::CtrlC);
        })
        .map_err(|error| SignalRelayError::Install(error.to_string()))?;
        Ok(Self {})
    }
}

#[cfg(test)]
mod tests {
    use super::{CancellationKind, CancellationToken};

    #[test]
    fn first_cancellation_reason_wins() {
        let token = CancellationToken::new();
        assert!(token.cancel(CancellationKind::CtrlC));
        assert!(!token.cancel(CancellationKind::Termination));
        assert_eq!(token.reason(), Some(CancellationKind::CtrlC));
        assert_eq!(token.reason().map(CancellationKind::exit_code), Some(130));
    }
}
