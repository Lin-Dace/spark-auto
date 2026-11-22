"""配置加载与校验：config.json、friends.json。"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
FRIENDS_PATH = BASE_DIR / "friends.json"
STATE_DIR = BASE_DIR / "state"
LOG_DIR = BASE_DIR / "logs"
RECORD_DIR = BASE_DIR / "records"

PLATFORMS = ("douyin", "kuaishou")
PLATFORM_LABELS = {"douyin": "抖音", "kuaishou": "快手"}

DEFAULT_MESSAGES_URL = {
    "douyin": "https://www.douyin.com/chat",
    "kuaishou": "https://www.kuaishou.com/message",
}


class ConfigError(ValueError):
    """配置内容不合法。"""


def _read_json(path: Path) -> dict:
    if not path.exists():
        hint = "（可复制 friends.example.json 为 friends.json 后填写）" if path == FRIENDS_PATH else ""
        raise ConfigError(f"找不到配置文件：{path}{hint}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} 不是合法的 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} 顶层必须是对象")
    return data


def _parse_clock(raw: object, field_name: str) -> time:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(raw).strip())
    if not match:
        raise ConfigError(f"{field_name} 需要 HH:MM 格式，当前为 {raw!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ConfigError(f"{field_name} 时间不合法：{raw!r}")
    return time(hour, minute)


@dataclass(frozen=True)
class SendWindow:
    """每日发送时间窗口，实际发送时刻在窗口内随机。"""

    start: time
    end: time
    jitter_seconds: int = 0

    def random_moment(self, reference: datetime) -> datetime:
        start_dt = datetime.combine(reference.date(), self.start)
        end_dt = datetime.combine(reference.date(), self.end)
        span = int((end_dt - start_dt).total_seconds())
        if span <= 0:
            raise ConfigError("send_window.end 必须晚于 send_window.start（暂不支持跨零点）")
        offset = random.randint(0, span)
        if self.jitter_seconds > 0:
            offset += random.randint(-self.jitter_seconds, self.jitter_seconds)
        offset = max(0, min(span, offset))
        return start_dt + timedelta(seconds=offset)


@dataclass(frozen=True)
class PlatformConfig:
    name: str
    enabled: bool
    messages_url: str

    @property
    def label(self) -> str:
        return PLATFORM_LABELS.get(self.name, self.name)


@dataclass(frozen=True)
class Friend:
    name: str
    user_id: str = ""
    enabled: bool = True

    @property
    def key(self) -> str:
        """用于去重与发送记录的稳定标识。"""
        return (self.user_id or self.name).strip().casefold()

    @property
    def display(self) -> str:
        return f"{self.name}（{self.user_id}）" if self.user_id else self.name


@dataclass(frozen=True)
class AppConfig:
    window: SendWindow
    friend_interval_seconds: tuple[int, int]
    max_retries: int
    headless: bool
    browser_channel: str
    sticker_enabled: bool
    platforms: dict[str, PlatformConfig]
    message_pool: tuple[str, ...]
    sticker_resource_id: str = "1687263059740"
    sticker_fallback_index: int = 12

    @property
    def log_path(self) -> Path:
        return LOG_DIR / "spark.log"

    @property
    def record_path(self) -> Path:
        return RECORD_DIR / "sent.jsonl"

    def state_path(self, platform: str) -> Path:
        return STATE_DIR / f"storage_state.{platform}.json"


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    data = _read_json(path)

    window_raw = data.get("send_window") or {}
    if not isinstance(window_raw, dict):
        raise ConfigError("send_window 必须是对象")
    window = SendWindow(
        start=_parse_clock(window_raw.get("start", "08:00"), "send_window.start"),
        end=_parse_clock(window_raw.get("end", "22:00"), "send_window.end"),
        jitter_seconds=int(window_raw.get("jitter_seconds", 0) or 0),
    )
    if window.jitter_seconds < 0:
        raise ConfigError("send_window.jitter_seconds 不能为负数")

    interval_raw = data.get("friend_interval_seconds") or {}
    if not isinstance(interval_raw, dict):
        raise ConfigError("friend_interval_seconds 必须是对象")
    interval_low = int(interval_raw.get("min", 5))
    interval_high = int(interval_raw.get("max", 60))
    if interval_low < 1 or interval_high < interval_low:
        raise ConfigError("friend_interval_seconds 需要满足 1 <= min <= max")

    platforms_raw = data.get("platforms") or {}
    if not isinstance(platforms_raw, dict):
        raise ConfigError("platforms 必须是对象")
    platforms: dict[str, PlatformConfig] = {}
    for name in PLATFORMS:
        item = platforms_raw.get(name) or {}
        if not isinstance(item, dict):
            raise ConfigError(f"platforms.{name} 必须是对象")
        url = str(item.get("messages_url") or DEFAULT_MESSAGES_URL[name]).strip()
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"platforms.{name}.messages_url 必须是 http(s) 地址")
        platforms[name] = PlatformConfig(
            name=name,
            enabled=bool(item.get("enabled", True)),
            messages_url=url,
        )

    pool_raw = data.get("message_pool") or []
    if not isinstance(pool_raw, list):
        raise ConfigError("message_pool 必须是数组")
    pool = tuple(str(item).strip() for item in pool_raw if str(item).strip())
    if not pool:
        raise ConfigError("message_pool 至少需要一条非空文案")

    max_retries = int(data.get("max_retries", 2))
    if max_retries < 0:
        raise ConfigError("max_retries 不能为负数")

    sticker_resource_id = str(data.get("sticker_resource_id") or "1687263059740").strip()
    try:
        sticker_fallback_index = int(data.get("sticker_fallback_index", 12))
    except (TypeError, ValueError) as exc:
        raise ConfigError("sticker_fallback_index 必须是整数") from exc
    if sticker_fallback_index < 0:
        raise ConfigError("sticker_fallback_index 不能为负数")

    return AppConfig(
        window=window,
        friend_interval_seconds=(interval_low, interval_high),
        max_retries=max_retries,
        headless=bool(data.get("headless", True)),
        browser_channel=str(data.get("browser_channel") or "").strip().lower(),
        sticker_enabled=bool(data.get("sticker_enabled", True)),
        platforms=platforms,
        message_pool=pool,
        sticker_resource_id=sticker_resource_id,
        sticker_fallback_index=sticker_fallback_index,
    )


def _parse_friend(entry: object, platform: str, index: int) -> Friend:
    """好友条目支持字符串或对象两种写法。"""
    if isinstance(entry, str):
        name = entry.strip()
        if not name:
            raise ConfigError(f"friends.json 中 {platform} 第 {index + 1} 个好友为空")
        return Friend(name=name)
    if isinstance(entry, dict):
        name = str(entry.get("name") or "").strip()
        if not name:
            raise ConfigError(f"friends.json 中 {platform} 第 {index + 1} 个好友缺少 name")
        return Friend(
            name=name,
            user_id=str(entry.get("user_id") or "").strip(),
            enabled=bool(entry.get("enabled", True)),
        )
    raise ConfigError(f"friends.json 中 {platform} 第 {index + 1} 个好友格式不正确")


def load_friends(path: Path = FRIENDS_PATH) -> dict[str, list[Friend]]:
    data = _read_json(path)
    logger = logging.getLogger("spark")
    result: dict[str, list[Friend]] = {}

    for platform in PLATFORMS:
        raw_entries = data.get(platform) or []
        if not isinstance(raw_entries, list):
            raise ConfigError(f"friends.json 中 {platform} 应该是数组")
        seen: dict[str, Friend] = {}
        friends: list[Friend] = []
        for index, entry in enumerate(raw_entries):
            friend = _parse_friend(entry, platform, index)
            if not friend.enabled:
                logger.info("[%s] 好友 %s 已在 friends.json 中禁用，跳过", PLATFORM_LABELS[platform], friend.display)
                continue
            if friend.key in seen:
                logger.warning(
                    "[%s] 好友 %s 与 %s 标识重复，已自动去重",
                    PLATFORM_LABELS[platform],
                    friend.display,
                    seen[friend.key].display,
                )
                continue
            seen[friend.key] = friend
            friends.append(friend)
        result[platform] = friends

    return result
