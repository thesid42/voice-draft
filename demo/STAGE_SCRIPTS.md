# Stage scripts — two 2-minute demos (live-validated)

Two speakable demo scripts. Every trap line was validated against the live
model (gates zeroed, run twice): the Critic fires **exactly** the two planned
objections and nothing else. Wording matters — deliver the **bold trap lines
verbatim**; paraphrase freely everywhere else.

## Prep (2 minutes, before you walk on)

1. Fresh server + browser reload (refresh = clean take). DevPanel closed for the show.
2. **Set `COOLDOWN_S` to ~20** on the DevPanel slider first (default 45 makes the second interrupt late at this pacing).
3. Speaker volume up; mic permission granted; VoiceOS typing into the capture field (test one sentence).
4. Morning-of, rerun both scripts once via the Sim (paste from here) — model behavior can drift.

**Rules of the stage:**
- **Pause briefly before every "Draft, …" command** so it chunks as its own utterance.
- When the Critic speaks: **stop talking, let it finish** (echo protection handles the rest), then answer.
- If it objects to a *different* line than planned: answer whatever it said and keep going — the arc still works. The scripted answers below are for the expected objections.
- After each answer, glance at the doc — the paragraph visibly improves. Let the audience see you notice.

---

## Script 1 — "The pitch" (meta: pitch Draft with Draft) · ~2:00

> **1.** Okay. I want to draft the pitch for Draft — the writing tool that argues back.
>
> **2.** The way it works: you think out loud, and the page writes itself while you talk.
>
> **3. Draft ships with no settings at all. We deleted the preferences menu — that's the whole religion.** *(trap premise — verbatim)*
>
> **4.** Out of the box it just goes. Install, talk, and you're drafting — zero setup, zero questions.
>
> **5. And honestly, it's ten times faster than anything else on the market.** *(TRAP A — verbatim, then stop talking)*

🔴 **CRITIC** (~3s later): *"Ten times faster than what, measured how?"* — orb pulses, block glows.

> **6.** *(answer)* Fair — ten times faster at first-run setup specifically. You're drafting in under a minute, where the incumbents take ten just to onboard you.
>
> **7.** *(pause, then)* **Draft, share this.** — *QR appears; audience phones join the live doc*
>
> **8.** And you can watch it happening — this document behind me is being written by the thing I'm pitching, which still feels a little like cheating.
>
> **9.** The design bet is one input and one page. You speak, it writes, and the critic keeps score.
>
> **10. Oh — and for the power users, we're going to let them tweak every single knob in the pipeline. Full customization.** *(TRAP B — verbatim, then stop)*

🔴 **CRITIC**: *"You said Draft has no settings at all — now power users can tweak every knob. Which is it?"*

> **11.** *(concede, grinning)* Ha — caught me. The knobs stay buried unless you go digging. The default path never shows you a single setting.
>
> **12.** So that's Draft: it writes while you talk, and it argues when you're wrong.
>
> **13.** *(pause)* **Draft, wrap it up.** — *clean final doc appears; the "no settings vs knobs" tension reads resolved*

---

## Script 2 — "The war on meetings" (relatable memo) · ~2:00

> **1.** I want to draft a memo to the team about how we run meetings. Working title: the war on meetings.
>
> **2.** Here's the thesis: this company runs on deep work, and meetings are where deep work goes to die.
>
> **3. So the new rule is simple: we are killing recurring meetings. All of them. The calendar starts empty.** *(trap premise — verbatim)*
>
> **4.** If something needs a decision, it becomes a doc first — writing forces the thinking.
>
> **5. The average engineer here loses twenty hours a week to meetings.** *(TRAP A — verbatim, then stop)*

🔴 **CRITIC**: *"Twenty hours a week according to what measurement?"*

> **6.** *(answer)* Good catch — that's straight from our January time audit: twenty-one hours for a typical engineer, so I rounded down to twenty.
>
> **7.** The point stands: the calendar should default to empty, and anything that survives has to earn its slot.
>
> **8.** Docs replace status updates, comments replace check-ins, and decisions get a one-page write-up with a named owner.
>
> **9. And obviously we'll still do the daily thirty-minute all-hands standup every morning, because alignment matters.** *(TRAP B — deadpan, verbatim, then stop)*

🔴 **CRITIC**: *"You just said you're killing all recurring meetings, but you're keeping a daily standup. Which is it?"*

> **10.** *(beat, then concede)* Yeah — that's exactly the kind of meeting this memo is supposed to kill. Scratch the standup; alignment moves to a Monday doc, async. — *watch the standup line get REVISED out of the doc, not appended*
>
> **11.** New closing line: if a meeting can be a document, it will be. And if it can't, it had better be short.
>
> **12.** *(optional flourish, pause)* **Draft, read that back.** — *the Critic's voice reads your closing line*
>
> **13.** *(pause)* **Draft, wrap it up.**

---

## Why these traps (if a judge asks)

- Trap A in both is a **naked number** — `vague_claim` is the Critic's most reliable sense.
- Trap B is a **binary factual contradiction** ("no settings" vs "every knob"; "kill all recurring meetings" vs "daily standup") — validated to fire the moment cooldown allows.
- Script 2's concession also demos the **Writer's self-correction**: the standup line gets revised away, not appended.
- Validation transcripts: both scripts fired exactly `[vague_claim, contradiction]` with zero extras, two runs each (2026-08-09, gpt-4o via OpenRouter).
