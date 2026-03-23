from __future__ import annotations

from shared.models import User

REQUESTER_ROLE = "requester"
DEV_TI_ROLE = "dev_ti"
ADMIN_ROLE = "admin"
OPS_ROLES = {DEV_TI_ROLE, ADMIN_ROLE}


def is_requester(user: User) -> bool:
    return user.role == REQUESTER_ROLE


def is_ops_user(user: User) -> bool:
    return user.role in OPS_ROLES


def can_access_all_tickets(user: User) -> bool:
    return is_ops_user(user)


def can_access_ticket(user: User, owner_user_id) -> bool:
    if can_access_all_tickets(user):
        return True
    return user.id == owner_user_id
