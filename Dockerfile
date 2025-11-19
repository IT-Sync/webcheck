FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt update && apt install -y whois

COPY bot/ ./bot/
COPY .env .env

ENV PYTHONPATH=/app

CMD ["python", "bot/main.py"]

