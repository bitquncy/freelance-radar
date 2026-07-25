"""SQLAlchemy models for FreelanceRadar V2 — data model from AGENTS.md §5.

All V2 entities live in their own metadata and (by default) their own
database file, fully isolated from the legacy aiosqlite tables.

Deviations from the simplified spec model (documented per AGENTS.md §12.6):
    * ``ProjectAnalysis.user_id`` — added because win probability and
      profitability are user-specific (§3.3 features depend on the user's
      profile), while the spec's simplified model omits it.
    * ``ExchangeConnection.settings`` — JSON column for non-secret adapter
      settings (e.g. Telegram channel username). Secrets still go through
      ``credentials_ref`` only.
    * ``Proposal.mode`` / ``Proposal.violations`` — track template vs AI
      generation and guardrail violations (§6.4).
"""
import enum
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (stored as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all V2 models."""


class Platform(str, enum.Enum):
    """Supported job sources (AGENTS.md §5 ExchangeConnection.platform)."""

    KWORK = "kwork"
    FL_RU = "fl_ru"
    WEBLANCER = "weblancer"
    TG_CHANNEL = "tg_channel"
    UPWORK = "upwork"


class SubscriptionTier(str, enum.Enum):
    """Subscription tiers (AGENTS.md §7) plus the 7-day trial."""

    TRIAL = "trial"
    BASIC = "basic"
    PRO = "pro"
    BUSINESS = "business"


class ConnectionStatus(str, enum.Enum):
    """Status of an exchange connection."""

    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class ProposalStatus(str, enum.Enum):
    """Proposal lifecycle status (AGENTS.md §5)."""

    DRAFT = "draft"
    EDITED = "edited"
    SENT = "sent"


class ProposalMode(str, enum.Enum):
    """How the proposal text was produced (§3.5 / §7 tariff table)."""

    TEMPLATE = "template"
    AI = "ai"


class PipelineStage(str, enum.Enum):
    """CRM funnel stages (AGENTS.md §3.7)."""

    NEW_LEAD = "new_lead"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REPEAT_CLIENT = "repeat_client"


class InteractionType(str, enum.Enum):
    """Interaction types (AGENTS.md §5)."""

    MESSAGE = "message"
    NOTE = "note"
    REMINDER = "reminder"


class ReminderStatus(str, enum.Enum):
    """Reminder lifecycle (§3.8): notify once, then wait for user action."""

    PENDING = "pending"
    NOTIFIED = "notified"
    DONE = "done"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    """Subscription payment status."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


def _enum_col(enum_cls: type) -> Enum:
    """Portable enum column: VARCHAR + values, no native DB enum."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class User(Base):
    """A freelancer using the service (multi-tenant, keyed by telegram_id)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    target_hourly_rate: Mapped[Optional[int]] = mapped_column(Integer)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.06)
    skills: Mapped[List[str]] = mapped_column(JSON, default=list)
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(
        _enum_col(SubscriptionTier), default=SubscriptionTier.TRIAL
    )
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    auto_send_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_send_threshold: Mapped[int] = mapped_column(Integer, default=80)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    connections: Mapped[List["ExchangeConnection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    portfolio_items: Mapped[List["PortfolioItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    clients: Mapped[List["Client"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ExchangeConnection(Base):
    """A user's connection to a job source (AGENTS.md §5).

    ``credentials_ref`` is a reference to a secret in a vault — never a raw
    password/token (§5, §8).
    """

    __tablename__ = "exchange_connections"
    __table_args__ = (
        # One connection per exchange per user; TG channels may repeat
        # (channel username lives in ``settings``), hence the partial index.
        Index(
            "uq_connections_user_exchange",
            "user_id",
            "platform",
            unique=True,
            sqlite_where=text("platform != 'tg_channel'"),
            postgresql_where=text("platform != 'tg_channel'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[Platform] = mapped_column(_enum_col(Platform))
    credentials_ref: Mapped[Optional[str]] = mapped_column(String(255))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[ConnectionStatus] = mapped_column(
        _enum_col(ConnectionStatus), default=ConnectionStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="connections")


class Project(Base):
    """A raw listing from an exchange/channel (AGENTS.md §5).

    Deduplicated globally by ``(source, external_id)`` (§3.1).
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_projects_source_ext"),
        # Fuzzy-dedup window scans by created_at (§3.1).
        Index("ix_projects_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_connection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("exchange_connections.id")
    )
    source: Mapped[Platform] = mapped_column(_enum_col(Platform), index=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(Text)
    description_raw: Mapped[str] = mapped_column(Text, default="")
    budget_raw: Mapped[Optional[str]] = mapped_column(String(255))
    budget_min: Mapped[Optional[int]] = mapped_column(Integer)
    budget_max: Mapped[Optional[int]] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    category: Mapped[Optional[str]] = mapped_column(String(255))
    proposals_count: Mapped[Optional[int]] = mapped_column(Integer)
    client_rating: Mapped[Optional[float]] = mapped_column(Float)
    client_orders: Mapped[Optional[int]] = mapped_column(Integer)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    url: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    analyses: Mapped[List["ProjectAnalysis"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectAnalysis(Base):
    """Extraction + scoring result for a project (AGENTS.md §3.2–3.4, §5)."""

    __tablename__ = "project_analyses"
    __table_args__ = (
        # Idempotency: one analysis per (project, user) — a concurrent tick /
        # restart replay must not create duplicates (and must not re-notify).
        UniqueConstraint("project_id", "user_id", name="uq_analysis_project_user"),
        # Monthly quota query pattern: user_id + computed_at >= month_start.
        Index("ix_analyses_user_computed", "user_id", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    extracted_budget: Mapped[Optional[int]] = mapped_column(Integer)
    extracted_deadline_days: Mapped[Optional[int]] = mapped_column(Integer)
    extracted_skills: Mapped[List[str]] = mapped_column(JSON, default=list)
    client_red_flags: Mapped[List[str]] = mapped_column(JSON, default=list)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    win_probability: Mapped[Optional[float]] = mapped_column(Float)
    profitability_index: Mapped[Optional[float]] = mapped_column(Float)
    effective_hourly_rate: Mapped[Optional[float]] = mapped_column(Float)
    net_payout: Mapped[Optional[float]] = mapped_column(Float)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="analyses")


class Proposal(Base):
    """A generated/edited/sent proposal (AGENTS.md §5)."""

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    generated_text: Mapped[str] = mapped_column(Text)
    status: Mapped[ProposalStatus] = mapped_column(
        _enum_col(ProposalStatus), default=ProposalStatus.DRAFT
    )
    mode: Mapped[ProposalMode] = mapped_column(
        _enum_col(ProposalMode), default=ProposalMode.AI
    )
    violations: Mapped[List[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Client(Base):
    """A CRM client card (AGENTS.md §3.7, §5)."""

    __tablename__ = "clients"
    __table_args__ = (
        # Idempotency: a double-tapped «Отправлено» must upsert into ONE card.
        # NULL platform_client_id stays non-unique (manual cards).
        UniqueConstraint(
            "user_id", "platform_client_id", name="uq_clients_user_platform_client"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform_client_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="")
    pipeline_stage: Mapped[PipelineStage] = mapped_column(
        _enum_col(PipelineStage), default=PipelineStage.NEW_LEAD
    )
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="clients")
    interactions: Mapped[List["Interaction"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    reminders: Mapped[List["Reminder"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class Interaction(Base):
    """A logged interaction with a client (AGENTS.md §5)."""

    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    type: Mapped[InteractionType] = mapped_column(_enum_col(InteractionType))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    client: Mapped["Client"] = relationship(back_populates="interactions")


class Reminder(Base):
    """A follow-up reminder (AGENTS.md §3.8, §5)."""

    __tablename__ = "reminders"
    __table_args__ = (
        # Due-reminder poll pattern: status == PENDING AND due_at <= now.
        Index("ix_reminders_status_due", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ReminderStatus] = mapped_column(
        _enum_col(ReminderStatus), default=ReminderStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    client: Mapped["Client"] = relationship(back_populates="reminders")


class PortfolioItem(Base):
    """A portfolio case — the ONLY source of facts about the user (§2.4, §6.4)."""

    __tablename__ = "portfolio_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    media_url: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="portfolio_items")


class Subscription(Base):
    """A subscription payment record (AGENTS.md §5, §7)."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        # Telegram Payments charge id — unique so a re-delivered
        # successful_payment update can never activate a subscription twice.
        UniqueConstraint("payment_charge_id", name="uq_subscriptions_charge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tier: Mapped[SubscriptionTier] = mapped_column(_enum_col(SubscriptionTier))
    amount: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(64), default="manual_invoice")
    status: Mapped[PaymentStatus] = mapped_column(
        _enum_col(PaymentStatus), default=PaymentStatus.PENDING
    )
    payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255))
    period_start: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    period_end: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def as_dict(obj: Any) -> dict:
    """Serialize a model instance to a plain dict (column values only)."""
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}
