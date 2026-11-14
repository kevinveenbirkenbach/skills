const Glossary = (() => {
  "use strict";
  const RULE_HINTS = {
    ask: "Grants matching asks in matching directories, never a command with a warning (rm -r, push, --force, sudo, pipes into a shell …). The passkey signs the rule and the agents it applies to once; the hook checks signature, pattern and agent itself.",
    review: "Grants reviews of matching branches and worktrees, only when their gate is green, for every agent: a review names no session. The passkey signs the rule once; the commit skill checks signature and pattern itself.",
    decision: "Takes the recommended option in decisions of matching agents. The passkey signs the rule once; the decisions themselves stay unsigned.",
  };
  const OFFICE_VERBS = {
    appoint: ["Appoint", "bi-person-plus", "council.py claim --operator on the host: the chosen session gets the free office."],
    takeover: ["Hand over", "bi-arrow-left-right", "council.py takeover --operator on the host: the office goes to the chosen session, even if the current holder is still alive."],
    recall: ["Recall", "bi-person-x", "council.py release --operator on the host: the office becomes free, even if the holder is still alive."],
  };
  const GATE_ACTIONS = {
    commit: "a commit on this branch needs a gate receipt for its tree that meets the level; the commit-msg and pre-merge-commit hooks check it.",
    merge: "a merge into this branch needs a receipt that meets the level; the pre-merge-commit hook checks it, the pre-push hook checks fast-forward and squash merges.",
    push: "pushing this branch needs a receipt that meets the level for the tree of every pushed commit; the pre-push hook checks it.",
    pr: "a pull request from this branch needs the level; gates.py resolve reports it, no git hook checks it.",
  };
  const GATE_LEVELS = {
    none: "no receipt needed.",
    quick: "gates.py quick passed on the staged files: Python syntax, JSON, bash -n and git diff --check.",
    test: "a green make test on the exact tree, GPU tests off.",
    "quality-high": "a green make quality-high on the exact tree, GPU tests off.",
    e2e: "a green make e2e on the exact tree, GPU tests off; the strictest level.",
  };
  const RECEIPT = ["receipt", "a green run records one for its tree; it meets its own level and every lower one for 30 days."];
  const GATE_SOURCES = {
    own: ["own rule", "the branch sets this level itself."],
    inherited: ["inherited from", "the branch sets no level, so the strictest level of its parent branches applies; the chip names the branch that sets it."],
    unset: ["no rule", "neither the branch nor a parent sets a level, so the action needs no receipt."],
    staged: ["staged", "changed here, not applied yet: Apply signs every staged change with one passkey signature, Discard drops them."],
  };
  const GATE_CYCLE = ["click, Enter or Space", "cycles the own rule through none, quick, test, quality-high and e2e, then back to inherited."];
  const BRANCH_MARKS = {
    merged: ["merged", "pkgmgr branch gc found every tip of the branch in the default branch or a merge line."],
    unmerged: ["not merged", "the branch holds commits the default branch does not have."],
    protected: ["protected", "the default or a protected branch: gc never deletes it."],
    stale: ["stale", "pkgmgr branch gc marks the entry stale; the Reason line says why."],
    unpushed: ["commits unpushed", "local commits its upstream does not have yet."],
    behind: ["commits behind", "upstream commits the local branch does not have yet."],
    gone: ["upstream gone", "the remote branch it tracks was deleted."],
    detached: ["no upstream", "the branch tracks no remote branch."],
    skip: ["gc skips", "pkgmgr branch gc leaves the branch alone for the reason shown."],
    reason: ["Reason", "pkgmgr's own words: merged by ancestor, by patch or by a pull request; unmerged with the commits not in the default branch; no own commits; dirty with the changed paths; default or protected branch."],
  };

  /**
   * @param {Object} mark one Ancestry.gateMarks entry: action, level, source and own.
   * @param {Object|null} staged the staged change of the chip, its level null when it drops the own rule.
   * @returns {Object} text: the chip text, also its aria-label; hint: the tooltip that explains it.
   */
  function gateChip(mark, staged) {
    const kind = staged ? "staged" : mark.own ? "own" : mark.source ? "inherited" : "unset";
    const level = staged ? staged.level || "inherited" : mark.level;
    const from = kind === "inherited" ? `${GATE_SOURCES.inherited[0]} ${mark.source}` : GATE_SOURCES[kind][0];
    const text = `${mark.action}: ${level} (${from})`;
    const meaning = Object.hasOwn(GATE_LEVELS, level) ? GATE_LEVELS[level] : GATE_SOURCES.inherited[1];
    return {text, hint: [text, `${mark.action}: ${GATE_ACTIONS[mark.action]}`, `${level}: ${meaning}`, `${from}: ${GATE_SOURCES[kind][1]}`, `${GATE_CYCLE[0]}: ${GATE_CYCLE[1]}`].join("\n")};
  }

  /**
   * @returns {Array<[string, Array<[string, string]>]>} the sections the Explain action lists, each a heading and its [term, meaning] rows.
   */
  function explain() {
    return [
      ["Gate actions", Object.entries(GATE_ACTIONS)],
      ["Gate levels", [...Object.entries(GATE_LEVELS), RECEIPT]],
      ["Where a level comes from", [...Object.values(GATE_SOURCES), GATE_CYCLE]],
      ["Branch marks", Object.values(BRANCH_MARKS)],
    ];
  }

  return {RULE_HINTS, OFFICE_VERBS, GATE_ACTIONS, GATE_LEVELS, GATE_SOURCES, GATE_CYCLE, RECEIPT, BRANCH_MARKS, gateChip, explain};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Glossary;
}
