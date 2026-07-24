from __future__ import annotations

import os
import re
from hashlib import sha1
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from flask import Flask, Response, jsonify, render_template, request

from autoflix_cli.scraping import anime_sama, arkanime, coflix, french_stream, player, wiflix
from . import node_providers, tmdb


ROOT = Path(__file__).parent
app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))

DEFAULT_ALLOWED_ORIGINS = {
    "https://nexoragabon.com",
    "https://www.nexoragabon.com",
}
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.getenv("AUTOFLIX_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
} or DEFAULT_ALLOWED_ORIGINS


@app.after_request
def add_cors_headers(response):
    """Allow the production site and its www variant to call the API."""
    origin = request.headers.get("Origin", "").rstrip("/")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Vary"] = "Origin"
    return response

PROVIDERS = {
    "french-stream": {"label": "French-Stream", "module": french_stream, "languages": ["fr"]},
    "anime-sama": {"label": "Anime-Sama", "module": anime_sama, "languages": ["fr"]},
}


def serialize(value: Any) -> Any:
    """Turn the CLI's lightweight objects into JSON-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if is_dataclass(value):
        return serialize(asdict(value))
    if hasattr(value, "__dict__"):
        return {key: serialize(item) for key, item in vars(value).items() if not key.startswith("_")}
    return str(value)


def _players(value: Any) -> list[dict]:
    if not value:
        return []
    return [
        {
            "name": getattr(item, "name", "Source vidéo"),
            "label": getattr(item, "name", "Source vidéo"),
            "url": getattr(item, "url", ""),
        }
        for item in value
        if getattr(item, "url", "")
    ]


def normalize_image_url(value: Any, base_url: str = "") -> str:
    """Repair relative and accidentally double-prefixed provider artwork URLs."""
    source = str(value or "").strip()
    if not source:
        return ""
    duplicated_origin = re.match(r"^https?://[^/]+(https?://.+)$", source, re.IGNORECASE)
    if duplicated_origin:
        source = duplicated_origin.group(1)
    if source.startswith("//"):
        return f"https:{source}"
    if urlparse(source).scheme in {"http", "https"}:
        return source
    return urljoin(base_url.rstrip("/") + "/", source) if base_url else source


def _source_fields(provider_name: str, stream_available: bool = True) -> dict[str, Any]:
    is_anime = provider_name == "anime-sama"
    return {
        "source": "Anime Nexora" if is_anime else "Content-Nexora",
        "sourceCode": "anime-nexora" if is_anime else "content-nexora",
        "provider": "anime-nexora" if is_anime else "content-nexora",
        "scraperProvider": provider_name or None,
        "playbackProvider": "anime-nexora" if is_anime else "content-nexora",
        "playbackProviderName": "Anime NexoraAPI" if is_anime else "Content-Nexora",
        "metadataAvailable": True,
        "streamAvailable": stream_available,
        "externalPlayback": True,
        "availableProviders": ["anime-nexora"] if is_anime else [
            "content-nexora",
            *(["french-nexora-node"] if node_providers.configured() else []),
        ],
    }


def _media_fields(
    provider_name: str,
    media_type: str,
    title: str,
    url: str,
    image: str,
    genres: Any,
    *,
    stream_available: bool = True,
) -> dict[str, Any]:
    normalized_image = normalize_image_url(image, url)
    identifier = sha1(str(url or title).encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"{'anime-nexora' if provider_name == 'anime-sama' else 'content-nexora'}~{media_type}~{identifier}",
        "type": media_type,
        "title": title,
        "name": title,
        "url": url,
        "img": normalized_image,
        "image_url": normalized_image,
        "image": normalized_image,
        "poster": normalized_image,
        "backdrop": normalized_image,
        "genres": genres or [],
        "categoryId": f"{'anime-nexora' if provider_name == 'anime-sama' else 'content-nexora'}-{media_type}",
        "categoryName": "Anime" if provider_name == "anime-sama" else (
            "Séries françaises" if media_type == "series" else "Films français"
        ),
        "isSeries": media_type == "series",
        **_source_fields(provider_name, stream_available),
    }


def normalize_content(value: Any, provider_name: str = "") -> dict:
    """Expose a stable media tree regardless of the scraper's internal class."""
    kind = value.__class__.__name__
    if kind in {"FrenchStreamMovie", "CoflixMovie", "WiflixMovie"}:
        players = _players(value.players)
        return {
            **_media_fields(
                provider_name,
                "movie",
                value.title,
                value.url,
                getattr(value, "img", ""),
                getattr(value, "genres", []),
                stream_available=bool(players),
            ),
            "players": players,
            "sources": players,
        }
    if kind == "FrenchStreamSeason":
        season_number = _number_from_text(value.title, 1)
        episodes = normalize_episodes(value.episodes, provider_name, season_number)
        episode_count = max((len(items) for items in episodes.values()), default=0)
        return {
            **_media_fields(provider_name, "series", value.title, value.url, getattr(value, "img", ""), [], stream_available=episode_count > 0),
            "seasonCount": 1,
            "episodeCount": episode_count,
            "seasons": [{
                "type": "season",
                "season": season_number,
                "name": f"Saison {season_number}",
                "title": f"Saison {season_number}",
                "url": value.url,
                "episodeCount": episode_count,
                "episodes": episodes,
            }],
        }
    if kind in {"SamaSeries", "CoflixSeries", "ArkSeries"}:
        seasons = []
        for index, season in enumerate(getattr(value, "seasons", []), 1):
            season_number = _number_from_text(getattr(season, "title", ""), index)
            episodes = normalize_episodes(getattr(season, "episodes", {}), provider_name, season_number) if hasattr(season, "episodes") else {}
            episode_count = max((len(items) for items in episodes.values()), default=0)
            seasons.append({
                "type": "season",
                "season": season_number,
                "name": season.title,
                "title": season.title,
                "url": getattr(season, "url", getattr(season, "id", "")),
                "episodeCount": episode_count,
                "episodes": episodes,
            })
        series_url = getattr(value, "url", getattr(value, "id", ""))
        episode_count = sum(season["episodeCount"] for season in seasons)
        return {
            **_media_fields(provider_name, "series", value.title, series_url, getattr(value, "img", ""), getattr(value, "genres", []), stream_available=bool(seasons)),
            "seasonCount": len(seasons),
            "episodeCount": episode_count,
            "seasons": seasons,
        }
    if kind in {"SamaSeason", "CoflixSeason", "WiflixSeriesSeason"}:
        season_number = _number_from_text(value.title, 1)
        episodes = normalize_episodes(value.episodes, provider_name, season_number)
        return {
            "type": "season",
            "season": season_number,
            "name": value.title,
            "title": value.title,
            "url": value.url,
            "episodeCount": max((len(items) for items in episodes.values()), default=0),
            "episodes": episodes,
        }
    if kind == "Episode":
        players = _players(value.players)
        return {
            "type": "episode",
            "name": value.title,
            "title": value.title,
            "episode": _number_from_text(value.title, 1),
            "index": _number_from_text(value.title, 1),
            "players": players,
            "sources": players,
            "streamAvailable": bool(players),
        }
    return serialize(value)


def _number_from_text(value: Any, fallback: int) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else fallback


def normalize_episodes(episodes: Any, provider_name: str = "", season_number: int = 1) -> dict:
    if isinstance(episodes, dict):
        result = {}
        for language, items in episodes.items():
            normalized_items = []
            for index, item in enumerate(items, 1):
                episode = normalize_content(item, provider_name)
                episode_number = _number_from_text(episode.get("title"), index)
                episode.update({
                    "id": f"{'anime-nexora' if provider_name == 'anime-sama' else 'content-nexora'}~episode~s{season_number}e{episode_number}~{language}",
                    "season": season_number,
                    "episode": episode_number,
                    "index": episode_number,
                    "language": str(language),
                    "languageName": str(language).upper(),
                })
                for source in episode.get("players", []):
                    source.setdefault("language", str(language))
                    source.setdefault("lang", str(language))
                normalized_items.append(episode)
            result[str(language)] = normalized_items
        return result
    if isinstance(episodes, list):
        return normalize_episodes({"default": episodes}, provider_name, season_number)
    return {}


def provider_or_error(name: str):
    provider = PROVIDERS.get(name.lower())
    if not provider:
        raise ValueError(f"Unknown provider. Choose one of: {', '.join(PROVIDERS)}")
    return provider


def call_provider(provider_name: str, operation: str, url: str | None = None, query: str | None = None):
    provider = provider_or_error(provider_name)
    module = provider["module"]
    # These scrapers intentionally initialize their origin in the CLI flow.
    # The HTTP API has no interactive provider menu, so initialize it here.
    if provider_name.lower() in {"anime-sama"}:
        module.get_website_url()
    if operation == "search":
        return module.search(query or "")
    if operation == "content":
        if hasattr(module, "get_content"):
            return module.get_content(url or "")
        return module.get_series(url or "")
    if operation == "series":
        return module.get_series(url or "")
    if operation == "season":
        return module.get_season(url or "")
    if operation == "episode":
        return module.get_episode(url or "")
    raise ValueError("Unsupported operation")


def normalize_search_result(value: Any, provider_name: str) -> dict[str, Any]:
    raw_title = str(getattr(value, "title", "") or "").strip()
    url = str(getattr(value, "url", "") or "").strip()
    is_series = provider_name == "anime-sama" or bool(
        re.search(r"(?:\bsaison\b|\bseason\b|\bepisode\b|/s-tv/)", f"{raw_title} {url}", re.IGNORECASE)
    )
    if provider_name == "anime-sama" and re.search(r"/(?:film|movie)(?:/|$)", url, re.IGNORECASE):
        is_series = False
    media_type = "series" if is_series else "movie"
    return _media_fields(
        provider_name,
        media_type,
        raw_title,
        url,
        getattr(value, "img", ""),
        getattr(value, "genres", []),
    )


def _merge_node_sources(content: dict[str, Any]) -> dict[str, Any]:
    tmdb_id = request.args.get("tmdbId", "").strip()
    if not tmdb_id or not node_providers.configured():
        return content
    media_type = "series" if content.get("type") == "series" else "movie"
    season_number = int(request.args.get("season", "1"))
    episode_number = int(request.args.get("episode", "1"))
    payload = node_providers.streams(
        tmdb_id,
        media_type,
        season=season_number if media_type == "series" else None,
        episode=episode_number if media_type == "series" else None,
        provider=request.args.get("nodeProvider", "all"),
    )
    sources = node_providers.normalized_sources(payload)
    content["nodeProviders"] = payload.get("providers", [])
    content["availableProviders"] = list(dict.fromkeys([
        *content.get("availableProviders", []),
        "french-nexora-node",
    ]))
    if not sources:
        return content
    if media_type == "movie":
        content["players"] = [*content.get("players", []), *sources]
        content["sources"] = content["players"]
        content["streamAvailable"] = True
        return content
    seasons = content.get("seasons", [])
    selected_season = next(
        (season for season in seasons if int(season.get("season", 0)) == season_number),
        seasons[0] if seasons else None,
    )
    if not selected_season:
        return content
    episodes = selected_season.setdefault("episodes", {})
    node_language = episodes.setdefault("fr-node", [])
    node_language.append({
        "id": f"content-nexora~episode~s{season_number}e{episode_number}~fr-node",
        "type": "episode",
        "name": f"Épisode {episode_number}",
        "title": f"Épisode {episode_number}",
        "season": season_number,
        "episode": episode_number,
        "index": episode_number,
        "language": "fr",
        "players": sources,
        "sources": sources,
        "streamAvailable": True,
    })
    content["streamAvailable"] = True
    return content


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "autoflix-api"})


@app.get("/api/providers")
def providers():
    return jsonify({
        "providers": [{"id": key, **{k: v for k, v in value.items() if k != "module"}} for key, value in PROVIDERS.items()],
        "playbackProviders": [
            {
                "id": "content-nexora",
                "label": "Content-Nexora / French-Stream",
                "enabled": True,
                "types": ["movie", "series"],
            },
            {
                "id": "french-nexora-node",
                "label": "French Nexora API Node",
                "enabled": node_providers.configured(),
                "types": ["movie", "series"],
            },
        ],
    })


@app.get("/api/catalog/items")
def catalog_items():
    """TMDB-backed catalog consumed by the Nexora web platform."""
    try:
        media_type = request.args.get("type", "movie").lower()
        if media_type not in {"movie", "series"}:
            return jsonify([])
        limit = min(max(int(request.args.get("limit", "24")), 1), 100)
        query = request.args.get("q", "").strip()
        items = tmdb.search(query, media_type, limit) if query else tmdb.popular(media_type, limit)
        return jsonify(items)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/catalog/items/<path:item_id>")
def catalog_item(item_id: str):
    try:
        tmdb_id, media_type = tmdb.parse_public_id(item_id)
        return jsonify(tmdb.details(tmdb_id, media_type))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/catalog/series/<path:item_id>")
def catalog_series(item_id: str):
    try:
        tmdb_id, media_type = tmdb.parse_public_id(item_id)
        if media_type != "series":
            return jsonify({"error": "Expected a TMDB series id"}), 400
        return jsonify(tmdb.series(tmdb_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/node-fr/api/catalog/items")
def legacy_catalog_items():
    """Compatibility path used by older Nexora web builds."""
    return catalog_items()


@app.get("/node-fr/api/catalog/items/<path:item_id>")
def legacy_catalog_item(item_id: str):
    return catalog_item(item_id)


@app.get("/node-fr/api/catalog/series/<path:item_id>")
def legacy_catalog_series(item_id: str):
    return catalog_series(item_id)


@app.get("/api/node/providers")
@app.get("/node-fr/api/providers")
def node_provider_list():
    if not node_providers.configured():
        return jsonify({"enabled": False, "count": 0, "providers": []})
    try:
        values = node_providers.providers()
        return jsonify({"enabled": True, "count": len(values), "providers": values})
    except Exception as exc:
        return jsonify({"enabled": True, "count": 0, "providers": [], "error": str(exc)}), 502


@app.get("/api/node/streams")
@app.get("/node-fr/api/streams")
def node_streams():
    if not node_providers.configured():
        return jsonify({"error": "FRENCH_NEXORA_API_BASE_URL is not configured"}), 503
    try:
        tmdb_id = request.args.get("tmdbId", "").strip()
        if not tmdb_id or not re.fullmatch(r"[A-Za-z0-9_-]+", tmdb_id):
            return jsonify({"error": "tmdbId is required"}), 400
        media_type = request.args.get("mediaType", "movie").lower()
        if media_type not in {"movie", "tv", "series"}:
            return jsonify({"error": "mediaType must be movie, tv, or series"}), 400
        season_number = int(request.args.get("season", "0") or 0)
        episode_number = int(request.args.get("episode", "0") or 0)
        payload = node_providers.streams(
            tmdb_id,
            media_type,
            season=season_number or None,
            episode=episode_number or None,
            provider=request.args.get("provider", "all"),
        )
        payload["sources"] = node_providers.normalized_sources(payload)
        return jsonify(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/anime-api/api/v1/search")
def legacy_anime_search():
    """Compatibility path for the previous Anime-Nexora client."""
    query = request.args.get("q", "").strip()
    try:
        raw = anime_sama.search(query) if query else []
        data = []
        for item in raw:
            image = normalize_image_url(item.img, item.url)
            data.append({
                "id": f"anime-nexora~series~{sha1(item.url.encode('utf-8')).hexdigest()[:12]}",
                "name": item.title,
                "title": item.title,
                "url": item.url,
                "image_url": image,
                "image": image,
                "poster": image,
                "genres": item.genres,
                "categories": ["Anime"],
                "languages": ["VF", "VOSTFR"],
                **_source_fields("anime-sama"),
            })
        return jsonify({"count": len(data), "data": data[: min(int(request.args.get("limit", "12")), 100)]})
    except Exception as exc:
        return jsonify({"count": 0, "data": [], "error": str(exc)}), 503


@app.get("/api/search")
def search():
    try:
        query = request.args.get("q", "").strip()
        if len(query) < 2:
            return jsonify({"error": "q must contain at least 2 characters"}), 400
        provider_name = request.args.get("provider", "").lower()
        result = call_provider(provider_name, "search", query=query)
        return jsonify({"results": [normalize_search_result(item, provider_name) for item in result]})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/content")
def content():
    try:
        provider_name = request.args["provider"].lower()
        normalized = normalize_content(call_provider(provider_name, "content", url=request.args["url"]), provider_name)
        return jsonify({"content": _merge_node_sources(normalized)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/series")
def series():
    try:
        provider_name = request.args["provider"].lower()
        normalized = normalize_content(call_provider(provider_name, "series", url=request.args["url"]), provider_name)
        return jsonify({"content": _merge_node_sources(normalized)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/season")
def season():
    try:
        provider_name = request.args["provider"].lower()
        return jsonify({"season": normalize_content(call_provider(provider_name, "season", url=request.args["url"]), provider_name)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/episode")
def episode():
    try:
        provider_name = request.args["provider"].lower()
        return jsonify({"episode": normalize_content(call_provider(provider_name, "episode", url=request.args["url"]), provider_name)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/api/resolve")
def resolve():
    payload = request.get_json(silent=True) or {}
    player_url = str(payload.get("player_url", "")).strip()
    if urlparse(player_url).scheme not in {"http", "https"}:
        return jsonify({"error": "player_url must be an HTTP(S) URL"}), 400
    try:
        referer = str(payload.get("referer", "https://autoflix.local/"))
        stream_url, subtitle_url = player.get_hls_link(player_url, headers={"Referer": referer}, return_subs=True)
        if not stream_url:
            return jsonify({"error": "No compatible stream found for this player URL"}), 404
        return jsonify({"stream_url": stream_url, "subtitle_url": subtitle_url, "kind": "hls" if ".m3u8" in stream_url.lower() else "video"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


def main():
    app.run(host=os.getenv("AUTOFLIX_HOST", "127.0.0.1"), port=int(os.getenv("AUTOFLIX_PORT", "8787")), debug=False)


if __name__ == "__main__":
    main()
