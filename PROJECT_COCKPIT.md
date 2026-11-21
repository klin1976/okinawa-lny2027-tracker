---
project: travel-radar
type: project-cockpit
created: '2026-11-19'
status: active
repo: F:/Antigravity/TravelLtinerary
github: https://github.com/klin1976/okinawa-lny2027-tracker
branch: main
updated: '2026-11-21'
tags:
  - project
  - antigravity
  - python
  - playwright
  - crawl4ai
  - sqlite
  - fastapi
  - github-actions
  - travel-radar
---

# 🛫 通用多目的地旅遊跨社比價與異動監控雷達 (`travel-radar`) 專案駕駛艙

> **快捷導航**：[[00_Index|🗺️ 00_Index (MOC 總索引)]] ｜ [[README|📘 README]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理手冊]] ｜ [[docs/api_spec|🔌 API 規格文件]] ｜ [[ConversationRecord|📝 對話紀錄]] ｜ [[REMINDER|⚠️ 提醒事項]]

---

## 📌 專案目的
參考 [`klin1976/tech-training-radar`](https://github.com/klin1976/tech-training-radar) 的 Zero-Infra 雷達架構，打造**不限定旅遊國家、地點、天數（1~30 天）與季節**的通用旅遊團費比價與異動監控雷達。支援五大旅行社（雄獅、山富、世邦、可樂、東南）雙模式爬取、Google Flights 多國直飛／轉機機票基準、國別差異化家族總預算、0~100 綜合規則評分、GitHub Actions 自動巡檢回寫 SQLite，以及 Discord / Telegram 雙管道緊急告警與每日健康心跳。

---

## 🧭 目前狀態
- **本機路徑**：`F:/Antigravity/TravelLtinerary`
- **Git 分支**：`main`
- **GitHub 儲存庫**：[klin1976/okinawa-lny2027-tracker](https://github.com/klin1976/okinawa-lny2027-tracker) (Private)
- **主力運作架構**：**Zero-Infra CLI-First (`src/cli.py`) + GitHub Actions Cron + SQLite (`data/radar.db`) Commit 回 Repo**（保留 FastAPI `src/main.py` 與 Docker 作為選配 Web/API 層）
- **當前里程碑**：**Phase 5 完成（通用化多目的地重構 & Zero-Infra 雷達落地）**

---

## 🚀 已完成里程碑與核心功能

### 1. 多目的地專案設定與通用 Schema (`config/trips/*.yaml`, `src/schemas/`)
- **專案化配置 (`TripConfig`)**：支援同時定義多國旅遊追蹤專案，目前內建 4 份範例：
  - `config/trips/okinawa_lny2027.yaml` (`enabled: true`，日本沖繩 4~5 日，佔床門檻 6 歲，直飛)
  - `config/trips/hokkaido_winter2027.yaml` (`enabled: false`，日本北海道 5~7 日，佔床門檻 6 歲，直飛)
  - `config/trips/korea_spring2027.yaml` (`enabled: false`，韓國首爾/釜山 4~6 日，人蔘/保肝購物站偵測)
  - `config/trips/europe_summer2027.yaml` (`enabled: false`，歐洲奧捷/德瑞 9~13 日，佔床門檻 12 歲，`max_stops: 1` 轉機支援)
- **Pydantic v2 通用模型**：`TourPackage`（保留 `OkinawaTourPackage` 別名相容）、`TourListItem`（1~30 天 + `trip_id`）、`FamilyBudgetResult`、`AlertEvent`（新增 `SEATS_RELEASED`、`GUARANTEED_DEPARTURE`）。

### 2. SQLite 演進、自動遷移與事件驅動快照 (`src/db/`)
- **資料表**：`tours`（含 `trip_id`, `destination_country`, `destination_airport`, `score`, `tags_json`）、`price_snapshots`（事件驅動寫入）、`flight_benchmarks`、`alert_logs`、`scan_history`（巡檢審計表）。
- **無痛遷移與 WAL Checkpoint**：`init-db` 自動 `ALTER TABLE` 升級舊庫並回填 `trip_id`；`checkpoint_db` 確保 Git Commit `data/radar.db` 前合併所有異動。

### 3. 混合爬蟲、動態詳情解析與多航線機票基準 (`src/discovery/`, `src/extractor/`)
- **五大旅行社 Adapter 全面解耦**：移除沖繩與 5 天寫死邏輯，改由 `TripConfig` 注入多關鍵字迴圈搜尋、排除字詞與天數區間；採 `httpx` Direct XHR/SSR 優先，支援 `--no-playwright` 關閉瀏覽器降級。
- **詳情解析與機票**：`DetailCrawler` 支援動態國家 Prompt；`FlightBenchmarkClient.fetch_route_benchmarks()` 支援任意國家機場與轉機設定。

### 4. 雙層評估、差異引擎與雙管道推播 (`src/calculator/`, `src/evaluator/`, `src/notifier/`)
- **`BudgetEngine`**：兒童佔床年齡門檻參數化（日本/韓國 6 歲 vs 歐洲 12 歲），全面去地域化。
- **`RuleEvaluator` & `DiffEngine`**：輸出 0~100 評分、規則通過/失敗明細與標籤，並彙整 `SEATS_RELEASED`、`GUARANTEED_DEPARTURE`、`PRICE_DROP` 等差異報告。
- **`src/notifier/`**：終端支援 `Rich → tabulate → plain text` 優雅降級；Webhook 支援 **Discord Rich Embed** 與 **Telegram Bot (HTML 安全跳脫)** 雙管道自動切換，提供緊急警報與 `--digest` 每日健康心跳。

### 5. CLI 入口、GitHub Actions 與 FastAPI 選配層 (`src/cli.py`, `.github/workflows/monitor.yml`, `src/main.py`)
- **CLI 子指令**：`init-db`、`list-trips`、`scan`、`diff`、`test-scrape`。
- **GitHub Actions**：每日兩次 (`cron: '17 1,13 * * *'`) + `workflow_dispatch` 手動觸發，自動掃描、通知並 Commit `data/radar.db` 回 Repo。
- **FastAPI 服務**：補齊 `GET /api/v1/trips` 與所有端點 `?trip_id=` 支援，並完全相容既有 API 契約。
