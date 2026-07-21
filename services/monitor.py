"""Monitor service with filtering and structured logging."""
import aiosqlite
from typing import Optional, List, Tuple

from parsers.kwork import KworkParser
from parsers.telegram_source import TelegramSourceParser
from services.filters import VacancyFilter
from services.logger_config import get_logger
from db import queries
from db.models import JobVacancy
from config import DB_PATH, OWNER_CHAT_ID

logger = get_logger(__name__)


class MonitorService:
    """Service for monitoring job sources with filtering and logging."""

    def __init__(self):
        self.kwork_parser = KworkParser()
        self.telegram_parser: Optional[TelegramSourceParser] = None

    async def fetch_all_vacancies(self) -> List[JobVacancy]:
        """Fetch vacancies from all enabled sources without saving to DB.

        Returns a list of raw vacancies (unfiltered, unsaved).
        This is used by the streaming check to process vacancies one by one.
        """
        all_vacancies: List[JobVacancy] = []

        async with aiosqlite.connect(DB_PATH) as db:
            sources = await queries.get_enabled_sources(db)

            for source in sources:
                try:
                    if source.source_type == "kwork":
                        vacancies = await self.kwork_parser.fetch_vacancies()
                        all_vacancies.extend(vacancies)
                        logger.info(
                            "monitor.kwork_fetched",
                            count=len(vacancies),
                        )

                    elif source.source_type == "telegram":
                        if not self.telegram_parser:
                            self.telegram_parser = TelegramSourceParser()
                            await self.telegram_parser.connect()

                        # Collect all URLs: legacy url field + new urls field
                        urls = []
                        if source.urls_list:
                            urls.extend(source.urls_list)
                        elif source.url:
                            urls.append(source.url)

                        for url in urls:
                            channel_username = url.split("/")[-1]
                            if not channel_username.startswith("@"):
                                channel_username = f"@{channel_username}"

                            vacancies = await self.telegram_parser.fetch_messages_from_channel(
                                channel_username, limit=20
                            )
                            all_vacancies.extend(vacancies)
                            logger.info(
                                "monitor.telegram_fetched",
                                channel=channel_username,
                                count=len(vacancies),
                            )

                except (ValueError, TypeError, ConnectionError, OSError, AttributeError, KeyError) as e:
                    logger.error(
                        "monitor.source_error",
                        source_name=source.name,
                        source_type=source.source_type,
                        error=str(e),
                    )
                    continue

        logger.info(
            "monitor.fetch_all_completed",
            total=len(all_vacancies),
        )
        return all_vacancies

    async def check_all_sources(self) -> int:
        """Check all enabled sources with pre-filtering."""
        new_count = 0
        filtered_count = 0

        async with aiosqlite.connect(DB_PATH) as db:
            sources = await queries.get_enabled_sources(db)
            profile = await queries.get_freelancer_profile(db, OWNER_CHAT_ID)
            filter_engine = VacancyFilter(profile)

            logger.info(
                "monitor.check_started",
                enabled_sources=len(sources),
                has_profile=profile is not None,
            )

            for source in sources:
                try:
                    if source.source_type == "kwork":
                        count, filtered = await self._check_kwork(db, filter_engine)
                        new_count += count
                        filtered_count += filtered

                    elif source.source_type == "telegram":
                        # Collect all URLs: legacy url field + new urls field
                        urls = []
                        if source.urls_list:
                            urls.extend(source.urls_list)
                        elif source.url:
                            urls.append(source.url)

                        for url in urls:
                            count, filtered = await self._check_telegram(db, url, filter_engine)
                            new_count += count
                            filtered_count += filtered

                except (ValueError, TypeError, ConnectionError, OSError, AttributeError, KeyError) as e:
                    logger.error(
                        "monitor.source_error",
                        source_name=source.name,
                        source_type=source.source_type,
                        error=str(e),
                    )
                    continue

        logger.info(
            "monitor.check_completed",
            new_vacancies=new_count,
            filtered_out=filtered_count,
            total_processed=new_count + filtered_count,
        )
        return new_count

    async def _check_kwork(self, db: aiosqlite.Connection, filter_engine: VacancyFilter) -> Tuple[int, int]:
        """Check Kwork with filtering. Returns (new_count, filtered_count)."""
        new_count = 0
        filtered_count = 0

        try:
            vacancies = await self.kwork_parser.fetch_vacancies()

            for vacancy in vacancies:
                if await queries.is_vacancy_seen(db, vacancy.kwork_id):
                    continue

                keep, reason = await filter_engine.apply_pre_filters(vacancy)
                if not keep:
                    vacancy.filtered_out = True
                    vacancy.filter_reason = reason
                    await queries.save_vacancy(db, vacancy)
                    filtered_count += 1
                    logger.info(
                        "monitor.pre_filtered",
                        kwork_id=vacancy.kwork_id,
                        reason=reason,
                        title=vacancy.title[:50],
                    )
                    continue

                await queries.save_vacancy(db, vacancy)
                new_count += 1
                logger.info(
                    "monitor.vacancy_saved",
                    kwork_id=vacancy.kwork_id,
                    title=vacancy.title[:50],
                    budget=vacancy.budget,
                    source="kwork",
                )

        except (ValueError, TypeError, ConnectionError, OSError, AttributeError, KeyError) as e:
            logger.error("monitor.kwork_error", error=str(e))

        return new_count, filtered_count

    async def _check_telegram(
        self, db: aiosqlite.Connection, channel_url: str, filter_engine: VacancyFilter
    ) -> Tuple[int, int]:
        """Check Telegram channel with filtering."""
        new_count = 0
        filtered_count = 0

        try:
            if not self.telegram_parser:
                self.telegram_parser = TelegramSourceParser()
                await self.telegram_parser.connect()

            channel_username = channel_url.split("/")[-1]
            if not channel_username.startswith("@"):
                channel_username = f"@{channel_username}"

            vacancies = await self.telegram_parser.fetch_messages_from_channel(
                channel_username, limit=20
            )

            for vacancy in vacancies:
                if await queries.is_vacancy_seen(db, vacancy.kwork_id):
                    continue

                keep, reason = await filter_engine.apply_pre_filters(vacancy)
                if not keep:
                    vacancy.filtered_out = True
                    vacancy.filter_reason = reason
                    await queries.save_vacancy(db, vacancy)
                    filtered_count += 1
                    logger.info(
                        "monitor.pre_filtered",
                        kwork_id=vacancy.kwork_id,
                        reason=reason,
                        source="telegram",
                    )
                    continue

                await queries.save_vacancy(db, vacancy)
                new_count += 1
                logger.info(
                    "monitor.vacancy_saved",
                    kwork_id=vacancy.kwork_id,
                    title=vacancy.title[:50],
                    source="telegram",
                )

        except (ValueError, TypeError, ConnectionError, OSError, AttributeError, KeyError) as e:
            logger.error("monitor.telegram_error", channel=channel_url, error=str(e))

        return new_count, filtered_count

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.telegram_parser:
            await self.telegram_parser.disconnect()
