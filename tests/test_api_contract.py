from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from autoflix_api import tmdb
from autoflix_api.app import app, normalize_content, normalize_image_url, normalize_search_result
from autoflix_cli.scraping.objects import Episode, FrenchStreamSeason, Player, SearchResult


class TmdbContractTests(unittest.TestCase):
    def test_catalog_item_matches_the_front_contract(self):
        raw = {
            "id": 603,
            "title": "Matrix",
            "original_title": "The Matrix",
            "release_date": "1999-03-30",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "overview": "Un monde simulé.",
            "vote_average": 8.2,
            "genre_ids": [28, 878],
        }

        item = tmdb._item(raw, "movie")

        self.assertEqual("tmdb~movie~603", item["id"])
        self.assertEqual("TMDB", item["source"])
        self.assertEqual("tmdb", item["sourceCode"])
        self.assertEqual("videasy", item["playbackProvider"])
        self.assertEqual(603, item["tmdbId"])
        self.assertTrue(item["streamAvailable"])
        self.assertEqual("https://image.tmdb.org/t/p/w500/poster.jpg", item["poster"])

    @patch("autoflix_api.tmdb._request")
    def test_series_details_expose_clickable_episodes(self, request_mock):
        request_mock.return_value = {
            "id": 1399,
            "name": "Game of Thrones",
            "first_air_date": "2011-04-17",
            "poster_path": "/got.jpg",
            "backdrop_path": "/got-bg.jpg",
            "genres": [{"id": 18, "name": "Drame"}],
            "seasons": [
                {"id": 1, "season_number": 1, "name": "Saison 1", "episode_count": 2}
            ],
        }

        result = tmdb.series(1399)
        episodes = result["seasons"][0]["episodes"]

        self.assertEqual(1, result["seasonCount"])
        self.assertEqual(2, result["episodeCount"])
        self.assertEqual("tmdb~series~1399~s~1~e~1", episodes[0]["id"])
        self.assertEqual(1, episodes[0]["season"])
        self.assertEqual(1, episodes[0]["episode"])
        self.assertEqual("videasy", episodes[0]["playbackProvider"])

    def test_current_and_legacy_tmdb_ids_are_accepted(self):
        self.assertEqual((603, "movie"), tmdb.parse_public_id("tmdb~movie~603"))
        self.assertEqual((1399, "series"), tmdb.parse_public_id("tmdb:tv:1399"))


class ContentContractTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_duplicate_french_stream_image_origin_is_repaired(self):
        value = "https://french-stream.onehttps://image.tmdb.org/t/p/w500/poster.jpg"
        self.assertEqual(
            "https://image.tmdb.org/t/p/w500/poster.jpg",
            normalize_image_url(value),
        )

    def test_search_result_has_clickable_front_fields(self):
        raw = SearchResult(
            "Mercredi - Saison 1",
            "https://french-stream.one/15112935-mercredi-saison-1.html",
            "https://image.tmdb.org/t/p/w500/poster.jpg",
            [],
        )

        item = normalize_search_result(raw, "french-stream")

        self.assertEqual("series", item["type"])
        self.assertEqual("content-nexora", item["sourceCode"])
        self.assertEqual("content-nexora", item["playbackProvider"])
        self.assertEqual(item["image"], item["poster"])
        self.assertTrue(item["streamAvailable"])

    def test_french_series_exposes_season_episode_and_language_fields(self):
        remote = FrenchStreamSeason(
            "Mercredi - Saison 1",
            "https://french-stream.one/mercredi-saison-1.html",
            {"vf": [Episode("Episode 1", [Player("Source VF", "https://video.test/embed")])]},
        )

        content = normalize_content(remote, "french-stream")
        episode = content["seasons"][0]["episodes"]["vf"][0]

        self.assertEqual("series", content["type"])
        self.assertEqual(1, content["seasonCount"])
        self.assertEqual(1, content["episodeCount"])
        self.assertEqual(1, episode["season"])
        self.assertEqual(1, episode["episode"])
        self.assertEqual("vf", episode["language"])
        self.assertEqual("vf", episode["players"][0]["language"])

    def test_provider_response_exposes_content_and_node_services(self):
        body = self.client.get("/api/providers").get_json()
        ids = {provider["id"] for provider in body["playbackProviders"]}
        self.assertEqual({"content-nexora", "french-nexora-node"}, ids)

    def test_node_routes_report_disabled_configuration_cleanly(self):
        with patch.dict(os.environ, {"FRENCH_NEXORA_API_BASE_URL": ""}, clear=False):
            response = self.client.get("/api/node/providers")
            legacy_response = self.client.get("/node-fr/api/providers")
        self.assertEqual(200, response.status_code)
        self.assertEqual(False, response.get_json()["enabled"])
        self.assertEqual(response.get_json(), legacy_response.get_json())

    @patch("autoflix_api.app.node_providers.streams")
    @patch("autoflix_api.app.call_provider")
    def test_node_movie_sources_are_merged_into_content(self, provider_mock, streams_mock):
        from autoflix_cli.scraping.objects import FrenchStreamMovie

        provider_mock.return_value = FrenchStreamMovie(
            "Matrix",
            "https://french-stream.one/matrix.html",
            "https://image.tmdb.org/t/p/w500/matrix.jpg",
            ["Science-fiction"],
            [Player("Content source", "https://content.test/embed")],
        )
        streams_mock.return_value = {
            "streams": [{
                "url": "https://node.test/movie.m3u8",
                "title": "Node source",
                "provider": "coflix",
                "providerName": "Coflix",
                "language": "fr",
                "type": "hls",
            }],
            "providers": [{"id": "coflix", "status": "ok", "count": 1}],
        }
        with patch.dict(os.environ, {"FRENCH_NEXORA_API_BASE_URL": "http://node.test"}, clear=False):
            response = self.client.get(
                "/api/content?provider=french-stream&url=https://french-stream.one/matrix.html&tmdbId=603"
            )

        self.assertEqual(200, response.status_code)
        content = response.get_json()["content"]
        self.assertEqual(2, len(content["players"]))
        self.assertEqual("french-nexora-node", content["players"][1]["sourceCode"])
        self.assertIn("french-nexora-node", content["availableProviders"])

    @patch("autoflix_api.app.tmdb.details")
    def test_catalog_detail_route_accepts_front_id(self, details_mock):
        details_mock.return_value = {"id": "tmdb~movie~603", "sourceCode": "tmdb"}
        response = self.client.get("/api/catalog/items/tmdb~movie~603")
        self.assertEqual(200, response.status_code)
        self.assertEqual("tmdb~movie~603", response.get_json()["id"])
        details_mock.assert_called_once_with(603, "movie")


if __name__ == "__main__":
    unittest.main()
