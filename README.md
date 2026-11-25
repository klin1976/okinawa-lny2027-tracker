---
title: "通用多目的地旅遊跨社比價與異動監控雷達 (travel-radar)"
aliases:
  - README
  - 專案說明
  - travel-radar
  - okinawa-lny2027-tracker
tags:
  - project-root
  - documentation
  - overview
  - travel-radar
type: documentation
created: 2026-11-19
updated: 2026-11-21
---

# 通用多目的地旅遊跨社比價與異動監控雷達 (`travel-radar`)

> 🧭 **知識圖譜導航**：[[00_Index|🗺️ 00_Index (知識圖譜總索引 MOC)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作架構]] ｜ [[docs/api_spec|🔌 API 與資料規格]] ｜ [[PROJECT_COCKPIT|🛸 專案駕駛艙]] ｜ [[ConversationRecord|📝 對話紀錄]]

參考 [`klin1976/tech-training-radar`](https://github.com/klin1976/tech-training-radar) 的 **Zero-Infra 雷達架構**，將原本限定 2027 春節沖繩的比價系統全面重構為 **不限定國家、地點、天數（1~30 天）與季節** 的多目的地旅遊跨社比價與異動監控雷達。支援台灣五大旅行社（雄獅、山富、世邦、可樂、東南）雙模式爬取、Google Flights 同期機票基準、依國別差異化調整的家族真實總預算試算、0~100 綜合規則評分、以及 Discord / Telegram 雙管道即時告警與每日健康心跳回報。

---

## 🚀 Zero-Infra 快速上手 (CLI-First)

### 1. 本機安裝與資料庫初始化
```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

# 初始化或自動遷移 SQLite 資料庫 (預設 data/radar.db)
python -m src.cli init-db
```

### 2. 常用 CLI 指令
```bash
# 查看目前設定的所有多目的地旅遊專案 (config/trips/*.yaml)
python -m src.cli list-trips

# 執行所有已啟用 (enabled: true) 專案的巡檢、評分、差異比對與雙管道推播
python -m src.cli scan --all --notify --digest

# 針對特定國家專案掃描（支援無 LLM 的 Zero-Infra 快速模式與關閉 Playwright）
python -m src.cli scan --trip europe_summer2027 --skip-llm --no-playwright

# 查詢過去 24 小時內的價格、機位與狀態異動歷史
python -m src.cli diff --hours 24

# 單一旅行社獨立爬蟲除錯（不寫入資料庫）
python -m src.cli test-scrape --agency lion --trip okinawa_lny2027
```

### 3. 網頁版雷達儀表板（靜態 Pages + 本機 Live 雙模式）
```bash
# 模式 A：本機啟動即時 Web 儀表板（http://127.0.0.1:8000）
# 支援唯讀看盤免 Key、即時觸發掃描與單頁網址試算（需在網頁輸入 .env 的 API_KEY）
python -m src.cli serve

# 模式 B：匯出靜態儀表板資料（web/data/dashboard.json），供 GitHub Pages 免費代管瀏覽
python -m src.cli build-web
# 或於掃描時自動刷新靜態資料：
python -m src.cli scan --all --build-web
```

> 💡 若將 Repository 設為 Public（或具備 GitHub Pro），於 GitHub **Settings → Pages → Build and deployment → Source** 選擇 **GitHub Actions**，每次排程巡檢後會自動部署靜態網頁。

### 4. 手機網頁雲端觸發 GitHub Actions 抓團（Fine-grained PAT 3 步驟）
在公開的 GitHub Pages 網頁（`STATIC SNAPSHOT` 模式）可免開本機電腦，直接觸發 `.github/workflows/cloud_scan.yml` 抓取任意國家／地區：
1. 至 GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**。
2. **Repository access** 選 **Only select repositories**（僅選本專案），**Permissions → Repository permissions → Actions** 設為 **Read and write**。
3. 開啟 GitHub Pages 網頁點右上角 **「🔑 雲端 Token」** 貼上並驗證儲存後，即可直接選地區點擊 **「☁️ 雲端抓團」**，約 1~2 分鐘自動抓團、寫入 `data/radar.db` 並刷新網頁。

---

## 🌍 新增旅遊目的地教學 (`config/trips/*.yaml`)

在 `config/trips/` 下新增任意 YAML（系統隨附 `okinawa_lny2027.yaml`、`hokkaido_winter2027.yaml`、`korea_spring2027.yaml`、`europe_summer2027.yaml` 四種範例），設定 `enabled: true` 即可納入自動巡檢：

- `destination.search_keywords` / `exclude_keywords`：控制搜尋關鍵字與標題排除（如郵輪、自由行）。
- `schedule.min_days` ~ `max_days`：支援 `1 ~ 30` 天各類短中長程行程。
- `flight_benchmark.max_stops`：短程設 `0`（直飛），歐美長程可設 `1`（轉機）。
- `party.child_bed_age_threshold`：支援依各國飯店規定調整（日本/韓國設 `6`，歐美可設 `12`）。
- `party.tip_per_day_twd` / `target_total_budget_twd`：覆寫該國家每日小費標準與家族目標總預算。

---

## 🤖 GitHub Actions 全自動排程（零伺服器成本）

`.github/workflows/monitor.yml` 預設於每日台灣時間 `09:17` 與 `21:17` 自動執行巡檢並將更新後的 `data/radar.db` Commit 回儲存庫。請至 GitHub Repo 的 **Settings → Secrets and variables → Actions** 設定以下機密變數（推播依設定自動啟用，皆可單獨或同時使用）：

| Secret 名稱 | 說明 | 必填 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | Discord 頻道 Webhook URL（發送 Rich Embed 警報與每日摘要） | 選填 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 選填 |
| `TELEGRAM_CHAT_ID` | Telegram 接收群組或個人 Chat ID | 選填 |
| `GEMINI_API_KEY` | Gemini API 金鑰（未設定時自動跳過 LLM 詳情解析，僅執行清單與試算） | 選填 |

---

## ⚙️ 技術架構（四層單向雷達管線 + 選配 FastAPI）

| 層級 | 模組與技術 | 說明 |
|---|---|---|
| CLI 入口 | `src/cli.py` | `init-db` / `list-trips` / `scan` / `diff` / `test-scrape` / `build-web` / `serve` |
| 上游擷取 | `src/discovery/` (`httpx` + Playwright 混合) | `httpx` Direct XHR/SSR 優先，必要時降級 Playwright |
| 詳情與機票 | `src/extractor/` (`Crawl4AI` + `fast-flights`) | 動態國家 Prompt、7 天 LLM 快取、多航線與轉機基準 |
| 試算與評估 | `src/calculator/` + `src/evaluator/` | `BudgetEngine`、`RuleEvaluator` (0~100 評分)、`AlertDetector`、`DiffEngine` |
| 持久化與審計 | `src/db/` (SQLite WAL + `checkpoint_db`) | `tours`、`price_snapshots` (事件驅動)、`flight_benchmarks`、`alert_logs`、`scan_history` |
| 通知與報表 | `src/notifier/` (`Rich` / `tabulate` + Webhook) | Discord + Telegram 緊急警報與 `--digest` 每日健康心跳 |
| 網頁與 API | `web/` + `src/web/` + `src/main.py` | 雙模式深色雷達儀表板（GitHub Pages 靜態 JSON + 本機 FastAPI Live API） |
