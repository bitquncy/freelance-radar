"""Project-wide constants and enums."""
from enum import Enum
from emoji_config import P


class _StrEnum(str, Enum):
    """Base class for string enums (compatible with Python 3.10+).

    Defines ``__str__`` explicitly: on Python 3.11 ``str()``, f-strings,
    ``%s`` and ``format()`` of a ``(str, Enum)`` all render
    ``"ClassName.MEMBER"`` (via ``Enum.__str__``/``__format__``), which
    leaked into user-visible filter reasons like
    ``"FilterReason.BUDGET_TOO_LOW (...)"``. This mirrors ``enum.StrEnum``
    semantics: every string coercion yields ``x.value``.
    """

    def __str__(self) -> str:
        return str(self.value)


class Priority(_StrEnum):
    """Vacancy priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceType(_StrEnum):
    """Source types for monitoring."""
    KWORK = "kwork"
    TELEGRAM = "telegram"


class EntityType(_StrEnum):
    """Entity types for blacklist."""
    VACANCY = "vacancy"
    CUSTOMER = "customer"


class Complexity(_StrEnum):
    """Complexity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class FilterReason(_StrEnum):
    """Filter reasons."""
    BLACKLISTED = "blacklisted"
    BUDGET_TOO_LOW = "budget_too_low"
    BUDGET_TOO_HIGH = "budget_too_high"
    BLACKLIST_WORD = "blacklist_word"
    NO_WHITELIST = "no_whitelist_words_matched"
    RATING_TOO_LOW = "customer_rating_too_low"
    TOO_MANY_PROPOSALS = "too_many_proposals"
    AI_SCORE_TOO_LOW = "ai_score_too_low"
    MATCH_TOO_LOW = "match_too_low"
    USER_BLACKLISTED = "user_blacklisted"


class Status(_StrEnum):
    """Vacancy status."""
    NEW = "new"
    ANALYZED = "analyzed"
    FILTERED = "filtered"
    RESPONDED = "responded"


# Emoji mapping
PRIORITY_EMOJI = {
    Priority.HIGH: f"{P.FIRE}",
    Priority.MEDIUM: "\u2b50",
    Priority.LOW: f"{P.PIN}",
}

PRIORITY_MAP = {
    Priority.HIGH: (f"{P.FIRE}", "High"),
    Priority.MEDIUM: ("\u2b50", "Medium"),
    Priority.LOW: (f"{P.PIN}", "Low"),
}

SOURCE_EMOJI = {
    SourceType.KWORK: f"{P.BRIEFCASE}",
    SourceType.TELEGRAM: f"{P.MEGAPHONE}",
}

STATUS_EMOJI = {
    Status.NEW: f"{P.NEW}",
    Status.ANALYZED: "\u2705",
    Status.FILTERED: f"{P.BAN}",
    Status.RESPONDED: f"{P.COMMENT}",
}

# Default values
DEFAULT_MIN_SCORE = 30
DEFAULT_MIN_MATCH = 20
DEFAULT_SCORE_BASE = 10

# Text formatting
BULLET = "\u2022"

# Limits
MAX_VACANCIES_PER_PAGE = 5
MAX_NOTIFICATION_CHARS = 200
MAX_DESCRIPTION_CHARS = 400
MAX_VACANCY_LIST = 100

# Timeouts
OPENAI_TIMEOUT = 30
PLAYWRIGHT_TIMEOUT = 20000
TELEGRAM_TIMEOUT = 30

# Rate limits
OPENAI_MAX_RPM = 20
OPENAI_MIN_DELAY = 3.0
KWORK_DAILY_LIMIT = 200
