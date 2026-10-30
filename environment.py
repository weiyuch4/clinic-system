"""Which deployment this process is (production, staging, local) and the guards that keep a test copy harmless.

A copy is a test copy only when APP_ENV says so (APP_ENV=staging), set by hand on the staging service.
Railway's own environment name is shown for information but never switches the guards on, so a renamed
production environment can't silently stop real LINE messages. A test copy shows a 測試環境 label on every
page and never sends LINE messages, even if someone pastes a real channel token into its settings."""
import logging
import os
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

_APP_ENV = os.environ.get("APP_ENV", "").strip().lower()
NAME = _APP_ENV or os.environ.get("RAILWAY_ENVIRONMENT_NAME") or ""
IS_TEST_COPY = bool(_APP_ENV) and _APP_ENV != "production"
COMMIT = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7]


def _is_line_host(host: str) -> bool:
    return host == "line.me" or host.endswith(".line.me")


def install_outbound_guard() -> None:
    """In a test copy, refuse every LINE API call that changes something (sends, broadcasts, webhook and
    LIFF setup). Reads (GET) still work so settings pages load. Patched on requests.Session, which every
    requests.get/post goes through, so a new sending path can't forget the check."""
    if not IS_TEST_COPY:
        return
    original = requests.Session.request

    def guarded(self, method, url, *args, **kwargs):
        host = urlsplit(str(url)).hostname or ""
        if str(method).upper() != "GET" and _is_line_host(host):
            logger.warning("Test copy (%s): blocked %s %s", NAME, method, host)
            raise requests.exceptions.ConnectionError(f"測試環境不會送出 LINE（{method} {host}）")
        return original(self, method, url, *args, **kwargs)

    requests.Session.request = guarded


BANNER_HTML = (
    '<div role="status" style="position:fixed;top:calc(env(safe-area-inset-top,0px) + 6px);left:50%;'
    'transform:translateX(-50%);z-index:2147483647;pointer-events:none;background:#b45309;color:#fff;'
    'font:600 12px/1 system-ui,sans-serif;padding:6px 12px;border-radius:999px;white-space:nowrap;'
    'box-shadow:0 2px 8px rgba(0,0,0,.25)">測試環境 · 資料不是真的，不會傳 LINE</div>'
)
