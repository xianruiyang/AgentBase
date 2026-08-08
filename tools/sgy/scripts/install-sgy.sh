#!/usr/bin/env bash
set -euo pipefail

action=${1:-install}
if [[ "$action" == install || "$action" == uninstall || "$action" == status ]]; then
    shift || true
else
    echo "usage: install-sgy.sh {install|uninstall|status} [options]" >&2
    exit 2
fi

archive=""
checksum=""
install_root="${XDG_DATA_HOME:-${HOME:?HOME is required}/.local/share}/sgy"
path_dir="${HOME:?HOME is required}/.local/bin"
remove_cache=0
while (($#)); do
    case "$1" in
        --archive) archive=${2:?missing --archive value}; shift 2 ;;
        --checksum) checksum=${2:?missing --checksum value}; shift 2 ;;
        --install-root) install_root=${2:?missing --install-root value}; shift 2 ;;
        --path-dir) path_dir=${2:?missing --path-dir value}; shift 2 ;;
        --no-path) path_dir=""; shift ;;
        --remove-cache) remove_cache=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() {
    echo "install-sgy: $*" >&2
    exit 2
}

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -- "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 -- "$1" | awk '{print $1}'
    else
        fail "sha256sum or shasum is required"
    fi
}

json_string() {
    key=$1
    file=$2
    sed -n "s/^[[:space:]]*\"$key\": \"\([^\"]*\)\",\{0,1\}[[:space:]]*$/\1/p" "$file" | head -n 1
}

state_value() {
    key=$1
    sed -n "s/^$key=//p" "$state_file" | head -n 1
}

host_target() {
    os=$(uname -s)
    arch=$(uname -m)
    case "$os:$arch" in
        Linux:x86_64) echo x86_64-unknown-linux-gnu ;;
        Darwin:x86_64) echo x86_64-apple-darwin ;;
        Darwin:arm64|Darwin:aarch64) echo aarch64-apple-darwin ;;
        *) fail "unsupported host: $os $arch" ;;
    esac
}

remove_cache_dir() {
    if [[ $(uname -s) == Darwin ]]; then
        cache_base="${HOME:?HOME is required}/Library/Caches"
    else
        cache_base=${XDG_CACHE_HOME:-${HOME:?HOME is required}/.cache}
    fi
    mkdir -p -- "$cache_base"
    cache_base=$(CDPATH= cd -- "$cache_base" && pwd -P)
    cache_dir="$cache_base/sgy/v1"
    case "$cache_dir" in
        "$cache_base"/*) ;;
        *) fail "refusing cache removal outside cache home" ;;
    esac
    rm -rf -- "$cache_dir"
}

if [[ "$action" != install && ! -d "$install_root" ]]; then
    if [[ "$action" == uninstall && $remove_cache == 1 ]]; then remove_cache_dir; fi
    if [[ "$action" == status ]]; then
        printf '{"schema":"sgy.install/v1","installed":false,"installRoot":"%s"}\n' "$install_root"
        exit 1
    fi
    printf '{"schema":"sgy.install/v1","removed":false,"reason":"not-installed"}\n'
    exit 0
fi
mkdir -p -- "$install_root"
install_root=$(CDPATH= cd -- "$install_root" && pwd -P)
case "$install_root" in
    /|/bin|/usr|/usr/bin|/opt|/var|/home) fail "unsafe install root: $install_root" ;;
esac
case "$install_root$path_dir" in
    *$'\n'*|*=*) fail "install and PATH directories must fit the state format" ;;
esac
current_dir="$install_root/current"
state_file="$install_root/.sgy-install-state"

if [[ "$action" == status ]]; then
    if [[ ! -f "$state_file" ]]; then
        printf '{"schema":"sgy.install/v1","installed":false,"installRoot":"%s"}\n' "$install_root"
        exit 1
    fi
    [[ $(state_value schema) == sgy.install/v1 ]] || fail "invalid install state schema"
    printf '{"schema":"sgy.install/v1","installed":true,"version":"%s","target":"%s","installRoot":"%s"}\n' \
        "$(state_value version)" "$(state_value target)" "$install_root"
    exit 0
fi

if [[ "$action" == uninstall ]]; then
    if [[ ! -f "$state_file" ]]; then
        ((remove_cache)) && remove_cache_dir
        printf '{"schema":"sgy.install/v1","removed":false,"reason":"not-installed"}\n'
        exit 0
    fi
    [[ $(state_value schema) == sgy.install/v1 ]] || fail "invalid install state schema"
    [[ $(state_value install_root) == "$install_root" ]] || fail "install state root mismatch"
    [[ $(state_value current_dir) == "$current_dir" ]] || fail "install state current directory mismatch"
    link_path=$(state_value link_path)
    link_created=$(state_value link_created)
    expected_link=""
    if [[ -n "$path_dir" ]]; then
        [[ -d "$path_dir" ]] || fail "PATH directory from command does not exist"
        path_dir=$(CDPATH= cd -- "$path_dir" && pwd -P)
        expected_link="$path_dir/sgy"
    fi
    [[ "$link_path" == "$expected_link" ]] || fail "PATH link does not match install state"
    if [[ "$link_created" == 1 && -n "$link_path" && -L "$link_path" ]]; then
        link_target=$(readlink "$link_path")
        if [[ "$link_target" == "$current_dir/sgy" ]]; then
            rm -- "$link_path"
        fi
    fi
    for leaf in LICENSE LICENSE-APACHE LICENSE-MIT NOTICE README.md THIRD_PARTY_LICENSES.txt manifest.json sbom.spdx.json sgy; do
        [[ "$leaf" =~ ^[A-Za-z0-9._-]+$ ]] || fail "unsafe managed member"
        [[ -f "$current_dir/$leaf" || -L "$current_dir/$leaf" ]] && rm -- "$current_dir/$leaf"
    done
    if [[ -d "$current_dir" ]] && ! compgen -G "$current_dir/*" >/dev/null && ! compgen -G "$current_dir/.[!.]*" >/dev/null && ! compgen -G "$current_dir/..?*" >/dev/null; then
        rmdir -- "$current_dir"
    fi
    rm -- "$state_file"
    ((remove_cache)) && remove_cache_dir
    if ! compgen -G "$install_root/*" >/dev/null && ! compgen -G "$install_root/.[!.]*" >/dev/null && ! compgen -G "$install_root/..?*" >/dev/null; then
        rmdir -- "$install_root"
    fi
    printf '{"schema":"sgy.install/v1","removed":true,"cacheRemoved":%s}\n' "$([[ $remove_cache == 1 ]] && echo true || echo false)"
    exit 0
fi

[[ -n "$archive" ]] || fail "--archive is required for install"
archive=$(CDPATH= cd -- "$(dirname -- "$archive")" && pwd -P)/$(basename -- "$archive")
checksum=${checksum:-$archive.sha256}
checksum=$(CDPATH= cd -- "$(dirname -- "$checksum")" && pwd -P)/$(basename -- "$checksum")
[[ -f "$archive" && -f "$checksum" ]] || fail "archive or checksum sidecar is missing"
command -v unzip >/dev/null 2>&1 || fail "unzip is required"
archive_name=$(basename -- "$archive")
[[ "$archive_name" == *.zip ]] || fail "release archive must be ZIP"
stem=${archive_name%.zip}
read -r expected_hash expected_name extra < "$checksum" || fail "invalid checksum sidecar"
[[ -z "${extra:-}" && "$expected_name" == "$archive_name" && "$expected_hash" =~ ^[0-9a-fA-F]{64}$ ]] || fail "invalid checksum sidecar"
actual_hash=$(sha256_file "$archive" | tr 'A-F' 'a-f')
expected_hash=$(printf '%s' "$expected_hash" | tr 'A-F' 'a-f')
[[ "$actual_hash" == "$expected_hash" ]] || fail "archive SHA-256 mismatch"

work="$install_root/.staging-$$-$RANDOM"
backup="$install_root/.backup-$$-$RANDOM"
mkdir -p -- "$work"
old_moved=0
new_committed=0
link_created_now=0
committed=0
cleanup() {
    status=$?
    trap - EXIT
    rm -rf -- "$work"
    if ((status != 0 && committed == 0)); then
        if ((link_created_now)) && [[ -L "$link_path" ]] && [[ $(readlink "$link_path") == "$current_dir/sgy" ]]; then
            rm -- "$link_path"
        fi
        if ((new_committed)) && [[ -d "$current_dir" ]]; then rm -rf -- "$current_dir"; fi
        if ((old_moved)) && [[ -d "$backup" ]]; then mv -- "$backup" "$current_dir"; fi
    fi
    exit "$status"
}
trap cleanup EXIT
members="$work/members.txt"
unzip -Z1 "$archive" > "$members"
[[ $(wc -l < "$members" | tr -d ' ') == 9 ]] || fail "package must contain exactly nine members"
[[ $(sort "$members" | uniq | wc -l | tr -d ' ') == 9 ]] || fail "package contains duplicate members"
expected_leaves='LICENSE
LICENSE-APACHE
LICENSE-MIT
NOTICE
README.md
THIRD_PARTY_LICENSES.txt
manifest.json
sbom.spdx.json
sgy'
actual_leaves=""
while IFS= read -r member; do
    case "$member" in
        "$stem"/*) leaf=${member#*/} ;;
        *) fail "unexpected ZIP root: $member" ;;
    esac
    [[ "$leaf" != */* && "$leaf" != . && "$leaf" != .. && -n "$leaf" ]] || fail "unsafe ZIP member: $member"
    actual_leaves="${actual_leaves}${leaf}"$'\n'
done < "$members"
if ! diff -u <(printf '%s\n' "$expected_leaves" | sort) <(printf '%s' "$actual_leaves" | sort) >/dev/null; then
    fail "package member set is not exact"
fi

manifest="$work/manifest.json"
unzip -p "$archive" "$stem/manifest.json" > "$manifest"
[[ $(json_string schema "$manifest") == sgy.release/v1 ]] || fail "manifest schema mismatch"
[[ $(json_string archive "$manifest") == "$archive_name" ]] || fail "manifest archive mismatch"
target=$(json_string target "$manifest")
[[ "$target" == $(host_target) ]] || fail "package target does not match host"
version=$(json_string version "$manifest")
binary=$(json_string binary "$manifest")
[[ "$binary" == sgy && -n "$version" ]] || fail "manifest binary/version mismatch"

unzip -qq "$archive" -d "$work/extracted"
package_root="$work/extracted/$stem"
for leaf in sgy README.md LICENSE LICENSE-MIT LICENSE-APACHE NOTICE THIRD_PARTY_LICENSES.txt sbom.spdx.json; do
    recorded_hash=$(awk -v wanted="$leaf" '
        $0 ~ "\"path\": \"" wanted "\"" { getline; getline; line=$0; gsub(/.*\"sha256\": \"|\".*/, "", line); print line; exit }
    ' "$manifest")
    [[ -n "$recorded_hash" && $(sha256_file "$package_root/$leaf") == "$recorded_hash" ]] || fail "manifest hash mismatch: $leaf"
done
[[ $($package_root/sgy --version) == "sgy $version" ]] || fail "binary version does not match manifest"

if [[ -f "$state_file" ]]; then
    [[ $(state_value schema) == sgy.install/v1 ]] || fail "invalid existing install state"
    if [[ $(state_value version) == "$version" && -x "$current_dir/sgy" && $($current_dir/sgy --version) == "sgy $version" ]]; then
        printf '{"schema":"sgy.install/v1","changed":false,"version":"%s","installRoot":"%s"}\n' "$version" "$install_root"
        exit 0
    fi
fi

link_created=0
link_path=""
if [[ -n "$path_dir" ]]; then
    mkdir -p -- "$path_dir"
    path_dir=$(CDPATH= cd -- "$path_dir" && pwd -P)
    [[ "$path_dir" != / ]] || fail "refusing to place PATH link at filesystem root"
    link_path="$path_dir/sgy"
    if [[ -e "$link_path" || -L "$link_path" ]]; then
        [[ -L "$link_path" && $(readlink "$link_path") == "$current_dir/sgy" ]] || fail "PATH link already belongs to another file"
        [[ -f "$state_file" ]] && link_created=$(state_value link_created)
    else
        link_created=1
    fi
fi

if [[ -e "$current_dir" ]]; then mv -- "$current_dir" "$backup"; old_moved=1; fi
mv -- "$package_root" "$current_dir"
new_committed=1
if [[ -n "$link_path" && ! -L "$link_path" ]]; then ln -s "$current_dir/sgy" "$link_path"; link_created_now=1; fi
state_tmp="$state_file.tmp"
cat > "$state_tmp" <<EOF
schema=sgy.install/v1
version=$version
target=$target
install_root=$install_root
current_dir=$current_dir
binary=sgy
archive_sha256=$actual_hash
link_path=$link_path
link_created=$link_created
EOF
mv -- "$state_tmp" "$state_file"
rm -rf -- "$backup"
committed=1
printf '{"schema":"sgy.install/v1","changed":true,"version":"%s","target":"%s","installRoot":"%s"}\n' "$version" "$target" "$install_root"
