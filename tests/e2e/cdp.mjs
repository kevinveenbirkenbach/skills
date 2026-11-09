import {spawn} from "node:child_process";
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

// Args: <chromium binary> <plan.json>; the plan lists steps {width, height, url, wait, keys, probe, shot, media, gesture},
// keys being real key presses (Enter, Tab) on the focused element before the probe and gesture running the probe with a
// user activation like a click, an optional init, the text of a function every new document runs before its own scripts,
// and an optional authenticator {credentialId, privateKey, rpId}: base64 id and PKCS#8 key of a passkey the page may sign with.
// Prints {results, errors}: one probe value per step and every uncaught page exception.
const [binary, planFile] = process.argv.slice(2);
const plan = JSON.parse(readFileSync(planFile, "utf8"));
const profile = mkdtempSync(join(tmpdir(), "cdp-"));
// --no-sandbox: the agent sandbox already forbids the user namespaces Chromium's own sandbox needs.
// --enable-unsafe-swiftshader: without a GPU, headless Chromium gives WebGL only through SwiftShader, which it no longer enables by itself.
// --ignore-certificate-errors: the https station fixtures use a throwaway self-signed certificate.
const flags = ["--headless", "--no-sandbox", "--disable-gpu", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-certificate-errors", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"];
const browser = spawn(binary, flags, {stdio: ["ignore", "ignore", "pipe"]});
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const KEYS = {Enter: [13, "\r"], Tab: [9, ""]};

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
  if (plan.init) {
    await page("Page.enable", {});
    await page("Page.addScriptToEvaluateOnNewDocument", {source: `(${plan.init})();`});
  }
  if (plan.authenticator) {
    await page("WebAuthn.enable", {enableUI: false});
    const {authenticatorId} = await page("WebAuthn.addVirtualAuthenticator", {options: {protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
    await page("WebAuthn.addCredential", {authenticatorId, credential: {...plan.authenticator, isResidentCredential: false, signCount: 0}});
  }
  for (const step of plan.steps) {
    await page("Emulation.setDeviceMetricsOverride", {width: step.width, height: step.height, deviceScaleFactor: 1, mobile: false});
    await page("Emulation.setEmulatedMedia", {features: step.media || []});
    if (step.url) {
      await page("Page.navigate", {url: step.url});
    }
    await sleep(step.wait);
    for (const key of step.keys || []) {
      const [code, text] = KEYS[key];
      await page("Input.dispatchKeyEvent", {type: "keyDown", key, code: key, windowsVirtualKeyCode: code, text});
      await page("Input.dispatchKeyEvent", {type: "keyUp", key, code: key, windowsVirtualKeyCode: code});
      await sleep(250);
    }
    let value = null;
    if (step.probe) {
      const {result, exceptionDetails} = await page("Runtime.evaluate", {expression: step.probe, awaitPromise: true, returnByValue: true, userGesture: Boolean(step.gesture)});
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
  rmSync(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 200});
}
console.log(JSON.stringify({results, errors}));
