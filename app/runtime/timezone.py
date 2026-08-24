import logging
from datetime import datetime, timezone, tzinfo
from typing import Any, Dict, Optional, Tuple

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

from app.runtime.state import load_runtime_config

logger = logging.getLogger("hermes.timezone")


def get_effective_timezone(config: Optional[Dict[str, Any]] = None) -> Tuple[tzinfo, str, Optional[str]]:
    """
    Resolves the effective timezone for scheduling and calendar operations.
    Returns: (tzinfo_obj, tz_name, optional_warning)
    """
    if config is None:
        config = load_runtime_config()

    # Support nested runtime.timezone or top-level timezone
    runtime_sec = config.get("runtime", {}) if isinstance(config.get("runtime"), dict) else {}
    tz_str = runtime_sec.get("timezone") or config.get("timezone", "local")

    if not tz_str or str(tz_str).lower() in ("local", "auto"):
        local_tz = datetime.now().astimezone().tzinfo
        tz_name = getattr(local_tz, "key", None) or getattr(local_tz, "zone", None)
        if not tz_name:
            warning = "System local timezone is a fixed offset without IANA identity; consider setting an explicit IANA timezone in config/runtime.yaml."
            return local_tz or timezone.utc, "local", warning
        return local_tz, str(tz_name), None

    tz_str = str(tz_str).strip()
    try:
        zi = zoneinfo.ZoneInfo(tz_str)
        return zi, tz_str, None
    except Exception:
        warning = f"Invalid timezone '{tz_str}'; fell back to UTC."
        logger.warning(warning)
        return timezone.utc, "UTC", warning


def to_runtime_local(now: datetime, config: Optional[Dict[str, Any]] = None) -> datetime:
    """
    Converts a datetime to the runtime configured local timezone.
    Strictly requires timezone-aware datetimes; naive datetimes are normalized to UTC with warning.
    """
    if now.tzinfo is None:
        logger.warning("Naive datetime passed to to_runtime_local; explicitly normalizing to UTC.")
        now = now.replace(tzinfo=timezone.utc)

    eff_tz, _, _ = get_effective_timezone(config)
    return now.astimezone(eff_tz)


def runtime_date_string(now: datetime, config: Optional[Dict[str, Any]] = None) -> str:
    """
    Returns the YYYY-MM-DD calendar date string in the runtime configured local timezone.
    """
    return to_runtime_local(now, config).strftime("%Y-%m-%d")
