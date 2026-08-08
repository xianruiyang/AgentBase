#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(uname -m)" in
    x86_64|amd64) ;;
    *)
        echo "The bundled sgy runtime requires Linux x86_64." >&2
        exit 126
        ;;
esac

binary="$script_dir/bin/linux-x86_64/sgy"
if [ ! -f "$binary" ]; then
    echo "Bundled sgy runtime not found: $binary" >&2
    exit 127
fi
if [ ! -x "$binary" ]; then
    chmod u+x "$binary" 2>/dev/null || {
        echo "Bundled sgy runtime is not executable: $binary" >&2
        exit 126
    }
fi

exec "$binary" "$@"
