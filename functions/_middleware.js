// Time-limited access to the Spiti Radar pages (Cloudflare Pages Functions, both city sites).
//
// A link carries ?key=<expires>.<label>.<signature>: expires = Unix seconds, label = who the link
// is for ([a-z0-9-], may be empty), signature = HMAC-SHA256(ACCESS_SECRET, "<expires>.<label>")
// in base64url. scripts/make_access_link.py makes such links. A valid key is moved into a cookie
// that ends with the key, and the visitor is sent to the same address without it.
//
// ACCESS_SECRET is a Pages environment variable (secret). While it is not set the site stays
// open to everyone, so the check is switched on by setting it.

const COOKIE = "sr_access";
const enc = new TextEncoder();

function b64urlDecode(s) {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

// -> seconds left, or 0 when the key is malformed, forged or expired
export async function keyValid(key, secret, now = Date.now() / 1000) {
  const m = /^(\d{9,11})\.([a-z0-9-]{0,40})\.([A-Za-z0-9_-]{43})$/.exec(key || "");
  if (!m) return 0;
  const expires = Number(m[1]);
  if (expires <= now) return 0;
  const k = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  let sig;
  try {
    sig = b64urlDecode(m[3]);
  } catch {
    return 0;
  }
  const ok = await crypto.subtle.verify("HMAC", k, sig, enc.encode(`${m[1]}.${m[2]}`));
  return ok ? Math.floor(expires - now) : 0;
}

function cookieKey(request) {
  const c = request.headers.get("Cookie") || "";
  const m = new RegExp(`(?:^|;\\s*)${COOKIE}=([^;]+)`).exec(c);
  return m ? m[1] : "";
}

const DENIED = `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Spiti Radar</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 16px;color:#222;background:#fff}
@media (prefers-color-scheme:dark){body{color:#eee;background:#111}}</style></head>
<body><h1>Доступ закрыт</h1><p>Ссылка недействительна или срок доступа закончился.
Попросите у владельца Spiti Radar новую ссылку.</p></body></html>`;

export async function onRequest(context) {
  const { request, env, next } = context;
  const secret = env.ACCESS_SECRET;
  if (!secret) return next();
  const url = new URL(request.url);
  const key = url.searchParams.get("key");
  if (key !== null) {
    const left = await keyValid(key, secret);
    if (left) {
      url.searchParams.delete("key");
      return new Response(null, {
        status: 302,
        headers: {
          Location: url.pathname + url.search + url.hash,
          "Set-Cookie": `${COOKIE}=${key}; Max-Age=${left}; Path=/; Secure; HttpOnly; SameSite=Lax`,
          "Cache-Control": "no-store",
        },
      });
    }
  } else if (await keyValid(cookieKey(request), secret)) {
    const res = await next();
    const out = new Response(res.body, res);
    out.headers.set("Cache-Control", "private, no-store");
    return out;
  }
  return new Response(DENIED, { status: 403, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}
