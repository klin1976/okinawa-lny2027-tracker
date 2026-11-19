from __future__ import annotations
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.config import Settings
from src.db.database import init_db
from src.db.repository import TourRepository
from src.extractor.detail_crawler import DetailCrawler, DetailExtractionError, EXPAND_TABS_JS
from src.extractor.flight_benchmark import FlightBenchmarkClient, parse_price_twd
from src.schemas.tour_schema import OkinawaTourPackage


def test_settings_llm_provider_switching(monkeypatch):
    # Gemini 模式
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    s_gemini = Settings(_env_file=None)
    assert s_gemini.get_litellm_provider_model() == "gemini/gemini-2.5-flash"
    assert s_gemini.get_llm_api_token() == "test-gemini-key"
    assert s_gemini.get_llm_base_url() is None

    # Ollama 模式
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    s_ollama = Settings(_env_file=None)
    assert s_ollama.get_litellm_provider_model() == "ollama/qwen2.5:14b"
    assert s_ollama.get_llm_api_token() is None
    assert s_ollama.get_llm_base_url() == "http://localhost:11434"


def test_parse_extracted_json_single_and_chunked_list():
    sample_dict = {
        "agency": "雄獅旅遊",
        "tour_code": "27JN204BR",
        "tour_name": "春節沖繩五日遊",
        "days": 5,
        "nights": 4,
        "departure_airport": "TPE",
        "pricing": {"adult_twin_price": 45900},
    }

    # 測試 chunking 回傳包含 error 物件的 list
    raw_list = json.dumps([{"error": "chunk empty"}, sample_dict])
    pkg = DetailCrawler.parse_extracted_json(raw_list, source_url="https://example.com/tour")
    assert isinstance(pkg, OkinawaTourPackage)
    assert pkg.agency == "雄獅旅遊"
    assert pkg.source_url == "https://example.com/tour"
    assert pkg.pricing.adult_twin_price == 45900

    # 測試空字串拋出例外
    with pytest.raises(DetailExtractionError):
        DetailCrawler.parse_extracted_json("")


@pytest.mark.asyncio
async def test_detail_crawler_parse_url_with_mock():
    sample_json = json.dumps(
        {
            "agency": "可樂旅遊",
            "tour_code": "OKA0204",
            "tour_name": "2027春節可樂沖繩四日",
            "days": 4,
            "nights": 3,
            "departure_airport": "KHH",
            "pricing": {"adult_twin_price": 38900, "tip_per_day_twd": 300},
        }
    )

    mock_result = SimpleNamespace(
        success=True,
        extracted_content=sample_json,
        error_message=None,
    )
    mock_crawler_instance = AsyncMock()
    mock_crawler_instance.arun.return_value = mock_result
    mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
    mock_crawler_instance.__aexit__.return_value = None

    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="ollama",
        OLLAMA_MODEL="qwen2.5:14b",
    )
    crawler = DetailCrawler(settings=settings)

    with patch("src.extractor.detail_crawler.AsyncWebCrawler", return_value=mock_crawler_instance):
        pkg = await crawler.parse_url("https://www.colatour.com.tw/sample", agency_hint="可樂旅遊")

    assert pkg.agency == "可樂旅遊"
    assert pkg.days == 4
    assert pkg.departure_airport == "KHH"
    assert pkg.pricing.adult_twin_price == 38900
    # 確認呼叫 arun 時有注入 EXPAND_TABS_JS
    call_kwargs = mock_crawler_instance.arun.call_args.kwargs
    assert call_kwargs["config"].js_code == EXPAND_TABS_JS


def test_parse_price_twd():
    assert parse_price_twd("NT$12,450") == 12450
    assert parse_price_twd("TWD 18,900") == 18900
    assert parse_price_twd(15000) == 15000
    assert parse_price_twd(0) is None
    assert parse_price_twd(None) is None
    assert parse_price_twd("價格電洽") is None


@pytest.mark.asyncio
async def test_flight_benchmark_client_and_db_save(tmp_path):
    db_file = str(tmp_path / "test_flights.db")
    await init_db(db_file)
    repo = TourRepository(db_file)
    client = FlightBenchmarkClient(repository=repo)

    mock_flights_resp = [
        SimpleNamespace(
            type="Round trip",
            airlines=["China Airlines"],
            price=16500,
            flights=[SimpleNamespace(departure="08:15", arrival="10:45", duration=90)],
        ),
        SimpleNamespace(
            type="Round trip",
            airlines=["EVA Air"],
            price=18200,
            flights=[SimpleNamespace(departure="09:40", arrival="12:10", duration=90)],
        ),
        SimpleNamespace(
            type="Round trip",
            airlines=["Starlux"],
            price="NT$19,800",
            flights=[SimpleNamespace(departure="11:00", arrival="13:30", duration=90)],
        ),
    ]

    with patch("src.extractor.flight_benchmark.get_flights", return_value=mock_flights_resp):
        results = await client.fetch_all_taiwan_oka_benchmarks(
            depart_date="2027-02-04",
            return_date="2027-02-08",
        )

    assert "TPE" in results
    assert "KHH" in results
    assert results["TPE"].min_price_twd == 16500
    assert results["TPE"].median_price_twd == 18200
    assert results["TPE"].flight_count == 3

    saved_tpe = await repo.get_latest_flight_benchmark("TPE", "OKA", "2027-02-04")
    assert saved_tpe is not None
    assert saved_tpe["min_price_twd"] == 16500
    assert saved_tpe["median_price_twd"] == 18200
