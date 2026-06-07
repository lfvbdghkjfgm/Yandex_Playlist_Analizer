from flask import Flask, request, render_template, Response, stream_with_context
from html import unescape
from html.parser import HTMLParser
import os
import re
import requests
import ollama
from ollama import Client
from urllib.parse import unquote, urlparse

app = Flask(__name__)

API_BASE_URLS = ("https://api.music.yandex.ru", "https://api.music.yandex.net")
REQUEST_TIMEOUT = 20


class PlaylistLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        for attr in ("src", "href"):
            url = attrs_dict.get(attr)
            if url:
                self.urls.append(unescape(url))


def extract_url_candidates(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return []

    candidates = []
    parser = PlaylistLinkParser()
    parser.feed(value)
    candidates.extend(parser.urls)
    candidates.extend(re.findall(r"https?://[^\s\"']+", value))
    candidates.append(value)

    unique_candidates = []
    for candidate in candidates:
        candidate = unescape(candidate).strip()
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)

    return unique_candidates


def parse_playlist_reference(raw_value):
    for candidate in extract_url_candidates(raw_value):
        parsed_url = urlparse(candidate)
        path_parts = [unquote(part) for part in parsed_url.path.split("/") if part]

        if len(path_parts) >= 4 and path_parts[0] == "iframe" and path_parts[1] == "playlist":
            return {"type": "owner_kind", "owner": path_parts[2], "kind": path_parts[3]}

        if len(path_parts) >= 4 and path_parts[0] == "users" and path_parts[2] == "playlists":
            return {"type": "owner_kind", "owner": path_parts[1], "kind": path_parts[3]}

        if len(path_parts) >= 2 and path_parts[0] in ("playlist", "playlists"):
            return {"type": "uuid", "uuid": path_parts[1]}

        if re.fullmatch(r"(?:lk\.)?[0-9a-fA-F-]{36}", candidate):
            playlist_uuid = candidate if candidate.startswith("lk.") else f"lk.{candidate}"
            return {"type": "uuid", "uuid": playlist_uuid}

    raise ValueError(
        "Не удалось найти плейлист во входных данных. Вставьте ссылку Яндекс Музыки "
        "или iframe-код вида https://music.yandex.ru/iframe/playlist/<user>/<id>."
    )


def create_yandex_headers():
    headers = {
        "accept": "application/json",
        "accept-language": "ru",
        "user-agent": "Mozilla/5.0",
        "x-yandex-music-client": "YandexMusicWebIframe/1.0.0",
        "x-yandex-music-without-invocation-info": "1",
    }
    token = os.getenv("YANDEX_MUSIC_TOKEN")
    if token:
        headers["authorization"] = token if token.lower().startswith(("oauth ", "bearer ")) else f"OAuth {token}"

    return headers


def build_playlist_api_path(playlist_reference):
    if playlist_reference["type"] == "uuid":
        return f"playlist/{playlist_reference['uuid']}"

    return f"users/{playlist_reference['owner']}/playlists/{playlist_reference['kind']}"


def describe_api_error(response):
    try:
        response_data = response.json()
        api_error = response_data.get("error", response_data)
        error_name = api_error.get("name")
        error_message = api_error.get("message")
    except ValueError:
        error_name = None
        error_message = response.text[:200]

    if response.status_code == 451:
        return (
            "API Яндекс Музыки вернул 451 Unavailable For Legal Reasons. "
            "Обычно это значит, что данные плейлиста недоступны без авторизации, "
            "подписки или из текущего региона. Если у аккаунта есть доступ, задайте "
            "OAuth-токен в переменной окружения YANDEX_MUSIC_TOKEN."
        )

    if response.status_code in (401, 403):
        return (
            f"API Яндекс Музыки вернул {response.status_code}. "
            "Нужна авторизация: задайте OAuth-токен в переменной окружения YANDEX_MUSIC_TOKEN."
        )

    details = f": {error_name}" if error_name else ""
    if error_message:
        details += f" {error_message}"

    return f"Ошибка при получении данных: {response.status_code}{details}"


def request_playlist_data(playlist_reference):
    path = build_playlist_api_path(playlist_reference)
    params = {
        "richTracks": "true",
        "page": 0,
        "pageSize": 1000,
        "trackMetaType": "music",
    }
    headers = create_yandex_headers()
    last_error = "неизвестная ошибка"

    for base_url in API_BASE_URLS:
        response = requests.get(
            f"{base_url}/{path}",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 200:
            return response.json()

        last_error = describe_api_error(response)

        if response.status_code in (401, 403, 451):
            break

    raise RuntimeError(last_error)


def unwrap_playlist_data(response_data):
    if isinstance(response_data, dict) and isinstance(response_data.get("result"), dict):
        return response_data["result"]

    return response_data


def format_track_title(track_item):
    track = track_item.get("track", track_item) if isinstance(track_item, dict) else {}
    title = track.get("title")
    artists = track.get("artists") or []
    artists_text = ", ".join(
        artist.get("name") for artist in artists if isinstance(artist, dict) and artist.get("name")
    )

    if title and artists_text:
        return f"{artists_text} - {title}"

    return title or "Без названия"


def get_tracks_from_playlist(playlist_url):
    try:
        playlist_reference = parse_playlist_reference(playlist_url)
        playlist_data = unwrap_playlist_data(request_playlist_data(playlist_reference))
        tracks = playlist_data.get("tracks", []) if isinstance(playlist_data, dict) else []

        if tracks:
            return [format_track_title(track) for track in tracks]

        return ["Треки не найдены в плейлисте."]
    except Exception as e:
        return [f"Ошибка обработки URL: {str(e)}"]

def analyze_personality_stream(tracks):
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    tracks_text = "\n".join(tracks)

    def local_fallback_analysis(tracks_list):
        # Простой эвристический анализ по названиям треков (локальный fallback)
        keywords = {
            'love': ['love', 'люб', 'любов'],
            'sad': ['sad', 'грусть', 'печаль', 'sadness'],
            'party': ['party', 'dance', 'танц', 'вечер'],
            'rock': ['rock', 'рок'],
            'pop': ['pop', 'поп'],
            'hiphop': ['hip', 'hop', 'rap', 'рэп'],
            'electronic': ['electro', 'edm', 'electron', 'дигит', 'хаус'],
            'classical': ['classical', 'симф', 'соната', 'опер'],
            'metal': ['metal', 'метал']
        }
        text = """Локальный быстрый анализ (fallback):\n\n"""
        flat = " ".join(t.lower() for t in tracks_list)
        counts = {}
        for k, toks in keywords.items():
            for tok in toks:
                if tok in flat:
                    counts[k] = counts.get(k, 0) + flat.count(tok)

        if counts:
            text += "Наиболее заметные темы/жанры: " + ", ".join(sorted(counts.keys(), key=lambda x: -counts[x])) + ".\n"
        else:
            text += "Не найдено явных ключевых жанров или тем по названиям треков.\n"

        # Элементарные выводы
        openness = 50 + min(30, sum(counts.get(k, 0) for k in ('electronic', 'rock', 'metal', 'hiphop'))) if counts else 50
        extraversion = 50 + (10 if 'party' in counts else -10 if 'sad' in counts else 0)
        neuroticism = 40 + (10 if 'sad' in counts else 0)

        text += f"OCEAN (примерно): Openness={openness}, Conscientiousness=50, Extraversion={extraversion}, Agreeableness=50, Neuroticism={neuroticism}.\n"
        text += "Уровень уверенности: низкая — это лишь эвристика по названиям треков.\n"
        text += "Ограничения: отсутствуют данные о частоте прослушиваний, порядке треков и метаданных.\n"
        return text

    messages = [
        {
            "role": "system",
            "content": """
Ты — психолог, анализирующий личность по музыкальным предпочтениям. Твоя задача — составить точный психологический портрет человека, опираясь на эмоции, мотивации и образ мышления, которые проявляются в плейлисте.

Отвечай строго по структуре и коротко. Не перечисляй жанры, не оценивай треки и не давай статистику. Избегай общих фраз типа "интересный человек" или "широкий вкус".

Структура ответа:

1) Основные черты характера: 4–6 характеристик. Каждая — 1 предложение, содержательное и связанное с музыкальными сигналами.
2) Эмоциональный профиль: текущее состояние, мотивы, доминирующие чувства и скрытые потребности.
3) Образ жизни и ценности: как этот человек предпочитает жить, к чему стремится, что для него важно.
4) Внутренний конфликт или напряжение: одно-два возможных противоречия в его личности.
5) Уверенность: укажи для каждого раздела высокую/среднюю/низкую уверенность.

Если выводы не основаны на явных признаках, говори прямо, что уверенность низкая. Отвечай только на русском языке, без воды и без лишнего текста.
"""
        },
        {
            "role": "user",
            "content": f"Вот список треков из плейлиста:\n{tracks_text}\n\nПроанализируй как психолог и дай конкретный портрет владельца. Не пиши общие фразы, не оценивай музыку, не делай жанровые выводы. Отвечай по заданным разделам."
        }
    ]
    # If explicitly disabled, use local fallback
    if os.getenv("DISABLE_OLLAMA", "0") in ("1", "true", "yes"):
        yield local_fallback_analysis(tracks)
        return

    try:
        client = Client(host=ollama_host)
        stream = client.chat(model=model, messages=messages, stream=True)
        for chunk in stream:
            try:
                # chunk is a ChatResponse object with message.content
                if hasattr(chunk, 'message') and chunk.message and hasattr(chunk.message, 'content'):
                    content = chunk.message.content
                    if content:
                        yield content
            except Exception:
                pass
        return
    except Exception as e:
        try:
            # Try non-streaming call as a fallback
            client = Client(host=ollama_host)
            resp = client.chat(model=model, messages=messages, stream=False)
            # resp is a ChatResponse object
            if hasattr(resp, 'message') and resp.message and hasattr(resp.message, 'content'):
                yield resp.message.content
            else:
                yield str(resp)
            return
        except Exception as e2:
            yield (
                "Ошибка при обращении к ollama: " + str(e2)
                + "\nВыполнен локальный быстрый анализ вместо полноценного вывода:\n\n"
            )
            yield local_fallback_analysis(tracks)
            return

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    playlist_url = request.form.get("playlist_url")
    tracks = get_tracks_from_playlist(playlist_url)

    if tracks and "Ошибка" not in tracks[0]:
        return Response(stream_with_context(analyze_personality_stream(tracks)), content_type='text/event-stream')
    else:
        error_message = tracks[0] if tracks else "Ошибка при обработке плейлиста."
        return Response(error_message, content_type='text/plain')

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug)
