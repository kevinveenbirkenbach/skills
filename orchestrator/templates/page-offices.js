  const OFFICE_RESULTS = {done: ["erledigt", "ok"], refused: ["verweigert", "bad"], failed: ["fehlgeschlagen", "bad"]};
  const OFFICE_VERBS = {
    appoint: ["Besetzen", "bi-person-plus", "council.py claim --operator auf dem Host: die gewählte Session erhält das freie Amt."],
    takeover: ["Übergeben", "bi-arrow-left-right", "council.py takeover --operator auf dem Host: das Amt geht an die gewählte Session, auch wenn der bisherige Inhaber noch lebt."],
    recall: ["Abberufen", "bi-person-x", "council.py release --operator auf dem Host: das Amt wird frei, auch wenn der Inhaber noch lebt."],
  };
  const OFFICE_HINT = "Der Host prüft deine Passkey-Signatur selbst und verweigert, wenn sich der Inhaber seit der Signatur geändert hat.";

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
    const name = h("input", {class: "field", "aria-label": "Amt", value: office, readonly: Boolean(office), maxlength: 129, autocomplete: "off", spellcheck: "false", placeholder: "chair, dimension/linie, cluster/slug oder work/slug"});
    const picks = successors(office, holder);
    const session = h("select", {class: "field", "aria-label": "Session"}, picks.map(([id, label]) => h("option", {value: id}, label)));
    const work = h("input", {class: "field", "aria-label": "Arbeit", value: claim && claim.work !== "-" ? claim.work : "", maxlength: 300, autocomplete: "off", placeholder: "woran die Session in diesem Amt arbeitet"});
    const outcome = h("div", {class: "mini", "aria-live": "polite"});
    const recall = action === "recall";
    const confirm = h("button", {type: "button", class: recall ? "btn danger" : "btn primary", disabled: !recall && !picks.length, ...named(verb, `${verb}: mit deiner Passkey-Signatur an den Host übergeben`)}, icon(glyph), verb);
    confirm.addEventListener("click", async () => {
      const item = {kind: "office", action, office: name.value.trim(), holder, session: recall ? "" : session.value, work: recall ? "" : work.value.trim()};
      confirm.disabled = true;
      if (!await signOffice([item], outcome, verb)) {
        confirm.disabled = false;
      }
    });
    openSheet(office ? `${office}: ${verb}` : "Neues Amt besetzen", [
      h("p", {class: "muted"}, text, " ", OFFICE_HINT),
      holder ? meta([["Inhaber", holderOf(claim) || holder, holder]]) : null,
      h("div", {class: "office-form"},
        h("label", {}, "Amt", name),
        recall ? null : h("label", {}, "Session", picks.length ? session : h("span", {class: "muted"}, "Keine passende Session bekannt.")),
        recall ? null : h("label", {}, "Arbeit", work)),
      outcome,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Abbrechen", "btn ghost", closeSheet), confirm),
    ], false);
    (office ? (recall ? confirm : session) : name).focus();
  }

  async function signOffice(items, outcome, verb) {
    const signed = await proofFor(items, verb);
    if (signed === null) {
      outcome.replaceChildren(h("p", {class: "muted"}, "Nicht signiert: nichts wurde übergeben."));
      return false;
    }
    const result = await sendJson("/api/offices", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${verb}: nicht möglich`, fail(result), false);
      outcome.replaceChildren(h("p", {class: "muted"}, `${result.status} ${result.text}`.trim()));
      return false;
    }
    outcome.replaceChildren(h("p", {class: "muted"},`Signiert und an den Host übergeben (Job ${result.data.id}); die Path-Unit ruft jetzt council.py auf.`));
    followJob(`/api/offices/${encodeURIComponent(result.data.id)}`, outcome, Date.now(), (data) => {
      const {good, lines} = showJob(data, outcome, "office", OFFICE_RESULTS);
      toast(`${verb}: ${good ? "erledigt" : "nicht ausgeführt"}`, lines, good);
      load();
    });
    return true;
  }
