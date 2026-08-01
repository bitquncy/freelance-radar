"""Database initialization for FreelanceRadar bot."""
import asyncio
import os
import aiosqlite
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from services.logger_config import get_logger

# DB_PATH is read from the environment (with the same default as config.py)
# instead of importing `config`: importing config validates the FULL settings
# model and crashes without BOT_TOKEN/OWNER_CHAT_ID. This script runs inside
# the container entrypoint — including CI's secret-less image smoke test —
# where only DB_PATH matters. load_dotenv() keeps the local `.env` workflow.
load_dotenv()
DB_PATH = os.environ.get("DB_PATH", "freelance_radar.db")

logger = get_logger(__name__)


async def init_database() -> None:
    """Initialize database with all required tables."""
    logger.info("db.initializing", db_path=DB_PATH)

    async with aiosqlite.connect(DB_PATH) as db:
        # Create vacancies table (extended)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kwork_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                budget TEXT,
                budget_min INTEGER,
                budget_max INTEGER,
                deadline TEXT,
                deadline_days INTEGER,
                category TEXT,
                subcategory TEXT,
                skills TEXT,
                proposals_count INTEGER,
                customer_rating REAL,
                customer_orders INTEGER,
                source TEXT NOT NULL DEFAULT 'kwork',
                fetched_at TEXT NOT NULL,
                analyzed INTEGER NOT NULL DEFAULT 0,
                responded INTEGER NOT NULL DEFAULT 0,
                ai_score INTEGER,
                ai_priority TEXT,
                ai_risks TEXT,
                match_percentage INTEGER,
                filtered_out INTEGER NOT NULL DEFAULT 0,
                filter_reason TEXT
            )
        """)

        # Create sources table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                url TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                urls TEXT
            )
        """)

        # Create user_settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                analysis_prompt TEXT,
                response_prompt TEXT,
                min_budget INTEGER,
                max_budget INTEGER,
                cooldown_seconds INTEGER NOT NULL DEFAULT 3600,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create freelancer_profile table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS freelancer_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                skills TEXT,
                experience_years INTEGER,
                preferred_categories TEXT,
                hourly_rate INTEGER,
                portfolio_url TEXT,
                bio TEXT,
                strong_sides TEXT,
                min_budget INTEGER,
                max_budget INTEGER,
                min_customer_rating REAL,
                max_proposals_count INTEGER,
                whitelist_words TEXT,
                blacklist_words TEXT,
                auto_mode_enabled INTEGER NOT NULL DEFAULT 0,
                auto_mode_delay_minutes INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create responses table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vacancy_id INTEGER NOT NULL,
                kwork_id TEXT NOT NULL,
                response_text TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY (vacancy_id) REFERENCES vacancies(id)
            )
        """)

        # Create chat_cooldowns table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_cooldowns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL UNIQUE,
                last_sent_at TEXT NOT NULL,
                cooldown_seconds INTEGER NOT NULL
            )
        """)

        # Create blacklist table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                reason TEXT,
                added_at TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                expires_at TEXT,
                UNIQUE(entity_type, entity_id, user_id)
            )
        """)

        # Create FTS5 virtual table for full-text search
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vacancies_fts USING fts5(
                title,
                description,
                content='vacancies',
                content_rowid='id'
            )
        """)

        # Triggers to keep FTS index in sync with vacancies
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS vacancies_fts_insert AFTER INSERT ON vacancies BEGIN
                INSERT INTO vacancies_fts(rowid, title, description)
                VALUES (new.id, new.title, new.description);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS vacancies_fts_delete AFTER DELETE ON vacancies BEGIN
                INSERT INTO vacancies_fts(vacancies_fts, rowid, title, description)
                VALUES ('delete', old.id, old.title, old.description);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS vacancies_fts_update AFTER UPDATE ON vacancies BEGIN
                INSERT INTO vacancies_fts(vacancies_fts, rowid, title, description)
                VALUES ('delete', old.id, old.title, old.description);
                INSERT INTO vacancies_fts(rowid, title, description)
                VALUES (new.id, new.title, new.description);
            END
        """)

        # Create chat_groups table for broadcast
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Create chat_group_members table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                chat_title TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                deactivated_reason TEXT,
                last_broadcast_at TEXT,
                added_at TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES chat_groups(id) ON DELETE CASCADE
            )
        """)

        # Create broadcasts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                message_text TEXT,
                message_type TEXT NOT NULL DEFAULT 'text',
                file_id TEXT,
                caption TEXT,
                sent_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                source_chat_id TEXT,
                source_message_id INTEGER,
                scheduled_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                disable_notification INTEGER NOT NULL DEFAULT 0,
                protect_content INTEGER NOT NULL DEFAULT 0,
                progress_chat_id TEXT,
                progress_message_id INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES chat_groups(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_code TEXT,
                error_message TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (broadcast_id) REFERENCES broadcasts(id) ON DELETE CASCADE,
                UNIQUE(broadcast_id, chat_id)
            )
        """)

        # Create indexes for performance
        # Vacancies indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_kwork_id ON vacancies(kwork_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_source ON vacancies(source)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_analyzed ON vacancies(analyzed)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_filtered ON vacancies(filtered_out)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_priority ON vacancies(ai_priority)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_fetched ON vacancies(fetched_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_responded ON vacancies(responded)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_score ON vacancies(ai_score)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_match ON vacancies(match_percentage)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_budget ON vacancies(budget_min, budget_max)")

        # Responses indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_responses_vacancy_id ON responses(vacancy_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_responses_approved ON responses(approved)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_responses_kwork_id ON responses(kwork_id)")

        # Other indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_chat_cooldowns_chat_id ON chat_cooldowns(chat_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_entity ON blacklist(entity_type, entity_id, user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_expires ON blacklist(expires_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_settings_user ON user_settings(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_profile_user ON freelancer_profile(user_id)")
        await db.commit()
        logger.info("Database initialized successfully")


async def run_migrations() -> None:
    """Run any pending migrations."""
    logger.info("Checking for migrations...")

    async with aiosqlite.connect(DB_PATH) as db:
        # Check if vacancies table has new columns (migration from old schema)
        cursor = await db.execute("PRAGMA table_info(vacancies)")
        columns = [row[1] for row in await cursor.fetchall()]

        new_columns = {
            'budget_min': 'INTEGER',
            'budget_max': 'INTEGER',
            'deadline_days': 'INTEGER',
            'subcategory': 'TEXT',
            'skills': 'TEXT',
            'proposals_count': 'INTEGER',
            'customer_rating': 'REAL',
            'customer_orders': 'INTEGER',
            'ai_score': 'INTEGER',
            'ai_priority': 'TEXT',
            'ai_risks': 'TEXT',
            'match_percentage': 'INTEGER',
            'filtered_out': 'INTEGER NOT NULL DEFAULT 0',
            'filter_reason': 'TEXT',
        }

        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                logger.info("db.adding_column", table="vacancies", column=col_name)
                await db.execute(f"ALTER TABLE vacancies ADD COLUMN {col_name} {col_type}")

        # Check if freelancer_profile table exists
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='freelancer_profile'")
        if not await cursor.fetchone():
            logger.info("Creating freelancer_profile table")
            await db.execute("""
                CREATE TABLE freelancer_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    skills TEXT,
                    experience_years INTEGER,
                    preferred_categories TEXT,
                    hourly_rate INTEGER,
                    portfolio_url TEXT,
                    bio TEXT,
                    strong_sides TEXT,
                    min_budget INTEGER,
                    max_budget INTEGER,
                    min_customer_rating REAL,
                    max_proposals_count INTEGER,
                    whitelist_words TEXT,
                    blacklist_words TEXT,
                    auto_mode_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_mode_delay_minutes INTEGER NOT NULL DEFAULT 5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

        # Migrate freelancer_profile columns
        cursor = await db.execute("PRAGMA table_info(freelancer_profile)")
        fp_columns = [row[1] for row in await cursor.fetchall()]
        fp_new_columns = {
            'min_budget': 'INTEGER',
            'max_budget': 'INTEGER',
        }
        for col_name, col_type in fp_new_columns.items():
            if col_name not in fp_columns:
                logger.info("db.adding_column", table="freelancer_profile", column=col_name)
                await db.execute(f"ALTER TABLE freelancer_profile ADD COLUMN {col_name} {col_type}")

        # Add indexes for new columns (only if columns were successfully added)
        new_indexes = [
            ("idx_vacancies_filtered_out", "CREATE INDEX IF NOT EXISTS idx_vacancies_filtered_out ON vacancies(filtered_out)"),
            ("idx_vacancies_ai_priority", "CREATE INDEX IF NOT EXISTS idx_vacancies_ai_priority ON vacancies(ai_priority)"),
            ("idx_freelancer_profile_user_id", "CREATE INDEX IF NOT EXISTS idx_freelancer_profile_user_id ON freelancer_profile(user_id)"),
        ]

        for idx_name, idx_sql in new_indexes:
            try:
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)
                )
                if not await cursor.fetchone():
                    logger.info("db.creating_index", index_name=idx_name)
                    await db.execute(idx_sql)
            except (aiosqlite.Error, ValueError, TypeError, OSError) as e:
                logger.warning("db.index_creation_failed", index_name=idx_name, error=str(e))

        # Migration: fix blacklist unique constraint to include user_id
        try:
            cursor = await db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='blacklist'"
            )
            row = await cursor.fetchone()
            if row and 'UNIQUE(entity_type, entity_id)' in row[0] and 'user_id' not in row[0].split('UNIQUE')[1].split(')')[0]:
                logger.info("Migrating blacklist table: adding user_id to unique constraint")
                # SQLite doesn't support ALTER TABLE for unique constraints
                # Need to recreate the table
                await db.execute("""
                    CREATE TABLE blacklist_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        entity_type TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        reason TEXT,
                        added_at TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        expires_at TEXT,
                        UNIQUE(entity_type, entity_id, user_id)
                    )
                """)
                await db.execute("""
                    INSERT INTO blacklist_new (id, entity_type, entity_id, reason, added_at, user_id, expires_at)
                    SELECT id, entity_type, entity_id, reason, added_at, user_id, expires_at FROM blacklist
                """)
                await db.execute("DROP TABLE blacklist")
                await db.execute("ALTER TABLE blacklist_new RENAME TO blacklist")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_entity ON blacklist(entity_type, entity_id, user_id)")
                logger.info("Blacklist table migrated successfully")
        except (aiosqlite.Error, ValueError, TypeError, OSError) as e:
            logger.warning("db.blacklist_migration_failed", error=str(e))

        # Migration: add urls column to sources table
        try:
            cursor = await db.execute("PRAGMA table_info(sources)")
            source_columns = [row[1] for row in await cursor.fetchall()]
            if "urls" not in source_columns:
                logger.info("db.adding_column", table="sources", column="urls")
                await db.execute("ALTER TABLE sources ADD COLUMN urls TEXT")
        except (aiosqlite.Error, ValueError, TypeError, OSError) as e:
            logger.warning("db.sources_migration_failed", error=str(e))

        # Migration: durable, restart-safe broadcast queue.
        broadcast_columns = {
            "blocked_count": "INTEGER NOT NULL DEFAULT 0",
            "skipped_count": "INTEGER NOT NULL DEFAULT 0",
            "total_count": "INTEGER NOT NULL DEFAULT 0",
            "source_chat_id": "TEXT",
            "source_message_id": "INTEGER",
            "scheduled_at": "TEXT",
            "started_at": "TEXT",
            "finished_at": "TEXT",
            "disable_notification": "INTEGER NOT NULL DEFAULT 0",
            "protect_content": "INTEGER NOT NULL DEFAULT 0",
            "progress_chat_id": "TEXT",
            "progress_message_id": "INTEGER",
            "last_error": "TEXT",
        }
        cursor = await db.execute("PRAGMA table_info(broadcasts)")
        existing_broadcast_columns = {row[1] for row in await cursor.fetchall()}
        for col_name, col_type in broadcast_columns.items():
            if col_name not in existing_broadcast_columns:
                await db.execute(
                    f"ALTER TABLE broadcasts ADD COLUMN {col_name} {col_type}"
                )

        member_columns = {
            "is_active": "INTEGER NOT NULL DEFAULT 1",
            "deactivated_reason": "TEXT",
            "last_broadcast_at": "TEXT",
        }
        cursor = await db.execute("PRAGMA table_info(chat_group_members)")
        existing_member_columns = {row[1] for row in await cursor.fetchall()}
        for col_name, col_type in member_columns.items():
            if col_name not in existing_member_columns:
                await db.execute(
                    f"ALTER TABLE chat_group_members ADD COLUMN {col_name} {col_type}"
                )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_code TEXT,
                error_message TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (broadcast_id) REFERENCES broadcasts(id) ON DELETE CASCADE,
                UNIQUE(broadcast_id, chat_id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_broadcasts_status_scheduled "
            "ON broadcasts(status, scheduled_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_broadcast_targets_status "
            "ON broadcast_targets(broadcast_id, status)"
        )

        # Rebuild FTS index if table is empty but vacancies exist
        cursor = await db.execute("SELECT COUNT(*) FROM vacancies_fts")
        fts_count = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM vacancies")
        vac_count = (await cursor.fetchone())[0]
        if fts_count == 0 and vac_count > 0:
            logger.info("db.rebuilding_fts_index", vacancies=vac_count)
            await db.execute("""
                INSERT INTO vacancies_fts(rowid, title, description)
                SELECT id, title, description FROM vacancies
            """)
            logger.info("db.fts_index_rebuilt")

        await db.commit()
        logger.info("Migrations completed")


async def init_and_migrate() -> None:
    """Initialize database and run migrations."""
    await init_database()
    await run_migrations()


if __name__ == "__main__":
    asyncio.run(init_and_migrate())
