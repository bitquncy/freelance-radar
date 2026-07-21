"""Kwork parser v3 — single browser, route blocking, resilient selectors, JSON extraction."""
import asyncio
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
    Page,
    BrowserContext,
)
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from parsers.base import BaseParser
from db.models import JobVacancy
from services.rate_limiter import KworkRateLimiter
from services.logger_config import get_logger
from config import (
    KWORK_PROJECTS_URL,
    KWORK_REQUEST_DELAY_MIN,
    KWORK_REQUEST_DELAY_MAX,
    KWORK_MAX_DETAIL_PAGES,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Stealth configuration
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
]

ACCEPT_LANGUAGES = [
    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "ru-RU,ru;q=0.9",
]

STEALTH_SCRIPTS = [
    "() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); }",
    "() => { window.chrome = { runtime: {} }; }",
    "() => { Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] }); }",
    "() => { Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] }); }",
    (
        "() => { const orig = window.Notification.requestPermission;"
        " window.Notification.requestPermission = function(cb) {"
        " const r = 'default'; if(cb) cb(r); return Promise.resolve(r); }; }"
    ),
    (
        "() => { const iframes = document.querySelectorAll('iframe');"
        " for (const f of iframes) { try {"
        " Object.defineProperty(f.contentWindow.navigator, 'webdriver', { get: () => undefined });"
        " } catch(e) {} } }"
    ),
]

# Resource types to block (ads, analytics, fonts, media)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

# URL substrings that indicate analytics / ads / trackers
BLOCKED_URL_PATTERNS = [
    "mc.yandex.ru",
    "mc.webvisor.org",
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googleadservices.com",
    "facebook.com/tr",
    "vk.com/rtrg",
    "top-fwz1.mail.ru",
    "cdn-eu.dynamicyield",
    "mc.yandex.ru/metrika",
    "yandex.ru/metrika",
    "google-analytics",
    "googlesyndication",
    "adservice",
]

# Known tech skills for keyword extraction from descriptions
KNOWN_SKILLS = [
    "python", "django", "flask", "fastapi", "javascript", "typescript", "react",
    "vue", "angular", "next.js", "node.js", "php", "laravel", "wordpress",
    "html", "css", "sql", "postgresql", "mysql", "mongodb", "redis",
    "docker", "kubernetes", "aws", "gcp", "azure",
    "figma", "photoshop", "illustrator", "sketch", "after effects", "premiere pro",
    "1с", "bitrix", "telegram", "bot", "парсинг", "парсер",
    "seo", "smm", "таргет", "контекст", "директ", "google ads",
    "лендинг", "сайт", "дизайн", "логотип", "брендинг",
    "копирайтинг", "рерайт", "перевод",
    "маркетинг", "продажи", "hr", "бухгалтерия", "юриспруденция",
    "курс", "обучение", "api", "rest", "graphql",
    "unity", "unreal", "blender", "3d",
    "excel", "power bi", "tableau",
    "machine learning", "ai", "нейросеть", "gpt",
    "тестирование", "qa", "автотесты",
    "devops", "ci/cd", "git", "github",
    "tailwind", "bootstrap", "scss", "sass",
]

DEBUG_DIR = Path("debug")


class KworkParser(BaseParser):
    """Kwork parser v3: single browser cycle, route blocking, resilient selectors."""

    def __init__(self, max_detail_pages: Optional[int] = None):
        self.base_url = "https://kwork.ru"
        self.max_detail_pages = max_detail_pages or KWORK_MAX_DETAIL_PAGES
        self.rate_limiter = KworkRateLimiter(
            daily_limit=200,
            delay_min=float(KWORK_REQUEST_DELAY_MIN),
            delay_max=float(KWORK_REQUEST_DELAY_MAX),
        )

    # -----------------------------------------------------------------------
    # Stealth helpers
    # -----------------------------------------------------------------------
    def _get_stealth_headers(self, referer: Optional[str] = None) -> dict:
        headers = {
            "Accept-Language": random.choice(ACCEPT_LANGUAGES),
            "DNT": "1",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _get_browser_context_args(self) -> dict:
        ua = random.choice(USER_AGENTS)
        vp = random.choice(VIEWPORTS)
        return {
            "viewport": vp,
            "user_agent": ua,
            "locale": "ru-RU",
            "timezone_id": "Europe/Moscow",
            "geolocation": {"latitude": 55.7558, "longitude": 37.6173},
            "permissions": ["geolocation"],
            "color_scheme": "light",
            "reduced_motion": "no-preference",
        }

    @staticmethod
    async def _apply_stealth(page: Page) -> None:
        for script in STEALTH_SCRIPTS:
            try:
                await page.evaluate(script)
            except PlaywrightError:
                pass

    @staticmethod
    async def _block_unnecessary_requests(page: Page) -> None:
        """Block ads, analytics, trackers and heavy media resources."""
        async def _handler(route, request):
            url = request.url
            rtype = request.resource_type
            if rtype in BLOCKED_RESOURCE_TYPES:
                await route.abort()
                return
            for pattern in BLOCKED_URL_PATTERNS:
                if pattern in url:
                    await route.abort()
                    return
            await route.continue_()
        await page.route("**/*", _handler)

    async def _save_html_for_debug(self, page: Page, filename: str) -> None:
        DEBUG_DIR.mkdir(exist_ok=True)
        html_path = DEBUG_DIR / f"{filename}.html"
        png_path = DEBUG_DIR / f"{filename}.png"
        try:
            html = await page.content()
            html_path.write_text(html, encoding="utf-8")
            await page.screenshot(path=str(png_path), full_page=True)
            logger.info("kwork.debug_saved", html=str(html_path), screenshot=str(png_path))
        except (PlaywrightError, OSError, TypeError) as e:
            logger.warning("kwork.debug_save_failed", filename=filename, error=str(e))

    async def _setup_page(self, page: Page, referer: Optional[str] = None) -> None:
        """Apply stealth, route blocking, headers and cookies to a new page."""
        await self._apply_stealth(page)
        await self._block_unnecessary_requests(page)
        await page.set_extra_http_headers(self._get_stealth_headers(referer=referer))

    @staticmethod
    async def _human_scroll(page: Page) -> None:
        """Simulate random human-like scrolling."""
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 1.5)")
        await asyncio.sleep(random.uniform(0.5, 1.5))

    # -----------------------------------------------------------------------
    # Public API — single browser context for entire cycle
    # -----------------------------------------------------------------------
    async def fetch_vacancies(self, limit: int = 10) -> List[JobVacancy]:
        """Fetch vacancies using a single browser instance."""
        if not self.rate_limiter.can_make_request():
            logger.warning(
                "kwork.daily_limit_reached",
                daily_limit=self.rate_limiter.daily_limit,
                requests_today=self.rate_limiter._requests_today,
            )
            return []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                context = await browser.new_context(**self._get_browser_context_args())
                await context.add_cookies([{
                    "name": "visited",
                    "value": "1",
                    "domain": ".kwork.ru",
                    "path": "/",
                }])

                cards = await self._fetch_project_cards(context)
                logger.info("kwork.project_cards_found", count=len(cards))

                if not cards:
                    logger.warning("kwork.no_cards_found")
                    return []

                cards = cards[:limit]
                detail_count = min(len(cards), self.max_detail_pages)
                logger.info(
                    "kwork.detail_pages_planned",
                    detail_count=detail_count,
                    total_cards=len(cards),
                )

                vacancies: List[JobVacancy] = []
                for idx, card in enumerate(cards):
                    try:
                        url = card.get("url")
                        if not url:
                            continue

                        if idx < detail_count:
                            vacancy = await self._fetch_detail_from_context(
                                context, url, basic_info=card,
                            )
                        else:
                            vacancy = self._build_vacancy_from_card(card)

                        if vacancy:
                            vacancies.append(vacancy)
                            logger.info(
                                "kwork.vacancy_fetched",
                                kwork_id=vacancy.kwork_id,
                                title=vacancy.title[:60],
                                budget=vacancy.budget,
                                has_detail=(idx < detail_count),
                            )

                        await self.rate_limiter.sleep()
                    except (PlaywrightError, ValueError, TypeError, KeyError, AttributeError) as e:
                        logger.error("kwork.fetch_detail_error", url=card.get("url"), error=str(e))
                        continue

                logger.info("kwork.fetch_completed", total_found=len(vacancies))
                return vacancies

            finally:
                await browser.close()

    async def fetch_project_list(self) -> List[str]:
        """Fetch list of project URLs (backward compatibility)."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                context = await browser.new_context(**self._get_browser_context_args())
                await context.add_cookies([{
                    "name": "visited",
                    "value": "1",
                    "domain": ".kwork.ru",
                    "path": "/",
                }])
                cards = await self._fetch_project_cards(context)
                return [c["url"] for c in cards if c.get("url")]
            finally:
                await browser.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((PlaywrightTimeout, ConnectionError, OSError)),
        reraise=True,
    )
    async def fetch_project_detail(self, url: str, basic_info: Optional[dict] = None) -> Optional[JobVacancy]:
        """Fetch detailed project info (standalone, with its own browser)."""
        if not self.rate_limiter.can_make_request():
            return None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                context = await browser.new_context(**self._get_browser_context_args())
                await context.add_cookies([{
                    "name": "visited",
                    "value": "1",
                    "domain": ".kwork.ru",
                    "path": "/",
                }])
                return await self._fetch_detail_from_context(context, url, basic_info)
            finally:
                await browser.close()

    # -----------------------------------------------------------------------
    # Internal: list page parsing (uses shared context)
    # -----------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((PlaywrightTimeout, ConnectionError, OSError)),
        reraise=True,
    )
    async def _fetch_project_cards(self, context: BrowserContext) -> List[dict]:
        if not self.rate_limiter.can_make_request():
            return []

        cards: List[dict] = []
        page = await context.new_page()
        try:
            await self._setup_page(page)
            logger.info("kwork.fetching_list", url=KWORK_PROJECTS_URL)

            await page.goto(KWORK_PROJECTS_URL, wait_until="networkidle")
            try:
                await page.wait_for_selector(".want-card", state="attached", timeout=20000)
            except PlaywrightTimeout:
                logger.warning("kwork.wait_for_cards_timeout")
            await asyncio.sleep(random.uniform(3, 5))
            await self._human_scroll(page)

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            self.rate_limiter.record_request()

            if self._is_blocked(soup):
                logger.error("kwork.blocked_or_captcha_list")
                await self._save_html_for_debug(page, "blocked_list")
                return []

            card_elements = soup.find_all("div", class_="want-card")
            logger.info("kwork.raw_cards_found", count=len(card_elements))

            seen_ids: set = set()
            for card_el in card_elements:
                parsed = self._parse_list_card(card_el)
                if not parsed:
                    continue
                kid = parsed.get("kwork_id")
                if kid and kid not in seen_ids:
                    seen_ids.add(kid)
                    cards.append(parsed)

            if not cards:
                logger.warning("kwork.no_project_cards_found")
                await self._save_html_for_debug(page, "no_cards_list")
        finally:
            await page.close()

        return cards

    # -----------------------------------------------------------------------
    # Internal: detail page parsing (uses shared context)
    # -----------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((PlaywrightTimeout, ConnectionError, OSError)),
        reraise=True,
    )
    async def _fetch_detail_from_context(
        self, context: BrowserContext, url: str,
        basic_info: Optional[dict] = None,
    ) -> Optional[JobVacancy]:
        if not self.rate_limiter.can_make_request():
            return None

        match = re.search(r"/projects/(\d+)(?:/view)?", url)
        if not match:
            logger.warning("kwork.invalid_url", url=url)
            return None

        kwork_id = match.group(1)
        full_url = urljoin(self.base_url, f"/projects/{kwork_id}/view")

        page = await context.new_page()
        try:
            await self._setup_page(page, referer=KWORK_PROJECTS_URL)
            logger.debug("kwork.fetching_detail", kwork_id=kwork_id, url=full_url)

            await page.goto(full_url, wait_until="networkidle")
            try:
                await page.wait_for_selector(
                    "[class*='wants-card__header-title']",
                    state="attached",
                    timeout=20000,
                )
            except PlaywrightTimeout:
                logger.warning("kwork.wait_for_title_timeout", kwork_id=kwork_id)
            await asyncio.sleep(random.uniform(3, 5))
            await self._human_scroll(page)

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            self.rate_limiter.record_request()

            if self._is_blocked(soup):
                logger.error("kwork.blocked_or_captcha", kwork_id=kwork_id, url=full_url)
                await self._save_html_for_debug(page, f"blocked_{kwork_id}")
                return None

            # Try extracting structured JSON from <script> tags
            json_data = self._extract_json_data(soup)

            title = self._extract_title(soup) or (basic_info.get("title") if basic_info else None)
            description = self._extract_description(soup)

            if not title:
                logger.warning("kwork.missing_title", kwork_id=kwork_id)
                await self._save_html_for_debug(page, f"missing_title_{kwork_id}")
                return None

            if not description and basic_info:
                description = basic_info.get("description")

            budget_text = self._extract_budget_text(soup) or (basic_info.get("budget") if basic_info else None)
            budget_min, budget_max = self._extract_budget_range(soup, budget_text)
            deadline_text = self._extract_deadline_text(soup) or (basic_info.get("deadline") if basic_info else None)
            deadline_days = self._extract_deadline_days(deadline_text)
            category = (
                self._extract_category(soup)
                or self._deep_search(json_data, ["category", "category_name", "rubric"], str)
                or (basic_info.get("category") if basic_info else None)
            )
            subcategory = (
                self._extract_subcategory(soup)
                or self._deep_search(json_data, ["subcategory", "sub_category"], str)
                or (basic_info.get("subcategory") if basic_info else None)
            )
            skills = self._extract_skills(soup, description=description, json_data=json_data)
            proposals_count = self._extract_proposals_count(soup) or (basic_info.get("proposals_count") if basic_info else None)
            customer_rating = self._extract_customer_rating(soup) or (basic_info.get("customer_rating") if basic_info else None)
            customer_orders = self._extract_customer_orders(soup) or (basic_info.get("customer_orders") if basic_info else None)

            return JobVacancy(
                kwork_id=kwork_id,
                url=full_url,
                title=title,
                description=description or "",
                budget=budget_text,
                budget_min=budget_min,
                budget_max=budget_max,
                deadline=deadline_text,
                deadline_days=deadline_days,
                category=category,
                subcategory=subcategory,
                skills=json.dumps(skills, ensure_ascii=False) if skills else None,
                proposals_count=proposals_count,
                customer_rating=customer_rating,
                customer_orders=customer_orders,
                source="kwork",
                fetched_at=datetime.now(),
            )
        finally:
            await page.close()

    # -----------------------------------------------------------------------
    # JSON extraction from <script> tags
    # -----------------------------------------------------------------------
    @staticmethod
    def _extract_json_data(soup: BeautifulSoup) -> Optional[dict]:
        """Try to extract inline JSON data (e.g. __INITIAL_STATE__, __DATA__)."""
        scripts = soup.find_all("script")
        for script in scripts:
            if not script.string:
                continue
            text = script.string
            for pattern in [
                r"window\.__INITIAL_STATE__\s*=\s*({.+?});?\s*$",
                r"window\.__DATA__\s*=\s*({.+?});?\s*$",
                r"window\.__PROJECT__\s*=\s*({.+?});?\s*$",
                r"window\.config\s*=\s*Object\.assign\(config,\s*({.+?})\)",
            ]:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except (json.JSONDecodeError, ValueError):
                        continue
        return None

    @staticmethod
    def _deep_search(data: Any, keys: List[str], expected_type: type) -> Optional[Any]:
        """Recursively search a nested dict/list for a key whose value matches expected_type."""
        if data is None:
            return None
        if isinstance(data, dict):
            for k, v in data.items():
                if k in keys and isinstance(v, expected_type):
                    return v
                result = KworkParser._deep_search(v, keys, expected_type)
                if result is not None:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = KworkParser._deep_search(item, keys, expected_type)
                if result is not None:
                    return result
        return None

    # -----------------------------------------------------------------------
    # Card parsing (list page)
    # -----------------------------------------------------------------------
    def _parse_list_card(self, card_el) -> Optional[dict]:
        # Title & URL — use regex class matching for resilience
        title_el = card_el.find(["h1", "h2"], class_=re.compile(r"header-title"))
        if not title_el:
            return None

        link_el = title_el.find("a", href=True)
        if not link_el:
            return None

        href = link_el["href"]
        match = re.search(r"/projects/(\d+)", href)
        if not match:
            return None

        kwork_id = match.group(1)
        title = link_el.get_text(strip=True)
        url = urljoin(self.base_url, f"/projects/{kwork_id}/view")

        # Description (truncated on list page)
        description = None
        desc_el = card_el.find("div", class_=re.compile(r"description-text"))
        if desc_el:
            visible_div = desc_el.find("div", class_="breakwords")
            if visible_div:
                description = visible_div.get_text(separator="\n", strip=True)
            else:
                description = desc_el.get_text(separator="\n", strip=True)

        # Budget
        budget_text = None
        price_el = card_el.find("div", class_=re.compile(r"wants-card__price|price"))
        if price_el:
            budget_text = price_el.get_text(strip=True)

        higher_el = card_el.find("div", class_=re.compile(r"higher-price"))
        if higher_el and budget_text:
            budget_text = f"{budget_text} ({higher_el.get_text(strip=True)})"
        elif higher_el:
            budget_text = higher_el.get_text(strip=True)

        # Deadline & proposals from informers
        deadline_text = None
        proposals_count = None
        informers = card_el.find("div", class_=re.compile(r"informers"))
        if informers:
            for span in informers.find_all("span"):
                text = span.get_text(strip=True)
                if any(k in text for k in ["Осталось", "д.", "ч.", "мин."]):
                    deadline_text = text.replace("Осталось:", "").strip()
                elif any(k in text.lower() for k in ["предложен", "отклик"]):
                    m = re.search(r"(\d+)", text)
                    if m:
                        proposals_count = int(m.group(1))

        # Customer info
        customer_rating = None
        customer_orders = None
        customer_el = card_el.find("div", class_=re.compile(r"payer-statistic|customer"))
        if customer_el:
            text = customer_el.get_text(separator=" ", strip=True)
            m = re.search(r"Размещено проектов на бирже:\s*(\d+)", text)
            if m:
                customer_orders = int(m.group(1))
            m = re.search(r"(\d+[.,]\d+)\s*рейтинг", text, re.I)
            if m:
                customer_rating = float(m.group(1).replace(",", "."))

        return {
            "kwork_id": kwork_id,
            "url": url,
            "title": title,
            "description": description,
            "budget": budget_text,
            "deadline": deadline_text,
            "proposals_count": proposals_count,
            "customer_rating": customer_rating,
            "customer_orders": customer_orders,
        }

    def _build_vacancy_from_card(self, card: dict) -> Optional[JobVacancy]:
        if not card.get("title"):
            return None
        budget_text = card.get("budget")
        budget_min, budget_max = self._extract_budget_range_from_text(budget_text)
        deadline_days = self._extract_deadline_days(card.get("deadline"))
        return JobVacancy(
            kwork_id=card["kwork_id"],
            url=card["url"],
            title=card["title"],
            description=card.get("description") or "",
            budget=budget_text,
            budget_min=budget_min,
            budget_max=budget_max,
            deadline=card.get("deadline"),
            deadline_days=deadline_days,
            category=None,
            subcategory=None,
            skills=None,
            proposals_count=card.get("proposals_count"),
            customer_rating=card.get("customer_rating"),
            customer_orders=card.get("customer_orders"),
            source="kwork",
            fetched_at=datetime.now(),
        )

    # -----------------------------------------------------------------------
    # Blocking detection
    # -----------------------------------------------------------------------
    @staticmethod
    def _is_blocked(soup: BeautifulSoup) -> bool:
        text = soup.get_text(separator=" ", strip=True).lower()
        indicators = [
            "smartcaptcha",
            "подтвердите, что вы не робот",
            "доступ ограничен",
            "проверка безопасности",
            "captcha",
            "я не робот",
        ]
        return any(ind in text for ind in indicators)

    # -----------------------------------------------------------------------
    # Extractors — resilient selectors + regex fallback
    # -----------------------------------------------------------------------
    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        # Primary: h1/h2 with class containing header-title
        for tag in ["h1", "h2"]:
            el = soup.find(tag, class_=re.compile(r"header-title"))
            if el:
                link = el.find("a")
                return link.get_text(strip=True) if link else el.get_text(strip=True)
        # Fallback: any h1
        h1 = soup.find("h1")
        return h1.get_text(strip=True) if h1 else None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        # Primary: div with class containing description-text
        el = soup.find("div", class_=re.compile(r"description-text|project-description"))
        if el:
            visible = el.find("div", class_="breakwords")
            text = visible.get_text(separator="\n", strip=True) if visible else el.get_text(separator="\n", strip=True)
            return text[:3000] if text else None
        # Fallback: largest text block near h1
        h1 = soup.find("h1")
        if h1:
            parent = h1.find_parent("div")
            if parent:
                for sibling in parent.find_next_siblings():
                    txt = sibling.get_text(separator="\n", strip=True)
                    if len(txt) > 100:
                        return txt[:3000]
        return None

    def _extract_budget_text(self, soup: BeautifulSoup) -> Optional[str]:
        el = soup.find("div", class_=re.compile(r"wants-card__price|project-price|price"))
        if el:
            return el.get_text(strip=True)
        # Fallback regex
        text = soup.get_text(separator=" ", strip=True)
        match = re.search(r"(?:Желаемый бюджет|Цена до)[:\s]*[^\n]{1,60}", text)
        return match.group(0).strip() if match else None

    def _extract_budget_range(self, soup: BeautifulSoup, budget_text: Optional[str] = None) -> Tuple[Optional[int], Optional[int]]:
        text = budget_text or self._extract_budget_text(soup)
        return self._extract_budget_range_from_text(text)

    @staticmethod
    def _extract_budget_range_from_text(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
        from parsers.utils import extract_budget_range_from_text as _extract
        return _extract(text)

    def _extract_deadline_text(self, soup: BeautifulSoup) -> Optional[str]:
        informers = soup.find("div", class_=re.compile(r"informers"))
        if informers:
            for span in informers.find_all("span"):
                text = span.get_text(strip=True)
                if any(k in text for k in ["Осталось", "д.", "ч.", "мин.", "день", "дня", "дней"]):
                    return text.replace("Осталось:", "").strip()
        # Fallback regex
        text = soup.get_text(separator=" ", strip=True)
        match = re.search(r"Осталось[:\s]*([^\n]{1,40})", text)
        return match.group(1).strip() if match else None

    def _extract_deadline_days(self, deadline_text: Optional[str]) -> Optional[int]:
        if not deadline_text:
            return None
        text = deadline_text.lower()
        # Check for weeks first
        weeks_match = re.search(r"(\d+)\s*(?:недел|неделю|недели)", text)
        if weeks_match:
            return int(weeks_match.group(1)) * 7
        # Check for days
        days_match = re.search(r"(\d+)\s*д(?:\.|[няей]+)", text)
        if days_match:
            days = int(days_match.group(1))
            hours_match = re.search(r"(\d+)\s*ч(?:\.|[асов]+)", text)
            if hours_match and int(hours_match.group(1)) >= 12:
                days += 1
            return days
        # Check for months
        months_match = re.search(r"(\d+)\s*(?:месяц|месяца|месяцев)", text)
        if months_match:
            return int(months_match.group(1)) * 30
        # Check for hours
        hours_match = re.search(r"(\d+)\s*ч(?:\.|[асов]+)", text)
        if hours_match:
            return 1 if int(hours_match.group(1)) > 0 else 0
        numbers = re.findall(r"\d+", text)
        return int(numbers[0]) if numbers else None

    def _extract_category(self, soup: BeautifulSoup) -> Optional[str]:
        breadcrumbs = soup.find("nav", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all("a")
            if len(links) >= 2:
                return links[1].get_text(strip=True)
        # Fallback: category link
        cat_link = soup.find("a", href=re.compile(r"/categories/[^/]+$"))
        if cat_link:
            return cat_link.get_text(strip=True)
        return None

    def _extract_subcategory(self, soup: BeautifulSoup) -> Optional[str]:
        breadcrumbs = soup.find("nav", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all("a")
            if len(links) >= 3:
                return links[2].get_text(strip=True)
        return None

    def _extract_skills(
        self,
        soup: BeautifulSoup,
        description: Optional[str] = None,
        json_data: Optional[dict] = None,
    ) -> Optional[List[str]]:
        """Extract skills from DOM tags, JSON data, and description keywords."""
        seen: set = set()
        result: List[str] = []

        def _add(text: str) -> None:
            t = text.strip()
            if t and len(t) < 50 and t.lower() not in seen:
                seen.add(t.lower())
                result.append(t)

        # 1. DOM tags
        for tag_el in soup.find_all("a", class_=re.compile(r"tag|skill")):
            _add(tag_el.get_text(strip=True))
        skill_list = soup.find("div", class_=re.compile(r"skills|tags"))
        if skill_list:
            for item in skill_list.find_all(["a", "span"]):
                _add(item.get_text(strip=True))

        # 2. JSON data
        if json_data:
            for key in ["skills", "tags", "requirements", "required_skills"]:
                json_skills = self._deep_search(json_data, [key], list)
                if isinstance(json_skills, list):
                    for s in json_skills:
                        if isinstance(s, str):
                            _add(s)

        # 3. Description keyword extraction
        if description:
            desc_lower = description.lower()
            for skill in KNOWN_SKILLS:
                if skill in desc_lower:
                    _add(skill)

        return result if result else None

    def _extract_proposals_count(self, soup: BeautifulSoup) -> Optional[int]:
        informers = soup.find("div", class_=re.compile(r"informers"))
        if informers:
            for span in informers.find_all("span"):
                text = span.get_text(strip=True)
                if any(k in text.lower() for k in ["предложен", "отклик"]):
                    m = re.search(r"(\d+)", text)
                    if m:
                        return int(m.group(1))
        # Fallback
        text = soup.get_text(separator=" ", strip=True)
        for pattern in [r"Предложений[:\s]*(\d+)", r"(\d+)\s*предложени", r"(\d+)\s*отклик"]:
            m = re.search(pattern, text, re.I)
            if m:
                return int(m.group(1))
        return None

    def _extract_customer_rating(self, soup: BeautifulSoup) -> Optional[float]:
        customer = soup.find("div", class_=re.compile(r"payer-statistic|customer"))
        if customer:
            text = customer.get_text(separator=" ", strip=True)
            match = re.search(r"(\d+[.,]\d+)", text)
            if match:
                val = float(match.group(1).replace(",", "."))
                if 0 <= val <= 5:
                    return val
        text = soup.get_text(separator=" ", strip=True)
        match = re.search(r"(\d+[.,]\d+)\s*рейтинг", text, re.I)
        return float(match.group(1).replace(",", ".")) if match else None

    def _extract_customer_orders(self, soup: BeautifulSoup) -> Optional[int]:
        customer = soup.find("div", class_=re.compile(r"payer-statistic|customer"))
        if customer:
            text = customer.get_text(separator=" ", strip=True)
            m = re.search(r"Размещено проектов на бирже[:\s]*(\d+)", text)
            if m:
                return int(m.group(1))
        text = soup.get_text(separator=" ", strip=True)
        for pattern in [
            r"Размещено проектов на бирже[:\s]*(\d+)",
            r"(\d+)\s*заказ",
            r"(\d+)\s*проект",
        ]:
            m = re.search(pattern, text, re.I)
            if m:
                return int(m.group(1))
        return None
