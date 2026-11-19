/* Gmail look-alike front end for Mailpit.
 *
 * Everything on screen comes from Mailpit's REST API on the same origin
 * (nginx proxies /api/ and /view/). Read/unread, delete and send are real
 * Mailpit operations. Mailpit has no concept of stars, archive or a trash
 * folder, so those three are kept in localStorage - that also keeps a demo
 * non-destructive, since "Delete" only moves a message to a local Trash.
 */
(() => {
  'use strict';

  const CFG = Object.assign({ account: 'demo@example.com', name: 'Demo User' }, window.GMAIL_CONFIG || {});
  const PAGE = 200;
  // Matches the breakpoint in styles.css, where the layout switches to the
  // Gmail mobile app look (search-bar header, avatar rows, nav drawer, FAB).
  const MOBILE = window.matchMedia('(max-width: 700px)');
  // Gmail collapses its nav to an icon rail on narrow desktop/tablet widths.
  const NARROW = window.matchMedia('(min-width: 701px) and (max-width: 1000px)');

  /* ------------------------------------------------------------------ icons */
  const S = (body, extra) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" ${extra || ''}>${body}</svg>`;

  const ICONS = {
    menu: S('<path d="M4 7h16M4 12h16M4 17h16"/>'),
    search: S('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>'),
    close: S('<path d="M6 6l12 12M18 6L6 18"/>'),
    tune: S('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'),
    help: S('<circle cx="12" cy="12" r="8.5"/><path d="M9.8 9.4a2.2 2.2 0 1 1 3.4 2c-.8.5-1.2 1-1.2 1.9"/><path d="M12 17.2h.01" stroke-width="2.4"/>'),
    settings: S('<circle cx="12" cy="12" r="7.4"/><circle cx="12" cy="12" r="3"/>' +
                '<g stroke-width="2.4"><path d="M19.4 12h1.9M12 19.4v1.9M4.6 12H2.7M12 4.6V2.7' +
                'M17.23 17.23l1.35 1.35M6.77 17.23l-1.35 1.35M6.77 6.77 5.42 5.42M17.23 6.77l1.35-1.35"/></g>'),
    folder: S('<path d="M3.5 6.5h5.5l2 2.5h9.5v9.5h-17z"/><path d="M14 12.5l2.5 2.5-2.5 2.5" stroke-width="1.6"/>'),
    'check-circle': S('<circle cx="12" cy="12" r="8.5"/><path d="M8.4 12.3l2.6 2.6 4.9-5.1"/>'),
    'app-calendar': '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="16" rx="2.5" fill="#fff" stroke="#4285f4" stroke-width="1.8"/><path d="M3.5 8.6h17" stroke="#4285f4" stroke-width="1.8"/><text x="12" y="17.6" text-anchor="middle" font-size="8.5" font-family="Arial, sans-serif" font-weight="bold" fill="#4285f4">31</text></svg>',
    'app-keep': '<svg viewBox="0 0 24 24"><path d="M12 3.2a6.1 6.1 0 0 0-3.7 10.9v2.2h7.4v-2.2A6.1 6.1 0 0 0 12 3.2z" fill="#fbbc04"/><rect x="9.5" y="17.5" width="5" height="1.9" rx=".9" fill="#fbbc04"/></svg>',
    'app-tasks': '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.6" fill="#1a73e8"/><path d="M8.2 12.4l2.6 2.6 5-5.3" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    'app-contacts': '<svg viewBox="0 0 24 24"><circle cx="12" cy="9.1" r="3.4" fill="#1a73e8"/><path d="M5.6 19.5c0-3.4 2.9-5.3 6.4-5.3s6.4 1.9 6.4 5.3z" fill="#1a73e8"/></svg>',
    apps: S('<g fill="currentColor" stroke="none"><circle cx="6" cy="6" r="1.7"/><circle cx="12" cy="6" r="1.7"/><circle cx="18" cy="6" r="1.7"/><circle cx="6" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="18" cy="12" r="1.7"/><circle cx="6" cy="18" r="1.7"/><circle cx="12" cy="18" r="1.7"/><circle cx="18" cy="18" r="1.7"/></g>'),
    pencil: S('<path d="M4 20h4L20 8l-4-4L4 16z"/><path d="M14 6l4 4"/>'),
    inbox: S('<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M3 13.5h4.5l1.7 2.5h5.6l1.7-2.5H21"/>'),
    star: S('<path d="M12 3.7l2.6 5.5 6 .8-4.4 4.1 1.1 6-5.3-3-5.3 3 1.1-6L3.4 10l6-.8z"/>'),
    clock: S('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 1.9"/>'),
    send: S('<path d="M3.5 20l17.5-8-17.5-8v6l11 2-11 2z" fill="currentColor" stroke="none"/>'),
    draft: S('<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><path d="M9 13h6M9 16.5h4"/>'),
    tag: S('<path d="M3.5 6.5h11l5 5.5-5 5.5h-11z"/><circle cx="7.5" cy="12" r="1.2" fill="currentColor" stroke="none"/>'),
    people: S('<circle cx="9.5" cy="9" r="3.2"/><path d="M3.5 19c0-3 2.7-4.6 6-4.6s6 1.6 6 4.6"/><path d="M16 6.4a3 3 0 0 1 0 5.6M18 18.6c0-1.9-.7-3.2-1.8-4"/>'),
    spam: S('<path d="M12 3.6l8.5 4.9v7L12 20.4 3.5 15.4v-7z"/><path d="M12 8.5V13"/><path d="M12 16.2h.01" stroke-width="2.4"/>'),
    archive: S('<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8h14v11.5H5z"/><path d="M9.5 12.5h5"/>'),
    trash: S('<path d="M6.5 7.5h11l-1 12.5h-9z"/><path d="M4 7.5h16M9.5 7.5V4h5v3.5"/>'),
    mail: S('<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3.6 7l8.4 5.8L20.4 7"/>'),
    'mail-open': S('<path d="M3.5 10.5L12 4.5l8.5 6v8h-17z"/><path d="M3.5 10.5L12 16.5l8.5-6"/>'),
    refresh: S('<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20.5 4v4.5H16"/>'),
    more: S('<g fill="currentColor" stroke="none"><circle cx="12" cy="5.5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="18.5" r="1.8"/></g>'),
    'chevron-down': S('<path d="M7 10l5 5 5-5"/>'),
    'chevron-left': S('<path d="M14.5 6l-6 6 6 6"/>'),
    'chevron-right': S('<path d="M9.5 6l6 6-6 6"/>'),
    'arrow-back': S('<path d="M20 12H4.5"/><path d="M11 5.5L4.5 12 11 18.5"/>'),
    reply: S('<path d="M9 5.5L3 11.5l6 6"/><path d="M3 11.5h9.5a7.5 7.5 0 0 1 7.5 7.5v.5"/>'),
    'reply-all': S('<path d="M8 6.5l-5 5 5 5"/><path d="M13 6.5l-5 5 5 5"/><path d="M8 11.5h6.5a6.5 6.5 0 0 1 6.5 6.5v.5"/>'),
    forward: S('<path d="M15 5.5l6 6-6 6"/><path d="M21 11.5h-9.5A7.5 7.5 0 0 0 4 19v.5"/>'),
    print: S('<path d="M7 8.5V4h10v4.5"/><rect x="4" y="8.5" width="16" height="7" rx="1.5"/><path d="M7 14h10v6H7z"/>'),
    'open-in-new': S('<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5L12 12"/><path d="M18 14v5.5H5V6.5h5"/>'),
    paperclip: S('<path d="M16.5 8v8.2a4.5 4.5 0 0 1-9 0V7a2.8 2.8 0 0 1 5.6 0v9.3"/>'),
    plus: S('<path d="M12 5v14M5 12h14"/>'),
    format: S('<path d="M6 6h12M6 12h12M6 18h8"/>'),
  };

  const STAR_ON = S('<path d="M12 3.7l2.6 5.5 6 .8-4.4 4.1 1.1 6-5.3-3-5.3 3 1.1-6L3.4 10l6-.8z" fill="currentColor"/>');

  function hydrateIcons(root) {
    root.querySelectorAll('[data-icon]').forEach((el) => {
      const svg = ICONS[el.dataset.icon];
      if (svg) el.innerHTML = svg;
      el.removeAttribute('data-icon');
    });
  }

  /* ------------------------------------------------------------------ state */
  const store = {
    get(key) {
      try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')); }
      catch (e) { return new Set(); }
    },
    put(key, set) { localStorage.setItem(key, JSON.stringify([...set])); },
  };

  const state = {
    all: [],                       // message summaries newest first
    folder: 'inbox',
    query: '',
    picked: new Set(),
    open: null,                    // id of the open conversation
    tags: [],                      // Mailpit tags, shown as Gmail labels
    info: null,                    // Mailpit /info, drives the footer numbers
    starred: store.get('gm.starred'),
    archived: store.get('gm.archived'),
    trashed: store.get('gm.trashed'),
  };

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  /* -------------------------------------------------------------------- api */
  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    if (!res.ok) throw new Error(path + ' -> ' + res.status);
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  const setRead = (ids, read) =>
    api('/api/v1/messages', { method: 'PUT', body: JSON.stringify({ IDs: ids, Read: read }) });
  const destroy = (ids) =>
    api('/api/v1/messages', { method: 'DELETE', body: JSON.stringify({ IDs: ids }) });

  /* ----------------------------------------------------------- formatting */
  const AVATAR_COLORS = ['#1a73e8', '#d93025', '#188038', '#e37400', '#9334e6', '#0b8043', '#c5221f', '#00639b'];
  function colorFor(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 9973;
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
  }

  const displayName = (addr) =>
    !addr ? '(unknown)' : (addr.Name || (addr.Address || '').split('@')[0] || addr.Address || '(unknown)');

  function initial(addr) {
    const n = displayName(addr).trim();
    return (n[0] || '?').toUpperCase();
  }

  function listDate(iso) {
    const d = new Date(iso);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    if (d.getFullYear() === now.getFullYear()) {
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
    return d.toLocaleDateString([], { month: 'numeric', day: 'numeric', year: '2-digit' });
  }

  function fullDate(iso) {
    const d = new Date(iso);
    const now = new Date();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const opts = { weekday: 'short', month: 'short', day: 'numeric' };
    if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
    const mins = Math.round((now - d) / 60000);
    const ago = mins < 1 ? ' (moments ago)'
      : mins < 60 ? ' (' + mins + ' minute' + (mins === 1 ? '' : 's') + ' ago)'
      : mins < 1440 ? ' (' + Math.round(mins / 60) + ' hour' + (Math.round(mins / 60) === 1 ? '' : 's') + ' ago)'
      : mins < 43200 ? ' (' + Math.round(mins / 1440) + ' day' + (Math.round(mins / 1440) === 1 ? '' : 's') + ' ago)'
      : '';
    return d.toLocaleDateString([], opts) + ', ' + time + ago;
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  const eq = (a, b) => String(a || '').toLowerCase() === String(b || '').toLowerCase();
  const isMine = (m) => eq(m.From && m.From.Address, CFG.account);
  const isToMe = (m) => (m.To || []).some((t) => eq(t.Address, CFG.account));

  /* ---------------------------------------------------------------- folders */
  const FOLDER_TITLE = {
    inbox: 'Inbox', starred: 'Starred', snoozed: 'Snoozed', sent: 'Sent',
    drafts: 'Drafts', all: 'All Mail', spam: 'Spam', trash: 'Trash',
  };

  function inFolder(m, folder) {
    const trashed = state.trashed.has(m.ID);
    switch (folder) {
      // Mail you sent to yourself shows up in both Inbox and Sent, as in Gmail.
      case 'inbox':   return !trashed && !state.archived.has(m.ID) && (!isMine(m) || isToMe(m));
      case 'starred': return !trashed && state.starred.has(m.ID);
      case 'sent':    return !trashed && isMine(m);
      case 'all':     return !trashed;
      case 'trash':   return trashed;
      default:        return false;   // snoozed / drafts / spam stay empty
    }
  }

  const visible = () => state.all.filter((m) => inFolder(m, state.folder));

  /* ------------------------------------------------------------------ load */
  async function load(opts) {
    const quiet = opts && opts.quiet;
    const url = state.query
      ? '/api/v1/search?query=' + encodeURIComponent(state.query) + '&limit=' + PAGE
      : '/api/v1/messages?limit=' + PAGE;
    try {
      const [data, info] = await Promise.all([api(url), api('/api/v1/info').catch(() => null)]);
      if (info) state.info = info;
      state.all = data.messages || [];
      if (data.tags) state.tags = data.tags;
      render();
    } catch (e) {
      if (!quiet) {
        $('#empty').hidden = false;
        $('#empty').textContent = 'Could not reach Mailpit: ' + e.message;
      }
    }
  }

  /* ---------------------------------------------------------------- render */
  function render() {
    renderFolders();
    renderLabels();
    renderFooter();
    if (state.open) return;                 // reading pane owns the screen
    $('#read-view').hidden = true;
    $('#list-view').hidden = false;
    renderList();
    renderTitle();
  }

  function renderFolders() {
    const inbox = state.all.filter((m) => inFolder(m, 'inbox'));
    const unread = inbox.filter((m) => !m.Read).length;
    $('#count-inbox').textContent = unread ? unread : '';
    const st = state.all.filter((m) => inFolder(m, 'starred')).length;
    $('#count-starred').textContent = st ? st : '';
    const tr = state.all.filter((m) => inFolder(m, 'trash')).length;
    $('#count-trash').textContent = tr ? tr : '';
    document.querySelectorAll('#folders a[data-folder]').forEach((a) => {
      a.classList.toggle('active', a.dataset.folder === state.folder);
    });
  }

  function renderLabels() {
    const ul = $('#labels');
    const want = (state.tags || []).join('|');
    if (ul.dataset.tags === want) return;
    ul.dataset.tags = want;
    ul.innerHTML = (state.tags || []).map((t) =>
      '<li><a data-label="' + esc(t) + '"><span class="icon">' + ICONS.tag +
      '</span><span class="label">' + esc(t) + '</span></a></li>').join('');
    ul.querySelectorAll('a[data-label]').forEach((a) => {
      a.onclick = () => {
        $('#q').value = 'tag:"' + a.dataset.label + '"';
        $('#search').dispatchEvent(new Event('submit'));
        document.body.classList.remove('drawer');
        $('#scrim').hidden = true;
      };
    });
  }

  function renderFooter() {
    const info = state.info;
    const used = info ? (info.DatabaseSize || 0) / 1073741824 : 0;
    $('#foot-storage').textContent = used.toFixed(2) + ' GB of 15 GB used';
    const mins = info ? Math.round((info.RuntimeStats && info.RuntimeStats.Uptime || 0) / 60) : 0;
    $('#foot-activity').textContent = 'Last account activity: ' +
      (mins < 1 ? 'moments ago' : mins < 60 ? mins + ' minute' + (mins === 1 ? '' : 's') + ' ago'
        : Math.round(mins / 60) + ' hour' + (Math.round(mins / 60) === 1 ? '' : 's') + ' ago');
  }

  function renderTitle() {
    const unread = state.all.filter((m) => inFolder(m, 'inbox') && !m.Read).length;
    document.title = (unread ? 'Inbox (' + unread + ')' : 'Inbox') + ' - ' + CFG.account + ' - Gmail';
  }

  function renderList() {
    const rows = $('#rows');
    const msgs = visible();
    rows.innerHTML = '';

    $('#pager').textContent = msgs.length
      ? '1–' + msgs.length + ' of ' + msgs.length
      : '';
    $('#tabs').hidden = state.folder !== 'inbox' || !!state.query;

    const empty = $('#empty');
    if (!msgs.length) {
      empty.hidden = false;
      empty.textContent = state.query
        ? 'No messages matched your search.'
        : state.folder === 'inbox'
          ? 'Nothing in your inbox, refresh to bring in new messages'
          : 'No conversations in ' + FOLDER_TITLE[state.folder] + '.';
      $('#trash-banner').hidden = true;
      return;
    }
    empty.hidden = true;
    const banner = $('#trash-banner');
    banner.hidden = state.folder !== 'trash';
    if (!banner.hidden) {
      // Gmail's trash banner - here it really does delete from Mailpit.
      banner.innerHTML = 'Messages that have been in Trash more than 30 days will be ' +
        'automatically deleted. <a href="#" id="empty-trash">Empty Trash now</a>';
    }

    msgs.forEach((m) => rows.appendChild(rowFor(m)));
    syncBulk();
  }

  function rowFor(m) {
    const row = el('div', 'row' + (m.Read ? '' : ' unread'));
    row.dataset.id = m.ID;
    if (state.picked.has(m.ID)) row.classList.add('picked');

    const who = state.folder === 'sent'
      ? 'To: ' + (m.To || []).map(displayName).join(', ')
      : displayName(m.From);

    const face = state.folder === 'sent' ? (m.To || [])[0] : m.From;

    row.innerHTML =
      '<span class="row-avatar" style="background:' + colorFor((face && face.Address) || '?') + '">' +
        esc(initial(face)) + '</span>' +
      '<button class="chk' + (state.picked.has(m.ID) ? ' on' : '') + '" data-act="pick" title="Select"></button>' +
      '<button class="star' + (state.starred.has(m.ID) ? ' on' : '') + '" data-act="star" title="' +
        (state.starred.has(m.ID) ? 'Starred' : 'Not starred') + '">' +
        (state.starred.has(m.ID) ? STAR_ON : ICONS.star) + '</button>' +
      '<span class="sender">' + esc(who) + '</span>' +
      '<span class="mid"><span class="subject">' + esc(m.Subject || '(no subject)') + '</span>' +
        (m.Snippet ? '<span class="sep"> - </span><span class="snippet">' + esc(m.Snippet) + '</span>' : '') +
        (m.Attachments ? '<span class="clip">' + ICONS.paperclip + '</span>' : '') +
      '</span>' +
      '<span class="date">' + listDate(m.Created) + '</span>' +
      '<span class="hover-actions">' +
        '<button class="iconbtn" data-act="archive" title="Archive">' + ICONS.archive + '</button>' +
        '<button class="iconbtn" data-act="trash" title="Delete">' + ICONS.trash + '</button>' +
        '<button class="iconbtn" data-act="toggleread" title="' +
          (m.Read ? 'Mark as unread' : 'Mark as read') + '">' +
          (m.Read ? ICONS.mail : ICONS['mail-open']) + '</button>' +
        '<button class="iconbtn" data-act="snooze" title="Snooze">' + ICONS.clock + '</button>' +
      '</span>';
    return row;
  }

  /* ----------------------------------------------------------- reading pane */
  async function openMessage(id) {
    let msg;
    try { msg = await api('/api/v1/message/' + id); }
    catch (e) { snack('Could not open that message.'); return; }

    state.open = id;
    const summary = state.all.find((m) => m.ID === id);
    if (summary && !summary.Read) {
      summary.Read = true;                      // Mailpit marks it read on fetch
      renderFolders();
      renderTitle();
    }

    const from = msg.From || {};
    const recipients = isToMe(msg) && (msg.To || []).length === 1
      ? 'to me'
      : 'to ' + (msg.To || []).map((t) => (eq(t.Address, CFG.account) ? 'me' : displayName(t))).join(', ');

    const starred = state.starred.has(id);
    const view = $('#read-view');
    view.innerHTML =
      '<div class="read-bar">' +
        '<button class="iconbtn" data-act="back" title="Back to ' + FOLDER_TITLE[state.folder] + '">' + ICONS['arrow-back'] + '</button>' +
        '<button class="iconbtn" data-act="archive" title="Archive">' + ICONS.archive + '</button>' +
        '<button class="iconbtn" data-act="trash" title="Delete">' + ICONS.trash + '</button>' +
        '<button class="iconbtn" data-act="unread" title="Mark as unread">' + ICONS.mail + '</button>' +
        '<button class="iconbtn" data-act="snooze" title="Snooze">' + ICONS.clock + '</button>' +
        '<button class="iconbtn" title="Add to tasks">' + ICONS['check-circle'] + '</button>' +
        '<button class="iconbtn" title="Move to">' + ICONS.folder + '</button>' +
        '<button class="iconbtn" title="Labels">' + ICONS.tag + '</button>' +
        '<button class="iconbtn" title="More">' + ICONS.more + '</button>' +
        '<div class="spacer"></div>' +
        '<span id="pager2"></span>' +
        '<button class="iconbtn" data-act="newer" title="Newer">' + ICONS['chevron-left'] + '</button>' +
        '<button class="iconbtn" data-act="older" title="Older">' + ICONS['chevron-right'] + '</button>' +
      '</div>' +
      '<div class="read-scroll">' +
        '<div class="read-subject">' +
          '<h1>' + esc(msg.Subject || '(no subject)') + '</h1>' +
          '<span class="chip">' + esc(FOLDER_TITLE[state.folder]) + '</span>' +
        '</div>' +
        '<div class="msg-head">' +
          '<div class="big-avatar" style="background:' + colorFor(from.Address || '?') + '">' + esc(initial(from)) + '</div>' +
          '<div class="msg-from">' +
            '<div class="from-line">' +
              '<span class="from-name">' + esc(displayName(from)) + '</span>' +
              '<span class="from-addr">&lt;' + esc(from.Address || '') + '&gt;</span>' +
            '</div>' +
            '<div class="to-line">' + esc(recipients) +
              '<button class="iconbtn" title="Show details">' + ICONS['chevron-down'] + '</button>' +
            '</div>' +
          '</div>' +
          '<div class="msg-meta">' +
            '<span class="date-full">' + esc(fullDate(msg.Date)) + '</span>' +
            '<span class="date-short">' + esc(listDate(msg.Date)) + '</span>' +
            '<button class="star iconbtn' + (starred ? ' on' : '') + '" data-act="star" title="' +
              (starred ? 'Starred' : 'Not starred') + '">' + (starred ? STAR_ON : ICONS.star) + '</button>' +
            '<button class="iconbtn" data-act="reply" title="Reply">' + ICONS.reply + '</button>' +
            '<button class="iconbtn" title="More">' + ICONS.more + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="msg-body" id="msg-body"></div>' +
        attachmentsHtml(msg) +
        '<div class="reply-row">' +
          '<button class="pill" data-act="reply">' + ICONS.reply + 'Reply</button>' +
          '<button class="pill" data-act="reply">' + ICONS['reply-all'] + 'Reply all</button>' +
          '<button class="pill" data-act="forward">' + ICONS.forward + 'Forward</button>' +
        '</div>' +
      '</div>';

    // HTML parts render through Mailpit's own /view/ endpoint so that inline
    // (cid:) images resolve; plain-text parts are shown as wrapped text.
    const body = view.querySelector('#msg-body');
    if (msg.HTML && msg.HTML.trim()) {
      const frame = el('iframe');
      frame.src = '/view/' + id + '.html';
      frame.addEventListener('load', () => fitFrame(frame));
      body.appendChild(frame);
    } else {
      body.appendChild(el('pre', null, esc(msg.Text || '')));
    }

    const idx = visible().findIndex((m) => m.ID === id);
    const total = visible().length;
    const p2 = view.querySelector('#pager2');
    if (p2 && idx >= 0) p2.textContent = (idx + 1) + ' of ' + total;
    view.querySelector('[data-act=newer]').disabled = idx <= 0;
    view.querySelector('[data-act=older]').disabled = idx < 0 || idx >= total - 1;

    $('#list-view').hidden = true;
    view.hidden = false;
    view.querySelector('.read-scroll').scrollTop = 0;
  }

  function fitFrame(frame) {
    try {
      const doc = frame.contentDocument;
      if (!doc) return;
      const style = doc.createElement('style');
      style.textContent =
        'html,body{margin:0;padding:0;overflow-y:hidden;' +
        'font:400 14px/1.5 "Google Sans",Roboto,Arial,sans-serif;color:#202124}';
      doc.head.appendChild(style);
      const pane = frame.clientWidth || 1;
      const wide = Math.max(doc.body.scrollWidth, doc.documentElement.scrollWidth);
      const scale = wide > pane + 4 ? pane / wide : 1;
      if (scale < 1) {
        doc.documentElement.style.transformOrigin = 'top left';
        doc.documentElement.style.width = wide + 'px';
        doc.documentElement.style.transform = 'scale(' + scale + ')';
      }
      const h = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight);
      frame.style.height = Math.ceil(h * scale + 24) + 'px';
    } catch (e) { frame.style.height = '480px'; }
  }

  function attachmentsHtml(msg) {
    const atts = msg.Attachments || [];
    if (!atts.length) return '';
    return '<div class="attachments">' +
      '<div class="att-head">' + atts.length + ' Attachment' + (atts.length === 1 ? '' : 's') +
        ' · Scanned by Gmail</div>' +
      '<div class="att-list">' + atts.map((a) =>
        '<a class="att" target="_blank" href="/api/v1/message/' + msg.ID + '/part/' + a.PartID + '">' +
          '<span class="clip">' + ICONS.paperclip + '</span>' +
          '<span><span class="nm">' + esc(a.FileName || a.PartID) + '</span><br>' +
          '<span class="sz">' + humanSize(a.Size || 0) + '</span></span></a>').join('') +
      '</div></div>';
  }

  function closeMessage() {
    state.open = null;
    if (location.hash.indexOf('/') > -1) { go(state.folder); return; }
    render();
  }

  /* URLs look like Gmail's: #inbox, #inbox/<message-id>. */
  function go(folder, id) {
    const hash = '#' + folder + (id ? '/' + id : '');
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  function route() {
    const parts = location.hash.replace(/^#/, '').split('/');
    const folder = FOLDER_TITLE[parts[0]] ? parts[0] : 'inbox';
    if (folder !== state.folder) state.picked.clear();
    state.folder = folder;
    const id = parts[1] || null;
    if (id) openMessage(id);
    else { state.open = null; render(); }
  }

  /* ---------------------------------------------------------------- actions */
  function persist() {
    store.put('gm.starred', state.starred);
    store.put('gm.archived', state.archived);
    store.put('gm.trashed', state.trashed);
  }

  function toggleStar(id) {
    if (state.starred.has(id)) state.starred.delete(id);
    else state.starred.add(id);
    persist();
  }

  function archive(ids) {
    ids.forEach((id) => state.archived.add(id));
    persist();
    snack('Conversation' + (ids.length > 1 ? 's' : '') + ' archived.', () => {
      ids.forEach((id) => state.archived.delete(id));
      persist();
      afterAction();
    });
  }

  function toTrash(ids) {
    ids.forEach((id) => state.trashed.add(id));
    persist();
    snack('Conversation' + (ids.length > 1 ? 's' : '') + ' moved to Trash.', () => {
      ids.forEach((id) => state.trashed.delete(id));
      persist();
      afterAction();
    });
  }

  async function markRead(ids, read) {
    try { await setRead(ids, read); } catch (e) { /* keep the UI responsive */ }
    ids.forEach((id) => {
      const m = state.all.find((x) => x.ID === id);
      if (m) m.Read = read;
    });
  }

  function afterAction() {
    state.picked.clear();
    if (state.open && !visible().some((m) => m.ID === state.open)) state.open = null;
    render();
  }

  function pickedIds() {
    return state.picked.size ? [...state.picked] : [];
  }

  function syncBulk() {
    const any = state.picked.size > 0;
    $('#bulk').hidden = !any;
    $('#btn-refresh').hidden = any;
    $('#select-all').classList.toggle('on', any && state.picked.size === visible().length);
  }

  /* -------------------------------------------------------------- snackbar */
  let snackTimer = null;
  function snack(text, undo) {
    clearTimeout(snackTimer);
    $('#snack-text').textContent = text;
    const btn = $('#snack-action');
    btn.hidden = !undo;
    btn.onclick = () => {
      $('#snackbar').hidden = true;
      if (undo) undo();
    };
    $('#snackbar').hidden = false;
    snackTimer = setTimeout(() => { $('#snackbar').hidden = true; }, 6000);
  }

  /* --------------------------------------------------------------- compose */
  const cw = {
    open(prefill) {
      document.body.classList.remove('cw-min');
      $('#cw-from').value = (prefill && prefill.from) || CFG.account;
      $('#cw-to').value = (prefill && prefill.to) || '';
      $('#cw-subject').value = (prefill && prefill.subject) || '';
      $('#cw-text').value = (prefill && prefill.text) || '';
      $('#compose-win').hidden = false;
      ($('#cw-to').value ? $('#cw-text') : $('#cw-to')).focus();
    },
    close() { $('#compose-win').hidden = true; document.body.classList.remove('cw-min'); },
    async send() {
      const to = $('#cw-to').value.split(/[,;]+/).map((s) => s.trim()).filter(Boolean);
      if (!to.length) { $('#cw-to').focus(); return; }
      const btn = $('#cw-send');
      btn.disabled = true;
      try {
        await api('/api/v1/send', {
          method: 'POST',
          body: JSON.stringify({
            From: { Email: $('#cw-from').value.trim() || CFG.account, Name: CFG.name },
            To: to.map((Email) => ({ Email })),
            Subject: $('#cw-subject').value,
            Text: $('#cw-text').value,
          }),
        });
        cw.close();
        snack('Message sent.');
        load({ quiet: true });
      } catch (e) {
        snack('Could not send: ' + e.message);
      } finally {
        btn.disabled = false;
      }
    },
  };

  function replyPrefill(kind) {
    const m = state.all.find((x) => x.ID === state.open);
    if (!m) return null;
    const quoted = (m.Snippet || '').trim();
    const stamp = new Date(m.Created).toLocaleString();
    return {
      to: kind === 'forward' ? '' : (m.From && m.From.Address) || '',
      subject: (kind === 'forward' ? 'Fwd: ' : 'Re: ') + (m.Subject || ''),
      text: '\n\nOn ' + stamp + ', ' + displayName(m.From) + ' wrote:\n> ' + quoted,
    };
  }

  /* ----------------------------------------------------------------- events */
  function wire() {
    hydrateIcons(document);

    const av = $('#me');
    av.textContent = (CFG.name || CFG.account)[0].toUpperCase();
    av.style.background = colorFor(CFG.account);
    av.title = CFG.name + ' (' + CFG.account + ')';

    // The drawer head repeats the Gmail logo, which the mobile header drops.
    $('.drawer-head').innerHTML = document.querySelector('.brand').innerHTML;

    const drawer = (open) => {
      document.body.classList.toggle('drawer', open);
      $('#scrim').hidden = !open;
    };
    $('#btn-rail').onclick = () => {
      if (MOBILE.matches) drawer(!document.body.classList.contains('drawer'));
      else document.body.classList.toggle('rail');
    };
    $('#scrim').onclick = () => drawer(false);
    MOBILE.addEventListener('change', () => {
      drawer(false);
      document.body.classList.remove('rail');   // desktop-only affordance
      applyViewport();
    });
    NARROW.addEventListener('change', () => applyViewport());
    $('#btn-more').onclick = () => {
      document.querySelectorAll('#folders .extra').forEach((li) => { li.hidden = !li.hidden; });
    };
    $('#btn-refresh').onclick = () => load();

    $('#trash-banner').onclick = async (e) => {
      if (!e.target.closest('#empty-trash')) return;
      e.preventDefault();
      const ids = visible().map((m) => m.ID);
      try {
        await destroy(ids);
        ids.forEach((id) => state.trashed.delete(id));
        persist();
        snack(ids.length + ' message' + (ids.length === 1 ? '' : 's') + ' deleted from Mailpit.');
        load();
      } catch (err) {
        snack('Could not empty Trash: ' + err.message);
      }
    };

    document.querySelectorAll('#folders a[data-folder]').forEach((a) => {
      a.onclick = () => {
        go(a.dataset.folder);
        drawer(false);
      };
    });

    $('#fab').onclick = () => cw.open();
    applyViewport();

    document.querySelectorAll('#tabs .tab').forEach((t) => {
      t.onclick = () => {
        document.querySelectorAll('#tabs .tab').forEach((x) => x.classList.remove('active'));
        t.classList.add('active');
      };
    });

    // search
    const q = $('#q');
    $('#search').onsubmit = (e) => {
      e.preventDefault();
      state.query = q.value.trim();
      state.open = null;
      $('#btn-clear').hidden = !state.query;
      load();
    };
    q.onfocus = () => $('#search').classList.add('focus');
    q.onblur = () => $('#search').classList.remove('focus');
    $('#btn-clear').onclick = () => {
      q.value = '';
      state.query = '';
      $('#btn-clear').hidden = true;
      load();
    };

    // list rows
    $('#rows').onclick = (e) => {
      const row = e.target.closest('.row');
      if (!row) return;
      const id = row.dataset.id;
      const act = (e.target.closest('[data-act]') || {}).dataset;
      if (!act) { go(state.folder, id); return; }
      e.stopPropagation();
      switch (act.act) {
        case 'pick':
          if (state.picked.has(id)) state.picked.delete(id); else state.picked.add(id);
          row.classList.toggle('picked', state.picked.has(id));
          row.querySelector('.chk').classList.toggle('on', state.picked.has(id));
          syncBulk();
          break;
        case 'star':
          toggleStar(id);
          renderList();
          renderFolders();
          break;
        case 'archive': archive([id]); afterAction(); break;
        case 'trash': toTrash([id]); afterAction(); break;
        case 'toggleread': {
          const m = state.all.find((x) => x.ID === id);
          markRead([id], !m.Read).then(() => { renderList(); renderFolders(); renderTitle(); });
          break;
        }
        case 'snooze': snack('Snooze is not wired up in this demo.'); break;
      }
    };

    // toolbar
    $('#select-all').onclick = () => {
      const msgs = visible();
      if (state.picked.size === msgs.length) state.picked.clear();
      else msgs.forEach((m) => state.picked.add(m.ID));
      renderList();
    };
    $('#select-caret').onclick = () => $('#select-all').click();

    $('#bulk').onclick = (e) => {
      const b = e.target.closest('[data-bulk]');
      if (!b) return;
      const ids = pickedIds();
      if (!ids.length) return;
      switch (b.dataset.bulk) {
        case 'archive': archive(ids); afterAction(); break;
        case 'trash': toTrash(ids); afterAction(); break;
        case 'read': markRead(ids, true).then(afterAction); break;
        case 'unread': markRead(ids, false).then(afterAction); break;
        case 'snooze': snack('Snooze is not wired up in this demo.'); break;
      }
    };

    // reading pane
    $('#read-view').onclick = (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const id = state.open;
      const list = visible();
      const idx = list.findIndex((m) => m.ID === id);
      switch (b.dataset.act) {
        case 'back': go(state.folder); break;
        case 'archive': archive([id]); afterAction(); break;
        case 'trash': toTrash([id]); afterAction(); break;
        case 'unread': markRead([id], false).then(() => { closeMessage(); }); break;
        case 'star': toggleStar(id); openMessage(id); break;
        case 'reply': cw.open(replyPrefill('reply')); break;
        case 'forward': cw.open(replyPrefill('forward')); break;
        case 'newer': if (idx > 0) go(state.folder, list[idx - 1].ID); break;
        case 'older': if (idx >= 0 && idx < list.length - 1) go(state.folder, list[idx + 1].ID); break;
        case 'snooze': snack('Snooze is not wired up in this demo.'); break;
      }
    };

    // compose window
    $('#compose').onclick = () => cw.open();
    $('#cw-close').onclick = () => cw.close();
    $('#cw-trash').onclick = () => { cw.close(); snack('Draft discarded.'); };
    $('#cw-min').onclick = () => document.body.classList.toggle('cw-min');
    $('.cw-head').onclick = (e) => {
      if (e.target.closest('.cw-ico')) return;
      if (document.body.classList.contains('cw-min')) document.body.classList.remove('cw-min');
    };
    $('#cw-send').onclick = () => cw.send();

    // a few of Gmail's keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
      if (e.ctrlKey && e.key === 'Enter' && !$('#compose-win').hidden) { cw.send(); return; }
      if (typing) {
        if (e.key === 'Escape') document.activeElement.blur();
        return;
      }
      if (e.key === '/') { e.preventDefault(); $('#q').focus(); return; }
      if (e.key === 'c') { e.preventDefault(); cw.open(); return; }
      if (e.key === 'u' || e.key === 'Escape') { if (state.open) go(state.folder); return; }
      if (state.open && e.key === 'e') { archive([state.open]); afterAction(); return; }
      if (state.open && e.key === 'r') { cw.open(replyPrefill('reply')); }
    });
  }

  function applyViewport() {
    $('#q').placeholder = MOBILE.matches ? 'Search in mail' : 'Search mail';
    document.body.classList.toggle('rail', NARROW.matches);
  }

  /* ------------------------------------------------------- live event feed */
  function listen() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let ws;
    try { ws = new WebSocket(proto + '//' + location.host + '/api/events'); }
    catch (e) { setInterval(() => load({ quiet: true }), 5000); return; }

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.Type === 'new' && msg.Data) {
        state.all.unshift(msg.Data);
        if (!state.open) {
          renderList();
          const row = $('#rows').querySelector('.row[data-id="' + msg.Data.ID + '"]');
          if (row) row.classList.add('arriving');
        }
        renderFolders();
        renderTitle();
      } else if (msg.Type === 'delete' || msg.Type === 'truncate' || msg.Type === 'update') {
        load({ quiet: true });
      }
    };
    // Reconnect if Mailpit restarts, and fall back to polling if it stays down.
    ws.onclose = () => setTimeout(listen, 3000);
  }

  window.addEventListener('hashchange', route);

  wire();
  load().then(route);
  listen();
})();
