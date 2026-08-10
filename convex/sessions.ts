// convex/sessions.ts — SPEC.md §14.B mutations/queries for the live-share
// mirror. Codegen-free: queryGeneric/mutationGeneric from "convex/server",
// NOT the generated helper module Convex writes under a dotfile-prefixed
// folder (doesn't exist until a human runs `npx convex dev` with their own
// account — this file must type-check and deploy without that ever having
// happened on this machine).
//
// Call sites (server/mirror.py, server-owned, fire-and-forget):
//   ensure(slug)                      <- session start / share
//   updateDoc(slug, title, blocks)    <- after every doc_update broadcast
//   upsertObjection(slug, objection)  <- after every interrupt + objection_update
//   finish(slug, markdown)            <- final_doc (wrap-up polish only)
//   close(slug)                       <- reset (rotates away the old slug)
//
// All mutations are idempotent / upsert-by-slug: any of them may be the
// first call to touch a given slug (ensure() is fire-and-forget from the
// server too, so it can race updateDoc/upsertObjection), so every handler
// creates the row if it's missing rather than assuming ensure() already ran.
import { mutationGeneric as mutation, queryGeneric as query } from "convex/server";
import { v } from "convex/values";

const blockValidator = v.object({
  id: v.string(),
  text: v.string(),
});

const objectionValidator = v.object({
  id: v.string(),
  kind: v.string(),
  message: v.string(),
  refs: v.array(v.string()),
  status: v.string(),
});

async function findBySlug(ctx: any, slug: string) {
  // .first() rather than .unique(): never throw on an unexpected duplicate
  // (e.g. a race between two fire-and-forget upserts) — this mirror is a
  // best-effort demo feature, not a source of truth, so degrade quietly.
  return await ctx.db
    .query("sessions")
    .withIndex("by_slug", (q: any) => q.eq("slug", slug))
    .first();
}

// Idempotent create-if-missing. Never overwrites an existing row.
export const ensure = mutation({
  args: { slug: v.string() },
  handler: async (ctx, { slug }) => {
    const existing = await findBySlug(ctx, slug);
    if (existing) return existing._id;
    return await ctx.db.insert("sessions", {
      slug,
      title: "",
      blocks: [],
      objections: [],
      status: "live",
      updatedAt: Date.now(),
    });
  },
});

export const updateDoc = mutation({
  args: {
    slug: v.string(),
    title: v.string(),
    blocks: v.array(blockValidator),
  },
  handler: async (ctx, { slug, title, blocks }) => {
    const existing = await findBySlug(ctx, slug);
    if (existing) {
      // status "live": a row being actively written IS live — this also
      // revives a finished row the user resumed via draft_open.
      await ctx.db.patch(existing._id, { title, blocks, status: "live", updatedAt: Date.now() });
      return existing._id;
    }
    return await ctx.db.insert("sessions", {
      slug,
      title,
      blocks,
      objections: [],
      status: "live",
      updatedAt: Date.now(),
    });
  },
});

export const upsertObjection = mutation({
  args: {
    slug: v.string(),
    objection: objectionValidator,
  },
  handler: async (ctx, { slug, objection }) => {
    const existing = await findBySlug(ctx, slug);
    if (!existing) {
      return await ctx.db.insert("sessions", {
        slug,
        title: "",
        blocks: [],
        objections: [objection],
        status: "live",
        updatedAt: Date.now(),
      });
    }
    const objections = (existing.objections ?? []).filter(
      (o: any) => o.id !== objection.id,
    );
    objections.push(objection);
    await ctx.db.patch(existing._id, { objections, updatedAt: Date.now() });
    return existing._id;
  },
});

// Sets status "finished" + finalMarkdown (the one-time wrap-up polish pass,
// SPEC.md §5 "Finish flow").
export const finish = mutation({
  args: { slug: v.string(), markdown: v.string() },
  handler: async (ctx, { slug, markdown }) => {
    const existing = await findBySlug(ctx, slug);
    if (!existing) {
      return await ctx.db.insert("sessions", {
        slug,
        title: "",
        blocks: [],
        objections: [],
        status: "finished",
        finalMarkdown: markdown,
        updatedAt: Date.now(),
      });
    }
    await ctx.db.patch(existing._id, {
      status: "finished",
      finalMarkdown: markdown,
      updatedAt: Date.now(),
    });
    return existing._id;
  },
});

// Sets status "finished" WITHOUT touching finalMarkdown — used on session
// reset to close out the old slug's row (it's being rotated away, not
// polished). AudienceView.jsx shows an "ended" fallback when finalMarkdown
// is absent on a finished row.
export const close = mutation({
  args: { slug: v.string() },
  handler: async (ctx, { slug }) => {
    const existing = await findBySlug(ctx, slug);
    if (!existing) {
      return await ctx.db.insert("sessions", {
        slug,
        title: "",
        blocks: [],
        objections: [],
        status: "finished",
        updatedAt: Date.now(),
      });
    }
    await ctx.db.patch(existing._id, { status: "finished", updatedAt: Date.now() });
    return existing._id;
  },
});

// Resume editing a stored draft (MCP draft_open): flip it back to live.
export const reopen = mutation({
  args: { slug: v.string() },
  handler: async (ctx, { slug }) => {
    const existing = await findBySlug(ctx, slug);
    if (!existing) return null;
    await ctx.db.patch(existing._id, { status: "live", updatedAt: Date.now() });
    return existing._id;
  },
});

export const getBySlug = query({
  args: { slug: v.string() },
  handler: async (ctx, { slug }) => {
    return await findBySlug(ctx, slug);
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("sessions").order("desc").take(50);
  },
});
