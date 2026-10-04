// TapTrack PD <-> iMessage via Photon Spectrum (spectrum-ts, cloud iMessage lines; no Mac needed).
//
//   node photon/sidecar.mjs
//
// - POST http://127.0.0.1:$PHOTON_PORT/send  {"to": "caregiver"|"patient"|"+1555...", "text": "..."}
// - GET  /health
// - Inbound iMessages (e.g. the caregiver asking "how is mom today?") are forwarded to the TapTrack API
//   POST /api/chat, and the reply is sent back in the same conversation (context is kept per sender
//   by the API).
// Spectrum has no HTTP send API, so this small Node process is the documented way for a Python app to send.
// Env (../.env): PHOTON_PROJECT_ID, PHOTON_PROJECT_SECRET, CAREGIVER_PHONE, PATIENT_PHONE, PHOTON_PORT, TAPTRACK_URL.
// Missing credentials -> the server still starts and /send answers {ok:false, error:"Photon not configured"}.
import http from "node:http";

try { process.loadEnvFile(new URL("../.env", import.meta.url)); } catch { /* no .env: rely on the environment */ }

const env = (k, d = "") => (process.env[k] ?? "").trim() || d;
const PROJECT_ID = env("PHOTON_PROJECT_ID", env("SPECTRUM_PROJECT_ID"));
const PROJECT_SECRET = env("PHOTON_PROJECT_SECRET", env("SPECTRUM_PROJECT_SECRET"));
const PORT = Number(env("PHOTON_PORT", "8790"));
const API = env("TAPTRACK_URL", `http://127.0.0.1:${env("PORT", "8000")}`);
const PHONES = { caregiver: env("CAREGIVER_PHONE"), patient: env("PATIENT_PHONE") };

let im = null;
let app = null;
let status = PROJECT_ID && PROJECT_SECRET ? "connecting" : "not configured (set PHOTON_PROJECT_ID and PHOTON_PROJECT_SECRET)";
const mask = (p) => (p ? p.slice(0, 2) + "***" + p.slice(-2) : null);
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), "[photon]", ...a);

async function connect() {
  if (!PROJECT_ID || !PROJECT_SECRET) return log(status);
  try {
    const { Spectrum } = await import("spectrum-ts");
    const { imessage } = await import("spectrum-ts/providers/imessage");
    app = await Spectrum({ projectId: PROJECT_ID, projectSecret: PROJECT_SECRET, providers: [imessage.config()] });
    im = imessage(app);
    status = "connected";
    log("connected to Spectrum; caregiver", mask(PHONES.caregiver), "patient", mask(PHONES.patient));
    listen();
  } catch (e) {
    status = `error: ${e.message}`;
    log("Spectrum connect failed:", e.message);
  }
}

async function send(to, text) {
  const phone = PHONES[to] ?? to;
  if (!im) return { ok: false, error: `Photon ${status}` };
  if (!phone) return { ok: false, error: `no phone number configured for ${to} (set ${to.toUpperCase()}_PHONE)` };
  try {
    const space = await im.space.create(phone);
    await space.send(text);
    log("sent to", to, mask(phone));
    return { ok: true, to, space: space.id };
  } catch (e) {
    const hint = /not allowed/i.test(e.message) ? " (register this number under Users in the Photon dashboard)" : "";
    log("send failed:", e.message);
    return { ok: false, error: e.message + hint };
  }
}

async function listen() {
  try {
    for await (const [space, message] of app.messages) {
      if (message.direction !== "inbound" || message.content?.type !== "text") continue;
      const from = message.sender?.id ?? "unknown";
      const role = from === PHONES.caregiver ? "caregiver" : from === PHONES.patient ? "patient" : "unknown";
      log("inbound from", role, mask(from));
      try {
        await space.responding(async () => {
          const r = await fetch(`${API}/api/chat`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ from, role, text: message.content.text, space_id: space.id }),
          });
          const data = await r.json();
          if (data.reply) await space.send(data.reply);
        });
      } catch (e) {
        log("reply failed:", e.message);
      }
    }
  } catch (e) {
    status = `stream error: ${e.message}`;
    log(status);
  }
}

const server = http.createServer(async (req, res) => {
  const reply = (code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };
  if (req.method === "GET" && req.url === "/health") {
    return reply(200, { ok: status === "connected", status, caregiver: mask(PHONES.caregiver), patient: mask(PHONES.patient) });
  }
  if (req.method === "POST" && req.url === "/send") {
    let body = "";
    for await (const chunk of req) body += chunk;
    try {
      const { to, text } = JSON.parse(body || "{}");
      if (!to || !text) return reply(400, { ok: false, error: "need to and text" });
      return reply(200, await send(to, text));
    } catch (e) {
      return reply(400, { ok: false, error: e.message });
    }
  }
  reply(404, { ok: false, error: "not found" });
});

server.listen(PORT, "127.0.0.1", () => log(`listening on 127.0.0.1:${PORT}; TapTrack API ${API}`));
connect();
