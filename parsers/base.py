"""Base parser interface for job sources."""
from abc import ABC, abstractmethod
from typing import List, Optional
from db.models import JobVacancy


class BaseParser(ABC):
    """Base class for all job source parsers."""

    @abstractmethod
    async def fetch_vacancies(self, limit: int = 10) -> List[JobVacancy]:
        """
        Fetch new vacancies from the source.

        Args:
            limit: Maximum number of vacancies to return.

        Returns:
            List of JobVacancy objects
        """
        pass

    @abstractmethod
    async def fetch_project_list(self) -> List[str]:
        """
        Fetch list of project URLs from the source.

        Returns:
            List of project URLs
        """
        pass

    @abstractmethod
    async def fetch_project_detail(self, url: str) -> Optional[JobVacancy]:
        """
        Fetch detailed information about a specific project.

        Args:
            url: Project URL

        Returns:
            JobVacancy object with project details
        """
        pass
