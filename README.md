# Webcheck Bot

Телеграм‑бот для мониторинга сайтов: проверяет HTTP‑доступность, срок действия SSL‑сертификата, дату окончания домена, собирает GeoIP‑информацию и пишет журнал действий пользователей. Проект разворачивается в Docker и использует PostgreSQL.

## Возможности
- Добавление сайтов простым сообщением или через `/list` / inline‑кнопки.
- Автоматический мониторинг по расписанию (APSheduler) + уведомления в чат.
- Отчёты по статусу сайтов: `/statusme`, `/status`, inline‑кнопка «📊 Статус».
- Управление сайтами: `/delete`, inline «🗑 Удалить», админское удаление `/remove_user`.
- Поиск поддоменов `/subdomains` и выгрузка результатов в CSV.
- Экспорт логов `/export_logs` и списка сайтов `/export_sites`.

## Технологии
- Python 3.11, aiogram, asyncio, APScheduler.
- PostgreSQL 15 (psycopg2).
- Дополнительные сервисы: whois/ipwhois, aiohttp, BeautifulSoup.
- Docker / docker‑compose для деплоя.

## Переменные окружения (`.env`)
```
BOT_TOKEN=Токен_бота_от_BotFather
BOT_OWNER_ID=123456789              # Telegram ID администратора
DB_NAME=devcheck
DB_USER=devuser
DB_PASS=devpass
DB_HOST=db                          # имя сервиса в docker-compose
DB_PORT=5432
```
> Локально можно использовать `localhost` в `DB_HOST`, если бот запускается вне Docker.

## Быстрый старт (Docker)
1. Создайте файл `.env` рядом с `docker-compose.yml` и заполните переменные из таблицы выше.
2. Запустите стек:
   ```bash
   docker compose up -d --build
   ```
3. Проверьте логи бота:
   ```bash
   docker compose logs -f devcheck-bot
   ```
4. Остановить:
   ```bash
   docker compose down
   ```
   Данные PostgreSQL лежат в `./pgdata`.

## Локальный запуск без Docker
1. Установите PostgreSQL и создайте БД/пользователя из `.env`.
2. Активируйте виртуальное окружение и зависимости:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Экспортируйте переменные (`export $(cat .env | xargs)` или используйте `python-dotenv`).
4. Запустите бота:
   ```bash
   python -m bot.main
   ```

## Структура проекта
```
bot/
  main.py             # входная точка, запускает aiogram + планировщик
  telegram/           # Telegram-команды, inline-обработчики, scheduler
  checks/             # HTTP/SSL/WHOIS/GeoIP-проверки и поиск поддоменов
  checks/service.py   # общий сервис проверки ресурса для UI и будущих агентов
  infra/              # PostgreSQL и инфраструктурные адаптеры
  core/               # форматтеры, URL-утилиты и общие helpers
```

Старые модули верхнего уровня (`bot/monitor.py`, `bot/db.py` и т.п.) оставлены как compatibility-wrapper'ы для существующих импортов.

Дополнительная архитектурная заметка по будущему websocket-агенту: `docs/architecture.md`.

## Админские команды
- `/admin` — список всех сайтов и пользователи, с inline‑удалением.
- `/status` — статусы всех сайтов.
- `/events` / `/logs` — события мониторинга и действия пользователей за 14 дней.
- `/export_logs`, `/export_sites` — выгрузка CSV.
- `/remove_user <user_id>` — полностью удалить сайты и логи пользователя.

## Полезные заметки
- При старте `bot/main.py` вызывает `migrate_add_notification_flags()` для добавления недостающих колонок в таблице `sites`.
- Расписание проверок задаётся в `scheduler.py`; при необходимости отрегулируйте интервал.
- Логи действий пишутся в БД (`user_logs`) через `log_user_action`, их удобно использовать для аудита.

Готово! После развертывания добавьте бота в Telegram и отправьте `/start`, чтобы протестировать функционал.
