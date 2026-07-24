from __future__ import annotations

import os
from typing import Any

from curl_cffi import requests


def base_url() -> str:
    return os.getenv("FRENCH_NEXORA_API_BASE_URL", "").strip().rstrip("/")


def configured() -> bool:
    return bool(base_url())


def _request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not configured():
        raise RuntimeError("FRENCH_NEXORA_API_BASE_URL is not configured")
    response = requests.get(
        f"{base_url()}{path}",
        params=params or {},
        headers={"Accept": "application/json"},
        impersonate="chrome",
        timeout=int(os.getenv("FRENCH_NEXORA_API_TIMEOUT", "65")),
    )
    response.raise_for_status()
    return response.json()


def providers() -> list[dict[str, Any]]:
    payload = _request("/api/providers")
    values = payload.get("providers", [])
    return values if isinstance(values, list) else []


def streams(
    tmdb_id: str | int,
    media_type: str,
    *,
    season: int | None = None,
    episode: int | None = None,
    provider: str = "all",
) -> dict[str, Any]:
    normalized_type = "tv" if media_type in {"tv", "series"} else "movie"
    params: dict[str, Any] = {
        "tmdbId": str(tmdb_id),
        "mediaType": normalized_type,
        "provider": provider or "all",
    }
    if normalized_type == "tv":
        if not season or not episode:
            raise ValueError("season and episode are required for a series")
        params.update({"season": int(season), "episode": int(episode)})
    return _request("/api/streams", params)


def normalized_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose the Node providers with the same player shape as Content-Nexora."""
    streams_value = payload.get("streams", [])
    if not isinstance(streams_value, list):
        return []
    sources = []
    seen = set()
    for stream in streams_value:
        if not isinstance(stream, dict):
            continue
        url = str(stream.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        provider_name = stream.get("providerName") or stream.get("provider") or "French Nexora"
        sources.append(
            {
                "name": str(stream.get("title") or provider_name),
                "label": str(stream.get("title") or provider_name),
                "url": url,
                "quality": stream.get("quality"),
                "language": stream.get("language") or "fr",
                "type": stream.get("type"),
                "headers": stream.get("headers"),
                "provider": stream.get("provider"),
                "providerName": provider_name,
                "source": "French Nexora API Node",
                "sourceCode": "french-nexora-node",
            }
        )
    return sources
