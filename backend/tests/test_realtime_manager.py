import asyncio
from dataclasses import dataclass, field
from uuid import UUID

import pytest

from app.realtime.manager import ConnectionLimitReachedError, ConnectionManager


ROOM_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ONE = UUID("22222222-2222-4222-8222-222222222222")
USER_TWO = UUID("33333333-3333-4333-8333-333333333333")


@dataclass
class FakeSocket:
    messages: list[str] = field(default_factory=list)
    closed: list[tuple[int, str]] = field(default_factory=list)
    fail_sends: bool = False

    async def send_text(self, data: str) -> None:
        if self.fail_sends:
            raise RuntimeError("socket failed")
        self.messages.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


def test_connection_manager_tracks_presence_and_socket_cap() -> None:
    async def scenario() -> None:
        manager = ConnectionManager(max_connections_per_user=3)
        sockets = [FakeSocket() for _ in range(4)]
        first = await manager.register(ROOM_ID, USER_ONE, sockets[0])
        second = await manager.register(ROOM_ID, USER_ONE, sockets[1])
        third = await manager.register(ROOM_ID, USER_ONE, sockets[2])

        assert await manager.user_is_online(ROOM_ID, USER_ONE)
        assert await manager.connection_count(ROOM_ID, USER_ONE) == 3
        with pytest.raises(ConnectionLimitReachedError):
            await manager.register(ROOM_ID, USER_ONE, sockets[3])

        await manager.unregister(first.connection_id)
        assert await manager.user_is_online(ROOM_ID, USER_ONE)
        await manager.unregister(second.connection_id)
        assert await manager.user_is_online(ROOM_ID, USER_ONE)
        await manager.unregister(third.connection_id)
        assert not await manager.user_is_online(ROOM_ID, USER_ONE)

    asyncio.run(scenario())


def test_targeted_broadcast_failed_send_and_shutdown_cleanup() -> None:
    async def scenario() -> None:
        manager = ConnectionManager()
        user_one_socket = FakeSocket()
        user_two_socket = FakeSocket()
        failed_socket = FakeSocket(fail_sends=True)
        one = await manager.register(ROOM_ID, USER_ONE, user_one_socket)
        two = await manager.register(ROOM_ID, USER_TWO, user_two_socket)
        failed = await manager.register(ROOM_ID, USER_TWO, failed_socket)

        await manager.send_to_user(ROOM_ID, USER_ONE, "targeted")
        assert user_one_socket.messages == ["targeted"]
        assert user_two_socket.messages == []
        await manager.broadcast_room(ROOM_ID, "room")
        assert user_one_socket.messages == ["targeted", "room"]
        assert user_two_socket.messages == ["room"]
        assert await manager.get(failed.connection_id) is None

        await manager.shutdown()
        assert await manager.get(one.connection_id) is None
        assert await manager.get(two.connection_id) is None
        assert user_one_socket.closed
        assert user_two_socket.closed

    asyncio.run(scenario())


def test_lifecycle_closure_detaches_user_and_room_connections_before_io() -> None:
    async def scenario() -> None:
        manager = ConnectionManager()
        departing_sockets = [FakeSocket(), FakeSocket()]
        remaining_socket = FakeSocket()
        departing = [
            await manager.register(ROOM_ID, USER_ONE, socket)
            for socket in departing_sockets
        ]
        remaining = await manager.register(ROOM_ID, USER_TWO, remaining_socket)

        closed_user_count = await manager.close_user_in_room(
            ROOM_ID,
            USER_ONE,
            code=4403,
            reason="room_left",
            final_message="left-event",
        )

        assert closed_user_count == 2
        assert await manager.online_users(ROOM_ID) == (USER_TWO,)
        departing_records = await asyncio.gather(
            *(manager.get(connection.connection_id) for connection in departing)
        )
        assert all(record is None for record in departing_records)
        assert all(socket.messages == ["left-event"] for socket in departing_sockets)
        assert all(socket.closed == [(4403, "room_left")] for socket in departing_sockets)

        closed_room_count = await manager.close_room(
            ROOM_ID,
            code=4404,
            reason="room_closed",
            final_message="closed-event",
        )

        assert closed_room_count == 1
        assert await manager.online_users(ROOM_ID) == ()
        assert await manager.get(remaining.connection_id) is None
        assert remaining_socket.messages == ["closed-event"]
        assert remaining_socket.closed == [(4404, "room_closed")]

        failed_notification_socket = FakeSocket(fail_sends=True)
        await manager.register(ROOM_ID, USER_ONE, failed_notification_socket)
        assert await manager.close_user_in_room(
            ROOM_ID,
            USER_ONE,
            code=4403,
            reason="room_left",
            final_message="left-event",
        ) == 1
        assert failed_notification_socket.closed == [(4403, "room_left")]
        assert await manager.online_users(ROOM_ID) == ()

    asyncio.run(scenario())
