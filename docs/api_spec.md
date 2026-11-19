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

### 1. 觸發每日比價與監控管線 (`POST /api/v1/pipeline/daily-run`)
**用途**：供 n8n 每日排程（09:00 / 21:00）呼叫，依序執行 Module 1 清單抓取 → SQLite 增量比對 → Module 2 詳情頁與機票基準解析 → Module 3 家族預算試算與告警偵測。  
**對應 Skill**：[[skills/okinawa-discovery/SKILL|okinawa-discovery]]、[[skills/okinawa-calculator/SKILL|okinawa-calculator]]

- **URL**: `POST /api/v1/pipeline/daily-run`
- **Request Body**:
  ```json
  {
    "force_refresh_details": false,
    "agencies": ["可樂旅遊", "東南旅遊", "雄獅旅遊", "山富旅遊", "世邦旅遊"]
  }
  ```
- **Response (成功)**:
  ```json
  {
    "run_id": "20270201T090000Z",
    "status": "SUCCESS",
    "alerts": [
      {
        "event_type": "PRICE_DROP",
        "tour_uid": "雄獅旅遊:27JN204BR:2027-02-04",
        "message": "成人團費調降 2,000 元"
      }
    ],
    "top_ranked_tours": [],
    "errors": []
  }
  ```
- **Response (失敗)**:
  ```json
  {
    "status": "FAILED",
    "detail": "Pipeline execution error message"
  }
  ```

### 2. 健康檢查 (`GET /health`)
**用途**：供 Docker Healthcheck 與 n8n 確認服務存活狀態。

- **URL**: `GET /health`
- **Response (成功)**:
  ```json
  {
    "status": "ok",
    "db_connected": true
  }
  ```

<!-- TODO: 待補充查詢歷史快照、手動匯出報表等次要端點規格 -->

---

## 🗄️ SQLite 資料表核心約束

- `tours`：主鍵 `tour_uid` 格式為 `"{agency}:{tour_code}:{departure_date}"`，`detail_json` 儲存 `OkinawaTourPackage` JSON 字串（詳見 [[2027_TravelLtinerary]] 核心模型）。
- `price_snapshots`：記錄每次排程抓取的 `adult_price`、`seats_available`、`status` 與 `estimated_family_total`。
- `flight_benchmarks`：記錄 `fast-flights` 查詢之 `TPE/KHH <-> OKA` 同期直飛基準價。
