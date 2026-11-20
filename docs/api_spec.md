---
title: "2027 春節沖繩旅遊跨社比價與監控系統 API 與資料交互規格文件"
aliases:
  - api_spec
  - docs/api_spec
  - API規格書
tags:
  - api
  - specification
  - schema
  - fast-api
  - okinawa-2027
type: api-spec
created: 2026-11-19
---

# 2027 春節沖繩旅遊跨社比價與監控系統 API 與資料交互規格文件

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC)]] ｜ [[README|📘 README (專案導覽)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作架構]]

> [!IMPORTANT]
> **架構聲明**：本系統採用 **Python FastAPI + Uvicorn** 封裝為單一 Docker 容器（`API_ONLY` 架構），搭配本地 **SQLite 3** 儲存歷史快照與行程詳情，外部由 **n8n** 透過 HTTP Request 排程觸發。

---

## 📚 開發引用規範 (Skill Reference)

> [!IMPORTANT]
> 本文件定義系統之**核心資料結構與交互規格**。實際開發時，必須搭配以下 Skill 作為落地指標：

| Skill 文件 | 適用情境 | 引用方式 | 核心看點 |
|-----------|---------|---------|---------|
| [[skills/okinawa-discovery/SKILL]] (okinawa-discovery) | 五大旅行社清單抓取與 XHR 攔截 | 實作 `src/discovery/` 前必讀 | 雙模式容錯、`TourListItem` 正規化、反封鎖延遲 |
| [[skills/okinawa-extractor/SKILL]] (okinawa-extractor) | 詳情頁 LLM 解析與機票基準查詢 | 實作 `src/extractor/` 前必讀 | 7 天增量解析、Gemini/Ollama 切換、`fast-flights` |
| [[skills/okinawa-calculator/SKILL]] (okinawa-calculator) | 家族總預算試算與異動告警 | 實作 `src/calculator/` 前必讀 | 滿 6 歲佔床規則、小費/房差、告警事件格式 |

---

## 🔌 API Endpoints

> [!NOTE]
> **認證機制**：除 `GET /health` 外，所有 `/api/v1/*` 端點皆須於 Request Header 帶入 `X-API-Key`（對應 `.env` 中的 `API_KEY`）。未帶入或金鑰錯誤將回傳 `HTTP 401 Unauthorized`。

### 1. 健康檢查 (`GET /health`)
**用途**：供 Docker `HEALTHCHECK`、`docker-compose` `service_healthy` 與 n8n 確認服務存活及 SQLite 連線狀態（免驗證）。

- **URL**: `GET /health`
- **Response (`200 OK`)**:
  ```json
  {
    "status": "ok",
    "db_connected": true,
    "last_run_at": "2027-02-01T09:05:12+08:00"
  }
  ```

---

### 2. 觸發每日比價與監控管線 (`POST /api/v1/pipeline/daily-run`)
**用途**：主排程進入點，供 n8n 每日排程（09:00 / 21:00 `Asia/Taipei`）呼叫，依序執行：Module 1 清單抓取 → SQLite 7 天增量比對 → Module 2 詳情頁與機票基準解析 → Module 3 家族預算試算與告警偵測。  
**對應 Skill**：[[skills/okinawa-discovery/SKILL|okinawa-discovery]]、[[skills/okinawa-extractor/SKILL|okinawa-extractor]]、[[skills/okinawa-calculator/SKILL|okinawa-calculator]]

- **URL**: `POST /api/v1/pipeline/daily-run`
- **Headers**: `X-API-Key: <API_KEY>`
- **Request Body**:
  ```json
  {
    "agencies": ["all"],
    "force_reparse": false,
    "max_new_details_per_run": 15
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "run_id": "20270201T090000Z",
    "status": "SUCCESS",
    "stats": {
      "discovered_count": 170,
      "parsed_new_count": 15,
      "reused_cached_count": 155,
      "errors_count": 0
    },
    "alerts": [
      {
        "alert_type": "PRICE_DROP",
        "tour_uid": "雄獅旅遊:27JN204BR:2027-02-04",
        "message": "成人團費調降 2,000 元"
      }
    ],
    "top_5_rankings": [
      {
        "tour_uid": "雄獅旅遊:27JN204BR:2027-02-04",
        "agency": "雄獅旅遊",
        "tour_name": "春節沖繩五日遊",
        "departure_date": "2027-02-04",
        "grand_total_twd": 328000,
        "seats_available": 14,
        "composite_score": 88.5,
        "detail_url": "https://travel.liontravel.com/detail?NormGroupID=..."
      }
    ],
    "errors": []
  }
  ```
- **Response (`500 Internal Server Error`)**:
  ```json
  {
    "status": "FAILED",
    "detail": "Pipeline execution error message"
  }
  ```

---

### 3. 單一網址手動解析與試算 (`POST /api/v1/extract/single`)
**用途**：手動送入單一旅行社行程網址，立即觸發 Crawl4AI + LLM 詳情頁解析並回傳 `OkinawaTourPackage` 與家族預算試算結果（適合除錯與臨時比價）。

- **URL**: `POST /api/v1/extract/single`
- **Headers**: `X-API-Key: <API_KEY>`
- **Request Body**:
  ```json
  {
    "url": "https://travel.liontravel.com/detail?NormGroupID=...",
    "agency_hint": "雄獅旅遊"
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "tour": {
      "agency": "雄獅旅遊",
      "tour_code": "27JN204BR",
      "tour_name": "春節沖繩五日遊",
      "days": 5,
      "departure_date": "2027-02-04"
    },
    "budget": {
      "grand_total_twd": 328000,
      "avg_cost_per_person_twd": 32800,
      "seat_status": "SUFFICIENT",
      "composite_score": 88.5
    }
  }
  ```

---

### 4. 取得最新家族總價排行榜 (`GET /api/v1/rankings`)
**用途**：查詢最新一輪家族總價與性價比排行榜，支援依出發機場、是否無購物站、是否機位足夠等條件篩選。

- **URL**: `GET /api/v1/rankings`
- **Headers**: `X-API-Key: <API_KEY>`
- **Query Parameters**:
  - `airport` (optional): 出發機場代碼篩選（如 `TPE`、`KHH`、`RMQ`）
  - `no_shopping` (optional, bool): 是否僅顯示無購物站行程
  - `only_enough_seats` (optional, bool): 是否僅顯示全家機位足夠之團次
  - `limit` (optional, int, default `20`): 回傳筆數上限
- **Response (`200 OK`)**:
  ```json
  {
    "total": 12,
    "rankings": [
      {
        "tour_uid": "雄獅旅遊:27JN204BR:2027-02-04",
        "agency": "雄獅旅遊",
        "tour_name": "春節沖繩五日遊",
        "departure_date": "2027-02-04",
        "departure_airport": "TPE",
        "grand_total_twd": 328000,
        "seats_available": 14,
        "has_shopping_station": false,
        "composite_score": 88.5
      }
    ]
  }
  ```

---

### 5. 查詢特定團次歷史價格與機位趨勢 (`GET /api/v1/tours/{tour_uid}/history`)
**用途**：依 `tour_uid` 查詢該團次於 SQLite `price_snapshots` 的歷史價格、家族總價與剩餘機位變化曲線資料。

- **URL**: `GET /api/v1/tours/{tour_uid}/history`
- **Headers**: `X-API-Key: <API_KEY>`
- **Path Parameter**: `tour_uid`（例：`雄獅旅遊:27JN204BR:2027-02-04`）
- **Response (`200 OK`)**:
  ```json
  {
    "tour_uid": "雄獅旅遊:27JN204BR:2027-02-04",
    "snapshots": [
      {
        "captured_at": "2027-02-01T09:00:10+08:00",
        "adult_price": 34900,
        "seats_available": 16,
        "status": "可報名",
        "estimated_family_total": 348000
      },
      {
        "captured_at": "2027-02-01T21:00:12+08:00",
        "adult_price": 32900,
        "seats_available": 14,
        "status": "可報名",
        "estimated_family_total": 328000
      }
    ]
  }
  ```
- **Response (`404 Not Found`)**:
  ```json
  {
    "detail": "Tour not found"
  }
  ```

---

## 🗄️ SQLite 資料表核心約束

- `tours`：主鍵 `tour_uid` 格式為 `"{agency}:{tour_code}:{departure_date}"`，`detail_json` 儲存 `OkinawaTourPackage` JSON 字串（詳見 [[2027_TravelLtinerary]] 核心模型）。
- `price_snapshots`：記錄每次排程抓取的 `adult_price`、`seats_available`、`status` 與 `estimated_family_total`。
- `flight_benchmarks`：記錄 `fast-flights` 查詢之 `TPE/KHH <-> OKA` 同期直飛基準價。
- `alert_logs`：以 `alert_key`（UNIQUE）進行 24 小時內告警事件去重，避免重複推播轟炸。
