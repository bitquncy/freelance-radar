"""Database queries for FreelanceRadar bot."""
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from db.models import JobVacancy, Source, UserSettings, Response, ChatCooldown, FreelancerProfile, Blacklist


# ---------------------------------------------------------------------------
# Vacancies
# ---------------------------------------------------------------------------

VACANCY_COLUMNS = [
    "kwork_id", "url", "title", "description", "budget",
    "budget_min", "budget_max", "deadline", "deadline_days",
    "category", "subcategory", "skills", "proposals_count",
    "customer_rating", "customer_orders", "source", "fetched_at",
    "analyzed", "responded", "ai_score", "ai_priority", "ai_risks",
    "match_percentage", "filtered_out", "filter_reason"
]


def _vacancy_from_row(row) -> JobVacancy:
    """Build JobVacancy from database row."""
    return JobVacancy(
        kwork_id=row[0],
        url=row[1],
        title=row[2],
        description=row[3],
        budget=row[4],
        budget_min=row[5],
        budget_max=row[6],
        deadline=row[7],
        deadline_days=row[8],
        category=row[9],
        subcategory=row[10],
        skills=row[11],
        proposals_count=row[12],
        customer_rating=row[13],
        customer_orders=row[14],
        source=row[15],
        fetched_at=datetime.fromisoformat(row[16]) if row[16] else datetime.now(),
        analyzed=bool(row[17]),
        responded=bool(row[18]),
        ai_score=row[19],
        ai_priority=row[20],
        ai_risks=row[21],
        match_percentage=row[22],
        filtered_out=bool(row[23]),
        filter_reason=row[24],
    )


async def is_vacancy_seen(db: aiosqlite.Connection, kwork_id: str) -> bool:
    """Check if vacancy with given kwork_id already exists in database."""
    async with db.execute(
        "SELECT 1 FROM vacancies WHERE kwork_id = ? LIMIT 1",
        (kwork_id,)
    ) as cursor:
        result = await cursor.fetchone()
        return result is not None


async def get_seen_kwork_ids(db: aiosqlite.Connection, kwork_ids: List[str]) -> set:
    """Batch check which kwork_ids already exist in database.

    Returns a set of kwork_ids that are already seen.
    """
    if not kwork_ids:
        return set()

    placeholders = ", ".join(["?" for _ in kwork_ids])
    async with db.execute(
        f"SELECT kwork_id FROM vacancies WHERE kwork_id IN ({placeholders})",
        kwork_ids,
    ) as cursor:
        rows = await cursor.fetchall()
        return {row[0] for row in rows}


async def save_vacancy(db: aiosqlite.Connection, vacancy: JobVacancy) -> int:
    """Save vacancy to database. Returns vacancy id."""
    cursor = await db.execute(
        f"""
        INSERT OR IGNORE INTO vacancies ({', '.join(VACANCY_COLUMNS)})
        VALUES ({', '.join(['?'] * len(VACANCY_COLUMNS))})
        """,
        (
            vacancy.kwork_id,
            vacancy.url,
            vacancy.title,
            vacancy.description,
            vacancy.budget,
            vacancy.budget_min,
            vacancy.budget_max,
            vacancy.deadline,
            vacancy.deadline_days,
            vacancy.category,
            vacancy.subcategory,
            vacancy.skills,
            vacancy.proposals_count,
            vacancy.customer_rating,
            vacancy.customer_orders,
            vacancy.source,
            vacancy.fetched_at.isoformat(),
            int(vacancy.analyzed),
            int(vacancy.responded),
            vacancy.ai_score,
            vacancy.ai_priority,
            vacancy.ai_risks,
            vacancy.match_percentage,
            int(vacancy.filtered_out),
            vacancy.filter_reason,
        )
    )
    await db.commit()
    return cursor.lastrowid


async def update_vacancy_ai_analysis(
    db: aiosqlite.Connection,
    kwork_id: str,
    ai_score: Optional[int],
    ai_priority: Optional[str],
    ai_risks: Optional[str],
    match_percentage: Optional[int]
) -> None:
    """Update AI analysis fields for a vacancy."""
    await db.execute(
        """
        UPDATE vacancies
        SET ai_score = ?, ai_priority = ?, ai_risks = ?, match_percentage = ?
        WHERE kwork_id = ?
        """,
        (ai_score, ai_priority, ai_risks, match_percentage, kwork_id)
    )
    await db.commit()


async def mark_vacancy_filtered(
    db: aiosqlite.Connection,
    kwork_id: str,
    reason: str
) -> None:
    """Mark vacancy as filtered out with reason."""
    await db.execute(
        "UPDATE vacancies SET filtered_out = 1, filter_reason = ? WHERE kwork_id = ?",
        (reason, kwork_id)
    )
    await db.commit()


async def batch_save_vacancies(
    db: aiosqlite.Connection,
    vacancies: List[JobVacancy],
) -> int:
    """Bulk save vacancies in a single transaction. Returns count saved."""
    if not vacancies:
        return 0

    placeholders = ', '.join(['?'] * len(VACANCY_COLUMNS))
    sql = f"""
        INSERT OR IGNORE INTO vacancies ({', '.join(VACANCY_COLUMNS)})
        VALUES ({placeholders})
    """

    rows = []
    for v in vacancies:
        rows.append((
            v.kwork_id, v.url, v.title, v.description, v.budget,
            v.budget_min, v.budget_max, v.deadline, v.deadline_days,
            v.category, v.subcategory, v.skills, v.proposals_count,
            v.customer_rating, v.customer_orders, v.source,
            v.fetched_at.isoformat(), int(v.analyzed), int(v.responded),
            v.ai_score, v.ai_priority, v.ai_risks, v.match_percentage,
            int(v.filtered_out), v.filter_reason,
        ))

    await db.executemany(sql, rows)
    await db.commit()
    return len(rows)


async def batch_update_vacancy_ai_analysis(
    db: aiosqlite.Connection,
    updates: List[Tuple],
) -> int:
    """Bulk update AI analysis fields.

    Args:
        updates: List of (ai_score, ai_priority, ai_risks, match_percentage, kwork_id) tuples.
    """
    if not updates:
        return 0

    sql = """
        UPDATE vacancies
        SET ai_score = ?, ai_priority = ?, ai_risks = ?, match_percentage = ?
        WHERE kwork_id = ?
    """
    await db.executemany(sql, updates)
    await db.commit()
    return len(updates)


async def get_unseen_vacancies(db: aiosqlite.Connection, limit: int = 20) -> List[JobVacancy]:
    """Get vacancies that haven't been analyzed yet and not filtered out."""
    cols = ', '.join(VACANCY_COLUMNS)
    async with db.execute(
        f"""
        SELECT {cols}
        FROM vacancies
        WHERE analyzed = 0 AND filtered_out = 0
        ORDER BY fetched_at DESC
        LIMIT ?
        """,
        (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [_vacancy_from_row(row) for row in rows]


async def get_high_priority_vacancies(db: aiosqlite.Connection, limit: int = 10) -> List[JobVacancy]:
    """Get high priority vacancies."""
    cols = ', '.join(VACANCY_COLUMNS)
    async with db.execute(
        f"""
        SELECT {cols}
        FROM vacancies
        WHERE filtered_out = 0 AND ai_priority = 'high' AND responded = 0
        ORDER BY ai_score DESC, fetched_at DESC
        LIMIT ?
        """,
        (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [_vacancy_from_row(row) for row in rows]


async def mark_vacancy_analyzed(db: aiosqlite.Connection, kwork_id: str) -> None:
    """Mark vacancy as analyzed."""
    await db.execute(
        "UPDATE vacancies SET analyzed = 1 WHERE kwork_id = ?",
        (kwork_id,)
    )
    await db.commit()


async def mark_vacancy_responded(db: aiosqlite.Connection, kwork_id: str) -> None:
    """Mark vacancy as responded."""
    await db.execute(
        "UPDATE vacancies SET responded = 1 WHERE kwork_id = ?",
        (kwork_id,)
    )
    await db.commit()


async def get_vacancy_id_by_kwork_id(db: aiosqlite.Connection, kwork_id: str) -> Optional[int]:
    """Get vacancy id by kwork_id."""
    cursor = await db.execute(
        "SELECT id FROM vacancies WHERE kwork_id = ?",
        (kwork_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def get_vacancy_by_kwork_id(db: aiosqlite.Connection, kwork_id: str) -> Optional[JobVacancy]:
    """Get vacancy by kwork_id."""
    cols = ', '.join(VACANCY_COLUMNS)
    async with db.execute(
        f"SELECT {cols} FROM vacancies WHERE kwork_id = ?",
        (kwork_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return _vacancy_from_row(row) if row else None


async def get_vacancy_stats(db: aiosqlite.Connection) -> dict:
    """Get vacancy statistics."""
    stats = {}

    async with db.execute("SELECT COUNT(*) FROM vacancies") as cursor:
        stats['total'] = (await cursor.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM vacancies WHERE analyzed = 0") as cursor:
        stats['unseen'] = (await cursor.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM vacancies WHERE responded = 1") as cursor:
        stats['responded'] = (await cursor.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM vacancies WHERE filtered_out = 1") as cursor:
        stats['filtered_out'] = (await cursor.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM vacancies WHERE ai_priority = 'high'") as cursor:
        stats['high_priority'] = (await cursor.fetchone())[0]

    async with db.execute(
        "SELECT source, COUNT(*) FROM vacancies GROUP BY source"
    ) as cursor:
        stats['by_source'] = {row[0]: row[1] for row in await cursor.fetchall()}

    return stats


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

async def add_source(db: aiosqlite.Connection, source: Source) -> int:
    """Add new monitoring source."""
    cursor = await db.execute(
        """
        INSERT INTO sources (name, source_type, url, enabled, created_at, urls)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source.name, source.source_type, source.url, int(source.enabled), datetime.now().isoformat(), source.urls)
    )
    await db.commit()
    return cursor.lastrowid


async def get_enabled_sources(db: aiosqlite.Connection) -> List[Source]:
    """Get all enabled monitoring sources."""
    async with db.execute(
        """
        SELECT id, name, source_type, url, enabled, created_at, urls
        FROM sources
        WHERE enabled = 1
        """
    ) as cursor:
        rows = await cursor.fetchall()
        return [
            Source(
                id=row[0], name=row[1], source_type=row[2],
                url=row[3], enabled=bool(row[4]),
                created_at=datetime.fromisoformat(row[5]),
                urls=row[6]
            )
            for row in rows
        ]


async def get_all_sources(db: aiosqlite.Connection) -> List[Source]:
    """Get all monitoring sources."""
    async with db.execute(
        "SELECT id, name, source_type, url, enabled, created_at, urls FROM sources"
    ) as cursor:
        rows = await cursor.fetchall()
        return [
            Source(
                id=row[0], name=row[1], source_type=row[2],
                url=row[3], enabled=bool(row[4]),
                created_at=datetime.fromisoformat(row[5]),
                urls=row[6]
            )
            for row in rows
        ]


async def toggle_source(db: aiosqlite.Connection, source_id: int) -> None:
    """Toggle source enabled status."""
    await db.execute(
        "UPDATE sources SET enabled = NOT enabled WHERE id = ?",
        (source_id,)
    )
    await db.commit()


async def delete_source(db: aiosqlite.Connection, source_id: int) -> None:
    """Delete source."""
    await db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    await db.commit()


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

async def get_user_settings(db: aiosqlite.Connection, user_id: int) -> Optional[UserSettings]:
    """Get user settings."""
    async with db.execute(
        """
        SELECT id, user_id, analysis_prompt, response_prompt, min_budget, max_budget, cooldown_seconds, created_at, updated_at
        FROM user_settings
        WHERE user_id = ?
        """,
        (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return UserSettings(
                id=row[0], user_id=row[1], analysis_prompt=row[2],
                response_prompt=row[3], min_budget=row[4], max_budget=row[5],
                cooldown_seconds=row[6],
                created_at=datetime.fromisoformat(row[7]),
                updated_at=datetime.fromisoformat(row[8])
            )
        return None


async def save_user_settings(db: aiosqlite.Connection, settings: UserSettings) -> None:
    """Save or update user settings."""
    now = datetime.now().isoformat()
    await db.execute(
        """
        INSERT INTO user_settings (user_id, analysis_prompt, response_prompt, min_budget, max_budget, cooldown_seconds, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            analysis_prompt = excluded.analysis_prompt,
            response_prompt = excluded.response_prompt,
            min_budget = excluded.min_budget,
            max_budget = excluded.max_budget,
            cooldown_seconds = excluded.cooldown_seconds,
            updated_at = excluded.updated_at
        """,
        (settings.user_id, settings.analysis_prompt, settings.response_prompt,
         settings.min_budget, settings.max_budget, settings.cooldown_seconds, now, now)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Freelancer profile
# ---------------------------------------------------------------------------

async def get_freelancer_profile(db: aiosqlite.Connection, user_id: int) -> Optional[FreelancerProfile]:
    """Get freelancer profile."""
    async with db.execute(
        """
        SELECT id, user_id, skills, experience_years, preferred_categories, hourly_rate,
               portfolio_url, bio, strong_sides, min_budget, max_budget,
               min_customer_rating, max_proposals_count,
               whitelist_words, blacklist_words, auto_mode_enabled, auto_mode_delay_minutes,
               created_at, updated_at
        FROM freelancer_profile
        WHERE user_id = ?
        """,
        (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return FreelancerProfile(
                id=row[0], user_id=row[1], skills=row[2], experience_years=row[3],
                preferred_categories=row[4], hourly_rate=row[5], portfolio_url=row[6],
                bio=row[7], strong_sides=row[8], min_budget=row[9], max_budget=row[10],
                min_customer_rating=row[11], max_proposals_count=row[12],
                whitelist_words=row[13], blacklist_words=row[14],
                auto_mode_enabled=bool(row[15]), auto_mode_delay_minutes=row[16],
                created_at=datetime.fromisoformat(row[17]),
                updated_at=datetime.fromisoformat(row[18])
            )
        return None


async def save_freelancer_profile(db: aiosqlite.Connection, profile: FreelancerProfile) -> None:
    """Save or update freelancer profile."""
    now = datetime.now().isoformat()
    await db.execute(
        """
        INSERT INTO freelancer_profile (
            user_id, skills, experience_years, preferred_categories, hourly_rate,
            portfolio_url, bio, strong_sides, min_budget, max_budget,
            min_customer_rating, max_proposals_count,
            whitelist_words, blacklist_words, auto_mode_enabled, auto_mode_delay_minutes,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            skills = excluded.skills,
            experience_years = excluded.experience_years,
            preferred_categories = excluded.preferred_categories,
            hourly_rate = excluded.hourly_rate,
            portfolio_url = excluded.portfolio_url,
            bio = excluded.bio,
            strong_sides = excluded.strong_sides,
            min_budget = excluded.min_budget,
            max_budget = excluded.max_budget,
            min_customer_rating = excluded.min_customer_rating,
            max_proposals_count = excluded.max_proposals_count,
            whitelist_words = excluded.whitelist_words,
            blacklist_words = excluded.blacklist_words,
            auto_mode_enabled = excluded.auto_mode_enabled,
            auto_mode_delay_minutes = excluded.auto_mode_delay_minutes,
            updated_at = excluded.updated_at
        """,
        (
            profile.user_id, profile.skills, profile.experience_years,
            profile.preferred_categories, profile.hourly_rate, profile.portfolio_url,
            profile.bio, profile.strong_sides, profile.min_budget, profile.max_budget,
            profile.min_customer_rating, profile.max_proposals_count,
            profile.whitelist_words, profile.blacklist_words,
            int(profile.auto_mode_enabled), profile.auto_mode_delay_minutes, now, now
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

async def save_response(db: aiosqlite.Connection, response: Response) -> int:
    """Save generated response."""
    cursor = await db.execute(
        """
        INSERT INTO responses (vacancy_id, kwork_id, response_text, approved, sent, created_at, sent_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (response.vacancy_id, response.kwork_id, response.response_text,
         int(response.approved), int(response.sent), datetime.now().isoformat(), None)
    )
    await db.commit()
    return cursor.lastrowid


async def approve_response(db: aiosqlite.Connection, response_id: int) -> None:
    """Approve response for sending."""
    await db.execute(
        "UPDATE responses SET approved = 1 WHERE id = ?",
        (response_id,)
    )
    await db.commit()


async def get_response_by_id(db: aiosqlite.Connection, response_id: int) -> Optional[Response]:
    """Get generated response by id."""
    async with db.execute(
        """
        SELECT id, vacancy_id, kwork_id, response_text, approved, sent, created_at, sent_at
        FROM responses
        WHERE id = ?
        """,
        (response_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return Response(
            id=row[0], vacancy_id=row[1], kwork_id=row[2], response_text=row[3],
            approved=bool(row[4]), sent=bool(row[5]),
            created_at=datetime.fromisoformat(row[6]) if row[6] else None,
            sent_at=datetime.fromisoformat(row[7]) if row[7] else None,
        )


async def get_recent_responses(db: aiosqlite.Connection, limit: int = 15) -> List[Response]:
    """Get recent responses for context."""
    async with db.execute(
        """
        SELECT id, vacancy_id, kwork_id, response_text, approved, sent, created_at, sent_at
        FROM responses
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [
            Response(
                id=row[0], vacancy_id=row[1], kwork_id=row[2], response_text=row[3],
                approved=bool(row[4]), sent=bool(row[5]),
                created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                sent_at=datetime.fromisoformat(row[7]) if row[7] else None,
            )
            for row in rows
        ]


async def mark_response_sent(db: aiosqlite.Connection, response_id: int) -> None:
    """Mark response as sent."""
    await db.execute(
        "UPDATE responses SET sent = 1, sent_at = ? WHERE id = ?",
        (datetime.now().isoformat(), response_id)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Chat cooldown
# ---------------------------------------------------------------------------

async def get_chat_cooldown(db: aiosqlite.Connection, chat_id: str) -> Optional[ChatCooldown]:
    """Get chat cooldown info."""
    async with db.execute(
        """
        SELECT id, chat_id, last_sent_at, cooldown_seconds
        FROM chat_cooldowns
        WHERE chat_id = ?
        """,
        (chat_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return ChatCooldown(
                id=row[0], chat_id=row[1],
                last_sent_at=datetime.fromisoformat(row[2]),
                cooldown_seconds=row[3]
            )
        return None


async def update_chat_cooldown(db: aiosqlite.Connection, chat_id: str, cooldown_seconds: int) -> None:
    """Update chat cooldown after sending message."""
    now = datetime.now().isoformat()
    await db.execute(
        """
        INSERT INTO chat_cooldowns (chat_id, last_sent_at, cooldown_seconds)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            last_sent_at = excluded.last_sent_at,
            cooldown_seconds = excluded.cooldown_seconds
        """,
        (chat_id, now, cooldown_seconds)
    )
    await db.commit()


async def can_send_to_chat(db: aiosqlite.Connection, chat_id: str, cooldown_seconds: int) -> bool:
    """Check if message can be sent to chat (cooldown expired)."""
    cooldown = await get_chat_cooldown(db, chat_id)
    if not cooldown:
        return True
    elapsed = (datetime.now() - cooldown.last_sent_at).total_seconds()
    return elapsed >= cooldown_seconds


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

async def is_blacklisted(db: aiosqlite.Connection, entity_type: str, entity_id: str) -> bool:
    """Check if entity is in blacklist and not expired."""
    now = datetime.now().isoformat()
    async with db.execute(
        "SELECT 1 FROM blacklist WHERE entity_type = ? AND entity_id = ? AND (expires_at IS NULL OR expires_at > ?) LIMIT 1",
        (entity_type, entity_id, now),
    ) as cursor:
        result = await cursor.fetchone()
        return result is not None


async def add_to_blacklist(
    db: aiosqlite.Connection,
    entity_type: str,
    entity_id: str,
    user_id: int,
    reason: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> int:
    """Add entity to blacklist. Returns row id."""
    cursor = await db.execute(
        """
        INSERT INTO blacklist (entity_type, entity_id, reason, added_at, user_id, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id, user_id) DO UPDATE SET
            reason = excluded.reason,
            added_at = excluded.added_at,
            expires_at = excluded.expires_at
        """,
        (entity_type, entity_id, reason, datetime.now().isoformat(), user_id, expires_at),
    )
    await db.commit()
    return cursor.lastrowid


async def remove_from_blacklist(db: aiosqlite.Connection, entity_type: str, entity_id: str) -> None:
    """Remove entity from blacklist."""
    await db.execute(
        "DELETE FROM blacklist WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    )
    await db.commit()


async def get_blacklist(
    db: aiosqlite.Connection, entity_type: Optional[str] = None
) -> List[Blacklist]:
    """Get blacklist entries, optionally filtered by entity_type. Excludes expired entries."""
    now = datetime.now().isoformat()
    if entity_type:
        async with db.execute(
            "SELECT id, entity_type, entity_id, reason, added_at, user_id, expires_at FROM blacklist WHERE entity_type = ? AND (expires_at IS NULL OR expires_at > ?) ORDER BY added_at DESC",
            (entity_type, now),
        ) as cursor:
            rows = await cursor.fetchall()
    else:
        async with db.execute(
            "SELECT id, entity_type, entity_id, reason, added_at, user_id, expires_at FROM blacklist WHERE (expires_at IS NULL OR expires_at > ?) ORDER BY added_at DESC",
            (now,),
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        Blacklist(
            id=row[0],
            entity_type=row[1],
            entity_id=row[2],
            reason=row[3],
            added_at=datetime.fromisoformat(row[4]),
            user_id=row[5],
            expires_at=datetime.fromisoformat(row[6]) if row[6] else None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Full-Text Search
# ---------------------------------------------------------------------------

async def search_vacancies(
    db: aiosqlite.Connection,
    query: str,
    limit: int = 20,
) -> List[JobVacancy]:
    """Full-text search over vacancies using FTS5.

    Supports:
    - Simple words: 'python django'
    - Phrases: '"machine learning"'
    - AND/OR: 'python AND django', 'python OR backend'
    - NOT: 'python NOT java'
    """
    if not query or not query.strip():
        return []

    # Escape FTS5 special characters
    safe_query = query.replace('"', '""').strip()
    # Escape FTS5 operators by wrapping each word in quotes
    # This prevents injection through AND, OR, NOT, NEAR, etc.
    words = safe_query.split()
    if len(words) > 1:
        safe_query = " AND ".join(f'"{w}"' for w in words)
    else:
        safe_query = f'"{safe_query}"'

    cols = ', '.join(VACANCY_COLUMNS)
    async with db.execute(
        f"""
        SELECT {cols}
        FROM vacancies
        WHERE id IN (
            SELECT rowid FROM vacancies_fts
            WHERE vacancies_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        )
        """,
        (safe_query, limit)
    ) as cursor:
        rows = await cursor.fetchall()
        return [_vacancy_from_row(row) for row in rows]


async def get_daily_vacancy_counts(
    db: aiosqlite.Connection,
    days: int = 14,
) -> List[Tuple[str, int]]:
    """Get daily counts of fetched vacancies for the last N days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    async with db.execute(
        """
        SELECT DATE(fetched_at) as day, COUNT(*)
        FROM vacancies
        WHERE fetched_at >= ?
        GROUP BY day
        ORDER BY day
        """,
        (since,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]


async def batch_mark_vacancy_filtered(
    db: aiosqlite.Connection,
    updates: List[Tuple],
) -> int:
    """Bulk mark vacancies as filtered out.

    Args:
        updates: List of (reason, kwork_id) tuples.
    """
    if not updates:
        return 0

    sql = """
        UPDATE vacancies
        SET filtered_out = 1, filter_reason = ?
        WHERE kwork_id = ?
    """
    await db.executemany(sql, updates)
    await db.commit()
    return len(updates)


async def search_vacancies_by_title(
    db: aiosqlite.Connection,
    query: str,
    limit: int = 20,
) -> List[JobVacancy]:
    """Search only in vacancy titles (LIKE fallback)."""
    if not query or not query.strip():
        return []

    # Escape LIKE wildcards to prevent SQL injection
    safe_query = query.replace("%", "\\%").replace("_", "\\_")

    cols = ', '.join(VACANCY_COLUMNS)
    async with db.execute(
        f"""
        SELECT {cols}
        FROM vacancies
        WHERE title LIKE ? ESCAPE '\\'
        ORDER BY fetched_at DESC
        LIMIT ?
        """,
        (f"%{safe_query}%", limit)
    ) as cursor:
        rows = await cursor.fetchall()
        return [_vacancy_from_row(row) for row in rows]
