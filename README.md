---
title: "2027 春節沖繩旅遊跨社比價與監控系統 (okinawa-lny2027-tracker)"
aliases:
  - README
  - 專案說明
  - okinawa-lny2027-tracker
tags:
  - project-root
  - documentation
  - overview
  - okinawa-2027
type: documentation
created: 2026-11-19
---

# 2027 春節沖繩旅遊跨社比價與監控系統 (`okinawa-lny2027-tracker`)

> 🧭 **知識圖譜導航**：[[00_Index|🗺️ 00_Index (知識圖譜總索引 MOC)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作架構]] ｜ [[docs/api_spec|🔌 API 與資料規格]] ｜ [[ConversationRecord|📝 對話紀錄]] ｜ [[REMINDER|⚠️ 提醒事項]]

自動化追蹤 **2027 年農曆春節區間（2027-02-01 至 2027-02-14）** 臺灣五大旅行社（可樂、東南、雄獅、山富、世邦）的沖繩 5 天（含）以下團體行程與同期 Google Flights 直飛機票基準價，並依自訂家族成員結構計算真實總預算與每日異常告警。

---

## 🗺️ 系統知識圖譜索引 (Knowledge Graph)

本專案全面支援 Obsidian 知識圖譜導航與雙向鏈結，請優先參閱 [[00_Index|00_Index (知識圖譜總索引 MOC)]] 探索整體架構關聯。

---

## ⚙️ 技術架構

| 層級 | 技術 | 關聯文檔 |
|------|------|---------|
| 後端 / API | Python 3.11+、FastAPI + Uvicorn | [[docs/api_spec]] |
| 爬蟲與瀏覽器 | `crawl4ai>=0.9.0`、Playwright (Chromium)、`httpx`、`fast-flights>=3.1.0` | [[skills/okinawa-discovery/SKILL]], [[skills/okinawa-extractor/SKILL]] |
| 資料模型與設定 | Pydantic v2、PyYAML | [[2027_TravelLtinerary]] |
| 資料庫 | SQLite 3 (`aiosqlite` / `sqlite3`) | [[docs/api_spec]] |
| LLM 解析 | Gemini API (`gemini/gemini-2.5-flash`) 或 Ollama (`ollama/qwen2.5:14b`) | [[skills/okinawa-extractor/SKILL]] |
| 預算與告警 | 家族計價引擎、小費乘算、佔床規則、異動偵測 | [[skills/okinawa-calculator/SKILL]] |
| 容器與排程 | Docker、Docker Compose、n8n (HTTP Request 觸發) | [[2027_TravelLtinerary]] |

---

## 🤖 AI 多代理協作

本專案使用 AI 多代理協作架構（Dual-Model Routing Workflow），詳見 [[AGENTS|AGENTS.md (AI 多代理架構與路由手冊)]]。

- **agent-orchestrator** (Pro): 任務拆解、DAG 排程與跨層協調
- **agent-backend** (Flash): FastAPI、爬蟲 Adapter、Crawl4AI、預算引擎實作
- **agent-database** (Flash): SQLite 結構與 Repository 實作
- **agent-qa** (Flash): pytest 單元測試與封包檢驗
- **agent-docs** (Flash): 規格文件、api_spec.md 與 Obsidian 圖譜維護

---

## 📚 開發與規格規範

- **知識總索引 (MOC)**：[[00_Index|00_Index.md]] / [[MOC|MOC.md]]
- **系統計畫規格書**：[[2027_TravelLtinerary|2027_TravelLtinerary.md]]
- **API 與資料交互規格**：[[docs/api_spec|docs/api_spec.md]]
- **模組一 (清單撈取)**：[[skills/okinawa-discovery/SKILL|skills/okinawa-discovery/SKILL.md]]
- **模組二 (詳情解析與機票)**：[[skills/okinawa-extractor/SKILL|skills/okinawa-extractor/SKILL.md]]
- **模組三 (預算試算與告警)**：[[skills/okinawa-calculator/SKILL|skills/okinawa-calculator/SKILL.md]]
- **專案對話與歷程**：[[ConversationRecord|ConversationRecord.md]]
- **關閉提醒事項**：[[REMINDER|REMINDER.md]]
