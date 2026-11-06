import {spawn} from "node:child_process";
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

// Args: <chromium binary> <plan.json>; the plan lists steps {width, height, url, wait, probe, shot}.
// Prints {results, errors}: one probe value per step and every uncaught page exception.
const [binary, planFile] = process.argv.slice(2);
const plan = JSON.parse(readFileSync(planFile, "utf8"));
const profile = mkdtempSync(join(tmpdir(), "cdp-"));
// --no-sandbox: the agent sandbox already forbids the user namespaces Chromium's own sandbox needs.
const flags = ["--headless", "--no-sandbox", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"];
const browser = spawn(binary, flags, {stdio: ["ignore", "ignore", "pipe"]});
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const address = await new Promise((resolve, reject) => {
  let text = "";
  const timer = setTimeout(() => reject(new Error(`no DevTools address: ${text.slice(-500)}`)), 30000);
  browser.stderr.on("data", (chunk) => {
    text += chunk;
    const found = /DevTools listening on (ws:\/\/\S+)/.exec(text);
    if (found) {
      clearTimeout(timer);
      resolve(found[1]);
    }
  });
  browser.on("exit", (code) => reject(new Error(`browser exited with ${code}: ${text.slice(-500)}`)));
});

const socket = new WebSocket(address);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});
const waiting = new Map();
const errors = [];
let next = 0;
socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.method === "Runtime.exceptionThrown") {
    const details = data.params.exceptionDetails;
    errors.push(details.exception ? details.exception.description : details.text);
  }
  if (data.id && waiting.has(data.id)) {
    const {resolve, reject} = waiting.get(data.id);
    waiting.delete(data.id);
    if (data.error) {
      reject(new Error(JSON.stringify(data.error)));
    } else {
      resolve(data.result);
    }
  }
};

function send(method, params, sessionId) {
  next += 1;
  const id = next;
  socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
  return new Promise((resolve, reject) => waiting.set(id, {resolve, reject}));
}

const results = [];
try {
  const {targetId} = await send("Target.createTarget", {url: "about:blank"});
  const {sessionId} = await send("Target.attachToTarget", {targetId, flatten: true});
  const page = (method, params) => send(method, params, sessionId);
  await page("Runtime.enable", {});
  for (const step of plan.steps) {
    await page("Emulation.setDeviceMetricsOverride", {width: step.width, height: step.height, deviceScaleFactor: 1, mobile: false});
    if (step.url) {
      await page("Page.navigate", {url: step.url});
    }
    await sleep(step.wait);
    let value = null;
    if (step.probe) {
      const {result, exceptionDetails} = await page("Runtime.evaluate", {expression: step.probe, awaitPromise: true, returnByValue: true});
      value = exceptionDetails ? {error: exceptionDetails.exception ? exceptionDetails.exception.description : exceptionDetails.text} : result.value;
    }
    if (step.shot) {
      const {data} = await page("Page.captureScreenshot", {format: "png"});
      writeFileSync(step.shot, Buffer.from(data, "base64"));
    }
    results.push(value);
  }
} finally {
  socket.close();
  browser.kill();
  rmSync(profile, {recursive: true, force: true});
}
console.log(JSON.stringify({results, errors}));
