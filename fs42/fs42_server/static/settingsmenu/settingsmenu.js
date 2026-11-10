// On-TV settings menu. Rows come from GET /settings, so a new setting added to
// fs42/user_settings.py shows up here without touching this page; a setting with
// a "group" goes in that group's sub-menu.
// OK on a setting opens a drop-down of every option; nothing changes until an
// option is confirmed with OK. Left (or Escape) closes the drop-down untouched,
// or goes back out of a sub-menu. A setting with "digits" (the weather ZIP code)
// is typed instead: OK starts typing, the number keys fill it in, Left erases a
// digit (or cancels when there are none) and OK saves it once it's full.
// Keys arrive from the remotes as PageUp/PageDown (up/down), ArrowLeft/ArrowRight,
// Enter and the digits 0-9; the arrow keys, Escape and mouse clicks also work in a
// browser.

const params = new URLSearchParams(window.location.search);
const LOGO = params.get('logo');

let schema = [];
let groups = [];
let values = {};
// the sub-menu being shown (a group key), or null for the main menu
let view = null;
let selected = 0;
// index of the row whose drop-down is open, or -1 when none is
let openRow = -1;
let optionCursor = 0;
// index of the typed-in row being edited, or -1, and what's been typed so far
let editRow = -1;
let draft = '';
let busy = false;
let statusTimer = null;
// where the cursor was on the main menu, so going back lands on the sub-menu's row
let mainSelected = 0;

// the rows of the menu being shown: {type: 'setting'|'group'|'back'|'exit', ...}
function rows() {
  if (view) {
    return [
      ...schema.filter(e => e.group === view).map(entry => ({ type: 'setting', entry })),
      { type: 'back' },
    ];
  }
  return [
    ...groups.filter(g => schema.some(e => e.group === g.key)).map(group => ({ type: 'group', group })),
    ...schema.filter(e => !e.group).map(entry => ({ type: 'setting', entry })),
    { type: 'exit' },
  ];
}

function optionIndex(entry) {
  const i = entry.options.findIndex(o => o.value === values[entry.key]);
  return i < 0 ? 0 : i;
}

function render() {
  const list = document.getElementById('menu-list');
  list.replaceChildren();
  let selectedEl = null;
  let dropdownEl = null;

  rows().forEach((row, i) => {
    const isOpen = i === openRow || i === editRow;
    const el = document.createElement('div');
    el.className = 'menu-row' + (i === selected && !isOpen ? ' selected' : '')
      + (i === openRow ? ' open' : '') + (i === editRow ? ' typing' : '');
    if (row.type === 'back' || row.type === 'exit') el.classList.add('action');
    el.addEventListener('click', () => {
      selected = i;
      if (isOpen) closeDropdown(); else activate();
    });

    if (row.type === 'setting') {
      const label = document.createElement('span');
      label.textContent = row.entry.label;
      const value = document.createElement('span');
      value.className = 'row-value';
      const text = document.createElement('span');
      const caret = document.createElement('span');
      caret.className = 'caret';
      if (row.entry.digits) {
        // while typing, blanks show how many digits are still to come
        text.className = 'typed';
        text.textContent = i === editRow ? draft.padEnd(row.entry.digits, '_') : values[row.entry.key];
        caret.textContent = i === editRow ? '' : '✎';
      } else {
        text.textContent = row.entry.options[optionIndex(row.entry)].label;
        caret.textContent = isOpen ? '▲' : '▼';
      }
      value.append(text, caret);
      el.append(label, value);
    } else if (row.type === 'group') {
      const label = document.createElement('span');
      label.textContent = row.group.label;
      const caret = document.createElement('span');
      caret.className = 'caret';
      caret.textContent = '▶';
      el.append(label, caret);
    } else {
      el.textContent = row.type === 'back' ? '◀  Back' : 'Exit Settings';
    }

    list.appendChild(el);
    if (i === selected) selectedEl = el;
    if (i === openRow) {
      dropdownEl = renderDropdown(row.entry);
      list.appendChild(dropdownEl);
    }
  });

  // the list scrolls when it doesn't fit - keep the cursor (and an open drop-down) in view
  const cursorEl = dropdownEl ? dropdownEl.querySelector('.menu-option.cursor') : selectedEl;
  if (cursorEl) cursorEl.scrollIntoView({ block: 'nearest' });

  const group = groups.find(g => g.key === view);
  document.getElementById('menu-title').textContent = group ? `Settings  ›  ${group.label}` : 'Settings';
  updateInfo();
  updateFooter();
}

function renderDropdown(entry) {
  const box = document.createElement('div');
  box.className = 'menu-dropdown';
  const current = optionIndex(entry);
  entry.options.forEach((option, i) => {
    const item = document.createElement('div');
    item.className = 'menu-option' + (i === optionCursor ? ' cursor' : '');
    const check = document.createElement('span');
    check.className = 'check';
    check.textContent = i === current ? '✓' : '';
    const text = document.createElement('span');
    text.textContent = option.label;
    item.append(check, text);
    item.addEventListener('click', e => {
      e.stopPropagation();
      optionCursor = i;
      confirmOption();
    });
    box.appendChild(item);
  });
  return box;
}

function updateInfo() {
  const label = document.getElementById('info-label');
  const desc = document.getElementById('info-desc');
  const row = rows()[selected];
  if (!row) return;
  // in an open list, an option with its own description is described while the cursor is on it
  const option = openRow >= 0 ? rows()[openRow].entry.options[optionCursor] : null;
  if (option && option.description) {
    label.textContent = option.label;
    desc.textContent = option.description;
  } else if (row.type === 'setting') {
    label.textContent = row.entry.label;
    desc.textContent = row.entry.description || '';
  } else if (row.type === 'group') {
    label.textContent = row.group.label;
    desc.textContent = row.group.description || '';
  } else if (row.type === 'back') {
    label.textContent = 'Back';
    desc.textContent = 'Go back to the main settings menu.';
  } else {
    label.textContent = 'Exit Settings';
    desc.textContent = 'Go back to the channel you were watching.';
  }
}

function updateFooter() {
  const row = rows()[selected];
  const back = view ? ['◀', 'Back'] : ['MENU', 'Exit'];
  let hints;
  if (editRow >= 0) {
    hints = [['0-9', 'Type'], ['◀', 'Erase'], ['OK', 'Save']];
  } else if (openRow >= 0) {
    hints = [['▲▼', 'Choose'], ['OK', 'Confirm'], ['◀', 'Cancel']];
  } else if (row && row.type === 'setting') {
    hints = [['▲▼', 'Select'], ['OK', 'Open'], back];
  } else if (row && row.type === 'group') {
    hints = [['▲▼', 'Select'], ['OK', 'Open'], back];
  } else if (row && row.type === 'back') {
    hints = [['▲▼', 'Select'], ['OK', 'Back'], ['MENU', 'Exit']];
  } else {
    hints = [['▲▼', 'Select'], ['OK', 'Exit'], ['MENU', 'Exit']];
  }
  const footer = document.getElementById('menu-footer');
  footer.replaceChildren(...hints.map(([key, action]) => {
    const span = document.createElement('span');
    const b = document.createElement('b');
    b.textContent = key;
    span.append(b, ` ${action}`);
    return span;
  }));
}

function showStatus(text) {
  const el = document.getElementById('info-status');
  el.textContent = text;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => { el.textContent = ''; }, 4000);
}

// OK (or a click) on the selected row
function activate() {
  const row = rows()[selected];
  if (!row) return;
  if (row.type === 'setting' && row.entry.digits) startTyping();
  else if (row.type === 'setting') openDropdown();
  else if (row.type === 'group') enterGroup(row.group.key);
  else if (row.type === 'back') leaveGroup();
  else closeMenu();
}

function enterGroup(key) {
  mainSelected = selected;
  view = key;
  selected = 0;
  openRow = -1;
  render();
}

function leaveGroup() {
  view = null;
  selected = mainSelected;
  openRow = -1;
  render();
}

function openDropdown() {
  const row = rows()[selected];
  if (!row || row.type !== 'setting') return;
  openRow = selected;
  // start on the current value so OK straight away changes nothing
  optionCursor = optionIndex(row.entry);
  render();
}

function startTyping() {
  editRow = selected;
  draft = '';
  render();
}

function stopTyping() {
  editRow = -1;
  draft = '';
  render();
}

async function saveTyped() {
  const row = rows()[editRow];
  if (!row || busy) return;
  const entry = row.entry;
  if (draft.length < entry.digits) {
    showStatus(`Type all ${entry.digits} digits`);
    return;
  }
  if (draft === values[entry.key]) {
    stopTyping();
    return;
  }
  busy = true;
  try {
    const res = await fetch(`/settings/${encodeURIComponent(entry.key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: draft })
    });
    if (!res.ok) {
      // the server says why - an unknown ZIP code, say - and the digits stay up to fix
      const detail = (await res.json().catch(() => ({}))).detail;
      showStatus(detail || 'Could not save - try again');
      return;
    }
    values = (await res.json()).values;
    showStatus(`${entry.label}: ${draft}`);
    stopTyping();
  } catch (e) {
    console.warn('setting change failed:', e);
    showStatus('Could not save - try again');
  } finally {
    busy = false;
  }
}

function typeDigit(d) {
  const row = rows()[editRow];
  if (!row || draft.length >= row.entry.digits) return;
  draft += d;
  render();
}

function closeDropdown() {
  openRow = -1;
  render();
}

async function confirmOption() {
  const row = rows()[openRow];
  if (!row || busy) return;
  const entry = row.entry;
  const choice = entry.options[optionCursor];
  if (choice.value === values[entry.key]) {
    closeDropdown();
    return;
  }
  busy = true;
  try {
    const res = await fetch(`/settings/${encodeURIComponent(entry.key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: choice.value })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    values = (await res.json()).values;
    openRow = -1;
    render();
    if (entry.key === 'aspect_ratio' && window.fs42Aspect) {
      window.fs42Aspect.apply(values.aspect_ratio);
    }
    if (entry.key === 'provider_logo') setupLogo();
    showStatus(`${entry.label}: ${choice.label}`);
  } catch (e) {
    console.warn('setting change failed:', e);
    showStatus('Could not save - try again');
  } finally {
    busy = false;
  }
}

function closeMenu() {
  fetch('/player/channels/settings/close', { method: 'POST' }).catch(e => {
    console.warn('close failed:', e);
  });
}

function move(dir) {
  if (openRow >= 0) {
    const count = rows()[openRow].entry.options.length;
    optionCursor = (optionCursor + dir + count) % count;
  } else {
    const count = rows().length;
    selected = (selected + dir + count) % count;
  }
  render();
}

document.addEventListener('keydown', e => {
  if (editRow >= 0) {
    // typing a value: only digits, erase, save and cancel do anything
    if (/^[0-9]$/.test(e.key)) typeDigit(e.key);
    else if (e.key === 'Enter') saveTyped();
    else if (e.key === 'ArrowLeft' || e.key === 'Backspace') {
      if (draft) {
        draft = draft.slice(0, -1);
        render();
      } else stopTyping();
    } else if (e.key === 'Escape') stopTyping();
    else return;
    e.preventDefault();
    return;
  }
  switch (e.key) {
    case 'PageUp':
    case 'ArrowUp':
      move(-1);
      break;
    case 'PageDown':
    case 'ArrowDown':
      move(1);
      break;
    case 'ArrowLeft':
      if (openRow >= 0) closeDropdown();
      else if (view) leaveGroup();
      break;
    case 'ArrowRight':
      if (openRow < 0) {
        const row = rows()[selected];
        if (row && row.type === 'setting' && row.entry.digits) startTyping();
        else if (row && row.type === 'setting') openDropdown();
        else if (row && row.type === 'group') enterGroup(row.group.key);
      }
      break;
    case 'Enter':
      if (openRow >= 0) confirmOption();
      else activate();
      break;
    case 'Escape':
      if (openRow >= 0) closeDropdown();
      else if (view) leaveGroup();
      else closeMenu();
      break;
    default:
      return;
  }
  e.preventDefault();
});

const LOGO_DIR = '/static/customguide/logos/';

async function setupLogo() {
  const holder = document.getElementById('menu-logo');
  // the Provider Logo setting wins over the logo= in the URL; for Random the
  // server picks one, like it does for the guide
  let file = values.provider_logo;
  if (file === 'random') {
    try {
      file = (await (await fetch('/settings/provider_logo/pick')).json()).file;
    } catch (e) {
      file = null;
    }
  }
  holder.replaceChildren();
  const src = file ? LOGO_DIR + encodeURIComponent(file) : LOGO;
  if (src) {
    const img = document.createElement('img');
    img.src = src;
    img.alt = '';
    holder.appendChild(img);
  } else {
    const text = document.createElement('span');
    text.className = 'text-logo';
    text.textContent = 'FS42';
    holder.appendChild(text);
  }
}

function startClock() {
  const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  function tick() {
    const now = new Date();
    document.getElementById('clock-day').textContent =
      `${days[now.getDay()]}, ${now.getMonth() + 1}/${now.getDate()}`;
    document.getElementById('clock-time').textContent =
      now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  tick();
  setInterval(tick, 1000);
}

async function init() {
  startClock();
  try {
    const res = await fetch('/settings');
    const data = await res.json();
    schema = data.schema;
    groups = data.groups || [];
    values = data.values;
  } catch (e) {
    console.warn('could not load settings:', e);
    showStatus('Could not load settings');
  }
  setupLogo();
  render();
}

init();
