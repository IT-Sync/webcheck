import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    """Raised when Telegram Mini App authorization data is invalid."""


@dataclass(frozen=True)
class TelegramUser:
    id: int
    username: str | None
    first_name: str
    last_name: str
    language_code: str | None


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
    now: int | None = None,
) -> TelegramUser:
    if not init_data or not bot_token:
        raise TelegramAuthError("Missing Telegram authorization data")

    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("Missing Telegram authorization hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthError("Invalid Telegram authorization signature")

    try:
        auth_date = int(values["auth_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramAuthError("Invalid Telegram authorization date") from exc

    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + 30:
        raise TelegramAuthError("Telegram authorization date is in the future")
    if max_age_seconds > 0 and current_time - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram authorization data has expired")

    try:
        payload = json.loads(values["user"])
        user_id = int(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramAuthError("Invalid Telegram user data") from exc

    return TelegramUser(
        id=user_id,
        username=payload.get("username"),
        first_name=str(payload.get("first_name") or ""),
        last_name=str(payload.get("last_name") or ""),
        language_code=payload.get("language_code"),
    )
