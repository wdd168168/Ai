"""外部二进制解析：优先用系统 PATH 里的，找不到就用包里自带的 bin/。

托管环境不一定装了 ffmpeg，这里保证语音转码永远有可用的二进制。
"""
from __future__ import annotations

import os
import shutil

_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def resolve(configured: str, fallback: str = "") -> str:
    if not configured:
        return configured
    base = os.path.basename(configured)
    # 显式路径：直接用
    if os.sep in configured or configured.startswith("."):
        if os.path.exists(configured):
            return configured
    found = shutil.which(configured)
    if found:
        return found
    # 回退用规范名，不看用户配的自定义名
    canon = fallback or base
    for cand in (os.path.join(_ROOT, "bin", canon), os.path.join(os.getcwd(), "bin", canon)):
        if os.path.exists(cand):
            try:
                os.chmod(cand, 0o755)
            except OSError:
                pass
            return cand
    return configured


def available(configured: str, fallback: str = "") -> bool:
    p = resolve(configured, fallback)
    return bool(p) and (os.path.exists(p) if os.sep in p else bool(shutil.which(p)))
