from __future__ import annotations

import html
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from src.schemas.budget_schema import AlertEvent, RankedTourResult

logger = logging.getLogger(__name__)

URGENT_ALERT_TYPES = {
    "PRICE_DROP",
    "SEATS_RELEASED",
    "GUARANTEED_DEPARTURE",
    "NEW_HIGH_VALUE_TOUR",
    "NEW_TOUR",
    "SEAT_CRITICAL",
    "LOW_SEATS",
}


class WebhookNotifier:
    """雙管道推播發送器：同時支援 Discord Webhook (Rich Embed) 與 Telegram Bot。"""

    ALERT_COLORS = {
        "PRICE_DROP": 0x2ECC71,
        "SEATS_RELEASED": 0x1ABC9C,
        "GUARANTEED_DEPARTURE": 0x3498DB,
        "NEW_HIGH_VALUE_TOUR": 0x9B59B6,
        "NEW_TOUR": 0x95A5A6,
        "SEAT_CRITICAL": 0xE74C3C,
        "LOW_SEATS": 0xF39C12,
        "AGENCY_CRAWL_ERROR": 0x7F8C8D,
    }

    @classmethod
    def send_discord_alerts(
        cls,
        alerts: List[AlertEvent],
        trip_name: str,
        webhook_url: str,
        max_embeds: int = 10,
    ) -> bool:
        if not alerts:
            return False

        embeds: List[Dict[str, Any]] = []
        for ev in alerts[:max_embeds]:
            color = cls.ALERT_COLORS.get(ev.alert_type, 0x3498DB)
            fields = [
                {"name": "專案", "value": trip_name, "inline": True},
                {"name": "事件類型", "value": ev.alert_type, "inline": True},
                {"name": "優先級", "value": ev.priority, "inline": True},
            ]
            if ev.tour_uid:
                fields.append({"name": "團次識別碼", "value": ev.tour_uid, "inline": False})

            embeds.append(
                {
                    "title": f"🔔 【旅遊雷達警報】{ev.alert_type}",
                    "description": ev.message,
                    "color": color,
                    "fields": fields,
                    "footer": {"text": "Travel Radar 通用旅遊比價雷達"},
                }
            )

        content_note = (
            f"⚠️ 共有 {len(alerts)} 則異動告警，以下顯示前 {max_embeds} 則："
            if len(alerts) > max_embeds
            else None
        )
        payload: Dict[str, Any] = {
            "username": "旅遊比價巡檢雷達",
            "embeds": embeds,
        }
        if content_note:
            payload["content"] = content_note

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                logger.info("[Webhook] Discord 緊急告警推播成功 (%d 則)", len(embeds))
                return True
            logger.warning("[Webhook] Discord 回傳狀態碼 %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("[Webhook] 發送 Discord 告警失敗: %s", exc)
        return False

    @classmethod
    def send_telegram_alerts(
        cls,
        alerts: List[AlertEvent],
        trip_name: str,
        bot_token: str,
        chat_id: str,
        max_items: int = 10,
    ) -> bool:
        if not alerts:
            return False

        lines = [f"🚨 <b>【旅遊比價雷達警報】{html.escape(trip_name)}</b>", ""]
        for idx, ev in enumerate(alerts[:max_items], 1):
            uid_part = f" (<code>{html.escape(ev.tour_uid)}</code>)" if ev.tour_uid else ""
            lines.append(
                f"{idx}. <b>[{html.escape(ev.alert_type)}]</b>{uid_part}\n"
                f"   {html.escape(ev.message)}"
            )
        if len(alerts) > max_items:
            lines.append(f"\n... 另有 {len(alerts) - max_items} 則異動未列出")

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "\n".join(lines),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("[Webhook] Telegram 緊急告警推播成功 (%d 則)", min(len(alerts), max_items))
                return True
            logger.warning("[Webhook] Telegram 回傳狀態碼 %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("[Webhook] 發送 Telegram 告警失敗: %s", exc)
        return False

    @classmethod
    def send_discord_digest(
        cls,
        rankings: List[RankedTourResult],
        agency_stats: Dict[str, Any],
        trip_name: str,
        destination_desc: str,
        webhook_url: str,
        diff_summary: Optional[Dict[str, int]] = None,
    ) -> bool:
        top_5 = rankings[:5]
        if top_5:
            lines = []
            for idx, r in enumerate(top_5, 1):
                short_name = r.tour_name[:24] + ("..." if len(r.tour_name) > 24 else "")
                seats = f"{r.seats_available}席" if r.seats_available is not None else r.status
                lines.append(
                    f"**{idx}.** [{r.agency}] [{short_name}]({r.detail_url}) "
                    f"｜ `{r.departure_date}` `{r.days}日` ｜ 家族總價 **NT${r.budget.grand_total_twd:,}** "
                    f"｜ ⭐{r.composite_score:.1f} ({seats})"
                )
            rankings_desc = "\n".join(lines)
        else:
            rankings_desc = "目前尚無符合條件之團體行程，雷達持續監控中。"

        stats_parts = [
            f"{name}: {info.get('count', 0)}筆({info.get('status', 'OK')})"
            for name, info in agency_stats.items()
        ]
        stats_line = " ｜ ".join(stats_parts) if stats_parts else "尚無爬蟲統計"

        summary = diff_summary or {}
        diff_line = (
            f"新團 {summary.get('new_count', 0)} ｜ "
            f"降價 {summary.get('price_drop_count', 0)} ｜ "
            f"釋出 {summary.get('seats_released_count', 0)}"
        )

        embed = {
            "title": f"🟢 【每日巡檢健康回報】{trip_name}",
            "description": f"雷達狀態：系統在線、巡檢正常 ✅\n目的地：**{destination_desc}**",
            "color": 0x2ECC71,
            "fields": [
                {"name": "🕷️ 各旅行社巡檢狀態", "value": stats_line, "inline": False},
                {"name": "📊 今日異動摘要", "value": diff_line, "inline": False},
                {"name": "🏆 Top 5 家族推薦排行", "value": rankings_desc, "inline": False},
            ],
            "footer": {"text": "Travel Radar 通用旅遊比價雷達 — 每日健康心跳"},
        }
        payload = {
            "username": "旅遊比價巡檢雷達",
            "embeds": [embed],
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                logger.info("[Webhook] Discord 每日健康回報發送成功 (%s)", trip_name)
                return True
            logger.warning("[Webhook] Discord Digest 回傳狀態碼 %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("[Webhook] 發送 Discord Digest 失敗: %s", exc)
        return False

    @classmethod
    def send_telegram_digest(
        cls,
        rankings: List[RankedTourResult],
        agency_stats: Dict[str, Any],
        trip_name: str,
        destination_desc: str,
        bot_token: str,
        chat_id: str,
        diff_summary: Optional[Dict[str, int]] = None,
    ) -> bool:
        top_5 = rankings[:5]
        if top_5:
            lines = []
            for idx, r in enumerate(top_5, 1):
                short_name = html.escape(r.tour_name[:24] + ("..." if len(r.tour_name) > 24 else ""))
                url = html.escape(r.detail_url, quote=True)
                seats = f"{r.seats_available}席" if r.seats_available is not None else html.escape(r.status)
                lines.append(
                    f"{idx}. [{html.escape(r.agency)}] <a href=\"{url}\">{short_name}</a>\n"
                    f"   📅 {html.escape(r.departure_date)} ({r.days}日) | "
                    f"💰 NT${r.budget.grand_total_twd:,} | ⭐{r.composite_score:.1f} ({seats})"
                )
            rankings_block = "\n".join(lines)
        else:
            rankings_block = "目前尚無符合條件之團體行程，雷達持續監控中。"

        stats_parts = [
            f"{html.escape(str(name))}: {info.get('count', 0)}筆({html.escape(str(info.get('status', 'OK')))})"
            for name, info in agency_stats.items()
        ]
        stats_line = " | ".join(stats_parts) if stats_parts else "尚無爬蟲統計"

        summary = diff_summary or {}
        diff_line = (
            f"新團 {summary.get('new_count', 0)} | "
            f"降價 {summary.get('price_drop_count', 0)} | "
            f"釋出 {summary.get('seats_released_count', 0)}"
        )

        text = (
            f"🟢 <b>【旅遊比價雷達】每日巡檢健康回報</b>\n"
            f"📌 專案：<b>{html.escape(trip_name)}</b> ({html.escape(destination_desc)})\n"
            f"🕷️ 旅行社：{stats_line}\n"
            f"📊 異動統計：{diff_line}\n\n"
            f"🏆 <b>Top 5 推薦排行</b>：\n{rankings_block}"
        )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("[Webhook] Telegram 每日健康回報發送成功 (%s)", trip_name)
                return True
            logger.warning("[Webhook] Telegram Digest 回傳狀態碼 %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("[Webhook] 發送 Telegram Digest 失敗: %s", exc)
        return False


def _resolve_channels(
    discord_webhook_url: Optional[str] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    d_url = discord_webhook_url or os.environ.get("DISCORD_WEBHOOK_URL") or None
    tg_token = telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or None
    tg_chat = telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID") or None
    return d_url, tg_token, tg_chat


def send_webhook_notifications(
    alerts: List[AlertEvent],
    trip_name: str = "通用旅遊追蹤專案",
    discord_webhook_url: Optional[str] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    include_ops_errors: bool = False,
) -> Dict[str, bool]:
    """依據環境變數自動切換發送 Discord 與/或 Telegram 緊急告警通知。"""
    target_alerts = [
        a for a in alerts
        if include_ops_errors or a.alert_type in URGENT_ALERT_TYPES
    ]
    if not target_alerts:
        logger.info("[Webhook] 本次巡檢無需推播之緊急異動。")
        return {"discord": False, "telegram": False}

    d_url, tg_token, tg_chat = _resolve_channels(
        discord_webhook_url, telegram_bot_token, telegram_chat_id
    )
    if not d_url and not (tg_token and tg_chat):
        logger.info(
            "[Webhook] 偵測到 %d 則異動告警，但未設定 DISCORD_WEBHOOK_URL 或 TELEGRAM_BOT_TOKEN/CHAT_ID，已略過網路推播。",
            len(target_alerts),
        )
        return {"discord": False, "telegram": False}

    sent = {"discord": False, "telegram": False}
    if d_url:
        sent["discord"] = WebhookNotifier.send_discord_alerts(
            target_alerts, trip_name=trip_name, webhook_url=d_url
        )
    if tg_token and tg_chat:
        sent["telegram"] = WebhookNotifier.send_telegram_alerts(
            target_alerts, trip_name=trip_name, bot_token=tg_token, chat_id=tg_chat
        )
    return sent


def send_webhook_digest(
    rankings: List[RankedTourResult],
    agency_stats: Dict[str, Any],
    trip_name: str = "通用旅遊追蹤專案",
    destination_desc: str = "多目的地旅遊",
    diff_summary: Optional[Dict[str, int]] = None,
    discord_webhook_url: Optional[str] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
) -> Dict[str, bool]:
    """發送每日健康心跳摘要（Heartbeat & Digest）。"""
    d_url, tg_token, tg_chat = _resolve_channels(
        discord_webhook_url, telegram_bot_token, telegram_chat_id
    )
    if not d_url and not (tg_token and tg_chat):
        logger.info(
            "[Webhook] 每日巡檢健康回報已產生 (%s)，但未設定推播環境變數，已略過網路推播。",
            trip_name,
        )
        return {"discord": False, "telegram": False}

    sent = {"discord": False, "telegram": False}
    if d_url:
        sent["discord"] = WebhookNotifier.send_discord_digest(
            rankings=rankings,
            agency_stats=agency_stats,
            trip_name=trip_name,
            destination_desc=destination_desc,
            webhook_url=d_url,
            diff_summary=diff_summary,
        )
    if tg_token and tg_chat:
        sent["telegram"] = WebhookNotifier.send_telegram_digest(
            rankings=rankings,
            agency_stats=agency_stats,
            trip_name=trip_name,
            destination_desc=destination_desc,
            bot_token=tg_token,
            chat_id=tg_chat,
            diff_summary=diff_summary,
        )
    return sent
