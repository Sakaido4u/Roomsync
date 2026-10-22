// Screen 4: my bookings, with cancel (API contract endpoints 13 and 14).
//
// Teachers can cancel their own one-time reservations. Timetable classes
// (scheduled) can only be changed by an admin, so they have no cancel button.

import { api, query } from '../api.js';
import {
  alertBox, bookingTag, busy, confirmDialog, emptyState, h, loading, niceDate, toast, todayIso,
} from '../ui.js';

export function renderBookings({ main }) {
  let view = 'upcoming';     // 'upcoming' | 'past'

  const tabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Which bookings' });
  const content = h('div');
  main.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'My bookings'), h('p', {}, 'Rooms you have reserved, and your timetable classes.')),
      h('a', { class: 'btn btn--primary', href: '#/reserve' }, 'Reserve a room')),
    h('div', { style: 'margin-bottom:16px' }, tabs),
    content);

  function drawTabs() {
    tabs.replaceChildren(...[['upcoming', 'Upcoming'], ['past', 'Past']].map(([key, label]) =>
      h('button', { type: 'button', 'aria-pressed': String(view === key),
        onclick: () => { view = key; drawTabs(); load(); } }, label)));
  }

  async function load() {
    content.replaceChildren(loading());
    const today = todayIso();
    const range = view === 'upcoming' ? { from: today } : { to: today };
    try {
      let bookings = await api(`/bookings/mine${query(range)}`);
      const now = new Date();
      const ended = b => new Date(`${b.date}T${b.end}:00+05:30`) <= now;
      bookings = view === 'upcoming' ? bookings.filter(b => !ended(b)) : bookings.filter(ended).reverse();
      draw(bookings);
    } catch (error) {
      content.replaceChildren(alertBox(error.message));
    }
  }

  function draw(bookings) {
    if (!bookings.length) {
      content.replaceChildren(view === 'upcoming'
        ? emptyState('📅', 'No upcoming bookings', 'Rooms you reserve will appear here.',
          h('a', { class: 'btn btn--primary', href: '#/reserve' }, 'Reserve a room'))
        : emptyState('🗂', 'No past bookings', null));
      return;
    }
    const list = h('div');
    let day = null;
    let group = null;
    for (const b of bookings) {
      if (b.date !== day) {
        day = b.date;
        group = h('ul', { class: 'list' });
        list.append(h('h2', { class: 'list__day' }, niceDate(day)), group);
      }
      group.append(row(b));
    }
    content.replaceChildren(list);
  }

  function row(b) {
    const canCancel = view === 'upcoming' && b.booking_status === 'reserved';
    const actions = h('div', { class: 'row__actions' });
    if (canCancel) {
      const button = h('button', { class: 'btn btn--secondary btn--small', type: 'button',
        'aria-label': `Cancel ${b.room_id} ${niceDate(b.date)} ${b.start}–${b.end}` }, 'Cancel');
      button.addEventListener('click', () => cancel(b, button));
      actions.append(button);
    } else if (view === 'upcoming' && b.booking_status === 'scheduled') {
      actions.append(h('span', { class: 'row__meta' }, 'Timetable class · admin changes only'));
    }
    return h('li', { class: 'row' },
      h('div', { class: 'row__time' }, `${b.start}–${b.end}`),
      h('div', { class: 'row__main' },
        h('div', { class: 'tags' }, bookingTag(b.booking_status)),
        h('span', { class: 'row__title' }, `${b.room_id} · ${b.purpose}`),
        b.class_id ? h('span', { class: 'row__meta' }, `Class ${b.class_id}`) : null),
      actions);
  }

  async function cancel(b, button) {
    const sure = await confirmDialog({
      title: 'Cancel this booking?',
      message: `${b.room_id} on ${niceDate(b.date)}, ${b.start}–${b.end} (${b.purpose}) will be freed for others. This cannot be undone.`,
      confirmLabel: 'Cancel booking',
      danger: true,
    });
    if (!sure) return;
    try {
      await busy(button, () => api(`/bookings/${b.booking_id}`, { method: 'DELETE' }));
      toast('Booking cancelled. The room is free again.');
      load();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  drawTabs();
  load();
}
