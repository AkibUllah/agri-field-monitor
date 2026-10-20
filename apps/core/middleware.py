"""Set ``request.user`` from a bearer JWT so GraphQL resolvers see the same user as DRF."""

from __future__ import annotations

import logging

from django.utils.functional import SimpleLazyObject

from apps.core.auth import TokenError, bearer_token, user_from_token

logger = logging.getLogger(__name__)


class JWTAuthenticationMiddleware:
    def __init__(self, get_response) -> None:  # noqa: ANN001
        self.get_response = get_response

    def __call__(self, request):  # noqa: ANN001
        token = bearer_token(request.META.get("HTTP_AUTHORIZATION"))
        if token is not None:
            session_user = request.user

            def resolve():  # noqa: ANN202
                try:
                    return user_from_token(token)
                except TokenError as exc:
                    logger.debug("rejected bearer token: %s", exc)
                    request.jwt_error = str(exc)
                    return session_user

            request.user = SimpleLazyObject(resolve)
        return self.get_response(request)
