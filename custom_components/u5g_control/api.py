"""Async SSH client for Ubiquiti U5G-class modems."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import asyncssh

from .const import MODEM_COMMAND_TIMEOUT
from .models import ModemSnapshot, RadioPreference


class U5GApiError(Exception):
    """Base API error."""


class U5GAuthenticationError(U5GApiError):
    """Authentication failed."""


class U5GHostKeyError(U5GApiError):
    """The modem host key no longer matches."""


@dataclass(slots=True)
class ProbeResult:
    """Information collected while pairing a modem."""

    host_key: str
    info: dict[str, str]
    snapshot: ModemSnapshot


def _extract_json(output: str) -> dict[str, Any]:
    """Extract one JSON object from command output."""
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise U5GApiError(f"No JSON object in modem response: {output[:200]!r}")
    try:
        value = json.loads(output[start : end + 1])
    except json.JSONDecodeError as err:
        raise U5GApiError(f"Invalid JSON from modem: {err}") from err
    if not isinstance(value, dict):
        raise U5GApiError("Unexpected non-object response from modem")
    return value


class U5GClient:
    """Maintain a pinned SSH connection to one modem."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.host_key = host_key
        self._connection: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()

    def _known_hosts(self) -> bytes | None:
        if not self.host_key:
            return None
        pattern = self.host if self.port == 22 else f"[{self.host}]:{self.port}"
        return f"{pattern} {self.host_key.strip()}\n".encode()

    async def _connect(self, *, unverified: bool = False) -> asyncssh.SSHClientConnection:
        try:
            return await asyncio.wait_for(
                asyncssh.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    known_hosts=None if unverified else self._known_hosts(),
                    client_keys=None,
                ),
                timeout=MODEM_COMMAND_TIMEOUT,
            )
        except asyncssh.PermissionDenied as err:
            raise U5GAuthenticationError("SSH authentication failed") from err
        except asyncssh.HostKeyNotVerifiable as err:
            raise U5GHostKeyError("SSH host key changed") from err
        except (asyncssh.Error, OSError, TimeoutError) as err:
            raise U5GApiError(f"SSH connection failed: {err}") from err

    async def async_close(self) -> None:
        """Close the cached connection."""
        if self._connection:
            self._connection.close()
            await self._connection.wait_closed()
            self._connection = None

    async def _ensure_connection(self) -> asyncssh.SSHClientConnection:
        if self._connection is None or self._connection.is_closed():
            self._connection = await self._connect()
        return self._connection

    async def async_run(self, command: str, stdin: str | None = None) -> str:
        """Run one fixed command, reconnecting once after transport failure."""
        async with self._lock:
            for attempt in range(2):
                connection = await self._ensure_connection()
                try:
                    result = await asyncio.wait_for(
                        connection.run(command, input=stdin, check=False),
                        timeout=MODEM_COMMAND_TIMEOUT,
                    )
                    if result.exit_status not in (0, None):
                        raise U5GApiError(
                            f"Command failed ({result.exit_status}): {result.stderr.strip()}"
                        )
                    return str(result.stdout)
                except (asyncssh.Error, OSError, TimeoutError) as err:
                    await self.async_close()
                    if attempt:
                        raise U5GApiError(f"SSH command failed: {err}") from err
            raise U5GApiError("SSH command failed")

    async def async_uiwwand(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the local uiwwand control API."""
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        output = await self.async_run("uiwwand-ctl", json.dumps(payload, separators=(",", ":")) + "\n")
        response = _extract_json(output)
        if response.get("error"):
            raise U5GApiError(f"uiwwand {method} failed: {response['error']}")
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise U5GApiError(f"Unexpected uiwwand {method} result")
        return result

    async def async_get_info(self) -> dict[str, str]:
        """Read stable hub identity with conservative fallbacks."""
        commands = {
            "hostname": "cat /proc/sys/kernel/hostname 2>/dev/null || true",
            "mac": "cat /sys/class/net/br0/address 2>/dev/null || cat /sys/class/net/eth0/address 2>/dev/null || true",
            "firmware": "cat /etc/version 2>/dev/null || true",
            "board": "cat /etc/board.info 2>/dev/null || true",
        }
        result: dict[str, str] = {}
        for key, command in commands.items():
            try:
                result[key] = (await self.async_run(command)).strip()
            except U5GApiError:
                # Identity metadata varies between U5G firmware families. A
                # missing optional file or utility must not make setup fail.
                result[key] = ""
        result["model"] = "Ubiquiti Cellular Modem"
        board_lower = result.get("board", "").lower()
        if "u5g" in board_lower:
            result["model"] = next(
                (line.split("=", 1)[-1].strip().strip('"') for line in result["board"].splitlines() if "model" in line.lower()),
                result["model"],
            )
        return result

    async def async_get_snapshot(self, include_info: bool = False) -> ModemSnapshot:
        """Read SIM, preferences, status, and optionally hub identity."""
        sim_state = await self.async_uiwwand("get-sim-state")
        preference_data = await self.async_uiwwand("get-radio-pref")
        radio_status = await self.async_uiwwand("get-radio-status")
        info = await self.async_get_info() if include_info else {}
        return ModemSnapshot(
            sim_state=sim_state,
            radio_preference=RadioPreference.from_uiwwand(preference_data),
            radio_status=radio_status,
            modem_info=info,
        )

    async def async_set_preference(self, iccid: str, preference: RadioPreference) -> None:
        """Atomically set a complete radio preference."""
        await self.async_uiwwand("set-radio-pref", preference.to_uiwwand(iccid))

    async def async_probe(self) -> ProbeResult:
        """Pair using trust-on-first-use and return the key to pin afterward."""
        await self.async_close()
        connection = await self._connect(unverified=True)
        try:
            key = connection.get_server_host_key()
            host_key = key.export_public_key().decode().strip()
            self.host_key = host_key
            self._connection = connection
            snapshot = await self.async_get_snapshot(include_info=True)
            return ProbeResult(host_key, snapshot.modem_info, snapshot)
        except BaseException:
            await self.async_close()
            raise

