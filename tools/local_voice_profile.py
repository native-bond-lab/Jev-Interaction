"""Load the private test profile before importing the application. Never display its values."""
from __future__ import annotations

import logging
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / ".local/voice-test.env"


def read_profile(path=PROFILE):
    values = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8-sig").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        if not key.replace("_", "").isalnum() or not key.isupper():
            raise ValueError("Invalid private profile setting name")
        values[key] = value
    return values


def activate(path=PROFILE):
    values = read_profile(path)
    os.environ.update(values)
    os.environ["JEV_RUNS_DIR"] = str(ROOT / "runs/domestic-test")
    if values.get("VOICE_TEST_DIRECT", "1") == "1":
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
    RedactingFormatter.secrets = [v for k, v in values.items() if v and ("KEY" in k or "TOKEN" in k)]
    return values


class RedactingFormatter(logging.Formatter):
    secrets = []

    def format(self, record):
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return text


def log_config():
    return {"version": 1, "disable_existing_loggers": False,
            "formatters": {"safe": {"()": RedactingFormatter, "format": "%(levelname)s %(message)s"}},
            "handlers": {"safe": {"class": "logging.StreamHandler", "formatter": "safe", "stream": "ext://sys.stderr"}},
            "root": {"handlers": ["safe"], "level": "WARNING"},
            "loggers": {"uvicorn": {"handlers": ["safe"], "level": "INFO", "propagate": False},
                        "uvicorn.error": {"level": "INFO"},
                        "uvicorn.access": {"handlers": ["safe"], "level": "WARNING", "propagate": False}}}
