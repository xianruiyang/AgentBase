use std::env;

fn main() {
    println!("cargo:rerun-if-env-changed=SGY_BUILD_VERSION");
    let package_version = env::var("CARGO_PKG_VERSION").expect("Cargo provides CARGO_PKG_VERSION");
    let release_version = env::var("SGY_BUILD_VERSION").unwrap_or(package_version);
    assert!(
        !release_version.is_empty()
            && release_version.len() <= 128
            && release_version
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'+')),
        "SGY_BUILD_VERSION must be a non-empty release-safe version"
    );
    println!("cargo:rustc-env=SGY_BUILD_VERSION={release_version}");
}
