"""Small, local research-profile format used by the Codex onboarding flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from text_utils import normalize_text, unique_normalized


PROFILE_SCHEMA_VERSION = 1
MATERIAL_TYPES = {"historical", "literary", "scholarship", "other"}


def _strings(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label}: ожидается список строк")
    result = unique_normalized(value)
    if not allow_empty and not result:
        raise ValueError(f"{label}: список не должен быть пустым")
    return result


def load_research_profile(path: Path) -> dict[str, Any]:
    """Load and validate a deliberately compact, human-auditable JSON profile."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Профиль исследования не найден: {path}. Для первоначальной "
            "настройки откройте проект в Codex и попросите выполнить инструкции "
            "из examples/codex/research-onboarding.ru.md (или английской версии)."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ошибка JSON в профиле {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: ожидается JSON-объект")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: поддерживается schema_version={PROFILE_SCHEMA_VERSION}"
        )

    name = normalize_text(str(payload.get("name", "")))
    research_area = normalize_text(str(payload.get("research_area", "")))
    result_language = normalize_text(str(payload.get("result_language", "")))
    if not name or not research_area or not result_language:
        raise ValueError(
            f"{path}: обязательны непустые name, research_area и result_language"
        )

    max_results = payload.get("max_results", 5)
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError(f"{path}: max_results должен быть целым числом")
    if not 1 <= max_results <= 20:
        raise ValueError(f"{path}: max_results должен быть от 1 до 20")

    raw_interests = payload.get("interests")
    if not isinstance(raw_interests, list) or not raw_interests:
        raise ValueError(f"{path}: interests должен быть непустым массивом")
    interests: list[dict[str, Any]] = []
    seen_interest_ids: set[str] = set()
    for index, value in enumerate(raw_interests, start=1):
        if not isinstance(value, dict):
            raise ValueError(f"{path}: interests[{index}] должен быть объектом")
        interest_id = normalize_text(str(value.get("id", "")))
        label = normalize_text(str(value.get("label", "")))
        terms = _strings(
            value.get("terms"), f"{path}: interests[{index}].terms", allow_empty=False
        )
        weight = value.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError(f"{path}: interests[{index}].weight должен быть числом")
        if not 0.1 <= float(weight) <= 5.0:
            raise ValueError(
                f"{path}: interests[{index}].weight должен быть от 0.1 до 5.0"
            )
        if not interest_id or not label:
            raise ValueError(f"{path}: interests[{index}] требует id и label")
        if interest_id in seen_interest_ids:
            raise ValueError(f"{path}: повторяющийся interest id {interest_id!r}")
        seen_interest_ids.add(interest_id)
        interests.append(
            {
                "id": interest_id,
                "label": label,
                "terms": terms,
                "weight": float(weight),
            }
        )

    raw_people = payload.get("focus_people", [])
    if not isinstance(raw_people, list):
        raise ValueError(f"{path}: focus_people должен быть массивом")
    focus_people: list[dict[str, Any]] = []
    for index, value in enumerate(raw_people, start=1):
        if not isinstance(value, dict):
            raise ValueError(f"{path}: focus_people[{index}] должен быть объектом")
        person_name = normalize_text(str(value.get("name", "")))
        if not person_name:
            raise ValueError(f"{path}: focus_people[{index}].name обязателен")
        aliases = _strings(
            value.get("aliases", []), f"{path}: focus_people[{index}].aliases"
        )
        focus_people.append(
            {"name": person_name, "aliases": unique_normalized([person_name, *aliases])}
        )

    material_types = _strings(
        payload.get("material_types", sorted(MATERIAL_TYPES)),
        f"{path}: material_types",
        allow_empty=False,
    )
    unknown_types = sorted(set(material_types) - MATERIAL_TYPES)
    if unknown_types:
        raise ValueError(
            f"{path}: неизвестные material_types: {', '.join(unknown_types)}"
        )

    preferences = payload.get("finding_preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError(f"{path}: finding_preferences должен быть объектом")
    preferred_kinds = _strings(
        preferences.get("preferred_kinds", []),
        f"{path}: finding_preferences.preferred_kinds",
    )
    include_unlisted = preferences.get("include_unlisted_people", True)
    avoid_repetition = preferences.get("avoid_person_repetition", True)
    if not isinstance(include_unlisted, bool) or not isinstance(avoid_repetition, bool):
        raise ValueError(
            f"{path}: include_unlisted_people/avoid_person_repetition должны быть bool"
        )
    notes = normalize_text(str(preferences.get("notes", "")))

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "name": name,
        "research_area": research_area,
        "result_language": result_language,
        "max_results": max_results,
        "interests": interests,
        "focus_people": focus_people,
        "material_types": material_types,
        "include_sources": _strings(
            payload.get("include_sources", []), f"{path}: include_sources"
        ),
        "exclude_sources": _strings(
            payload.get("exclude_sources", []), f"{path}: exclude_sources"
        ),
        "finding_preferences": {
            "preferred_kinds": preferred_kinds,
            "include_unlisted_people": include_unlisted,
            "avoid_person_repetition": avoid_repetition,
            "notes": notes,
        },
    }
