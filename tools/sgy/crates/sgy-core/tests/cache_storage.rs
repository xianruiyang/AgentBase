use std::{
    collections::HashSet,
    ffi::OsString,
    fs,
    io::{BufReader, Cursor},
    path::{Path, PathBuf},
    sync::{Arc, Barrier},
    thread,
    time::{Duration, SystemTime},
};

use serde_json::{json, Value};
use sgy_core::{
    cache::{
        default_cache_root, hash_argv, validate_cache_id, CacheAudit, CacheError, CacheIndexRecord,
        CacheLimits, CacheMode, CacheProcess, CacheQuery, CacheStore, CommittedCache, SourceFormat,
    },
    codec::{parse_single_json, parse_yaml_documents, ByteSpan, JsonLines},
    invocation::Profile,
};
use sha2::{Digest, Sha256};
use tempfile::{tempdir, TempDir};

const SECRET_PATTERN: &str = "secret-pattern($SENSITIVE)";

struct Fixture {
    _directory: TempDir,
    workspace: PathBuf,
    cache_root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempdir().expect("fixture root");
        let workspace = directory.path().join("workspace");
        let cache_root = directory.path().join("user-cache");
        fs::create_dir(&workspace).expect("workspace");
        Self {
            _directory: directory,
            workspace,
            cache_root,
        }
    }

    fn store(&self, limits: CacheLimits) -> CacheStore {
        CacheStore::open(&self.cache_root, Some(&self.workspace), limits).expect("cache store")
    }
}

fn audit(suffix: &str) -> CacheAudit {
    let user = vec![
        OsString::from("run"),
        OsString::from("--pattern"),
        OsString::from(format!("{SECRET_PATTERN}-{suffix}")),
    ];
    let mut effective = user.clone();
    effective.push(OsString::from("--json=stream"));
    CacheAudit::from_argv(
        "C:/tools/ast-grep.exe",
        "0.42.0",
        "D:/work/repo",
        &user,
        &effective,
        vec!["--json=stream".to_owned()],
        Profile::TokenSafe,
        CacheMode::Auto,
    )
}

fn commit_jsonl(store: &CacheStore, raw: &[u8], now: SystemTime, suffix: &str) -> CommittedCache {
    let mut staging = store
        .begin(SourceFormat::JsonLines, audit(suffix), now)
        .expect("begin staging");
    staging
        .stage_source(Cursor::new(raw))
        .expect("stage source");
    for record in JsonLines::new(BufReader::new(Cursor::new(raw))) {
        staging
            .add_source_record(&record.expect("valid JSONL"))
            .expect("index record");
    }
    staging
        .commit(CacheProcess::completed(0), now)
        .expect("commit cache")
}

fn parse_metadata(path: &Path) -> Value {
    let bytes = fs::read(path).expect("metadata bytes");
    parse_yaml_documents(&bytes)
        .expect("safe metadata YAML")
        .into_iter()
        .next()
        .expect("one metadata document")
}

fn directory_size(path: &Path) -> u64 {
    fs::read_dir(path)
        .expect("read entry")
        .map(|entry| {
            let entry = entry.expect("entry");
            let metadata = entry.metadata().expect("metadata");
            if metadata.is_dir() {
                directory_size(&entry.path())
            } else {
                metadata.len()
            }
        })
        .sum()
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn fixed_now() -> SystemTime {
    SystemTime::UNIX_EPOCH + Duration::from_secs(2_000_000_000)
}

#[test]
fn committed_jsonl_preserves_raw_bytes_hash_offsets_and_private_argv() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let raw = concat!(
        "{\"file\":\"src/a.ts\",\"text\":\"α\"}\r\n",
        "  {\"file\":\"src/b.ts\",\"ruleId\":\"r\"}\n"
    )
    .as_bytes();
    let committed = commit_jsonl(&store, raw, fixed_now(), "privacy");

    assert!(validate_cache_id(&committed.cache_id).is_ok());
    assert!(!committed.path.starts_with(&fixture.workspace));
    assert_eq!(
        fs::read(committed.path.join("native.jsonl")).expect("native source"),
        raw
    );
    assert_eq!(committed.source_bytes, raw.len() as u64);
    assert_eq!(committed.source_sha256, sha256(raw));
    assert_eq!(committed.record_count, 2);

    let index: Value =
        serde_json::from_slice(&fs::read(committed.path.join("index.json")).expect("index bytes"))
            .expect("index JSON");
    assert_eq!(index["schema"], "sgy.cache-index/v1");
    assert_eq!(index["cache_id"], committed.cache_id);
    assert_eq!(index["source_sha256"], sha256(raw));
    assert_eq!(index["record_count"], 2);
    for (ordinal, record) in index["records"]
        .as_array()
        .expect("records")
        .iter()
        .enumerate()
    {
        assert_eq!(record["id"], ordinal as u64);
        let start = record["byte_start"].as_u64().expect("start") as usize;
        let end = record["byte_end"].as_u64().expect("end") as usize;
        serde_json::from_slice::<Value>(&raw[start..end]).expect("independent JSON value");
        assert!(!raw[start..end].ends_with(b"\n"));
        assert!(!raw[start..end].ends_with(b"\r"));
    }

    let metadata_bytes = fs::read(committed.path.join("metadata.yaml")).expect("metadata");
    let metadata_text = String::from_utf8(metadata_bytes.clone()).expect("UTF-8 metadata");
    assert!(!metadata_text.contains(SECRET_PATTERN));
    let metadata = parse_yaml_documents(&metadata_bytes)
        .expect("metadata YAML")
        .remove(0);
    assert_eq!(metadata["schema"], "sgy.cache-metadata/v1");
    assert_eq!(metadata["state"], "committed");
    assert_eq!(metadata["source"]["bytes"], raw.len() as u64);
    assert_eq!(metadata["source"]["sha256"], sha256(raw));
    assert_eq!(
        metadata["invocation"]["user_argv_sha256"]
            .as_str()
            .expect("argv hash")
            .len(),
        64
    );
    assert!(committed.path.join("access.lock").is_file());
}

#[test]
fn dropped_or_incomplete_staging_never_appears_as_committed() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let now = SystemTime::now();
    let raw = b"{\"value\":1}\n";

    let abandoned_id = {
        let mut staging = store
            .begin(SourceFormat::JsonLines, audit("drop"), now)
            .expect("staging");
        let id = staging.cache_id().to_owned();
        staging.stage_source(Cursor::new(raw)).expect("source");
        id
    };
    assert!(!store.entry_path(&abandoned_id).expect("path").exists());
    assert_eq!(
        fs::read_dir(store.root().join(".staging"))
            .expect("staging root")
            .count(),
        0
    );

    let mut incomplete = store
        .begin(SourceFormat::JsonLines, audit("incomplete"), now)
        .expect("staging");
    let incomplete_id = incomplete.cache_id().to_owned();
    incomplete.stage_source(Cursor::new(raw)).expect("source");
    let path = incomplete
        .mark_incomplete(CacheProcess::incomplete("cancelled", Some(130)), now)
        .expect("retain incomplete");
    assert!(path.starts_with(store.root().join(".incomplete")));
    assert!(!store.entry_path(&incomplete_id).expect("path").exists());
    let metadata = parse_metadata(&path.join("metadata.yaml"));
    assert_eq!(metadata["state"], "incomplete");
    assert_eq!(metadata["process"]["failure"], "cancelled");
    assert_eq!(metadata["process"]["exit_code"], 130);

    let report = store
        .gc(now + Duration::from_secs(25 * 60 * 60))
        .expect("GC stale incomplete");
    assert_eq!(report.removed_incomplete, 1);
    assert!(!path.exists());
}

#[test]
fn invalid_spans_ids_and_pointer_indexes_cannot_commit() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let now = fixed_now();
    let raw = b"{\"value\":1}\n";

    let mut before_source = store
        .begin(SourceFormat::JsonLines, audit("before-source"), now)
        .expect("staging");
    let error = before_source
        .add_index_record(CacheIndexRecord {
            id: 0,
            byte_span: Some(ByteSpan::new(0, 1)),
            pointer: None,
            file: None,
            range: None,
            rule_id: None,
        })
        .expect_err("source must precede index");
    assert!(matches!(error, CacheError::InvalidIndex(_)));

    let mut bad_span = store
        .begin(SourceFormat::JsonLines, audit("bad-span"), now)
        .expect("staging");
    bad_span.stage_source(Cursor::new(raw)).expect("source");
    bad_span
        .add_index_record(CacheIndexRecord {
            id: 0,
            byte_span: Some(ByteSpan::new(0, raw.len() as u64)),
            pointer: None,
            file: None,
            range: None,
            rule_id: None,
        })
        .expect("record accepted before full validation");
    let error = bad_span
        .commit(CacheProcess::completed(0), now)
        .expect_err("span includes newline");
    assert!(matches!(error, CacheError::InvalidIndex(_)));

    let array = json!([{"file": "a.ts"}, {"file": "b.ts"}]);
    let raw_array = serde_json::to_vec(&array).expect("array JSON");
    let mut pointer = store
        .begin(SourceFormat::JsonArray, audit("pointer"), now)
        .expect("staging");
    pointer
        .stage_source(Cursor::new(&raw_array))
        .expect("array source");
    pointer
        .add_index_record(CacheIndexRecord::with_pointer(0, "/0", &array[0]))
        .expect("pointer zero");
    pointer
        .add_index_record(CacheIndexRecord::with_pointer(1, "/1", &array[1]))
        .expect("pointer one");
    let committed = pointer
        .commit(CacheProcess::completed(0), now)
        .expect("pointer commit");
    let index: Value =
        serde_json::from_slice(&fs::read(committed.path.join("index.json")).expect("index"))
            .expect("index JSON");
    assert_eq!(index["records"][0]["pointer"], "/0");
    assert_eq!(index["records"][1]["pointer"], "/1");
    let verified = store
        .open_verified(&committed.cache_id, now + Duration::from_secs(1))
        .expect("verified array");
    assert_eq!(verified.result(1).expect("array result"), array[1]);
}

#[test]
fn json_value_and_sarif_indexes_match_the_native_source_contract() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let now = fixed_now();

    let raw_value = b" \r\n{\"file\":\"src/value.ts\",\"value\":1}\n";
    let parsed = parse_single_json(raw_value).expect("JSON value");
    let mut value_staging = store
        .begin(SourceFormat::JsonValue, audit("json-value"), now)
        .expect("staging");
    value_staging
        .stage_source(Cursor::new(raw_value))
        .expect("source");
    value_staging
        .add_source_record(&parsed)
        .expect("value index");
    let value_cache = value_staging
        .commit(CacheProcess::completed(0), now)
        .expect("value commit");
    assert_eq!(
        fs::read(value_cache.path.join("native.json")).expect("native JSON"),
        raw_value
    );

    let sarif = json!({
        "version": "2.1.0",
        "runs": [
            {"results": [{"ruleId": "first"}, {"ruleId": "second"}]},
            {"results": [{"ruleId": "third"}]}
        ]
    });
    let raw_sarif = serde_json::to_vec(&sarif).expect("SARIF JSON");
    let pointers = [
        "/runs/0/results/0",
        "/runs/0/results/1",
        "/runs/1/results/0",
    ];
    let values = [
        &sarif["runs"][0]["results"][0],
        &sarif["runs"][0]["results"][1],
        &sarif["runs"][1]["results"][0],
    ];
    let mut sarif_staging = store
        .begin(SourceFormat::Sarif, audit("sarif"), now)
        .expect("staging");
    sarif_staging
        .stage_source(Cursor::new(&raw_sarif))
        .expect("source");
    for (id, (pointer, value)) in pointers.iter().zip(values).enumerate() {
        sarif_staging
            .add_index_record(CacheIndexRecord::with_pointer(id as u64, *pointer, value))
            .expect("SARIF index");
    }
    let sarif_cache = sarif_staging
        .commit(CacheProcess::completed(0), now)
        .expect("SARIF commit");
    let index: Value = serde_json::from_slice(
        &fs::read(sarif_cache.path.join("index.json")).expect("SARIF index"),
    )
    .expect("index JSON");
    assert_eq!(index["record_count"], 3);
    for (position, pointer) in pointers.iter().enumerate() {
        assert_eq!(index["records"][position]["pointer"], *pointer);
    }
    let verified_sarif = store
        .open_verified(&sarif_cache.cache_id, now + Duration::from_secs(1))
        .expect("verified SARIF");
    assert_eq!(
        verified_sarif.result(2).expect("SARIF result")["ruleId"],
        "third"
    );

    let located = json!({
        "ruleId": "located",
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": "src/located.ts"},
                "region": {"startLine": 2, "startColumn": 1}
            }
        }]
    });
    let located_index = CacheIndexRecord::with_sarif_pointer(3, "/runs/1/results/1", &located);
    assert_eq!(located_index.file.as_deref(), Some("src/located.ts"));
    assert_eq!(located_index.rule_id.as_deref(), Some("located"));
    assert_eq!(
        located_index.range.as_ref().expect("SARIF region")["startLine"],
        2
    );

    let mut incomplete = store
        .begin(SourceFormat::Sarif, audit("sarif-incomplete"), now)
        .expect("staging");
    incomplete
        .stage_source(Cursor::new(&raw_sarif))
        .expect("source");
    incomplete
        .add_index_record(CacheIndexRecord::with_pointer(0, pointers[0], values[0]))
        .expect("first SARIF index");
    let error = incomplete
        .commit(CacheProcess::completed(0), now)
        .expect_err("incomplete SARIF index must fail");
    assert!(matches!(error, CacheError::InvalidIndex(_)));
}

#[test]
fn verified_get_query_touch_and_remove_use_the_committed_source() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let now = fixed_now();
    let raw = concat!(
        "{\"file\":\"src/a.ts\",\"ruleId\":\"r1\",\"text\":\"first\"}\n",
        "{\"file\":\"src/b.ts\",\"ruleId\":\"r2\",\"text\":\"second\"}\n",
        "{\"file\":\"src/a.ts\",\"ruleId\":\"r1\",\"text\":\"third\"}\n"
    )
    .as_bytes();
    let committed = commit_jsonl(&store, raw, now, "verified");
    let before = parse_metadata(&committed.path.join("metadata.yaml"));
    let accessed_at = now + Duration::from_secs(60 * 60);

    let verified = store
        .open_verified(&committed.cache_id, accessed_at)
        .expect("verified cache");
    assert_eq!(verified.cache_id(), committed.cache_id);
    assert_eq!(verified.source_format(), SourceFormat::JsonLines);
    assert_eq!(verified.record_count(), 3);
    assert_eq!(verified.result(1).expect("result one")["text"], "second");
    assert_eq!(verified.field(2, "/text").expect("text field"), "third");
    assert!(matches!(
        verified.field(2, "text"),
        Err(CacheError::InvalidSelection(_))
    ));

    let query = verified
        .query(&CacheQuery {
            file: Some("src/a.ts".to_owned()),
            rule_id: Some("r1".to_owned()),
            offset: 1,
            limit: 1,
        })
        .expect("indexed query");
    assert_eq!(query.total, 2);
    assert_eq!(query.shown, 1);
    assert!(query.complete);
    assert_eq!(query.results[0].id, 2);
    assert_eq!(query.results[0].value["text"], "third");

    let after = parse_metadata(&committed.path.join("metadata.yaml"));
    assert_ne!(before["last_access_at"], after["last_access_at"]);
    assert_eq!(
        verified.metadata()["last_access_at"],
        after["last_access_at"]
    );
    assert!(matches!(
        store.remove(&committed.cache_id),
        Err(CacheError::Busy(_))
    ));
    drop(verified);
    store.remove(&committed.cache_id).expect("remove cache");
    assert!(matches!(
        store.open_verified(&committed.cache_id, accessed_at),
        Err(CacheError::NotFound(_))
    ));
}

#[test]
fn verified_read_rejects_corruption_without_touching_metadata() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let now = fixed_now();
    let committed = commit_jsonl(&store, b"{\"text\":\"safe\"}\n", now, "corrupt");
    let metadata_path = committed.path.join("metadata.yaml");
    let metadata_before = fs::read(&metadata_path).expect("metadata before");
    fs::write(
        committed.path.join("native.jsonl"),
        b"{\"text\":\"evil\"}\n",
    )
    .expect("corrupt source");

    let error = store
        .open_verified(&committed.cache_id, now + Duration::from_secs(60))
        .expect_err("corrupt cache must fail");
    assert!(matches!(error, CacheError::Verification(_)));
    assert_eq!(
        fs::read(&metadata_path).expect("metadata after"),
        metadata_before
    );
}

#[test]
fn source_mutation_missing_records_and_id_collision_are_detected() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let now = fixed_now();
    let raw = b"{\"value\":1}\n{\"value\":2}\n";

    let mut missing = store
        .begin(SourceFormat::JsonLines, audit("missing"), now)
        .expect("staging");
    missing.stage_source(Cursor::new(raw)).expect("source");
    let first = JsonLines::new(BufReader::new(Cursor::new(raw)))
        .next()
        .expect("first")
        .expect("record");
    missing.add_source_record(&first).expect("first index");
    let error = missing
        .commit(CacheProcess::completed(0), now)
        .expect_err("missing second record");
    assert!(matches!(error, CacheError::InvalidIndex(_)));

    let mut mutated = store
        .begin(SourceFormat::JsonLines, audit("mutated"), now)
        .expect("staging");
    mutated
        .stage_source(Cursor::new(&raw[..14]))
        .expect("source");
    let record = JsonLines::new(BufReader::new(Cursor::new(&raw[..14])))
        .next()
        .expect("record")
        .expect("valid");
    mutated.add_source_record(&record).expect("index");
    fs::write(mutated.source_path(), b"{\"value\":9}\n").expect("mutate staged source");
    let error = mutated
        .commit(CacheProcess::completed(0), now)
        .expect_err("hash mutation");
    assert!(matches!(error, CacheError::Verification(_)));

    let one = b"{\"value\":1}\n";
    let mut collision = store
        .begin(SourceFormat::JsonLines, audit("collision"), now)
        .expect("staging");
    let preferred = collision.cache_id().to_owned();
    let occupied = store.entry_path(&preferred).expect("occupied path");
    fs::create_dir(&occupied).expect("occupy generated id");
    fs::write(occupied.join("do-not-overwrite"), b"owner").expect("marker");
    collision.stage_source(Cursor::new(one)).expect("source");
    let record = JsonLines::new(BufReader::new(Cursor::new(one)))
        .next()
        .expect("record")
        .expect("valid");
    collision.add_source_record(&record).expect("index");
    let committed = collision
        .commit(CacheProcess::completed(0), now)
        .expect("allocate replacement id");
    assert_ne!(committed.cache_id, preferred);
    assert_eq!(
        fs::read(occupied.join("do-not-overwrite")).expect("preserved marker"),
        b"owner"
    );
}

#[test]
fn cache_root_validation_rejects_workspace_and_untrusted_ids_without_writes() {
    let fixture = Fixture::new();
    let inside = fixture.workspace.join(".sgy-cache");
    let error = CacheStore::open(&inside, Some(&fixture.workspace), CacheLimits::default())
        .expect_err("workspace cache root must fail");
    assert!(matches!(error, CacheError::WorkspaceRoot { .. }));
    assert!(
        !inside.exists(),
        "boundary check must happen before creation"
    );

    for invalid in [
        "../01J00000000000000000000000",
        "01j00000000000000000000000",
        "01I00000000000000000000000",
        "01J0000000000000000000000",
        "01J00000000000000000000000/",
    ] {
        assert!(validate_cache_id(invalid).is_err(), "accepted {invalid}");
    }
    assert!(validate_cache_id("01J00000000000000000000000").is_ok());

    let default = default_cache_root().expect("platform cache root");
    assert!(default.is_absolute());
    assert!(default.ends_with(Path::new("sgy/cache/v1")));

    let store = fixture.store(CacheLimits::default());
    let mut disabled = audit("off");
    disabled.cache_mode = CacheMode::Off;
    let error = store
        .begin(SourceFormat::JsonLines, disabled, fixed_now())
        .expect_err("cache=off must not create staging");
    assert!(matches!(error, CacheError::Disabled));
    assert_eq!(
        fs::read_dir(store.root().join(".staging"))
            .expect("staging root")
            .count(),
        0
    );
}

#[test]
fn entry_limit_and_locked_quota_fail_without_visible_partial_commit() {
    let fixture = Fixture::new();
    let tiny = CacheLimits {
        max_entry_bytes: 8,
        quota_bytes: 1024,
        ..CacheLimits::default()
    };
    let store = fixture.store(tiny);
    let mut staging = store
        .begin(SourceFormat::JsonLines, audit("too-large"), fixed_now())
        .expect("staging");
    let id = staging.cache_id().to_owned();
    let error = staging
        .stage_source(Cursor::new(b"{\"value\":123456789}\n"))
        .expect_err("source limit");
    assert!(matches!(error, CacheError::EntryTooLarge { .. }));
    drop(staging);
    assert!(!store.entry_path(&id).expect("path").exists());

    let fixture = Fixture::new();
    let generous = fixture.store(CacheLimits::default());
    let raw = b"{\"value\":1}\n";
    let first = commit_jsonl(&generous, raw, fixed_now(), "first");
    let first_size = directory_size(&first.path);
    let lease = generous
        .acquire_entry(&first.cache_id)
        .expect("active entry lease");
    let constrained = fixture.store(CacheLimits {
        quota_bytes: first_size,
        ..CacheLimits::default()
    });
    let mut second = constrained
        .begin(SourceFormat::JsonLines, audit("second"), fixed_now())
        .expect("second staging");
    let second_id = second.cache_id().to_owned();
    second.stage_source(Cursor::new(raw)).expect("source");
    for record in JsonLines::new(BufReader::new(Cursor::new(raw))) {
        second
            .add_source_record(&record.expect("record"))
            .expect("index");
    }
    let error = second
        .commit(CacheProcess::completed(0), fixed_now())
        .expect_err("locked quota must fail");
    assert!(matches!(error, CacheError::Quota { .. }));
    assert!(first.path.exists());
    assert!(!constrained.entry_path(&second_id).expect("path").exists());
    drop(lease);
}

#[test]
fn gc_removes_expired_then_lru_but_never_an_active_entry() {
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let raw = b"{\"value\":1}\n";
    let now = fixed_now();
    let expired = commit_jsonl(&store, raw, now, "expired");
    let report = store
        .gc(now + Duration::from_secs(8 * 24 * 60 * 60))
        .expect("expired GC");
    assert_eq!(report.removed_expired, 1);
    assert!(!expired.path.exists());

    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let oldest = commit_jsonl(&store, raw, now, "oldest");
    let newest = commit_jsonl(&store, raw, now + Duration::from_secs(60), "newest");
    let one_entry = directory_size(&newest.path);
    let constrained = fixture.store(CacheLimits {
        quota_bytes: one_entry,
        ..CacheLimits::default()
    });
    let report = constrained
        .gc(now + Duration::from_secs(120))
        .expect("LRU GC");
    assert_eq!(report.removed_lru, 1);
    assert!(!oldest.path.exists());
    assert!(newest.path.exists());

    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let locked = commit_jsonl(&store, raw, now, "locked");
    let removable = commit_jsonl(&store, raw, now + Duration::from_secs(60), "removable");
    let lease = store.acquire_entry(&locked.cache_id).expect("lease");
    let constrained = fixture.store(CacheLimits {
        quota_bytes: directory_size(&locked.path),
        ..CacheLimits::default()
    });
    let report = constrained
        .gc(now + Duration::from_secs(120))
        .expect("locked-aware GC");
    assert_eq!(report.removed_lru, 1);
    assert!(locked.path.exists());
    assert!(!removable.path.exists());
    drop(lease);
}

#[test]
fn concurrent_commits_get_unique_entries_without_overwrite() {
    let fixture = Fixture::new();
    let store = Arc::new(fixture.store(CacheLimits::default()));
    let now = fixed_now();
    let threads = (0..8)
        .map(|index| {
            let store = Arc::clone(&store);
            thread::spawn(move || {
                let raw = format!("{{\"value\":{index}}}\n");
                commit_jsonl(&store, raw.as_bytes(), now, &format!("thread-{index}"))
            })
        })
        .collect::<Vec<_>>();
    let committed = threads
        .into_iter()
        .map(|thread| thread.join().expect("cache thread"))
        .collect::<Vec<_>>();
    let ids = committed
        .iter()
        .map(|entry| entry.cache_id.clone())
        .collect::<HashSet<_>>();
    assert_eq!(ids.len(), committed.len());
    for entry in committed {
        assert!(entry.path.is_dir());
        assert_eq!(
            parse_metadata(&entry.path.join("metadata.yaml"))["cache_id"],
            entry.cache_id
        );
    }
}

#[test]
fn concurrent_readers_commits_and_gc_preserve_active_entries() {
    const ACTIVE: usize = 8;
    let fixture = Fixture::new();
    let store = Arc::new(fixture.store(CacheLimits::default()));
    let now = fixed_now();
    let active = (0..ACTIVE)
        .map(|index| {
            let raw = format!("{{\"active\":{index}}}\n");
            commit_jsonl(&store, raw.as_bytes(), now, &format!("active-{index}"))
        })
        .collect::<Vec<_>>();
    let barrier = Arc::new(Barrier::new(ACTIVE + 1));
    let readers = active
        .iter()
        .map(|entry| {
            let store = Arc::clone(&store);
            let barrier = Arc::clone(&barrier);
            let cache_id = entry.cache_id.clone();
            thread::spawn(move || {
                let cache = store.open_verified(&cache_id, now).expect("active cache");
                barrier.wait();
                thread::sleep(Duration::from_millis(100));
                cache.result(0).expect("active result")
            })
        })
        .collect::<Vec<_>>();
    barrier.wait();

    let writer_store = Arc::clone(&store);
    let writer = thread::spawn(move || {
        commit_jsonl(
            &writer_store,
            b"{\"concurrent\":true}\n",
            now,
            "concurrent-writer",
        )
    });
    let report = store
        .gc(now + Duration::from_secs(8 * 24 * 60 * 60))
        .expect("concurrent GC");
    assert_eq!(report.removed_expired, 0);
    for (entry, reader) in active.iter().zip(readers) {
        assert!(entry.path.exists(), "GC removed an active cache entry");
        assert!(reader.join().expect("reader")["active"].is_u64());
    }
    assert!(writer.join().expect("writer").path.exists());
}

#[test]
fn large_cache_index_is_iterated_without_a_resident_record_vector() {
    const RECORDS: usize = 50_000;
    let fixture = Fixture::new();
    let store = fixture.store(CacheLimits::default());
    let mut raw = Vec::with_capacity(RECORDS * 48);
    for ordinal in 0..RECORDS {
        use std::io::Write as _;
        writeln!(
            &mut raw,
            "{{\"file\":\"src/f{}.ts\",\"n\":{ordinal}}}",
            ordinal % 64
        )
        .expect("generate JSONL");
    }

    let committed = commit_jsonl(&store, &raw, fixed_now(), "large-stream");
    let verified = store
        .open_verified(&committed.cache_id, fixed_now())
        .expect("verify large cache");
    assert_eq!(verified.record_count(), RECORDS as u64);
    let iterated = verified
        .iter_records()
        .expect("index iterator")
        .try_fold(0_usize, |count, record| record.map(|_| count + 1))
        .expect("valid records");
    assert_eq!(iterated, RECORDS);
    assert_eq!(
        verified.result((RECORDS - 1) as u64).expect("last result")["n"],
        RECORDS - 1
    );
}

#[test]
fn argv_hash_is_length_prefixed_and_boundary_sensitive() {
    let left = vec![OsString::from("ab"), OsString::from("c")];
    let right = vec![OsString::from("a"), OsString::from("bc")];
    assert_ne!(hash_argv(&left), hash_argv(&right));
    assert_eq!(hash_argv(&left).len(), 64);
    assert_eq!(hash_argv(&left), hash_argv(&left));
}
