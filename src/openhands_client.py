"""REST client for OpenHands Agent Server.

Compensates for missing SDK by polling events and using REST file operations.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable, Optional

import httpx
from rich.console import Console

from .constants import DEFAULT_LLM_BASE_URL, DEFAULT_OPENHANDS_LLM_MODEL

console = Console()


class OpenHandsError(Exception):
    """Raised when OpenHands Agent Server requests fail."""
    pass


# Terminal statuses for conversations
TERMINAL_STATUSES = frozenset(
    {"error", "stopped", "completed", "cancelled", "finished", "stuck"}
)


class OpenHandsClient:
    """Manage the OpenHands Agent Server lifecycle and task submission."""

    def __init__(
        self,
        base_url: str = "http://localhost:3005",
        compose_file: Optional[str] = None,
        timeout: int = 600,
        model: str = DEFAULT_OPENHANDS_LLM_MODEL,
        base_llm_url: str = DEFAULT_LLM_BASE_URL,
        auth_header: Optional[str] = None,
        use_existing_server: bool = False,
    ):
        self.base_url = base_url
        self.compose_file = compose_file
        self.timeout = timeout
        self.model = model
        # vLLM serves at /v1/, litellm appends /chat/completions
        self.base_llm_url = base_llm_url.rstrip("/") + "/v1"
        # Wire to an existing OpenHands Agent Server (e.g. openhands-canvas:43006)
        # instead of spawning SuperApp's own compose container.
        self.use_existing_server = use_existing_server
        headers: dict[str, str] = {}
        if auth_header:
            headers["Authorization"] = (
                auth_header
                if auth_header.lower().startswith("bearer")
                else f"Bearer {auth_header}"
            )
        self._client = httpx.Client(base_url=self.base_url, timeout=60.0, headers=headers)

    # --- Lifecycle ---

    def start_server(self) -> None:
        """Start the OpenHands container via Docker Compose.

        No-op when use_existing_server=True (we reuse an already-running
        server, e.g. openhands-canvas) — just wait for it to be ready.
        """
        if self.use_existing_server:
            console.print(f"[blue]Reusing existing OpenHands server at {self.base_url}[/blue]")
            self.wait_for_ready()
            return
        cmd = ["docker", "compose"]
        if self.compose_file:
            cmd.extend(["-f", self.compose_file])
        cmd.extend(["up", "-d"])
        console.print(f"[blue]Starting OpenHands: {' '.join(cmd)}[/blue]")
        subprocess.run(cmd, check=True)
        self.wait_for_ready()

    def stop_server(self) -> None:
        """Stop the OpenHands container.

        No-op when reusing an existing server — we did not start it.
        """
        if self.use_existing_server:
            console.print(f"[blue]Leaving existing OpenHands server running ({self.base_url})[/blue]")
            return
        cmd = ["docker", "compose"]
        if self.compose_file:
            cmd.extend(["-f", self.compose_file])
        cmd.append("down")
        console.print("[blue]Stopping OpenHands...[/blue]")
        subprocess.run(cmd, check=False)

    def wait_for_ready(self, retries: int = 60, interval: float = 2.0) -> None:
        """Wait until /health and /api/conversations are ready.

        Catches all exceptions — container startup can produce various
        socket-level errors (ConnectError, RemoteProtocolError, ReadError).
        """
        for i in range(retries):
            health_ok = False
            try:
                resp = self._client.get("/health", timeout=5.0)
                if resp.status_code == 200:
                    health_ok = True
            except httpx.RequestError:
                pass

            if health_ok:
                try:
                    conv_resp = self._client.get("/api/conversations", timeout=5.0)
                    # 200/422 = ready. 401/403 = reachable but auth-gated
                    # (e.g. openhands-canvas); treat as ready so a valid
                    # auth header is exercised on the first real request.
                    if conv_resp.status_code in (200, 422, 401, 403):
                        return
                except httpx.RequestError:
                    pass

            if i < retries - 1:
                time.sleep(interval)
        raise OpenHandsError(
            f"OpenHands server did not become ready after {retries} attempts"
        )

    # --- Conversations ---

    def create_conversation(self, goal: str, workspace: str, n_retries: int = 3) -> str:
        """Create a new conversation (task) and return the conversation ID.

        Payload must match the SDK's StartConversationRequest model exactly.
        Key requirements (from SDK source):
        - agent.kind must be "Agent" for discriminated union dispatch
        - agent.tools must be a list of tool names the agent can call
        - initial_message must be a valid SendMessageRequest with role + typed content
        - run=True triggers the agent loop immediately after creation
        """
        payload = {
            "workspace": {"working_dir": workspace, "kind": "LocalWorkspace"},
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": goal}],
                "run": True,
            },
            "agent": {
                "kind": "Agent",
                "llm": {
                    "model": self.model,
                    "base_url": self.base_llm_url,
                    "api_key": "dummy",
                },
                # OpenHands v1.30.0 tool names (from /api/tools/).
                # Covers: shell, file I/O, glob/grep, directory listing.
                "tools": [
                    {"name": "terminal"},
                    {"name": "file_editor"},
                    {"name": "write_file"},
                    {"name": "read_file"},
                    {"name": "edit"},
                    {"name": "glob"},
                    {"name": "grep"},
                    {"name": "list_directory"},
                ],
            },
            "confirmation_policy": {"kind": "NeverConfirm"},
        }
        for attempt in range(n_retries):
            try:
                resp = self._client.post(
                    "/api/conversations", json=payload, timeout=30.0
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return data.get("id", data.get("conversation_id", ""))
                if resp.status_code in (401, 403):
                    raise OpenHandsError(
                        f"Auth rejected creating conversation ({resp.status_code}). "
                        f"Check the OpenHands auth header / API key for {self.base_url}."
                    )
                raise OpenHandsError(
                    f"Failed to create conversation: {resp.status_code} {resp.text}"
                )
            except httpx.ConnectError:
                if attempt < n_retries - 1:
                    time.sleep(2)
                    continue
                raise OpenHandsError(
                    f"Failed to connect after {n_retries} attempts"
                )
        raise OpenHandsError("Unexpected code path")

    # --- Events (compensates for missing WebSocket/SDK streaming) ---

    def _get_events(
        self, conv_id: str, page_id: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        """Fetch events via REST /events/search endpoint."""
        params = {"limit": limit, "sort_order": "TIMESTAMP_DESC"}
        if page_id:
            params["page_id"] = page_id
        try:
            resp = self._client.get(
                f"/api/conversations/{conv_id}/events/search",
                params=params,
                timeout=15.0,
            )
            return resp.json().get("items", [])
        except httpx.HTTPError:
            return []

    def _get_execution_status(self, conv_id: str) -> str:
        """Get current execution_status of a conversation."""
        try:
            resp = self._client.get(f"/api/conversations/{conv_id}", timeout=15.0)
            return resp.json().get("execution_status", "unknown")
        except httpx.HTTPError:
            return "unknown"

    def stream_events(
        self,
        conv_id: str,
        on_event: Optional[Callable[[dict], None]] = None,
        poll_interval: float = 2.0,
    ) -> list[dict]:
        """Poll events until conversation completes, calling on_event for each.

        Uses REST event polling as a drop-in for SDK event streaming.
        Returns all collected events.
        """
        deadline = time.time() + self.timeout
        all_events: list[dict] = []
        last_id: Optional[str] = None
        seen_ids: set[str] = set()

        while time.time() < deadline:
            events = self._get_events(conv_id, last_id)

            for evt in events:
                eid = evt.get("id")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    all_events.append(evt)
                    if on_event:
                        on_event(evt)

                if eid:
                    last_id = eid

            status = self._get_execution_status(conv_id)
            if status in TERMINAL_STATUSES:
                return all_events

            time.sleep(poll_interval)

        raise OpenHandsError(
            f"Conversation {conv_id} timed out after {self.timeout}s"
        )

    def poll_conversation_with_events(
        self,
        conv_id: str,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Stream events via REST polling until conversation finishes."""
        self.stream_events(conv_id, on_event=on_event)
        return self._client.get(f"/api/conversations/{conv_id}", timeout=15.0).json()

    def close(self) -> None:
        self._client.close()