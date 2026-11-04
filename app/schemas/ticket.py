from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    customer_id: int
    order_id: int | None = None
    subject: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)


class TicketUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=50)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    order_id: int | None
    subject: str
    description: str
    status: str