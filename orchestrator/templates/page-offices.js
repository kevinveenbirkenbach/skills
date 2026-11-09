  const OFFICE_RESULTS = {done: ["done", "ok"], refused: ["refused", "bad"], failed: ["failed", "bad"]};
  const OFFICE_VERBS = {
    appoint: ["Appoint", "bi-person-plus", "council.py claim --operator on the host: the chosen session gets the free office."],
    takeover: ["Hand over", "bi-arrow-left-right", "council.py takeover --operator on the host: the office goes to the chosen session, even if the current holder is still alive."],
    recall: ["Recall", "bi-person-x", "council.py release --operator on the host: the office becomes free, even if the holder is still alive."],
  };
  const OFFICE_HINT = "The host checks your passkey signature itself and refuses if the holder changed since the signature.";

  function successors(office, holder) {
    const [dimension, line] = office.split("/");
    const lined = Boolean(line) && dimension !== "work" && dimension !== "cluster";
    return state.graph.nodes
      .filter((node) => (node.kind === "session" || node.kind === "chair") && SESSION_ID.test(node.id) && node.id !== holder)
      .filter((node) => !lined || !state.claims.some((claim) => claim.session === node.id && claim.kind === "line" && claim.dimension === dimension && claim.office !== office))
      .map((node) => [node.id, `${labelOf(node.id)} · ${node.id.slice(0, 8)}`]);
  }

  function officeSheet(action, claim) {
    const office = claim ? claim.office : "";
    const holder = claim && action !== "appoint" ? claim.session : "";
    const [verb, glyph, text] = OFFICE_VERBS[action];
    const name = h("input", {class: "field", "aria-label": "Office", value: office, readonly: Boolean(office), maxlength: 129, autocomplete: "off", spellcheck: "false", placeholder: "chair, dimension/line, cluster/slug or work/slug"});
    const picks = successors(office, holder);
    const session = h("select", {class: "field", "aria-label": "Session"}, picks.map(([id, label]) => h("option", {value: id}, label)));
    const work = h("input", {class: "field", "aria-label": "Work", value: claim && claim.work !== "-" ? claim.work : "", maxlength: 300, autocomplete: "off", placeholder: "what the session works on in this office"});
    const outcome = h("div", {class: "mini", "aria-live": "polite"});
    const recall = action === "recall";
    const confirm = h("button", {type: "button", class: recall ? "btn danger" : "btn primary", disabled: !recall && !picks.length, ...named(verb, `${verb}: hand over to the host with your passkey signature`)}, icon(glyph), verb);
    confirm.addEventListener("click", async () => {
      const item = {kind: "office", action, office: name.value.trim(), holder, session: recall ? "" : session.value, work: recall ? "" : work.value.trim()};
      confirm.disabled = true;
      if (!await signOffice([item], outcome, verb)) {
        confirm.disabled = false;
      }
    });
    openSheet(office ? `${office}: ${verb}` : "Appoint a new office", [
      h("p", {class: "muted"}, text, " ", OFFICE_HINT),
      holder ? meta([["Holder", holderOf(claim) || holder, holder]]) : null,
      h("div", {class: "office-form"},
        h("label", {}, "Office", name),
        recall ? null : h("label", {}, "Session", picks.length ? session : h("span", {class: "muted"}, "No matching session known.")),
        recall ? null : h("label", {}, "Work", work)),
      outcome,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), confirm),
    ], false);
    (office ? (recall ? confirm : session) : name).focus();
  }

  async function signOffice(items, outcome, verb) {
    const signed = await proofFor(items, verb);
    if (signed === null) {
      outcome.replaceChildren(h("p", {class: "muted"}, "Not signed: nothing was handed over."));
      return false;
    }
    const result = await sendJson("/api/offices", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${verb}: not possible`, fail(result), false);
      outcome.replaceChildren(h("p", {class: "muted"}, `${result.status} ${result.text}`.trim()));
      return false;
    }
    outcome.replaceChildren(h("p", {class: "muted"},`Signed and handed to the host (job ${result.data.id}); the path unit now calls council.py.`));
    followJob(`/api/offices/${encodeURIComponent(result.data.id)}`, outcome, Date.now(), (data) => {
      const {good, lines} = showJob(data, outcome, "office", OFFICE_RESULTS);
      toast(`${verb}: ${good ? "done" : "not carried out"}`, lines, good);
      load();
    });
    return true;
  }
