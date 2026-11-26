import {readFileSync} from "node:fs";

const ANSWER_MS = 240000;

// Returns {binary, plan}: the browser binary and the parsed plan.json named by the driver's two arguments.
export function readPlan() {
  const [binary, planFile] = process.argv.slice(2);
  return {binary, plan: JSON.parse(readFileSync(planFile, "utf8"))};
}

// Args: socket an open WebSocket to the browser; browser its spawned process; label names the protocol in errors;
// failure(data) returns the Error a reply carries, else null; event(data) sees every message.
// Returns call({method, ...}): sends it with a fresh id and resolves with the reply's result; it rejects on an error
// reply, after ANSWER_MS without one, or once the socket closes or the browser exits.
export function connect(socket, browser, label, failure, event) {
  const waiting = new Map();
  let next = 0;
  const failAll = (why) => {
    for (const {reject} of waiting.values()) {
      reject(new Error(why));
    }
    waiting.clear();
  };
  socket.onclose = () => failAll(`${label} socket closed`);
  browser.on("exit", (code) => failAll(`browser exited with ${code}`));
  socket.onmessage = (message) => {
    const data = JSON.parse(message.data);
    event(data);
    if (data.id && waiting.has(data.id)) {
      const {resolve, reject} = waiting.get(data.id);
      waiting.delete(data.id);
      const error = failure(data);
      if (error) {
        reject(error);
      } else {
        resolve(data.result);
      }
    }
  };
  return (payload) => {
    next += 1;
    const id = next;
    socket.send(JSON.stringify({id, ...payload}));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        waiting.delete(id);
        reject(new Error(`${payload.method} got no answer within ${ANSWER_MS} ms`));
      }, ANSWER_MS);
      const settle = (finish) => (value) => {
        clearTimeout(timer);
        finish(value);
      };
      waiting.set(id, {resolve: settle(resolve), reject: settle(reject)});
    });
  };
}
