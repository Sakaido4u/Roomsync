// Booking pieces used on several screens:
// - bookingBox(): a summary of one booking,
// - conflictBody(): what the "already booked" pop-up shows (409 reply),
// - openAdminChange(): the admin's override / reschedule / remove dialogs,
//   which always need a reason (API contract endpoints 15, 16, 17).

import { ApiError, api } from './api.js';
import { alertBox, bookingTag, busy, h, niceDate, openDialog, toast } from './ui.js';

export function bookingBox(b) {
  return h('div', { class: 'booking-box' },
    h('div', { class: 'booking-box__row' },
      b.booking_status ? bookingTag(b.booking_status) : null,
      h('strong', {}, b.room_id || '')),
    h('dl', {},
      h('dt', {}, 'When'), h('dd', {}, `${niceDate(b.date)}, ${b.start}–${b.end}`),
      h('dt', {}, 'Booked by'), h('dd', {}, b.booked_by?.name || '—'),
      h('dt', {}, 'Purpose'), h('dd', {}, b.purpose),
      b.class_id ? [h('dt', {}, 'Class'), h('dd', {}, b.class_id)] : null));
}

// The body of the "already booked" pop-up for a 409 conflict reply.
// onPickRoom(roomId) is called when a free room is chosen.
export function conflictBody(errorBody, roomId, onPickRoom) {
  const existing = errorBody.existing_booking;
  const free = errorBody.free_rooms || [];
  return [
    h('p', {}, errorBody.message || 'This room is already booked for that time.'),
    existing ? bookingBox({ ...existing, room_id: roomId }) : null,
    h('h3', { style: 'font-size:1rem' }, free.length ? 'Free rooms at the same time' : 'No other room is free at that time.'),
    free.length
      ? h('ul', { class: 'choice-list' }, free.map(room =>
        h('li', {}, h('button', { class: 'btn btn--secondary', type: 'button', onclick: () => onPickRoom(room.room_id) },
          h('span', {}, h('strong', {}, room.room_id), ` · ${room.name}`),
          h('span', { 'aria-hidden': 'true' }, 'Book this →')))))
      : null,
  ];
}

// --- Admin changes ------------------------------------------------------------

function reasonField(id) {
  return h('div', { class: 'field' },
    h('label', { for: id }, 'Reason (shown to the teacher and the class CR)'),
    h('textarea', { id, name: 'reason', required: true, maxlength: '500',
      placeholder: 'e.g. Department event moved to this room' }));
}

function notifiedText(list) {
  return list?.length ? ` Notified: ${list.join(', ')}.` : '';
}

// Shows the API error inside the dialog (or the conflict details on 409).
function showError(form, error, roomId) {
  form.querySelector('.dialog-error')?.remove();
  const box = h('div', { class: 'dialog-error' });
  if (error instanceof ApiError && error.status === 409) {
    box.append(alertBox(error.message), ...conflictBody(error.body, roomId, picked => {
      form.room_id.value = picked;
      box.remove();
    }).filter(Boolean));
  } else {
    box.append(alertBox(error.message || 'Something went wrong.'));
  }
  form.prepend(box);
}

// kind: 'override' | 'reschedule' | 'remove'. booking needs booking_id,
// room_id, date, start, end, purpose, booked_by. onDone() runs after success.
export async function openAdminChange(kind, booking, onDone) {
  const titles = { override: 'Override booking', reschedule: 'Reschedule booking', remove: 'Remove booking' };
  const intro = {
    override: 'The room and time go to a new booking in your name. The current booking is marked overridden.',
    reschedule: 'Move this booking to another room or time. It keeps its status.',
    remove: 'The booking is cancelled and the room becomes free.',
  }[kind];

  const form = h('form', { class: 'stack', novalidate: true });
  form.append(bookingBox(booking), h('p', { class: 'muted' }, intro));

  if (kind === 'override') {
    form.append(
      h('div', { class: 'field' }, h('label', { for: 'ov-purpose' }, 'New purpose'),
        h('input', { id: 'ov-purpose', name: 'purpose', required: true, maxlength: '200' })),
      h('div', { class: 'field' }, h('label', { for: 'ov-class' }, 'Class (optional)'),
        h('input', { id: 'ov-class', name: 'class_id', placeholder: 'e.g. CSE-7A' })));
  }
  if (kind === 'reschedule') {
    const roomSelect = h('select', { id: 'rs-room', name: 'room_id' });
    try {
      const rooms = await api('/rooms');
      roomSelect.append(...rooms.map(r => h('option', { value: r.room_id }, `${r.room_id} · ${r.name}`)));
    } catch {
      roomSelect.append(h('option', { value: booking.room_id }, booking.room_id));
    }
    roomSelect.value = booking.room_id;
    form.append(h('div', { class: 'form-grid' },
      h('div', { class: 'field span-2' }, h('label', { for: 'rs-room' }, 'Room'), roomSelect),
      h('div', { class: 'field span-2' }, h('label', { for: 'rs-date' }, 'Date'),
        h('input', { id: 'rs-date', name: 'date', type: 'date', value: booking.date, required: true })),
      h('div', { class: 'field' }, h('label', { for: 'rs-start' }, 'From'),
        h('input', { id: 'rs-start', name: 'start', type: 'time', value: booking.start, required: true })),
      h('div', { class: 'field' }, h('label', { for: 'rs-end' }, 'To'),
        h('input', { id: 'rs-end', name: 'end', type: 'time', value: booking.end, required: true }))));
  }
  form.append(reasonField(`${kind}-reason`));

  const submit = h('button', { class: `btn ${kind === 'override' ? 'btn--primary' : kind === 'remove' ? 'btn--danger' : 'btn--primary'}`, type: 'submit' },
    { override: 'Override', reschedule: 'Move booking', remove: 'Remove booking' }[kind]);
  const cancel = h('button', { class: 'btn btn--secondary', type: 'button' }, 'Go back');
  form.append(h('div', { class: 'dialog__actions', style: 'padding:0' }, cancel, submit));

  const dialog = openDialog({ title: titles[kind], body: form, wide: kind === 'reschedule' });
  cancel.addEventListener('click', () => dialog.close());
  form.querySelector('input:not([type=date]):not([type=time]), textarea')?.focus();

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const reason = form.reason.value.trim();
    if (!reason) return showError(form, new Error('A reason is required for this change.'));
    const id = booking.booking_id;
    try {
      let message;
      if (kind === 'override') {
        const purpose = form.purpose.value.trim();
        if (!purpose) return showError(form, new Error('Enter the new purpose.'));
        const reply = await busy(submit, () => api(`/bookings/${id}/override`, {
          method: 'POST', body: { purpose, class_id: form.class_id.value.trim() || null, reason },
        }));
        message = `Booking overridden.${notifiedText(reply.notified)}`;
      } else if (kind === 'reschedule') {
        const reply = await busy(submit, () => api(`/bookings/${id}/reschedule`, {
          method: 'POST',
          body: { room_id: form.room_id.value, date: form.date.value, start: form.start.value, end: form.end.value, reason },
        }));
        message = `Booking moved to ${reply.room_id}, ${niceDate(reply.date)} ${reply.start}–${reply.end}.${notifiedText(reply.notified)}`;
      } else {
        const reply = await busy(submit, () => api(`/bookings/${id}/remove`, { method: 'POST', body: { reason } }));
        message = `Booking removed.${notifiedText(reply.notified)}`;
      }
      dialog.close();
      toast(message);
      onDone?.();
    } catch (error) {
      showError(form, error, form.room_id?.value || booking.room_id);
    }
  });
}

// Small row of the three admin buttons for one booking.
export function adminButtons(booking, onDone) {
  const button = (kind, label, cls = 'btn--secondary') =>
    h('button', { class: `btn ${cls} btn--small`, type: 'button',
      'aria-label': `${label} ${booking.room_id} ${booking.start}–${booking.end}`,
      onclick: () => openAdminChange(kind, booking, onDone) }, label);
  return [button('override', 'Override'), button('reschedule', 'Reschedule'), button('remove', 'Remove', 'btn--ghost')];
}
