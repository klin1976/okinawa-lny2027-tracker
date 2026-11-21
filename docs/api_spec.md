---
title: "通用多目的地旅遊比價與異動監控雷達 API 與資料交互規格文件"
aliases:
  - api_spec
  - docs/api_spec
  - API規格書
tags:
  - api
  - specification
  - schema
  - fast-api
  - travel-radar
type: api-spec
created: 2026-11-19
updated: 2026-11-21
---

# 通用多目的地旅遊比價與異動監控雷達 (`travel-radar`) API 與資料交互規格文件

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC)]] ｜ [[README|📘 README (專案導覽)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作架構]]

> [!IMPORTANT]
> **架構聲明**：本系統採 **CLI-First + Zero-Infra（GitHub Actions Cron + SQLite `data/radar.db` 回寫）** 為主力運作模式，同時保留 **FastAPI + Uvicorn** (`src/main.py`) 作為選配 Web/API 服務層，全端點已全面支援多目的地 `trip_id`。

---

## 🔌 REST API Endpoints（選配服務層）

> [!NOTE]
> **認證機制**：除 `GET /health` 外，所有 `/api/v1/*` 端點皆須於 Request Header 帶入 `X-API-Key`（對應 `.env` 中的 `API_KEY`）。未帶入或金鑰錯誤將回傳 `HTTP 401 Unauthorized`。

### 1. 健康檢查 (`GET /health`)
檢查 SQLite 連線狀態與最新價格快照時間（免驗證）。

- **Response (`200 OK`)**:
  ```json
  {
    "status": "ok",
    "db_connected": true,
    "last_run_at": "2027-02-01T09:05:12+08:00"
  }
  ```

---

### 2. 取得已設定之多目的地旅遊專案 (`GET /api/v1/trips`)
列出 `config/trips/*.yaml` 下所有旅遊專案摘要設定。

- **Query Parameters**:
  - `enabled_only` (optional, bool, default `false`): 是否僅回傳 `enabled: true` 的專案。
- **Response (`200 OK`)**:
  ```json
  {
    "total": 4,
    "trips": [
      {
        "trip_id": "okinawa_lny2027",
        "trip_name": "2027 春節沖繩家族團",
        "enabled": true,
        "country": "日本",
        "region_name": "沖繩",
        "airports": ["OKA"],
        "departure_date_start": "2027-02-01",
        "departure_date_end": "2027-02-14",
        "min_days": 4,
        "max_days": 5,
        "child_bed_age_threshold": 6,
        "target_total_budget_twd": 450000
      }
    ]
  }
  ```

---

### 3. 觸發指定專案巡檢與監控管線 (`POST /api/v1/pipeline/daily-run`)
依序執行清單抓取 → 7 天增量詳情解析 → 多航線機票基準 → 家族預算與 `RuleEvaluator` 評分 → 事件驅動快照與差異告警偵測 → `scan_history` 寫入。

- **Request Body**:
  ```json
  {
    "trip_id": "okinawa_lny2027",
    "agencies": ["all"],
    "force_reparse": false,
    "max_new_details_per_run": 15,
    "skip_flight_benchmark": false
  }
  ```
- **Response (`200 OK`)**:
  回傳 `run_id`、`trip_id`、`trip_name`、`status`、`stats`（含 `snapshots_inserted`）、`diff_summary`、`alerts`（含 `PRICE_DROP` / `SEATS_RELEASED` / `GUARANTEED_DEPARTURE` / `NEW_HIGH_VALUE_TOUR` 等）、`top_5_rankings`、`rankings` 與 `errors`。

---

### 4. 單一網址手動解析與試算 (`POST /api/v1/extract/single`)
送入單一旅行社行程網址，以 `TourPackage` 擷取並執行 `BudgetEngine` + `RuleEvaluator`。

- **Request Body**:
  ```json
  {
    "url": "https://travel.liontravel.com/detail?NormGroupID=...",
    "agency_hint": "雄獅旅遊",
    "trip_id": "europe_summer2027"
  }
  ```
- **Response (`200 OK`)**: 回傳 `tour` (`TourPackage`)、`budget` (`FamilyBudgetResult`) 與 `evaluation`（`is_passed`, `score`, `tags`, `passed_rules`, `failed_rules`）。

---

### 5. 取得最新家族總價排行榜 (`GET /api/v1/rankings`)
支援跨國多專案篩選與 1~30 天各類行程排序。

- **Query Parameters**:
  - `trip_id` (optional): 篩選特定旅遊專案 ID（如 `europe_summer2027`）
  - `airport` (optional): 台灣出發機場代碼篩選（`TPE`、`KHH`、`RMQ`、`TSA`）
  - `no_shopping` (optional, bool): 是否僅顯示無購物站行程
  - `only_enough_seats` (optional, bool): 是否僅顯示全家機位足夠之團次
  - `limit` (optional, int, default `20`): 回傳筆數上限

---

### 6. 查詢特定團次歷史價格與機位趨勢 (`GET /api/v1/tours/{tour_uid}/history`)
依 `tour_uid` 查詢元資料（含 `trip_id`、`destination_country`、`destination_airport`）及 `price_snapshots` 時間序列。

---

## 🗄️ SQLite 資料表核心約束 (`data/radar.db`)

- **`tours`**：主鍵 `tour_uid` 格式維持 `"{agency}:{tour_code}:{departure_date}"`；新增 `trip_id`、`destination_country`、`destination_airport`、`score`、`tags_json` 欄位，`detail_json` 儲存通用 `TourPackage` JSON 字串。支援自動 `ALTER TABLE` 舊庫遷移。
- **`price_snapshots`**：**事件驅動快照表**，僅在首次收錄或 `adult_price`、`seats_available`、`status`、`estimated_family_total` 任一欄位異動時寫入，避免 GitHub Repo 資料庫膨脹。
- **`flight_benchmarks`**：支援任意全球航線（`origin` ↔ `destination`）與直飛/轉機機票基準價記錄。
- **`alert_logs`**：以 `alert_key`（UNIQUE）進行告警去重，避免重複推播。
- **`scan_history`**：巡檢審計表，記錄每次各 `trip_id` 掃描時間、執行旅行社、總筆數、新團/降價/釋出/狀態變動數與錯誤摘要。
