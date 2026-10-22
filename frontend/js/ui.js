// Small helpers shared by every screen.

// Creates an element. Text is always added as plain text (never as HTML),
// so a booking purpose like "<script>" is shown, not run.
//   h('button', { class: 'btn', onclick: save }, 'Save')
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) continue;
    if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2), value);
    } else if (key === 'class') {
      el.className = value;
    } else if (value === true) {
      el.setAttribute(key, '');
    } else {
      el.setAttribute(key, value);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

// Simple line icons drawn with SVG, so they take the text colour and stay
// sharp at any size (emoji look different on every device).
const ICONS = {
  // A room (square) with a person (dot) inside: the RoomSync mark.
  logo: '<rect x="5" y="5" width="14" height="14" rx="3"/><circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
};

export function icon(name, size = 20) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = ICONS[name];   // fixed shapes from this file, never user data
  return svg;
}

// --- Dialogs ----------------------------------------------------------------

// Opens a pop-up dialog. The browser's <dialog> keeps keyboard focus inside
// it, closes on Esc, and puts focus back where it was afterwards.
//   const d = openDialog({ title: 'Remove booking', body: [...], actions: [...] });
//   d.close();
export function openDialog({ title, body, actions = [], wide = false }) {
  const titleId = `dialog-title-${Math.random().toString(36).slice(2)}`;
  const dialog = h('dialog', { class: `dialog${wide ? ' dialog--wide' : ''}`, 'aria-labelledby': titleId },
    h('div', { class: 'dialog__head' },
      h('h2', { id: titleId }, title),
      h('button', { class: 'dialog__close', type: 'button', 'aria-label': 'Close', onclick: () => close() }, '✕')),
    h('div', { class: 'dialog__body' }, body),
    actions.length ? h('div', { class: 'dialog__actions' }, actions) : null);
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  // Clicking the dark area outside the box closes it too.
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.showModal();
  function close() { if (dialog.open) dialog.close(); }
  return { el: dialog, close };
}

// "Are you sure?" with a clear consequence. Resolves true or false.
export function confirmDialog({ title, message, confirmLabel, danger = false }) {
  return new Promise(resolve => {
    let answered = false;
    const yes = h('button', { class: `btn ${danger ? 'btn--danger' : 'btn--primary'}`, type: 'button' }, confirmLabel);
    const no = h('button', { class: 'btn btn--secondary', type: 'button' }, 'Go back');
    const d = openDialog({ title, body: h('p', {}, message), actions: [no, yes] });
    yes.addEventListener('click', () => { answered = true; resolve(true); d.close(); });
    no.addEventListener('click', () => d.close());
    d.el.addEventListener('close', () => { if (!answered) resolve(false); });
    yes.focus();
  });
}

// Runs an async action with a button showing "Please wait…" meanwhile.
// Returns whatever the action returns; errors are passed on to the caller.
export async function busy(button, work) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Please wait…';
  try {
    return await work();
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

export function loading(text = 'Loading…') {
  return h('div', { class: 'loading', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), text);
}

export function emptyState(iconText, title, text, action = null) {
  return h('div', { class: 'empty-state' },
    h('div', { class: 'empty-state__icon', 'aria-hidden': 'true' }, iconText),
    h('h2', {}, title),
    text ? h('p', {}, text) : null,
    action);
}

export function toast(message, kind = 'info') {
  const box = document.getElementById('toasts');
  const item = h('div', { class: `toast toast--${kind}` }, message);
  box.append(item);
  setTimeout(() => item.remove(), 4500);
}

export function alertBox(message, kind = 'error') {
  const icon = { error: '!', success: '✓', info: 'i' }[kind];
  return h('div', { class: `alert alert--${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    h('span', { class: 'alert__icon', 'aria-hidden': 'true' }, icon),
    h('span', {}, message));
}

// --- Labels from the API contract's "Fixed values" table -----------------

export const ROLE_LABELS = {
  student: 'Student',
  teacher: 'Teacher',
  admin: 'Admin',
  super_admin: 'Super admin',
};

export const ROOM_TYPE_LABELS = {
  classroom: 'Classroom',
  lab: 'Lab',
  meeting_room: 'Meeting room',
};

const BOOKING_TAGS = {
  not_booked: { icon: '○', label: 'Not booked' },
  scheduled: { icon: '▣', label: 'Scheduled' },
  reserved: { icon: '◆', label: 'Reserved' },
  overridden: { icon: '⇄', label: 'Overridden' },
  released: { icon: '↺', label: 'Released' },
  cancelled: { icon: '✕', label: 'Cancelled' },
};

const OCCUPANCY_TAGS = {
  people_detected: { icon: '●', label: 'People detected' },
  not_detected: { icon: '○', label: 'Not detected' },
  no_data: { icon: '–', label: 'No camera data' },
};

// Each tag shows a symbol AND words, never colour alone.
export function bookingTag(status) {
  const tag = BOOKING_TAGS[status] || { icon: '?', label: status };
  return h('span', { class: `tag tag--${status}` },
    h('span', { class: 'tag__icon', 'aria-hidden': 'true' }, tag.icon),
    h('span', { class: 'visually-hidden' }, 'Booking: '),
    tag.label);
}

export function occupancyTag(occupancy, headCount) {
  if (!occupancy) {
    return h('span', { class: 'tag tag--not_live', title: 'Occupancy is only shown for the current time' },
      h('span', { class: 'tag__icon', 'aria-hidden': 'true' }, '◷'),
      h('span', { class: 'visually-hidden' }, 'Occupancy: '),
      'Not live');
  }
  const tag = OCCUPANCY_TAGS[occupancy] || { icon: '?', label: occupancy };
  const count = occupancy === 'people_detected' && headCount ? ` · ${headCount}` : '';
  return h('span', { class: `tag tag--${occupancy}` },
    h('span', { class: 'tag__icon', 'aria-hidden': 'true' }, tag.icon),
    h('span', { class: 'visually-hidden' }, 'Occupancy: '),
    tag.label + count);
}

// --- Dates and times (India time, as the API uses) ------------------------

// "2026-11-03" for <input type="date"> and the API.
export function isoDate(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// "15:00"
export function hhmm(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// "2026-11-03" -> "Tue 3 Nov"
export function niceDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', {
    weekday: 'short', day: 'numeric', month: 'short',
  });
}

// ISO date-time -> "3 Nov, 15:04" (or "Today, 15:04")
export function niceDateTime(isoDateTime) {
  const d = new Date(isoDateTime);
  const time = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
  if (isoDate(d) === isoDate(new Date())) return `Today, ${time}`;
  return `${d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}, ${time}`;
}

export function todayIso() {
  return isoDate(new Date());
}

export function minutesOf(time) {
  const [h, m] = time.split(':').map(Number);
  return h * 60 + m;
}
