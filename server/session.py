"""SessionState + block-patch application (SPEC.md §5 SessionState, §13.E ids).

Single session, single process, in-memory only -- no DB, no persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Objection:
    id: str
    kind: str
    message: str
    refs: list[str]
    status: str  # "spoken" | "dismissed" | "answered"


@dataclass
class SessionState:
    transcript: list[dict] = field(default_factory=list)  # [{"text":..., "ts":...}]
    block_order: list[str] = field(default_factory=list)  # ordering of block ids
    blocks: dict[str, str] = field(default_factory=dict)  # id -> text
    title: str = ""
    objections: list[Objection] = field(default_factory=list)
    last_interrupt_ts: Optional[float] = None
    utterances_since_interrupt: int = 0
    writer_running: bool = False
    pending_utterances: list[dict] = field(default_factory=list)

    # Bumped on reset. In-flight writer/critic tasks capture this at the
    # start of a pass and check it again before broadcasting, so a stale
    # LLM response from before a reset can never resurrect content after it.
    generation: int = 0

    _block_seq: int = field(default=0, repr=False)
    _objection_seq: int = field(default=0, repr=False)
    _readback_seq: int = field(default=0, repr=False)

    def next_block_id(self) -> str:
        self._block_seq += 1
        return f"b{self._block_seq}"

    def peek_next_block_id(self) -> str:
        """Hint only -- the Writer model assigns its own block ids."""
        return f"b{self._block_seq + 1}"

    def note_block_id(self, block_id: str) -> None:
        """Keep the id sequence hint in sync with model-chosen ids."""
        if block_id and block_id[0] in ("b", "B") and block_id[1:].isdigit():
            num = int(block_id[1:])
            if num > self._block_seq:
                self._block_seq = num

    def next_objection_id(self) -> str:
        self._objection_seq += 1
        return f"o{self._objection_seq}"

    def next_readback_id(self) -> str:
        self._readback_seq += 1
        return f"r{self._readback_seq}"


def _insert_block(state: SessionState, block_id: str, text: str, after: Optional[str]) -> None:
    if block_id in state.block_order:
        state.block_order.remove(block_id)
    state.blocks[block_id] = text
    if after and after in state.block_order:
        idx = state.block_order.index(after) + 1
        state.block_order.insert(idx, block_id)
    else:
        state.block_order.append(block_id)


def apply_patches(state: SessionState, patches: list[dict]) -> dict[str, str]:
    """Apply Writer patches (SPEC.md §5) to state.blocks / state.block_order.

    Returns {block_id: status} for blocks touched in THIS pass ("new" or
    "revised"). Deleted blocks are removed outright and are absent from the
    returned dict. Callers combine this with the full block_order to build
    the doc_update per-block status list (untouched blocks -> "unchanged").
    """
    touched: dict[str, str] = {}
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        op = patch.get("op")
        block_id = patch.get("id")
        text = patch.get("text", "")
        after = patch.get("after")

        if op == "add":
            if not block_id:
                block_id = state.next_block_id()
            else:
                state.note_block_id(block_id)
            _insert_block(state, block_id, text, after)
            touched[block_id] = "new"

        elif op == "replace":
            if block_id and block_id in state.blocks:
                state.blocks[block_id] = text
                touched[block_id] = "revised"
            else:
                # Defensive: model referenced an unknown id on a replace.
                # Treat as an add so the content isn't silently dropped.
                if not block_id:
                    block_id = state.next_block_id()
                else:
                    state.note_block_id(block_id)
                _insert_block(state, block_id, text, after)
                touched[block_id] = "new"

        elif op == "delete":
            if block_id and block_id in state.blocks:
                del state.blocks[block_id]
                if block_id in state.block_order:
                    state.block_order.remove(block_id)
                touched.pop(block_id, None)
        # unknown op: ignore (caller logs the raw patch count either way)

    return touched


def doc_update_blocks(state: SessionState, touched: dict[str, str]) -> list[dict]:
    """Full ordered block list with per-update delta statuses (§13.E)."""
    return [
        {"id": bid, "text": state.blocks[bid], "status": touched.get(bid, "unchanged")}
        for bid in state.block_order
    ]


def render_markdown(state: SessionState) -> str:
    """Plain (unpolished) markdown rendering of the current state.

    Used for `export` (never polished, per §13.E) and as the Writer's
    fallback for `finish` when the polish pass fails/is unavailable.
    """
    title = state.title or "Untitled"
    lines = [f"# {title}", ""]
    for bid in state.block_order:
        text = state.blocks.get(bid, "")
        if text:
            lines.append(text)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def reset_state(state: SessionState) -> None:
    """Reset a SessionState in place back to a fresh session (§5 new/start over).

    Mutates in place (rather than swapping the object) so every module that
    already holds a reference to `state` sees the reset immediately, and so
    the `generation` bump is visible to in-flight writer/critic tasks that
    captured an earlier generation.
    """
    state.transcript.clear()
    state.block_order.clear()
    state.blocks.clear()
    state.title = ""
    state.objections.clear()
    state.last_interrupt_ts = None
    state.utterances_since_interrupt = 0
    state.writer_running = False
    state.pending_utterances.clear()
    state.generation += 1
    state._block_seq = 0
    state._objection_seq = 0
    state._readback_seq = 0
