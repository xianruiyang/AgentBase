#![no_main]

use std::ffi::OsString;

use libfuzzer_sys::fuzz_target;
use sgy_core::{
    config::ConfigStack, defaults::resolve_defaults, invocation::ExplicitOptions,
};

fuzz_target!(|data: &[u8]| {
    let mut native: Vec<OsString> = data
        .split(|byte| *byte == b'\n')
        .take(64)
        .map(|token| OsString::from(String::from_utf8_lossy(token).into_owned()))
        .collect();
    if native.is_empty() {
        native.push(OsString::from("run"));
    }

    let mut invocation = vec![
        OsString::from("sgy"),
        OsString::from("exec"),
        OsString::from("--"),
    ];
    invocation.extend(native.iter().cloned());
    let parsed = sgy_cli::parse_invocation_from(invocation)
        .unwrap_or_else(|error| panic!("fixed wrapper invocation failed: {error}"));
    assert_eq!(parsed.user_argv, native);

    let decision = resolve_defaults(
        &ExplicitOptions::default(),
        &ConfigStack::default(),
        &parsed.user_argv,
    )
    .unwrap_or_else(|error| panic!("default resolution failed: {error}"));
    assert_eq!(decision.user_argv, parsed.user_argv);
    assert!(decision.effective_argv.starts_with(&decision.user_argv));
    assert_eq!(
        decision.effective_argv.len(),
        decision.user_argv.len() + decision.injected.len()
    );
});
