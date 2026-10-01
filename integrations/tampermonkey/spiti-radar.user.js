// ==UserScript==
// @name         Spiti Radar capture
// @namespace    https://jenyshir.com/spiti-radar
// @version      1.0
// @description  Sends the listings shown on a portal results page to Spiti Radar (one click, the page you are looking at).
// @match        https://www.spitogatos.gr/*
// @match        https://www.spiti24.gr/*
// @match        https://www.tospitimou.gr/*
// @match        https://www.plot.gr/*
// @match        https://www.indomio.gr/*
// @match        https://www.xe.gr/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      script.google.com
// @connect      script.googleusercontent.com
// ==/UserScript==

(function () {
  'use strict';

  // same listing links as integrations/gmail_alerts/Code.gs
  const LISTING_LINK = /(spitogatos|spiti24|tospitimou|plot|car|indomio|xe)\.gr\/(?:[^\s"<>]*?(aggelia|aggelies|property\/d\/|akinito|listing|ad\/|\/\d{6,})|\d{6,}-)/i;
  const MAX_CARD_TEXT = 800;

  function settings(ask) {
    let url = GM_getValue('endpoint', '');
    let key = GM_getValue('key', '');
    if (ask || !url || !key) {
      url = (prompt('Spiti Radar: адрес веб-приложения Apps Script', url) || '').trim();
      key = (prompt('Spiti Radar: ключ (capture key)', key) || '').trim();
      GM_setValue('endpoint', url);
      GM_setValue('key', key);
    }
    return {url, key};
  }

  function cleanUrl(href) {
    const u = new URL(href, location.href);
    u.hash = '';
    [...u.searchParams.keys()].filter(k => /^utm_/i.test(k)).forEach(k => u.searchParams.delete(k));
    return u.toString();
  }

  function listingLinks(root) {
    const urls = new Set();
    root.querySelectorAll('a[href]').forEach(a => {
      if (LISTING_LINK.test(a.href)) urls.add(cleanUrl(a.href));
    });
    return urls;
  }

  // the largest element around the link that still holds only this one listing
  function cardFor(anchor) {
    let card = anchor;
    for (let el = anchor.parentElement; el && el !== document.body; el = el.parentElement) {
      if (listingLinks(el).size > 1) break;
      card = el;
    }
    return card;
  }

  function collect() {
    const items = new Map();
    document.querySelectorAll('a[href]').forEach(a => {
      if (!LISTING_LINK.test(a.href)) return;
      const url = cleanUrl(a.href);
      const text = (cardFor(a).innerText || '').replace(/\s+/g, ' ').trim().slice(0, MAX_CARD_TEXT);
      const old = items.get(url);
      if (!old || text.length > old.text.length) items.set(url, {url, text});
    });
    return [...items.values()].filter(it => /€/.test(it.text));
  }

  function transaction() {
    const s = decodeURIComponent(location.href).toLowerCase();
    if (/enoik|rent|ενοικ|μισθ/.test(s)) return 'ενοικίαση';
    if (/pwlis|polis|agora|sale|buy|πωλ/.test(s)) return 'πώληση';
    return '';
  }

  function send(button) {
    const items = collect();
    if (!items.length) {
      toast('На этой странице не найдено объявлений с ценой');
      return;
    }
    const {url, key} = settings(false);
    if (!url || !key) return;
    button.disabled = true;
    GM_xmlhttpRequest({
      method: 'POST',
      url: url,
      headers: {'Content-Type': 'text/plain;charset=utf-8'},
      data: JSON.stringify({key, page: location.href, transaction: transaction(), items}),
      onload: r => {
        button.disabled = false;
        let res = {};
        try { res = JSON.parse(r.responseText); } catch (e) { /* not json */ }
        toast(res.ok ? 'Отправлено в Spiti Radar: ' + res.added : 'Ошибка: ' + (res.error || 'HTTP ' + r.status));
      },
      onerror: () => {
        button.disabled = false;
        toast('Ошибка сети, попробуйте ещё раз');
      },
    });
  }

  function toast(text) {
    const t = document.createElement('div');
    t.textContent = text;
    t.style.cssText = 'position:fixed;left:16px;bottom:76px;z-index:2147483647;padding:10px 14px;border-radius:8px;' +
                      'background:#18262a;color:#fff;font:14px sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.3)';
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  function addButton() {
    const b = document.createElement('button');
    b.textContent = '→ Spiti Radar';
    b.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;padding:12px 16px;border:0;' +
                      'border-radius:24px;background:#0e6b76;color:#fff;font:600 15px sans-serif;' +
                      'box-shadow:0 2px 8px rgba(0,0,0,.3);cursor:pointer';
    b.addEventListener('click', () => send(b));
    document.body.appendChild(b);
  }

  GM_registerMenuCommand('Spiti Radar: настройки', () => settings(true));
  addButton();
})();
