import re
from typing import Any, Optional, Tuple

# Redaction Patterns
BEARER_PATTERN = re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.]+', re.IGNORECASE)
PARAM_SECRET_PATTERN = re.compile(
    r'(?P<key>(?:api[_-]?key|apikey|token|secret|password|auth|access[_-]?token|client[_-]?secret))\s*[:=]\s*(?P<val>[^\s&,"\']+)',
    re.IGNORECASE,
)
URL_CRED_PATTERN = re.compile(r'https?://[^:\s@]+:[^@\s]+@', re.IGNORECASE)
AUTH_HEADER_PATTERN = re.compile(r'(Authorization\s*:\s*)(?:Basic|Digest|Bearer)\s+[^\r\n]+', re.IGNORECASE)

# File Paths (Windows, UNC, and Linux/macOS user paths)
WINDOWS_PATH_PATTERN = re.compile(r'[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\r\n:;\'"<>|]+', re.IGNORECASE)
UNC_PATH_PATTERN = re.compile(r'\\\\[a-zA-Z0-9._-]+\\[^\r\n:;\'"<>|\s]+', re.IGNORECASE)
UNIX_PATH_PATTERN = re.compile(r'/(?:home|Users|root)/[^\r\n:;\'"<>|\s]+', re.IGNORECASE)


def classify_error_category(err_str: str) -> str:
    """Classifies an error string into a canonical, safe error category."""
    if not err_str:
        return "unknown_error"

    lower = err_str.lower()
    if "429" in lower or "rate limit" in lower or "too many requests" in lower or "quota" in lower:
        return "rate_limit"
    if "401" in lower or "403" in lower or "unauthorized" in lower or "forbidden" in lower or "auth" in lower or "permission" in lower:
        return "auth_error"
    if "timeout" in lower or "timed out" in lower or "deadline" in lower:
        return "timeout"
    if (
        "connection" in lower
        or "network" in lower
        or "dns" in lower
        or "nodename" in lower
        or "socket" in lower
        or "unreachable" in lower
        or "offline" in lower
        or "gaierror" in lower
        or "refused" in lower
        or "reset" in lower
    ):
        return "network_error"
    if "disk" in lower or "no space" in lower or "low_space" in lower or "enospc" in lower:
        return "disk_space"
    if "sqlite" in lower or "database" in lower or "corrupt" in lower or "locked" in lower or "operationalerror" in lower or "integrityerror" in lower:
        return "database_error"
    if "validation" in lower or "json" in lower or "schema" in lower or "keyerror" in lower or "attributeerror" in lower or "typeerror" in lower:
        return "schema_error"
    if "export_failed" in lower or "interrupted" in lower or "runtimeerror" in lower or "blocked" in lower:
        return "runtime_error"

    return "unknown_error"


def sanitize_error(error_input: Any, max_length: int = 300) -> Tuple[str, str]:
    """
    Sanitizes an error message by stripping sensitive credentials, tokens,
    and user filesystem paths, while preserving the key name and root cause.

    Returns:
        (error_category, sanitized_summary)
    """
    if error_input is None:
        return "unknown_error", "No error recorded"

    if isinstance(error_input, BaseException):
        raw = f"{type(error_input).__name__}: {str(error_input)}"
    else:
        raw = str(error_input)

    # 1. Truncate multi-line tracebacks to primary message / root cause line
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        return "unknown_error", "Unknown error"

    # Find the most meaningful line: in Python tracebacks, the last line is the exception description
    if len(lines) > 1 and "Traceback" in lines[0]:
        msg_line = lines[-1]
    elif len(lines) > 1 and any(err_term in lines[-1].lower() for err_term in ('error', 'exception', 'failed', 'failure', 'denied', 'refused')):
        msg_line = lines[-1]
    else:
        msg_line = lines[0]

    # 2. Redact Bearer tokens
    sanitized = BEARER_PATTERN.sub("Bearer [REDACTED]", msg_line)

    # 3. Redact Authorization headers
    sanitized = AUTH_HEADER_PATTERN.sub(r"\1[REDACTED]", sanitized)

    # 4. Redact sensitive parameter values (preserve key name)
    sanitized = PARAM_SECRET_PATTERN.sub(r"\g<key>=[REDACTED]", sanitized)

    # 5. Redact embedded URL credentials
    sanitized = URL_CRED_PATTERN.sub("https://[REDACTED]@", sanitized)

    # 6. Redact absolute local user file paths
    sanitized = WINDOWS_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)
    sanitized = UNC_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)
    sanitized = UNIX_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)

    # 7. Normalize whitespace
    sanitized = " ".join(sanitized.split())

    # 8. Bound length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + "..."

    category = classify_error_category(sanitized)
    return category, sanitized


def sanitize_error_summary(text: Optional[str], max_length: int = 300) -> Optional[str]:
    """Sanitizes an error summary string, returning None if input is None."""
    if text is None:
        return None
    _, summary = sanitize_error(text, max_length=max_length)
    return summary


def sanitize_error_category(category: Optional[str], text: Optional[str]) -> Optional[str]:
    """Returns a valid category or classifies the text if category is missing."""
    if category and category != "unknown" and category != "unknown_error":
        return category
    if text:
        cat, _ = sanitize_error(text)
        return cat
    return None


def sanitize_runtime_data(data: Any) -> Any:
    """Recursively sanitizes sensitive patterns from nested strings, dicts, and lists."""
    if isinstance(data, str):
        # Redact Bearer, Auth headers, params, URLs, paths
        sanitized = BEARER_PATTERN.sub("Bearer [REDACTED]", data)
        sanitized = AUTH_HEADER_PATTERN.sub(r"\1[REDACTED]", sanitized)
        sanitized = PARAM_SECRET_PATTERN.sub(r"\g<key>=[REDACTED]", sanitized)
        sanitized = URL_CRED_PATTERN.sub("https://[REDACTED]@", sanitized)
        sanitized = WINDOWS_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)
        sanitized = UNC_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)
        sanitized = UNIX_PATH_PATTERN.sub("[LOCAL_PATH]", sanitized)
        return sanitized
    elif isinstance(data, dict):
        return {k: sanitize_runtime_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_runtime_data(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_runtime_data(item) for item in data)
    return data
