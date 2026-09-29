/**
 * Spiti Radar — portal alert inbox → Google Sheet.
 *
 * Runs inside the dedicated alerts Gmail account (script.google.com).
 * Every run it reads new alert emails from property portals and writes one
 * row per listing link into the sheet "alerts". Spiti Radar reads that sheet
 * (published as CSV) and adds the new listings to the search.
 *
 * Setup (once):
 *   1. script.google.com → New project → paste this file → Save.
 *   2. Run `setup` once and allow access to Gmail and Sheets.
 *      It creates the sheet "Spiti Radar alerts" and a daily trigger.
 *   3. In the sheet: File → Share → Publish to web → sheet "alerts" → CSV → Publish.
 *      Give the CSV link to Spiti Radar (environment variable PORTAL_ALERTS_CSV_URL).
 *
 * Nothing leaves the account except what you publish: portal name, email date,
 * subject, listing link, link text and a short text fragment around the link.
 *
 * Browser captures (integrations/tampermonkey/spiti-radar.user.js) come in through doPost
 * and are written to the same sheet, in the same columns, so Spiti Radar reads them
 * together with the alerts. Setup (once):
 *   4. Run `setupCapture` once; it logs the capture key.
 *   5. Deploy → New deployment → Web app: execute as Me, access Anyone → Deploy.
 *      Give the web app URL and the capture key to the Tampermonkey script.
 *   Optional: script properties TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID make the bot
 *   confirm every capture in Telegram.
 */

const PORTALS = {
  'spitogatos': 'Spitogatos',
  'spiti24': 'Spiti24',
  'tospitimou': 'Tospitimou',
  'plot.gr': 'Plot',
  'car.gr': 'Plot',
  'indomio': 'Indomio',
  'xe.gr': 'XE',
};
// links that are listings (not logos, settings or unsubscribe links), on any of the portals
// plot.gr puts the listing number right after the domain: plot.gr/40778351-diamerisma-...
const LISTING_LINK = /(spitogatos|spiti24|tospitimou|plot|car|indomio|xe)\.gr\/(?:[^\s"<>]*?(aggelia|aggelies|property\/d\/|akinito|listing|ad\/|\/\d{6,})|\d{6,}-)/i;
// links that are never listings; not worth a lookup
const SKIP_LINK = /unsubscribe|apenergopoi|settings|preferences|privacy|terms|facebook|instagram|twitter|youtube|linkedin|apple\.com|google\.com|\.(png|jpe?g|gif)(\?|$)/i;
const QUERY = 'newer_than:4d (from:spitogatos OR from:spiti24 OR from:tospitimou OR from:plot.gr OR from:car.gr OR from:indomio OR from:xe.gr)';
const SHEET_NAME = 'alerts';
const PROP_SHEET_ID = 'SPITI_RADAR_SHEET_ID';

function setup() {
  const props = PropertiesService.getScriptProperties();
  let id = props.getProperty(PROP_SHEET_ID);
  if (!id) {
    const ss = SpreadsheetApp.create('Spiti Radar alerts');
    const sh = ss.getSheets()[0];
    sh.setName(SHEET_NAME);
    sh.appendRow(['message_id', 'received', 'portal', 'subject', 'url', 'link_text', 'context']);
    id = ss.getId();
    props.setProperty(PROP_SHEET_ID, id);
  }
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('collectAlerts').timeBased().everyHours(6).create();
  collectAlerts();
  Logger.log('Sheet: https://docs.google.com/spreadsheets/d/' + id);
}

function collectAlerts() {
  const id = PropertiesService.getScriptProperties().getProperty(PROP_SHEET_ID);
  if (!id) throw new Error('Run setup() first');
  const sh = SpreadsheetApp.openById(id).getSheetByName(SHEET_NAME);
  const last = sh.getLastRow();
  const done = last > 1 ? sh.getRange(2, 1, last - 1, 5).getValues() : [];
  // emails that gave listing links are done; emails that gave none (marker row) are read again,
  // so a fixed link pattern picks up alerts that arrived before the fix
  const seen = new Set(done.filter(r => r[4]).map(r => String(r[0])));
  const marked = new Set(done.filter(r => !r[4]).map(r => String(r[0])));
  const rows = [];
  GmailApp.search(QUERY, 0, 200).forEach(thread => {
    thread.getMessages().forEach(msg => {
      const mid = msg.getId();
      if (seen.has(mid)) return;
      const from = msg.getFrom().toLowerCase();
      const portal = Object.keys(PORTALS).find(k => from.includes(k));
      if (!portal) return;
      const body = msg.getBody();
      const urls = new Set();
      const re = /<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
      let m, lookups = 0;
      while ((m = re.exec(body)) !== null) {
        let url = resolveRedirect(m[1].replace(/&amp;/g, '&'));
        // tracking links (click.xe.gr/..., sendgrid, etc.): ask the tracker where it points,
        // without opening the listing page itself
        if (!LISTING_LINK.test(url) && /^https?:/i.test(url) && !SKIP_LINK.test(url) && lookups < 150) {
          lookups++;
          url = followTracker(url);
        }
        if (!LISTING_LINK.test(url)) continue;
        url = url.replace(/[?&]utm_[^#]*$/, '');
        if (urls.has(url)) continue;
        urls.add(url);
        const text = strip(m[2]).slice(0, 200);
        const at = m.index;
        // text before and after the link; the card of the listing is in one of them
        const before = strip(body.slice(Math.max(0, at - 2500), at)).slice(-700);
        const after = strip(body.slice(at, at + 3000)).slice(0, 700);
        const host = (url.match(/(spitogatos|spiti24|tospitimou|plot|car|indomio|xe)\.gr/i) || [])[1];
        const name = host ? PORTALS[host.toLowerCase() === 'plot' ? 'plot.gr' : host.toLowerCase() === 'car' ? 'car.gr' : host.toLowerCase() === 'xe' ? 'xe.gr' : host.toLowerCase()] : PORTALS[portal];
        rows.push([mid, msg.getDate(), name || PORTALS[portal], msg.getSubject(), url, text, before + ' ⟦LINK⟧ ' + after]);
      }
      if (!urls.size && !marked.has(mid)) {
        // keep a marker row so the email is not re-read; useful to see unknown formats
        rows.push([mid, msg.getDate(), PORTALS[portal], msg.getSubject(), '', '', strip(body).slice(0, 600)]);
      }
    });
  });
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  Logger.log(rows.length + ' rows added');
}

const PROP_CAPTURE_KEY = 'SPITI_RADAR_CAPTURE_KEY';

function setupCapture() {
  const props = PropertiesService.getScriptProperties();
  let key = props.getProperty(PROP_CAPTURE_KEY);
  if (!key) {
    key = Utilities.getUuid();
    props.setProperty(PROP_CAPTURE_KEY, key);
  }
  Logger.log('Capture key: ' + key);
}

// body: {key, page, transaction, items: [{url, text}]}; one sheet row per listing
function doPost(e) {
  const props = PropertiesService.getScriptProperties();
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ok: false, error: 'bad json'});
  }
  if (!body.key || body.key !== props.getProperty(PROP_CAPTURE_KEY)) return reply({ok: false, error: 'bad key'});
  const items = (body.items || []).filter(it => it && LISTING_LINK.test(String(it.url || ''))).slice(0, 200);
  if (!items.length) return reply({ok: true, added: 0});
  const host = (String(body.page || '').match(/\/\/(?:www\.)?([^\/]+)/) || [])[1] || '';
  const key = Object.keys(PORTALS).find(k => host.toLowerCase().includes(k));
  const portal = key ? PORTALS[key] : host;
  const now = new Date();
  const subject = 'Browser capture: ' + (body.transaction || '') + ' ' + String(body.page || '').slice(0, 300);
  const rows = items.map(it => ['capture-' + now.getTime(), now, portal, subject, String(it.url).slice(0, 500),
                                '', ' ⟦LINK⟧ ' + String(it.text || '').replace(/\s+/g, ' ').slice(0, 800)]);
  const sh = SpreadsheetApp.openById(props.getProperty(PROP_SHEET_ID)).getSheetByName(SHEET_NAME);
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  notifyTelegram(props, 'Spiti Radar: получено ' + rows.length + ' объявлений с ' + portal + '. Попадут в поиск после утреннего сбора.');
  return reply({ok: true, added: rows.length});
}

function notifyTelegram(props, text) {
  const token = props.getProperty('TELEGRAM_BOT_TOKEN');
  const chat = props.getProperty('TELEGRAM_CHAT_ID');
  if (!token || !chat) return;
  UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage',
                    {method: 'post', payload: {chat_id: chat, text: text}, muteHttpExceptions: true});
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function strip(html) {
  return html.replace(/<style[\s\S]*?<\/style>/gi, ' ').replace(/^[^<]*>/, ' ').replace(/<[^>]*$/, ' ').replace(/<[^>]+>/g, ' ')
             .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
}

// portals often wrap links in click-tracking redirects; keep the real target when it is in the query
function resolveRedirect(url) {
  const m = url.match(/[?&](?:url|u|redirect|target|link)=([^&]+)/i);
  if (m) {
    try { return decodeURIComponent(m[1]); } catch (e) { /* keep original */ }
  }
  return url;
}

// one step at a time, only reading the redirect target (Location header), up to 4 hops
function followTracker(url) {
  for (let i = 0; i < 4; i++) {
    if (LISTING_LINK.test(url)) return url;
    let resp;
    try {
      resp = UrlFetchApp.fetch(url, {followRedirects: false, muteHttpExceptions: true});
    } catch (e) {
      return url;
    }
    const code = resp.getResponseCode();
    const loc = resp.getHeaders()['Location'] || resp.getHeaders()['location'];
    if (code < 300 || code >= 400 || !loc) return url;
    url = resolveRedirect(loc);
  }
  return url;
}
