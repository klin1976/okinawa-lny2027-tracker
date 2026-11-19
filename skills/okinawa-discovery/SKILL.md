---
name: okinawa-discovery
description: >
  模組一：五大旅行社（雄獅、可樂、東南、山富、世邦）上游清單自動撈取引擎規範。
  採用雙模式容錯架構（Direct XHR Replay + Playwright Network Interception），輸出統一 TourListItem。
aliases:
  - okinawa-discovery
  - 模組一：清單自動撈取引擎
tags:
  - skill
  - crawler
  - playwright
  - discovery
  - okinawa-2027
type: skill
created: 2026-11-19
---

# 模組一：上游清單自動撈取引擎 (`src/discovery/`) 開發規範

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作]] ｜ [[docs/api_spec|🔌 API規格書]]  
> **關聯模組**：[[skills/okinawa-extractor/SKILL|🧠 模組二：okinawa-extractor]] ｜ [[skills/okinawa-calculator/SKILL|💰 模組三：okinawa-calculator]]

---

## 核心邏輯

- 所有旅行社 Adapter 必須繼承 `BaseAgencyAdapter`，並實作雙模式擷取：
  1. **Mode A — Direct XHR Replay**（優先，`< 2` 秒）：透過 `httpx.AsyncClient` 直接發送搜尋 API 請求。
  2. **Mode B — Playwright Network Interception**（備援，HTTP 403/WAF 或欄位變更時自動降級）：透過無頭 Chromium 攔截 `application/json` XHR 回應，或於伺服器渲染頁面抽取 DOM。
- 所有輸出必須正規化為 `TourListItem` (`src/schemas/discovery_schema.py`)，並計算 `raw_hash` 用於增量比對。
- 共同過濾條件（讀取自 `config/agencies.yaml`）：目的地關鍵字 `沖繩` / `琉球` / `OKA`、出發日期 `2027-02-01` ～ `2027-02-14`、天數 `days <= 5`。
- 比對完成後將新團次送入 [[skills/okinawa-extractor/SKILL|模組二：詳情頁結構化解析]]。

## 已知地雷 / Gotchas

- 各旅行社併發度上限為 `1`，翻頁間隔需隨機延遲 `2.0 ~ 4.5` 秒（Jitter）。
- 單一旅行社抓取失敗不得中斷其餘四家執行，須捕捉例外並寫入錯誤日誌回報給 n8n。
- 開發階段應先使用 `scripts/inspect_xhr.py --agency <name> --url "<url>"` 傾印 XHR 封包至 `logs/xhr_dump/`，切勿猜測 API 欄位。

## 檔案範圍

| 檔案 / 目錄 | 說明 | 關聯文檔 |
|------------|------|---------|
| `src/discovery/base_adapter.py` | 抽象基底類別（雙模式切換與重試） | [[2027_TravelLtinerary]] |
| `src/discovery/lion_adapter.py` | 雄獅旅遊 Adapter | [[AGENTS]] `agent-backend` |
| `src/discovery/cola_adapter.py` | 可樂旅遊 Adapter | [[AGENTS]] `agent-backend` |
| `src/discovery/settour_adapter.py` | 東南旅遊 Adapter | [[AGENTS]] `agent-backend` |
| `src/discovery/richmont_adapter.py` | 山富旅遊 Adapter | [[AGENTS]] `agent-backend` |
| `src/discovery/fourp_adapter.py` | 世邦旅遊 Adapter | [[AGENTS]] `agent-backend` |
| `src/schemas/discovery_schema.py` | `TourListItem` Pydantic 模型 | [[docs/api_spec]] |
| `scripts/inspect_xhr.py` | 開發階段 XHR 攔截輔助工具 | [[AGENTS]] `agent-qa` |
