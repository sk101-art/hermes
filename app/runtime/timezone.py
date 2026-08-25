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
    tz_str = runtime_sec.get("timezone") or config.get("timezone", "Asia/Kolkata")

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


def runtime_now_utc() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def runtime_local_datetime(now: datetime, config: Optional[Dict[str, Any]] = None) -> datetime:
    """Normalizes/converts UTC datetime to local timezone."""
    return to_runtime_local(now, config)


def runtime_date(now: datetime, config: Optional[Dict[str, Any]] = None) -> str:
    """Returns the YYYY-MM-DD calendar date string in the runtime configured local timezone."""
    return runtime_date_string(now, config)


def runtime_day_bounds_utc(date_val: Any, config: Optional[Dict[str, Any]] = None) -> Tuple[datetime, datetime]:
    """
    Computes start and end boundaries of a local date in UTC.
    The returned datetimes are timezone-aware in UTC timezone.
    """
    from datetime import date
    if isinstance(date_val, str):
        date_clean = date_val.strip().replace("-", "")
        dt_val = datetime.strptime(date_clean, "%Y%m%d").date()
    elif isinstance(date_val, datetime):
        dt_val = date_val.date()
    elif isinstance(date_val, date):
        dt_val = date_val
    else:
        raise ValueError(f"Unsupported date type: {type(date_val)}")

    eff_tz, _, _ = get_effective_timezone(config)
    local_start = datetime.combine(dt_val, datetime.min.time()).replace(tzinfo=eff_tz)
    local_end = datetime.combine(dt_val, datetime.max.time()).replace(tzinfo=eff_tz)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def format_runtime_timestamp(value: Any, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Converts a datetime (or ISO string) to the standard runtime format string.
    If value is naive, it's normalized to UTC before converting to local.
    Returns: '25 Aug 2026, 8:14 AM IST'
    """
    if not value:
        return None
    
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value # Return as-is if unparseable
            
    if not isinstance(value, datetime):
        return str(value)
        
    local_dt = to_runtime_local(value, config)
    eff_tz, tz_name, _ = get_effective_timezone(config)
    
    # Try to get short timezone name (e.g. IST)
    tz_short = local_dt.tzname() or tz_name
    if tz_short == "Asia/Kolkata":
        tz_short = "IST"
        
    return local_dt.strftime("%d %b %Y, %I:%M %p ") + tz_short
