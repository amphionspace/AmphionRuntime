"""Shared frontend replacement rules used by Android and Python inference."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_PKG_DIR = Path(__file__).resolve().parent
_DINGQIAO_ROOT = _PKG_DIR.parent
_WORKSPACE_ROOT = _DINGQIAO_ROOT.parent


@dataclass(frozen=True)
class _ReplacementRule:
    stages: frozenset[str]
    pattern: re.Pattern[str]
    replacement: str


def apply_frontend_rules(stage: str, text: str) -> str:
    """Apply Android-compatible ``frontend_rules.json`` replacements."""

    rules_path = _resolve_rules_path()
    if rules_path is None:
        return text
    output = text
    for rule in _load_rules(str(rules_path)):
        if stage in rule.stages:
            output = rule.pattern.sub(lambda match, r=rule: _render_replacement(r.replacement, match), output)
    return output


def _resolve_rules_path() -> Path | None:
    explicit = os.environ.get("LITS_FRONTEND_RULES_PATH")
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None

    model_dir = os.environ.get("LITS_MODEL_DIR")
    if model_dir:
        path = Path(model_dir) / "frontend_rules.json"
        if path.is_file():
            return path

    candidates = [
        _WORKSPACE_ROOT
        / "lits_dingqiao_sdk_vocos24k"
        / "tools"
        / "trial-export"
        / "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
        / "0.1.0"
        / "frontend_rules.json",
        _WORKSPACE_ROOT
        / "lits_dingqiao_sdk_vocos24k"
        / "tools"
        / "trial-export"
        / "dingqiao_lits_en_zh_vocos24k_streaming_proto"
        / "0.1.0"
        / "frontend_rules.json",
        _WORKSPACE_ROOT
        / "lits_dingqiao_sdk_vocos24k_v2_5"
        / "android"
        / "AmphionRuntime"
        / "sdk"
        / "src"
        / "main"
        / "assets"
        / "lits-models"
        / "tts"
        / "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
        / "0.1.0"
        / "frontend_rules.json",
        _WORKSPACE_ROOT
        / "lits_dingqiao_sdk_vocos24k_v2_5"
        / "tools"
        / "trial-export"
        / "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
        / "0.1.0"
        / "frontend_rules.json",
    ]
    return next((path for path in candidates if path.is_file()), None)


@lru_cache(maxsize=8)
def _load_rules(path_text: str) -> tuple[_ReplacementRule, ...]:
    path = Path(path_text)
    root = json.loads(path.read_text(encoding="utf-8"))
    rules: list[_ReplacementRule] = []
    for item in root.get("replacements", []):
        pattern = item.get("pattern", "")
        replacement = item.get("replacement", "")
        stages = frozenset(stage for stage in item.get("stages", []) if stage)
        if not pattern or not replacement or not stages:
            continue
        rules.append(
            _ReplacementRule(
                stages=stages,
                pattern=re.compile(pattern, re.IGNORECASE),
                replacement=replacement,
            )
        )
    return tuple(rules)


def _render_replacement(template: str, match: re.Match[str]) -> str:
    output: list[str] = []
    index = 0
    while index < len(template):
        char = template[index]
        if char == "$" and index + 1 < len(template) and template[index + 1].isdigit():
            group_index = int(template[index + 1])
            output.append(match.group(group_index) or "")
            index += 2
        else:
            output.append(char)
            index += 1
    return "".join(output)
