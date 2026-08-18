import re

from pydantic import BaseModel, Field, computed_field

# Flag icons in the source are named by emoji codepoints: 1f1f5-1f1f1.png -> 🇵🇱
_FLAG_CODEPOINTS = re.compile(r"([0-9a-f]{4,5})-([0-9a-f]{4,5})\.png")


class Country(BaseModel):
    id: int
    name: str
    icon: str | None = None

    @computed_field
    @property
    def flag_emoji(self) -> str | None:
        """Derive the emoji from the file name so the client does not pull an
        image from a third-party server — see AGENTS.md, rule 1."""
        if not self.icon:
            return None
        m = _FLAG_CODEPOINTS.search(self.icon)
        if not m:
            return None
        return chr(int(m.group(1), 16)) + chr(int(m.group(2), 16))


class Filters(BaseModel):
    countries: list[Country] = []


class WorkloadItem(BaseModel):
    """One queue in the eCherha response.

    Unknown fields are ignored: the source may add its own, and that is no
    reason to fail.
    """

    id: int
    title: str
    country_id: int | None = None
    for_vehicle_type: int
    queue_flow: int | None = None
    is_paused: bool = False
    cancel_after: int | None = None
    lat: float | None = None
    lng: float | None = None
    wait_time: int = 0
    vehicles_in_queue: int = Field(0, alias="vehicle_in_active_queues_counts")


class WorkloadResponse(BaseModel):
    data: list[WorkloadItem]
    filters: Filters = Filters()
