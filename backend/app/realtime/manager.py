"""In-process authenticated WebSocket connection and presence management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid4


class WebSocketTransport(Protocol):
    """Small transport surface required by the connection manager."""

    async def send_text(self, data: str) -> None:
        """Send one already-serialized protocol event."""

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the transport."""


class ConnectionLimitReachedError(RuntimeError):
    """Raised when one user reaches the per-room socket limit."""


@dataclass(slots=True)
class ManagedConnection:
    """An authenticated socket; no durable room or quiz state is stored here."""

    connection_id: UUID
    room_id: UUID
    user_id: UUID
    socket: WebSocketTransport
    protocol_version: int = 1
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
class ConnectionManager:
    """Own sockets in one process and derive ephemeral online presence."""

    def __init__(self, *, max_connections_per_user: int = 3) -> None:
        if max_connections_per_user < 1:
            raise ValueError("max_connections_per_user must be positive")
        self._max_connections_per_user = max_connections_per_user
        self._rooms: dict[UUID, dict[UUID, dict[UUID, ManagedConnection]]] = {}
        self._connections: dict[UUID, ManagedConnection] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        room_id: UUID,
        user_id: UUID,
        socket: WebSocketTransport,
        protocol_version: int = 1,
    ) -> ManagedConnection:
        """Register a socket after application authentication and membership."""

        connection = ManagedConnection(
            connection_id=uuid4(),
            room_id=room_id,
            user_id=user_id,
            socket=socket,
            protocol_version=protocol_version,
        )
        async with self._lock:
            room_connections = self._rooms.setdefault(room_id, {})
            user_connections = room_connections.setdefault(user_id, {})
            if len(user_connections) >= self._max_connections_per_user:
                if not user_connections:
                    room_connections.pop(user_id, None)
                if not room_connections:
                    self._rooms.pop(room_id, None)
                raise ConnectionLimitReachedError
            user_connections[connection.connection_id] = connection
            self._connections[connection.connection_id] = connection
        return connection

    def get_protocol_version(self, connection_id: UUID) -> int:
        conn = self._connections.get(connection_id)
        return conn.protocol_version if conn else 1

    def list_room_connections(self, room_id: UUID) -> list[ManagedConnection]:
        room = self._rooms.get(room_id, {})
        conns: list[ManagedConnection] = []
        for user_dict in room.values():
            conns.extend(user_dict.values())
        return conns

    async def unregister(self, connection_id: UUID) -> ManagedConnection | None:
        """Remove a socket and return its metadata, if it was still registered."""

        connection, _ = await self.unregister_with_presence(connection_id)
        return connection

    async def unregister_with_presence(
        self,
        connection_id: UUID,
    ) -> tuple[ManagedConnection | None, bool]:
        """Remove a socket and report whether its user became offline."""

        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None:
                return None, False
            room_connections = self._rooms.get(connection.room_id)
            if room_connections is None:
                return connection, True
            user_connections = room_connections.get(connection.user_id)
            became_offline = user_connections is not None and len(user_connections) == 1
            if user_connections is not None:
                user_connections.pop(connection_id, None)
                if not user_connections:
                    room_connections.pop(connection.user_id, None)
            if not room_connections:
                self._rooms.pop(connection.room_id, None)
            return connection, became_offline

    async def get(self, connection_id: UUID) -> ManagedConnection | None:
        async with self._lock:
            return self._connections.get(connection_id)

    async def online_users(self, room_id: UUID) -> tuple[UUID, ...]:
        """Return a stable copy of users with at least one active socket."""

        async with self._lock:
            room_connections = self._rooms.get(room_id, {})
            return tuple(room_connections)

    async def user_is_online(self, room_id: UUID, user_id: UUID) -> bool:
        async with self._lock:
            return bool(self._rooms.get(room_id, {}).get(user_id))

    async def connection_count(self, room_id: UUID, user_id: UUID) -> int:
        async with self._lock:
            return len(self._rooms.get(room_id, {}).get(user_id, {}))

    async def send_to_connection(self, connection_id: UUID, message: str) -> bool:
        connection = await self.get(connection_id)
        if connection is None:
            return False
        return await self._send_one(connection, message)

    async def send_to_user(
        self,
        room_id: UUID,
        user_id: UUID,
        message: str,
    ) -> None:
        connections = await self._copy_user_connections(room_id, user_id)
        await asyncio.gather(
            *(self._send_one(connection, message) for connection in connections)
        )

    async def broadcast_room(self, room_id: UUID, message: str) -> None:
        """Broadcast without holding the map lock during network I/O."""

        connections = await self._copy_room_connections(room_id)
        await asyncio.gather(
            *(self._send_one(connection, message) for connection in connections)
        )

    async def close_connection(
        self,
        connection_id: UUID,
        *,
        code: int,
        reason: str,
    ) -> bool:
        connection = await self.get(connection_id)
        if connection is None:
            return False
        try:
            async with connection.send_lock:
                await connection.socket.close(code=code, reason=reason)
        except Exception:
            pass
        await self.unregister(connection_id)
        return True

    async def close_user_in_room(
        self,
        room_id: UUID,
        user_id: UUID,
        *,
        code: int,
        reason: str,
        final_message: str | None = None,
    ) -> int:
        """Detach and close every socket for one room member."""

        async with self._lock:
            room_connections = self._rooms.get(room_id)
            if room_connections is None:
                connections: tuple[ManagedConnection, ...] = ()
            else:
                connections = tuple(room_connections.pop(user_id, {}).values())
                for connection in connections:
                    self._connections.pop(connection.connection_id, None)
                if not room_connections:
                    self._rooms.pop(room_id, None)
        await asyncio.gather(
            *(
                self._notify_and_close_transport(
                    connection,
                    code,
                    reason,
                    final_message,
                )
                for connection in connections
            )
        )
        return len(connections)

    async def close_user(
        self,
        user_id: UUID,
        *,
        code: int,
        reason: str,
        final_message: str | None = None,
    ) -> int:
        """Detach and close every socket for one user across all rooms."""

        async with self._lock:
            connections_list: list[ManagedConnection] = []
            for room_connections in self._rooms.values():
                connections_list.extend(
                    room_connections.get(user_id, {}).values()
                )
            connections = tuple(connections_list)
            for connection in connections:
                self._connections.pop(connection.connection_id, None)
            for room_id in tuple(self._rooms):
                room_connections = self._rooms[room_id]
                room_connections.pop(user_id, None)
                if not room_connections:
                    self._rooms.pop(room_id, None)
        await asyncio.gather(
            *(
                self._notify_and_close_transport(
                    connection,
                    code,
                    reason,
                    final_message,
                )
                for connection in connections
            )
        )
        return len(connections)

    async def close_room(
        self,
        room_id: UUID,
        *,
        code: int,
        reason: str,
        final_message: str | None = None,
    ) -> int:
        """Detach and close every socket currently registered to a room."""

        async with self._lock:
            room_connections = self._rooms.pop(room_id, {})
            connections = tuple(
                connection
                for user_connections in room_connections.values()
                for connection in user_connections.values()
            )
            for connection in connections:
                self._connections.pop(connection.connection_id, None)
        await asyncio.gather(
            *(
                self._notify_and_close_transport(
                    connection,
                    code,
                    reason,
                    final_message,
                )
                for connection in connections
            )
        )
        return len(connections)

    async def shutdown(self, *, code: int = 1001, reason: str = "server shutdown") -> None:
        """Close and forget every process-local socket."""

        async with self._lock:
            connections = tuple(self._connections.values())
            self._connections.clear()
            self._rooms.clear()
        await asyncio.gather(
            *(self._close_transport(connection, code, reason) for connection in connections)
        )

    async def _copy_user_connections(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> tuple[ManagedConnection, ...]:
        async with self._lock:
            return tuple(self._rooms.get(room_id, {}).get(user_id, {}).values())

    async def _copy_room_connections(
        self,
        room_id: UUID,
    ) -> tuple[ManagedConnection, ...]:
        async with self._lock:
            room_connections = self._rooms.get(room_id, {})
            return tuple(
                connection
                for user_connections in room_connections.values()
                for connection in user_connections.values()
            )

    async def _send_one(self, connection: ManagedConnection, message: str) -> bool:
        try:
            async with connection.send_lock:
                await connection.socket.send_text(message)
        except Exception:
            await self.unregister(connection.connection_id)
            return False
        return True

    @staticmethod
    async def _close_transport(
        connection: ManagedConnection,
        code: int,
        reason: str,
    ) -> None:
        try:
            async with connection.send_lock:
                await connection.socket.close(code=code, reason=reason)
        except Exception:
            pass

    @staticmethod
    async def _notify_and_close_transport(
        connection: ManagedConnection,
        code: int,
        reason: str,
        final_message: str | None,
    ) -> None:
        async with connection.send_lock:
            if final_message is not None:
                try:
                    await connection.socket.send_text(final_message)
                except Exception:
                    pass
            try:
                await connection.socket.close(code=code, reason=reason)
            except Exception:
                pass
