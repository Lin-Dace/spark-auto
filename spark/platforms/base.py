"""平台适配器基类：弹性定位、发送流程、异常类型。"""

from __future__ import annotations

import abc

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page, expect

from ..config import Friend
from ..humanize import typing_delay_ms

# 页面出现这些提示时，说明触发了验证码 / 风控 / 频繁限制，应当立即停止
BLOCK_PATTERNS = (
    "安全验证",
    "验证码",
    "操作过于频繁",
    "操作频繁",
    "发送过于频繁",
    "请稍后再试",
    "账号存在异常",
    "账号异常",
    "登录已过期",
    "发送失败",
    "消息发送失败",
)


class SparkError(Exception):
    """工具内可预期的异常。"""


class LoginRequired(SparkError):
    """登录态缺失或已失效。"""


class LayoutChanged(SparkError):
    """页面结构变化，找不到关键元素。"""


class SendUnverified(SparkError):
    """点击发送后无法确认消息已发出（不重试，避免重复发送）。"""


class TransientFailure(SparkError):
    """页面操作/网络抖动，可在有限次数内重试。"""


class RestrictionDetected(SparkError):
    """命中验证码 / 风控 / 频繁提示，需要立即停止。"""


async def first_visible(candidates: list[Locator], timeout_ms: int = 2500) -> Locator | None:
    """按顺序尝试每个候选定位器，返回第一个可见的元素。"""
    for locator in candidates:
        try:
            await expect(locator.first).to_be_visible(timeout=timeout_ms)
            return locator.first
        except (AssertionError, PlaywrightError):
            continue
    return None


async def any_text_visible(page: Page, texts: tuple[str, ...]) -> bool:
    """页面是否出现其中任意一段文本（用于判断登录态）。"""
    for text in texts:
        try:
            if await page.get_by_text(text, exact=False).first.is_visible():
                return True
        except PlaywrightError:
            continue
    return False


async def fill_composer(page: Page, composer: Locator, text: str) -> None:
    """普通输入框用 fill；富文本编辑器逐字输入，避免编辑器状态没同步导致回车发不出去。"""
    try:
        editable = await composer.get_attribute("contenteditable")
    except PlaywrightError:
        editable = None

    if editable is None or editable.lower() != "true":
        try:
            await composer.fill(text)
            return
        except PlaywrightError:
            pass

    await composer.click()
    try:
        await page.keyboard.type(text, delay=typing_delay_ms())
    except PlaywrightError as exc:
        raise TransientFailure(f"输入文案失败：{exc}") from exc


class PlatformAdapter(abc.ABC):
    """各平台只负责「定位元素」，发送流程统一在基类里。"""

    name: str = ""
    label: str = ""
    # 登录后才会出现的会话 Cookie，用来避免把「页面还没加载出登录按钮」误判为已登录
    LOGIN_COOKIE_NAMES: tuple[str, ...] = ()
    # 部分平台没有发送按钮，输入框里回车即发送
    send_with_enter: bool = False

    # 是否支持发送表情包（网页版表情面板）
    supports_sticker: bool = False
    # 表情包资源 ID / 在表情面板中的兜底序号，由配置注入
    sticker_resource_id: str = "1687263059740"
    sticker_fallback_index: int = 12

    def __init__(self, messages_url: str) -> None:
        self.messages_url = messages_url

    async def send_sticker(self, page: Page, friend: Friend) -> bool:
        """尝试发送表情包；返回 False 表示当前页面不支持，调用方可回退到文字。"""
        return False

    async def has_login_cookie(self, page: Page) -> bool:
        if not self.LOGIN_COOKIE_NAMES:
            return True
        try:
            cookies = await page.context.cookies()
        except PlaywrightError:
            return False
        present = {str(cookie.get("name")) for cookie in cookies}
        return any(name in present for name in self.LOGIN_COOKIE_NAMES)

    async def open(self, page: Page) -> None:
        try:
            await page.goto(self.messages_url, wait_until="domcontentloaded")
        except PlaywrightError as exc:
            raise TransientFailure(f"打开私信页面失败：{exc}") from exc
        await page.wait_for_timeout(1500)
        await self.ensure_not_blocked(page)

    async def ensure_not_blocked(self, page: Page) -> None:
        try:
            body_text = await page.locator("body").inner_text(timeout=5000)
        except PlaywrightError:
            return
        for pattern in BLOCK_PATTERNS:
            if pattern in body_text:
                raise RestrictionDetected(f"页面出现提示：{pattern}")

    async def send_message(self, page: Page, friend: Friend, text: str) -> None:
        """定位聊天 -> 输入 -> 发送 -> 校验。点击发送之后不再抛出可重试异常。"""
        try:
            await self.open_chat(page, friend)
            await self.ensure_not_blocked(page)
            composer = await self.find_composer(page)
            if composer is None:
                raise LayoutChanged("找不到聊天输入框（网页版私信可能不可用）")
            await fill_composer(page, composer, text)
            await page.wait_for_timeout(300)
            if not self.send_with_enter:
                button = await self.find_send_button(page)
                if button is None:
                    raise LayoutChanged("找不到发送按钮")
        except PlaywrightError as exc:
            raise TransientFailure(f"页面操作异常：{exc}") from exc

        try:
            if self.send_with_enter:
                # 输入完成后焦点仍在编辑器里，直接回车；重新点击可能因编辑器重渲染而超时
                await page.keyboard.press("Enter")
            else:
                await button.click()
        except PlaywrightError as exc:
            raise SendUnverified(f"点击发送按钮时页面异常，无法确认是否已发送：{exc}") from exc

        await page.wait_for_timeout(1800)
        await self.ensure_not_blocked(page)
        if not await self.verify_sent(page, text):
            raise SendUnverified("点击发送后未能确认消息已发出")

    async def verify_sent(self, page: Page, text: str) -> bool:
        composer = await self.find_composer(page)
        if composer is not None:
            try:
                remaining = (await composer.inner_text()).strip()
            except PlaywrightError:
                remaining = ""
            if not remaining:
                return True

        snippet = text[:12]
        try:
            return await page.get_by_text(snippet, exact=False).last.is_visible()
        except PlaywrightError:
            return False

    @abc.abstractmethod
    async def is_logged_in(self, page: Page) -> bool: ...

    @abc.abstractmethod
    async def open_chat(self, page: Page, friend: Friend) -> None: ...

    @abc.abstractmethod
    async def find_composer(self, page: Page) -> Locator | None: ...

    @abc.abstractmethod
    async def find_send_button(self, page: Page) -> Locator | None: ...


__all__ = [
    "BLOCK_PATTERNS",
    "LayoutChanged",
    "LoginRequired",
    "PlatformAdapter",
    "RestrictionDetected",
    "SendUnverified",
    "SparkError",
    "TransientFailure",
    "any_text_visible",
    "first_visible",
]
