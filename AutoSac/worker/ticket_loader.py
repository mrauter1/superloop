from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import Ticket, TicketAttachment, TicketMessage


@dataclass(frozen=True)
class LoadedTicketContext:
    ticket: Ticket
    public_messages: Sequence[TicketMessage]
    internal_messages: Sequence[TicketMessage]
    public_attachments: Sequence[TicketAttachment]


def load_ticket_context(db: Session, ticket_id: uuid.UUID) -> LoadedTicketContext:
    ticket = db.execute(select(Ticket).where(Ticket.id == ticket_id)).scalar_one()
    public_messages = db.execute(
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id, TicketMessage.visibility == "public")
        .order_by(TicketMessage.created_at.asc())
    ).scalars().all()
    internal_messages = db.execute(
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id, TicketMessage.visibility == "internal")
        .order_by(TicketMessage.created_at.asc())
    ).scalars().all()
    public_attachments = db.execute(
        select(TicketAttachment)
        .where(TicketAttachment.ticket_id == ticket_id, TicketAttachment.visibility == "public")
        .order_by(TicketAttachment.created_at.asc())
    ).scalars().all()
    return LoadedTicketContext(
        ticket=ticket,
        public_messages=public_messages,
        internal_messages=internal_messages,
        public_attachments=public_attachments,
    )
