from __future__ import annotations

import typing

from strawberry.permission import BasePermission
from strawberry.types import Info


def current_user(info: Info):  # noqa: ANN201
    request = getattr(info.context, "request", None)
    return getattr(request, "user", None)


class IsAuthenticated(BasePermission):
    message = "Authentication required: send 'Authorization: Bearer <token>' (see login mutation)"

    def has_permission(self, source: typing.Any, info: Info, **kwargs: typing.Any) -> bool:
        user = current_user(info)
        return bool(user is not None and user.is_authenticated)
