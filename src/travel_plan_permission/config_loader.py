"""Shared YAML configuration loading helpers."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Self

import yaml


def load_rules[RuleT](
    raw_rules: Iterable[dict[str, object]],
    factory: Callable[[dict[str, object]], RuleT],
) -> list[RuleT]:
    """Convert raw rule dictionaries through a caller-supplied factory."""

    return [factory(rule) for rule in raw_rules]


class YamlConfigLoaderMixin:
    """Mixin for config classes that load themselves from YAML content."""

    @classmethod
    def from_yaml(cls, content: str) -> Self:
        """Build a config object from YAML content."""

        raise NotImplementedError

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> Self:
        """Load configuration from a YAML file or configured default."""

        target_path = cls._resolve_config_path(path)
        if target_path is None or not target_path.exists():
            content = cls._read_default_config_resource()
            if content is None:
                raise FileNotFoundError(cls._missing_config_message())
        else:
            content = target_path.read_text(encoding="utf-8")
        return cls.from_yaml(content)

    @classmethod
    def from_environment(cls, env_var: str) -> Self:
        """Load configuration from an environment variable containing YAML."""

        content = os.getenv(env_var)
        if not content:
            raise ValueError(f"Environment variable '{env_var}' is not set or empty")
        return cls.from_yaml(content)

    @staticmethod
    def _load_yaml_mapping(content: str) -> dict[str, Any]:
        return yaml.safe_load(content) or {}

    @classmethod
    def _resolve_config_path(cls, path: str | Path | None) -> Path | None:
        return Path(path) if path is not None else cls._default_config_path()

    @staticmethod
    def _default_config_path() -> Path | None:
        return None

    @staticmethod
    def _read_default_config_resource() -> str | None:
        return None

    @staticmethod
    def _missing_config_message() -> str:
        return "No configuration file found"
