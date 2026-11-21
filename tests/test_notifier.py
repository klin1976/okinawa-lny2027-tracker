from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.evaluator import DiffEngine
from src.notifier.console import print_diff_report, print_rankings_table, print_recent_diffs
from src.notifier.webhook import send_webhook_digest, send_webhook_notifications
from src.schemas.budget_schema import AlertEvent, CostBreakdown, FamilyBudgetResult, RankedTourResult


def _mock_ranked_tour() -> RankedTourResult:
    uid = "雄獅旅遊:EU01:2027-07-10"
    return RankedTourResult(
        trip_id="europe_summer2027",
        tour_uid=uid,
        agency="雄獅旅遊",
        tour_name="《奧捷夢幻》維也納+布拉格12日",
        departure_date="2027-07-10",
        days=12,
        departure_airport="TPE",
        adult_price=88000,
        seats_available=14,
        status="保證出團",
        detail_url="https://example.com/eu01?a=1&b=2",
        budget=FamilyBudgetResult(
            tour_uid=uid,
            grand_total_twd=880000,
            avg_cost_per_person_twd=88000,
            total_family_members=10,
            total_flight_seats_needed=10,
            total_beds_needed=7,
            seat_status="SUFFICIENT",
            breakdown=CostBreakdown(),
        ),
        composite_score=92.5,
        tags=["保證出團", "無購物"],
    )


def test_webhook_notifications_dual_channels_and_disabled(monkeypatch):
    alerts = [
        AlertEvent(
            alert_key="PRICE_DROP:test:1",
            alert_type="PRICE_DROP",
            tour_uid="雄獅旅遊:EU01:2027-07-10",
            priority="高",
            message="團費大降 3,000 元 <優惠>",
        )
    ]

    # 1. 未設定任何環境變數時不應發送且不報錯
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with patch("httpx.Client.post") as mock_post:
        res_none = send_webhook_notifications(alerts, trip_name="奧捷團")
    assert res_none == {"discord": False, "telegram": False}
    mock_post.assert_not_called()

    # 2. 同時設定 Discord 與 Telegram 時兩者皆發送
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-token-123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999888")

    mock_resp = MagicMock(status_code=200, text="ok")
    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res_both = send_webhook_notifications(alerts, trip_name="2027 歐洲奧捷團")

    assert res_both == {"discord": True, "telegram": True}
    assert mock_post.call_count == 2
    urls_called = [call.args[0] for call in mock_post.call_args_list]
    assert "https://discord.com/api/webhooks/test" in urls_called
    assert "https://api.telegram.org/bottg-token-123/sendMessage" in urls_called

    # 驗證 Telegram HTML 跳脫處理
    tg_payload = mock_post.call_args_list[1].kwargs["json"]
    assert tg_payload["parse_mode"] == "HTML"
    assert "&lt;優惠&gt;" in tg_payload["text"]


def test_webhook_digest_single_channel_and_console_outputs(monkeypatch):
    rankings = [_mock_ranked_tour()]
    stats = {"雄獅旅遊": {"count": 12, "status": "OK"}}

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/digest")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    mock_resp = MagicMock(status_code=204, text="")
    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res = send_webhook_digest(
            rankings=rankings,
            agency_stats=stats,
            trip_name="2027 暑假歐洲團",
            destination_desc="歐洲 奧捷/德瑞",
            diff_summary={"new_count": 0, "price_drop_count": 0, "seats_released_count": 0},
        )
    assert res == {"discord": True, "telegram": False}
    assert mock_post.call_count == 1
    embed = mock_post.call_args.kwargs["json"]["embeds"][0]
    assert "每日巡檢健康回報" in embed["title"]
    assert "NT$880,000" in embed["fields"][2]["value"]

    # Console 輸出不應拋錯
    print_rankings_table(rankings, title="測試排行榜")
    print_diff_report(DiffEngine.build_report([]))
    print_recent_diffs(
        [
            {
                "captured_at": "2027-07-01T09:00:00",
                "trip_id": "europe_summer2027",
                "agency": "雄獅旅遊",
                "tour_name": "奧捷12日",
                "departure_date": "2027-07-10",
                "old_price": 91000,
                "new_price": 88000,
                "old_seats": 10,
                "new_seats": 14,
                "old_status": "候補",
                "new_status": "保證出團",
            }
        ],
        hours=24,
    )
