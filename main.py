"""抖音 / 快手 每日续火花工具（个人自用）。

用法：
    python main.py login --platform all    # 首次扫码登录，保存本地登录态
    python main.py run                     # 立即执行一轮（今日已发送的会跳过）
    python main.py schedule                # 常驻，每天在配置的随机时间执行一次
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta

try:
    from spark.browser import interactive_login
    from spark.config import PLATFORMS, STATE_DIR, ConfigError, load_config, load_friends
    from spark.logging_setup import setup_logging
    from spark.records import SentRecords
    from spark.runner import AbortRun, run_once
except ModuleNotFoundError as exc:  # 首次运行缺少依赖时给出明确提示
    print(f"缺少依赖：{exc}\n请先执行：pip install -r requirements.txt 和 playwright install chromium")
    sys.exit(1)


def bootstrap():
    config = load_config()
    logger = setup_logging(config.log_path)
    friends = load_friends()
    records = SentRecords(config.record_path)
    return config, friends, records, logger


async def _sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, 900))


async def cmd_login(args: argparse.Namespace) -> int:
    config = load_config()
    logger = setup_logging(config.log_path)
    targets = PLATFORMS if args.platform == "all" else (args.platform,)
    for platform in targets:
        await interactive_login(config, platform)
    logger.info("登录流程结束，登录态位于：%s", STATE_DIR)
    return 0


async def _wait_for_random_moment(config, logger) -> bool:
    """等到今天的随机时刻；窗口已过则返回 False。"""
    now = datetime.now()
    if now.time() >= config.window.end:
        logger.info(
            "今天的发送窗口（%s-%s）已结束，本轮跳过",
            config.window.start.strftime("%H:%M"),
            config.window.end.strftime("%H:%M"),
        )
        return False

    target = config.window.random_moment(now)
    if target <= now:
        logger.info("今天的随机时间点（%s）已过，立即执行", target.strftime("%H:%M:%S"))
        return True

    logger.info("等待到今天的随机发送时间：%s", target.strftime("%Y-%m-%d %H:%M:%S"))
    await _sleep_until(target)
    return True


async def cmd_run(args: argparse.Namespace) -> int:
    config, friends, records, logger = bootstrap()
    logger.info("=== 开始执行（run 模式） ===")
    if args.random and not await _wait_for_random_moment(config, logger):
        logger.info("=== 本轮跳过 ===")
        return 0
    try:
        summary = await run_once(config, friends, records, logger)
    except AbortRun as exc:
        logger.error("本轮已中止：%s", exc)
        return 2
    logger.info("=== 本轮结束：%s ===", summary.as_text())
    return 0


async def cmd_schedule(_args: argparse.Namespace) -> int:
    config, friends, records, logger = bootstrap()
    logger.info("进入每日定时模式（Ctrl+C 退出）")

    while True:
        now = datetime.now()
        if now.time() >= config.window.end:
            next_day = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
            logger.info(
                "今天的发送窗口（%s-%s）已结束，等待 %s 再规划下一天",
                config.window.start.strftime("%H:%M"),
                config.window.end.strftime("%H:%M"),
                next_day.strftime("%Y-%m-%d %H:%M:%S"),
            )
            await _sleep_until(next_day)
            continue

        target = config.window.random_moment(now)
        if target <= now:
            delay = random.randint(5, 30)
            logger.info(
                "今天的随机时间点（%s）已过，%d 秒后立即执行；今日已发送的好友会自动跳过",
                target.strftime("%H:%M:%S"),
                delay,
            )
            await asyncio.sleep(delay)
        else:
            logger.info(
                "下次发送时间：%s（在 %s-%s 之间随机）",
                target.strftime("%Y-%m-%d %H:%M:%S"),
                config.window.start.strftime("%H:%M"),
                config.window.end.strftime("%H:%M"),
            )
            await _sleep_until(target)

        logger.info("=== 开始执行（schedule 模式） ===")
        try:
            summary = await run_once(config, friends, records, logger)
            logger.info("=== 本轮结束：%s ===", summary.as_text())
        except AbortRun as exc:
            logger.error("命中风控或验证提示，已中止本轮：%s", exc)

        next_day = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        logger.info("等待进入下一天计划：%s", next_day.strftime("%Y-%m-%d %H:%M:%S"))
        await _sleep_until(next_day)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抖音/快手每日续火花工具（个人自用，发送早上好表情包）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="扫码登录并保存本地登录态")
    login_parser.add_argument("--platform", choices=[*PLATFORMS, "all"], default="all")
    login_parser.set_defaults(func=cmd_login)

    run_parser = subparsers.add_parser("run", help="立即执行一轮发送")
    run_parser.add_argument(
        "--random",
        action="store_true",
        help="先在今天的随机时刻等待，再执行（配合 Windows 计划任务使用）",
    )
    run_parser.set_defaults(func=cmd_run)

    schedule_parser = subparsers.add_parser("schedule", help="常驻运行，每天随机时间发送一次")
    schedule_parser.set_defaults(func=cmd_schedule)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\n已退出")
        return 130
    except ConfigError as exc:
        print(f"配置错误：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
