from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMConfig,
    LLMExtractionStrategy,
)

from src.config import Settings, get_settings
from src.schemas.tour_schema import OkinawaTourPackage

logger = logging.getLogger(__name__)

# 針對五大旅行社詳情頁常見的折疊面板、頁籤（行程明細、費用說明、高齡與兒童條款、購物站備註）進行展開
EXPAND_TABS_JS = """
(() => {
    const selectors = [
        '[role="tab"]',
        '.nav-tabs a',
        '.nav-tabs button',
        '.tab-item',
        '.accordion-button',
        '.collapse-header',
        '.btn-more',
        '.expand-btn',
        'button[aria-expanded="false"]',
        'summary'
    ];
    for (const sel of selectors) {
        document.querySelectorAll(sel).forEach(el => {
            try {
                const text = (el.innerText || '').trim();
                if (!text.includes('報名') && !text.includes('登入') && !text.includes('結帳')) {
                    el.click();
                }
            } catch (e) {}
        });
    }
    window.scrollTo(0, document.body.scrollHeight / 2);
    setTimeout(() => window.scrollTo(0, document.body.scrollHeight), 400);
})();
"""

EXTRACTION_INSTRUCTION = """
你是一位專業的台灣旅遊產品結構化資料擷取專家。請仔細閱讀這份台灣旅行社「沖繩團體旅遊」詳情頁的完整內容，
並嚴格按照 JSON Schema 提取所有關鍵資訊，特別注意以下細節：
1. **航班與包機資訊**：擷取去程與回程的航空公司、班號、起降時間、機場代碼（TPE/KHH/RMQ/OKA）、是否為廉航(is_lcc)、是否標註春節包機/加班機(is_charter_flight)、託運行李公斤數與機上餐食。
2. **價格與年齡/佔床條款**：
   - 成人雙人房佔床每人團費 (adult_twin_price，台幣整數)。
   - 兒童佔床與不佔床的價格或價差 (child_with_bed_price, child_no_bed_price, child_no_bed_diff)，以及年齡限制文字 (child_no_bed_age_rule)。
   - 未滿2歲嬰兒報價 (infant_under_2_price)。
   - 高齡/長輩條款 (senior_age_threshold, senior_companion_rule, senior_insurance_note, senior_price_adjustment)。
   - 領隊導遊司機每日小費 (tip_per_day_twd)、單人房差 (single_room_supplement)、三人房或加床規定 (triple_room_policy)、報名訂金 (deposit_per_person)。
3. **每日行程與購物站檢查**：
   - 逐日列出景點名稱、所屬分區、門票包含狀態、以及**是否為購物站**（例如：光伸免稅店、藥妝免稅店、珍珠店、乳膠店等，務必將 `is_shopping_stop` 設為 `true`）。
   - 統計每日三餐安排與自理餐數量 (self_paid_meal_count)，以及當晚候選飯店（拆開「或」字放入 `candidate_hotels`）。
4. **比較旗標 (comparison_flags)**：
   - 若行程包含任何免稅店/購物站，`has_shopping_station` 必須為 `true`。
   - 若全程連住同一間飯店免搬行李，`no_hotel_change` 設為 `true`。
   - 標註適合兒童的亮點標籤（如：美麗海水族館、DMM水族館、玉泉洞、星野、戲水）。
若某欄位在頁面中完全未提及，請填 `null`（布林值依預設或頁面實際敘述判斷），絕不可憑空捏造價格或航班。
"""


class DetailExtractionError(RuntimeError):
    """詳情頁擷取或 LLM 解析失敗例外。"""


class DetailCrawler:
    """封裝 Crawl4AI + LLMExtractionStrategy 解析旅行社詳情頁。"""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def _build_llm_config(self) -> LLMConfig:
        provider_model = self.settings.get_litellm_provider_model()
        api_token = self.settings.get_llm_api_token()
        base_url = self.settings.get_llm_base_url()

        if self.settings.llm_provider.strip().lower() == "gemini" and (
            not api_token or api_token == "your_gemini_api_key_here"
        ):
            raise DetailExtractionError(
                "未設定有效的 GEMINI_API_KEY，無法執行 Gemini LLM 解析（請設定 .env 或切換 LLM_PROVIDER=ollama）。"
            )

        kwargs: Dict[str, Any] = {"provider": provider_model}
        if api_token:
            kwargs["api_token"] = api_token
        if base_url:
            kwargs["base_url"] = base_url
        return LLMConfig(**kwargs)

    def _build_extraction_strategy(self, agency_hint: Optional[str] = None) -> LLMExtractionStrategy:
        llm_config = self._build_llm_config()
        instruction = EXTRACTION_INSTRUCTION
        if agency_hint:
            instruction = f"本頁面來自旅行社「{agency_hint}」。\n" + instruction

        return LLMExtractionStrategy(
            llm_config=llm_config,
            schema=OkinawaTourPackage.model_json_schema(),
            extraction_type="schema",
            instruction=instruction,
            chunk_token_threshold=6000,
            overlap_rate=0.1,
            apply_chunking=True,
            input_format="markdown",
            extra_args={"temperature": 0.1},
        )

    @staticmethod
    def parse_extracted_json(
        raw_content: Optional[str],
        source_url: Optional[str] = None,
        agency_hint: Optional[str] = None,
    ) -> OkinawaTourPackage:
        """將 LLM 回傳的 JSON 字串解析並驗證為 OkinawaTourPackage。"""
        if not raw_content or not raw_content.strip():
            raise DetailExtractionError("LLM 未回傳任何結構化內容 (extracted_content 為空)。")

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise DetailExtractionError(f"LLM 回傳非合法 JSON：{exc}") from exc

        if isinstance(parsed, list):
            # Crawl4AI chunking 模式下可能回傳 dict 陣列，過濾出非錯誤物件
            valid_items = [item for item in parsed if isinstance(item, dict) and not item.get("error")]
            if not valid_items:
                raise DetailExtractionError(f"LLM 擷取結果陣列無有效資料：{parsed}")
            data: Dict[str, Any] = valid_items[0]
        elif isinstance(parsed, dict):
            if parsed.get("error"):
                raise DetailExtractionError(f"LLM 擷取回報錯誤：{parsed}")
            data = parsed
        else:
            raise DetailExtractionError(f"非預期的 JSON 根型別：{type(parsed)}")

        if source_url and not data.get("source_url"):
            data["source_url"] = source_url
        if agency_hint and not data.get("agency"):
            data["agency"] = agency_hint

        # 若 days 未填或超出 1-5 限制，於 Pydantic 驗證前做安全防衛或讓驗證反映錯誤
        return OkinawaTourPackage.model_validate(data)

    async def parse_url(
        self,
        url: str,
        agency_hint: Optional[str] = None,
        timeout_ms: int = 60000,
    ) -> OkinawaTourPackage:
        """爬取指定詳情頁網址並透過 LLM 解析為 OkinawaTourPackage。"""
        strategy = self._build_extraction_strategy(agency_hint=agency_hint)
        browser_config = BrowserConfig(
            headless=self.settings.crawler_headless,
            verbose=False,
        )
        run_config = CrawlerRunConfig(
            extraction_strategy=strategy,
            js_code=EXPAND_TABS_JS,
            cache_mode=CacheMode.BYPASS,
            wait_until="domcontentloaded",
            delay_before_return_html=2.5,
            page_timeout=timeout_ms,
        )

        logger.info("開始使用 Crawl4AI 解析詳情頁: %s (provider=%s)", url, self.settings.get_litellm_provider_model())
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            raise DetailExtractionError(f"Crawl4AI 抓取失敗 ({url}): {result.error_message}")

        package = self.parse_extracted_json(
            result.extracted_content,
            source_url=url,
            agency_hint=agency_hint,
        )
        return package
