"""快手网页版私信适配器（仅发送文字）。

快手网页版私信的入口与稳定性会随版本变化，若页面打不开或找不到关键元素，
会记录原因并跳过，不做任何接口逆向或伪造请求。
"""

from __future__ import annotations

import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from ..config import Friend
from .base import LayoutChanged, PlatformAdapter, any_text_visible, first_visible

LOGGED_OUT_TEXTS = ("扫码登录", "验证码登录", "登录后查看更多")


class KuaishouAdapter(PlatformAdapter):
    name = "kuaishou"
    label = "快手"
    LOGIN_COOKIE_NAMES = ("passToken", "kuaishou.server.web_st", "kuaishou.server.web_ph")

    async def is_logged_in(self, page: Page) -> bool:
        if not await self.has_login_cookie(page):
            return False
        if await any_text_visible(page, LOGGED_OUT_TEXTS):
            return False
        try:
            login_button = page.get_by_role("button", name=re.compile(r"^\s*登录\s*$"))
            if await login_button.first.is_visible():
                return False
        except PlaywrightError:
            pass
        return True

    async def open_chat(self, page: Page, friend: Friend) -> None:
        search = await first_visible(
            [
                page.get_by_placeholder(re.compile("搜索")),
                page.get_by_placeholder(re.compile("搜索联系人|搜索好友|搜索用户")),
                page.locator('input[placeholder*="搜索"]'),
                page.locator('[class*="search"] input'),
            ],
            timeout_ms=3000,
        )
        if search is None:
            raise LayoutChanged("找不到私信联系人搜索框（网页版私信可能不可用）")

        await search.click()
        await search.fill(friend.name)
        await page.wait_for_timeout(1200)

        target = await first_visible(
            [
                page.get_by_text(friend.name, exact=True),
                page.get_by_role("listitem").filter(has_text=friend.name),
                page.get_by_title(friend.name),
                page.get_by_text(friend.name, exact=False),
            ],
            timeout_ms=3000,
        )
        if target is None:
            raise LayoutChanged(f"搜索不到好友：{friend.display}")

        await target.click()
        await page.wait_for_timeout(1500)

    async def find_composer(self, page: Page) -> Locator | None:
        return await first_visible(
            [
                page.locator('div[contenteditable="true"][data-placeholder]').last,
                page.locator('div[contenteditable="true"]').last,
                page.locator('[role="textbox"]').last,
                page.get_by_role("textbox").last,
                page.locator("textarea").last,
            ],
            timeout_ms=2500,
        )

    async def find_send_button(self, page: Page) -> Locator | None:
        return await first_visible(
            [
                page.get_by_role("button", name=re.compile(r"^\s*发送\s*$")),
                page.locator('button:has-text("发送")'),
                page.locator('[role="button"]:has-text("发送")'),
                page.get_by_text("发送", exact=True).last,
            ],
            timeout_ms=2500,
        )


__all__ = ["KuaishouAdapter"]
