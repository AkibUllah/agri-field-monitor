"""Stateless JWT auth shared by the GraphQL endpoint (via middleware) and DRF views."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from rest_framework import authentication, exceptions


class TokenError(Exception):
    pass


def create_token(user: AbstractBaseUser, lifetime: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    lifetime = lifetime or timedelta(hours=settings.JWT_LIFETIME_HOURS)
    payload = {
        "sub": str(user.pk),
        "username": user.get_username(),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc


def user_from_token(token: str) -> AbstractBaseUser:
    payload = decode_token(token)
    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=payload["sub"], is_active=True)
    except (user_model.DoesNotExist, KeyError, ValueError) as exc:
        raise TokenError("user not found") from exc
    return user


def bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


class JWTAuthentication(authentication.BaseAuthentication):
    """DRF authenticator for ``Authorization: Bearer <jwt>``."""

    keyword = "Bearer"

    def authenticate(self, request):  # noqa: ANN001
        token = bearer_token(request.META.get("HTTP_AUTHORIZATION"))
        if token is None:
            return None
        try:
            user = user_from_token(token)
        except TokenError as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc
        return user, token

    def authenticate_header(self, request) -> str:  # noqa: ANN001
        return self.keyword
