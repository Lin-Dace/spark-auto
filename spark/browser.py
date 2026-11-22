"""浏览器与登录态管理：复用 storage_state，不保存密码。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from playwright.async_api import BrowserContext, Error as PlaywrightError, async_playwright

from .config import AppConfig

LOGIN_TIMEOUT_SECONDS = 600
LOGIN_POLL_SECONDS = 3
LOGIN_CONFIRM_TIMES = 2


@asynccontextmanager
async def browser_context(
    cfg: AppConfig,
    platform: str,
    *,
    headless: bool | None = None,
) -> AsyncIterator[BrowserContext]:
    """打开一个使用本地登录态的浏览器上下文。"""
    state_path = cfg.state_path(platform)
    use_headless = cfg.headless if headless is None else headless
    logger = logging.getLogger("spark")

    async with async_playwright() as playwright:
        browser = None
        if cfg.browser_channel:
            try:
                browser = await playwright.chromium.launch(
                    headless=use_headless, channel=cfg.browser_channel
                )
            except PlaywrightError as exc:
                logger.warning(
                    "启动 %s 失败（%s），改用 Playwright 自带 Chromium",
                    cfg.browser_channel,
                    str(exc).splitlines()[0],
                )
        if browser is None:
            try:
                browser = await playwright.chromium.launch(headless=use_headless)
            except PlaywrightError as exc:
                raise PlaywrightError(
                    f"启动浏览器失败：{exc}\n"
                    "提示：请执行 python -m playwright install chromium，"
                    "或在 config.json 把 browser_channel 改为本机已安装的 chrome / msedge"
                ) from exc

        context = await browser.new_context(
            storage_state=str(state_path) if state_path.exists() else None,
            locale="zh-CN",
            viewport={"width": 1366, "height": 900},
        )
        context.set_default_timeout(15_000)
        context.set_default_navigation_timeout(60_000)
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


async def interactive_login(cfg: AppConfig, platform: str) -> bool:
    """打开有头浏览器，用户扫码后自动检测登录状态并保存。"""
    from .platforms import create_adapter  # 延迟导入，避免循环依赖

    logger = logging.getLogger("spark")
    platform_cfg = cfg.platforms[platform]
    adapter = create_adapter(platform, platform_cfg.messages_url)

    logger.info("[%s] 正在打开浏览器，请在弹出的窗口中扫码登录", platform_cfg.label)
    async with browser_context(cfg, platform, headless=False) as context:
        page = await context.new_page()
        await page.goto(platform_cfg.messages_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        logger.info("[%s] 当前页面：%s", platform_cfg.label, page.url)
        logger.info(
            "[%s] 登录成功后会自动保存登录态，最多等待 %d 秒",
            platform_cfg.label,
            LOGIN_TIMEOUT_SECONDS,
        )

        deadline = datetime.now() + timedelta(seconds=LOGIN_TIMEOUT_SECONDS)
        confirmed = 0
        logged_in = False
        while datetime.now() < deadline:
            if page.is_closed():
                logger.error("[%s] 浏览器窗口被关闭，登录未完成", platform_cfg.label)
                return False
            try:
                if await adapter.is_logged_in(page):
                    confirmed += 1
                    if confirmed >= LOGIN_CONFIRM_TIMES:
                        logged_in = True
                        break
                else:
                    confirmed = 0
            except PlaywrightError:
                confirmed = 0
            await asyncio.sleep(LOGIN_POLL_SECONDS)

        if not logged_in:
            logger.error("[%s] 等待登录超时，未保存登录态", platform_cfg.label)
            return False

        await page.wait_for_timeout(1000)
        state_path = cfg.state_path(platform)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(state_path))
        logger.info("[%s] 登录态已保存：%s", platform_cfg.label, state_path)
        return True
