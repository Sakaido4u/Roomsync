// Screen 5: notifications (API contract endpoints 22, 23, and 18 for the
// Keep / Release answer to a no-show reminder).

import { api, query } from '../api.js';
import { alertBox, busy, emptyState, h, loading, niceDateTime, toast } from '../ui.js';

const TYPES = {
  booking_overridden: { icon: '⇄', label: 'Booking taken over' },
  booking_rescheduled: { icon: '↻', label: 'Booking moved' },
  booking_removed: { icon: '✕', label: 'Booking removed' },
  no_show_reminder: { icon: '⏰', label: 'Is your room in use?' },
  booking_released: { icon: '↺', label: 'Booking released' },
};

export function renderNotifications({ main, refreshUnread }) {
  let unreadOnly = false;
  let items = [];

  const tabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Which notifications' });
  const markAll = h('button', { class: 'btn btn--secondary', type: 'button', onclick: markAllRead }, 'Mark all as read');
  const content = h('div');
  main.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Notifications'), h('p', {}, 'Changes to your bookings and no-show reminders.')),
      markAll),
    h('div', { style: 'margin-bottom:16px' }, tabs),
    content);

  function drawTabs() {
    tabs.replaceChildren(...[[false, 'All'], [true, 'Unread']].map(([value, label]) =>
      h('button', { type: 'button', 'aria-pressed': String(unreadOnly === value),
        onclick: () => { unreadOnly = value; drawTabs(); load(); } }, label)));
  }

  async function load() {
    content.replaceChildren(loading());
    try {
      items = await api(`/notifications${query({ unread: unreadOnly ? 'true' : '' })}`);
      draw();
    } catch (error) {
      content.replaceChildren(alertBox(error.message));
    }
  }

  function draw() {
    markAll.hidden = !items.some(n => !n.read);
    if (!items.length) {
      content.replaceChildren(emptyState('🔔', unreadOnly ? 'Nothing unread' : 'No notifications yet',
        'You will be told here (and by email) when a booking of yours changes.'));
      return;
    }
    content.replaceChildren(h('ul', { class: 'list' }, items.map(note)));
  }

  function note(n) {
    const type = TYPES[n.type] || { icon: 'i', label: n.type };
    const actions = h('div', { class: 'note__actions' });

    if (n.type === 'no_show_reminder' && n.booking_id) {
      const keep = h('button', { class: 'btn btn--primary btn--small', type: 'button' }, 'Keep the room');
      const release = h('button', { class: 'btn btn--secondary btn--small', type: 'button' }, 'Release it');
      keep.addEventListener('click', () => answer(n, 'keep', keep));
      release.addEventListener('click', () => answer(n, 'release', release));
      actions.append(keep, release);
    }
    if (!n.read) {
      const read = h('button', { class: 'btn btn--ghost btn--small', type: 'button' }, 'Mark as read');
      read.addEventListener('click', () => markRead(n, read));
      actions.append(read);
    }

    return h('li', { class: `note${n.read ? '' : ' note--unread'}` },
      h('span', { class: 'note__icon', 'aria-hidden': 'true' }, type.icon),
      h('div', { class: 'note__main' },
        h('div', { class: 'note__head' },
          h('span', {},
            h('span', { class: 'note__type' }, type.label),
            n.read ? null : h('span', { class: 'note__unread' }, ' · Unread')),
          h('time', { class: 'note__time', datetime: n.created_at }, niceDateTime(n.created_at))),
        h('p', { class: 'note__message' }, n.message),
        actions.childElementCount ? actions : null));
  }

  async function markRead(n, button) {
    try {
      await busy(button, () => api(`/notifications/${n.notification_id}/read`, { method: 'POST' }));
      n.read = true;
      if (unreadOnly) items = items.filter(x => x !== n);
      draw();
      refreshUnread();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function markAllRead() {
    try {
      await busy(markAll, () => Promise.all(items.filter(n => !n.read).map(n =>
        api(`/notifications/${n.notification_id}/read`, { method: 'POST' }))));
      toast('All notifications marked as read.');
      load();
      refreshUnread();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function answer(n, action, button) {
    try {
      await busy(button, () => api(`/bookings/${n.booking_id}/no-show-response`, {
        method: 'POST', body: { action },
      }));
      toast(action === 'keep'
        ? 'Thanks. The room stays booked.'
        : 'The room has been released for others.');
      if (!n.read) await api(`/notifications/${n.notification_id}/read`, { method: 'POST' }).catch(() => {});
      load();
      refreshUnread();
    } catch (error) {
      // e.g. "This booking is already released." when answering too late.
      toast(error.message, 'error');
    }
  }

  drawTabs();
  load();
}
