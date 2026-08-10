"""SessionState + block-patch application (SPEC.md §5 SessionState, §13.E ids).

Single session, single process, in-memory only -- no DB, no persistence
(beyond the optional Convex mirror, which is out of this module's concern).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from server import config

# Slug (SPEC.md §14.B): two short lowercase words + 2 digits, e.g.
# "amber-fox-42". Minted at session creation and on every reset. Inline
# wordlist -- no external resource, deliberately small/hackathon-sized.
_SLUG_WORDS = [
    "amber", "birch", "cedar", "coral", "delta", "ember", "fable", "flint",
    "grove", "haze", "indigo", "ivory", "jade", "koa", "lumen", "maple",
    "nova", "onyx", "opal", "pearl", "quartz", "raven", "reed", "sable",
    "slate", "storm", "teal", "umber", "violet", "willow", "zephyr", "fox",
    "wolf", "hawk", "owl", "bear", "lynx", "crow", "deer", "otter", "heron",
    "falcon", "wren", "finch", "moth", "elk", "seal", "pine", "moss",
]


def _mint_slug() -> str:
    a, b = random.sample(_SLUG_WORDS, 2)
    n = random.randint(10, 99)
    return f"{a}-{b}-{n}"


@dataclass
class Objection:
    id: str
    kind: str
    message: str
    refs: list[str]
    status: str  # "spoken" | "dismissed" | "answered"


def objection_to_dict(o: Objection) -> dict:
    """Plain-dict shape shared by session.snapshot(), the Convex mirror, and
    the MCP layer's `pending_objection` field -- one place defines it."""
    return {"id": o.id, "kind": o.kind, "message": o.message, "refs": o.refs, "status": o.status}


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

    # Share-flow capability token (SPEC.md §14.B): minted here and on every
    # reset. Included in `hello` and GET /state; audience URLs are
    # AUDIENCE_BASE_URL + slug.
    slug: str = field(default_factory=_mint_slug)

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


def get_last_block_text(state: SessionState) -> Optional[str]:
    """The most recent paragraph's text, or None if no blocks exist yet.

    Shared by the WS "draft, read that back" path and the MCP
    draft_read_back tool -- one place decides what "the last block" means.
    """
    if not state.block_order:
        return None
    return state.blocks[state.block_order[-1]]


def snapshot(state: SessionState) -> dict:
    """Document snapshot (SPEC.md §14.A): {title, blocks:[{id,text}],
    objections:[...], slug, has_openai_key}. Backs GET /state and the MCP
    draft_get_document tool.
    """
    return {
        "title": state.title,
        "blocks": [{"id": bid, "text": state.blocks[bid]} for bid in state.block_order],
        "objections": [objection_to_dict(o) for o in state.objections],
        "slug": state.slug,
        "has_openai_key": config.has_openai_key(),
    }


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
    state.slug = _mint_slug()


def load_snapshot(state: SessionState, row: dict) -> None:
    """Resume a stored draft (MCP draft_open, SPEC.md §14.B): replace the
    live session with the stored row's content and ADOPT ITS SLUG, so every
    subsequent edit mirrors into the same Convex row.

    The transcript is not stored in Convex, so it restarts empty -- from here
    the Writer/Critic work from the loaded blocks plus new utterances.
    reset_state() first: bumps generation so in-flight writer/critic runs
    from the previous session can never leak into the resumed one.
    """
    reset_state(state)
    state.slug = (row.get("slug") or state.slug).strip() or state.slug
    state.title = (row.get("title") or "").strip()

    for b in row.get("blocks") or []:
        bid = b.get("id") if isinstance(b, dict) else None
        text = (b.get("text") if isinstance(b, dict) else str(b)) or ""
        if not bid:
            bid = state.next_block_id()
        state.note_block_id(bid)
        state.blocks[bid] = text
        state.block_order.append(bid)

    # Loaded objections keep the Critic's dedup memory across the resume.
    # Anything still 'spoken' in the stored row is stale -- mark answered.
    for o in row.get("objections") or []:
        if not isinstance(o, dict):
            continue
        status = o.get("status") or "answered"
        if status == "spoken":
            status = "answered"
        oid = o.get("id") or state.next_objection_id()
        state.objections.append(
            Objection(
                id=oid,
                kind=o.get("kind") or "note",
                message=o.get("message") or "",
                refs=list(o.get("refs") or []),
                status=status,
            )
        )
        seq = oid[1:]
        if oid[:1] == "o" and seq.isdigit() and int(seq) > state._objection_seq:
            state._objection_seq = int(seq)
