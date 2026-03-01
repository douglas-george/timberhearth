---
title: Status Guide
type: meta
---

# Status Guide — The Three Tiers of Timberhearth

Every document and claim in this vault carries one of three status levels. This distinction is the backbone of the system: it separates what *is* from what *may be*, and what the players know from what only the DM knows.

---

## ✅ CANON

> *"This happened. It is real and locked."*

Canon facts have been **determined by player choices and session events**. They cannot be revised. The world is built on them. When a session ends and something has been decided — a choice made, a character met, a truth revealed — it becomes canon.

**Examples:**
- Gabriel and Jessica were summoned together at the Night of Voices.
- The town fountain was destroyed in the Great Pumpkin Fray.
- Ringtail saved them at the pumpkin patch and collapsed.

Use the `✅ [CANON]` inline marker for canon facts embedded in mixed documents.

---

## 👁️ REVEALED

> *"The players know this. It is the working truth of the world — but it hasn't been fully locked in by choices yet."*

Revealed lore is information the characters have **encountered, learned, or been told**. It is real from the players' perspective. However, it may still carry nuance, misunderstanding, or gaps that future sessions clarify. It has not yet been *cemented* by a player choice the way canon facts are.

**Examples:**
- There are thirteen Guardians who gave up their human forms.
- The pumpkin seed ban is tied to a real magical seal.
- Whistlewing's true name was Elric Brightfeather.

Use the `👁️ [REVEALED]` inline marker for revealed lore in mixed documents.

---

## 🔒 HIDDEN

> *"The DM knows this. The players do not — yet."*

Hidden lore is **DM-only material**: backstory, motivations, future plot hooks, and working assumptions that guide the in-game experience but have not entered the players' world. Hidden lore is the most freely revisable tier — it can be updated, changed, or discarded as the story evolves, as long as it hasn't been revealed.

**Examples:**
- The current whereabouts of the eight undiscovered Guardians.
- Ringtail's condition after the pumpkin patch.
- Maribel's full knowledge and what she plans to do with it.

Use the `🔒 [HIDDEN]` inline marker for hidden content in mixed documents.

---

## Document-Level Status

Every file in this vault has a `status` field in its YAML frontmatter:

```yaml
---
status: canon        # the whole document is canon
---
```

```yaml
---
status: revealed     # players know this exists and roughly what it says
---
```

```yaml
---
status: hidden       # DM eyes only
---
```

When a document is **mixed** (contains content from multiple tiers), set `status: mixed` in the frontmatter and use inline markers throughout the body.

---

## Promotion

When a session event promotes content from one tier to the next, record it in [`canon-log.md`](canon-log.md). This is the living heartbeat of the vault.

> Hidden → Revealed: the players encountered or learned this.
> Revealed → Canon: a player choice locked this in permanently.
