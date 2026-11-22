"""平台适配器工厂。"""

from __future__ import annotations

from .base import (
    LayoutChanged,
    LoginRequired,
    PlatformAdapter,
    RestrictionDetected,
    SendUnverified,
    SparkError,
    TransientFailure,
)
from .douyin import DouyinAdapter
from .kuaishou import KuaishouAdapter

ADAPTERS: dict[str, type[PlatformAdapter]] = {
    "douyin": DouyinAdapter,
    "kuaishou": KuaishouAdapter,
}


def create_adapter(platform: str, messages_url: str) -> PlatformAdapter:
    try:
        adapter_cls = ADAPTERS[platform]
    except KeyError as exc:
        raise ValueError(f"不支持的平台：{platform}") from exc
    return adapter_cls(messages_url)


__all__ = [
    "ADAPTERS",
    "LayoutChanged",
    "LoginRequired",
    "PlatformAdapter",
    "RestrictionDetected",
    "SendUnverified",
    "SparkError",
    "TransientFailure",
    "create_adapter",
]
