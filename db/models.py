"""Data models for FreelanceRadar bot."""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


def _parse_json_list(value: Optional[str]) -> List:
    """Parse a JSON string or comma-separated string into a list."""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [w.strip() for w in value.split(",") if w.strip()]


def _to_json_list(value) -> Optional[str]:
    """Convert a list or string to JSON string."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except (json.JSONDecodeError, TypeError):
            return json.dumps([w.strip() for w in value.split(",") if w.strip()])
    if isinstance(value, (list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps([value], ensure_ascii=False)


@dataclass
class JobVacancy:
    """Represents a job vacancy from any source."""
    kwork_id: str
    url: str
    title: str
    description: str
    budget: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    deadline: Optional[str] = None
    deadline_days: Optional[int] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    skills: Optional[str] = None  # JSON list stored as string
    proposals_count: Optional[int] = None
    customer_rating: Optional[float] = None
    customer_orders: Optional[int] = None
    source: str = "kwork"
    fetched_at: datetime = field(default_factory=datetime.now)
    analyzed: bool = False
    responded: bool = False
    # AI analysis fields
    ai_score: Optional[int] = None  # 0-100
    ai_priority: Optional[str] = None  # low/medium/high
    ai_risks: Optional[str] = None
    match_percentage: Optional[int] = None
    # Filter fields
    filtered_out: bool = False
    filter_reason: Optional[str] = None

    @property
    def skills_list(self) -> List[str]:
        """Get skills as a list."""
        return _parse_json_list(self.skills)

    @skills_list.setter
    def skills_list(self, value):
        """Set skills from a list or string."""
        self.skills = _to_json_list(value)


@dataclass
class Source:
    """Represents a monitoring source (Kwork, Telegram channel, etc.)."""
    id: Optional[int]
    name: str
    source_type: str  # 'kwork', 'telegram'
    url: Optional[str]
    enabled: bool = True
    created_at: Optional[datetime] = None
    urls: Optional[str] = None  # JSON list of URLs/channels

    @property
    def urls_list(self) -> List[str]:
        """Get URLs as a list."""
        return _parse_json_list(self.urls)

    @urls_list.setter
    def urls_list(self, value):
        """Set URLs from a list or string."""
        self.urls = _to_json_list(value)


@dataclass
class UserSettings:
    """User settings for job analysis and responses."""
    id: Optional[int]
    user_id: int
    analysis_prompt: Optional[str]
    response_prompt: Optional[str]
    min_budget: Optional[int]
    max_budget: Optional[int]
    cooldown_seconds: int = 3600
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class FreelancerProfile:
    """Freelancer profile for personalization and filtering."""
    id: Optional[int]
    user_id: int
    skills: Optional[str] = None  # JSON list
    experience_years: Optional[int] = None
    preferred_categories: Optional[str] = None  # JSON list
    hourly_rate: Optional[int] = None
    portfolio_url: Optional[str] = None
    bio: Optional[str] = None
    strong_sides: Optional[str] = None
    # Filter preferences
    min_budget: Optional[int] = None
    max_budget: Optional[int] = None
    min_customer_rating: Optional[float] = None
    max_proposals_count: Optional[int] = None
    whitelist_words: Optional[str] = None  # JSON list
    blacklist_words: Optional[str] = None  # JSON list
    auto_mode_enabled: bool = False
    auto_mode_delay_minutes: int = 5
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def skills_list(self) -> List[str]:
        """Get skills as a list."""
        return _parse_json_list(self.skills)

    @skills_list.setter
    def skills_list(self, value):
        """Set skills from a list or string."""
        self.skills = _to_json_list(value)

    @property
    def preferred_categories_list(self) -> List[str]:
        """Get preferred categories as a list."""
        return _parse_json_list(self.preferred_categories)

    @preferred_categories_list.setter
    def preferred_categories_list(self, value):
        """Set preferred categories from a list or string."""
        self.preferred_categories = _to_json_list(value)

    @property
    def whitelist_words_list(self) -> List[str]:
        """Get whitelist words as a list."""
        return _parse_json_list(self.whitelist_words)

    @whitelist_words_list.setter
    def whitelist_words_list(self, value):
        """Set whitelist words from a list or string."""
        self.whitelist_words = _to_json_list(value)

    @property
    def blacklist_words_list(self) -> List[str]:
        """Get blacklist words as a list."""
        return _parse_json_list(self.blacklist_words)

    @blacklist_words_list.setter
    def blacklist_words_list(self, value):
        """Set blacklist words from a list or string."""
        self.blacklist_words = _to_json_list(value)


@dataclass
class Response:
    """Represents a generated response to a job vacancy."""
    id: Optional[int]
    vacancy_id: int
    kwork_id: str
    response_text: str
    approved: bool = False
    sent: bool = False
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


@dataclass
class ChatCooldown:
    """Tracks cooldown for sending messages to Telegram chats."""
    id: Optional[int]
    chat_id: str
    last_sent_at: datetime
    cooldown_seconds: int


@dataclass
class Blacklist:
    """Represents a blacklisted entity (vacancy or customer)."""
    id: Optional[int]
    entity_type: str        # 'vacancy' or 'customer'
    entity_id: str          # kwork_id or customer identifier
    reason: Optional[str]
    added_at: datetime
    user_id: int
    expires_at: Optional[datetime] = None  # TTL for blacklisted entries
