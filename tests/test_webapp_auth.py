import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from bot.webapp.auth import TelegramAuthError, validate_init_data


BOT_TOKEN = "123456:test-token"
NOW = 1_750_000_000


def signed_init_data(*, auth_date=NOW, user=None, bot_token=BOT_TOKEN):
    payload = {
        "auth_date": str(auth_date),
        "query_id": "AAExampleQuery",
        "user": json.dumps(
            user
            or {
                "id": 42,
                "first_name": "Ada",
                "last_name": "Lovelace",
                "username": "ada",
                "language_code": "en",
            },
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    payload["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(payload)


class TelegramWebAppAuthTest(unittest.TestCase):
    def test_accepts_valid_signed_user(self):
        user = validate_init_data(signed_init_data(), BOT_TOKEN, now=NOW)

        self.assertEqual(user.id, 42)
        self.assertEqual(user.username, "ada")
        self.assertEqual(user.first_name, "Ada")

    def test_rejects_tampered_user(self):
        init_data = signed_init_data().replace("%22id%22%3A42", "%22id%22%3A43")

        with self.assertRaises(TelegramAuthError):
            validate_init_data(init_data, BOT_TOKEN, now=NOW)

    def test_rejects_expired_data(self):
        with self.assertRaisesRegex(TelegramAuthError, "expired"):
            validate_init_data(
                signed_init_data(auth_date=NOW - 101),
                BOT_TOKEN,
                max_age_seconds=100,
                now=NOW,
            )

    def test_rejects_future_data(self):
        with self.assertRaisesRegex(TelegramAuthError, "future"):
            validate_init_data(signed_init_data(auth_date=NOW + 31), BOT_TOKEN, now=NOW)


if __name__ == "__main__":
    unittest.main()
