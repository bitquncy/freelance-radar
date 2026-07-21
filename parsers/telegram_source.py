"""Telegram source parser using HTTP requests to t.me/s/ (public web preview)."""
import json
import re
import hashlib
from datetime import datetime
from typing import List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from services.logger_config import get_logger
from parsers.base import BaseParser
from db.models import JobVacancy
from config import USER_AGENT

logger = get_logger(__name__)


class TelegramSourceParser(BaseParser):
    """Parser for Telegram channels via public web preview (t.me/s/)."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def connect(self) -> None:
        await self._get_client()
        logger.info("telegram_source.connected")

    async def disconnect(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("telegram_source.disconnected")

    async def fetch_vacancies(self, limit: int = 10) -> List[JobVacancy]:
        return []

    async def fetch_project_list(self) -> List[str]:
        return []

    async def fetch_project_detail(self, url: str) -> Optional[JobVacancy]:
        return None

    async def fetch_messages_from_channel(
        self,
        channel_username: str,
        limit: int = 20,
    ) -> List[JobVacancy]:
        """Fetch recent messages from a Telegram channel via t.me/s/."""
        channel = channel_username.lstrip("@")
        url = f"https://t.me/s/{channel}"

        client = await self._get_client()

        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.error("telegram_source.fetch_error", channel=channel, error=str(e))
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        messages = soup.select(".tgme_widget_message_wrap")

        vacancies: List[JobVacancy] = []
        for msg in messages[:limit]:
            try:
                vacancy = self._parse_message(msg, channel)
                if vacancy:
                    vacancies.append(vacancy)
            except (AttributeError, KeyError, ValueError, TypeError) as e:
                logger.warning("telegram_source.parse_msg_error", error=str(e))

        logger.info(
            "telegram_source.fetched",
            channel=channel,
            count=len(vacancies),
        )
        return vacancies

    def _parse_message(self, msg, channel: str) -> Optional[JobVacancy]:
        """Parse a single message element into JobVacancy."""
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            return None

        text = text_el.get_text(separator="\n", strip=True)
        if len(text) < 20:
            return None

        # Extract message ID from data-post attribute
        post_el = msg.select_one(".tgme_widget_message")
        post_id = ""
        if post_el and post_el.get("data-post"):
            post_id = post_el["data-post"].split("/")[-1]

        kwork_id = hashlib.md5(f"tg_{channel}_{post_id}".encode()).hexdigest()[:16]

        # Extract title (first line)
        lines = text.split("\n")
        title = lines[0][:100] if lines else text[:100]

        # Extract budget
        budget = self._extract_budget(text)
        budget_min, budget_max = self._extract_budget_range(text)

        # Extract deadline
        deadline = self._extract_deadline(text)
        deadline_days = self._extract_deadline_days(text)

        # Extract category/skills
        category = self._extract_category(text)
        skills = self._extract_skills(text)

        # Message link
        url = f"https://t.me/{channel}/{post_id}"

        return JobVacancy(
            kwork_id=kwork_id,
            url=url,
            title=title,
            description=text[:2000],
            budget=budget,
            budget_min=budget_min,
            budget_max=budget_max,
            deadline=deadline,
            deadline_days=deadline_days,
            category=category,
            skills=json.dumps(skills, ensure_ascii=False) if skills else None,
            source=f"telegram:{channel}",
            fetched_at=datetime.now(),
        )

    def _extract_budget(self, text: str) -> Optional[str]:
        patterns = [
            r"(\d[\d\s]*(?:\s*[-–]\s*\d[\d\s]*)?\s*(?:руб|₽|rub|USD|\$|EUR|€))",
            r"(?:бюджет|оплата|стоимость|цена)[:\s]*(\d[\d\s]*(?:\s*[-–]\s*\d[\d\s]*)?)",
            r"(\d{3,6}\s*[-–]?\s*\d{0,6}\s*(?:руб|₽|\$|USD))",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_budget_range(self, text: str) -> Tuple[Optional[int], Optional[int]]:
        from parsers.utils import extract_budget_range_from_text
        budget_text = self._extract_budget(text)
        return extract_budget_range_from_text(budget_text)

    def _extract_deadline(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:срок|deadline|время)[:\s]*([^\n]{3,50})",
            r"(\d+\s*(?:день|дня|дней|недел|месяц|час|часов))",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_deadline_days(self, text: str) -> Optional[int]:
        from parsers.utils import extract_deadline_days
        return extract_deadline_days(text)

    def _extract_category(self, text: str) -> Optional[str]:
        hashtags = re.findall(r"#(\w+)", text)
        if hashtags:
            return hashtags[0]
        categories = [
            "python", "javascript", "web", "design", "seo", "marketing",
            "copywriting", "перевод", "mobile", "devops", "data", "backend",
            "frontend", "react", "node", "django", "бот", "парсинг",
        ]
        text_lower = text.lower()
        for cat in categories:
            if cat in text_lower:
                return cat
        return None

    def _extract_skills(self, text: str) -> Optional[List[str]]:
        hashtags = re.findall(r"#(\w+)", text)
        if hashtags:
            return hashtags[:10]
        return None

    async def send_message_to_chat(self, chat_id: str, message: str) -> bool:
        logger.warning("telegram_source.send_not_supported")
        return False
