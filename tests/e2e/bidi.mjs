import {spawn} from "node:child_process";
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {createServer} from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";

// Args: <firefox binary> <plan.json>; the plan lists steps {width, height, url, wait, probe, shot, gesture} and an optional
// init like cdp.mjs.
// Prints {results, errors}: one probe value per step and every JavaScript error the page logged.
const [binary, planFile] = process.argv.slice(2);
const plan = JSON.parse(readFileSync(planFile, "utf8"));
const profile = mkdtempSync(join(tmpdir(), "bidi-"));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const port = await new Promise((resolve) => {
  const probe = createServer().listen(0, "127.0.0.1", () => {
    const {port: free} = probe.address();
    probe.close(() => resolve(free));
  });
});
const browser = spawn(binary, ["--headless", "--no-remote", "--profile", profile, "--remote-debugging-port", String(port), "about:blank"], {stdio: ["ignore", "ignore", "pipe"]});

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
const waiting = new Map();
const errors = [];
let next = 0;
socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.method === "log.entryAdded" && data.params.level === "error" && data.params.type === "javascript") {
    errors.push(data.params.text);
  }
  if (data.id && waiting.has(data.id)) {
    const {resolve, reject} = waiting.get(data.id);
    waiting.delete(data.id);
    if (data.type === "error") {
      reject(new Error(`${data.error}: ${data.message}`));
    } else {
      resolve(data.result);
    }
  }
};

function send(method, params) {
  next += 1;
  const id = next;
  socket.send(JSON.stringify({id, method, params}));
  return new Promise((resolve, reject) => waiting.set(id, {resolve, reject}));
}

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
