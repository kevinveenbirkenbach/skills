# 094 - Hub Cards Bound to Their Claude Dialog

## User Story

As the operator, I want a hub card for a Claude dialog (an ask or an
AskUserQuestion) to live exactly as long as that dialog and to close the
moment either side answers, so that I never see a card expire or go stale
while its dialog in Claude is still open.

## Decisions (operator-confirmed 2026-11-27; do not re-litigate)

1. **Cause** (found 2026-11-27): the PermissionRequest hook waits
   `HOOK_TIMEOUT=110` s (`scripts/orchestrator.sh`) for the hub; then the
   card expires while Claude's own dialog stays open as long as the operator
   takes. The operator rejected several such cards as "expired in hub".
2. **One lifecycle per dialog** (operator): the card and the dialog share
   the call key of 080. The hook keeps waiting while the dialog lives, up
   to a timeout adjustable in Settings (default 60 min, at most the hook
   timeout Claude Code allows); whichever side answers first wins.
3. **Claude's answer closes the card at once** (operator): PostToolUse (an
   allowed call, an AskUserQuestion with its answers) closes it as "answered
   in Claude"; the session's next `Stop` or `UserPromptSubmit` closes every
   still open card of that session (a denial or an interrupt in Claude);
   `SessionEnd` closes the session's cards.
4. **Timer only as fallback** (operator): a card whose hook timed out while
   its dialog may still be open shows "open in Claude: answer it there",
   never stale or expired; it closes by decision 3.
5. **Test first** (operator): before the wait grows, a live test settles
   whether Claude shows its dialog while the hook waits (the docs do not
   say). If the dialog only appears after the hook returns, the default wait
   stays at 110 s and decisions 3 and 4 still apply.
   Rejected: a longer fixed wait without the binding.
   **Result 2026-11-27** (operator, AskUserQuestion live test, second run):
   the Claude dialog appears at once while the hook waits, so both run side
   by side and the longer default wait of decision 2 applies.
6. **Closes bound to a session token** (operator, 2026-11-28, after a
   skeptic found that any local process sending the guard header could end
   another session's cards and forge an AskUserQuestion choice): the hook
   keeps one `secrets.token_urlsafe(32)` closer token per session id in a
   mode 0600 file beside its replay store
   (`~/.local/state/kvb-orchestrator-approvals/closers/<session>.token`,
   linked into place on first use, session id checked against
   `signing.SESSION`), sends it as `closer` with every ask, every hooked
   decision and every closing report, and deletes it after its
   `SessionEnd` report. The hub keeps only its sha256 digest and closes a
   card only when the digest matches (`hmac.compare_digest`); `Stop`,
   `UserPromptSubmit` and `SessionEnd` never close a card without one, and a
   PostToolUse records an answer as choice only for a matching one. A card
   an older hook registered without a closer still closes by its call key
   on PostToolUse, with no choice.
   Rejected: signing each report with a passkey (a click per tool call).

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> T1
    subgraph T["🔬 T · Live test"]
        T1["⏱️ A 3-minute ask: does the dialog show while the hook waits?"] --> T2{"💬 Operator confirms what they saw?"}
    end
    T2 -- "📋 result recorded" --> A1
    subgraph A["🔗 A · Binding"]
        A1["🪝 PostToolUse, Stop, UserPromptSubmit, SessionEnd close cards"] --> A2["⏳ Adjustable wait, 'open in Claude' fallback"]
        A2 --> A3{"🧪 Unit, integration and E2E green?"}
        A3 -- "🔴 no: fix" --> A1
        A3 -- "🟢 yes" --> AF{"💬 Operator feedback?"}
        AF -- "✏️ changes" --> A1
    end
    AF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Binding

- [ ] An ask allowed in Claude leaves the hub's open cards within 5 s of
      its PostToolUse.
- [ ] An AskUserQuestion answered in Claude closes its hub decision with
      the answers shown, and the card leaves an open Match deck within 5 s
      of the answer, without waiting for the deck's refresh interval
      (operator 2026-11-27: answered cards stayed far too long).
- [ ] A denial in Claude closes the session's open cards at its next `Stop`
      or `UserPromptSubmit`.
- [ ] `SessionEnd` closes every open card of the session.
- [ ] After a hook timeout the card reads "open in Claude" and carries no
      stale or expired stamp.
- [ ] A closing report without the session's closer token, or with another
      one, closes no card and records no choice; the hub stores only the
      token's digest; a card of an older hook closes by its call key on
      PostToolUse only (decision 6).

### Wait

- [ ] Settings holds the wait (1 to 60 min); the hook's `--timeout` and its
      settings.json timeout follow it after `make orchestrator-hook`.
- [x] The live test result is recorded in this document (decision 5).

### Tests

- Unit:
  - [ ] Card state over the lifecycle: open, answered in hub, answered in
        Claude, open in Claude.
- Integration:
  - [ ] Each closing hook event through the HTTP handler closes exactly the
        cards of its session and call key.
  - [ ] `tests/test_hub_dialog_bound_cards.py` `TestCloserBinding` and
        `TestCloserToken`: no or a wrong closer closes nothing, the right
        one only its own session's cards, no forged choice, older-hook
        cards, a 0600 token file and refused session ids.
- E2E:
  - [ ] `tests/e2e/test_dialog_bound_cards_e2e.py`: a card closes on a
        simulated PostToolUse, Stop and SessionEnd; the "open in Claude"
        state after a timeout.
