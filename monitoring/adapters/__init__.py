"""Source adapters with the single interface ``fetch() -> list[RawListing]`` (§3.1)."""
from monitoring.adapters.base import RawListing, SourceAdapter

__all__ = ["RawListing", "SourceAdapter"]
