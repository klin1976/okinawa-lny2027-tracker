---
name: okinawa-calculator
description: >
  模組三：家族真實總預算試算、評分排行與異動告警偵測引擎。
  讀取 config/family_profile.yaml，處理日本滿 6 歲強制佔床、小費、單人房差與剩餘機位檢核。
aliases:
  - okinawa-calculator
  - 模組三：家族預算試算與告警
tags:
  - skill
  - calculator
  - budget
  - alerts
  - n8n
  - okinawa-2027
type: skill
created: 2026-11-19
---

# 模組三：家族總預算試算與告警 (`src/calculator/`) 開發規範

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作]] ｜ [[docs/api_spec|🔌 API規格書]]  
> **關聯模組**：[[skills/okinawa-discovery/SKILL|🕷️ 模組一：okinawa-discovery]] ｜ [[skills/okinawa-extractor/SKILL|🧠 模組二：okinawa-extractor]]

---

## 核心邏輯

- **家族計價規則 (`budget_engine.py`)**：讀取 `config/family_profile.yaml` 定義之成員年齡與佔床需求，自動套用日本「滿 6 歲強制佔床」規則，加計每日小費乘算、單人房差，並檢核 `seats_available` 是否足以容納全家人數。
- **風險標註**：針對長輩陪同友善度與購物站風險進行標註與評分排行。
- **異動偵測 (`alert_detector.py`)**：比對當日與前次 `price_snapshots`，偵測降價、新團上架、機位跌破門檻等事件，產出 `alerts[]` 供 n8n 發送通知（定義見 [[docs/api_spec]]）。

## 已知地雷 / Gotchas

- 計算總預算時不可遺漏領隊司機小費（通常以天數 × 人數計算）與單人房差。
- 所有計價與告警規則必須有對應的 `pytest` 單元測試（`tests/test_budget_engine.py`、`tests/test_alert_detector.py`，由 [[AGENTS]] `agent-qa` 負責）。

## 檔案範圍

| 檔案 / 目錄 | 說明 | 關聯文檔 |
|------------|------|---------|
| `src/calculator/budget_engine.py` | 計價公式、小費、房差、年齡/機位檢核 | [[2027_TravelLtinerary]] 第 3.3 節 |
| `src/calculator/alert_detector.py` | 降價、低機位、新團事件偵測器 | [[docs/api_spec]] `/daily-run` |
| `src/schemas/budget_schema.py` | 預算試算結果與告警事件 Pydantic 模型 | [[docs/api_spec]] |
| `config/family_profile.yaml` | 家族成員結構與告警門檻設定 | [[2027_TravelLtinerary]] |
| `tests/test_budget_engine.py` | 計價邏輯單元測試 | [[AGENTS]] `agent-qa` |
| `tests/test_alert_detector.py` | 告警規則單元測試 | [[AGENTS]] `agent-qa` |
