"""抖音网页版私信适配器。

注意：抖音网页版的私信入口/结构可能随版本变化，也可能对部分账号不可用。
找不到联系人搜索框、输入框或发送按钮时，会记录原因并跳过，不伪造任何请求。
"""

from __future__ import annotations

import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page, expect

from ..config import Friend
from .base import LayoutChanged, PlatformAdapter, SendUnverified, any_text_visible, first_visible

LOGGED_OUT_TEXTS = ("扫码登录", "验证码登录", "密码登录")


class DouyinAdapter(PlatformAdapter):
    name = "douyin"
    label = "抖音"
    LOGIN_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_guard", "uid_tt")
    send_with_enter = True
    supports_sticker = True

    async def open(self, page: Page) -> None:
        await super().open(page)
        # 会话列表是懒加载的骨架屏，等搜索框出现后再多等一会儿
        await first_visible(
            [
                page.get_by_placeholder("搜索"),
                page.locator('input[placeholder*="搜索"]'),
            ],
            timeout_ms=8000,
        )
        await page.wait_for_timeout(2500)

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
        target = await self._find_in_list(page, friend.name)
        if target is None:
            raise LayoutChanged(f"会话列表里找不到好友：{friend.display}（名字需与列表显示一致）")
        await target.click()
        await page.wait_for_timeout(1800)

    async def send_sticker(self, page: Page, friend: Friend) -> bool:
        """打开表情面板，发送固定的「早上好」贴图。抖音网页版点击贴图会直接发出并关闭面板。"""
        await self.open_chat(page, friend)
        await self.ensure_not_blocked(page)

        composer = await self.find_composer(page)
        if composer is None:
            raise LayoutChanged("找不到聊天输入框（网页版私信可能不可用）")
        box = await composer.bounding_box()
        if box is None:
            return False

        # 笑脸按钮在输入框右侧，按坐标找同排的第二个 svg
        tagged = await page.evaluate(
            """() => {
                const list = document.querySelectorAll('[contenteditable="true"]');
                const composer = list[list.length - 1];
                if (!composer) return false;
                const cr = composer.getBoundingClientRect();
                const svgs = Array.from(document.querySelectorAll('svg'))
                    .map(el => ({el, r: el.getBoundingClientRect()}))
                    .filter(x => x.r.width > 0 && x.r.height > 0
                        && x.r.x > cr.right
                        && x.r.y >= cr.y - 40 && x.r.y <= cr.y + cr.height + 40)
                    .sort((a, b) => a.r.x - b.r.x);
                if (svgs.length < 2) return false;
                svgs[1].el.setAttribute('data-spark-emoji', '1');
                return true;
            }"""
        )
        try:
            if tagged:
                await page.locator('[data-spark-emoji="1"]').first.click()
            else:
                await page.mouse.click(box["x"] + box["width"] + 80, box["y"] + box["height"] / 2)
        finally:
            if tagged:
                await page.evaluate(
                    """() => document.querySelectorAll('[data-spark-emoji]')
                        .forEach(el => el.removeAttribute('data-spark-emoji'))"""
                )

        panel = page.locator(".componentsemojiemojiPanel")
        try:
            await expect(panel).to_be_visible(timeout=3500)
        except (AssertionError, PlaywrightError):
            return False

        items = page.locator(".emojiEmojiItememojiItem")
        count = await items.count()
        if count == 0:
            await page.keyboard.press("Escape")
            return False

        # 固定选「早上好」贴图；按资源 ID 匹配，找不到时用同一表情包内的固定序号兜底
        tagged = await page.evaluate(
            """({resourceId, fallbackIndex}) => {
                const items = Array.from(document.querySelectorAll('.emojiEmojiItememojiItem'));
                if (!items.length) return false;
                let target = items.find(it => {
                    const img = it.querySelector('img');
                    return img && (img.getAttribute('src') || '').includes(resourceId);
                });
                if (!target) target = items[fallbackIndex] || items[items.length - 1];
                target.setAttribute('data-spark-sticker', '1');
                return true;
            }""",
            {"resourceId": self.sticker_resource_id, "fallbackIndex": self.sticker_fallback_index},
        )
        if not tagged:
            await page.keyboard.press("Escape")
            return False
        try:
            await page.locator('[data-spark-sticker="1"]').click()
        except PlaywrightError as exc:
            raise SendUnverified(f"点击表情时页面异常，无法确认是否已发送：{exc}") from exc
        finally:
            await page.evaluate(
                """() => document.querySelectorAll('[data-spark-sticker]')
                    .forEach(el => el.removeAttribute('data-spark-sticker'))"""
            )

        await page.wait_for_timeout(1500)
        await self.ensure_not_blocked(page)
        try:
            still_open = await panel.is_visible()
        except PlaywrightError:
            still_open = False
        if still_open:
            raise SendUnverified("点击表情后表情面板未关闭，无法确认是否已发出")
        return True

    async def _find_in_list(self, page: Page, name: str, max_scrolls: int = 60) -> Locator | None:
        """抖音顶部的搜索只索引联系人，很多会话搜不到，所以直接在会话列表里滚动查找。

        列表是虚拟滚动，且名字和火花数可能渲染在同一个区域内，这里用 JS 按
        文本精确匹配、并按横坐标排除右侧未读角标，再标记出目标元素点击。
        """
        # 每次从列表顶部开始，避免目标在当前滚动位置上方而找不到
        await page.mouse.move(150, 400)
        for _ in range(10):
            await page.mouse.wheel(0, -3000)
            await page.wait_for_timeout(120)

        for _ in range(max_scrolls):
            await page.evaluate(
                """() => document.querySelectorAll('[data-spark-target]')
                    .forEach(el => el.removeAttribute('data-spark-target'))"""
            )
            found = await page.evaluate(
                """(name) => {
                    const norm = (s) => (s || '').replace(/[\\s\\u00a0\\u200b-\\u200d\\u3164\\ufe0d\\ufe0f\\ufff4\\ufff9-\\ufffb]/g, '');
                    const target = norm(name);
                    const leaves = Array.from(document.querySelectorAll('div,span,p,a'))
                        .filter(el => el.children.length === 0);
                    for (const el of leaves) {
                        if (norm(el.textContent) !== target) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (rect.x > 240) continue;  // 排除右侧未读角标/时间
                        el.setAttribute('data-spark-target', '1');
                        return true;
                    }
                    // 名字外层带子元素（例如表情）时，叶节点匹配不到，退化为小尺寸容器匹配
                    for (const el of Array.from(document.querySelectorAll('div,span,p,a'))) {
                        if (norm(el.innerText) !== target) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (rect.x > 240 || rect.width > 200 || rect.height > 40) continue;
                        el.setAttribute('data-spark-target', '1');
                        return true;
                    }
                    return false;
                }""",
                name,
            )
            if found:
                return page.locator('[data-spark-target="1"]').first
            await page.mouse.move(150, 400)
            await page.mouse.wheel(0, 700)
            await page.wait_for_timeout(600)
        return None

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
        # 抖音私信没有文字发送按钮，按回车发送（send_with_enter = True）
        return None


__all__ = ["DouyinAdapter"]
