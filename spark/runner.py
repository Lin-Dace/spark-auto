"""发送调度：好友去重、每日一次、随机间隔、失败即停。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .browser import browser_context
from .config import AppConfig, Friend
from .humanize import pick_message, sleep_between
from .platforms import (
    LayoutChanged,
    LoginRequired,
    PlatformAdapter,
    RestrictionDetected,
    SendUnverified,
    TransientFailure,
    create_adapter,
)
from .records import SentRecords


class AbortRun(Exception):
    """命中验证码 / 风控 / 频繁提示，整轮立即停止。"""


@dataclass
class RunSummary:
    sent: int = 0
    skipped: int = 0
    failed: int = 0

    def as_text(self) -> str:
        return f"成功 {self.sent} 人，跳过 {self.skipped} 人，失败 {self.failed} 人"


async def run_once(
    config: AppConfig,
    friends_by_platform: dict[str, list[Friend]],
    records: SentRecords,
    logger: logging.Logger,
) -> RunSummary:
    summary = RunSummary()

    for platform, platform_config in config.platforms.items():
        if not platform_config.enabled:
            logger.info("[%s] 已在 config.json 中关闭，跳过", platform_config.label)
            continue

        friends = friends_by_platform.get(platform, [])
        if not friends:
            logger.info("[%s] friends.json 中没有可用好友，跳过", platform_config.label)
            continue

        pending = [friend for friend in friends if not records.has_sent_today(platform, friend.key)]
        already_sent = len(friends) - len(pending)
        if already_sent:
            summary.skipped += already_sent
            logger.info("[%s] 今日已发送 %d 人，本次跳过", platform_config.label, already_sent)
        if not pending:
            continue

        state_path = config.state_path(platform)
        if not state_path.exists():
            logger.error(
                "[%s] 缺少登录态文件 %s，请先执行：python main.py login --platform %s",
                platform_config.label,
                state_path,
                platform,
            )
            summary.skipped += len(pending)
            continue

        adapter = create_adapter(platform, platform_config.messages_url)
        adapter.sticker_resource_id = config.sticker_resource_id
        adapter.sticker_fallback_index = config.sticker_fallback_index
        completed = 0
        try:
            async with browser_context(config, platform) as context:
                page = await context.new_page()
                await adapter.open(page)
                if not await adapter.is_logged_in(page):
                    raise LoginRequired("登录态已失效")

                logger.info("[%s] 开始发送，待发送 %d 人", platform_config.label, len(pending))
                for position, friend in enumerate(pending):
                    if not await adapter.is_logged_in(page):
                        raise LoginRequired("发送过程中登录态失效")

                    sent_ok = await _send_to_friend(
                        adapter, page, config, records, platform, platform_config.label, friend, logger
                    )
                    completed += 1
                    if sent_ok:
                        summary.sent += 1
                    else:
                        summary.failed += 1

                    if position < len(pending) - 1:
                        delay = await sleep_between(*config.friend_interval_seconds)
                        logger.info("[%s] 间隔 %.0f 秒后处理下一位好友", platform_config.label, delay)

        except LoginRequired as exc:
            remaining = len(pending) - completed
            summary.skipped += remaining
            logger.error(
                "[%s] %s，剩余 %d 人跳过；请重新执行 python main.py login --platform %s",
                platform_config.label,
                exc,
                remaining,
                platform,
            )
        except RestrictionDetected as exc:
            logger.error("[%s] 检测到验证码/风控/频繁提示（%s），本轮立即中止", platform_config.label, exc)
            raise AbortRun(str(exc)) from exc
        except PlaywrightError as exc:
            remaining = len(pending) - completed
            summary.failed += remaining
            logger.error(
                "[%s] 浏览器/网络异常：%s，剩余 %d 人跳过（若提示缺少浏览器，请执行 playwright install chromium）",
                platform_config.label,
                exc,
                remaining,
            )
        except Exception as exc:  # noqa: BLE001 - 兜底，避免单个平台崩掉整轮
            remaining = len(pending) - completed
            summary.failed += remaining
            logger.exception("[%s] 未预期异常：%s，剩余 %d 人跳过", platform_config.label, exc, remaining)

    return summary


async def _send_to_friend(
    adapter: PlatformAdapter,
    page: Page,
    config: AppConfig,
    records: SentRecords,
    platform: str,
    label: str,
    friend: Friend,
    logger: logging.Logger,
) -> bool:
    if config.sticker_enabled and adapter.supports_sticker:
        try:
            sticker_sent = await adapter.send_sticker(page, friend)
        except RestrictionDetected:
            raise
        except SendUnverified as exc:
            # 点击贴图后无法确认结果，不重试也不补发文字，避免同一天发两条
            logger.error("[%s] 给 %s 发表情包后无法确认是否发出，跳过：%s", label, friend.display, exc)
            return False
        except (LayoutChanged, TransientFailure, PlaywrightError) as exc:
            logger.warning("[%s] 给 %s 发表情包失败，改用文案：%s", label, friend.display, exc)
            sticker_sent = False
        else:
            if sticker_sent:
                sent_at = records.add(platform, friend.key, friend.display, "[早上好表情包]")
                logger.info(
                    "[%s] 已发送早上好表情包给 %s（%s）",
                    label,
                    friend.display,
                    sent_at.strftime("%Y-%m-%d %H:%M:%S"),
                )
                return True

    text = pick_message(config.message_pool, records.last_message(platform, friend.key))
    attempts = config.max_retries + 1

    for attempt in range(1, attempts + 1):
        try:
            await adapter.send_message(page, friend, text)
        except RestrictionDetected:
            raise
        except (LayoutChanged, SendUnverified) as exc:
            # 结构异常 / 无法确认结果：直接跳过，避免重复发送
            logger.error("[%s] 放弃发送给 %s：%s", label, friend.display, exc)
            return False
        except TransientFailure as exc:
            logger.warning(
                "[%s] 发送给 %s 第 %d/%d 次尝试失败：%s",
                label,
                friend.display,
                attempt,
                attempts,
                exc,
            )
            if attempt >= attempts:
                logger.error("[%s] 放弃发送给 %s：多次尝试仍失败", label, friend.display)
                return False
            await page.wait_for_timeout(3000)
            try:
                await adapter.open(page)
            except RestrictionDetected:
                raise
            except Exception:  # noqa: BLE001 - 重新进入私信页失败时交给下一轮尝试
                pass
        else:
            sent_at = records.add(platform, friend.key, friend.display, text)
            logger.info(
                "[%s] 已发送给 %s（%s）：%s",
                label,
                friend.display,
                sent_at.strftime("%Y-%m-%d %H:%M:%S"),
                text,
            )
            return True

    return False


__all__ = ["AbortRun", "RunSummary", "run_once"]
