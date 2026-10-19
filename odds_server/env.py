"""Minimal .env loader (no external packages needed)."""
import os


def load_env(path):
    """Read KEY=VALUE lines from `path` into os.environ (existing values win)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


def setting(name, default=""):
    return os.environ.get(name, default).strip()
