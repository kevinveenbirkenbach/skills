import {spawn} from "node:child_process";
import {mkdtempSync, rmSync, writeFileSync} from "node:fs";
import {createServer} from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {connect, readPlan} from "./driver.mjs";

// Args: <firefox binary> <plan.json>; the plan lists steps {width, height, url, wait, keys, drag, probe, shot, gesture} and
// an optional init like cdp.mjs.
// Prints {results, errors}: one probe value per step and every JavaScript error the page logged.
const {binary, plan} = readPlan();
const profile = mkdtempSync(join(tmpdir(), "bidi-"));
writeFileSync(join(profile, "user.js"), ['user_pref("media.navigator.streams.fake", true);', 'user_pref("media.navigator.permission.disabled", true);', 'user_pref("media.volume_scale", "0.0");', ""].join("\n"));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const KEYS = {Enter: "", Tab: "", ArrowLeft: "", ArrowRight: ""};
const port = await new Promise((resolve) => {
  const probe = createServer().listen(0, "127.0.0.1", () => {
    const {port: free} = probe.address();
    probe.close(() => resolve(free));
  });
});
// Trip-wire: Firefox still starts "crashreporter --ping-cleanup", which ignores MOZ_CRASHREPORTER_DISABLE and can dump core.<pid> into its cwd; the throwaway profile takes it.
const browser = spawn(binary, ["--headless", "--no-remote", "--profile", profile, "--remote-debugging-port", String(port), "about:blank"], {cwd: profile, stdio: ["ignore", "ignore", "pipe"], env: {...process.env, MOZ_CRASHREPORTER_DISABLE: "1"}});

const address = await new Promise((resolve, reject) => {
  let text = "";
  const timer = setTimeout(() => reject(new Error(`no BiDi address: ${text.slice(-500)}`)), 60000);
  browser.stderr.on("data", (chunk) => {
    text += chunk;
    const found = /WebDriver BiDi listening on (ws:\/\/\S+)/.exec(text);
    if (found) {
      clearTimeout(timer);
      resolve(found[1]);
    }
  });
  browser.on("exit", (code) => reject(new Error(`browser exited with ${code}: ${text.slice(-500)}`)));
});

const socket = new WebSocket(`${address}/session`);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});
const errors = [];
const call = connect(socket, browser, "BiDi", (data) => (data.type === "error" ? new Error(`${data.error}: ${data.message}`) : null), (data) => {
  if (data.method === "log.entryAdded" && data.params.level === "error" && data.params.type === "javascript") {
    errors.push(data.params.text);
  }
});
const send = (method, params) => call({method, params});

const results = [];
try {
  await send("session.new", {capabilities: {alwaysMatch: {acceptInsecureCerts: true}}});
  await send("session.subscribe", {events: ["log.entryAdded"]});
  if (plan.init) {
    await send("script.addPreloadScript", {functionDeclaration: plan.init});
  }
  const {contexts} = await send("browsingContext.getTree", {});
  const context = contexts[0].context;
  for (const step of plan.steps) {
    await send("browsingContext.setViewport", {context, viewport: {width: step.width, height: step.height}});
    if (step.url) {
      await send("browsingContext.navigate", {context, url: step.url, wait: "complete"});
    }
    await sleep(step.wait);
    for (const key of step.keys || []) {
      await send("input.performActions", {context, actions: [{type: "key", id: "keyboard", actions: [{type: "keyDown", value: KEYS[key]}, {type: "keyUp", value: KEYS[key]}]}]});
      await sleep(250);
    }
    if (step.drag) {
      const [[x0, y0], [x1, y1]] = step.drag;
      const moves = [{type: "pointerMove", x: x0, y: y0}, {type: "pointerDown", button: 0}, {type: "pointerMove", x: x1, y: y1}, {type: "pointerUp", button: 0}];
      await send("input.performActions", {context, actions: [{type: "pointer", id: "mouse", parameters: {pointerType: "mouse"}, actions: moves}]});
      await sleep(250);
    }
    let value = null;
    if (step.probe) {
      const answer = await send("script.evaluate", {expression: `(async () => JSON.stringify(await ${step.probe}))()`, target: {context}, awaitPromise: true, resultOwnership: "none", userActivation: Boolean(step.gesture)});
      value = answer.type === "success" ? JSON.parse(answer.result.value) : {error: answer.exceptionDetails.text};
    }
    if (step.shot) {
      const {data} = await send("browsingContext.captureScreenshot", {context});
      writeFileSync(step.shot, Buffer.from(data, "base64"));
    }
    results.push(value);
  }
  await send("browser.close", {}).catch(() => null);
} finally {
  socket.close();
  browser.kill();
  await sleep(300);
  rmSync(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 200});
}
console.log(JSON.stringify({results, errors}));
