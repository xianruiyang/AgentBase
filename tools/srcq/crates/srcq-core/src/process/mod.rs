//! Non-interactive, shell-free process execution and wrapper-owned output primitives.

mod atomic_output;
mod cancellation;
mod runner;

pub use atomic_output::{OutputCommitError, PreparedOutput};
pub use cancellation::{CancellationKind, CancellationToken, SignalRelay, SignalRelayError};
pub(crate) use runner::cancellation_from_exit_status;
pub use runner::{
    run, CancellationReport, ProcessError, ProcessOutcome, ProcessOutput, ProcessRequest,
    StdinMode, TerminationStage,
};
