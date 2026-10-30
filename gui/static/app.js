// PaperPull's panel. One page and no build step. Each view has an address
// after the #, so Back and a bookmark work, and every action is a request to
// the panel's own API, which checks it again whatever the page says.
'use strict';
// PaperPull Server, where the panel is in a browser on another computer.
const SERVER = __SERVER__;
// Whether the terms of use are still to be accepted, and which version
// (gui/app.py). Read as text, so a page served with the placeholders left
// as they are does not ask.
const TERMS_DUE = '__TERMS_DUE__' === 'true';
const TERMS_VERSION = '__TERMS_VERSION__';
const $ = id => document.getElementById(id);

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
// Remembered in this browser only, and a browser that keeps nothing, a
// private window say, just keeps nothing.
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* nothing kept */ } },
};

// -- icons, drawn with the text's own color ---------------------------------------
function sv(d, size, width) {
  return '<svg width="' + (size || 18) + '" height="' + (size || 18) + '" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="' + (width || 2) + '" stroke-linecap="round" stroke-linejoin="round" ' +
    'aria-hidden="true">' + d + '</svg>';
}
function svFill(d, size) {
  return '<svg width="' + (size || 18) + '" height="' + (size || 18) + '" viewBox="0 0 24 24" fill="currentColor" ' +
    'aria-hidden="true">' + d + '</svg>';
}
const P = {
  chevron: '<path d="M9 6l6 6-6 6"/>', left: '<path d="M15 6l-6 6 6 6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>', check: '<path d="M5 12l5 5L19 7"/>',
  alert: '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  restore: '<path d="M4 12a8 8 0 1 0 2.3-5.7"/><path d="M4 4v5h5"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8z"/><path d="M7.5 7.5h.01"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  report: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
  file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  record: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/>',
  person: '<circle cx="10" cy="8" r="4"/><path d="M3 21a7 7 0 0 1 14 0M19 8v6M16 11h6"/>',
  box: '<path d="M3 7h18v4H3zM5 11v8h14v-8M10 15h4"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
};
const DOTS = svFill('<circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/>', 20);
const PLAY = svFill('<path d="M7 5l12 7-12 7z"/>', 16);
const STOP = svFill('<rect x="6" y="6" width="12" height="12" rx="2"/>', 16);
const PAUSE = svFill('<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>', 26);

// -- what the panel holds ------------------------------------------------------------
let META = null;        // /api/apps
let ROWS = null;        // /api/accounts, one per provider and person
let PROVIDERS = null;   // /api/providers, for choosing providers
let VIEW = '';
const ROUTE = {view: '', app: '', account: ''};

// PaperPull Server signs a session out after hours without use, and the
// page then meets 401 on its next request, so it goes to the sign-in.
function signedOut(r) {
  if (SERVER && r.status === 401) location.href = '/login';
}
async function getJSON(url) {
  const r = await fetch(url);
  signedOut(r);
  let d = {};
  try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw new Error((d && typeof d.detail === 'string' && d.detail) || 'the panel answered ' + r.status);
  return d;
}
async function postJSON(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify(body || {})});
  signedOut(r);
  let d = {};
  try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw new Error((d && typeof d.detail === 'string' && d.detail) || 'that did not work');
  return d;
}
const inSample = () => Boolean(META && META.root_source === 'sample');
const keyOf = r => r.app + '\n' + r.account;
const rowByKey = key => (ROWS || []).find(r => keyOf(r) === key) || null;
const rowFor = (app, account) => (ROWS || []).find(r => r.app === app && r.account === account) || null;

// -- words -----------------------------------------------------------------------
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function when(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  if (!m) return '';
  const year = +m[1], same = year === new Date().getFullYear();
  return MONTHS[+m[2] - 1] + ' ' + (+m[3]) + (same ? '' : ', ' + year);
}
function many(n, one, more) { return n + ' ' + (n === 1 ? one : (more || one + 's')); }
function noun(r) { return r && r.kind === 'RECEIPT' ? 'receipt' : 'document'; }
// A provider's name as an owner, Lowe's for Lowe's, never Lowe's's, as the
// core says it (paperpull_core.listing).
function whose(name) { return /'s$/.test(name) ? name : name + "'s"; }
const CADENCE = {'weekly': 'every week', '2x month': 'twice a month', 'monthly': 'every month',
                 'quarterly': 'every three months', '2x year': 'twice a year', 'yearly': 'once a year'};
function whoOf(r) { return r.owner || (r.account !== 'primary' ? r.account : ''); }
function subOf(r) {
  return [whoOf(r), r.gets || (r.kind === 'RECEIPT' ? 'Receipts' : 'Statements')].filter(Boolean).join(' · ');
}
function tint(name) {
  let h = 0;
  for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return 't' + (h % 5);
}
function mono(r, big) {
  return '<span class="tile-mono ' + tint(r.provider) + (big ? ' lg' : '') + '" aria-hidden="true">' +
    esc((r.provider || '?').charAt(0).toUpperCase()) + '</span>';
}
const ACTION_WORDS = {login: 'Sign in', discover: "Check what's there", pilot: 'Try the newest few',
  all: 'Get new documents', resume: 'Continue', verify: 'Check saved files', diagnose: 'Support report',
  record: 'Record steps', rename: 'Rename preview', rename_apply: 'Apply renames', review_names: 'Review names'};
const ACTION_DOING = {login: 'Opening the sign-in window for %s', discover: 'Checking what %s has',
  pilot: 'Trying the newest few from %s', all: 'Getting new documents from %s', resume: 'Continuing %s',
  verify: 'Checking the files saved from %s', diagnose: 'Making a support report on %s',
  record: 'Recording your steps on %s', rename: 'Previewing new names for %s', rename_apply: 'Renaming files from %s',
  review_names: 'Renaming receipts from %s'};

// -- where an account stands, in words ---------------------------------------------
// Each state gets one chip, one sentence and one next step. Nothing here
// says an account is signed in, since nothing short of a run knows that.
const NEEDS = ['stopped', 'attention', 'unreadable', 'overdue', 'due', 'gap'];
const FRESH = ['never', 'not_started'];
function groupOf(r) { return NEEDS.includes(r.state) ? 'needs' : FRESH.includes(r.state) ? 'new' : 'ok'; }
// Whether a stopped account is carried on with Continue. Not after a Resume
// that stopped because no run read the list to its end, since only a run
// that lists carries on from that, and Continue would stop there again (#124).
function continues(r) { return r.state === 'stopped' && r.last_outcome !== 'unlisted'; }
function present(r) {
  const n = noun(r), latest = when(r.newest);
  // The panel's own log first, then the time the app last wrote its run
  // summary, which a run from a terminal leaves too.
  const lastAt = r.last_run && r.last_run.ended ? when(r.last_run.ended) : when(r.checked);
  const every = CADENCE[r.cadence] || '';
  const usual = (age, cls, chip) => ({
    chip: {cls, text: chip},
    say: 'Newest ' + n + ' is ' + latest + ', ' + many(age, 'day') + ' ago.' +
      (every ? ' ' + r.provider + ' usually sends one ' + every + '.' : ''),
    act: {label: 'Get new', run: 'all', primary: true}});
  if (!r.runnable) return {chip: {cls: 'bad', text: 'Will not run'}, say: 'Its folder does not match a provider PaperPull ships.', act: {label: 'Open', nav: true}};
  if (r.needs_setup) return {chip: {cls: 'bad', text: 'Needs setup'}, say: 'Run setup-all in the PaperPull folder, then reload this page.', act: {label: 'Open', nav: true}};
  switch (r.state) {
    case 'stopped': {
      const again = Boolean(r.last_run && r.last_run.redownload);
      const why = {closed: 'was stopped partway, by Stop or by closing its page', interrupted: 'was interrupted',
                   failed: 'ended with a problem'}[r.last_outcome] || 'stopped before it finished';
      // Restore is a desktop dialog. Where it is not offered, a stopped
      // restore's row opens the account instead of a button that does nothing.
      const restore = SERVER || inSample() ? {label: 'Open', nav: true}
        : {label: 'Restore the rest', dialog: 'restore', primary: true};
      if (!continues(r)) return {chip: {cls: 'info', text: 'Stopped partway'},
        say: 'The last run' + (lastAt ? ' on ' + lastAt : '') + ' stopped because ' + whose(r.provider) + ' list was not read ' +
          'to its end, and Continue carries on only from what is listed. Get new reads the list again. Nothing was lost.',
        act: {label: 'Get new', run: 'all', primary: true}};
      return {chip: {cls: 'info', text: 'Stopped partway'},
        say: (again ? 'The restore' : 'The last run') + (lastAt ? ' on ' + lastAt : '') + ' ' + why + '. Nothing was lost.',
        act: again ? restore : {label: 'Continue', run: 'resume', primary: true}};
    }
    case 'nostatus':
      return {chip: {cls: 'plain', text: 'Status not read'},
        say: 'PaperPull could not read how current this archive is. Getting new is still safe.',
        act: {label: 'Get new', run: 'all'}};
    case 'attention': {
      const res = (r.last_run && r.last_run.result) || {};
      const bits = [];
      const named = Math.min(res.name_review || 0, res.manual_review || 0);
      const aside = (res.manual_review || 0) - named;
      if (named) bits.push(many(named, n) + ' saved under a name to review');
      if (aside) bits.push(many(aside, n) + ' set aside for you to check');
      if (res.wrong_document) bits.push(res.wrong_document + ' refused as the wrong document');
      if (res.alike) bits.push(many(res.alike, n) + ' left unsaved, sharing a type and date');
      if (res.failed) bits.push(res.failed + ' failed');
      if (res.validation_failures) bits.push(many(res.validation_failures, 'PDF') + ' that did not check out');
      return {chip: {cls: 'due', text: 'Needs a look'},
        say: 'The last run' + (lastAt ? ' on ' + lastAt : '') + ' left ' + (bits.join(', ') || 'something to check') + '.',
        act: {label: 'See what to check', nav: true}};
    }
    case 'unreadable':
      return {chip: {cls: 'bad', text: "Can't read its records"},
        say: 'Its progress.json could not be read, so nothing new is listed until it is repaired or restored from its Backups folder.',
        act: {label: 'Open', nav: true}};
    case 'overdue': return usual(r.age_days, 'bad', 'Overdue');
    case 'due': return usual(r.age_days, 'due', 'New one likely');
    case 'gap': {
      const g = r.gaps[0] || {};
      const more = r.gaps.length > 1 ? ' ' + many(r.gaps.length - 1, 'more gap') + ' on its page.' : '';
      return {chip: {cls: 'gap', text: 'Possible gap'},
        say: many(g.missing || 1, n) + ' look missing between ' + when(g.after) + ' and ' + when(g.before) + '.' + more,
        act: {label: 'Look for them', run: 'all', scope: {year: '', start: String(g.after || '').slice(0, 10),
              end: String(g.before || '').slice(0, 10)}}};
    }
    case 'never':
      return {chip: {cls: 'plain', text: 'Nothing saved yet'},
        say: 'PaperPull has listed what ' + r.provider + ' offers and saved none of it yet.',
        act: {label: 'Get new', run: 'all', primary: true}};
    case 'not_started':
      return {chip: {cls: 'plain', text: 'Not started'},
        say: 'Sign in once and PaperPull saves every ' + n + ' ' + r.provider + ' keeps online.',
        act: {label: 'Start', nav: true, primary: true}};
    case 'unknown':
      return {chip: {cls: 'plain', text: 'No schedule yet'},
        say: many(r.documents, n) + (latest ? ', newest ' + latest : '') + '. Too few to know how often ' + r.provider + ' sends one.',
        act: {label: 'Get new', run: 'all'}};
    case 'ongoing':
      return {chip: {cls: 'ok', text: lastAt ? 'Checked ' + lastAt : 'Ready'},
        say: many(r.documents, n) + (latest ? ' · newest ' + latest : ''),
        act: {label: 'Get new', run: 'all'}};
    default:
      return {chip: {cls: 'ok', text: 'Up to date'},
        say: many(r.documents, n) + (latest ? ' · newest ' + latest : '') + (lastAt ? ' · checked ' + lastAt : ''),
        act: {label: 'Get new', run: 'all'}};
  }
}
function ours(r) { return RUN.state === 'running' && RUN.app === r.app && RUN.account === r.account; }

// -- the views ---------------------------------------------------------------------
const VIEWS = ['welcome', 'home', 'account', 'run', 'sheets', 'names', 'settings'];
function parseRoute() {
  const h = decodeURIComponent((location.hash || '').replace(/^#\/?/, ''));
  const parts = h.split('/');
  if (parts[0] === 'a' && parts.length >= 3) return {view: 'account', app: parts[1], account: parts.slice(2).join('/')};
  if (VIEWS.includes(parts[0])) return {view: parts[0]};
  if (parts[0] === 'add') return {view: 'welcome', add: true};
  return {view: 'home'};
}
function accountHash(r) { return '#/a/' + encodeURIComponent(r.app) + '/' + encodeURIComponent(r.account); }
function route() {
  if (!META) return;
  closeMenus();
  const want = parseRoute();
  const empty = !Object.keys(META.apps).length;
  if (empty && !['welcome', 'settings'].includes(want.view)) { want.view = 'welcome'; want.add = false; }
  Object.assign(ROUTE, {view: want.view, app: want.app || '', account: want.account || ''});
  const changed = VIEW !== want.view;
  VIEW = want.view;
  for (const v of VIEWS) $('view-' + v).hidden = v !== VIEW;
  for (const a of document.querySelectorAll('[data-nav]')) {
    const on = a.dataset.nav === (VIEW === 'account' || VIEW === 'run' ? 'home' : VIEW);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  $('mainnav').hidden = empty;
  if (VIEW === 'welcome') openWelcome(want.add && !empty);
  else if (VIEW === 'home') renderHome();
  else if (VIEW === 'account') renderAccount();
  else if (VIEW === 'run') renderRun();
  else if (VIEW === 'sheets') openSheets();
  else if (VIEW === 'names') openNames();
  else if (VIEW === 'settings') renderSettings();
  renderRunbar();
  if (changed) {
    const h = document.querySelector('#view-' + VIEW + ' h1');
    if (h) { h.setAttribute('tabindex', '-1'); h.focus({preventScroll: true}); }
    window.scrollTo(0, 0);
  }
}
window.addEventListener('hashchange', route);
function renderAll() {
  if (VIEW === 'home') renderHome();
  else if (VIEW === 'account') renderAccount();
  else if (VIEW === 'run') renderRun();
  renderRunbar();
}

function notice(text, tone) {
  $('noticetext').textContent = text;
  $('notice').className = 'notice' + (tone ? ' ' + tone : '');
  $('notice').hidden = !text;
}

async function load() {
  if (!META) {
    $('view-home').hidden = false;
    $('h-body').innerHTML = '<p class="muted" role="status">Reading your accounts…</p>';
  }
  try { META = await getJSON('/api/apps'); }
  catch (e) { notice('Could not reach the control panel. ' + e.message, 'warn'); return; }
  $('samplebar').hidden = !inSample();
  $('serverbadge').hidden = !SERVER;
  if (SERVER && $('paperlesspill')) $('paperlesspill').hidden = !(META.server && META.server.paperless);
  // A host that cannot give Chrome its sandbox opens no sign-in window, so
  // the panel says why at the top of every page (#110).
  const sandbox = (SERVER && META.server && META.server.sandbox) || '';
  $('sandboxtext').textContent = sandbox;
  $('sandboxbar').hidden = !sandbox;
  const fresh = Object.keys(META.refreshed || {});
  if (fresh.length) {
    notice("Updated to this version's code, " + fresh.join(', ') +
           ". The old files are in each folder's Backups.", '');
  }
  await loadAccounts();
  route();
}
async function loadAccounts() {
  let d;
  try { d = await getJSON('/api/accounts'); }
  catch (e) { ROWS = ROWS || []; notice('Could not read the accounts. ' + e.message, 'warn'); return; }
  ROWS = d.accounts || [];
  // Without the status reader no row can say how current it is, and saying
  // so beats every account looking new.
  if (d.status_available === false) {
    notice("This copy of PaperPull could not load its status reader (tools/status.py), so how current each " +
           'archive is cannot be shown. Getting new documents still works.', 'warn');
  }
}

// -- every account -------------------------------------------------------------------
function queueTargets() {
  return (ROWS || []).filter(r => r.runnable && !r.needs_setup && !r.running && (
    (r.state === 'stopped' && !(r.last_run && r.last_run.redownload)) ||
    ['overdue', 'due', 'gap', 'never'].includes(r.state)));
}
function rowHTML(r) {
  const p = present(r);
  let chip = '<span class="chip ' + p.chip.cls + '">' + esc(p.chip.text) + '</span>';
  let say = '<div class="say">' + esc(p.say) + '</div>';
  let act = actButton(r, p.act);
  if (r.running) {
    if (ours(r)) {
      chip = '<span class="chip info">Getting new now</span>';
      say = '<div class="progress"><span class="bar"><span style="width:' + runPercent() + '%"></span></span>' +
        '<span class="small muted">' + esc(runStateText()) + '</span></div>';
      act = '<a class="btn btn-s" href="#/run">Watch</a>';
    } else {
      chip = '<span class="chip info">Running in another tab</span>';
      say = '<div class="say">' + esc(ACTION_WORDS[r.running.action] || 'A run') + ' is going in another tab or window.</div>';
      act = '';
    }
  }
  return '<div class="acct" data-key="' + esc(keyOf(r)) + '">' + mono(r) +
    '<div class="who"><a href="' + accountHash(r) + '">' + esc(r.provider) + '</a><div class="sub">' + esc(subOf(r)) + '</div></div>' +
    '<div class="what">' + chip + say + '</div>' +
    '<div class="do">' + act + '<span class="menu-wrap"><button type="button" class="ib" data-do="menu" data-key="' +
    esc(keyOf(r)) + '" aria-haspopup="menu" aria-expanded="false" aria-label="More for ' + esc(r.provider) +
    (whoOf(r) ? ', ' + esc(whoOf(r)) : '') + '">' + DOTS + '</button></span></div></div>';
}
function actButton(r, act) {
  if (!act) return '';
  const cls = 'btn ' + (act.primary ? 'btn-p' : 'btn-s') + ' starts';
  if (act.nav) return '<a class="btn ' + (act.primary ? 'btn-p' : 'btn-s') + '" href="' + accountHash(r) + '">' + esc(act.label) + '</a>';
  if (act.dialog) return '<button type="button" class="' + cls + '" data-do="restore" data-key="' + esc(keyOf(r)) + '">' + esc(act.label) + '</button>';
  const scope = act.scope ? ' data-start="' + esc(act.scope.start) + '" data-end="' + esc(act.scope.end) + '"' : '';
  return '<button type="button" class="' + cls + '" data-do="run" data-action="' + act.run + '" data-key="' +
    esc(keyOf(r)) + '"' + scope + '>' + esc(act.label) + '</button>';
}
function renderHome() {
  const body = $('h-body');
  $('addlink').hidden = inSample();
  if (!ROWS) { body.innerHTML = '<p class="muted">Reading your accounts…</p>'; return; }
  const n = ROWS.length;
  $('h-sub').textContent = n ? many(n, 'account') + ' · checked against how often each provider sends a document' : '';
  const groups = {needs: [], ok: [], new: []};
  for (const r of ROWS) groups[groupOf(r)].push(r);
  let html = '';
  const targets = queueTargets();
  if (targets.length) {
    const names = targets.map(r => r.provider + (whoOf(r) ? ' (' + whoOf(r) + ')' : ''));
    html += '<section class="card summary" aria-label="Summary"><div class="icon due">' + sv(P.download, 24) + '</div>' +
      '<div class="text"><p class="big">' + esc(many(targets.length, 'account')) + ' may have something new</p>' +
      '<p class="muted">' + esc(names.slice(0, 5).join(', ') + (names.length > 5 ? ' and ' + (names.length - 5) + ' more' : '')) +
      '. Nothing is ever downloaded twice, so getting new is always safe.</p></div>' +
      (targets.length > 1 ? '<button type="button" class="btn btn-p starts" data-do="queue">Get new for all ' +
        targets.length + ', one by one</button>' :
        actButton(targets[0], {label: 'Get new', run: continues(targets[0]) ? 'resume' : 'all', primary: true,
                               scope: present(targets[0]).act.scope})) + '</section>';
  } else if (n && !groups.needs.length && !groups.ok.length) {
    html += '<section class="card summary" aria-label="Summary"><div class="icon due">' + sv(P.lock, 24) + '</div>' +
      '<div class="text"><p class="big">Next, sign in to your first provider</p><p class="muted">Open one below and press ' +
      'Open sign-in window. You sign in yourself, and PaperPull then saves what that provider keeps online.</p></div></section>';
  } else if (n && !groups.needs.length) {
    html += '<section class="card summary" aria-label="Summary"><div class="icon ok">' + sv(P.check, 24, 2.4) + '</div>' +
      '<div class="text"><p class="big">Everything is up to date</p><p class="muted">Nothing is past its usual date. ' +
      'Getting new is still safe at any time.</p></div></section>';
  }
  const section = (title, list) => list.length ? '<h2 class="section-title">' + title + '</h2><div class="card list">' +
    list.map(rowHTML).join('') + '</div>' : '';
  html += section('Needs a look', groups.needs) + section('Up to date', groups.ok) + section('Not started', groups.new);
  html += '<p class="hint">' + (inSample() ? 'This is the sample archive. ' : '') + 'Saved in <span class="mono">' +
    esc(META.apps_root) + '</span>' + (!SERVER && !inSample() ? ' · <a href="#/settings">Change in Settings</a>' : '') + '</p>';
  body.innerHTML = html;
  lockStarts();
}

// -- one account ------------------------------------------------------------------
function scopeSaved() {
  let s = {};
  try { s = JSON.parse(store.get('scope') || '{}') || {}; } catch (e) { s = {}; }
  const by = s.by || (s.year ? 'year' : (s.start || s.end) ? 'range' : 'all');
  return {by, year: s.year || '', start: s.start || '', end: s.end || ''};
}
function scopeValues() {
  const by = (document.querySelector('input[name=dates]:checked') || {}).value || 'all';
  const year = $('year') ? $('year').value : '', start = $('start') ? $('start').value : '', end = $('end') ? $('end').value : '';
  if (by === 'year') return {year, start: '', end: ''};
  if (by === 'range') return {year: '', start, end};
  return {year: '', start: '', end: ''};
}
function onScope() {
  const by = (document.querySelector('input[name=dates]:checked') || {}).value || 'all';
  $('yearbox').hidden = by !== 'year';
  $('rangebox').hidden = by !== 'range';
  const s = scopeValues();
  let text;
  if (by === 'year') text = 'Only ' + s.year + '. Years outside it are skipped where the site has a year picker.';
  else if (by === 'range') text = (s.start || 'the beginning') + ' to ' + (s.end || 'today') + '. Years outside that are skipped where the site has a year picker.';
  else text = 'Every year. Slower on sites with a year picker, and the only way Accounts sees the whole archive.';
  $('scopehint').textContent = text;
  store.set('scope', JSON.stringify({by, year: $('year').value, start: $('start').value, end: $('end').value}));
}
function yearOptions(selected) {
  const now = new Date().getFullYear();
  let html = '';
  for (let y = now; y >= now - 15; y--) html += '<option' + (String(y) === String(selected) ? ' selected' : '') + '>' + y + '</option>';
  return html;
}
function renderAccount() {
  const r = rowFor(ROUTE.app, ROUTE.account);
  const body = $('a-body');
  if (!r) {
    $('a-crumb').textContent = ROUTE.app;
    body.innerHTML = '<div class="card pad"><h1>That account is not here</h1><p class="muted" style="margin-top:6px">' +
      'It may have been removed. <a href="#/">Back to accounts</a></p></div>';
    return;
  }
  $('a-crumb').textContent = r.provider + (whoOf(r) ? ' · ' + whoOf(r) : '');
  const p = present(r);
  const saved = scopeSaved();
  const again = r.state === 'stopped' && Boolean(r.last_run && r.last_run.redownload);
  const stoppedHere = continues(r) && !again;
  let html = '<div class="head" style="align-items:center">' + mono(r, true) +
    '<div><h1 id="a-title" tabindex="-1">' + esc(r.provider) + '</h1><p>' + esc(subOf(r)) + ' · ' +
    esc(many(r.documents, noun(r))) + ' saved</p></div><div class="row-actions">' +
    (!SERVER && !inSample() ? '<button type="button" class="btn btn-s" data-do="reveal" data-key="' + esc(keyOf(r)) + '">' +
      sv(P.folder) + 'Open folder</button>' : '') +
    '<span class="menu-wrap"><button type="button" class="btn btn-s" data-do="menu" data-key="' + esc(keyOf(r)) +
    '" aria-haspopup="menu" aria-expanded="false">' + DOTS + 'More</button></span></div></div>';
  if (r.needs_setup) html += '<p class="callout warn" style="margin-bottom:20px">This provider is not set up yet. Run setup-all in the PaperPull folder, then reload this page.</p>';
  if (!r.runnable) html += '<p class="callout warn" style="margin-bottom:20px">This folder does not match a provider PaperPull ships, so it will not run. Its folder must hold exactly one provider script whose name is one PaperPull ships.</p>';
  const band = {stopped: 'info', attention: 'attention', unreadable: 'bad', overdue: 'bad', due: 'due', gap: 'gap', current: 'ok'}[r.state] || '';
  const loginSay = SERVER
    ? 'Opens ' + whose(r.provider) + " sign-in page in the sign-in window, docked beside this page. You type your password there and PaperPull never sees it. Leave it signed in while documents download."
    : 'Opens ' + r.provider + ' in its own browser window. You type your password there and PaperPull never sees it. Leave the window open while documents download.';
  html += '<div class="cols"><div class="main-col"><section class="card" aria-labelledby="getdocs">' +
    '<div class="band ' + band + '"><span class="chip ' + p.chip.cls + '">' + esc(p.chip.text) + '</span><span class="say">' +
    esc(p.say) + '</span>' + (stoppedHere ? '<button type="button" class="btn btn-p starts" data-do="run" data-action="resume" data-key="' +
    esc(keyOf(r)) + '">' + PLAY + 'Continue where it stopped</button>' : '') +
    (again && !SERVER && !inSample() ? '<button type="button" class="btn btn-p starts" data-do="restore" data-key="' + esc(keyOf(r)) + '">Restore the rest</button>' : '') +
    '</div>' + gapList(r) +
    '<div class="steps"><h2 id="getdocs" style="margin-bottom:18px">Get your documents</h2>' +
    '<div class="step"><div class="stepnum">1</div><div class="body"><h3>Sign in to ' + esc(r.provider) + '</h3><p id="steplogin">' +
    esc(loginSay) + '</p><button type="button" class="btn btn-s starts" data-do="run" data-action="login" data-key="' +
    esc(keyOf(r)) + '">' + sv(P.lock) + 'Open sign-in window</button></div></div>' +
    '<div class="step"><div class="stepnum on">2</div><div class="body"><h3>Get new documents</h3><p>Saves every ' + noun(r) +
    ' you do not have yet. Safe to repeat, nothing is ever downloaded twice, even if you deleted the PDFs after importing them elsewhere.' +
    (!SERVER ? ' To get deleted files back, use Restore deleted files under More.' : '') + '</p>' +
    '<fieldset><legend>Which dates</legend><div class="seg">' +
    '<label><input type="radio" name="dates" value="all"' + (saved.by === 'all' ? ' checked' : '') + '>All dates</label>' +
    '<label><input type="radio" name="dates" value="year"' + (saved.by === 'year' ? ' checked' : '') + '>One year</label>' +
    '<label><input type="radio" name="dates" value="range"' + (saved.by === 'range' ? ' checked' : '') + '>Between two dates</label></div>' +
    '<div class="dates"><label class="field" id="yearbox">Year<select id="year">' + yearOptions(saved.year) + '</select></label>' +
    '<span id="rangebox" class="dates" style="margin:0"><label class="field">From<input type="date" id="start" value="' + esc(saved.start) + '"></label>' +
    '<label class="field">To<input type="date" id="end" value="' + esc(saved.end) + '"></label></span></div>' +
    '<p class="hint" id="scopehint" style="margin-top:8px"></p></fieldset>' +
    '<div class="row-actions" style="margin-top:18px"><button type="button" class="btn btn-p btn-lg starts" data-do="run" data-action="all" data-key="' +
    esc(keyOf(r)) + '">' + sv(P.download, 18, 2.2) + 'Get new documents</button>' +
    '<button type="button" class="link starts" data-do="run" data-action="pilot" data-key="' + esc(keyOf(r)) + '">Try the newest few first</button>' +
    '<span class="sep-dot" aria-hidden="true">·</span>' +
    '<button type="button" class="link starts" data-do="run" data-action="discover" data-key="' + esc(keyOf(r)) + '">Only check what\'s there</button></div>' +
    '</div></div></div></section></div>';
  html += '<aside class="side-col"><section class="card pad" aria-labelledby="latest"><h2 id="latest" class="section-title">Latest documents</h2>' +
    (r.latest.length ? '<ul class="files">' + r.latest.map(f => '<li>' + sv(P.file, 16) + '<span class="nm" title="' + esc(f.name) + '">' +
      esc(f.name) + '</span></li>').join('') + '</ul>' : '<p class="hint">Nothing saved yet.</p>') +
    (!SERVER && !inSample() && r.latest.length ? '<p style="margin-top:8px"><button type="button" class="link" data-do="reveal" data-key="' +
      esc(keyOf(r)) + '">See all ' + esc(many(r.documents, noun(r))) + ' in the folder</button></p>' : '') + '</section>' +
    '<section class="card pad" aria-labelledby="recent"><h2 id="recent" class="section-title">Recent runs</h2>' +
    (r.runs.length ? '<ul class="runs">' + r.runs.map(runLine).join('') + '</ul>' :
      '<p class="hint">Runs started here are listed once there are some.</p>') + '</section></aside></div>';
  $('a-body').innerHTML = html;
  for (const el of document.querySelectorAll('input[name=dates]')) el.addEventListener('change', onScope);
  for (const id of ['year', 'start', 'end']) $(id).addEventListener('change', onScope);
  onScope();
  lockStarts();
}
function gapList(r) {
  // Shown whenever there are any, since an account that is also past its
  // usual date can be missing periods in the middle too.
  if (!r.gaps.length) return '';
  return '<div style="padding:16px 24px 0"><p class="small" style="font-weight:700;margin-bottom:6px">Possible gaps</p>' +
    '<p class="hint" style="margin-bottom:8px">A run that looks current can still be missing periods in the middle.</p><ul class="runs">' +
    r.gaps.map(g => '<li><span style="flex:1">' + esc(when(g.after)) + ' to ' + esc(when(g.before)) + ' · ' + esc(String(g.missing)) +
      ' missing' + (g.labels && g.labels[0] ? ' · ' + esc(g.count > 1 ? g.count + ' series, including ' + g.labels[0] : g.labels[0]) : '') +
      '</span><button type="button" class="link starts" data-do="run" data-action="all" data-key="' + esc(keyOf(r)) +
      '" data-start="' + esc(String(g.after).slice(0, 10)) + '" data-end="' + esc(String(g.before).slice(0, 10)) + '">Look for them</button></li>').join('') +
    '</ul></div>';
}
function runLine(e) {
  const res = e.result || {};
  let said;
  if (e.closed) said = 'stopped when its page closed';
  else if (e.exit_code === 130) said = 'interrupted';
  else if (e.exit_code && e.exit_code !== 0) said = 'ended with a problem';
  else if (res.stopped) said = 'stopped partway';
  else if (savedCount(res, e.saved)) said = many(savedCount(res, e.saved), 'new file');
  else said = ['pilot', 'all', 'resume'].includes(e.action) ? 'nothing new' : 'done';
  return '<li><span class="when">' + esc(when(e.ended || e.started)) + '</span><span>' + esc(ACTION_WORDS[e.action] || e.action) +
    (e.redownload ? ' (restore)' : '') + ', ' + esc(said) + '</span></li>';
}

// -- the More menu ------------------------------------------------------------------
function closeMenus() {
  for (const m of document.querySelectorAll('.menu')) m.remove();
  for (const b of document.querySelectorAll('[aria-expanded="true"][data-do="menu"]')) b.setAttribute('aria-expanded', 'false');
}
function menuItem(doIt, key, ico, title, line, disabled) {
  return '<button type="button" role="menuitem" class="mi' + (doIt === 'run' || doIt === 'record' || doIt === 'support' ||
    doIt === 'rename' || doIt === 'review' || doIt === 'restore' ? ' starts' : '') + '" data-do="' + doIt + '" data-key="' + esc(key) + '"' +
    (disabled ? ' disabled' : '') + (doIt === 'run' ? ' data-action="verify"' : '') + '>' + sv(ico, 20) +
    '<span><b>' + esc(title) + '</b><span>' + esc(line) + '</span></span></button>';
}
function openMenu(btn) {
  const open = btn.getAttribute('aria-expanded') === 'true';
  closeMenus();
  if (open) return;
  const r = rowByKey(btn.dataset.key);
  if (!r) return;
  const k = keyOf(r), sample = inSample();
  let html = '<div class="menu" role="menu" aria-label="More for ' + esc(r.provider) + '">';
  if (VIEW !== 'account') html += menuItem('nav', k, P.chevron, 'Open ' + r.provider, 'Sign in, choose dates and see recent runs');
  html += '<div class="grp">Your files</div>';
  if (!SERVER) html += menuItem('restore', k, P.restore, 'Restore deleted files', 'Fetch again the PDFs you deleted, for dates you choose', sample);
  html += menuItem('rename', k, P.pencil, 'Rename existing files', 'Match them to your File names setting, with a preview first');
  // Only a receipt provider has Review Names (META.apps[app].reviews_names).
  if (META.apps[r.app] && META.apps[r.app].reviews_names) {
    html += menuItem('review', k, P.tag, 'Review names', 'Give a better name to receipts PaperPull was unsure of', sample);
  }
  html += menuItem('run', k, P.shield, 'Check saved files', 'Re-check every PDF already saved. Downloads nothing');
  if (!SERVER && !sample) html += menuItem('reveal', k, P.folder, 'Open folder', 'Where ' + whose(r.provider) + ' files are saved');
  html += '<div class="rule"></div><div class="grp">Get help</div>' +
    menuItem('support', k, P.report, 'Make a support report', "Reads " + whose(r.provider) + " page and saves a file with no account details, to attach to an issue") +
    menuItem('record', k, P.record, 'Record steps for support', 'Watches while you click your way to a document. Downloads nothing and records no typing');
  if (!sample) {
    html += '<div class="rule"></div><div class="grp">This provider</div>' +
      menuItem('person', k, P.person, 'Add another person', 'Their own sign-in window, folder and download history') +
      menuItem('remove', k, P.box, 'Remove from PaperPull', 'Moves its folder to Removed. Nothing is deleted');
  }
  html += '</div>';
  btn.insertAdjacentHTML('afterend', html);
  btn.setAttribute('aria-expanded', 'true');
  lockStarts();
  const first = btn.parentNode.querySelector('.mi:not(:disabled)');
  if (first) first.focus();
}
document.addEventListener('click', e => {
  if (!e.target.closest('.menu-wrap')) closeMenus();
  if (!e.target.closest('.parts')) closePicklist();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeMenus(); closePicklist(); }
});

// -- runs -------------------------------------------------------------------------
const RUN = {state: 'idle'};
let es = null;
let recordingApp = null, recordingAccount = 'primary';
let failureApp = null, failureAccount = 'primary';
const RUN_ACTIONS_WITH_DATES = ['pilot', 'all', 'resume', 'discover'];
// Said when a run that downloads again ends before it is through. Continue
// never downloads again, so it would skip the rest and call the run done,
// and the same range again would fetch again what this run restored.
const AGAIN_LEFT = 'Continue will not download again, and restoring the same dates again ' +
  'fetches again what this run already restored, so choose the dates that are left';
// Only a year, or both ends of a range. One date alone is open at the
// other end, and From 1990 or To today is a whole history.
function againScoped(s) { return Boolean(s.year || (s.start && s.end)); }

function lockStarts() {
  const busy = RUN.state === 'running';
  for (const b of document.querySelectorAll('.starts')) {
    if (busy) { if (!b.disabled) { b.disabled = true; b.dataset.runlock = '1'; } }
    else if (b.dataset.runlock) { b.disabled = false; delete b.dataset.runlock; }
  }
}
// A run that downloads again is asked for in a POST body, so the choice
// and the agreement arrive as true and false, never as text in an address.
// EventSource can only GET, so this reads the same stream with fetch and
// hands its events to the same handlers.
function postRun(body, url) {
  const stop = new AbortController(), on = {};
  const src = { onmessage: null, onerror: null, refused: '',
                addEventListener(name, fn) { on[name] = fn; }, close() { stop.abort(); } };
  const lost = () => { if (!stop.signal.aborted && src.onerror) src.onerror(); };
  (async () => {
    let r;
    try {
      r = await fetch(url || '/api/run', { method: 'POST', signal: stop.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    } catch (e) { lost(); return; }
    if (!r.ok) {
      try { const d = await r.json(); if (typeof d.detail === 'string') src.refused = d.detail; } catch (e) { /* not JSON */ }
      src.refused = src.refused || 'the panel refused this run';
      lost(); return;
    }
    const reader = r.body.getReader(), text = new TextDecoder();
    let buf = '', ended = false;
    try {
      for (;;) {
        const part = await reader.read();
        if (part.done) break;
        buf += text.decode(part.value, { stream: true });
        let cut;
        while ((cut = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          let name = 'message';
          const data = [];
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) name = line.slice(6).trim();
            else if (line.startsWith('data:')) data.push(line.slice(line.startsWith('data: ') ? 6 : 5));
          }
          if (name === 'done') ended = true;
          const e = { data: data.join('\n') };
          if (name === 'message') { if (src.onmessage) src.onmessage(e); }
          else if (on[name]) on[name](e);
        }
      }
    } catch (e) { lost(); return; }
    if (!ended) lost();
  })();
  return src;
}
// opts: scope to use instead of the page's dates, redownload for Restore,
// stay to keep the person where they are, sink, an element its output also
// goes to, onDone, told the exit code, and queue, for a run of a round.
function startRun(r, action, opts) {
  opts = opts || {};
  if (RUN.state === 'running') {
    notice('Wait for the run on ' + RUN.provider + ' to finish first.', 'warn');
    return false;
  }
  const app = r.app, account = r.account;
  const s = opts.scope || (RUN_ACTIONS_WITH_DATES.includes(action) && VIEW === 'account' ? scopeValues()
                           : {year: '', start: '', end: ''});
  if (!s.year && s.start && s.end && s.start > s.end) { notice('The From date is after the To date.', 'warn'); return false; }
  const again = opts.redownload === true;
  if (again && (SERVER || !againScoped(s) || !(META.redownload_actions || []).includes(action))) return false;
  Object.assign(RUN, {state: 'running', app, account, provider: r.provider, kind: r.kind, who: whoOf(r), action,
    scope: s, again, lines: [], result: null, saved: null, code: null, refused: '', found: null, step: 0, total: 0,
    connected: false, now: '', failure: false, startedAt: new Date(), endedAt: null, outcome: null,
    queue: Boolean(opts.queue), onDone: opts.onDone || null, sink: opts.sink ? $(opts.sink) : null, stopped: false});
  if (RUN.sink) { if (!opts.append) RUN.sink.textContent = ''; RUN.sink.hidden = false; }
  const q = new URLSearchParams({ app, account, action });
  if (s.year) q.set('year', s.year); else { if (s.start) q.set('start', s.start); if (s.end) q.set('end', s.end); }
  // A recording waits for the person, so it needs a way to say when. The
  // app and person it belongs to are kept here rather than read back when
  // Stop is pressed, so a Stop can never reach another folder. A second
  // person's recording waits in their own folder.
  recordingApp = (action === 'record') ? app : null;
  recordingAccount = account;
  // Review Names carries what the person typed, in a body to its own address.
  es = opts.review ? postRun({ app, account, answers: opts.review }, '/api/review-names/apply')
     : again ? postRun(Object.assign({ app, account, action, redownload: true, confirmed: true },
                                     Object.fromEntries(q.entries())))
     : new EventSource(`/api/run?${q.toString()}`);
  es.addEventListener('result', e => { try { RUN.result = JSON.parse(e.data); } catch (x) { RUN.result = null; } });
  es.addEventListener('saved', e => { try { RUN.saved = JSON.parse(e.data); } catch (x) { RUN.saved = []; } });
  es.onmessage = e => onLine(e.data);
  es.addEventListener('done', e => finishRun(e.data));
  es.onerror = () => {
    if (!es) return;
    const why = es.refused || '';
    es.close(); es = null;
    recordingApp = null;
    finishRun(RUN.stopped ? 'stopped' : 'lost', why);
  };
  if (SERVER && action === 'login') openDock(r.provider);
  closeMenus();
  notice('', '');
  if (!opts.stay && location.hash !== '#/run') location.hash = '#/run'; else renderAll();
  lockStarts();
  return true;
}
let paintQueued = false;
function onLine(text) {
  RUN.lines.push(text);
  if (RUN.sink) { RUN.sink.textContent += text + '\n'; RUN.sink.scrollTop = RUN.sink.scrollHeight; }
  const t = text.trim();
  let m;
  if ((m = /Documents known:\s*(\d+)/i.exec(t))) RUN.found = +m[1];
  if ((m = /^\[(\d+)\/(\d+)\]/.exec(t))) { RUN.step = +m[1]; RUN.total = +m[2]; }
  else if ((m = /Downloading (\d+) document/i.exec(t))) { RUN.total = +m[1]; }
  if (/^Connected\b/.test(t)) RUN.connected = true;
  if (t && !t.startsWith('$ ')) RUN.now = t;
  if (!paintQueued) {
    paintQueued = true;
    requestAnimationFrame(() => { paintQueued = false; paintRunLive(); renderRunbar(); });
  }
}
function runPercent() {
  if (RUN.total) return Math.max(4, Math.min(100, Math.round(100 * RUN.step / RUN.total)));
  return RUN.found != null ? 12 : 4;
}
function runStateText() {
  if (RUN.state !== 'running') return RUN.outcome ? RUN.outcome.title : '';
  if (RUN.total) return 'Saving ' + RUN.step + ' of ' + RUN.total;
  if (RUN.found != null) return 'Found ' + many(RUN.found, noun(RUN));
  if (RUN.connected) return 'Connected';
  return 'Starting';
}
function stopRun() {
  if (!es) return;
  RUN.stopped = true;
  // Closing the stream ends the run on the panel's side, the same as
  // closing the tab. Nothing already saved is lost.
  es.close(); es = null;
  recordingApp = null;
  finishRun('stopped');
}
async function stopRecording() {
  if (!recordingApp) return;
  const b = $('stoprec');
  if (b) { b.disabled = true; b.textContent = 'Stopping…'; }
  try {
    await fetch('/api/record/stop', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: recordingApp, account: recordingAccount }) });
  } catch (e) { /* the run's own end says what happened */ }
}
function finishRun(code, refused) {
  if (RUN.state !== 'running') return;
  if (es) { es.close(); es = null; }
  recordingApp = null;
  Object.assign(RUN, {state: 'done', code: String(code), refused: refused || '', endedAt: new Date()});
  if (RUN.refused && RUN.sink) RUN.sink.textContent += RUN.refused + '\n';
  RUN.outcome = runOutcome();
  if (RUN.again && !RUN.outcome.clean && RUN.sink) RUN.sink.textContent += AGAIN_LEFT + '.\n';
  const done = RUN.onDone;
  RUN.onDone = null;
  if (RUN.code !== '0' || (RUN.result && RUN.result.attention)) checkFailure(RUN.app, RUN.account);
  if (done) done(RUN.code);
  if (RUN.queue && QUEUE) queueStep();
  loadAccounts().then(renderAll);
  renderAll();
  lockStarts();
}
// How many files a run saved. Its own result counts them, and the names
// read from its new-this-run.txt can be fewer (one name for two files of
// that name, 500 at most) or none when the list could not be read, so a run
// that saved documents never reads as having saved nothing (#103).
function savedCount(res, saved) {
  const counted = res && Number.isInteger(res.new_files) && res.new_files > 0 ? res.new_files : 0;
  return Math.max(counted, Array.isArray(saved) ? saved.length : 0);
}
// What a run came to, in a title, a sentence and a tone.
function runOutcome() {
  const res = RUN.result, code = RUN.code, n = noun(RUN), saved = RUN.saved || [];
  const fresh = savedCount(res, saved);
  const who = RUN.provider;
  // Documents of one type on one date are listed on every run and never
  // saved, since a row cannot be bound to either. They are said here, but
  // never make a run one that needs a look, which it would then be for good.
  const alike = res && res.alike ? ' ' + many(res.alike, n) + ' that share a type and a date with another ' +
    'could not be told apart and were left unsaved. Take any you need from ' + whose(who) + ' own page.' : '';
  // Continue picks up a run that downloads. A Discover that stopped is
  // pressed again, since it was asked only to see what is there, and a
  // restore that stopped is chosen again for the dates it did not reach.
  const downloads = ['pilot', 'all', 'resume'].includes(RUN.action) && !RUN.again;
  const recheck = RUN.action === 'discover';
  const next = RUN.again ? AGAIN_LEFT : downloads ? 'Continue picks up where it stopped'
    : recheck ? 'Check again when you are ready' : 'Nothing was lost';
  if (RUN.refused) return {tone: 'bad', title: 'This run did not start', say: RUN.refused, clean: false};
  if (code === 'stopped') return {tone: 'info', title: 'You stopped this run',
    say: 'Nothing already saved is lost. ' + next + '.', clean: false, resume: downloads, recheck};
  if (code === 'lost') return {tone: 'bad', title: 'Lost touch with this run',
    say: 'Progress is saved. Check the account. ' + next + '.', clean: false, resume: downloads, recheck};
  if (code === '130') return {tone: 'info', title: 'Interrupted, progress saved',
    say: next + '.', clean: false, resume: downloads, recheck};
  if (code !== '0') return {tone: 'bad', title: 'This run ended with a problem',
    say: 'It exited with code ' + code + '. Progress is saved, and the technical details below say what happened. ' +
      next + '.', clean: false, resume: downloads, recheck};
  // A Resume with nothing more to carry on with, since no run read the list
  // to its end. Continue would stop here again, so the next step is a run
  // that reads the list (#124).
  if (res && res.stopped && res.list_not_read) return {tone: 'info', title: 'Stopped before finishing',
    say: whose(who) + " list was not read to its end, so there was nothing more to carry on with. Get new documents " +
      'reads the list again. Nothing already saved is lost.', clean: false, relist: true};
  if (res && res.stopped) return {tone: 'info', title: 'Stopped before finishing',
    say: RUN.again ? AGAIN_LEFT + '.' : who + ' may have signed you out partway. Nothing is lost. Sign in again, then ' +
      (downloads ? 'continue.' : recheck ? 'check again.' : 'run it again.'),
    clean: false, resume: downloads, recheck, signin: true};
  if (res && res.attention) {
    // A receipt saved under a name the app was unsure of is counted as one
    // to review, and its file is where it belongs. Only the rest sit in
    // the Manual Review folder, which was all this ever said.
    const named = Math.min(res.name_review || 0, res.manual_review || 0);
    const aside = (res.manual_review || 0) - named;
    const details = [];
    if (res.wrong_document) details.push(`${res.wrong_document} refused as the wrong document`);
    if (named) details.push(`${named} saved under a name to review`);
    if (aside) details.push(`${aside} set aside`);
    if (res.failed) details.push(`${res.failed} failed`);
    if (res.validation_failures) details.push(`${res.validation_failures} PDF validation failures`);
    const says = [];
    if (named) says.push((named === 1 ? 'A receipt was' : named + ' receipts were') + ' saved under a name ' +
      'PaperPull was unsure of. Review names gives each a better one.');
    // An invoice that failed its check is put aside in Manual Review and
    // counted in validation_failures, while its order may count as one
    // saved under a name to review.
    const asideToo = aside > 0 || (res.validation_failures || 0) > 0;
    if (asideToo) says.push('A document set aside sits in the Manual Review folder, where PaperPull kept it ' +
      'rather than file it under the wrong name.');
    if (!says.length) says.push('The technical details below say what happened.');
    return {tone: 'warn', title: fresh ? many(fresh, 'new ' + n) + ' saved, some need a look' : 'Finished, needs attention',
      say: 'Finished, needs attention (' + details.join(', ') + '). ' + says.join(' ') + alike, clean: true, attention: true,
      names: named > 0, aside: asideToo};
  }
  if (res && ['pilot', 'all', 'resume'].includes(RUN.action)) {
    return fresh ? {tone: 'ok', title: many(fresh, 'new ' + n) + ' saved',
      say: alike ? 'Finished.' + alike : 'Finished, no issues reported.', clean: true}
      : {tone: 'ok', title: 'Nothing new', say: 'Everything ' + (alike ? 'else ' : '') + who +
        ' lists in these dates is already saved.' + alike, clean: true};
  }
  if (inSample()) return {tone: 'ok', title: 'Nothing to run in the sample', say: RUN.lines.filter(Boolean).join(' '), clean: true};
  const plain = {
    login: ['Sign-in window opened', SERVER ? 'Sign in to ' + who + ' in the sign-in window, then get new documents.'
      : 'Sign in to ' + who + ' in the window that opened and leave it open, then get new documents.'],
    discover: ['Checked ' + who, RUN.found != null ? many(RUN.found, n) + ' listed. Nothing was downloaded.' : 'Nothing was downloaded. The technical details list what was found.'],
    verify: ['Saved files checked', 'The technical details list each file.'],
    diagnose: ['Support report saved', 'It is in the Diagnostics folder of ' + who + '. Attach the file whose name starts with survey- to an issue.'],
    record: ['Recording saved', 'It is in the Diagnostics folder of ' + who + ', ready to attach to an issue.'],
    rename: ['Rename preview ready', 'Nothing has been changed. The technical details list every file that would change.'],
    rename_apply: ['Files renamed', 'The technical details list each file.'],
    review_names: rvRenamed(RUN.lines) ? ['Receipts renamed', 'The technical details list each file.']
      : ['Nothing was renamed', 'The technical details say why.'],
  }[RUN.action];
  if (plain) return {tone: 'ok', title: plain[0], say: plain[1] + (RUN.action === 'discover' ? alike : ''), clean: true};
  if (res) return {tone: 'ok', title: 'Finished, no issues reported', say: '', clean: true};
  return {tone: 'warn', title: 'Finished, check the details', say: 'No run summary came back, so read the technical details.', clean: true};
}
// The failure file is the account's own, a second person's in their folder.
async function checkFailure(app, account) {
  try {
    const q = new URLSearchParams({app, account});
    const r = await fetch('/api/failure/latest?' + q.toString());
    const d = await r.json();
    if (d.found && RUN.app === app && RUN.account === account) {
      failureApp = app; failureAccount = account; RUN.failure = true; renderAll();
    }
  } catch (e) { /* nothing to offer */ }
}
// A file the server hands the browser. Asked first, so a file that is not
// there is said here rather than the page going to an error.
async function fetchDownload(url) {
  let r;
  try { r = await fetch(url); } catch (e) { notice('The server could not be reached.', 'warn'); return; }
  if (!r.ok) {
    let d = {};
    try { d = await r.json(); } catch (e) { /* not JSON */ }
    notice((d && typeof d.detail === 'string' && d.detail) || 'That did not download.', 'warn');
    return;
  }
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(r.headers.get('content-disposition') || '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob());
  a.download = m ? decodeURIComponent(m[1]) : 'download';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}
async function revealFailure() {
  if (!failureApp) return;
  if (SERVER) {
    await fetchDownload('/api/failure/download?' + new URLSearchParams({app: failureApp, account: failureAccount}).toString());
    return;
  }
  try {
    await fetch('/api/failure/reveal', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: failureApp, account: failureAccount }) });
  } catch (e) { /* the file is still there */ }
}
function renderRun() {
  const body = $('r-body');
  renderQueueList();
  if (RUN.state === 'idle') {
    $('r-crumbs').innerHTML = '<a href="#/">Accounts</a>';
    body.innerHTML = '<div class="card pad"><h1 id="r-title">No run yet</h1><p class="muted" style="margin-top:6px">Start one from an account. ' +
      '<a href="#/">Back to accounts</a></p></div>';
    return;
  }
  const r = rowFor(RUN.app, RUN.account);
  const back = r ? '<a href="' + accountHash(r) + '">' + esc(RUN.provider) + '</a>' : esc(RUN.provider);
  const scope = RUN.scope.year ? ' · ' + RUN.scope.year : (RUN.scope.start || RUN.scope.end) ?
    ' · ' + (RUN.scope.start || '…') + ' to ' + (RUN.scope.end || '…') : (RUN_ACTIONS_WITH_DATES.includes(RUN.action) ? ' · all dates' : '');
  $('r-crumbs').innerHTML = '<a href="#/">Accounts</a>' + sv(P.chevron, 16) + back + sv(P.chevron, 16) +
    '<span aria-current="page">' + esc((RUN.again ? 'Restore deleted files' : ACTION_WORDS[RUN.action] || RUN.action) + ' · started ' +
    RUN.startedAt.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}) + scope) + '</span>';
  let html;
  if (RUN.state === 'running') {
    html = '<section class="card" aria-labelledby="r-title"><div class="outcome"><span class="spinner" aria-hidden="true"></span>' +
      '<div class="text"><h1 id="r-title" tabindex="-1">' + esc((RUN.again ? 'Restoring files from %s' : ACTION_DOING[RUN.action] || '%s').replace('%s', RUN.provider)) + '</h1>' +
      '<p>' + (RUN.action === 'record' ? 'Click your way to a document in ' + esc(whose(RUN.provider)) + ' window, then stop the recording here.'
        : 'Usually takes a minute or two.') + '</p></div></div>' +
      '<div class="live"><div class="now"><b id="r-state" role="status">' + esc(runStateText()) + '</b>' +
      '<span class="bar wide' + (RUN.total ? '' : ' indeterminate') + '" id="r-bar"><span style="width:' + runPercent() + '%"></span></span></div>' +
      '<p class="hint mono" id="r-now">' + esc(RUN.now) + '</p></div>' +
      '<div class="keepopen"><p>Keep this page open. Closing it stops the run. Anything already saved stays saved, and the next run picks up the rest. ' +
      'You can look at other pages meanwhile.</p>' +
      (RUN.action === 'record' ? '<button type="button" class="btn btn-p" id="stoprec" data-do="stop-recording">' + STOP + 'Stop recording</button>'
        : '<button type="button" class="btn btn-s" data-do="stop-run">' + STOP + 'Stop</button>') + '</div>' +
      techDetails(false) + '</section>';
  } else {
    const o = RUN.outcome || {tone: 'info', title: '', say: ''};
    const ico = {ok: sv(P.check, 28, 2.6), info: PAUSE, warn: sv(P.alert, 26), bad: sv(P.alert, 26)}[o.tone];
    const key = r ? esc(keyOf(r)) : '';
    html = '<section class="card" aria-labelledby="r-title"><div class="outcome"><div class="icon ' + o.tone + '">' + ico + '</div>' +
      '<div class="text"><h1 id="r-title" tabindex="-1">' + esc(o.title) + '</h1>' + (o.say ? '<p id="statustext">' + esc(o.say) + '</p>' : '') + '</div>' +
      '<div class="row-actions">' + (r ? '<a class="btn btn-s" href="' + accountHash(r) + '">Back to ' + esc(RUN.provider) + '</a>' : '') +
      '<a class="btn btn-s" href="#/">All accounts</a></div></div>';
    if ((RUN.saved || []).length) {
      html += '<ul class="saved" aria-label="Saved this run">' + RUN.saved.slice(0, 50).map(n => '<li>' + sv(P.check, 16, 3) +
        '<span>' + esc(n) + '</span></li>').join('') + (RUN.saved.length > 50 ? '<li>and ' + (RUN.saved.length - 50) + ' more</li>' : '') + '</ul>';
    }
    if (r && (o.resume || o.recheck || o.signin || o.relist)) {
      html += '<ol class="nextsteps">' +
        '<li><div class="stepnum">1</div><div class="body"><b>Sign in to ' + esc(RUN.provider) + ' again</b><span>In its window, or open a new one</span></div>' +
        '<button type="button" class="btn btn-s starts" data-do="run" data-action="login" data-key="' + key + '">Open sign-in window</button></li>' +
        (o.resume ? '<li><div class="stepnum on">2</div><div class="body"><b>Continue where it stopped</b><span>Picks up what is left, without asking again for what is already saved</span></div>' +
          '<button type="button" class="btn btn-p starts" data-do="run" data-action="resume" data-key="' + key + '">' + PLAY + 'Continue</button></li>' : '') +
        (o.relist ? '<li><div class="stepnum on">2</div><div class="body"><b>Get new documents</b><span>Reads ' + esc(whose(RUN.provider)) +
          ' list again, then saves what you do not have yet</span></div>' +
          '<button type="button" class="btn btn-p starts" data-do="run" data-action="all" data-key="' + key + '">' + PLAY +
          'Get new documents</button></li>' : '') +
        (o.recheck ? '<li><div class="stepnum on">2</div><div class="body"><b>Check again</b><span>Lists what ' + esc(RUN.provider) +
          ' has once more. Nothing is downloaded</span></div><button type="button" class="btn btn-p starts" data-do="run" data-action="discover" data-key="' +
          key + '">Check again</button></li>' : '') + '</ol>';
    }
    if (r && ['diagnose', 'record'].includes(RUN.action) && o.clean) {
      // The server's folder is on the server, so the file comes to the browser.
      html += '<div class="keepopen"><p>The file holds counts and states and no text from your account.</p>' +
        (SERVER ? '<button type="button" class="btn btn-s" data-do="report-download" data-key="' + key + '" data-action="' +
          esc(RUN.action) + '">' + sv(P.download) + 'Download the file to attach</button></div>'
          : '<button type="button" class="btn btn-s" data-do="reveal" data-key="' + key + '">' + sv(P.folder) + 'Open folder</button></div>');
    }
    html += techDetails(!o.clean && !RUN.failure) + '</section>';
    if (o.attention && r) {
      const folder = !SERVER && !inSample() && (o.aside || !o.names);
      // On the server what was set aside comes to the browser in one zip.
      const aside = SERVER && o.aside;
      html += '<section class="callout warn" style="margin-top:20px"><div class="text"><h2>' +
        (o.names && !o.aside ? 'Some receipts need a better name' : 'Some documents need a look') + '</h2>' +
        '<p>' + esc(o.say) + '</p>' + (o.names || folder || aside ? '<div class="row-actions">' +
        (o.names ? '<button type="button" class="btn btn-s" data-do="review" data-key="' + key + '">' + sv(P.tag) +
          'Review names</button>' : '') +
        (folder ? '<button type="button" class="btn btn-s" data-do="reveal" data-key="' + key + '">' +
          sv(P.folder) + 'Open ' + esc(whose(RUN.provider)) + ' folder</button>' : '') +
        (aside ? '<button type="button" class="btn btn-s" data-do="aside-download" data-key="' + key + '">' +
          sv(P.download) + 'Download what was set aside</button>' : '') + '</div>' : '') + '</div></section>';
    }
    if (RUN.failure) {
      html += '<section class="callout plain" id="failnote" style="margin-top:20px">' + sv(P.report, 22) + '<div class="text">' +
        '<h2>A file about what went wrong</h2><p>This run wrote a file about what went wrong. It holds counts and states and no text ' +
        'from your account. Read it, then attach it to this provider\'s issue.</p>' +
        '<button type="button" class="btn btn-s" id="failreveal" data-do="failure">' + (SERVER ? 'Download the file to attach' : 'Show the file to attach') +
        '</button></div></section>';
    }
  }
  html += queueHeld();
  body.innerHTML = html;
  lockStarts();
}
function techDetails(open) {
  return '<details class="tech"' + (open ? ' open' : '') + '><summary>Technical details <span>· the full output, ' +
    many(RUN.lines.length, 'line') + '</span></summary><pre class="log" id="console">' + esc(RUN.lines.join('\n')) + '</pre></details>';
}
function paintRunLive() {
  if (VIEW !== 'run' || RUN.state !== 'running') return;
  const st = $('r-state'), bar = $('r-bar'), now = $('r-now'), con = $('console');
  if (st) st.textContent = runStateText();
  if (bar) { bar.classList.toggle('indeterminate', !RUN.total); bar.firstChild.style.width = runPercent() + '%'; }
  if (now) now.textContent = RUN.now;
  if (con) {
    const stick = con.scrollTop + con.clientHeight >= con.scrollHeight - 8;
    con.textContent = RUN.lines.join('\n');
    if (stick) con.scrollTop = con.scrollHeight;
    const sum = con.parentNode.querySelector('summary span');
    if (sum) sum.textContent = '· the full output, ' + many(RUN.lines.length, 'line');
  }
}
function renderRunbar() {
  const show = RUN.state === 'running' && VIEW !== 'run';
  $('runbar').hidden = !show;
  if (!show) return;
  $('rb-what').textContent = RUN.provider + (RUN.who ? ' · ' + RUN.who : '');
  $('rb-state').textContent = (RUN.again ? 'Restoring' : ACTION_WORDS[RUN.action]) + ' · ' + runStateText();
  const bar = $('rb-bar');
  bar.classList.toggle('indeterminate', !RUN.total);
  bar.firstChild.style.width = runPercent() + '%';
}

// -- a round of runs, Get new for all -----------------------------------------------
let QUEUE = null;
function startQueue() {
  const items = queueTargets().map(r => {
    const p = present(r);
    return {key: keyOf(r), provider: r.provider + (whoOf(r) ? ' (' + whoOf(r) + ')' : ''),
            action: continues(r) ? 'resume' : 'all', scope: p.act.scope || {year: '', start: '', end: ''}, said: ''};
  });
  if (!items.length) return;
  QUEUE = {items, i: 0, held: false, finished: false};
  queueRun();
}
function queueRun() {
  if (!QUEUE) return;
  QUEUE.held = false;
  while (QUEUE.i < QUEUE.items.length && !rowByKey(QUEUE.items[QUEUE.i].key)) {
    QUEUE.items[QUEUE.i].said = 'gone';
    QUEUE.i++;
  }
  if (QUEUE.i >= QUEUE.items.length) { QUEUE.finished = true; renderRun(); return; }
  const it = QUEUE.items[QUEUE.i];
  // Another run started in the moment before this one could, and only
  // one goes at a time, so the round waits for the person instead of
  // saying the next starts on its own when it never would.
  if (!startRun(rowByKey(it.key), it.action, {scope: it.scope, queue: true})) {
    QUEUE.held = true;
    renderAll();
  }
}
function queueStep() {
  const it = QUEUE.items[QUEUE.i];
  const o = RUN.outcome || {};
  if (o.clean) {
    it.said = o.attention ? 'held' : 'done';
    QUEUE.i++;
    if (QUEUE.i >= QUEUE.items.length) QUEUE.finished = true;
    else setTimeout(queueRun, 800);
  } else {
    it.said = 'held';
    QUEUE.held = true;
    // A Continue with nothing more to carry on with would only stop the same
    // way again, so trying it again reads the list, with no dates set (#124).
    // What the pause says follows this run, so a retry that stops for a
    // sign-in says that.
    it.relist = Boolean(o.relist);
    if (o.relist) Object.assign(it, {action: 'all', scope: {year: '', start: '', end: ''}});
  }
}
function renderQueueList() {
  const list = $('r-queue');
  if (!QUEUE) { list.hidden = true; return; }
  list.hidden = false;
  list.innerHTML = QUEUE.items.map((it, i) => {
    const cls = i === QUEUE.i && !QUEUE.finished ? (QUEUE.held ? 'held' : 'now') : it.said === 'done' ? 'done' : it.said === 'held' ? 'held' : '';
    return '<li class="' + cls + '">' + (i + 1) + '. ' + esc(it.provider) + '</li>';
  }).join('');
}
function queueHeld() {
  if (!QUEUE) return '';
  if (QUEUE.finished) {
    const done = QUEUE.items.filter(it => it.said === 'done').length;
    return '<section class="callout info" style="margin-top:20px"><div class="text"><h2>The round is finished</h2><p>' +
      esc(done + ' of ' + QUEUE.items.length + ' finished cleanly.') + '</p><div class="row-actions">' +
      '<a class="btn btn-s" href="#/" data-do="queue-end">Back to accounts</a></div></div></section>';
  }
  if (!QUEUE.held) return '<p class="hint" style="margin-top:12px">' + esc('Account ' + (QUEUE.i + 1) + ' of ' + QUEUE.items.length +
    '. The next starts on its own when this one finishes.') + '</p>';
  const it = QUEUE.items[QUEUE.i];
  return '<section class="callout warn" style="margin-top:20px"><div class="text"><h2>Paused at ' + esc(it.provider) + '</h2>' +
    '<p>' + esc(it.relist ? 'This one had nothing more to carry on with, since its list was not read to its end, so the round ' +
      'waits for you. Try it again to read the list first, or move on.' :
      'This one did not finish, so the round waits for you. Sign in again and try it once more, or move on.') + '</p>' +
    '<div class="row-actions"><button type="button" class="btn btn-s starts" data-do="run" data-action="login" data-key="' + esc(it.key) +
    '">Open sign-in window</button><button type="button" class="btn btn-p starts" data-do="queue-retry">Try it again</button>' +
    '<button type="button" class="btn btn-s starts" data-do="queue-skip">Skip to the next</button>' +
    '<button type="button" class="link" data-do="queue-end">Stop the round</button></div></div></section>';
}

// -- dialogs ----------------------------------------------------------------------
let DLG_ROW = null;
function openRestore(r) {
  if (SERVER || inSample()) return;
  DLG_ROW = r;
  $('rs-title').textContent = 'Restore deleted files from ' + r.provider;
  $('rs-year').innerHTML = yearOptions(new Date().getFullYear() - 1);
  for (const el of document.querySelectorAll('input[name=rsby]')) el.checked = el.value === 'year';
  for (const el of document.querySelectorAll('input[name=rshow]')) el.checked = el.value === 'all';
  $('rs-start').value = ''; $('rs-end').value = '';
  $('rs-err').hidden = true;
  rsBy();
  $('dlg-restore').showModal();
}
function rsBy() {
  const by = document.querySelector('input[name=rsby]:checked').value;
  $('rs-yearbox').hidden = by !== 'year';
  $('rs-range').hidden = by !== 'range';
  rsLabel();
}
function rsScope() {
  const by = document.querySelector('input[name=rsby]:checked').value;
  return by === 'year' ? {year: $('rs-year').value, start: '', end: ''} : {year: '', start: $('rs-start').value, end: $('rs-end').value};
}
function rsLabel() {
  const s = rsScope();
  $('rs-go').textContent = 'Restore missing files' + (s.year ? ' from ' + s.year : '');
}
function rsGo() {
  const s = rsScope(), how = document.querySelector('input[name=rshow]:checked').value;
  const err = $('rs-err');
  if (!againScoped(s)) { err.textContent = 'Choose a year, or both a From and a To date.'; err.hidden = false; return; }
  if (s.start && s.end && s.start > s.end) { err.textContent = 'The From date is after the To date.'; err.hidden = false; return; }
  // Closed only once the run has started, so a refusal is said here.
  if (!startRun(DLG_ROW, how, {scope: s, redownload: true})) {
    err.textContent = 'Wait for the run going now to finish first.'; err.hidden = false; return;
  }
  $('dlg-restore').close();
}
function openPerson(r) {
  DLG_ROW = r;
  $('ps-title').textContent = 'Add another person to ' + r.provider;
  $('ps-label').value = ''; $('ps-owner').value = ''; $('ps-err').hidden = true;
  $('dlg-person').showModal();
}
async function psGo() {
  const label = $('ps-label').value.trim(), owner = $('ps-owner').value.trim(), err = $('ps-err');
  if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(label)) {
    err.textContent = 'Use lowercase letters, digits, - or _, starting with a letter or digit.'; err.hidden = false; return;
  }
  let d;
  try { d = await postJSON('/api/account', {app: DLG_ROW.app, label, owner}); }
  catch (e) { err.textContent = e.message; err.hidden = false; return; }
  $('dlg-person').close();
  // The whole list again, so the new person is in every list the page
  // keeps, the renames File names offers among them.
  await load();
  const r = rowFor(DLG_ROW.app, d.account);
  location.hash = r ? accountHash(r) : '#/';
  notice('Added ' + (d.owner || d.account) + ' to ' + DLG_ROW.provider + '. Their documents go to ' + d.output_dir +
    '. Open the sign-in window and sign in as them, then get new documents.', 'ok');
}
function openRemove(r) {
  DLG_ROW = r;
  const people = (ROWS || []).filter(x => x.app === r.app).length;
  $('rm-title').textContent = 'Remove ' + r.provider + ' from PaperPull?';
  $('rm-lead').textContent = '"' + r.app + '" will no longer appear here' + (people > 1 ? ', for all ' + people + ' people on it.' : '.');
  $('rm-err').hidden = true;
  $('dlg-remove').showModal();
}
async function rmGo() {
  let d;
  try { d = await postJSON('/api/remove', {app: DLG_ROW.app}); }
  catch (e) { $('rm-err').textContent = e.message; $('rm-err').hidden = false; return; }
  $('dlg-remove').close();
  const kept = [];
  if (d.pdfs) kept.push(many(d.pdfs, 'PDF'));
  if (d.history) kept.push('a history of ' + many(d.history, 'document'));
  if (d.profile) kept.push('a signed-in browser profile');
  await load();
  location.hash = '#/';
  notice('Removed "' + d.app + '". Its folder was moved to ' + d.moved_to + (kept.length ? ', still holding ' + kept.join(', ') : '') +
    '. Nothing was deleted, and moving it back restores the provider.', 'ok');
}
let RN_PREVIEWED = false;
function openRename(r) {
  DLG_ROW = r;
  RN_PREVIEWED = false;
  $('rn-title').textContent = 'Rename existing files from ' + r.provider;
  $('rn-log').hidden = true; $('rn-log').textContent = '';
  $('rn-apply').disabled = true; $('rn-prev').disabled = false;
  $('rn-state').textContent = '';
  $('dlg-rename').showModal();
}
function rnRun(apply) {
  if (apply && !RN_PREVIEWED) return;
  $('rn-state').textContent = apply ? 'Renaming…' : 'Previewing…';
  $('rn-prev').disabled = true; $('rn-apply').disabled = true;
  const started = startRun(DLG_ROW, apply ? 'rename_apply' : 'rename', {stay: true, sink: 'rn-log', onDone: code => {
    if (code !== '0') { $('rn-state').textContent = 'That did not finish. The output above says why.'; $('rn-prev').disabled = false; return; }
    if (apply) { $('rn-state').textContent = 'Renamed. The list above names each file.'; return; }
    RN_PREVIEWED = true;
    $('rn-apply').disabled = false; $('rn-prev').disabled = false;
    $('rn-state').textContent = 'Preview done. Nothing has been changed. Read it above, then rename.';
  }});
  if (!started) {
    $('rn-state').textContent = 'Wait for the run going now to finish first.';
    $('rn-prev').disabled = false; $('rn-apply').disabled = !RN_PREVIEWED;
  }
}

// Review Names. The receipts the app was unsure how to name are listed by
// the app itself (/api/review-names), a person types a better summary for
// any of them, and the app renames those (/api/review-names/apply). A blank
// box keeps its name, as Enter does in the console version.
let RV = null;
function openReview(r) {
  DLG_ROW = r;
  RV = {row: r, receipts: []};
  $('rv-title').textContent = 'Review names from ' + r.provider;
  $('rv-list').innerHTML = ''; $('rv-list').hidden = true;
  $('rv-log').hidden = true; $('rv-log').textContent = '';
  $('rv-go').disabled = true;
  $('rv-paperless').hidden = !(SERVER && META.server && META.server.paperless);
  $('dlg-review').showModal();
  rvLoad('');
}
async function rvLoad(before) {
  const rv = RV;
  $('rv-state').textContent = before + 'Finding the receipts to review…';
  let d;
  try { d = await postJSON('/api/review-names', {app: rv.row.app, account: rv.row.account}); }
  catch (e) { if (RV === rv) $('rv-state').textContent = before + e.message; return; }
  if (RV !== rv) return;
  rv.receipts = Array.isArray(d.receipts) ? d.receipts : [];
  // What the app said about rows it left out, without its own count line.
  const said = (d.said || []).filter(t => !/need review\.$|need name review\.$/.test(t)).join(' ');
  const n = rv.receipts.length;
  $('rv-state').textContent = before + (n ? many(n, 'receipt') + ' waiting for a better name.'
    : 'No receipts are waiting for a better name.') + (said ? ' ' + said : '');
  $('rv-list').innerHTML = rv.receipts.map((x, i) => {
    const items = Array.isArray(x.items) ? x.items.filter(Boolean) : [];
    const head = [x.date, x.number ? '#' + x.number : ''].filter(Boolean).join(' · ');
    return '<div class="rv-item"><div class="rv-file">' + esc(x.file || '') + '</div>' +
      '<div class="hint">' + esc(head) + (items.length ? ' · ' + esc(items.join('; ')) : '') + '</div>' +
      '<input type="text" autocomplete="off" maxlength="120" data-i="' + i + '" placeholder="Leave blank to keep this name" ' +
      'aria-label="' + esc('New summary for ' + (x.file || 'this receipt')) + '"></div>';
  }).join('');
  $('rv-list').hidden = !n;
  $('rv-go').disabled = !n;
}
// How many receipts a review's output says it renamed. It ends with code 0
// when it renamed none, every name having gone stale or failed, so the
// output is what tells.
function rvRenamed(lines) {
  return (lines || []).filter(t => /^\s*Renamed (->|to) /.test(t)).length;
}
// Words that ask to keep a name, never a new one. The box once read
// "Keep this name", and typed in it renamed receipts "Keep This Name". The
// same list as KEEP_WORDS in core renaming.py, which reads them again.
const KEEP_WORDS = new Set(['keep', 'keep it', 'keep this', 'keep name', 'keep the name', 'keep this name',
  'keep its name', 'keep same', 'keep the same', 'keep the same name', 'same',
  'same name', 'the same', 'no change', 'unchanged', 'leave it', 'leave as is',
  'leave blank', 'leave it blank', 'leave blank to keep this name']);
function keepsName(text) {
  return KEEP_WORDS.has(String(text || '').toLowerCase().replace(/[^a-z ]+/g, ' ').split(/\s+/).filter(Boolean).join(' '));
}
function rvAnswers() {
  return [...$('rv-list').querySelectorAll('input[data-i]')].map(inp => {
    const x = RV.receipts[+inp.dataset.i];
    return {id: String(x.id || ''), number: String(x.number || ''), summary: inp.value.trim()};
  }).filter(a => a.id && a.summary && !keepsName(a.summary));
}
function rvGo() {
  if (!RV) return;
  const answers = rvAnswers();
  if (!answers.length) { $('rv-state').textContent = 'Type a new summary for at least one receipt first.'; return; }
  $('rv-go').disabled = true;
  $('rv-state').textContent = 'Renaming…';
  const rv = RV;
  const started = startRun(rv.row, 'review_names', {stay: true, sink: 'rv-log', review: answers, onDone: code => {
    if (RV !== rv) return;
    if (code !== '0') {
      $('rv-state').textContent = 'That did not finish. The output below says why.';
      $('rv-go').disabled = false;
      return;
    }
    const n = rvRenamed(RUN.lines);
    rvLoad(n ? 'Renamed ' + many(n, 'receipt') + '. The output below names each file. '
      : 'Nothing was renamed. The output below says why. ');
  }});
  if (!started) { $('rv-state').textContent = 'Wait for the run going now to finish first.'; $('rv-go').disabled = false; }
}
// Enter in a box goes to the next one. In a form of method dialog it would
// close the dialog, and everything typed with it.
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.closest || !e.target.closest('#rv-list')) return;
  e.preventDefault();
  const boxes = [...$('rv-list').querySelectorAll('input[data-i]')];
  const next = boxes[boxes.indexOf(e.target) + 1];
  (next || $('rv-go')).focus();
});

// -- the server's sign-in window ---------------------------------------------------
function openDock(provider) {
  if (!SERVER) return;
  $('dock-title').textContent = provider ? provider + ' sign-in window' : 'Sign-in window';
  $('dock-say').textContent = 'Sign in below the way you would on ' + (provider ? whose(provider) : "the provider's") +
    ' own site. Your password goes to the provider, never to PaperPull. Leave it signed in when you are done.';
  // Opened again unless noVNC shows the screen now, since one that closed
  // after going unused asks for the password once its page is opened.
  const frame = $('dockframe');
  let live = false;
  try { live = frame.contentDocument.documentElement.classList.contains('noVNC_connected'); } catch (e) { live = false; }
  if (!live) {
    frame.src = '/screen/novnc/vnc.html?autoconnect=1&reconnect=1&resize=scale&path=screen/websockify';
  }
  document.body.classList.add('docked');
  $('dock').querySelector('[data-do=dock-close]').focus();
}
function closeDock() { document.body.classList.remove('docked'); }

// -- choosing providers, first and later --------------------------------------------
const W = {step: 1, add: false, picked: new Set(), group: 'all', search: ''};
// The groups in gui/providers.json, in the order the chips show them.
const GROUP_ORDER = ['banks', 'shopping', 'bills', 'pay', 'investing', 'loans', 'insurance'];
async function openWelcome(add) {
  W.add = add;
  W.step = add ? 2 : W.step || 1;
  if (!add) W.picked = W.picked || new Set();
  if (add) W.picked = new Set();
  $('w-aside').hidden = add;
  $('existinglink').hidden = SERVER;
  $('movelink').hidden = inSample();
  if (!PROVIDERS || add) {
    try { PROVIDERS = await getJSON('/api/providers'); } catch (e) { PROVIDERS = {providers: [], templates: false}; }
  }
  if (!$('newroot').value) $('newroot').value = (add ? META.apps_root : PROVIDERS.suggested_root) || '';
  if (add) $('newroot').value = META.apps_root || '';
  if (SERVER) {
    $('newroot').readOnly = true;
    $('serverroot').hidden = false; $('rootsay').hidden = true;
    $('newrootlabel').textContent = 'Where your documents go';
  }
  wShow();
  renderTiles();
}
function wShow() {
  for (const n of [1, 2, 3]) $('w-step' + n).hidden = W.step !== n;
  const names = W.add ? ['Choose providers', 'Your name'] : ['Where to save', 'Choose providers', 'Your name'];
  const at = W.add ? W.step - 1 : W.step;
  $('w-stepper').innerHTML = names.map((t, i) => (i ? '<li class="line" aria-hidden="true"></li>' : '') +
    '<li' + (i + 1 === at ? ' aria-current="step"' : i + 1 < at ? ' class="done"' : '') + '><span class="n">' +
    (i + 1 < at ? sv(P.check, 14, 3) : i + 1) + '</span><b>' + esc(t) + '</b></li>').join('');
  $('w-title2').textContent = W.add ? 'Add providers' : 'Which providers do you use?';
  const n = W.picked.size;
  $('w-create').textContent = 'Set up ' + (n ? many(n, 'provider') : '');
}
function renderTiles() {
  const box = $('providers');
  if (!PROVIDERS || !PROVIDERS.templates) { box.textContent = 'No provider templates are available in this copy.'; return; }
  const all = PROVIDERS.providers.filter(p => !W.add || !p.installed);
  if (!all.length) { box.textContent = 'Every provider is already set up.'; return; }
  const groups = {};
  for (const g of GROUP_ORDER) for (const p of all) if (p.group === g) groups[g] = p.category || g;
  for (const p of all) if (p.group && !groups[p.group]) groups[p.group] = p.category || p.group;
  $('w-groups').innerHTML = '<button type="button" class="fchip" data-do="w-group" data-group="all" aria-pressed="' + (W.group === 'all') + '">All ' +
    all.length + '</button>' + Object.entries(groups).map(([g, name]) => '<button type="button" class="fchip" data-do="w-group" data-group="' +
    esc(g) + '" aria-pressed="' + (W.group === g) + '">' + esc(name) + '</button>').join('');
  const q = W.search.trim().toLowerCase();
  const shown = all.filter(p => (W.group === 'all' || p.group === W.group) &&
    (!q || [p.provider, p.slug, p.documents, p.category].some(t => String(t || '').toLowerCase().includes(q))));
  box.innerHTML = shown.map(p => '<label class="ptile"><input type="checkbox" value="' + esc(p.slug) + '"' +
    (p.installed ? ' disabled checked' : W.picked.has(p.slug) ? ' checked' : '') + '>' +
    '<span class="tile-mono ' + tint(p.provider) + '" aria-hidden="true">' + esc(p.provider.charAt(0)) + '</span><span><b>' + esc(p.provider) + '</b>' +
    (p.documents ? '<span class="gets">' + esc(p.documents) + '</span>' : '') +
    (p.tested === false ? '<span class="tag warn">Not run on a real account yet</span>' : '') +
    (p.note ? '<span class="tag plain">' + esc(p.note) + '</span>' : '') +
    (p.installed ? '<span class="tag plain">Already set up</span>' : '') +
    '</span><span class="check" aria-hidden="true">' + sv(P.check, 12, 4) + '</span></label>').join('') ||
    '<p class="muted">No provider matches that. Try another word.</p>';
  $('w-count').textContent = shown.length === all.length ? many(all.length, 'provider') : 'Showing ' + shown.length + ' of ' + all.length;
  wPicked();
}
function wPicked() {
  const names = (PROVIDERS.providers || []).filter(p => W.picked.has(p.slug)).map(p => p.provider);
  $('w-picked-n').textContent = names.length ? names.length + ' chosen' : 'None chosen yet';
  $('w-picked').textContent = names.join(', ');
  $('w-next2').disabled = !names.length;
  wShow();
}
async function wCreate() {
  const root = $('newroot').value.trim();
  const picked = [...W.picked];
  const owner = $('owner').value.trim();
  $('newmsg').textContent = '';
  if (!root) { $('newmsg').textContent = 'Choose a folder first.'; return; }
  if (!picked.length) { $('newmsg').textContent = 'Choose at least one provider.'; return; }
  $('newmsg').textContent = 'Setting up…';
  let r;
  try {
    r = await fetch('/api/create', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({root, providers: picked, owner})});
  } catch (e) { $('newmsg').textContent = 'Could not reach the control panel.'; return; }
  let d = {};
  try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) { $('newmsg').textContent = d.detail || 'That did not work.'; return; }
  W.picked = new Set(); W.step = 1; $('owner').value = ''; $('newmsg').textContent = '';
  PROVIDERS = null;
  await load();
  location.hash = '#/';
  const n = d.created.length;
  notice('Set up ' + many(n, 'provider') + ' in ' + d.root + '. ' +
    (d.owner ? 'Documents will be filed under ' + d.owner + '. ' : '') +
    'Next, open one and sign in when its sign-in window opens.', 'ok');
}

// -- moving to another computer (#67) ------------------------------------------------
// One box. On the welcome page of a new computer it brings a history file in,
// setting up what the file names. In Settings it writes one too.
const HX_LEAD_WELCOME =
  'Choose the history file you saved with Export history in Settings on your ' +
  'other computer. Each provider and person in it is set up here with their settings, ' +
  'and every document they already downloaded is marked as downloaded, so none of them ' +
  'is downloaded here again. No sign-in comes with the file, so you sign in to each ' +
  'provider here yourself.';
const HX_LEAD_STATUS =
  'Export history saves a file that lists each provider and person here, their settings, ' +
  'and every document each one has already downloaded. Import it on another computer, or ' +
  'on PaperPull Server, and nothing you already have is downloaded there again. It holds ' +
  'no password, no sign-in and no PDF. It does hold document titles, order numbers, totals ' +
  'and the account holders\' names, so keep it as private as your documents.';
const HX_PLAN = {'set up': 'set up here', 'add person': 'added here', 'fill in': 'already here'};
const HX_DONE = {'set up': 'set up', 'add person': 'added', 'fill in': 'filled in'};
let HX_FILE = '';
function placeMove(welcome) {
  (welcome ? $('setupmove') : $('stmove')).append($('movebox'));
  $('setupmove').hidden = !welcome;
  $('hxhead').textContent = welcome ? 'Import a history file' : 'Move to another computer';
  $('hxexportrow').hidden = welcome;
  $('hxlead').textContent = welcome ? HX_LEAD_WELCOME : HX_LEAD_STATUS;
}
function hxWelcome() { return VIEW === 'welcome'; }
function hxReset() { HX_FILE = ''; $('hxfile').value = ''; $('hximport').hidden = true; }
async function exportHistory() {
  $('hxmsg').textContent = 'Writing the file…';
  let r;
  try { r = await fetch('/api/history/export'); }
  catch (e) { $('hxmsg').textContent = 'Could not reach the control panel.'; return; }
  if (!r.ok) {
    let d = {}; try { d = await r.json(); } catch (e) { /* not JSON */ }
    $('hxmsg').textContent = d.detail || 'That did not work.'; return;
  }
  const blob = await r.blob();
  const named = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = named ? named[1] : 'PaperPull history.ppz';
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  $('hxmsg').textContent = 'Saved ' + a.download + ' with your downloads. Keep it as private as your documents.';
}
async function hxPost(url) {
  const body = {file: HX_FILE, root: hxWelcome() ? $('newroot').value.trim() : ''};
  let r;
  try {
    r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  } catch (e) { $('hxmsg').textContent = 'Could not reach the control panel.'; return null; }
  let d = {}; try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) { $('hxmsg').textContent = d.detail || 'That did not work.'; return null; }
  return d;
}
function hxTable(d, done) {
  const why = r => r.failed ? r.failed : r.action === 'skipped' ? 'skipped, ' + r.why : (done ? HX_DONE : HX_PLAN)[r.action];
  const rows = d.rows.map(r =>
    '<tr><td>' + esc(r.provider) + '</td><td>' + esc(r.account === 'primary' ? '' : r.account) +
    '</td><td>' + esc(why(r)) + '</td><td class="num">' + r.records + '</td>' +
    '<td class="num">' + r.downloaded + '</td></tr>').join('');
  return '<table class="t"><thead><tr><th>Provider</th><th>Person</th><th>Here</th>' +
    '<th class="num">Documents</th><th class="num">Downloaded</th></tr></thead><tbody>' + rows + '</tbody></table>';
}
function hxCounts(d) {
  const ok = d.rows.filter(r => r.action !== 'skipped' && !r.failed);
  const n = a => ok.filter(r => r.action === a).length;
  return {setUp: n('set up'), people: n('add person'), filled: n('fill in'),
          skipped: d.rows.length - ok.length,
          docs: ok.reduce((s, r) => s + r.downloaded, 0),
          changes: n('set up') + n('add person') + ok.reduce((s, r) => s + (r.new || 0) + (r.marked || 0), 0)};
}
function hxSaying(c, done) {
  const parts = [];
  if (c.setUp) parts.push((done ? 'set up ' : 'sets up ') + many(c.setUp, 'provider'));
  if (c.people) parts.push((done ? 'added ' : 'adds ') + many(c.people, 'person', 'people'));
  if (c.filled) parts.push((done ? 'added to ' : 'adds to ') + 'the history of ' + c.filled + ' already here');
  const said = parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts.join('');
  let s = (done ? 'Imported. It ' : 'Importing ') + said + '. ' + many(c.docs, 'document') +
    ' downloaded on the other computer ' + (done ? 'will' : 'would') + ' never be downloaded here again.';
  if (c.skipped) s += ' ' + many(c.skipped, 'line was', 'lines were') + ' skipped, as the table says.';
  return s;
}
async function planHistory() {
  const f = $('hxfile').files[0];
  HX_FILE = ''; $('hxplan').innerHTML = ''; $('hximport').hidden = true;
  $('hxmsg').textContent = '';
  if (!f) return;
  if (f.size > 12 * 1024 * 1024) { $('hxmsg').textContent = 'That file is far larger than any download history.'; return; }
  $('hxmsg').textContent = 'Reading the file…';
  try {
    const url = await new Promise((ok, no) => {
      const rd = new FileReader();
      rd.onload = () => ok(String(rd.result)); rd.onerror = () => no(rd.error);
      rd.readAsDataURL(f);
    });
    HX_FILE = url.slice(url.indexOf(',') + 1);
  } catch (e) { $('hxmsg').textContent = 'That file could not be read.'; return; }
  const d = await hxPost('/api/history/plan');
  if (!d) return;
  const c = hxCounts(d);
  $('hxplan').innerHTML = hxTable(d, false);
  if (!c.setUp && !c.people && !c.filled) { $('hxmsg').textContent = 'Nothing in that file can be imported here, as the table says.'; return; }
  if (!c.changes) { $('hxmsg').textContent = 'Everything in that file is already here, so importing it would change nothing.'; return; }
  $('hxmsg').textContent = hxSaying(c, false) + ' Nothing is downloaded now.';
  $('hximport').textContent = c.setUp || c.people ? 'Set up and import' : 'Import';
  $('hximport').hidden = false;
}
async function importHistory() {
  if (!HX_FILE) return;
  $('hximport').disabled = true;
  $('hxmsg').textContent = 'Importing…';
  const welcome = hxWelcome();
  const d = await hxPost('/api/history/import');
  $('hximport').disabled = false;
  if (!d) return;
  hxReset();
  const c = hxCounts(d);
  $('hxplan').innerHTML = hxTable(d, true);
  $('hxmsg').textContent = hxSaying(c, true);
  if (welcome) {
    placeMove(false);
    await load();
    location.hash = '#/';
    notice(hxSaying(c, true) + ' Nothing was downloaded, and no sign-in came with the file. Open each provider and sign in, ' +
      'and Get new then downloads only what is new.', 'ok');
  } else {
    // Providers set up by the import join every list, and a panel that
    // had none leaves its welcome.
    await load();
  }
}

// -- spreadsheets -------------------------------------------------------------------
// Which providers get a spreadsheet. Receipt archives have line items, so
// they are listed, each with its second-account folders folded in. Statement
// archives are not offered one, since they have documents, not purchases.
let XL_LOADED = false;
function openSheets() {
  if (!XL_LOADED) { loadExportProviders(); loadTransactionProviders(); }
}
async function loadExportProviders() {
  const sel = $('xlprovider'); sel.innerHTML = '';
  let d;
  try { d = await (await fetch('/api/export/providers')).json(); }
  catch (e) { d = {available: false, providers: []}; }
  XL_LOADED = true;
  const provs = (d.providers || []);
  sel.append(new Option('All receipt providers', ''));
  for (const p of provs) sel.append(new Option(p.provider, p.provider));
  $('xlnote').textContent = provs.length
    ? 'Receipt archives found, ' + provs.map(p => p.provider).join(', ') + '. Statement archives have no line items and are not offered.'
    : 'No receipt archive found yet. Amazon, Target, Walmart and the other receipt providers write one after a run.';
  $('xlbuild').disabled = !provs.length;
}
async function loadTransactionProviders() {
  const sel = $('txprovider'); sel.innerHTML = '';
  let d;
  try { d = await (await fetch('/api/export/transactions/providers')).json(); }
  catch (e) { d = {available: false, providers: []}; }
  const provs = d.providers || [];
  sel.append(new Option('All statement providers', ''));
  for (const p of provs) sel.append(new Option(p.provider + ' (' + p.pdfs + ' PDFs)', p.provider));
  $('txnote').textContent = provs.length ? 'Statement archives with PDFs on disk, ' + provs.map(p => p.provider).join(', ') + '.'
    : (d.reason || 'No statement PDFs on disk under this folder yet.');
  $('txbuild').disabled = !provs.length;
}
function fileDone(path, extra) {
  return '<div class="callout plain" style="padding:14px 16px">' + sv(P.file, 20) + '<div class="text"><b class="mono">' +
    esc(String(path).split(/[\\/]/).pop()) + '</b><p class="hint" style="margin:2px 0 8px">' + esc(extra) + '</p>' +
    '<button type="button" class="btn btn-s btn-sm" data-do="sheet-reveal">' + (SERVER ? 'Download' : 'Show in folder') + '</button></div></div>';
}
let txes = null;
function buildTransactions() {
  const asCsv = document.querySelector('input[name=txfmt]:checked').value === 'csv';
  if (txes) txes.close();
  const log = $('txlog'); log.textContent = '';
  $('txdetails').hidden = false; $('txstate').hidden = false; $('txdone').innerHTML = '';
  $('txnow').textContent = 'Reading statements';
  $('txbuild').disabled = true;
  const q = new URLSearchParams({provider: $('txprovider').value, csv: asCsv ? '1' : ''});
  let wrote = '';
  txes = new EventSource('/api/export/transactions?' + q.toString());
  txes.onmessage = e => {
    log.textContent += e.data + '\n'; log.scrollTop = log.scrollHeight;
    const line = e.data.trim();
    if (line && !line.startsWith('$ ')) $('txnow').textContent = line.length > 90 ? line.slice(0, 90) + '…' : line;
  };
  txes.addEventListener('result', e => { try { wrote = JSON.parse(e.data).path; } catch (x) { wrote = ''; } });
  txes.addEventListener('done', e => {
    txes.close(); txes = null;
    $('txbuild').disabled = false; $('txstate').hidden = true;
    if (e.data !== '0') { log.textContent += '(ended with code ' + e.data + ')\n'; $('txdone').innerHTML = '<p class="hint bad">That did not finish. The technical details say why.</p>'; return; }
    $('txdone').innerHTML = wrote ? fileDone(wrote, 'Made just now') : '';
  });
  txes.onerror = () => { if (txes) { txes.close(); txes = null; } $('txbuild').disabled = false; $('txstate').hidden = true; };
}
async function buildSpreadsheet() {
  const asCsv = document.querySelector('input[name=xlfmt]:checked').value === 'csv';
  $('xlbody').textContent = 'Making it…';
  let d;
  const provider = $('xlprovider').value;
  try {
    d = await (await fetch('/api/export', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({csv: asCsv, provider})})).json();
  } catch (e) { $('xlbody').textContent = 'Could not reach the control panel.'; return; }
  if (!d.ok) { $('xlbody').textContent = d.reason || 'The export failed.'; return; }
  let html = fileDone(d.path, many(d.purchases, 'item') + ' in ' + many(d.orders, 'order') + ', made just now');
  html += '<table class="t" style="margin-top:12px"><thead><tr><th>Provider</th><th class="num">Line items</th></tr></thead><tbody>';
  for (const [p, n] of Object.entries(d.providers).sort()) html += '<tr><td>' + esc(p) + '</td><td class="num">' + n + '</td></tr>';
  html += '</tbody></table>';
  if (d.openpyxl_missing) html += '<p class="hint warn" style="margin-top:8px">openpyxl is not installed here, so this is a .csv. Run <code>pip install openpyxl</code> in the panel\'s environment for an .xlsx.</p>';
  $('xlbody').innerHTML = html;
}
async function revealSpreadsheet() {
  // A server cannot open a folder on the computer the page is on, so it
  // hands the spreadsheet to the browser instead. Asked first, so a refusal,
  // a spreadsheet swapped for a link among them, is said in the panel and a
  // run streaming on this page goes on.
  if (SERVER) { await fetchDownload('/api/export/download'); return; }
  try { await fetch('/api/export/reveal', {method: 'POST'}); } catch (e) { /* the file is still there */ }
}

// -- file names (#50) ----------------------------------------------------------------
let NM = null, NM_TIMER = null, NM_PARTS = null;
const NM_SEPS = [[' ', 'space'], [' - ', 'dash'], [' -- ', 'two dashes'], ['_', 'underscore'], ['', 'nothing']];
const NM_DATES = ['yyyy-mm-dd', 'yyyymmdd', 'mm-dd-yyyy', 'dd mmm yyyy', 'mmmm d yyyy'];
const NM_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
function nmDateExample(fmt) {
  const d = new Date(), y = String(d.getFullYear()), m = d.getMonth(), day = d.getDate();
  const two = v => String(v).padStart(2, '0');
  const map = {yyyy: y, yy: y.slice(2), mmmm: NM_MONTHS[m], mmm: NM_MONTHS[m].slice(0, 3), mm: two(m + 1), m: String(m + 1), dd: two(day), d: String(day)};
  return fmt.replace(/yyyy|yy|mmmm|mmm|mm|m|dd|d/g, t => map[t]);
}
function nmLabel(f, receipts) {
  return ({date: 'Date', year: 'Year', month: 'Month', provider: 'Provider',
           owner: 'Account holder', kind: 'Document type', summary: 'Description',
           number: receipts ? 'Order number' : 'Document number', account: 'Account',
           total: 'Order total', store: 'Store', type: 'Online or in store',
           part: 'Part, like 1 of 3'})[f] || f;
}
// How many of the files already downloaded have this part, in words, so
// nobody builds a name on something this provider never gives.
function nmHowMany(f, got, n) {
  if (f === 'owner') return 'from your settings';
  if (f === 'part') return 'only on a split order';
  if (!n) return '';
  if (got >= n) return 'on every file';
  if (got === 0) return 'on none of your files';
  const pct = Math.round(100 * got / n);
  return pct >= 90 ? 'on almost every file' : 'on ' + got + ' of ' + n + ' files';
}
// A pattern as parts the page can show, or null when it says something
// they cannot, alternatives or written text, which stays editable as text.
const NM_SEG = /\[([^[\]{}\\]*)\{([a-z]+)(?::([^{}|\\]*))?\}([^[\]{}\\]*)\]|([^[\]{}\\]*)\{([a-z]+)(?::([^{}|\\]*))?\}/y;
function nmParse(pattern) {
  if (!pattern || !NM) return null;
  const segs = [];
  NM_SEG.lastIndex = 0;
  while (NM_SEG.lastIndex < pattern.length) {
    const at = NM_SEG.lastIndex;
    const m = NM_SEG.exec(pattern);
    if (!m || m.index !== at) return null;
    if (m[2]) segs.push({pre: m[1], field: m[2], fmt: m[3] || '', post: m[4], optional: true});
    else segs.push({pre: m[5], field: m[6], fmt: m[7] || '', post: '', optional: false});
  }
  if (!segs.length || segs[0].pre) return null;
  if (!segs.every(s => NM.fields.includes(s.field))) return null;
  const rest = segs.slice(1).map(s => s.pre);
  const sep = (NM_SEPS.map(s => s[0]).sort((a, b) => b.length - a.length)
    .find(c => rest.every(p => p.startsWith(c)))) ?? '';
  const mark = /^[(<["'#]*$/, close = /^[)>\]"'.]*$/;
  const parts = segs.map((s, i) => ({field: s.field, fmt: s.fmt, optional: s.optional,
    before: i ? s.pre.slice(sep.length) : '', after: s.post}));
  if (!parts.every(p => mark.test(p.before) && close.test(p.after))) return null;
  return {parts, sep: rest.length ? sep : ' '};
}
function nmBuild(parts, sep) {
  return parts.map((p, i) => {
    const body = (i ? sep : '') + p.before + '{' + p.field + (p.fmt ? ':' + p.fmt : '') + '}' + p.after;
    return p.optional ? '[' + body + ']' : body;
  }).join('');
}
function openNames() {
  const sel = $('nmapp');
  const apps = Object.keys(META.apps);
  const want = sel.value || (ROUTE.app && META.apps[ROUTE.app] ? ROUTE.app : apps[0]);
  sel.innerHTML = apps.map(a => '<option' + (a === want ? ' selected' : '') + '>' + esc(a) + '</option>').join('');
  if (!$('nmsep').options.length) {
    $('nmsep').innerHTML = NM_SEPS.map(([v, name]) => '<option value="' + esc(v) + '">' + esc(name) + ', ' +
      esc(nmDateExample('yyyy-mm-dd') + v + 'Amazon') + '</option>').join('');
    $('nmdate').innerHTML = NM_DATES.map(f => '<option value="' + f + '">' + esc(nmDateExample(f)) + '</option>').join('');
  }
  loadNaming();
}
function nmScopeValue() { return document.querySelector('input[name=nmscope]:checked').value; }
async function loadNaming() {
  const app = $('nmapp').value;
  if (!app) return;
  let d;
  try { d = await (await fetch('/api/naming?app=' + encodeURIComponent(app))).json(); }
  catch (e) { return; }
  $('nmunavail').hidden = Boolean(d.available);
  $('nmbody').hidden = !d.available;
  if (!d.available) return;
  NM = d;
  const kind = d.kind === 'receipts' ? 'receipts' : 'statements';
  $('nmsharedlabel').textContent = 'Every ' + kind + ' provider';
  $('nmownlabel').textContent = 'Only ' + d.provider;
  $('nmlead').textContent = 'Your newest ' + d.provider + ' file would be named';
  document.querySelector('input[name=nmscope][value=' + (d.own ? 'own' : 'shared') + ']').checked = true;
  $('nmpattern').value = d.own || d.shared || d.default;
  $('nmnote').textContent = '';
  nmFromText();
}
function nmFromText() {
  const parsed = nmParse($('nmpattern').value);
  NM_PARTS = parsed;
  $('nmtextonly').hidden = Boolean(parsed) || !$('nmpattern').value;
  if (parsed) {
    $('nmsep').value = parsed.sep;
    const date = parsed.parts.find(p => p.field === 'date' && p.fmt);
    if (date && NM_DATES.includes(date.fmt)) $('nmdate').value = date.fmt;
  }
  $('nmsep').disabled = $('nmdate').disabled = !parsed;
  if (!parsed && $('nmpattern').value) $('nmtext').open = true;
  renderParts();
  nmChanged();
}
function nmToText() {
  if (!NM_PARTS) return;
  $('nmpattern').value = nmBuild(NM_PARTS.parts, NM_PARTS.sep);
  renderParts();
  nmChanged();
}
function renderParts() {
  const box = $('nmparts');
  if (!NM) { box.innerHTML = ''; return; }
  const receipts = NM.kind === 'receipts';
  const parts = NM_PARTS ? NM_PARTS.parts : [];
  box.innerHTML = parts.map((p, i) => '<span class="part' + (p.optional ? ' maybe' : '') + '">' +
    '<span class="sw" style="background:' + ['#2f6fe0', '#0f766e', '#8b5cf6', '#d9a440', '#e2557b', '#5a6270'][i % 6] + '" aria-hidden="true"></span>' +
    '<b>' + esc(nmLabel(p.field, receipts)) + '</b>' +
    '<button type="button" class="x" data-do="nm-move" data-i="' + i + '" data-by="-1"' + (i ? '' : ' disabled') +
    ' aria-label="Move ' + esc(nmLabel(p.field, receipts)) + ' earlier">' + sv(P.left, 14, 2.4) + '</button>' +
    '<button type="button" class="x" data-do="nm-move" data-i="' + i + '" data-by="1"' + (i < parts.length - 1 ? '' : ' disabled') +
    ' aria-label="Move ' + esc(nmLabel(p.field, receipts)) + ' later">' + sv(P.chevron, 14, 2.4) + '</button>' +
    '<button type="button" class="x" data-do="nm-remove" data-i="' + i + '" aria-label="Remove ' + esc(nmLabel(p.field, receipts)) + '">' +
    sv(P.x, 14, 2.4) + '</button></span>').join('') +
    (NM_PARTS ? '<button type="button" class="btn btn-s addpart" data-do="nm-add" aria-expanded="false">' + sv(P.plus, 16, 2.4) + 'Add a part</button>' : '');
}
function closePicklist() {
  const open = document.querySelector('.picklist');
  if (open) open.remove();
  const add = document.querySelector('.addpart');
  if (add) add.setAttribute('aria-expanded', 'false');
}
function openPicklist(btn) {
  if (document.querySelector('.picklist')) { closePicklist(); return; }
  const receipts = NM.kind === 'receipts', n = NM.fill.records;
  const used = new Set(NM_PARTS.parts.map(p => p.field));
  // An order total, a store and online or in store are things a receipt
  // has. On a statements app they would only ever come out empty.
  const fields = NM.fields.filter(f => !used.has(f) && (receipts || !['total', 'store', 'type'].includes(f)));
  const html = fields.map(f => {
    const got = NM.fill.filled[f] || 0;
    const none = n && f !== 'owner' && f !== 'part' && !got;
    return '<button type="button" class="pick' + (none ? ' none' : '') + '" data-do="nm-pick" data-field="' + f + '"><span style="flex:1;font-weight:600">' +
      esc(nmLabel(f, receipts)) + '</span><span class="c">' + esc(nmHowMany(f, got, n)) + '</span></button>';
  }).join('') || '<p class="hint" style="padding:8px 12px">Every part is already in the name.</p>';
  btn.insertAdjacentHTML('afterend', '<div class="picklist" role="listbox" aria-label="Parts you can add">' + html + '</div>');
  btn.setAttribute('aria-expanded', 'true');
}
function nmPick(field) {
  closePicklist();
  // A date and a provider are always there, so they are never optional.
  const skip = $('nmskip').checked && field !== 'date' && field !== 'provider';
  NM_PARTS.parts.push({field, fmt: field === 'date' ? $('nmdate').value : '', optional: skip,
                       before: field === 'part' ? '(' : '', after: field === 'part' ? ')' : ''});
  nmToText();
}
function nmChanged() {
  clearTimeout(NM_TIMER);
  NM_TIMER = setTimeout(nmPreview, 250);
}
async function nmPreview() {
  const pattern = $('nmpattern').value;
  let d;
  try {
    d = await (await fetch('/api/naming/preview', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: $('nmapp').value, pattern})})).json();
  } catch (e) { return; }
  const pr = $('nmproblem');
  pr.hidden = !d.problem;
  pr.textContent = d.problem || '';
  const box = $('nmpreview');
  if (!d.names || !d.names.length) {
    box.innerHTML = '<p class="hint">No files from this provider yet, so there is nothing to preview.</p>';
    $('nmname').textContent = 'No files yet';
    return;
  }
  $('nmname').textContent = d.names[0].new;
  box.innerHTML = '<table class="t mono"><thead><tr><th>Your newest files now</th><th>With this naming</th></tr></thead><tbody>' +
    d.names.map(n => '<tr><td class="muted">' + esc(n.current) + '</td><td' + (n.new !== n.current ? ' style="font-weight:700"' : '') + '>' +
      esc(n.new) + '</td></tr>').join('') + '</tbody></table>';
}
async function nmSave() {
  let r, d;
  try {
    r = await fetch('/api/naming/save', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: $('nmapp').value, scope: nmScopeValue(),
                            pattern: $('nmpattern').value})});
    d = await r.json();
  } catch (e) { $('nmnote').textContent = 'Could not reach the control panel.'; return; }
  if (!r.ok) { $('nmnote').textContent = d.detail || 'Not saved.'; return; }
  await loadNaming();
  $('nmnote').textContent = d.written ? 'Saved. New downloads use it.' : 'Nothing to change.';
  if (d.changed && d.changed.length) nmOffer(d.changed);
}
// The offer to bring files already on disk into line, one app and one
// account at a time, through the app's own --rename. Renaming is never
// offered until a preview of the same apps has finished cleanly.
let NM_OFFER = null, NM_PREVIEWED = false;
function nmOffer(apps) {
  NM_OFFER = apps; NM_PREVIEWED = false;
  $('nmoffer').hidden = !apps;
  if (!apps) return;
  $('nmofferapps').textContent = (apps.length === 1 ? 'In ' : 'In these ' + apps.length + ' providers, ') + apps.join(', ') + ', every person.';
  $('nmapplybtn').disabled = true;
  $('nmprevbtn').disabled = false;
  $('nmofferstate').textContent = '';
  $('nmlog').hidden = true;
  $('nmoffer').scrollIntoView({block: 'nearest'});
}
function nmPairs() {
  const pairs = [];
  for (const a of NM_OFFER || []) {
    const m = META.apps[a];
    if (!m) continue;
    for (const acc of (m.accounts && m.accounts.length ? m.accounts : ['primary'])) pairs.push([a, acc]);
  }
  return pairs;
}
function nmRename(apply) {
  const pairs = nmPairs();
  if (!pairs.length) return;
  if (apply && !NM_PREVIEWED) return;
  const action = apply ? 'rename_apply' : 'rename';
  const log = $('nmlog');
  log.textContent = ''; log.hidden = false;
  $('nmprevbtn').disabled = true; $('nmapplybtn').disabled = true;
  let i = 0;
  const next = (code) => {
    if (code !== undefined && code !== '0') {
      $('nmofferstate').textContent = 'Stopped at ' + pairs[i - 1].join(', ') + ', which did not finish. Its output says why.';
      $('nmprevbtn').disabled = false;
      return;
    }
    if (i >= pairs.length) {
      if (apply) {
        $('nmofferstate').textContent = 'Renamed. The list above names each file.';
        loadNaming();
      } else {
        NM_PREVIEWED = true;
        $('nmapplybtn').disabled = false; $('nmprevbtn').disabled = false;
        log.textContent += '\n== That is the whole preview. Nothing has been changed. ==\n';
        $('nmofferstate').textContent = 'Preview done. Read it above, then rename.';
      }
      return;
    }
    const [app, account] = pairs[i++];
    const r = rowFor(app, account) || {app, account, provider: app, kind: ''};
    log.textContent += (i > 1 ? '\n' : '') + '== ' + app + (account === 'primary' ? '' : ', ' + account) + ' ==\n';
    // Each app's lines follow the last one's in the same box.
    if (!startRun(r, action, {stay: true, sink: 'nmlog', append: true, onDone: next})) {
      $('nmofferstate').textContent = 'Wait for the run going now to finish first.';
      $('nmprevbtn').disabled = false;
    }
  };
  $('nmofferstate').textContent = apply ? 'Renaming…' : 'Previewing…';
  next();
}

// -- settings -----------------------------------------------------------------------
function renderSettings() {
  $('root').textContent = META.apps_root || '';
  $('rootwhy').textContent = inSample() ? 'This is the sample archive. Leave it to see your own.'
    : SERVER ? 'The data folder beside compose.yaml on your server, named /data inside the container.'
    : META.root_source === 'environment' ? 'Set by the APPS_ROOT setting this panel was started with.'
    : 'Each provider has a folder of its own in here, holding its documents and its download history.';
  $('existing').hidden = SERVER || inSample() || META.root_source === 'environment';
  $('rootinput').value = $('rootinput').value || META.apps_root || '';
  $('stmove').hidden = inSample();
  if (!hxWelcome()) placeMove(false);
  $('g-sampleopen').hidden = inSample();
  $('g-sampleleave').hidden = !inSample();
  const theme = store.get('theme') || 'system';
  for (const el of document.querySelectorAll('input[name=theme]')) el.checked = el.value === theme;
  openDocuments();
}
// The documents folder (#102). One folder for every provider, each provider's
// person given a folder of their own inside it, or one of their own set here,
// which the panel writes into that person's config. Saving moves nothing.
// Documents saved before stay where they are until Move, which is the app's
// own Rename, offered only once a preview of the same person has finished
// cleanly.
let DC_PREVIEWED = false;
// The folder for every provider as saved, the one Use it for every provider
// applies, since the list beside it is of the folders it would replace there.
let DR_ROOT = '';
function dcPick() {
  const [app, account] = ($('dcpick').value || '').split('\n');
  return app ? {app, account: account || 'primary'} : null;
}
function openDocuments() {
  $('g-docscard').hidden = inSample() || !Object.keys(META.apps || {}).length;
  if ($('g-docscard').hidden) return;
  const sel = $('dcpick'), was = sel.value;
  const opts = [];
  for (const [app, m] of Object.entries(META.apps)) {
    for (const acc of (m.accounts && m.accounts.length ? m.accounts : ['primary'])) {
      const v = app + '\n' + acc;
      opts.push('<option value="' + esc(v) + '"' + (v === was ? ' selected' : '') + '>' +
        esc(app + (acc === 'primary' ? '' : ', ' + acc)) + '</option>');
    }
  }
  sel.innerHTML = opts.join('');
  const isUnix = SERVER || Boolean(META.apps_root && META.apps_root.startsWith('/'));
  $('drinput').placeholder = SERVER ? '/data/Documents' : (isUnix ? '/Users/you/Documents/PaperPull' : 'C:\\Users\\you\\Documents\\PaperPull');
  $('dcinput').placeholder = SERVER ? '/data/Documents' : (isUnix ? '/Users/you/Documents/Statements' : 'C:\\Users\\you\\Documents\\Statements');
  dcLoad();
}
async function dcLoad() {
  const p = dcPick();
  if (!p) return;
  DC_PREVIEWED = false;
  $('dcmsg').textContent = ''; $('dcstate').textContent = '';
  $('dclog').hidden = true; $('dcmovebtn').disabled = true;
  let d;
  try { d = await (await fetch('/api/documents?' + new URLSearchParams(p))).json(); }
  catch (e) { return; }
  if (!d || d.detail) { $('dcnow').textContent = (d && d.detail) || ''; return; }
  DR_ROOT = d.documents_root || '';
  $('drnow').textContent = d.documents_root ? 'Every provider’s documents go to ' + d.documents_root + ', unless one has a folder of their own.'
    : 'No folder for every provider. Each provider keeps its documents in its own folder, or one of their own set below.';
  if (document.activeElement !== $('drinput')) $('drinput').value = d.documents_root || '';
  $('drclear').hidden = !d.documents_root;
  $('dcnow').textContent = d.documents_dir
    ? (d.follows ? 'From the folder for every provider, documents' : 'Set for them alone, documents') +
      ' go to ' + d.documents_dir + '. Records stay in ' + d.output_dir + '.'
    // One added since the folder was saved gets it as its next download
    // starts, unless that run would refuse it, which is said instead.
    : d.follows && d.in_root && d.in_root_refused ? 'Documents and records both go to ' + d.output_dir +
      ', since their download runs will not use ' + d.in_root + '. ' + d.in_root_refused
    : d.follows && d.in_root ? 'From the folder for every provider, documents go to ' + d.in_root +
      ' from their next download. Records stay in ' + d.output_dir + '.'
    : 'Documents and records both go to ' + d.output_dir + '.';
  if (document.activeElement !== $('dcinput')) $('dcinput').value = d.documents_dir || '';
  const isUnix = SERVER || Boolean(META.apps_root && META.apps_root.startsWith('/'));
  $('dcinput').placeholder = d.in_root || (SERVER ? '/data/Documents' : (isUnix ? '/Users/you/Documents/Statements' : 'C:\\Users\\you\\Documents\\Statements'));
  $('dcfollow').hidden = !d.documents_root || d.follows;
  // Each one Use it for every provider would change, named before it is pressed.
  const own = d.documents_root ? (d.own || []) : [];
  $('drown').hidden = !own.length;
  $('drownlist').innerHTML = own.map(o => '<li>' + esc(o.who) + ' keeps ' +
    esc(o.folder || 'the folder its records are in') + '</li>').join('');
  $('drapplyall').hidden = !own.length;
  $('dcleft').hidden = !d.left;
  $('dclefttext').textContent = !d.left ? ''
    : d.documents_dir ? many(d.left, 'document') + (d.left === 1 ? ' is' : ' are') + ' not in ' +
      d.documents_dir + ' yet, saved before in ' + d.output_dir + ' or a documents folder used before. ' +
      'They are found where they are. Move them there, with a preview first.'
    : many(d.left, 'document') + (d.left === 1 ? ' is' : ' are') + ' in a documents folder used before. ' +
      'Move brings them back to ' + d.output_dir + ', with a preview first.';
}
async function drSave(how) {
  const clear = how === 'clear';
  const applyAll = how === 'all';
  const folder = clear ? '' : applyAll ? DR_ROOT : $('drinput').value.trim();
  $('drmsg').textContent = '';
  if (!clear && !folder) { $('drmsg').textContent = 'Paste the folder path first, or use each provider’s own folder.'; return; }
  let d;
  try { d = await postJSON('/api/documents/root', {folder, all: applyAll}); }
  catch (e) { $('drmsg').textContent = e.message; return; }
  $('drinput').value = d.documents_root || '';
  await dcLoad();
  if (!d.documents_root) {
    $('drmsg').textContent = !d.written ? 'Nothing to change.' : 'Each provider keeps documents in its own folder.';
    return;
  }
  if (!d.written) {
    $('drmsg').textContent = 'Nothing to change.';
    return;
  }
  const own = d.own || [];
  let msg = 'Saved. ' + (own.length
    ? many(d.following, 'provider and person follows', 'providers and people follow') + ' it now, and ' +
      many(own.length, 'keeps', 'keep') + ' a folder of their own, listed below.'
    : !d.following ? 'Each provider and person gets their folder inside it as their first download starts.'
    : d.following === 1 ? 'The one provider and person follows it now.'
    : 'All ' + d.following + ' providers and people follow it now.');
  if (applyAll && d.configs) {
    msg += ' The folder each had before is in a copy of its config, in its provider’s Backups folder.';
  }
  if (d.missed && d.missed.length) {
    msg += ' The config of ' + d.missed.join(' and of ') + ' could not be written, and is as it was.';
  }
  $('drmsg').textContent = msg;
}
async function dcSave(how) {
  const p = dcPick();
  if (!p) return;
  const folder = how === 'save' ? $('dcinput').value.trim() : '';
  if (how === 'save' && !folder) { $('dcmsg').textContent = 'Paste the folder path first, or use the provider’s own folder.'; return; }
  let d;
  try { d = await postJSON('/api/documents', Object.assign({folder, follow: how === 'follow'}, p)); }
  catch (e) { $('dcmsg').textContent = e.message; return; }
  await dcLoad();
  $('dcmsg').textContent = d.written ? 'Saved. New downloads go there.' : 'Nothing to change.';
}
function dcMove(apply) {
  const p = dcPick();
  if (!p || (apply && !DC_PREVIEWED)) return;
  const r = rowFor(p.app, p.account) || {app: p.app, account: p.account, provider: p.app, kind: ''};
  $('dcprevbtn').disabled = true; $('dcmovebtn').disabled = true;
  $('dcstate').textContent = apply ? 'Moving\u2026' : 'Previewing\u2026';
  const done = code => {
    $('dcprevbtn').disabled = false;
    if (code !== undefined && code !== '0') { $('dcstate').textContent = 'It did not finish. The output says why.'; return; }
    if (apply) { $('dcstate').textContent = 'Moved. The list above names each file.'; DC_PREVIEWED = false; dcLoad(); return; }
    DC_PREVIEWED = true; $('dcmovebtn').disabled = false;
    $('dcstate').textContent = 'Preview done. Read it above, then move.';
  };
  if (!startRun(r, apply ? 'move_documents_apply' : 'move_documents', {stay: true, sink: 'dclog', onDone: done})) {
    $('dcstate').textContent = 'Wait for the run going now to finish first.';
    $('dcprevbtn').disabled = false;
  }
}
async function saveRoot() {
  const root = $('rootinput').value.trim();
  $('rootmsg').textContent = '';
  if (!root) { $('rootmsg').textContent = 'Paste the folder path first.'; return; }
  let d;
  try { d = await postJSON('/api/root', {root}); }
  catch (e) { $('rootmsg').textContent = e.message; return; }
  $('rootmsg').textContent = d.apps === 0 ? 'Saved, but no PaperPull folders were found there yet.'
    : 'Found ' + many(d.apps, 'provider') + '.';
  XL_LOADED = false;
  await load();
}
async function setSample(on) {
  try { await postJSON('/api/sample', {on}); }
  catch (e) { notice(e.message || 'Could not switch.', 'warn'); return; }
  XL_LOADED = false;
  await load();
  location.hash = '#/';
}
function applyTheme() {
  const t = store.get('theme') || 'system';
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}

// -- every button --------------------------------------------------------------------
const DO = {
  'menu': el => openMenu(el),
  'nav': el => { const r = rowByKey(el.dataset.key); if (r) location.hash = accountHash(r); },
  'run': el => {
    const r = rowByKey(el.dataset.key);
    if (!r) return;
    const scope = el.dataset.start ? {year: '', start: el.dataset.start, end: el.dataset.end} : null;
    startRun(r, el.dataset.action, scope ? {scope} : {});
  },
  'restore': el => { const r = rowByKey(el.dataset.key); closeMenus(); if (r) openRestore(r); },
  'rename': el => { const r = rowByKey(el.dataset.key); closeMenus(); if (r) openRename(r); },
  'review': el => { const r = rowByKey(el.dataset.key); closeMenus(); if (r) openReview(r); },
  'support': el => { DLG_ROW = rowByKey(el.dataset.key); closeMenus(); if (DLG_ROW) $('dlg-support').showModal(); },
  'record': el => { DLG_ROW = rowByKey(el.dataset.key); closeMenus(); if (DLG_ROW) $('dlg-record').showModal(); },
  'person': el => { const r = rowByKey(el.dataset.key); closeMenus(); if (r) openPerson(r); },
  'remove': el => { const r = rowByKey(el.dataset.key); closeMenus(); if (r) openRemove(r); },
  'reveal': async el => {
    const r = rowByKey(el.dataset.key);
    closeMenus();
    if (!r) return;
    try { await postJSON('/api/reveal', {app: r.app, account: r.account}); } catch (e) { notice(e.message, 'warn'); }
  },
  'queue': () => startQueue(),
  'queue-retry': () => queueRun(),
  'queue-skip': () => { QUEUE.items[QUEUE.i].said = 'skipped'; QUEUE.i++; queueRun(); },
  'queue-end': () => { QUEUE = null; renderAll(); },
  'stop-run': () => stopRun(),
  'stop-recording': () => stopRecording(),
  'failure': () => revealFailure(),
  'report-download': el => {
    const r = rowByKey(el.dataset.key);
    if (r) fetchDownload('/api/diagnostics/download?' + new URLSearchParams({app: r.app, account: r.account,
      action: el.dataset.action}).toString());
  },
  'aside-download': el => {
    const r = rowByKey(el.dataset.key);
    if (r) fetchDownload('/api/aside/download?' + new URLSearchParams({app: r.app, account: r.account}).toString());
  },
  'rs-go': () => rsGo(),
  'ps-go': () => psGo(),
  'rm-go': () => rmGo(),
  'rn-preview': () => rnRun(false),
  'rn-apply': () => rnRun(true),
  'rv-go': () => rvGo(),
  'sp-go': () => { $('dlg-support').close(); startRun(DLG_ROW, 'diagnose'); },
  'rc-go': () => { $('dlg-record').close(); startRun(DLG_ROW, 'record'); },
  'tm-go': () => tmGo(),
  'dock-close': () => closeDock(),
  'dismiss-notice': () => notice('', ''),
  'open-sample': () => setSample(true),
  'leave-sample': () => setSample(false),
  'add-provider': () => { location.hash = '#/add'; },
  'settings-folder': () => { location.hash = '#/settings'; setTimeout(() => { $('existing').hidden = false; $('rootinput').focus(); }, 50); },
  'save-root': () => saveRoot(),
  'hx-export': () => exportHistory(),
  'hx-import': () => importHistory(),
  'w-import': () => { placeMove(true); $('hxfile').focus(); },
  'w-next': () => {
    if (W.step === 1 && !$('newroot').value.trim()) { $('newroot').focus(); return; }
    W.step = Math.min(3, W.step + 1); wShow();
    const h = $(W.step === 2 ? 'w-title2' : 'w-title3'); if (h) h.focus();
  },
  'w-back': () => {
    if (W.add && W.step === 2) { location.hash = '#/'; return; }
    W.step = Math.max(1, W.step - 1); wShow();
  },
  'w-group': el => { W.group = el.dataset.group; renderTiles(); },
  'w-create': () => wCreate(),
  'xl-build': () => buildSpreadsheet(),
  'tx-build': () => buildTransactions(),
  'sheet-reveal': () => revealSpreadsheet(),
  'nm-save': () => nmSave(),
  'nm-default': () => { $('nmpattern').value = NM ? NM.default : ''; nmFromText(); },
  'nm-clear': () => { $('nmpattern').value = ''; NM_PARTS = {parts: [], sep: $('nmsep').value || ' '}; renderParts(); $('nmtext').open = true; $('nmpattern').focus(); nmChanged(); },
  'nm-add': el => openPicklist(el),
  'nm-pick': el => nmPick(el.dataset.field),
  'nm-remove': el => { NM_PARTS.parts.splice(+el.dataset.i, 1); nmToText(); },
  'nm-move': el => {
    const i = +el.dataset.i, j = i + (+el.dataset.by), parts = NM_PARTS.parts;
    if (j < 0 || j >= parts.length) return;
    [parts[i], parts[j]] = [parts[j], parts[i]];
    // A name starts with its first part, never with a separator.
    nmToText();
  },
  'nm-preview': () => nmRename(false),
  // Enabled only once a preview of the same providers finished cleanly,
  // which is what makes pressing it a decision rather than a guess.
  'nm-apply': () => nmRename(true),
  'nm-notnow': () => nmOffer(null),
  'dc-save': () => dcSave('save'),
  'dc-clear': () => dcSave('own'),
  'dc-follow': () => dcSave('follow'),
  'dr-save': () => drSave('save'),
  'dr-clear': () => drSave('clear'),
  'dr-apply-all': () => drSave('all'),
  'dc-preview': () => dcMove(false),
  // Enabled only once a preview of the same person finished cleanly.
  'dc-move': () => dcMove(true),
};
document.addEventListener('click', e => {
  const el = e.target.closest('[data-do]');
  if (!el || el.disabled) return;
  const fn = DO[el.dataset.do];
  if (!fn) return;
  if (el.tagName === 'A' && el.dataset.do !== 'queue-end') e.preventDefault();
  fn(el, e);
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.closest('#providers') && t.type === 'checkbox') {
    if (t.checked) W.picked.add(t.value); else W.picked.delete(t.value);
    wPicked();
  } else if (t.name === 'rsby') rsBy();
  else if (t.id === 'rs-year' || t.id === 'rs-start' || t.id === 'rs-end') rsLabel();
  else if (t.name === 'theme') { store.set('theme', t.value); applyTheme(); }
  else if (t.id === 'dcpick') dcLoad();
  else if (t.id === 'hxfile') planHistory();
  else if (t.id === 'nmapp') loadNaming();
  else if (t.name === 'nmscope') { if (NM) { $('nmpattern').value = (nmScopeValue() === 'own' ? NM.own : '') || NM.shared || NM.default; nmFromText(); } }
  else if (t.id === 'nmsep' && NM_PARTS) { NM_PARTS.sep = t.value; nmToText(); }
  else if (t.id === 'nmdate' && NM_PARTS) { for (const p of NM_PARTS.parts) if (p.field === 'date') p.fmt = t.value; nmToText(); }
});
document.addEventListener('input', e => {
  if (e.target.id === 'w-search') { W.search = e.target.value; renderTiles(); }
  else if (e.target.id === 'nmpattern') { NM_PARTS = nmParse(e.target.value); $('nmtextonly').hidden = Boolean(NM_PARTS) || !e.target.value;
    $('nmsep').disabled = $('nmdate').disabled = !NM_PARTS; renderParts(); nmChanged(); }
});
// A page the browser brings back from its back and forward cache keeps what
// it was showing, and nothing in it may still look like it is running.
window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });

// On the server the documents folder is the shared folder the container was
// given, so it is shown and not asked for, and what would open a folder on
// this computer downloads the file instead.
function serverPage() {
  if (!SERVER) return;
  const btn = $('screenbtn');
  if (btn) btn.addEventListener('click', e => {
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    e.preventDefault();
    openDock(RUN.state === 'running' ? RUN.provider : '');
  });
}
// The terms of use, the first time the panel opens and again when they
// change. Only I understand ends the dialog. Escape, or anything else that
// closes it, brings it straight back. Once pressed the page goes on, and an
// answer that could not be saved is said, so the terms come back next time.
let TERMS_OK = !TERMS_DUE;
function openTerms() {
  const d = $('dlg-terms');
  d.addEventListener('cancel', e => e.preventDefault());
  d.addEventListener('close', () => { if (!TERMS_OK) d.showModal(); });
  d.showModal();
}
async function tmGo() {
  TERMS_OK = true;
  $('dlg-terms').close();
  try { await postJSON('/api/terms', {accepted: TERMS_VERSION}); }
  catch (e) { notice('Your answer to the terms could not be saved, so they will be shown again next time. ' + e.message, 'warn'); }
}
applyTheme();
serverPage();
placeMove(false);
load();
if (TERMS_DUE) openTerms();
