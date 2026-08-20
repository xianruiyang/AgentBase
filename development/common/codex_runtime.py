"""Shared, redacted Codex runtime-environment projection for local evaluators."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


RUNTIME_ENVIRONMENT_SCHEMA = "agentbase.codex-runtime-environment/v1"
SHELL_ENVIRONMENT_POLICY_SCHEMA = "agentbase.codex-shell-environment-policy/v1"
SHELL_ENVIRONMENT_POLICY_PATH = Path(__file__).with_name(
    "codex_shell_environment_policy.json"
)
NETWORK_ENVIRONMENT_KEYS = (
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "CODEX_CA_CERTIFICATE",
    "SSL_CERT_FILE",
)
AMBIENT_CREDENTIAL_KEYS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_CLIENT_SECRET",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "NODE_AUTH_TOKEN",
    "NPM_TOKEN",
    "PYPI_TOKEN",
}
AMBIENT_CONTROL_KEYS = {
    "CI",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GNUPGHOME",
    "NODE_OPTIONS",
    "NODE_PATH",
    "OLDPWD",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PWD",
    "VIRTUAL_ENV",
}
AMBIENT_SENSITIVE_PREFIXES = (
    "AWS_",
    "AZURE_",
    "CODEX_",
    "CONDA_",
    "GH_",
    "GITHUB_",
    "GIT_",
    "GOOGLE_",
    "GPG_",
    "NPM_",
    "OPENAI_",
    "PIP_",
    "PYPI_",
    "SSH_",
)
ENVIRONMENT_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class CodexRuntimeError(ValueError):
    """The declared runtime projection is invalid or no longer reproducible."""


def resolve_shell_environment_policy(
    path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate the one shared Codex model-shell environment policy."""

    source = (SHELL_ENVIRONMENT_POLICY_PATH if path is None else path).resolve()
    try:
        raw = source.read_bytes()
        policy = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexRuntimeError(f"cannot read Codex shell environment policy: {exc}") from exc
    if not isinstance(policy, dict) or set(policy) != {
        "schema",
        "inherit",
        "ignore_default_excludes",
        "experimental_use_profile",
        "filters",
    }:
        raise CodexRuntimeError("Codex shell environment policy has an invalid shape")
    if policy.get("schema") != SHELL_ENVIRONMENT_POLICY_SCHEMA:
        raise CodexRuntimeError("Codex shell environment policy schema mismatch")
    if policy.get("inherit") not in {"all", "core", "none"}:
        raise CodexRuntimeError("Codex shell environment inherit mode is invalid")
    for name in ("ignore_default_excludes", "experimental_use_profile"):
        if not isinstance(policy.get(name), bool):
            raise CodexRuntimeError(f"Codex shell environment {name} must be boolean")
    filters = policy.get("filters")
    if not isinstance(filters, dict) or not filters or any(
        not isinstance(pattern, str)
        or not pattern
        or len(pattern) > 128
        or action != "exclude"
        for pattern, action in filters.items()
    ):
        raise CodexRuntimeError("Codex shell environment filters are invalid")
    descriptor = {
        "schema": SHELL_ENVIRONMENT_POLICY_SCHEMA,
        "logical_path": "development/common/codex_shell_environment_policy.json",
        "sha256": _sha256_bytes(raw),
    }
    return descriptor, policy


def codex_shell_environment_overrides(
    *,
    expected_sha256: str | None = None,
) -> list[str]:
    """Serialize the shared policy as deterministic Codex `-c` overrides."""

    descriptor, policy = resolve_shell_environment_policy()
    if expected_sha256 is not None and descriptor["sha256"] != expected_sha256:
        raise CodexRuntimeError("Codex shell environment policy changed after identity capture")
    overrides = [
        f"shell_environment_policy.inherit={json.dumps(policy['inherit'])}",
        "shell_environment_policy.ignore_default_excludes="
        + str(policy["ignore_default_excludes"]).lower(),
        "shell_environment_policy.experimental_use_profile="
        + str(policy["experimental_use_profile"]).lower(),
    ]
    overrides.extend(
        "shell_environment_policy.filters."
        + json.dumps(pattern)
        + "="
        + json.dumps(action)
        for pattern, action in sorted(policy["filters"].items())
    )
    return overrides


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_dotenv_projection(path: Path) -> dict[str, str]:
    """Read only the fixed network allowlist from a UTF-8 dotenv file."""

    if not path.is_file():
        raise CodexRuntimeError(f"Codex runtime dotenv does not exist: {path}")
    allowed = set(NETWORK_ENVIRONMENT_KEYS)
    projection: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise CodexRuntimeError(
                f"invalid dotenv assignment at line {line_number}"
            )
        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if not ENVIRONMENT_KEY_PATTERN.fullmatch(key):
            raise CodexRuntimeError(f"invalid dotenv key at line {line_number}")
        canonical_key = key.upper()
        if canonical_key not in allowed:
            continue
        if canonical_key in projection:
            raise CodexRuntimeError(
                f"duplicate projected dotenv key: {canonical_key}"
            )
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or not value.endswith(quote):
                raise CodexRuntimeError(
                    f"unterminated projected dotenv value at line {line_number}"
                )
            value = value[1:-1]
        else:
            comment = value.find(" #")
            if comment >= 0:
                value = value[:comment].rstrip()
        projection[canonical_key] = value
    return projection


def apply_runtime_environment_options(
    projection: dict[str, str],
    options: Mapping[str, str],
) -> dict[str, str]:
    """Apply only explicitly declared proxy transformations."""

    proxy_dns = options.get("proxy_dns", "as-configured")
    if proxy_dns not in {"as-configured", "remote"}:
        raise CodexRuntimeError(
            "runtime_environment.proxy_dns must be as-configured or remote"
        )
    effective = dict(projection)
    if proxy_dns == "remote":
        for key in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"):
            value = effective.get(key)
            if not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme.lower() == "socks5":
                effective[key] = urlunsplit(
                    (
                        "socks5h",
                        parsed.netloc,
                        parsed.path,
                        parsed.query,
                        parsed.fragment,
                    )
                )
    all_proxy_fanout = options.get("all_proxy_fanout", "none")
    if all_proxy_fanout not in {"none", "http-and-https"}:
        raise CodexRuntimeError(
            "runtime_environment.all_proxy_fanout must be none or http-and-https"
        )
    if all_proxy_fanout == "http-and-https" and effective.get("ALL_PROXY"):
        effective.setdefault("HTTP_PROXY", effective["ALL_PROXY"])
        effective.setdefault("HTTPS_PROXY", effective["ALL_PROXY"])
    return effective


def resolve_runtime_environment(
    raw: Any,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve a redacted descriptor and its in-memory network projection."""

    if not isinstance(raw, dict):
        raise CodexRuntimeError("runtime_environment must be an object")
    source = Path(
        os.path.expandvars(str(raw.get("dotenv_path", "")))
    ).expanduser().resolve()
    required_raw = raw.get("required_keys")
    if not isinstance(required_raw, list) or not required_raw:
        raise CodexRuntimeError(
            "runtime_environment.required_keys must be a non-empty list"
        )
    required: list[str] = []
    allowed = set(NETWORK_ENVIRONMENT_KEYS)
    for item in required_raw:
        key = str(item).upper()
        if key not in allowed:
            raise CodexRuntimeError(f"runtime environment key is not allowed: {key}")
        if key not in required:
            required.append(key)
    source_projection = parse_dotenv_projection(source)
    options = {
        "proxy_dns": str(raw.get("proxy_dns", "as-configured")),
        "all_proxy_fanout": str(raw.get("all_proxy_fanout", "none")),
    }
    projection = apply_runtime_environment_options(source_projection, options)
    missing = [key for key in required if not projection.get(key)]
    if missing:
        raise CodexRuntimeError(
            f"required runtime environment keys are missing or empty: {missing}"
        )
    descriptor = {
        "schema": RUNTIME_ENVIRONMENT_SCHEMA,
        "source_kind": "codex-dotenv-allowlist",
        "source_path": str(source),
        "allowed_keys": list(NETWORK_ENVIRONMENT_KEYS),
        "required_keys": required,
        "projected_keys": sorted(projection),
        "projection_options": options,
        "projection_sha256": _sha256_bytes(_canonical_bytes(projection)),
        "values_redacted": True,
    }
    return descriptor, projection


def materialize_runtime_environment(descriptor: dict[str, Any]) -> dict[str, str]:
    """Re-read a descriptor and reject any change before launching Codex."""

    if descriptor.get("schema") != RUNTIME_ENVIRONMENT_SCHEMA:
        raise CodexRuntimeError("runtime environment schema mismatch")
    if descriptor.get("allowed_keys") != list(NETWORK_ENVIRONMENT_KEYS):
        raise CodexRuntimeError("runtime environment allowlist mismatch")
    source = Path(str(descriptor.get("source_path", ""))).resolve()
    source_projection = parse_dotenv_projection(source)
    options = descriptor.get("projection_options")
    if not isinstance(options, dict):
        raise CodexRuntimeError("runtime environment projection options mismatch")
    projection = apply_runtime_environment_options(source_projection, options)
    if sorted(projection) != descriptor.get("projected_keys"):
        raise CodexRuntimeError("runtime environment projected keys changed")
    required = descriptor.get("required_keys", [])
    if not isinstance(required, list) or any(
        not projection.get(str(key)) for key in required
    ):
        raise CodexRuntimeError("runtime environment required keys changed")
    if _sha256_bytes(_canonical_bytes(projection)) != descriptor.get(
        "projection_sha256"
    ):
        raise CodexRuntimeError("runtime environment projection changed")
    return projection


def sanitized_process_environment(
    projection: Mapping[str, str],
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Clear ambient network aliases before applying the frozen projection."""

    environment = dict(os.environ if base is None else base)
    allowed = set(NETWORK_ENVIRONMENT_KEYS)
    for key in list(environment):
        canonical_key = key.upper()
        if (
            canonical_key in allowed
            or canonical_key in AMBIENT_CREDENTIAL_KEYS
            or canonical_key in AMBIENT_CONTROL_KEYS
            or canonical_key.startswith(AMBIENT_SENSITIVE_PREFIXES)
        ):
            del environment[key]
    for key, value in projection.items():
        canonical_key = key.upper()
        if canonical_key not in allowed:
            raise CodexRuntimeError(
                f"process environment key is not allowed: {canonical_key}"
            )
        environment[canonical_key] = value
    return environment
