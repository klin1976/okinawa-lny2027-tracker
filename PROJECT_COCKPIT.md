---
project: okinawa-lny2027-tracker
type: project-cockpit
created: '2026-11-19'
status: active
repo: F:/Antigravity/TravelLtinerary
github: https://github.com/klin1976/okinawa-lny2027-tracker
branch: main
updated: '2026-11-19'
tags:
  - project
  - antigravity
  - python
  - playwright
  - crawl4ai
  - sqlite
  - fastapi
  - n8n
  - okinawa-2027
---

# 🛫 2027 春節沖繩旅遊跨社比價與監控系統 (okinawa-lny2027-tracker) 專案駕駛艙

> **快捷導航**：[[00_Index|🗺️ 00_Index (MOC 總索引)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理手冊]] ｜ [[docs/api_spec|🔌 API 規格文件]] ｜ [[ConversationRecord|📝 對話紀錄]] ｜ [[REMINDER|⚠️ 提醒事項]]

---

## 📌 專案目的
針對 **2027 年農曆春節區間（2027-02-01 至 2027-02-14，核心連假 2/4～2/10）**，自動追蹤臺灣五大旅行社（可樂、東南、雄獅、山富、世邦）的沖繩 5 天（含）以下行程與同期 Google Flights 直飛機票基準價，並依自訂家族成員結構計算真實總預算、機位充足度與每日異常告警。

---

## 🧭 目前狀態
- **本機路徑**：`F:/Antigravity/TravelLtinerary`
- **Git 分支**：`main` (與遠端同步)
- **GitHub 儲存庫**：[klin1976/okinawa-lny2027-tracker](https://github.com/klin1976/okinawa-lny2027-tracker) (Private)
- **架構模式**：`API_ONLY` (FastAPI + Playwright + SQLite + n8n)
- **當前里程碑**：**Phase 1 完成**（架構骨架、Schema、SQLite 4 張表與 Repository、家族預算/告警引擎、15 項單元測試全數 PASS）

---

## 🚀 已完成里程碑與核心功能

### 1. 資料模型與設定檔
- **Pydantic v2 Schema**：`OkinawaTourPackage`（詳情模型）、`TourListItem`（清單模型）、`FamilyBudgetResult`（預算試算）、`AlertEvent`（異動告警）。
- **外部化配置**：
  - `config/agencies.yaml`：五大旅行社搜尋過濾參數與反爬蟲延遲。
  - `config/family_profile.yaml`：成員年齡、日本滿 6 歲強制佔床、小費與三人房偏好、告警門檻與評分權重。

### 2. SQLite 資料庫與 Repository (`src/db/`)
- 4 張核心資料表：`tours`、`price_snapshots`、`flight_benchmarks`、`alert_logs`。
- 支援增量解析比對（未滿 7 天沿用舊詳情）、每日價格與機位快照寫入、24 小時告警去重。

### 3. 模組三：家族真實總預算與告警引擎 (`src/calculator/`)
- **`budget_engine.py`**：日本滿 6 歲強制佔床防護、每日小費乘算、奇數佔床三人房/單人房差檢核、全家機位充足度檢核、長輩警示與免稅購物站標註、綜合推薦評分。
- **`alert_detector.py`**：降價告警 (`PRICE_DROP`)、低機位預警 (`LOW_SEATS`)、機位危急 (`SEAT_CRITICAL`)、新團分級 (`NEW_HIGH_VALUE_TOUR` / `NEW_TOUR`)。

### 4. 驗收測試 (`tests/`)
- `tests/test_budget_engine.py` (7 passed)
- `tests/test_alert_detector.py` (6 passed)
- `tests/test_repository.py` (2 passed)
- 總計 **15/15 測試全數通過 (Exit Code 0)**。

---

## 🗺️ 專案 Skills 與模組規範
- [[skills/okinawa-discovery/SKILL|okinawa-discovery]]：五大旅行社雙模式（Direct XHR + Playwright Network Interception）清單撈取規範。
- [[skills/okinawa-extractor/SKILL|okinawa-extractor]]：Crawl4AI + LLM（Gemini/Ollama）兩段式增量解析與 fast-flights 基準規範。
- [[skills/okinawa-calculator/SKILL|okinawa-calculator]]：家族預算試算公式、佔床規則與告警偵測規範。
