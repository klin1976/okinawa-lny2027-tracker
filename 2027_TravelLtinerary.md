---
title: "2027 春節沖繩旅遊跨社比價與監控系統 — 系統計畫規格書"
aliases:
  - 2027_TravelLtinerary
  - 系統計畫規格書
  - TravelLtinerary
tags:
  - specification
  - architecture
  - itinerary
  - okinawa-2027
type: specification
created: 2026-11-19
---

# 2027 春節沖繩旅遊跨社比價與監控系統 — 系統計畫規格書 (`TravelLtinerary.md`)

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC 總索引)]] ｜ [[README|📘 README (專案導覽)]] ｜ [[AGENTS|🤖 AGENTS (多代理協作架構)]] ｜ [[docs/api_spec|🔌 docs/api_spec (API 規格)]] ｜ [[ConversationRecord|📝 對話紀錄]] ｜ [[REMINDER|⚠️ 提醒事項]]

## 重點摘要

* **文件定位**：本規格書可直接置於專案根目錄，交由 **Antigravity** 作為最高指導藍圖，採「分階段里程碑（Phase 1～4）」逐一生成程式碼與驗證。
* **核心節費與穩定設計（兩段式增量抓取）**：每日排程僅透過**模組一（清單 XHR API）**高速更新所有團次的「團費與剩餘機位」；只有遇到**新上架團號**或**超過 7 天未更新**的行程，才觸發 `Crawl4AI + LLM` 解析詳情頁，可省下超過 90% 的 Token 與運算時間。
* **系統整合架構**：將三大模組封裝為單一 **Python FastAPI + Playwright Docker 容器**，搭配本地 **SQLite** 記錄歷史價格與機位快照；外部由 **n8n** 透過標準 HTTP Request 節點排程觸發，並依回傳的異動事件（降價、新團、機位跌破門檻）發送 Telegram／Discord／Email 告警。
* **家族決策引擎**：透過外部設定檔 `config/family_profile.yaml` 定義家庭成員年齡與佔床需求，自動處理日本「滿 6 歲強制佔床」、小費乘算、單人房差、剩餘機位是否足以容納全家，以及長輩陪同與購物站風險標註。

---

## 一、 專案總覽與系統架構

### 1.1 專案目標
建立一套自動化旅遊情報與比價系統，針對 **2027 年農曆春節區間（2027-02-01 至 2027-02-14，核心連假為 2/4～2/10）**，自動追蹤臺灣五大旅行社（可樂、東南、雄獅、山富、世邦）的**沖繩 5 天（含）以下**行程與同期 Google Flights 直飛機票基準價，並依自訂家族成員結構計算真實總預算與每日異常告警。

### 1.2 系統資料流架構

```text
[n8n 每日排程 (Cron: 09:00 / 21:00)]
        │
        ▼ (HTTP POST /api/v1/pipeline/daily-run)
┌──────────────────────────────────────────────────────────────────────┐
│  Docker Container: okinawa-tour-tracker (FastAPI + Playwright)       │
│                                                                      │
│  ┌──────────────────────┐      ┌──────────────────────────────────┐  │
│  │ Module 1: 清單發現引擎 │ ───▶ │ SQLite 狀態比對層 (Delta Check)  │  │
│  │ (5家旅行社 XHR/攔截)  │      │ - 記錄每日價格/機位快照           │  │
│  └──────────────────────┘      │ - 篩選「新團號」送詳情頁解析       │  │
│                                └────────────────┬─────────────────┘  │
│                                                 │ (僅針對新團號)      │
│  ┌──────────────────────┐                       ▼                    │
│  │ fast-flights 基準模組 │      ┌──────────────────────────────────┐  │
│  │ (TPE/KHH <-> OKA)    │      │ Crawl4AI + LLM 詳情頁結構化解析   │  │
│  └──────────┬───────────┘      │ (輸出統一 OkinawaTourPackage JSON)│  │
│             │                  └────────────────┬─────────────────┘  │
│             └─────────────────┬─────────────────┘                    │
│                               ▼                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Module 3: 家族真實總預算試算與評分排行引擎                        │  │
│  │ (讀取 family_profile.yaml + 計算總價/小費/房差/機位檢核/告警事件) │  │
│  └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ (回傳 JSON: alerts[] + top_ranked_tours[])
                                ▼
[n8n 條件分支與通知節點] ──▶ Telegram Bot / Discord / Email / Google Sheets
```

### 1.3 技術堆疊（Tech Stack）
* **執行環境**：Python 3.11+、Docker、Docker Compose
* **Web API 框架**：FastAPI + Uvicorn（供 n8n 呼叫）
* **爬蟲與瀏覽器核心**：`crawl4ai>=0.9.0`、Playwright (Chromium)、`httpx`、`fast-flights>=3.1.0`
* **資料模型與驗證**：Pydantic v2、PyYAML
* **資料庫**：SQLite 3（搭配 `aiosqlite` 或標準 `sqlite3`，單檔好備份，可零痛點掛載 Docker Volume）
* **LLM 供應商**：透過環境變數切換 Gemini API (`gemini/gemini-2.5-flash`) 或地端 Ollama (`ollama/qwen2.5:14b`)

---

## 二、 專案目錄結構規劃

請 Antigravity 嚴格依照以下結構建立專案，保持高內聚、低耦合：

```text
okinawa-lny2027-tracker/
├── TravelLtinerary.md               # 本系統計畫規格書
├── Dockerfile                       # 基於 Playwright Python 官方映像檔
├── docker-compose.yml               # 包含 tracker API 與可選的 n8n 整合設定
├── requirements.txt
├── .env.example                     # GEMINI_API_KEY, OLLAMA_URL, ALERT_THRESHOLD 等
├── config/
│   ├── agencies.yaml                # 五家旅行社搜尋條件、XHR 設定、啟用開關
│   └── family_profile.yaml          # 家族成員結構、佔床規則、房間偏好與告警門檻
├── data/                            # Docker Volume 掛載點（存放 SQLite 與匯出報表）
│   ├── tracker.db
│   └── reports/
├── scripts/
│   └── inspect_xhr.py               # 開發階段 XHR 攔截與封包檢視輔助工具
├── src/
│   ├── main.py                      # FastAPI 入口與 API Endpoints
│   ├── config.py                    # 載入 .env 與 YAML 設定
│   ├── schemas/
│   │   ├── tour_schema.py           # 統一 OkinawaTourPackage Pydantic 模型（見附錄一）
│   │   ├── discovery_schema.py      # 模組一清單項目模型 (TourListItem)
│   │   └── budget_schema.py         # 模組三預算試算結果與告警事件模型
│   ├── db/
│   │   ├── database.py              # SQLite 連線與 DDL 初始化
│   │   └── repository.py            # 寫入團次、價格歷史快照、異動比對查詢
│   ├── discovery/                   # 【模組一】上游清單自動抓取
│   │   ├── base_adapter.py          # 抽象基底類別 (雙模式：XHR 直打 + Playwright 攔截)
│   │   ├── lion_adapter.py          # 雄獅旅遊
│   │   ├── cola_adapter.py          # 可樂旅遊
│   │   ├── settour_adapter.py       # 東南旅遊
│   │   ├── richmont_adapter.py      # 山富旅遊
│   │   └── fourp_adapter.py         # 世邦旅遊
│   ├── extractor/                   # 詳情頁解析與機票基準
│   │   ├── detail_crawler.py        # Crawl4AI + LLMExtractionStrategy 封裝
│   │   └── flight_benchmark.py      # fast-flights 查詢 TPE/KHH <-> OKA
│   ├── calculator/                  # 【模組三】家族總預算試算與排行
│   │   ├── budget_engine.py         # 計價公式、小費、房差、年齡/機位檢核
│   │   └── alert_detector.py        # 降價、低機位、新團事件偵測器
│   └── services/
│       └── pipeline_service.py      # 串聯 Module 1 -> DB Diff -> Extractor -> Module 3
├── n8n/
│   └── okinawa_monitor_workflow.json # 可直接匯入 n8n 的工作流範本
└── tests/
    ├── test_budget_engine.py        # 模組三計價邏輯單元測試
    └── test_alert_detector.py       # 告警規則單元測試
```

---

## 三、 模組一規格：上游清單自動撈取引擎 (`src/discovery/`) — [[skills/okinawa-discovery/SKILL|專案技能規範]]

### 3.1 設計原則：雙模式容錯架構（Adapter Pattern）
臺灣旅行社前端 API 參數與 Cookie 檢核不定期變動，單靠寫死的 `httpx` POST 請求容易失效。所有旅行社 Adapter 均須繼承 `BaseAgencyAdapter`，支援兩種擷取模式並自動容錯：

1. **Mode A — Direct XHR Replay（優先模式，耗時 < 2 秒）**：透過 `httpx.AsyncClient` 直接發送旅行社搜尋 API 的 JSON/Form POST 請求（可自動處理分頁 `pageIndex`）。
2. **Mode B — Playwright Network Interception（備援模式，當 Mode A 遇到 HTTP 403/WAF 或欄位變更時自動降級切換）**：
   * 使用無頭 Chromium 開啟旅行社「沖繩＋出發日期區間」的搜尋結果頁。
   * 掛載監聽器 `page.on("response", handler)`，攔截符合特定 URL Pattern 且 `Content-Type` 為 `application/json` 的 XHR 回應，直接解析原始 JSON，並自動捲動或點擊「下一頁」。
   * 若該站為傳統伺服器渲染（如部分世邦頁面無 JSON XHR），則直接於同一個 Playwright Session 抽取列表 DOM 連結與基礎價格。

### 3.2 統一清單輸出格式 (`TourListItem`)
五家旅行社 Adapter 必須將異質清單正規化為統一格式：

```python
from typing import Literal, Optional
from pydantic import BaseModel


class TourListItem(BaseModel):
    agency: Literal["可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊"]
    tour_code: str                  # 唯一識別碼（團號/產品代碼，用於 DB 去重）
    tour_name: str
    departure_date: str             # YYYY-MM-DD
    days: int                       # 過濾器硬限制 <= 5
    departure_airport: str          # TPE / KHH / RMQ / OTHER
    adult_price: Optional[int]      # 清單頁即時成人團費（台幣整數）
    seats_available: Optional[int]  # 清單頁即時可售機位
    status: str                     # 可報名 / 保證出團 / 候補 / 滿團
    detail_url: str                 # 完整行程詳情頁網址
    raw_hash: str                   # 清單關鍵欄位雜湊值，用於判斷是否異動
```

### 3.3 五家旅行社前置條件與過濾規則
* **共同過濾參數（讀取自 `config/agencies.yaml`）**：
  * 目的地關鍵字：`沖繩`、`琉球`、`OKA`
  * 出發日期區間：`2027-02-01` ～ `2027-02-14`
  * 天數上限：`days <= 5`
  * 出發地：`ALL`（保留 `TPE` 與 `KHH`，供後續分組比較）
* **各社實作要點與 Debug 工具需求**：
  * 須附帶輔助偵錯腳本 `scripts/inspect_xhr.py --agency lion --url "<搜尋頁網址>"`，能在開發階段自動開啟 Playwright 並將所有 JSON XHR 的 Request URL、Payload 與 Response 樣本存到 `logs/xhr_dump/`，方便快速對齊五家最新 API 欄位，避免猜測。
  * **雄獅（Lion）**：攔截 `NormGroupList` / `SearchGroup` 類 API，擷取 `NormGroupID`、`GoDate`、`GroupStraightPrice`、`AvailableVacancy`。
  * **可樂（Cola）**：攔截 `TourSearch` AJAX JSON，組合 `PatternNo` 與出發日參數生成詳情 URL。
  * **東南（Settour）**：攔截團體搜尋 API，擷取 `ProdNo`（如 `GFG...`）、出發日與可售位數。
  * **山富（Richmont）**：攔截 `/group/` 搜尋列表 JSON 或 DOM 卡片，提取團號與團費。
  * **世邦（4p）**：支援 XHR 攔截或 HTML 列表解析雙路徑，過濾天數與出發月份。
* **反封鎖與禮貌存取規範**：
  * 各旅行社併發度上限為 `1`（依序執行或分社錯開），翻頁間隔隨機延遲 `2.0 ~ 4.5` 秒（Jitter）。
  * 單一旅行社抓取失敗不得中斷其他四家執行，須捕捉例外並寫入執行錯誤日誌回報給 n8n。

---

## 四、 模組二規格：Docker 容器化、SQLite 監控與 n8n 告警流 — [[skills/okinawa-extractor/SKILL|專案技能規範]]

### 4.1 資料庫設計（SQLite DDL：`src/db/database.py`）
設計四張核心資料表，實現**增量解析（省 LLM 費用）**與**歷史價格／機位趨勢追蹤**：

```sql
-- 1. 行程主表（存放 Crawl4AI + LLM 解析出的靜態結構化資料）
CREATE TABLE IF NOT EXISTS tours (
    tour_uid TEXT PRIMARY KEY,          -- 格式: "{agency}:{tour_code}:{departure_date}"
    agency TEXT NOT NULL,
    tour_code TEXT NOT NULL,
    tour_name TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    days INTEGER NOT NULL,
    departure_airport TEXT,
    detail_url TEXT NOT NULL,
    detail_json TEXT,                   -- 完整 OkinawaTourPackage JSON 字串
    detail_parsed_at TEXT,              -- 最後一次執行 Crawl4AI 解析的時間 (ISO8601)
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER DEFAULT 1         -- 1=仍在架上, 0=已下架或滿團消失
);

-- 2. 每日快照歷史表（每次排程由模組一寫入，用於比對漲跌與機位流失）
CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tour_uid TEXT NOT NULL,
    captured_at TEXT NOT NULL,          -- ISO8601 時間戳
    adult_price INTEGER,
    seats_available INTEGER,
    status TEXT,
    estimated_family_total INTEGER,     -- 模組三算出的當下家族總價
    FOREIGN KEY (tour_uid) REFERENCES tours(tour_uid)
);

-- 3. 同期機票基準歷史表（fast-flights 每日記錄）
CREATE TABLE IF NOT EXISTS flight_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,               -- TPE / KHH
    destination TEXT NOT NULL,          -- OKA
    depart_date TEXT NOT NULL,
    return_date TEXT NOT NULL,
    min_price_twd INTEGER,
    median_price_twd INTEGER,
    raw_json TEXT,
    captured_at TEXT NOT NULL
);

-- 4. 告警發送紀錄表（防止同一事件每日重複轟炸通知）
CREATE TABLE IF NOT EXISTS alert_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT UNIQUE NOT NULL,     -- 去重鍵，例: "PRICE_DROP:{tour_uid}:{new_price}"
    alert_type TEXT NOT NULL,           -- NEW_TOUR / PRICE_DROP / LOW_SEATS / SEAT_CRITICAL
    tour_uid TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

### 4.2 FastAPI 服務介面規格 (`src/main.py`)
容器暴露 Port `8000`，提供標準 RESTful API 供 n8n 呼叫（透過 Header `X-API-Key` 驗證）：

| Method & Endpoint | 功能說明 | 關鍵 Request 參數 / Response 結構 |
| :--- | :--- | :--- |
| `GET /health` | 容器健康檢查 | 回傳 SQLite 狀態與最後執行時間。 |
| `POST /api/v1/pipeline/daily-run` | **主排程進入點**（串聯模組一→增量詳情解析→機票基準→模組三試算→產出告警） | Body: `{"agencies": ["all"], "force_reparse": false, "max_new_details_per_run": 15}`<br>Response: `{"run_id", "stats": {...}, "alerts": [...], "top_5_rankings": [...]}` |
| `POST /api/v1/extract/single` | 手動塞入單一網址測試 Crawl4AI 解析與家族試算 | Body: `{"url": "...", "agency_hint": "雄獅旅遊"}` |
| `GET /api/v1/rankings` | 取得最新一輪家族總價排行榜（支援篩選無購物站、出發機場） | Query: `?airport=TPE&no_shopping=true&only_enough_seats=true&limit=20` |
| `GET /api/v1/tours/{tour_uid}/history` | 查詢特定團次的歷史價格與機位變化曲線資料 | 回傳 `price_snapshots` 時間序列陣列。 |

### 4.3 增量解析規則（Cost Control）
在 `/api/v1/pipeline/daily-run` 中強制執行以下判斷：
1. 若 `tour_uid` 已存在於 `tours` 表，且 `detail_parsed_at` 距離現在 **小於 7 天**：**跳過 Crawl4AI 與 LLM**，直接沿用舊的 `detail_json`，並將今日模組一撈到的最新 `adult_price`、`seats_available`、`status` 覆寫進快照與試算流程。
2. 若為**全新團號**，或距離上次解析超過 7 天：才送入 Crawl4AI 解析詳情頁，並受限於 `max_new_details_per_run`（預設單次最多解析 15 筆，避免首次啟動一次跑上百頁造成超時或被鎖 IP；剩餘未解析團次將於下次排程自動補完）。

### 4.4 告警事件偵測規則 (`src/calculator/alert_detector.py`)
比對「本次快照」與「上一次快照」，符合下列條件且不存在於 `alert_logs.alert_key` 時，產生結構化告警：

| 告警類型 (`alert_type`) | 觸發條件（可於 YAML 調整） | 優先級 |
| :--- | :--- | :--- |
| `PRICE_DROP` | 成人單價較前次下降 **≥ NT$ 1,500**，或家族總預算下降 **≥ NT$ 10,000** | 高 |
| `LOW_SEATS` | 剩餘機位從充裕跌破「家族所需機位 + 緩衝數」（例如需 10 位，機位跌至 ≤ 14 位且仍足夠） | 中高 |
| `SEAT_CRITICAL` | 原本心儀（排名前 10）的團次，剩餘機位跌破「家族所需人數」（已無法全團報名） | 高 |
| `NEW_HIGH_VALUE_TOUR` | 新上架且符合「無購物站 ＋ 剩餘機位足夠 ＋ 家族總價進入前 5 名」的春節團 | 中 |
| `AGENCY_CRAWL_ERROR` | 任一家旅行社連續抓取失敗，提醒檢查該社 XHR 參數是否改版 | 維運 |

### 4.5 Docker 與 n8n 整合設計
* **`Dockerfile` 要求**：使用 `mcr.microsoft.com/playwright/python:v1.50.0-noble`（或相容版本）作為基底，預裝 Chromium 依賴套件與中文字體，確保中文網頁截圖與 DOM 渲染正常；設定 `TZ=Asia/Taipei` 讓日期判斷與台灣時區一致。
* **`docker-compose.yml` 要求**：
  * 掛載 `./data:/app/data` 與 `./config:/app/config`（修改家庭成員或告警門檻無須重建 Image）。
  * 設定 `shm_size: '2gb'` 防止 Chromium 在容器內因 `/dev/shm` 過小崩潰。
  * 設定記憶體上限（例如 `mem_limit: 2g`），確保在輕量雲端主機或本機皆能穩定常駐。
* **n8n 工作流規劃 (`n8n/okinawa_monitor_workflow.json`)**：
  1. `Schedule Trigger`：每日 `09:00` 與 `21:00`（台北時間）觸發。
  2. `HTTP Request`：`POST http://okinawa-tracker:8000/api/v1/pipeline/daily-run`（Timeout 設為 600 秒）。
  3. `IF Node`：判斷 `alerts.length > 0`。
  4. `Code Node`：將告警陣列與 Top 5 排行榜整理成精簡的 Markdown / HTML 訊息（含旅行社、出發日、家族總價、剩餘機位、警示標籤、直達連結）。
  5. `Telegram / Discord / Gmail Node`：推播通知（若同時需建表紀錄，可並聯 `Google Sheets Append/Update` 節點）。

---

## 五、 模組三規格：家族真實總預算試算與評分排行引擎 (`src/calculator/`) — [[skills/okinawa-calculator/SKILL|專案技能規範]]

### 5.1 家族設定檔規格 (`config/family_profile.yaml`)
將人數、年齡、佔床意願與風險偏好全部外部化，不寫死在程式碼中：

```yaml
family_name: "2027沖繩春節家族團"
target_dates:
  earliest_departure: "2027-02-04"
  latest_return: "2027-02-11"
  max_days: 5

# 成員明細（系統會依年齡自動對應日本佔床法規與長輩條款）
members:
  - role: "adult"
    count: 6
    age_note: "一般成人"
    require_bed: true
    require_flight_seat: true
  - role: "senior"
    count: 1
    age: 70
    require_bed: true
    require_flight_seat: true
  - role: "child"
    count: 1
    age: 10
    require_bed: true            # 日本規定滿6歲強制佔床
    require_flight_seat: true
  - role: "child"
    count: 1
    age: 8
    require_bed: true
    require_flight_seat: true
  - role: "child"
    count: 1
    age: 2                       # 滿2歲需機位；未滿6歲可優先適用「兒童不佔床」
    require_bed: false
    require_flight_seat: true
  # 若有未滿2歲嬰兒可加入 role: "infant", age: 1, require_bed: false, require_flight_seat: false

# 費用估算預設值（當旅行社頁面未標明特定欄位時的保守補位值，系統會標記 is_estimated=true）
defaults:
  tip_per_day_twd: 300           # 日本團常見每日小費
  tip_exempt_under_age: 2        # 未滿2歲嬰兒通常免收小費
  fallback_child_no_bed_diff: -3000
  fallback_infant_price: 6000
  fallback_single_room_supplement: 12000

# 房間分配策略
rooming:
  prefer_triple_room_for_odd_pax: true   # 佔床總人數為奇數時，優先檢查行程是否允許三人房/加床；若不允許才加計單人房差

# 告警與篩選門檻
alerts:
  price_drop_per_adult_twd: 1500
  price_drop_family_total_twd: 10000
  seat_buffer: 4                 # 剩餘機位 <= (全家族需機位人數 + 4) 即發低機位預警

# 綜合性價比評分權重（用於除總價外的綜合推薦排序）
scoring_weights:
  avoid_shopping_stop_bonus: 15
  no_hotel_change_bonus: 10
  early_out_late_back_bonus: 12
  kid_friendly_attraction_bonus: 8
  senior_restriction_penalty: -5
  too_many_self_paid_meals_penalty: -5   # 自理餐超過 4 餐扣分
```

### 5.2 核心計價公式與邊界條件處理 (`src/calculator/budget_engine.py`)

針對每筆 `OkinawaTourPackage`，計算引擎必須逐項拆解並保留**計算明細（Line Items）**與**估算信心旗標**：

1. **人數與機位檢核**：
   * `total_flight_seats_needed` = 所有 `require_flight_seat == true` 的成員總和（依上例為 `10` 席）。
   * `total_beds_needed` = 所有「`require_bed == true` **或** `age >= 6`」的成員總和（強制執行日本飯店滿 6 歲佔床防護邏輯；依上例為 `9` 床）。
   * 若 `tour.seats_available is not None` 且 `tour.seats_available < total_flight_seats_needed`，標記 `seat_status = "INSUFFICIENT"`，於排行中可選擇過濾或置底。
2. **各項費用計算規則**：
   * **一般成人費用**：`adult_count * adult_twin_price`。
   * **長輩費用**：`senior_count * (adult_twin_price + (senior_price_adjustment or 0))`。若 `member.age >= (senior_age_threshold or 70)`，自動將 `senior_companion_rule` 與 `senior_insurance_note` 寫入 `risk_warnings[]`。
   * **佔床兒童費用（含滿 6 歲強制佔床）**：
     * 優先取 `child_with_bed_price`；
     * 其次取 `adult_twin_price + child_with_bed_diff`；
     * 若兩者皆為 `null`，則以 `adult_twin_price` 計價並記錄 `assumptions.append("兒童佔床未標價，採成人同價估算")`。
   * **不佔床兒童費用（2～5 歲且 `require_bed == false`）**：
     * 優先取 `child_no_bed_price`；
     * 其次取 `adult_twin_price + child_no_bed_diff`；
     * 若皆為 `null`，採用 `adult_twin_price + fallback_child_no_bed_diff` 並標記 `is_estimated = True`。
   * **嬰兒費用（未滿 2 歲）**：取 `infant_under_2_price` 或 `fallback_infant_price`。
   * **領隊導遊小費總計**：`(tip_per_day_twd or defaults.tip_per_day_twd) * tour.days * (年齡 >= tip_exempt_under_age 的總人數)`。
   * **單人房差檢核**：
     * 若 `total_beds_needed % 2 == 1`（例如 9 位佔床者）：
     * 檢查 `triple_room_policy` 是否明確註明「無法加床／無三人房」或 `prefer_triple_room_for_odd_pax == false`；若是，則加上 `single_room_supplement`（或預設值）；若允許三人房，則房差計為 `0` 並於備註寫入「以雙人房 + 1 間三人房估算」。
3. **地上成本與機票對照**：
   * 依行程的 `departure_airport` 對應今日 `flight_benchmarks` 最低直飛票價，計算 `estimated_land_cost_per_adult = adult_twin_price - benchmark_flight_min_price`，一眼辨識該春節團是否溢價過高。
4. **輸出結果模型 (`FamilyBudgetResult`)**：
   * `grand_total_twd`（全家族含小費與房差真實總價）
   * `avg_cost_per_person_twd`（全家族平均每人花費）
   * `breakdown`（成人／長輩／佔床童／不佔床童／嬰兒／小費／房差逐項金額）
   * `is_estimated` 與 `assumptions[]`（透明列出哪些項目是估算補位）
   * `risk_warnings[]`（例如：「含光伸免稅購物站」、「70歲以上須親友陪同」、「春節包機開票不退」、「剩餘機位僅 6 位不足 10 位」、「自理餐達 5 餐」）
   * `composite_score`（綜合推薦分數，結合價格排名與體驗加減分）

---

## 六、 給 Antigravity 的分階段實作任務清單（Execution Roadmap）

為避免 AI 開發代理一次生成過多檔案導致介面脫節，建議在 Antigravity 中依照以下 **4 個 Phase** 依序下達指令，每完成一個 Phase 立即執行驗收指令確認通過，再進入下一個 Phase：

### Phase 1：專案骨架、Schema 與「模組三」預算引擎（最易單元測試驗證）
* **任務目標**：
  * 依據 `TravelLtinerary.md` 建立完整目錄結構、`requirements.txt`、`.env.example`、`config/family_profile.yaml`、`config/agencies.yaml`。
  * 實作 `src/schemas/`（`tour_schema.py`、`discovery_schema.py`、`budget_schema.py`）。
  * 實作 `src/db/database.py`、`src/db/repository.py`（SQLite 四張表與 CRUD）。
  * 實作 `src/calculator/budget_engine.py`、`src/calculator/alert_detector.py` 與對應的 `pytest` 單元測試（至少涵蓋：6 歲強制佔床、奇數佔床房差判斷、70 歲長輩警示、機位不足標記、降價告警去重）。
* **驗收標準（DoD）**：執行 `pytest tests/` 全部綠燈通過，且模擬 3 筆假沖繩行程 JSON 能正確輸出排序後的家族總價明細。

### Phase 2：詳情頁解析引擎與機票基準模組（`src/extractor/`）
* **任務目標**：
  * 實作 `src/extractor/detail_crawler.py`（封裝 Crawl4AI + `EXPAND_TABS_JS` + `LLMExtractionStrategy`，支援 `.env` 切換 Gemini API 或 Ollama）。
  * 實作 `src/extractor/flight_benchmark.py`（封裝 `fast-flights`，同時支援查詢 `TPE -> OKA` 與 `KHH -> OKA`）。
  * 建立 CLI 測試指令，能輸入 1 個真實旅行社網址，輸出驗證過的 `OkinawaTourPackage` 與家族試算結果。
* **驗收標準（DoD）**：實際代入 1～2 個真實沖繩春節行程網址，成功寫入 `data/tracker.db` 並產出完整結構化 JSON，且 `fast-flights` 成功撈回 2027/02 機票基準。

### Phase 3：「模組一」五大旅行社清單自動撈取與 XHR 偵錯工具（`src/discovery/`）
* **任務目標**：
  * 先實作 `scripts/inspect_xhr.py` 與 `src/discovery/base_adapter.py`（支援 Direct XHR 與 Playwright Network Interception 雙模式）。
  * 依序實作五家 Adapter（建議順序：雄獅 → 可樂 → 東南 → 山富 → 世邦），每次針對單一旅行社透過 `inspect_xhr.py` 確認當下真實 API 端點與 JSON 欄位後再定稿該 Adapter。
  * 實作 `src/services/pipeline_service.py` 串起「清單抓取 → SQLite 增量比對 → 僅對新團號呼叫 Crawl4AI → 家族試算 → 告警偵測」。
* **驗收標準（DoD）**：執行清單抓取指令後，五家旅行社皆能各自穩定回傳 2027/02 沖繩 ≤5 天的 `TourListItem` 陣列，且二次執行時確認「已存在團號不會重複觸發 LLM 解析」。

### Phase 4：「模組二」FastAPI 容器化與 n8n 監控告警工作流
* **任務目標**：
  * 實作 `src/main.py`（FastAPI 所有端點與 `X-API-Key` 保護）。
  * 撰寫 `Dockerfile`、`docker-compose.yml`（含 Volume 掛載、`shm_size: 2gb`、`TZ=Asia/Taipei`）。
  * 產出可匯入的 `n8n/okinawa_monitor_workflow.json`（含每日排程、HTTP 呼叫、條件過濾、Telegram 訊息排版模板）。
* **驗收標準（DoD）**：`docker compose up -d --build` 啟動成功；透過 `curl` 呼叫 `/health` 與 `/api/v1/pipeline/daily-run` 回傳 HTTP 200 及預期 JSON；匯入 n8n 後手動觸發一次，成功收到排版清晰的告警與排行榜推播。

---

## 附錄一：統一行程資料模型 (`src/schemas/tour_schema.py`)

以下 Pydantic v2 Schema 供 Crawl4AI 的 `LLMExtractionStrategy` 與模組三試算引擎共用：

```python
from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class FlightLeg(BaseModel):
    airline: str = Field(..., description="航空公司名稱，例如中華航空、長榮航空、星宇航空、台灣虎航、樂桃航空")
    flight_number: Optional[str] = Field(None, description="航班編號，例如 CI120、JX870、IT230")
    is_lcc: bool = Field(False, description="是否為廉價航空（如虎航、樂桃、泰越捷等）")
    is_charter_flight: bool = Field(False, description="是否標註為春節包機、加班機或團體包銷機位")
    departure_airport: str = Field(..., description="出發機場 IATA 代碼，例如 TPE、KHH、RMQ、OKA")
    arrival_airport: str = Field(..., description="抵達機場 IATA 代碼，例如 OKA、TPE、KHH")
    departure_time: Optional[str] = Field(None, description="出發時間 HH:MM（24小時制）")
    arrival_time: Optional[str] = Field(None, description="抵達時間 HH:MM（24小時制）")
    checked_baggage_kg: Optional[int] = Field(None, description="免費託運行李公斤數（若頁面未標明則為 null）")
    meal_included: Optional[bool] = Field(None, description="是否含機上餐食")


class FlightSummary(BaseModel):
    outbound: Optional[FlightLeg] = Field(None, description="去程航班資訊")
    inbound: Optional[FlightLeg] = Field(None, description="回程航班資訊")
    time_band: Literal["早去晚回", "早去午回", "午去晚回", "午去午回", "晚去早回", "晚去晚回", "其他"] = Field(
        "其他", description="航班時段綜合評價（11:59前出發算早去，17:00後回程算晚回）"
    )
    flight_notes: Optional[str] = Field(None, description="航班相關備註（如包機時間可能異動、開票後不可退改）")


class ChildPricing(BaseModel):
    child_with_bed_price: Optional[int] = Field(None, description="兒童佔床報價（台幣），若與成人同價請填入成人價")
    child_with_bed_diff: Optional[int] = Field(None, description="兒童佔床與成人價差（負數代表減價，如 -2000）")
    child_no_bed_price: Optional[int] = Field(None, description="兒童不佔床報價（台幣）")
    child_no_bed_diff: Optional[int] = Field(None, description="兒童不佔床與成人價差（如 -4000）")
    child_no_bed_age_rule: Optional[str] = Field(
        None, description="兒童不佔床適用年齡規定（例如：滿2歲未滿6歲可不佔床，6歲以上強制佔床）"
    )
    infant_under_2_price: Optional[int] = Field(None, description="未滿2歲嬰兒報價（台幣，含稅不佔位）")


class SeniorAndSpecialPolicy(BaseModel):
    senior_price_adjustment: Optional[int] = Field(
        None, description="長輩敬老優惠（填負數）或高齡附加費用（填正數），無特別價差填 null"
    )
    senior_age_threshold: Optional[int] = Field(None, description="條款中提及的高齡門檻歲數（常見為 70 或 75 歲）")
    senior_companion_rule: Optional[str] = Field(
        None, description="高齡參團規定（如：滿70歲須有親友陪同、80歲以上須填健康聲明書）"
    )
    senior_insurance_note: Optional[str] = Field(
        None, description="高齡旅客旅責險或意外醫療保額限制／加保說明"
    )


class PricingDetail(BaseModel):
    currency: str = Field("TWD", description="幣別，預設 TWD")
    adult_twin_price: Optional[int] = Field(None, description="成人雙人房佔床每人團費（台幣整數）")
    tax_included: bool = Field(True, description="報價是否已含機場稅與燃油附加費")
    lny_surcharge_included: bool = Field(True, description="報價是否已含 2027 春節旺季加價")
    lny_surcharge_note: Optional[str] = Field(None, description="春節特殊加價、高訂金或嚴格取消費規則說明")
    child_pricing: ChildPricing = Field(default_factory=ChildPricing)
    senior_policy: SeniorAndSpecialPolicy = Field(default_factory=SeniorAndSpecialPolicy)
    tip_per_day_twd: Optional[int] = Field(None, description="領隊導遊司機小費（台幣／每日，日本團常見 300）")
    single_room_supplement: Optional[int] = Field(None, description="單人房差額（台幣）")
    triple_room_policy: Optional[str] = Field(None, description="三人房或加床規定（如提供沙發床、行軍床或無法加床）")
    deposit_per_person: Optional[int] = Field(None, description="報名訂金（台幣／每人）")
    early_bird_or_promo: Optional[str] = Field(None, description="早鳥折扣、第二人減價或聯名卡優惠說明")


class AttractionItem(BaseModel):
    name: str = Field(..., description="景點名稱，例如：沖繩美麗海水族館、古宇利島、國際通、玉泉洞")
    region: Literal["北部(名護/本部)", "中部(恩納/北谷/讀谷)", "南部(那霸/系滿/南城)", "離島", "未分類"] = Field(
        "未分類", description="景點所屬沖繩地理分區"
    )
    admission_type: Literal["含門票", "免費/下車參觀", "車窗瀏覽", "自費", "未標明"] = Field(
        "未標明", description="門票包含狀態"
    )
    is_shopping_stop: bool = Field(False, description="是否為購物站（如光伸免稅店、藥妝免稅站、珍珠店等）")


class MealPlan(BaseModel):
    breakfast: str = Field("未標明", description="早餐安排（如：飯店內用、敬請自理）")
    lunch: str = Field("未標明", description="午餐安排（如：燒肉吃到飽、方便遊玩敬請自理）")
    dinner: str = Field("未標明", description="晚餐安排（如：涮涮鍋、敬請自理）")
    self_paid_meal_count: int = Field(0, description="當日須自理的餐數（0～3）")


class HotelStay(BaseModel):
    candidate_hotels: List[str] = Field(default_factory=list, description="當晚候選飯店名稱清單（拆開『或』字）")
    or_similar: bool = Field(False, description="頁面是否標註『或同級』")
    area: Literal["那霸市區", "海濱渡假區(恩納/名護/讀谷/北谷)", "中部商務", "南部/瀨長島", "其他"] = Field(
        "其他", description="飯店所在區域類型"
    )
    is_beach_resort: bool = Field(False, description="是否屬於海景渡假村類型飯店")


class DailyItinerary(BaseModel):
    day_number: int = Field(..., ge=1, le=5, description="第幾天（1 至 5）")
    day_title: str = Field(..., description="當日行程標題摘要")
    is_free_day: bool = Field(False, description="當日是否為全日自由活動（無專車與導遊）")
    attractions: List[AttractionItem] = Field(default_factory=list, description="當日景點清單")
    meals: MealPlan = Field(default_factory=MealPlan)
    hotel: Optional[HotelStay] = Field(None, description="當晚住宿（最後一天回台灣則為 null）")


class ComparisonFlags(BaseModel):
    has_shopping_station: bool = Field(False, description="全行程是否包含免稅購物站（如光伸免稅店）")
    free_day_count: int = Field(0, description="全日自由活動天數")
    no_hotel_change: bool = Field(False, description="是否全程連住同一間飯店免搬行李")
    total_self_paid_meals: int = Field(0, description="全行程總計自理餐數")
    kid_friendly_tags: List[str] = Field(
        default_factory=list, description="適合兒童的亮點標籤（如：美麗海水族館、DMM水族館、玉泉洞、星野、戲水）"
    )


class OkinawaTourPackage(BaseModel):
    agency: Literal["可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊", "其他"] = Field(
        ..., description="旅行社名稱"
    )
    tour_code: Optional[str] = Field(None, description="團號或產品代碼")
    tour_name: str = Field(..., description="完整行程標題")
    source_url: Optional[str] = Field(None, description="原始抓取網址")
    tour_type: Literal["團體旅遊", "MiniTour/小包團", "機加酒自由行", "半自助"] = Field(
        "團體旅遊", description="行程運作型態"
    )
    days: int = Field(..., ge=1, le=5, description="行程總天數（本研究限定 5 天含以下）")
    nights: int = Field(..., ge=0, le=4, description="住宿晚數")
    departure_date: Optional[str] = Field(None, description="出發日期 YYYY-MM-DD")
    return_date: Optional[str] = Field(None, description="回程日期 YYYY-MM-DD")
    is_lny_2027_peak: bool = Field(
        False, description="出發或行程區間是否涵蓋 2027 農曆春節連假（2027-02-04 至 2027-02-10）"
    )
    departure_airport: Literal["TPE", "KHH", "RMQ", "TSA", "OTHER"] = Field(
        "TPE", description="台灣出發機場代碼（TPE桃園、KHH高雄、RMQ台中、TSA松山）"
    )
    status: Literal["可報名", "保證出團", "候補", "滿團", "已截止", "未知"] = Field("未知", description="團位狀態")
    seats_available: Optional[int] = Field(None, description="剩餘可售機位數")
    min_pax_to_go: Optional[int] = Field(None, description="最低成行人數（如 16 人或 6 人）")
    flights: FlightSummary = Field(default_factory=FlightSummary)
    pricing: PricingDetail = Field(default_factory=PricingDetail)
    itinerary: List[DailyItinerary] = Field(default_factory=list, description="每日行程明細")
    comparison_flags: ComparisonFlags = Field(default_factory=ComparisonFlags)
```