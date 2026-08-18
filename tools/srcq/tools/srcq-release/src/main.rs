#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const FIXED_AST_GREP: &str = "0.42.0";
const VERIFIED_AST_GREP: [&str; 3] = ["0.41.1", "0.42.0", "0.44.1"];
const VERIFIED_RIPGREP: [&str; 2] = ["15.1.0", "15.2.0"];
const VERIFIED_FD: [&str; 1] = ["10.4.2"];
const THIRD_PARTY_LICENSES_TITLE: &str = "SRCQ THIRD-PARTY LICENSES";

fn main() {
    if let Err(error) = run() {
        eprintln!("srcq-release: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args_os();
    let _program = args.next();
    let command = args
        .next()
        .and_then(|value| value.into_string().ok())
        .ok_or_else(usage)?;
    if command != "package" {
        return Err(usage());
    }
    let options = parse_options(args)?;
    let request = PackageRequest {
        metadata: required_path(&options, "metadata")?,
        cargo_lock: required_path(&options, "cargo-lock")?,
        binary: required_path(&options, "binary")?,
        readme: required_path(&options, "readme")?,
        license: required_path(&options, "license")?,
        license_mit: required_path(&options, "license-mit")?,
        license_apache: required_path(&options, "license-apache")?,
        notice: required_path(&options, "notice")?,
        out_dir: required_path(&options, "out-dir")?,
        version: required(&options, "version")?.to_owned(),
        target: required(&options, "target")?.to_owned(),
        source_revision: required(&options, "source-revision")?.to_owned(),
        source_date_epoch: required(&options, "source-date-epoch")?
            .parse::<u64>()
            .map_err(|_| "--source-date-epoch must be an unsigned integer".to_owned())?,
        rustc: required(&options, "rustc")?.to_owned(),
    };
    validate_release_token("version", &request.version)?;
    validate_release_token("target", &request.target)?;
    validate_revision(&request.source_revision)?;
    let output = package(&request)?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "archive": output.archive,
            "sha256": output.archive_sha256,
            "manifest": output.manifest,
            "sbom": output.sbom,
            "thirdPartyLicenses": output.third_party_licenses
        }))
        .map_err(|error| error.to_string())?
    );
    Ok(())
}

fn usage() -> String {
    "usage: srcq-release package --metadata PATH --cargo-lock PATH --binary PATH --readme PATH --license PATH --license-mit PATH --license-apache PATH --notice PATH --out-dir PATH --version VERSION --target TRIPLE --source-revision REVISION --source-date-epoch SECONDS --rustc VERSION".to_owned()
}

fn parse_options(
    args: impl Iterator<Item = std::ffi::OsString>,
) -> Result<BTreeMap<String, String>, String> {
    let tokens: Vec<_> = args.collect();
    if tokens.len() % 2 != 0 {
        return Err("every release option requires one value".to_owned());
    }
    let mut options = BTreeMap::new();
    for pair in tokens.chunks_exact(2) {
        let flag = pair[0]
            .to_str()
            .ok_or_else(|| "release option names must be UTF-8".to_owned())?;
        let name = flag
            .strip_prefix("--")
            .ok_or_else(|| format!("unexpected positional argument: {flag}"))?;
        let value = pair[1]
            .to_str()
            .ok_or_else(|| format!("--{name} value must be UTF-8"))?;
        if options.insert(name.to_owned(), value.to_owned()).is_some() {
            return Err(format!("duplicate option: --{name}"));
        }
    }
    Ok(options)
}

fn required<'a>(options: &'a BTreeMap<String, String>, name: &str) -> Result<&'a str, String> {
    options
        .get(name)
        .map(String::as_str)
        .ok_or_else(|| format!("missing --{name}"))
}

fn required_path(options: &BTreeMap<String, String>, name: &str) -> Result<PathBuf, String> {
    required(options, name).map(PathBuf::from)
}

fn validate_release_token(name: &str, value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'+' | b'_'))
    {
        return Err(format!("--{name} is not release-safe: {value:?}"));
    }
    Ok(())
}

fn validate_revision(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 256
        || value
            .chars()
            .any(|character| character.is_control() || matches!(character, '/' | '\\'))
    {
        return Err("--source-revision must be a bounded printable identifier".to_owned());
    }
    Ok(())
}

struct PackageRequest {
    metadata: PathBuf,
    cargo_lock: PathBuf,
    binary: PathBuf,
    readme: PathBuf,
    license: PathBuf,
    license_mit: PathBuf,
    license_apache: PathBuf,
    notice: PathBuf,
    out_dir: PathBuf,
    version: String,
    target: String,
    source_revision: String,
    source_date_epoch: u64,
    rustc: String,
}

struct PackageOutput {
    archive: String,
    archive_sha256: String,
    manifest: String,
    sbom: String,
    third_party_licenses: String,
}

fn package(request: &PackageRequest) -> Result<PackageOutput, String> {
    let metadata_bytes = read(&request.metadata)?;
    let metadata: Value = serde_json::from_slice(&metadata_bytes)
        .map_err(|error| format!("invalid cargo metadata: {error}"))?;
    let cargo_lock = read(&request.cargo_lock)?;
    let binary = read(&request.binary)?;
    let readme = read(&request.readme)?;
    let license = read(&request.license)?;
    let license_mit = read(&request.license_mit)?;
    let license_apache = read(&request.license_apache)?;
    let notice = read(&request.notice)?;
    let binary_name = if request.target.contains("windows") {
        "srcq.exe"
    } else {
        "srcq"
    };
    let package_name = format!("srcq-{}-{}", request.version, request.target);
    let archive_name = format!("{package_name}.zip");
    let manifest_name = format!("{package_name}.manifest.json");
    let sbom_name = format!("{package_name}.sbom.spdx.json");
    let third_party_name = format!("{package_name}.third-party-licenses.txt");
    let sbom = build_sbom(request, &metadata, &metadata_bytes)?;
    let sbom_bytes = json_bytes(&sbom)?;
    let third_party_licenses = build_third_party_licenses(request, &metadata)?;

    let material_files = [
        file_record(binary_name, &binary),
        file_record("README.md", &readme),
        file_record("LICENSE", &license),
        file_record("LICENSE-MIT", &license_mit),
        file_record("LICENSE-APACHE", &license_apache),
        file_record("NOTICE", &notice),
        file_record("THIRD_PARTY_LICENSES.txt", &third_party_licenses),
        file_record("sbom.spdx.json", &sbom_bytes),
    ];
    let manifest = json!({
        "schema": "srcq.release/v1",
        "name": "srcq",
        "version": request.version,
        "target": request.target,
        "archive": archive_name,
        "binary": binary_name,
        "source": {
            "revision": request.source_revision,
            "sourceDateEpoch": request.source_date_epoch,
            "cargoLockSha256": sha256(&cargo_lock)
        },
        "build": {
            "rustc": request.rustc,
            "rustToolchain": "1.85.0",
            "profile": "release",
            "deterministicArchive": true
        },
        "astGrepCompatibility": {
            "fixed": FIXED_AST_GREP,
            "verified": VERIFIED_AST_GREP
        },
        "nativeEngineCompatibility": {
            "astGrep": {"executable": "ast-grep", "bundled": false, "verified": VERIFIED_AST_GREP},
            "ripgrep": {"executable": "rg.exe", "bundled": false, "verified": VERIFIED_RIPGREP},
            "fd": {"executable": "fd.exe", "bundled": false, "verified": VERIFIED_FD}
        },
        "runtime": {
            "requiredExecutable": "ast-grep",
            "requiredExecutables": ["ast-grep", "rg.exe", "fd.exe"],
            "node": false,
            "python": false
        },
        "files": material_files
    });
    let manifest_bytes = json_bytes(&manifest)?;

    let mut entries = vec![
        ZipEntry::executable(format!("{package_name}/{binary_name}"), binary),
        ZipEntry::regular(format!("{package_name}/README.md"), readme),
        ZipEntry::regular(format!("{package_name}/LICENSE"), license),
        ZipEntry::regular(format!("{package_name}/LICENSE-MIT"), license_mit),
        ZipEntry::regular(format!("{package_name}/LICENSE-APACHE"), license_apache),
        ZipEntry::regular(format!("{package_name}/NOTICE"), notice),
        ZipEntry::regular(
            format!("{package_name}/THIRD_PARTY_LICENSES.txt"),
            third_party_licenses.clone(),
        ),
        ZipEntry::regular(
            format!("{package_name}/manifest.json"),
            manifest_bytes.clone(),
        ),
        ZipEntry::regular(format!("{package_name}/sbom.spdx.json"), sbom_bytes.clone()),
    ];
    entries.sort_by(|left, right| left.name.cmp(&right.name));
    let archive_bytes = deterministic_zip(&entries)?;
    let archive_sha256 = sha256(&archive_bytes);

    fs::create_dir_all(&request.out_dir)
        .map_err(|error| format!("failed to create {}: {error}", request.out_dir.display()))?;
    let archive_path = request.out_dir.join(&archive_name);
    let checksum_name = format!("{archive_name}.sha256");
    write_atomic(&archive_path, &archive_bytes)?;
    write_atomic(
        &request.out_dir.join(&checksum_name),
        format!("{archive_sha256}  {archive_name}\n").as_bytes(),
    )?;
    write_atomic(&request.out_dir.join(&manifest_name), &manifest_bytes)?;
    write_atomic(&request.out_dir.join(&sbom_name), &sbom_bytes)?;
    write_atomic(
        &request.out_dir.join(&third_party_name),
        &third_party_licenses,
    )?;

    Ok(PackageOutput {
        archive: archive_name,
        archive_sha256,
        manifest: manifest_name,
        sbom: sbom_name,
        third_party_licenses: third_party_name,
    })
}

fn read(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|error| format!("failed to read {}: {error}", path.display()))
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let temporary = path.with_extension(format!(
        "{}.tmp",
        path.extension()
            .and_then(|extension| extension.to_str())
            .unwrap_or("release")
    ));
    fs::write(&temporary, bytes)
        .map_err(|error| format!("failed to write {}: {error}", temporary.display()))?;
    if path.exists() {
        fs::remove_file(path)
            .map_err(|error| format!("failed to replace {}: {error}", path.display()))?;
    }
    fs::rename(&temporary, path)
        .map_err(|error| format!("failed to commit {}: {error}", path.display()))
}

fn json_bytes(value: &Value) -> Result<Vec<u8>, String> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn file_record(path: &str, bytes: &[u8]) -> Value {
    json!({
        "path": path,
        "bytes": bytes.len(),
        "sha256": sha256(bytes)
    })
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn build_third_party_licenses(
    request: &PackageRequest,
    metadata: &Value,
) -> Result<Vec<u8>, String> {
    let packages = metadata["packages"]
        .as_array()
        .ok_or_else(|| "cargo metadata has no packages array".to_owned())?;
    let nodes = metadata["resolve"]["nodes"]
        .as_array()
        .ok_or_else(|| "cargo metadata has no resolve.nodes".to_owned())?;
    let package_by_id: BTreeMap<_, _> = packages
        .iter()
        .filter_map(|package| package["id"].as_str().map(|id| (id.to_owned(), package)))
        .collect();
    let node_by_id: BTreeMap<_, _> = nodes
        .iter()
        .filter_map(|node| node["id"].as_str().map(|id| (id.to_owned(), node)))
        .collect();
    let root_id = packages
        .iter()
        .find(|package| package["name"] == "srcq-cli")
        .and_then(|package| package["id"].as_str())
        .ok_or_else(|| "cargo metadata does not contain srcq-cli".to_owned())?;
    let reachable = release_reachable(root_id, &node_by_id);
    let mut ordered: Vec<_> = reachable
        .iter()
        .filter_map(|id| package_by_id.get(id).map(|package| (id.clone(), *package)))
        .filter(|(_, package)| package["source"].as_str().is_some())
        .collect();
    ordered.sort_by(|left, right| {
        package_order_key(left.1, &left.0).cmp(&package_order_key(right.1, &right.0))
    });

    let mut text_by_hash: BTreeMap<String, (Vec<u8>, BTreeSet<String>)> = BTreeMap::new();
    let mut package_index = Vec::new();
    for (_, package) in &ordered {
        let name = package["name"].as_str().unwrap_or("unknown");
        let version = package["version"].as_str().unwrap_or("unknown");
        let declared = package["license"]
            .as_str()
            .ok_or_else(|| format!("{name} {version} does not declare a license"))?;
        if !allowed_license_expression(declared) {
            return Err(format!(
                "{name} {version} has an unreviewed license expression: {declared}"
            ));
        }
        let manifest_path = package["manifest_path"]
            .as_str()
            .ok_or_else(|| format!("{name} {version} has no manifest path"))?;
        let package_root = Path::new(manifest_path)
            .parent()
            .ok_or_else(|| format!("{name} {version} manifest has no parent"))?;
        let mut license_paths = Vec::new();
        for entry in fs::read_dir(package_root)
            .map_err(|error| format!("failed to inspect {name} {version}: {error}"))?
        {
            let entry = entry.map_err(|error| format!("failed to inspect {name}: {error}"))?;
            if !entry
                .file_type()
                .map_err(|error| format!("failed to inspect {}: {error}", entry.path().display()))?
                .is_file()
            {
                continue;
            }
            let file_name = entry.file_name().to_string_lossy().into_owned();
            let uppercase = file_name.to_ascii_uppercase();
            if ["LICENSE", "LICENCE", "COPYING", "UNLICENSE", "NOTICE"]
                .iter()
                .any(|prefix| uppercase.starts_with(prefix))
            {
                license_paths.push((file_name, entry.path()));
            }
        }
        license_paths.sort_by(|left, right| left.0.cmp(&right.0));
        if license_paths.is_empty() {
            return Err(format!(
                "{name} {version} has no packaged license/notice file"
            ));
        }
        package_index.push(format!(
            "PACKAGE: {name} {version}\nDECLARED: {declared}\nSOURCE: {}\n",
            package["source"].as_str().unwrap_or("NOASSERTION")
        ));
        for (file_name, path) in license_paths {
            let bytes = read(&path)?;
            if bytes.is_empty() {
                return Err(format!(
                    "{name} {version} contains an empty license file: {file_name}"
                ));
            }
            let hash = sha256(&bytes);
            package_index.push(format!("  {file_name} -> LicenseText-{hash}\n"));
            let entry = text_by_hash
                .entry(hash)
                .or_insert_with(|| (bytes, BTreeSet::new()));
            entry.1.insert(format!("{name} {version}/{file_name}"));
        }
        package_index.push("\n".to_owned());
    }

    let mut output = third_party_licenses_preamble(&request.target, ordered.len());
    for line in package_index {
        output.push_str(&line);
    }
    output.push_str("=== LICENSE TEXTS ===\n\n");
    for (hash, (bytes, uses)) in text_by_hash {
        output.push_str(&format!(
            "--- LicenseText-{hash} ---\nUSED BY:\n  {}\n\n",
            uses.into_iter().collect::<Vec<_>>().join("\n  ")
        ));
        output.push_str(&String::from_utf8_lossy(&bytes));
        if !output.ends_with('\n') {
            output.push('\n');
        }
        output.push('\n');
    }
    Ok(output.into_bytes())
}

fn third_party_licenses_preamble(target: &str, package_count: usize) -> String {
    format!(
        "{THIRD_PARTY_LICENSES_TITLE}\nTARGET: {target}\nPACKAGES: {package_count}\n\nThis file is generated from target-filtered Cargo metadata. License texts are deduplicated by SHA-256; every package/file mapping is listed below.\n\n=== PACKAGE INDEX ===\n\n"
    )
}

fn allowed_license_expression(expression: &str) -> bool {
    matches!(
        expression,
        "MIT OR Apache-2.0"
            | "Apache-2.0 OR MIT"
            | "MIT/Apache-2.0"
            | "Apache-2.0/MIT"
            | "MIT"
            | "Unlicense OR MIT"
            | "BSD-2-Clause"
            | "BSD-3-Clause"
            | "BSD-2-Clause OR Apache-2.0 OR MIT"
            | "(MIT OR Apache-2.0) AND Unicode-3.0"
            | "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT"
            | "Apache-2.0 OR MIT OR Zlib"
            | "MIT OR Apache-2.0 OR Zlib"
            | "ISC"
            | "Zlib"
            | "CC0-1.0"
    )
}

fn build_sbom(
    request: &PackageRequest,
    metadata: &Value,
    metadata_bytes: &[u8],
) -> Result<Value, String> {
    let packages = metadata["packages"]
        .as_array()
        .ok_or_else(|| "cargo metadata has no packages array".to_owned())?;
    let resolve = metadata["resolve"]
        .as_object()
        .ok_or_else(|| "cargo metadata has no resolve graph".to_owned())?;
    let nodes = resolve
        .get("nodes")
        .and_then(Value::as_array)
        .ok_or_else(|| "cargo metadata has no resolve.nodes".to_owned())?;
    let package_by_id: BTreeMap<_, _> = packages
        .iter()
        .filter_map(|package| package["id"].as_str().map(|id| (id.to_owned(), package)))
        .collect();
    let node_by_id: BTreeMap<_, _> = nodes
        .iter()
        .filter_map(|node| node["id"].as_str().map(|id| (id.to_owned(), node)))
        .collect();
    let root_id = packages
        .iter()
        .find(|package| package["name"] == "srcq-cli")
        .and_then(|package| package["id"].as_str())
        .ok_or_else(|| "cargo metadata does not contain srcq-cli".to_owned())?
        .to_owned();
    let reachable = release_reachable(&root_id, &node_by_id);
    let mut ordered: Vec<_> = reachable
        .iter()
        .filter_map(|id| package_by_id.get(id).map(|package| (id.clone(), *package)))
        .collect();
    ordered.sort_by(|left, right| {
        package_order_key(left.1, &left.0).cmp(&package_order_key(right.1, &right.0))
    });
    let spdx_ids: BTreeMap<_, _> = ordered
        .iter()
        .enumerate()
        .map(|(index, (id, package))| {
            (
                id.clone(),
                format!(
                    "SPDXRef-Package-{index:04}-{}",
                    sanitize_spdx(package["name"].as_str().unwrap_or("unknown"))
                ),
            )
        })
        .collect();
    let spdx_packages: Vec<_> = ordered
        .iter()
        .map(|(id, package)| {
            let name = package["name"].as_str().unwrap_or("unknown");
            let version = if id == &root_id {
                request.version.as_str()
            } else {
                package["version"].as_str().unwrap_or("unknown")
            };
            json!({
                "name": name,
                "SPDXID": spdx_ids[id],
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": false,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": package["license"].as_str().unwrap_or("NOASSERTION"),
                "supplier": "NOASSERTION"
            })
        })
        .collect();
    let mut relationship_keys = BTreeSet::new();
    relationship_keys.insert((
        "SPDXRef-DOCUMENT".to_owned(),
        "DESCRIBES".to_owned(),
        spdx_ids[&root_id].clone(),
    ));
    for id in &reachable {
        let Some(node) = node_by_id.get(id) else {
            continue;
        };
        for dependency in release_dependencies(node) {
            if reachable.contains(dependency) {
                relationship_keys.insert((
                    spdx_ids[id].clone(),
                    "DEPENDS_ON".to_owned(),
                    spdx_ids[dependency].clone(),
                ));
            }
        }
    }
    let relationships: Vec<_> = relationship_keys
        .into_iter()
        .map(|(from, relationship, to)| {
            json!({
                "spdxElementId": from,
                "relationshipType": relationship,
                "relatedSpdxElement": to
            })
        })
        .collect();
    let namespace_seed = sha256(metadata_bytes);
    Ok(json!({
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": format!("srcq-{}-{}", request.version, request.target),
        "documentNamespace": format!(
            "urn:srcq:spdx:{}:{}:{}",
            request.version,
            request.target,
            &namespace_seed[..16]
        ),
        "creationInfo": {
            "created": unix_to_rfc3339(request.source_date_epoch)?,
            "creators": [format!("Tool: srcq-release-{}", env!("CARGO_PKG_VERSION"))]
        },
        "packages": spdx_packages,
        "relationships": relationships
    }))
}

fn package_order_key(package: &Value, id: &str) -> (String, String, String) {
    (
        package["name"].as_str().unwrap_or("unknown").to_owned(),
        package["version"].as_str().unwrap_or("unknown").to_owned(),
        id.to_owned(),
    )
}

fn release_reachable(root: &str, nodes: &BTreeMap<String, &Value>) -> BTreeSet<String> {
    let mut reached = BTreeSet::new();
    let mut queue = VecDeque::from([root.to_owned()]);
    while let Some(id) = queue.pop_front() {
        if !reached.insert(id.clone()) {
            continue;
        }
        if let Some(node) = nodes.get(&id) {
            for dependency in release_dependencies(node) {
                if !reached.contains(dependency) {
                    queue.push_back(dependency.to_owned());
                }
            }
        }
    }
    reached
}

fn release_dependencies(node: &Value) -> Vec<&str> {
    node["deps"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|dependency| {
            let kinds = dependency["dep_kinds"].as_array();
            kinds.is_none_or(|kinds| {
                kinds.is_empty()
                    || kinds.iter().any(|kind| {
                        kind["kind"].is_null()
                            || kind["kind"].as_str().is_some_and(|value| value == "build")
                    })
            })
        })
        .filter_map(|dependency| dependency["pkg"].as_str())
        .collect()
}

fn sanitize_spdx(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '.' | '-') {
                character
            } else {
                '-'
            }
        })
        .collect()
}

fn unix_to_rfc3339(seconds: u64) -> Result<String, String> {
    let seconds =
        i64::try_from(seconds).map_err(|_| "SOURCE_DATE_EPOCH is too large".to_owned())?;
    let days = seconds / 86_400;
    let day_seconds = seconds % 86_400;
    let (year, month, day) = civil_from_days(days);
    let hour = day_seconds / 3_600;
    let minute = (day_seconds % 3_600) / 60;
    let second = day_seconds % 60;
    Ok(format!(
        "{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z"
    ))
}

fn civil_from_days(days_since_epoch: i64) -> (i64, i64, i64) {
    let days = days_since_epoch + 719_468;
    let era = days.div_euclid(146_097);
    let day_of_era = days - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_prime + 2) / 5 + 1;
    let month = month_prime + if month_prime < 10 { 3 } else { -9 };
    if month <= 2 {
        year += 1;
    }
    (year, month, day)
}

struct ZipEntry {
    name: String,
    bytes: Vec<u8>,
    unix_mode: u32,
}

impl ZipEntry {
    fn regular(name: String, bytes: Vec<u8>) -> Self {
        Self {
            name,
            bytes,
            unix_mode: 0o100644,
        }
    }

    fn executable(name: String, bytes: Vec<u8>) -> Self {
        Self {
            name,
            bytes,
            unix_mode: 0o100755,
        }
    }
}

struct CentralRecord {
    name: Vec<u8>,
    crc32: u32,
    size: u32,
    offset: u32,
    unix_mode: u32,
}

fn deterministic_zip(entries: &[ZipEntry]) -> Result<Vec<u8>, String> {
    let mut output = Vec::new();
    let mut central = Vec::new();
    for entry in entries {
        let name = entry.name.as_bytes();
        let name_len = u16::try_from(name.len()).map_err(|_| "ZIP entry name is too long")?;
        let size = u32::try_from(entry.bytes.len()).map_err(|_| "ZIP entry exceeds 4 GiB")?;
        let offset = u32::try_from(output.len()).map_err(|_| "ZIP archive exceeds 4 GiB")?;
        let crc32 = crc32(&entry.bytes);
        push_u32(&mut output, 0x0403_4b50);
        push_u16(&mut output, 20);
        push_u16(&mut output, 0x0800);
        push_u16(&mut output, 0);
        push_u16(&mut output, 0);
        push_u16(&mut output, 33);
        push_u32(&mut output, crc32);
        push_u32(&mut output, size);
        push_u32(&mut output, size);
        push_u16(&mut output, name_len);
        push_u16(&mut output, 0);
        output.extend_from_slice(name);
        output.extend_from_slice(&entry.bytes);
        central.push(CentralRecord {
            name: name.to_vec(),
            crc32,
            size,
            offset,
            unix_mode: entry.unix_mode,
        });
    }
    let central_offset = u32::try_from(output.len()).map_err(|_| "ZIP archive exceeds 4 GiB")?;
    for record in &central {
        push_u32(&mut output, 0x0201_4b50);
        push_u16(&mut output, 0x0314);
        push_u16(&mut output, 20);
        push_u16(&mut output, 0x0800);
        push_u16(&mut output, 0);
        push_u16(&mut output, 0);
        push_u16(&mut output, 33);
        push_u32(&mut output, record.crc32);
        push_u32(&mut output, record.size);
        push_u32(&mut output, record.size);
        push_u16(
            &mut output,
            u16::try_from(record.name.len()).map_err(|_| "ZIP entry name is too long")?,
        );
        push_u16(&mut output, 0);
        push_u16(&mut output, 0);
        push_u16(&mut output, 0);
        push_u16(&mut output, 0);
        push_u32(&mut output, record.unix_mode << 16);
        push_u32(&mut output, record.offset);
        output.extend_from_slice(&record.name);
    }
    let central_size = u32::try_from(output.len())
        .map_err(|_| "ZIP archive exceeds 4 GiB")?
        .checked_sub(central_offset)
        .ok_or_else(|| "invalid central directory bounds".to_owned())?;
    let entry_count = u16::try_from(central.len()).map_err(|_| "too many ZIP entries")?;
    push_u32(&mut output, 0x0605_4b50);
    push_u16(&mut output, 0);
    push_u16(&mut output, 0);
    push_u16(&mut output, entry_count);
    push_u16(&mut output, entry_count);
    push_u32(&mut output, central_size);
    push_u32(&mut output, central_offset);
    push_u16(&mut output, 0);
    Ok(output)
}

fn push_u16(output: &mut Vec<u8>, value: u16) {
    output.extend_from_slice(&value.to_le_bytes());
}

fn push_u32(output: &mut Vec<u8>, value: u32) {
    output.extend_from_slice(&value.to_le_bytes());
}

fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = u32::MAX;
    for byte in bytes {
        crc ^= u32::from(*byte);
        for _ in 0..8 {
            let mask = 0u32.wrapping_sub(crc & 1);
            crc = (crc >> 1) ^ (0xedb8_8320 & mask);
        }
    }
    !crc
}

#[cfg(test)]
mod tests {
    use super::{
        allowed_license_expression, crc32, deterministic_zip, third_party_licenses_preamble,
        unix_to_rfc3339, ZipEntry,
    };

    #[test]
    fn license_policy_accepts_reviewed_permissive_expressions_only() {
        assert!(allowed_license_expression(
            "(MIT OR Apache-2.0) AND Unicode-3.0"
        ));
        assert!(allowed_license_expression("BSD-3-Clause"));
        assert!(!allowed_license_expression("GPL-3.0-only"));
        assert!(!allowed_license_expression("NOASSERTION"));
    }

    #[test]
    fn crc32_matches_standard_vector() {
        assert_eq!(crc32(b"123456789"), 0xcbf4_3926);
    }

    #[test]
    fn source_date_epoch_is_rendered_deterministically() {
        assert_eq!(unix_to_rfc3339(0).expect("epoch"), "1970-01-01T00:00:00Z");
        assert_eq!(
            unix_to_rfc3339(1_767_225_599).expect("year end"),
            "2025-12-31T23:59:59Z"
        );
    }

    #[test]
    fn third_party_license_preamble_uses_srcq_product_identity() {
        let preamble = third_party_licenses_preamble("x86_64-pc-windows-msvc", 52);
        assert!(preamble.starts_with("SRCQ THIRD-PARTY LICENSES\n"));
        assert!(!preamble.contains("SGY THIRD-PARTY LICENSES"));
    }

    #[test]
    fn zip_bytes_are_stable() {
        let entries = vec![
            ZipEntry::regular("srcq/LICENSE".to_owned(), b"license\n".to_vec()),
            ZipEntry::executable("srcq/srcq".to_owned(), b"binary".to_vec()),
        ];
        let first = deterministic_zip(&entries).expect("first ZIP");
        let second = deterministic_zip(&entries).expect("second ZIP");
        assert_eq!(first, second);
        assert!(first.starts_with(&0x0403_4b50u32.to_le_bytes()));
        assert!(first
            .windows(4)
            .any(|bytes| bytes == 0x0605_4b50u32.to_le_bytes()));
    }
}
