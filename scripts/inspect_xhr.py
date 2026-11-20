from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_agencies_config


async def inspect_agency_xhr(
    agency: str,
    url: str,
    wait_seconds: float = 8.0,
    headless: bool = True,
    output_dir: str = "logs/xhr_dump",
) -> Path:
    """開啟 Playwright 攔截指定網頁之所有 JSON XHR 請求與回應，寫入 logs/xhr_dump/ 供欄位對齊。"""
    dump_dir = Path(output_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)
    captured: List[Dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="zh-TW",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        async def on_response(response):
            try:
                content_type = (response.headers.get("content-type") or "").lower()
                if "application/json" not in content_type and "text/json" not in content_type:
                    return
                req = response.request
                post_data = None
                try:
                    post_data = req.post_data
                except Exception:
                    pass

                body_json: Any = None
                try:
                    body_json = await response.json()
                except Exception:
                    try:
                        body_json = (await response.text())[:2000]
                    except Exception:
                        body_json = None

                captured.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "method": req.method,
                        "request_headers": dict(req.headers),
                        "post_data": post_data,
                        "response_sample": body_json,
                    }
                )
                print(f"[XHR] {req.method} {response.status} -> {response.url}")
            except Exception as exc:
                print(f"[WARN] 解析 XHR 失敗: {exc}")

        page.on("response", on_response)

        print(f"開啟網頁: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print(f"[WARN] goto timeout 或載入異常: {exc}")

        await asyncio.sleep(wait_seconds)
        # 嘗試捲動觸發延遲載入的 XHR
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(2.0)
        except Exception:
            pass

        await browser.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = dump_dir / f"{agency}_{timestamp}.json"
    out_file.write_text(
        json.dumps(
            {
                "agency": agency,
                "target_url": url,
                "captured_at": timestamp,
                "total_json_xhr": len(captured),
                "requests": captured,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n共攔截 {len(captured)} 筆 JSON XHR，已寫入：{out_file}")
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="五大旅行社搜尋頁 XHR 攔截與封包傾印工具")
    parser.add_argument(
        "--agency",
        required=True,
        choices=["lion", "cola", "settour", "richmont", "fourp"],
        help="旅行社代碼",
    )
    parser.add_argument("--url", type=str, default=None, help="搜尋頁網址（未指定時讀取 config/agencies.yaml）")
    parser.add_argument("--wait", type=float, default=8.0, help="載入後等待秒數")
    parser.add_argument("--headed", action="store_true", help="以有頭模式開啟瀏覽器觀察操作")
    args = parser.parse_args()

    url = args.url
    if not url:
        cfg = load_agencies_config("config/agencies.yaml")
        url = cfg.get("agencies", {}).get(args.agency, {}).get("search_url")
    if not url:
        parser.error("未提供 --url 且 config/agencies.yaml 找不到對應 search_url")

    asyncio.run(
        inspect_agency_xhr(
            agency=args.agency,
            url=url,
            wait_seconds=args.wait,
            headless=not args.headed,
        )
    )


if __name__ == "__main__":
    main()
