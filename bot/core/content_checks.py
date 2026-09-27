"""Validation and evaluation for configurable HTTP response assertions."""

import json
import re


MAX_REQUIRED_TEXT_LENGTH = 2000
MAX_JSON_ASSERTIONS = 20
_PATH_TOKEN = re.compile(r"(?:^|\.)([A-Za-z_][A-Za-z0-9_-]*)|\[(\d+)\]")


def normalize_check_settings(payload):
    """Return a bounded, persistence-ready check settings dictionary."""
    if not isinstance(payload, dict):
        raise ValueError("Настройки проверки должны быть JSON-объектом")

    raw_statuses = payload.get("expected_status_codes", [])
    if raw_statuses is None:
        raw_statuses = []
    if not isinstance(raw_statuses, list) or len(raw_statuses) > 50:
        raise ValueError("Передайте список не более чем из 50 HTTP-кодов")
    statuses = []
    for value in raw_statuses:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("HTTP-код должен быть целым числом от 100 до 599")
        if isinstance(value, bool):
            raise ValueError("HTTP-код должен быть целым числом от 100 до 599")
        try:
            status = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("HTTP-код должен быть целым числом от 100 до 599") from exc
        if not 100 <= status <= 599:
            raise ValueError("HTTP-код должен быть целым числом от 100 до 599")
        if status not in statuses:
            statuses.append(status)

    required_text = payload.get("required_text")
    if required_text is not None:
        if not isinstance(required_text, str):
            raise ValueError("Обязательный текст должен быть строкой")
        required_text = required_text.strip()
        if len(required_text) > MAX_REQUIRED_TEXT_LENGTH:
            raise ValueError(f"Обязательный текст не должен превышать {MAX_REQUIRED_TEXT_LENGTH} символов")
        if not required_text:
            required_text = None

    assertions = payload.get("json_assertions", {})
    if assertions is None:
        assertions = {}
    if not isinstance(assertions, dict) or len(assertions) > MAX_JSON_ASSERTIONS:
        raise ValueError(f"JSON-проверки должны быть объектом не более чем с {MAX_JSON_ASSERTIONS} полями")
    normalized_assertions = {}
    for path, expected in assertions.items():
        if not isinstance(path, str) or not path or len(path) > 200:
            raise ValueError("Путь JSON должен быть непустой строкой до 200 символов")
        _parse_json_path(path)
        try:
            json.dumps(expected, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Ожидаемое значение для {path} не является JSON") from exc
        normalized_assertions[path] = expected

    return {
        "expected_status_codes": sorted(statuses),
        "required_text": required_text,
        "json_assertions": normalized_assertions,
    }


def has_content_assertions(settings):
    return bool(
        settings.get("expected_status_codes")
        or settings.get("required_text")
        or settings.get("json_assertions")
    )


def _parse_json_path(path):
    if path == "$":
        return []
    raw = path[2:] if path.startswith("$.") else path
    tokens = []
    position = 0
    while position < len(raw):
        match = _PATH_TOKEN.match(raw, position)
        if not match:
            raise ValueError(f"Некорректный путь JSON: {path}")
        tokens.append(match.group(1) if match.group(1) is not None else int(match.group(2)))
        position = match.end()
    return tokens


def _json_value(document, path):
    value = document
    for token in _parse_json_path(path):
        if isinstance(token, int):
            if not isinstance(value, list) or token >= len(value):
                raise KeyError(path)
            value = value[token]
        else:
            if not isinstance(value, dict) or token not in value:
                raise KeyError(path)
            value = value[token]
    return value


def evaluate_response(status_code, body, settings):
    """Return ``None`` when all assertions pass, otherwise a concise reason."""
    expected_statuses = settings.get("expected_status_codes") or []
    if expected_statuses and status_code not in expected_statuses:
        expected = ", ".join(str(value) for value in expected_statuses)
        return f"HTTP {status_code}, ожидался один из: {expected}"

    required_text = settings.get("required_text")
    if required_text and required_text not in body:
        return "В ответе отсутствует обязательный текст"

    assertions = settings.get("json_assertions") or {}
    if assertions:
        try:
            document = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return "Ответ не является корректным JSON"
        for path, expected in assertions.items():
            try:
                actual = _json_value(document, path)
            except KeyError:
                return f"В JSON отсутствует путь {path}"
            if actual != expected:
                return f"Значение JSON {path} не совпадает с ожидаемым"
    return None
