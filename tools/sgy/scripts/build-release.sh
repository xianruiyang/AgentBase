#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/.." && pwd)
target=""
version=""
source_revision="${SGY_SOURCE_REVISION:-}"
source_date_epoch="${SOURCE_DATE_EPOCH:-0}"
out_dir="$root/dist"
clean=0

while (($#)); do
    case "$1" in
        --target) target=${2:?missing --target value}; shift 2 ;;
        --version) version=${2:?missing --version value}; shift 2 ;;
        --source-revision) source_revision=${2:?missing --source-revision value}; shift 2 ;;
        --source-date-epoch) source_date_epoch=${2:?missing --source-date-epoch value}; shift 2 ;;
        --out-dir) out_dir=${2:?missing --out-dir value}; shift 2 ;;
        --clean) clean=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

host_target=$(rustc -vV | sed -n 's/^host: //p')
if [[ -z "$host_target" ]]; then
    echo "rustc -vV did not report a host target" >&2
    exit 2
fi
target=${target:-$host_target}
if [[ ! "$target" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    echo "target is not release-safe: $target" >&2
    exit 2
fi
if [[ -z "$version" ]]; then
    version=$(awk '
        /^\[workspace\.package\]$/ { in_workspace=1; next }
        /^\[/ { in_workspace=0 }
        in_workspace && /^version[[:space:]]*=/ {
            value=$0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/"[[:space:]]*$/, "", value); print value; exit
        }
    ' "$root/Cargo.toml")
fi
if [[ ! "$version" =~ ^[A-Za-z0-9.+_-]+$ ]]; then
    echo "version is not release-safe: $version" >&2
    exit 2
fi
if [[ -z "$source_revision" ]] && command -v git >/dev/null 2>&1; then
    source_revision=$(git -C "$root" rev-parse --verify HEAD 2>/dev/null || true)
fi
source_revision=${source_revision:-unversioned-workspace}
if [[ ! "$source_date_epoch" =~ ^[0-9]+$ ]]; then
    echo "source date epoch must be an unsigned integer" >&2
    exit 2
fi

target_root="$root/target/release-build"
build_root="$target_root/$target"
case "$build_root" in
    "$target_root"/*) ;;
    *) echo "refusing build directory outside target/release-build" >&2; exit 2 ;;
esac
if ((clean)) && [[ -d "$build_root" ]]; then
    rm -rf -- "$build_root"
fi
mkdir -p -- "$build_root" "$out_dir"

separator=$(printf '\037')
remap="--remap-path-prefix=$root=."
release_rustflags="$remap"
if [[ "$target" == *-msvc ]]; then
    release_rustflags="${release_rustflags}${separator}-C${separator}link-arg=/Brepro"
fi
if [[ -n "${CARGO_ENCODED_RUSTFLAGS:-}" ]]; then
    export CARGO_ENCODED_RUSTFLAGS="${CARGO_ENCODED_RUSTFLAGS}${separator}${release_rustflags}"
else
    export CARGO_ENCODED_RUSTFLAGS="$release_rustflags"
fi
export CARGO_TARGET_DIR="$build_root"
export SGY_BUILD_VERSION="$version"
export SOURCE_DATE_EPOCH="$source_date_epoch"

cd -- "$root"
cargo build --release --locked -p sgy-release
cargo build --release --locked --target "$target" -p sgy-cli --bin sgy

helper="$build_root/release/sgy-release"
binary="$build_root/$target/release/sgy"
if [[ "$target" == *windows* ]]; then
    binary="$binary.exe"
fi
if [[ ! -x "$helper" || ! -f "$binary" ]]; then
    echo "expected release executables were not produced" >&2
    exit 2
fi
if [[ "$target" == "$host_target" ]]; then
    actual_version=$($binary --version)
    if [[ "$actual_version" != "sgy $version" ]]; then
        echo "binary version mismatch: $actual_version" >&2
        exit 2
    fi
fi

metadata_path="$build_root/cargo-metadata-$target.json"
cargo metadata --locked --format-version 1 --filter-platform "$target" > "$metadata_path"
rustc_version=$(rustc --version)
"$helper" package \
    --metadata "$metadata_path" \
    --cargo-lock "$root/Cargo.lock" \
    --binary "$binary" \
    --readme "$root/README.md" \
    --license "$root/LICENSE" \
    --license-mit "$root/LICENSE-MIT" \
    --license-apache "$root/LICENSE-APACHE" \
    --notice "$root/NOTICE" \
    --out-dir "$out_dir" \
    --version "$version" \
    --target "$target" \
    --source-revision "$source_revision" \
    --source-date-epoch "$source_date_epoch" \
    --rustc "$rustc_version"
