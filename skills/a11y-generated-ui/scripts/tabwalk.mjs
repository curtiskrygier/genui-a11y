// Level 1 screen-reader check: walk every atom with the Tab key in headless Chromium and record, for each stop, what the browser's accessibility
// tree exposes (role, name, state). That is the information a screen reader is built from; it is not a screen reader.
// Input: <dir>/html.json + shell.css (as audit.mjs). Output: <dir>/tabwalk.json  {atom: {stops:[...], findings:{rule:count}, composite_unreached:n}}
import fs from 'node:fs';
import puppeteer from 'puppeteer-core';
import { readInput, namesOf, prepare, open, launchBrowser } from './lib.mjs';
const dir = process.argv[2];
const dark = process.argv[3] === 'dark';
const shell = fs.existsSync(dir + '/shell.css') ? fs.readFileSync(dir + '/shell.css', 'utf8') : '';
const d = readInput(dir);
const only = process.argv[4] ? process.argv[4].split(',') : null;
const MAXSTOPS = 60;
const NEEDS_NAME = new Set(['button','link','checkbox','radio','textbox','searchbox','combobox','listbox','slider','spinbutton','switch','tab','menuitem','menuitemcheckbox','menuitemradio','option','treeitem','img','image']);
const CONTROLS = new Set(['button','link','checkbox','textbox','searchbox','combobox','listbox','slider','spinbutton','switch']);
const COMPOSITE = new Set(['radio','tab','menuitem','menuitemcheckbox','menuitemradio','option','treeitem']);
const b = await launchBrowser(puppeteer, d);
const page = await b.newPage();
await prepare(page, d);
const cdp = await page.createCDPSession();
await cdp.send('Accessibility.enable'); await cdp.send('DOM.enable');
const val = (p) => (p && p.value !== undefined && p.value !== null) ? p.value : '';
const info = (nodes, bid) => {   // the AX node for one DOM node
  const n = nodes.find(x => x.backendDOMNodeId === bid && !x.ignored) || nodes.find(x => x.backendDOMNodeId === bid);
  if (!n) return { role: '', name: '', props: {} };
  const props = {}; for (const p of (n.properties || [])) if (['checked','selected','expanded','disabled','pressed','required','invalid','haspopup'].includes(p.name)) props[p.name] = val(p.value);
  return { role: val(n.role), name: String(val(n.name)).trim(), props, ignored: !!n.ignored };
};
const STY = el => { const c = getComputedStyle(el); return [c.outlineStyle, c.outlineWidth, c.outlineColor, c.boxShadow, c.backgroundColor, c.borderTopColor, c.color, c.textDecorationLine, c.transform, c.opacity].join('|'); };
const out = {};
for (const t of namesOf(d)) {
  if (only && !only.includes(t)) continue;
  const res = { stops: [], findings: {}, composite_unreached: 0, detail: [] };
  let curSn = '';
  const add = (k, extra) => { res.findings[k] = (res.findings[k] || 0) + 1; res.detail.push(k + ': ' + (extra || curSn)); };
  try {
    await open(page, d, t, { shell, dark, kind: 'tab' });
    await page.addStyleTag({ content: '*,*::before,*::after{animation-duration:0.001s!important;animation-delay:0s!important;animation-iteration-count:1!important;transition:none!important}' });
    await new Promise(r => setTimeout(r, 150));
    await page.evaluate(() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); window.focus(); });
    const seen = new Set(); const reachedBackend = new Set();
    let prevStyle = null;
    for (let i = 0; i < MAXSTOPS; i++) {
      await page.keyboard.press('Tab');
      const h = await page.evaluateHandle(() => document.activeElement);
      const meta = await page.evaluate((el, sty) => {
        if (!el || el === document.body || el === document.documentElement) return { gone: true };
        if (!el.__tw) el.__tw = Math.random().toString(36).slice(2);
        const r = el.getBoundingClientRect();
        const cs0 = getComputedStyle(el); const scroller = !el.hasAttribute('tabindex') && /(auto|scroll)/.test(cs0.overflowX + cs0.overflowY);
        return { scroller, sn: el.outerHTML.replace(/\s+/g,' ').slice(0,230), id: el.__tw, tag: el.tagName.toLowerCase(), w: Math.round(r.width), h: Math.round(r.height), style: eval('(' + sty + ')')(el), vis: getComputedStyle(el).visibility !== 'hidden' };
      }, h, STY.toString());
      if (meta.gone) { break; }
      if (seen.has(meta.id)) { if (i === 1 || meta.id === [...seen][0]) { /* wrapped */ } else add('focus_loop'); break; }
      seen.add(meta.id); curSn = meta.sn;
      const ev = await cdp.send('Runtime.evaluate', { expression: 'document.activeElement' });
      const desc = await cdp.send('DOM.describeNode', { objectId: ev.result.objectId });
      const bid = desc.node.backendNodeId; reachedBackend.add(bid);
      const ax = await cdp.send('Accessibility.getPartialAXTree', { backendNodeId: bid, fetchRelatives: false });
      const a = info(ax.nodes, bid);
      res.stops.push({ tag: meta.tag, role: a.role, name: a.name.slice(0, 60), props: a.props, w: meta.w, h: meta.h });
      if ((NEEDS_NAME.has(a.role)) && !a.name) add('unnamed_stop');
      if (a.name && !/[\p{L}\p{N}]/u.test(a.name) && !/\p{Extended_Pictographic}/u.test(a.name)) add('glyph_name');   // emoji are announced by their name, so they are not flagged   // a name that is only a symbol, such as a left angle bracket: read out as nothing useful
      if (res.stops.length > 1 && a.name && res.stops[res.stops.length - 2].name === a.name.slice(0, 60)) add('repeated_name');   // two stops in a row announced the same
      if ((!a.role || a.role === 'generic' || a.role === 'none' || a.role === 'GenericContainer') && !meta.scroller) add('generic_stop');   // a scroll container the browser made focusable is not an author mistake
      if (meta.w < 4 || meta.h < 4 || !meta.vis) add('invisible_stop');
      // visible focus: the same element, once focus has left it, must look different from when it had focus
      if (prevStyle) {
        const now = await page.evaluate((id, sty) => { const e = [...document.querySelectorAll('*')].find(x => x.__tw === id); return e ? eval('(' + sty + ')')(e) : null; }, prevStyle.id, STY.toString());
        if (now !== null && now === prevStyle.style) add('no_visible_focus', prevStyle.sn);
      }
      prevStyle = { id: meta.id, style: meta.style, sn: meta.sn };
    }
    if (res.stops.length >= MAXSTOPS) add('possible_trap');
    // controls the accessibility tree exposes that Tab never reached
    const full = (await cdp.send('Accessibility.getFullAXTree')).nodes;
    const byId = new Map(full.map(n => [n.nodeId, n]));
    const inNative = new Set();   // parts of a native date or time field (month, day, year, picker button): Tab moves through them inside one element
    for (const n of full) { let p = n.parentId; for (let k = 0; p && k < 6; k++) { const pn = byId.get(p); if (!pn) break; if (/^(Date|DateTime|InputTime|Time|Week|Month|DateTimeLocal)$/i.test(String(val(pn.role)))) { inNative.add(n.nodeId); break; } p = pn.parentId; } }
    for (const n of full) {
      if (n.ignored || !n.backendDOMNodeId) continue;
      const role = val(n.role); const dis = (n.properties || []).some(p => p.name === 'disabled' && val(p.value) === true);
      if (dis || reachedBackend.has(n.backendDOMNodeId) || inNative.has(n.nodeId)) continue;
      if (CONTROLS.has(role)) add('unreachable_control', role + ' ' + String(val(n.name)).slice(0, 40)); else if (COMPOSITE.has(role)) res.composite_unreached++;
    }
  } catch (e) { res.err = String(e.message).slice(0, 100); }
  out[t] = res;
}
await b.close();
fs.writeFileSync(dir + '/tabwalk.json', JSON.stringify(out));
console.log('walked ' + Object.keys(out).length);
