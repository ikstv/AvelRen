from pydantic import BaseModel, Field


class WorkloadItem(BaseModel):
    """Одна черга у відповіді єЧерги.

    Невідомі поля ігноруємо: джерело може додати свої, і це не привід падати.
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
