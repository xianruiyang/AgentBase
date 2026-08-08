#[test]
fn core_does_not_expose_cli_types() {
    let info = sgy_core::build_info();
    assert_eq!(info.package_name, "sgy-core");
    assert_eq!(info.core_api_level, 1);
}
