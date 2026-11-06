  const RP_ID = "localhost";
  const ALGORITHMS = [-7, -8, -257];
  const onLocalhost = () => window.location.hostname === RP_ID;
  const localUrl = () => `http://${RP_ID}:${window.location.port}${window.location.pathname}${window.location.hash}`;
  const b64url = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const unb64url = (text) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=")), (char) => char.charCodeAt(0));
  const localLink = () => h("a", {href: localUrl()}, localUrl());
  const KEEPASSXC_LOCALHOST = "KeePassXC lehnt Passkeys auf http://localhost ab, bis in KeePassXC unter Werkzeuge → Einstellungen → Browser-Integration → Fortgeschritten „Nutzung von localhost mit Passkeys zulassen“ (Allow using localhost with passkeys) angehakt ist; die Datenbank muss entsperrt sein. Sonst meldet KeePassXC-Browser „Passkeys request canceled.“ und Chrome öffnet seinen eigenen Passkey-Dialog.";

  async function assertion(prepared, label) {
    if (!onLocalhost()) {
      toast(`${label}: nicht signiert`, [`Der Passkey signiert nur unter ${localUrl()}`], false);
      return null;
    }
    if (!prepared.credentials.length) {
      toast(`${label}: nicht signiert`, ["Kein Passkey gepinnt: Einstellungen → Passkey registrieren"], false);
      return null;
    }
    try {
      const credential = await navigator.credentials.get({publicKey: {
        challenge: unb64url(prepared.challenge),
        rpId: RP_ID,
        allowCredentials: prepared.credentials.map((id) => ({type: "public-key", id: unb64url(id)})),
        userVerification: "preferred",
        timeout: 120000,
      }});
      const answer = credential.response;
      return {id: b64url(credential.rawId), clientDataJSON: b64url(answer.clientDataJSON), authenticatorData: b64url(answer.authenticatorData), signature: b64url(answer.signature)};
    } catch (error) {
      toast(`${label}: nicht signiert`, [`${(error && error.name) || error}: KeePassXC gesperrt oder abgebrochen; nichts wurde gesendet.`], false);
      return null;
    }
  }

  async function proofFor(entries, label) {
    const result = await sendJson("/api/sign", {items: entries});
    if (!result.ok || !result.data) {
      toast(`${label}: nicht möglich`, fail(result), false);
      return null;
    }
    if (result.data.payload === null) {
      return {proof: null};
    }
    const signed = await assertion(result.data, label);
    return signed ? {proof: {payload: result.data.payload, assertion: signed}} : null;
  }

  async function registerPasskey(output) {
    if (!onLocalhost()) {
      output.replaceChildren(h("p", {class: "muted"}, "nicht registriert: WebAuthn braucht die Domain ", localLink()));
      return;
    }
    try {
      const credential = await navigator.credentials.create({publicKey: {
        rp: {id: RP_ID, name: "Agent Orchestrator"},
        user: {id: crypto.getRandomValues(new Uint8Array(16)), name: "operator", displayName: "Agent Orchestrator Operator"},
        challenge: crypto.getRandomValues(new Uint8Array(32)),
        pubKeyCredParams: ALGORITHMS.map((alg) => ({type: "public-key", alg})),
        attestation: "none",
        authenticatorSelection: {residentKey: "preferred", userVerification: "preferred"},
        timeout: 120000,
      }});
      const answer = credential.response;
      const blob = b64url(new TextEncoder().encode(JSON.stringify({id: b64url(credential.rawId), attestationObject: b64url(answer.attestationObject), clientDataJSON: b64url(answer.clientDataJSON)})));
      const command = `python3 ~/.local/share/kvb-orchestrator/client/approval.py pin --port ${window.location.port} --approvers ~/.config/kvb-orchestrator/approvers.json --credential '${blob}'`;
      output.replaceChildren(
        h("p", {class: "muted"}, "Diesen Befehl im Terminal des Hosts ausführen, außerhalb jeder Sandbox; erst dann gilt der Passkey. Der Hub pinnt nie selbst."),
        h("div", {class: "command"}, h("code", {}, command), copyButton(command)),
        h("label", {}, "Credential", h("textarea", {class: "field", readonly: true, rows: 3}, blob)));
    } catch (error) {
      output.replaceChildren(h("p", {class: "muted"}, `nicht registriert: ${(error && error.name) || error}`), h("p", {class: "muted"}, KEEPASSXC_LOCALHOST));
    }
  }

  function passkeySection() {
    const output = h("div", {class: "mini", "aria-live": "polite"});
    const keys = state.approvers.length
      ? h("ul", {class: "mini"}, state.approvers.map((key) => h("li", {}, pill(key.alg, "ok"), " ", h("code", {title: key.id}, `${key.id.slice(0, 16)}…`))))
      : h("p", {class: "muted"}, "Kein Passkey gepinnt: Runner, Hook und Commit-Skills verweigern jede Freigabe.");
    return h("section", {}, h("h3", {}, "Passkey"),
      h("p", {class: "muted"}, "Freigaben von Asks, Reviews und Operator-Befehlen signiert ein Passkey in KeePassXC; Runner, Hook und Commit-Skills prüfen die Signatur selbst gegen die gepinnten Schlüssel."),
      keys,
      h("p", {class: "muted"}, KEEPASSXC_LOCALHOST),
      onLocalhost() ? null : h("p", {class: "muted"}, "WebAuthn braucht die Domain: ", localLink()),
      h("div", {}, btn("Passkey registrieren", "btn small soft", () => registerPasskey(output))),
      output);
  }
