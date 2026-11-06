  async function send(path, body, type) {
    try {
      const response = await fetch(path, {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": type}, body, cache: "no-store"});
      const text = await response.text();
      let data = null;
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
      return {ok: response.ok, status: response.status, text, data};
    } catch (error) {
      return {ok: false, status: 0, text: String(error), data: null};
    }
  }
  const sendJson = (path, payload) => send(path, JSON.stringify(payload), "application/json");
  const fail = (result) => [`${result.status} ${result.text}`.trim()];
