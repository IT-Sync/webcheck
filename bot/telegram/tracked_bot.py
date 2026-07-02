from aiogram import Bot

from bot.infra.db import log_bot_message


def _chat_id(args, kwargs):
    if "chat_id" in kwargs:
        return kwargs["chat_id"]
    return args[0] if args else None


def _log_message(chat_id, source, status, error=None):
    try:
        log_bot_message(chat_id, source, status, error)
    except Exception as e:
        print(f"Failed to log bot message metric: {e}")


class TrackedBot(Bot):
    async def send_message(self, *args, **kwargs):
        chat_id = _chat_id(args, kwargs)
        try:
            result = await super().send_message(*args, **kwargs)
        except Exception as e:
            if chat_id is not None:
                _log_message(chat_id, "send_message", "failed", type(e).__name__)
            raise
        if chat_id is not None:
            _log_message(chat_id, "send_message", "sent")
        return result

    async def send_document(self, *args, **kwargs):
        chat_id = _chat_id(args, kwargs)
        try:
            result = await super().send_document(*args, **kwargs)
        except Exception as e:
            if chat_id is not None:
                _log_message(chat_id, "send_document", "failed", type(e).__name__)
            raise
        if chat_id is not None:
            _log_message(chat_id, "send_document", "sent")
        return result
