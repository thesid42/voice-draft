// convex/schema.ts — SPEC.md §14.B.
//
// Codegen-free: defineSchema/defineTable never required generated code (only
// the `api` object, `Doc<>`/`Id<>` types do, from `npx convex dev`). This
// project's functions (sessions.ts) use queryGeneric/mutationGeneric instead
// of the generated `query`/`mutation`, and the audience page (web/watch.html
// -> AudienceView.jsx) uses `anyApi` instead of a generated `api` object, so
// nothing here ever imports from the Convex-generated helper module.
import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  // One row per Draft session, keyed by the human-readable slug minted by
  // server/session.py (e.g. "amber-fox-42"). The slug is the capability —
  // there is no auth (accepted hackathon risk, SPEC.md §14.B).
  sessions: defineTable({
    slug: v.string(),
    title: v.string(),
    blocks: v.array(
      v.object({
        id: v.string(),
        text: v.string(),
      }),
    ),
    objections: v.array(
      v.object({
        id: v.string(),
        kind: v.string(),
        message: v.string(),
        refs: v.array(v.string()),
        status: v.string(), // "spoken" | "answered" | "dismissed"
      }),
    ),
    // "live" while the session is being mirrored; "finished" once the
    // server calls finish() (wrap-up polish landed, finalMarkdown set) or
    // close() (session reset/rotated away without a polish pass — the
    // audience page falls back to an "ended" notice when finalMarkdown is
    // absent, see AudienceView.jsx).
    status: v.string(),
    finalMarkdown: v.optional(v.string()),
    updatedAt: v.number(),
  }).index("by_slug", ["slug"]),
});
