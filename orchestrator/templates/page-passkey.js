  const RP_ID = "localhost";
  const ALGORITHMS = [-7, -8, -257];
  const onLocalhost = () => window.location.hostname === RP_ID;
  const localUrl = () => `http://${RP_ID}:${window.location.port}${window.location.pathname}${window.location.hash}`;
  const b64url = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const unb64url = (text) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=")), (char) => char.charCodeAt(0));
  const localLink = () => h("a", {href: localUrl()}, localUrl());
  const KEEPASSXC_LOCALHOST = "KeePassXC refuses passkeys on http://localhost until “Allow using localhost with passkeys” is checked in KeePassXC under Tools → Settings → Browser Integration → Advanced; the database must be unlocked. Otherwise KeePassXC-Browser reports “Passkeys request canceled.” and Chrome opens its own passkey dialog.";

  async function assertion(prepared, label) {
    if (!onLocalhost()) {
      toast(`${label}: not signed`, [`The passkey signs only under ${localUrl()}`], false);
      return null;
    }
    if (!prepared.credentials.length) {
      toast(`${label}: not signed`, ["No passkey pinned: Settings → Register passkey"], false);
      return null;
    }
    const prompt = h("div", {class: "toast wait passkey-prompt", id: "passkey-prompt", role: "status", "aria-live": "polite"}, h("strong", {}, "Passkey signs"), h("pre", {}, promptText(label, prepared)));
    document.body.append(prompt);
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
      toast(`${label}: not signed`, [`${(error && error.name) || error}: KeePassXC locked or canceled; nothing was sent.`], false);
      return null;
    } finally {
      prompt.remove();
    }
  }

  let signing = false;

  async function prove(path, fields, label) {
    const result = await sendJson(path, fields);
    if (!result.ok || !result.data) {
      toast(`${label}: not possible`, fail(result), false);
      return null;
    }
    if (result.data.payload === null) {
      return {proof: null};
    }
    const signed = await assertion(result.data, label);
    return signed ? {proof: {payload: result.data.payload, assertion: signed}} : null;
  }

  async function signedProof(path, fields, label) {
    if (signing) {
      toast(`${label}: not signed`, ["Another passkey signature is still open: finish or cancel it first; nothing was sent."], false);
      return null;
    }
    signing = true;
    try {
      return await prove(path, fields, label);
    } finally {
      signing = false;
    }
  }

  function proofFor(entries, label) {
    return signedProof("/api/sign", {items: entries}, label);
  }

  async function registerPasskey(output) {
    if (!onLocalhost()) {
      output.replaceChildren(h("p", {class: "muted"}, "not registered: WebAuthn needs the domain ", localLink()));
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
        h("p", {class: "muted"}, "Run this command in the host's terminal, outside any sandbox; only then does the passkey apply. The hub never pins by itself."),
        h("div", {class: "command"}, h("code", {}, command), copyButton(command)),
        h("label", {}, "Credential", h("textarea", {class: "field", readonly: true, rows: 3}, blob)));
    } catch (error) {
      output.replaceChildren(h("p", {class: "muted"}, `not registered: ${(error && error.name) || error}`), h("p", {class: "muted"}, KEEPASSXC_LOCALHOST));
    }
  }

  function passkeySection() {
    const output = h("div", {class: "mini", "aria-live": "polite"});
    const keys = state.approvers.length
      ? h("ul", {class: "mini"}, state.approvers.map((key) => h("li", {}, pill(key.alg, "ok"), " ", h("code", {title: key.id}, `${key.id.slice(0, 16)}…`))))
      : h("p", {class: "muted"}, "No passkey pinned: runner, hook and commit skills refuse every grant.");
    return h("section", {}, h("h3", {}, "Passkey"),
      h("p", {class: "muted"}, "A passkey in KeePassXC signs grants of asks, reviews and operator commands; runner, hook and commit skills check the signature themselves against the pinned keys."),
      keys,
      h("p", {class: "muted"}, KEEPASSXC_LOCALHOST),
      onLocalhost() ? null : h("p", {class: "muted"}, "WebAuthn needs the domain: ", localLink()),
      h("div", {}, btn("Register passkey", "btn small soft", () => registerPasskey(output))),
      output);
  }
