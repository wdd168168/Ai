"""单进程启动入口（托管/轻量模式）。

生产推荐 docker compose（Postgres + Redis + 多进程）；这个入口用于：
- 单机快速试用（SQLite + 进程内队列）
- 平台托管一个可直接打开的后台

用法：python3 run.py   （PORT 默认 8800）
"""
from __future__ import annotations

import os
import sys

# 固定到项目根目录：SQLite、media、session、.env 的相对路径都以这里为基准，
# 不依赖进程是从哪个工作目录被拉起来的。
_BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_BASE)
for _sub in ("data", "data/media", "data/sessions"):
    os.makedirs(os.path.join(_BASE, _sub), exist_ok=True)

import uvicorn  # noqa: E402

# 兼容两种目录布局：app/ 与 run.py 同级；或代码在 backend/ 下
for _candidate in (_BASE, os.path.join(_BASE, "backend")):
    if os.path.isdir(os.path.join(_candidate, "app")) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)


def main() -> None:
    port = int(os.getenv("PORT", "8800"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        workers=1,
    )


if __name__ == "__main__":
    main()
