# -*- coding: utf-8 -*-
# Copyright (c) 2020 Nekokatt
# Copyright (c) 2021-present davfsa
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import asyncio
import contextlib
import time

import mock
import pytest

from hikari import errors
from hikari.impl import buckets
from hikari.impl import rate_limits
from hikari.internal import routes
from hikari.internal import time as hikari_date


class TestRESTBucket:
    @pytest.fixture()
    def template(self):
        return routes.Route("GET", "/foo/bar")

    @pytest.fixture()
    def compiled_route(self, template):
        return routes.CompiledRoute("/foo/bar", template, "1a2b3c")

    @pytest.mark.asyncio()
    async def test_async_context_manager(self, compiled_route):
        with mock.patch.object(buckets.RESTBucket, "acquire", new=mock.AsyncMock()) as acquire:
            with mock.patch.object(buckets.RESTBucket, "release") as release:
                async with buckets.RESTBucket("spaghetti", compiled_route, object(), float("inf")):
                    acquire.assert_awaited_once_with()
                    release.assert_not_called()

            release.assert_called_once_with()

    @pytest.mark.parametrize("name", ["spaghetti", buckets.UNKNOWN_HASH])
    def test_is_unknown(self, name, compiled_route):
        with buckets.RESTBucket(name, compiled_route, object(), float("inf")) as rl:
            assert rl.is_unknown is (name == buckets.UNKNOWN_HASH)

    def test_release(self, compiled_route):
        with buckets.RESTBucket(__name__, compiled_route, object(), float("inf")) as rl:
            rl._lock = mock.Mock()

            rl.release()

            rl._lock.release.assert_called_once_with()

    def test_update_rate_limit(self, compiled_route):
        with buckets.RESTBucket(__name__, compiled_route, object(), float("inf")) as rl:
            rl.remaining = 1
            rl.limit = 2
            rl.reset_at = 3
            rl.period = 2

            with mock.patch.object(hikari_date, "monotonic", return_value=4.20):
                rl.update_rate_limit(9, 18, 27)

            assert rl.remaining == 9
            assert rl.limit == 18
            assert rl.reset_at == 27
            assert rl.period == 27 - 4.20

    @pytest.mark.asyncio()
    async def test_acquire_when_unknown_bucket(self, compiled_route):
        with buckets.RESTBucket(buckets.UNKNOWN_HASH, compiled_route, object(), float("inf")) as rl:
            rl._lock = mock.AsyncMock()
            with mock.patch.object(rate_limits.WindowedBurstRateLimiter, "acquire") as super_acquire:
                assert await rl.acquire() is None

            rl._lock.acquire.assert_awaited_once_with()
            super_acquire.assert_not_called()

    @pytest.mark.asyncio()
    async def test_acquire_when_too_long_ratelimit(self, compiled_route):
        stack = contextlib.ExitStack()
        rl = stack.enter_context(buckets.RESTBucket("spaghetti", compiled_route, object(), 60))
        rl._lock = mock.Mock(acquire=mock.AsyncMock())
        rl.reset_at = time.perf_counter() + 999999999999999999999999999
        stack.enter_context(mock.patch.object(buckets.RESTBucket, "is_rate_limited", return_value=True))
        stack.enter_context(pytest.raises(errors.RateLimitTooLongError))

        with stack:
            await rl.acquire()

        rl._lock.acquire.assert_awaited_once_with()
        rl._lock.release.assert_called_once_with()

    @pytest.mark.asyncio()
    async def test_acquire(self, compiled_route):
        global_ratelimit = mock.AsyncMock()

        with buckets.RESTBucket("spaghetti", compiled_route, global_ratelimit, float("inf")) as rl:
            rl._lock = mock.AsyncMock()
            with mock.patch.object(rate_limits.WindowedBurstRateLimiter, "acquire") as super_acquire:
                await rl.acquire()

            super_acquire.assert_awaited_once_with()
            rl._lock.acquire.assert_awaited_once_with()
            global_ratelimit.acquire.assert_awaited_once_with()

    def test_resolve_when_not_unknown(self, compiled_route):
        with buckets.RESTBucket("spaghetti", compiled_route, object(), float("inf")) as rl:
            with pytest.raises(RuntimeError, match=r"Cannot resolve known bucket"):
                rl.resolve("test")

            assert rl.name == "spaghetti"

    def test_resolve(self, compiled_route):
        with buckets.RESTBucket(buckets.UNKNOWN_HASH, compiled_route, object(), float("inf")) as rl:
            rl.resolve("test")

            assert rl.name == "test"


class TestRESTBucketManager:
    @pytest.fixture()
    def bucket_manager(self):
        manager = buckets.RESTBucketManager(max_rate_limit=float("inf"))
        manager._closed_event = mock.Mock(wait=mock.AsyncMock(), is_set=mock.Mock(return_value=False))

        return manager

    @pytest.mark.asyncio()
    async def test_close_closes_all_buckets(self, bucket_manager):
        buckets_array = [mock.Mock() for _ in range(30)]
        bucket_manager._real_hashes_to_buckets = {f"blah{i}": b for i, b in enumerate(buckets_array)}

        bucket_manager.close()

        assert not bucket_manager._real_hashes_to_buckets

        for i, b in enumerate(buckets_array):
            b.close.assert_called_once(), i

    @pytest.mark.asyncio()
    async def test_close_sets_closed_event(self, bucket_manager):
        closed_event = mock.Mock()
        bucket_manager._closed_event = closed_event

        bucket_manager.close()

        assert bucket_manager._closed_event is None
        closed_event.set.assert_called_once()

    @pytest.mark.asyncio()
    async def test_start(self, bucket_manager):
        bucket_manager._closed_event = None

        assert bucket_manager._gc_task is None
        bucket_manager.start()
        assert bucket_manager._gc_task is not None

        # cancel created task
        bucket_manager._gc_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bucket_manager._gc_task

    @pytest.mark.asyncio()
    async def test_start_when_already_started(self, bucket_manager):
        bucket_manager._closed_event = object()

        with pytest.raises(errors.ComponentStateConflictError):
            bucket_manager.start()

    @pytest.mark.asyncio()
    async def test_gc_polls_until_closed_event_set(self, event_loop, bucket_manager):
        bucket_manager._closed_event = asyncio.Event()

        # Start the gc and initial assertions
        task = event_loop.create_task(bucket_manager._gc(0.001, float("inf")))
        assert not task.done()

        # [First poll] event not set => shouldn't complete the task
        await asyncio.sleep(0.001)
        assert not task.done()

        # [Second poll] event not set during poll => shouldn't complete the task
        await asyncio.sleep(0.001)
        bucket_manager._closed_event.set()
        assert not task.done()

        # [Third poll] event set => should complete the task
        await asyncio.sleep(0.001)
        assert task.done()

    @pytest.mark.asyncio()
    async def test_gc_makes_gc_pass(self, bucket_manager):
        class ExitError(Exception):
            ...

        bucket_manager._closed_event.wait = mock.Mock()

        with mock.patch.object(buckets.RESTBucketManager, "_purge_stale_buckets") as purge_stale_buckets:
            with mock.patch.object(asyncio, "wait_for", side_effect=[asyncio.TimeoutError, ExitError]):
                with pytest.raises(ExitError):
                    await bucket_manager._gc(0.001, 33)

        purge_stale_buckets.assert_called_with(33)

    @pytest.mark.asyncio()
    async def test_purge_stale_buckets_any_buckets_that_are_empty_but_still_rate_limited_are_kept_alive(
        self, bucket_manager
    ):
        bucket = mock.Mock()
        bucket.is_empty = True
        bucket.is_unknown = False
        bucket.reset_at = time.perf_counter() + 999999999999999999999999999

        bucket_manager._real_hashes_to_buckets["foobar"] = bucket

        bucket_manager._purge_stale_buckets(0)

        assert "foobar" in bucket_manager._real_hashes_to_buckets
        bucket.close.assert_not_called()

    @pytest.mark.asyncio()
    async def test_purge_stale_buckets_any_buckets_that_are_empty_but_not_rate_limited_and_not_expired_are_kept_alive(
        self, bucket_manager
    ):
        bucket = mock.Mock()
        bucket.is_empty = True
        bucket.is_unknown = False
        bucket.reset_at = time.perf_counter()

        bucket_manager._real_hashes_to_buckets["foobar"] = bucket

        bucket_manager._purge_stale_buckets(10)

        assert "foobar" in bucket_manager._real_hashes_to_buckets
        bucket.close.assert_not_called()

    @pytest.mark.asyncio()
    async def test_purge_stale_buckets_any_buckets_that_are_empty_but_not_rate_limited_and_expired_are_closed(
        self, bucket_manager
    ):
        bucket = mock.Mock()
        bucket.is_empty = True
        bucket.is_unknown = False
        bucket.reset_at = time.perf_counter() - 999999999999999999999999999

        bucket_manager._real_hashes_to_buckets["foobar"] = bucket

        bucket_manager._purge_stale_buckets(0)

        assert "foobar" not in bucket_manager._real_hashes_to_buckets
        bucket.close.assert_called_once()

    @pytest.mark.asyncio()
    async def test_purge_stale_buckets_any_buckets_that_are_not_empty_are_kept_alive(self, bucket_manager):
        bucket = mock.Mock()
        bucket.is_empty = False
        bucket.is_unknown = True
        bucket.reset_at = time.perf_counter()

        bucket_manager._real_hashes_to_buckets["foobar"] = bucket

        bucket_manager._purge_stale_buckets(0)

        assert "foobar" in bucket_manager._real_hashes_to_buckets
        bucket.close.assert_not_called()

    @pytest.mark.asyncio()
    async def test_acquire_route_when_not_in_routes_to_real_hashes_makes_new_bucket_using_initial_hash(
        self, bucket_manager
    ):
        route = mock.Mock()

        with mock.patch.object(buckets, "_create_authentication_hash", return_value="auth_hash"):
            with mock.patch.object(
                buckets, "_create_unknown_hash", return_value="UNKNOWN;auth_hash;bobs"
            ) as create_unknown_hash:
                bucket_manager.acquire_bucket(route, "auth")

        assert "UNKNOWN;auth_hash;bobs" in bucket_manager._real_hashes_to_buckets
        assert isinstance(bucket_manager._real_hashes_to_buckets["UNKNOWN;auth_hash;bobs"], buckets.RESTBucket)
        create_unknown_hash.assert_called_once_with(route, "auth_hash")

    @pytest.mark.asyncio()
    async def test_acquire_route_when_not_in_routes_to_real_hashes_doesnt_cache_route(self, bucket_manager):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(
            wraps=lambda initial_hash, auth: f"{initial_hash};{auth};bobs"
        )

        bucket_manager.acquire_bucket(route, "auth")

        assert bucket_manager._routes_to_hashes.get(route.route) is None

    @pytest.mark.asyncio()
    async def test_acquire_route_when_route_cached_already_obtains_hash_from_route_and_bucket_from_hash(
        self, bucket_manager
    ):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(return_value="eat pant;1234")
        bucket = mock.Mock(reset_at=time.perf_counter() + 999999999999999999999999999)
        bucket_manager._routes_to_hashes[route.route] = "eat pant"
        bucket_manager._real_hashes_to_buckets["eat pant;1234"] = bucket

        assert bucket_manager.acquire_bucket(route, "auth") is bucket

    @pytest.mark.asyncio()
    async def test_acquire_route_returns_context_manager(self, bucket_manager):
        route = mock.Mock()

        bucket = mock.Mock(reset_at=time.perf_counter() + 999999999999999999999999999)
        with mock.patch.object(buckets, "RESTBucket", return_value=bucket):
            route.create_real_bucket_hash = mock.Mock(
                wraps=lambda initial_hash, auth: f"{initial_hash};{auth};bobs"
            )

            assert bucket_manager.acquire_bucket(route, "auth") is bucket

    @pytest.mark.asyncio()
    async def test_acquire_unknown_route_returns_context_manager_for_new_bucket(self, bucket_manager):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(return_value="eat pant;bobs")
        bucket = mock.Mock(reset_at=time.perf_counter() + 999999999999999999999999999)
        bucket_manager._routes_to_hashes[route.route] = "eat pant"
        bucket_manager._real_hashes_to_buckets["eat pant;bobs"] = bucket

        assert bucket_manager.acquire_bucket(route, "auth") is bucket

    @pytest.mark.asyncio()
    async def test_update_rate_limits_if_wrong_bucket_hash_reroutes_route(self, bucket_manager):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(
            wraps=lambda initial_hash, auth: f"{initial_hash};{auth};bobs"
        )
        bucket_manager._routes_to_hashes[route.route] = "123"

        with mock.patch.object(buckets, "_create_authentication_hash", return_value="auth_hash"):
            with mock.patch.object(hikari_date, "monotonic", return_value=27):
                with mock.patch.object(buckets, "RESTBucket") as bucket:
                    bucket_manager.update_rate_limits(route, "auth", "blep", 22, 23, 3.56)

        assert bucket_manager._routes_to_hashes[route.route] == "blep"
        assert bucket_manager._real_hashes_to_buckets["blep;auth_hash;bobs"] is bucket.return_value
        bucket.return_value.update_rate_limit.assert_called_once_with(22, 23, 27 + 3.56)

    @pytest.mark.asyncio()
    async def test_update_rate_limits_if_unknown_bucket_hash_reroutes_route(self, bucket_manager):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(
            wraps=lambda initial_hash, auth: f"{initial_hash};{auth};bobs"
        )
        bucket_manager._routes_to_hashes[route.route] = "123"
        bucket = mock.Mock()
        bucket_manager._real_hashes_to_buckets["UNKNOWN;auth_hash;bobs"] = bucket

        stack = contextlib.ExitStack()
        create_authentication_hash = stack.enter_context(
            mock.patch.object(buckets, "_create_authentication_hash", return_value="auth_hash")
        )
        create_unknown_hash = stack.enter_context(
            mock.patch.object(buckets, "_create_unknown_hash", return_value="UNKNOWN;auth_hash;bobs")
        )
        stack.enter_context(mock.patch.object(hikari_date, "monotonic", return_value=27))

        with stack:
            bucket_manager.update_rate_limits(route, "auth", "blep", 22, 23, 3.56)

        assert bucket_manager._routes_to_hashes[route.route] == "blep"
        assert bucket_manager._real_hashes_to_buckets["blep;auth_hash;bobs"] is bucket
        bucket.resolve.assert_called_once_with("blep;auth_hash;bobs")
        bucket.update_rate_limit.assert_called_once_with(22, 23, 27 + 3.56)
        create_unknown_hash.assert_called_once_with(route, "auth_hash")
        create_authentication_hash.assert_called_once_with("auth")

    @pytest.mark.asyncio()
    async def test_update_rate_limits_if_right_bucket_hash_does_nothing_to_hash(self, bucket_manager):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(
            wraps=lambda initial_hash, auth: f"{initial_hash};{auth};bobs"
        )
        bucket_manager._routes_to_hashes[route.route] = "123"
        bucket = mock.Mock(reset_at=time.perf_counter() + 999999999999999999999999999)
        bucket_manager._real_hashes_to_buckets["123;auth_hash;bobs"] = bucket

        with mock.patch.object(buckets, "_create_authentication_hash", return_value="auth_hash"):
            with mock.patch.object(hikari_date, "monotonic", return_value=27):
                bucket_manager.update_rate_limits(route, "auth", "123", 22, 23, 7.65)

        assert bucket_manager._routes_to_hashes[route.route] == "123"
        assert bucket_manager._real_hashes_to_buckets["123;auth_hash;bobs"] is bucket
        bucket.update_rate_limit.assert_called_once_with(22, 23, 27 + 7.65)

    @pytest.mark.asyncio()
    async def test_update_rate_limits_updates_params(self, bucket_manager):
        route = mock.Mock()
        route.create_real_bucket_hash = mock.Mock(
            wraps=lambda initial_hash, auth: f"{initial_hash};{auth};bobs"
        )
        bucket_manager._routes_to_hashes[route.route] = "123"
        bucket = mock.Mock(reset_at=time.perf_counter() + 999999999999999999999999999)
        bucket_manager._real_hashes_to_buckets["123;auth_hash;bobs"] = bucket

        with mock.patch.object(buckets, "_create_authentication_hash", return_value="auth_hash"):
            with mock.patch.object(hikari_date, "monotonic", return_value=27):
                bucket_manager.update_rate_limits(route, "auth", "123", 22, 23, 5.32)
                bucket.update_rate_limit.assert_called_once_with(22, 23, 27 + 5.32)

    @pytest.mark.parametrize(("closed_event", "is_alive"), [(None, False), ("some", True)])
    def test_is_alive(self, bucket_manager, closed_event, is_alive):
        bucket_manager._closed_event = closed_event
        assert bucket_manager.is_alive is is_alive
