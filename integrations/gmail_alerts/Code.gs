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
// links that are listings (not logos, settings or unsubscribe links)
const LISTING_LINK = /(spitogatos\.gr\/(aggelia|property)|spiti24\.gr\/\d|tospitimou\.gr\/.*\d{5,}|plot\.gr\/\d|car\.gr\/.*\d{6,}|indomio\.gr\/aggelies\/\d|xe\.gr\/property\/d\/)/i;
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
  const seen = new Set(last > 1 ? sh.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0])) : []);
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
      let m;
      while ((m = re.exec(body)) !== null) {
        const url = resolveRedirect(m[1].replace(/&amp;/g, '&'));
        if (!LISTING_LINK.test(url) || urls.has(url)) continue;
        urls.add(url);
        const text = strip(m[2]).slice(0, 200);
        const at = m.index;
        const context = strip(body.slice(Math.max(0, at - 1500), at + 1500)).slice(0, 600);
        rows.push([mid, msg.getDate(), PORTALS[portal], msg.getSubject(), url, text, context]);
      }
      if (!urls.size) {
        // keep a marker row so the email is not re-read; useful to see unknown formats
        rows.push([mid, msg.getDate(), PORTALS[portal], msg.getSubject(), '', '', strip(body).slice(0, 600)]);
      }
    });
  });
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  Logger.log(rows.length + ' rows added');
}

function strip(html) {
  return html.replace(/<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' ')
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
