"""Local backend configuration loading without exposing secret values."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import MutableMapping


BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = BACKEND_DIR / ".env"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    # Only treat a hash as an unquoted comment when whitespace precedes it.
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


def load_backend_env(
    env_path: Path = DEFAULT_ENV_PATH,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load simple KEY=value lines; existing process environment wins."""
    target = os.environ if environ is None else environ
    if not env_path.exists():
        return

    try:
        contents = env_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RuntimeError("Could not read backend/.env; check its file permissions") from error

    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not _ENV_NAME.fullmatch(name):
            continue
        if name not in target:
            target[name] = _parse_env_value(value)


load_backend_env()
