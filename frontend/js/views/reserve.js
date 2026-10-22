// Screen 3: reserve a room (API contract endpoint 12).
//
// If the slot is taken, the backend replies 409 with who booked it, why, and
// free rooms at the same time; the "already booked" pop-up shows that and
// books a free room in one click. The side panel shows the chosen room's
// bookings for the day (endpoint 10), so clashes can be avoided up front.

import { ApiError, api, query } from '../api.js';
import { conflictBody } from '../bookings-ui.js';
import {
  alertBox, bookingTag, busy, emptyState, h, loading, minutesOf, niceDate, openDialog, toast, todayIso,
} from '../ui.js';

export function renderReserve({ main, params }) {
  const roomSelect = h('select', { id: 'room', name: 'room_id', required: true },
    h('option', { value: '' }, 'Choose a room…'));
  const form = h('form', { class: 'panel', novalidate: true },
    h('h2', {}, 'Booking details'),
    h('p', { class: 'panel__intro' }, 'For a one-time booking: an extra class, a meeting or an event.'),
    h('div', { class: 'form-grid' },
      h('div', { class: 'field span-2' }, h('label', { for: 'room' }, 'Room'), roomSelect),
      h('div', { class: 'field span-2' }, h('label', { for: 'date' }, 'Date'),
        h('input', { id: 'date', name: 'date', type: 'date', min: todayIso(), required: true,
          value: params.get('date') || todayIso() })),
      h('div', { class: 'field' }, h('label', { for: 'start' }, 'From'),
        h('input', { id: 'start', name: 'start', type: 'time', step: '300', required: true,
          value: params.get('start') || '' })),
      h('div', { class: 'field' }, h('label', { for: 'end' }, 'To'),
        h('input', { id: 'end', name: 'end', type: 'time', step: '300', required: true,
          value: params.get('end') || '' })),
      h('div', { class: 'field span-2' }, h('label', { for: 'purpose' }, 'Purpose'),
        h('input', { id: 'purpose', name: 'purpose', required: true, maxlength: '200',
          placeholder: 'e.g. Extra class - DBMS' })),
      h('div', { class: 'field span-2' }, h('label', { for: 'class-id' }, 'Class (optional)'),
        h('input', { id: 'class-id', name: 'class_id', list: 'my-classes', placeholder: 'e.g. CSE-7A',
          'aria-describedby': 'class-hint' }),
        h('datalist', { id: 'my-classes' }),
        h('span', { class: 'field__hint', id: 'class-hint' },
          "If set, that class's CR is told about changes to this booking."))),
    h('div', { class: 'form-actions' },
      h('button', { class: 'btn btn--primary', type: 'submit' }, 'Reserve room'),
      h('a', { class: 'btn btn--secondary', href: '#/rooms' }, 'Back to rooms')));

  const dayPanel = h('section', { class: 'panel', 'aria-labelledby': 'day-title' });

  main.replaceChildren(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Reserve a room'),
      h('p', {}, 'Pick a room and time. If it is already taken, you will see free rooms instead.'))),
    h('div', { class: 'split' }, form, dayPanel));

  // --- The chosen room's day ---------------------------------------------------

  let dayLoad = 0;
  async function drawDay() {
    const id = ++dayLoad;
    const room = form.room_id.value;
    const date = form.date.value;
    dayPanel.replaceChildren(h('h2', { id: 'day-title' }, room ? `${room} on ${date ? niceDate(date) : '…'}` : 'Room schedule'));
    if (!room || !date) {
      dayPanel.append(h('p', { class: 'panel__intro' }, 'Choose a room and date to see what is already booked.'));
      return;
    }
    dayPanel.append(loading());
    try {
      const bookings = await api(`/rooms/${encodeURIComponent(room)}/schedule${query({ date })}`);
      if (id !== dayLoad) return;
      dayPanel.lastChild.remove();
      dayPanel.append(bookings.length
        ? h('ul', { class: 'list' }, bookings.map(b => h('li', { class: 'booking-box' },
          h('div', { class: 'booking-box__row' }, h('strong', {}, `${b.start}–${b.end}`), bookingTag(b.booking_status)),
          h('span', {}, b.purpose), h('span', { class: 'muted' }, b.booked_by.name))))
        : emptyState('✓', 'Free all day', 'Nothing is booked in this room on this date yet.'));
    } catch (error) {
      if (id !== dayLoad) return;
      dayPanel.lastChild.remove();
      dayPanel.append(alertBox(error.message));
    }
  }
  form.room_id.addEventListener('change', drawDay);
  form.date.addEventListener('change', drawDay);

  // --- Loading choices -----------------------------------------------------------

  (async () => {
    try {
      const rooms = await api('/rooms');
      roomSelect.append(...rooms.map(r => h('option', { value: r.room_id }, `${r.room_id} · ${r.name} (${r.capacity} seats)`)));
      roomSelect.value = params.get('room') || '';
    } catch (error) {
      form.prepend(alertBox(error.message));
    }
    drawDay();
    try {
      const classes = await api('/classes/mine');
      document.getElementById('my-classes').append(...classes.map(c => h('option', { value: c.class_id }, c.name)));
    } catch { /* suggestions only */ }
  })();

  // --- Submitting -------------------------------------------------------------

  function values(roomId = form.room_id.value) {
    return {
      room_id: roomId,
      date: form.date.value,
      start: form.start.value,
      end: form.end.value,
      purpose: form.purpose.value.trim(),
      class_id: form.class_id.value.trim() || null,
    };
  }

  function problem(v) {
    if (!v.room_id) return 'Choose a room.';
    if (!v.date || !v.start || !v.end) return 'Choose the date and time.';
    if (minutesOf(v.end) <= minutesOf(v.start)) return '"To" must be after "From".';
    if (!v.purpose) return 'Enter the purpose.';
    return null;
  }

  async function reserve(v, button) {
    form.querySelector(':scope > .alert')?.remove();
    try {
      const booking = await busy(button, () => api('/bookings', { method: 'POST', body: v }));
      toast(`${booking.room_id} reserved for ${niceDate(booking.date)}, ${booking.start}–${booking.end}.`);
      location.hash = '#/bookings';
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) return showConflict(v, error.body);
      form.prepend(alertBox(error.message));
    }
  }

  function showConflict(v, body) {
    const dialog = openDialog({
      title: `${v.room_id} is already booked`,
      wide: true,
      body: conflictBody(body, v.room_id, async roomId => {
        dialog.close();
        form.room_id.value = roomId;
        drawDay();
        await reserve(values(roomId), form.querySelector('button[type=submit]'));
      }),
      actions: [h('button', { class: 'btn btn--secondary', type: 'button', onclick: () => dialog.close() },
        'Choose another time')],
    });
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    const v = values();
    const why = problem(v);
    if (why) {
      form.querySelector(':scope > .alert')?.remove();
      form.prepend(alertBox(why));
      return;
    }
    reserve(v, form.querySelector('button[type=submit]'));
  });
}
