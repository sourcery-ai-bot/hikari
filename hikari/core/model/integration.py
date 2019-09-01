#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © Nekoka.tt 2019
#
# This file is part of Hikari.
#
# Hikari is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Hikari is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Hikari. If not, see <https://www.gnu.org/licenses/>.
"""
Account integrations.
"""
from __future__ import annotations

import datetime

import typing

from hikari.core.model import base
from hikari.core.model import model_cache
from hikari.core.model import user
from hikari.core.utils import dateutils
from hikari.core.utils import transform


@base.dataclass()
class IntegrationAccount(base.Snowflake):
    """
    An account used for an integration.
    """

    __slots__ = ("_state", "id", "name")

    _state: typing.Any

    #: The id for the account
    #:
    #: :type: :class:`int`
    id: int

    #: The name of the account
    #:
    #: :type: :class:`str`
    name: str

    @staticmethod
    def from_dict(global_state: model_cache.AbstractModelCache, payload):
        return IntegrationAccount(
            _state=global_state, id=transform.get_cast(payload, "id", int), name=payload.get("name")
        )


@base.dataclass()
class Integration(base.Snowflake):
    """
    A guild integration.
    """

    __slots__ = (
        "_state",
        "id",
        "name",
        "type",
        "enabled",
        "syncing",
        "_role_id",
        "expire_grace_period",
        "user",
        "account",
        "synced_at",
    )

    _state: typing.Any
    _role_id: int

    #: The integration ID
    #:
    #: :type: :class:`int`
    id: int

    #: The name of the integration
    #:
    #: :type: :class:`str`
    name: str

    #: The type of integration (e.g. twitch, youtube, etc)
    #:
    #: :type: :class:`str`
    type: str

    #: Whether the integration is enabled or not.
    #:
    #: :type: :class:`bool`
    enabled: bool

    #: Whether the integration is currently synchronizing.
    #:
    #: :type: :class:`bool`
    syncing: bool

    #: The grace period for expiring subscribers.
    #:
    #: :type: :class:`int`
    expire_grace_period: int

    #: The user for this integration
    #:
    #: :type: :class:`hikari.core.model.user.User`
    user: user.User

    #: Integration account information.
    #:
    #: :type: :class:`hikari.core.model.integration.IntegrationAccount`
    account: IntegrationAccount

    #: The time when the integration last synchronized.
    #:
    #: :type: :class:`datetime.datetime`
    synced_at: datetime.datetime

    @staticmethod
    def from_dict(global_state: model_cache.AbstractModelCache, payload):
        return Integration(
            _state=global_state,
            id=transform.get_cast(payload, "id", int),
            name=payload.get("name"),
            type=payload.get("type"),
            enabled=transform.get_cast(payload, "enabled", bool),
            syncing=transform.get_cast(payload, "syncing", bool),
            _role_id=transform.get_cast(payload, "role_id", int),
            expire_grace_period=transform.get_cast(payload, "expire_grace_period", int),
            user=global_state.parse_user(payload.get("user")),
            account=IntegrationAccount.from_dict(
                global_state, payload.get("account")
            ),  #  Change this later, slightly hacky way to do it
            synced_at=transform.get_cast(payload, "synced_at", dateutils.parse_iso_8601_datetime),
        )


__all__ = ["Integration", "IntegrationAccount"]