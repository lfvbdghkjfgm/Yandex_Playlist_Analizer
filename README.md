# PlaylistPersona

**PlaylistPersona** is a service for creating a psychological portrait of a Yandex Music playlist owner. Paste a playlist link, and the service will analyze musical preferences to infer character, emotions, and mindset.

## What the service does

- 🔍 Анализирует плейлист Яндекс.Музыки.
- 🧠 Формирует психологический портрет владельца.
- 🌒 Удобный тёмный интерфейс для быстрого ввода и вывода.
- 🚀 Работает с Ollama в Docker-контейнере.

## Быстрый запуск через Docker Compose

1. Соберите и запустите сервис:

```powershell
docker compose build
docker compose up -d
```

2. Откройте браузер:

```text
http://localhost:8080
```

## Launching with Docker Compose

1. Build and start the service:

```powershell
docker compose build
docker compose up -d
```

2. Open the frontend in your browser:

```text
http://localhost:8080
```

3. To stop the service:

```powershell
docker compose down
```

## Project structure

- `app.py` — основной Flask-сервер.
- `templates/index.html` — фронтенд-интерфейс.
- `requirements.txt` — Python-зависимости.
- `Dockerfile` — образ для веб-сервиса.
- `Dockerfile.ollama` — образ для Ollama.
- `docker-compose.yml` — запуск веб-сервиса и Ollama вместе.

## Важная заметка

Сервис использует Ollama для генерации текста. При первом запуске в Docker может потребоваться некоторое время на загрузку модели.

## Технологии

- Python / Flask
- HTML / CSS / JavaScript
- Docker / Docker Compose
- Ollama

---

Если хотите, можно также добавить инструкцию по использованию приватного OAuth-токена Яндекс.Музыки для доступа к закрытым плейлистам.
