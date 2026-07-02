# Webcheck Agent

Отдельный агент проверки ресурсов. Запускается на удалённом сервере, сам подключается к центральному серверу по WebSocket, получает задания и возвращает результат проверки из своей сети/страны.

## Быстрый старт

1. Создайте `.env` рядом с этим файлом:
   ```bash
   cp .env.example .env
   ```
2. Заполните `SERVER_WS_URL`, `AGENT_TOKEN`, `AGENT_ID`, `AGENT_COUNTRY`.
   Порт указывается прямо в URL:
   ```env
   SERVER_WS_URL=wss://your-domain.example:443/ws/agents
   ```
   Для локальной проверки без TLS можно использовать:
   ```env
   SERVER_WS_URL=ws://host.docker.internal:8090/ws/agents
   ```
   Если агент запускается не в контейнере, подойдёт `ws://127.0.0.1:8090/ws/agents`.
3. Запустите:
   ```bash
   docker compose up -d --build
   ```
4. Логи:
   ```bash
   docker compose logs -f webcheck-agent
   ```

## Протокол

Агент подключается к серверу и отправляет:

```json
{
  "type": "agent.hello",
  "agent_id": "server-a",
  "country": "RU",
  "region": "Moscow",
  "provider": "",
  "token": "secret"
}
```

Сервер отправляет задание:

```json
{
  "type": "check.request",
  "job_id": "uuid",
  "url": "https://example.com",
  "checks": ["http", "ssl", "domain"],
  "timeout_sec": 30
}
```

Агент отвечает:

```json
{
  "type": "check.result",
  "job_id": "uuid",
  "agent_id": "server-a",
  "country": "RU",
  "region": "Moscow",
  "ok": true,
  "http": {
    "ok": true,
    "status_code": 200,
    "latency_ms": 120,
    "ip": "203.0.113.10"
  },
  "ssl_days": 47,
  "domain_days": 348,
  "registrar": "Example Registrar",
  "contact_url": null,
  "error": null
}
```
