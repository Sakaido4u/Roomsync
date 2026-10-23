// Screen 2: the room grid (main screen). API contract endpoints 8 and 9.
//
// Pick a building, date and time slot (default: now). Each room card shows
// its booking status and its occupancy as two separate tags, plus who booked
// it and why. While the slot includes the current time, the grid refreshes
// every 5 seconds so camera changes show up live.

import { ApiError, api, query } from '../api.js';
import { adminButtons } from '../bookings-ui.js';
import {
  ROOM_TYPE_LABELS, alertBox, bookingTag, h, hhmm, isoDate, minutesOf, niceDate, occupancyTag,
} from '../ui.js';

const LIVE_REFRESH_MS = 5000;
const SLOT_MINUTES = 60;
const STAFF = ['teacher', 'admin'];

// The slot that contains "now": from the last quarter hour, one hour long.
function nowSlot() {
  const now = new Date();
  const start = new Date(now);
  start.setMinutes(Math.floor(now.getMinutes() / 15) * 15, 0, 0);
  let end = new Date(start.getTime() + SLOT_MINUTES * 60000);
  if (end.getDate() !== start.getDate()) end = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 23, 59);
  return { date: isoDate(start), start: hhmm(start), end: hhmm(end) };
}

function includesNow(slot) {
  const now = new Date();
  if (slot.date !== isoDate(now)) return false;
  const minutes = now.getHours() * 60 + now.getMinutes();
  return minutesOf(slot.start) <= minutes && minutes < minutesOf(slot.end);
}

export function renderRooms({ main, params, user }) {
  let slot = {
    date: params.get('date') || nowSlot().date,
    start: params.get('start') || nowSlot().start,
    end: params.get('end') || nowSlot().end,
    building: params.get('building') || '',
  };
  let timer = null;
  let loadId = 0;          // ignores slow replies that arrive after a newer request
  let firstLoad = true;

  // --- Layout ----------------------------------------------------------------

  const buildingSelect = h('select', { id: 'building', name: 'building' },
    h('option', { value: '' }, 'All buildings'));
  const dateInput = h('input', { id: 'date', name: 'date', type: 'date', value: slot.date, required: true });
  const startInput = h('input', { id: 'start', name: 'start', type: 'time', value: slot.start, step: '300', required: true });
  const endInput = h('input', { id: 'end', name: 'end', type: 'time', value: slot.end, step: '300', required: true });

  const toolbar = h('form', { class: 'toolbar', 'aria-label': 'Choose building and time slot' },
    h('div', { class: 'field field--building' }, h('label', { for: 'building' }, 'Building'), buildingSelect),
    h('div', { class: 'field field--date' }, h('label', { for: 'date' }, 'Date'), dateInput),
    h('div', { class: 'field' }, h('label', { for: 'start' }, 'From'), startInput),
    h('div', { class: 'field' }, h('label', { for: 'end' }, 'To'), endInput),
    h('button', { class: 'btn btn--secondary toolbar__now', type: 'button', onclick: jumpToNow }, 'Now'));

  const live = h('span', { class: 'live live--off' });
  const counts = h('div', { class: 'statusbar__counts', 'aria-live': 'polite' });
  const message = h('div');
  const grid = h('ul', { class: 'room-grid', 'aria-label': 'Rooms', 'aria-busy': 'true' });

  main.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', {},
        h('h1', {}, 'Rooms now'),
        h('p', { id: 'slot-summary' }))),
    toolbar,
    h('div', { class: 'statusbar' }, counts, live),
    message,
    grid);

  toolbar.addEventListener('change', readToolbar);
  toolbar.addEventListener('submit', event => {
    event.preventDefault();
    readToolbar();
  });

  // --- Reading the filters -------------------------------------------------

  function readToolbar() {
    const next = {
      date: dateInput.value,
      start: startInput.value,
      end: endInput.value,
      building: buildingSelect.value,
    };
    if (!next.date || !next.start || !next.end) return;
    if (minutesOf(next.end) <= minutesOf(next.start)) {
      message.replaceChildren(alertBox('"To" must be after "From".'));
      return;
    }
    slot = next;
    // Keep the choice in the address, so refreshing the page keeps it.
    history.replaceState(null, '', `#/rooms${query(slot)}`);
    load(true);
  }

  function jumpToNow() {
    const now = nowSlot();
    dateInput.value = now.date;
    startInput.value = now.start;
    endInput.value = now.end;
    readToolbar();
  }

  // --- Loading -------------------------------------------------------------

  async function loadBuildings() {
    try {
      const rooms = await api('/rooms');
      const buildings = [...new Set(rooms.map(r => r.building))].sort();
      buildingSelect.append(...buildings.map(b => h('option', { value: b }, b)));
      buildingSelect.value = slot.building;
    } catch {
      // The grid itself shows any error; the building list can stay short.
    }
  }

  async function load(showSkeleton = false) {
    const id = ++loadId;
    clearTimeout(timer);
    const isLive = includesNow(slot);
    if (showSkeleton || firstLoad) drawSkeleton();
    document.getElementById('slot-summary').textContent =
      `${slot.building || 'All buildings'} · ${niceDate(slot.date)} · ${slot.start}–${slot.end}`;

    try {
      const rooms = await api(`/rooms/status${query(slot)}`);
      if (id !== loadId) return;
      message.replaceChildren();
      drawRooms(rooms, isLive);
    } catch (error) {
      if (id !== loadId) return;
      if (error instanceof ApiError && error.status === 401) return;   // app.js shows the login page
      grid.setAttribute('aria-busy', 'false');
      message.replaceChildren(alertBox(error.message || 'Could not load the rooms.'));
      if (firstLoad) {
        grid.replaceChildren(h('li', { class: 'empty-state' },
          h('div', { class: 'empty-state__icon', 'aria-hidden': 'true' }, '⚠'),
          h('h2', {}, 'Rooms could not be loaded'),
          h('button', { class: 'btn btn--primary', type: 'button', onclick: () => load(true) }, 'Try again')));
      }
    }
    firstLoad = false;

    live.className = isLive ? 'live' : 'live live--off';
    live.replaceChildren(h('span', { class: 'live__dot', 'aria-hidden': 'true' }),
      isLive ? 'Live · updates every 5 s' : 'Occupancy is shown live only for the current time');
    if (isLive) timer = setTimeout(() => load(false), LIVE_REFRESH_MS);
  }

  // --- Drawing -------------------------------------------------------------

  function drawSkeleton() {
    grid.setAttribute('aria-busy', 'true');
    grid.replaceChildren(...Array.from({ length: 6 }, () =>
      h('li', { class: 'room-card', 'aria-hidden': 'true' },
        h('div', { class: 'skeleton skeleton--line', style: 'width:40%;height:20px' }),
        h('div', { class: 'skeleton skeleton--line', style: 'width:65%' }),
        h('div', { class: 'tags' }, h('div', { class: 'skeleton skeleton--tag' }),
          h('div', { class: 'skeleton skeleton--tag', style: 'width:130px' })),
        h('div', { class: 'skeleton', style: 'height:52px' }))));
  }

  function drawRooms(rooms, isLive) {
    grid.setAttribute('aria-busy', 'false');
    const free = rooms.filter(r => r.booking_status === 'not_booked').length;
    const withPeople = rooms.filter(r => r.occupancy === 'people_detected').length;
    counts.replaceChildren(...[
      h('span', {}, h('strong', {}, rooms.length), rooms.length === 1 ? ' room' : ' rooms'),
      h('span', {}, h('strong', {}, free), ' not booked'),
      isLive && h('span', {}, h('strong', {}, withPeople), ' with people detected'),
    ].filter(Boolean));

    if (rooms.length === 0) {
      grid.replaceChildren(h('li', { class: 'empty-state' },
        h('div', { class: 'empty-state__icon', 'aria-hidden': 'true' }, '🏫'),
        h('h2', {}, 'No rooms here'),
        h('p', {}, slot.building ? `There are no rooms in ${slot.building}.` : 'No rooms have been added yet.')));
      return;
    }
    grid.replaceChildren(...rooms.map(roomCard));
  }

  function roomCard(room) {
    const b = room.booking;
    const canReserve = STAFF.includes(user.role) && room.booking_status === 'not_booked';
    const reserveLink = `#/reserve${query({ room: room.room_id, date: slot.date, start: slot.start, end: slot.end })}`;

    return h('li', { class: 'room-card', 'aria-labelledby': `room-${room.room_id}` },
      h('div', { class: 'room-card__head' },
        h('div', {},
          h('h2', { class: 'room-card__id', id: `room-${room.room_id}` }, room.room_id),
          h('div', { class: 'room-card__name' }, room.name)),
        h('span', { class: 'room-card__type' }, ROOM_TYPE_LABELS[room.type] || room.type)),
      h('div', { class: 'tags' },
        bookingTag(room.booking_status),
        occupancyTag(room.occupancy, room.head_count)),
      b
        ? h('div', { class: 'room-card__booking' },
          h('span', { class: 'room-card__who' }, b.booked_by.name),
          h('span', { class: 'room-card__what' },
            [b.purpose, b.class_id].filter(Boolean).join(' · ')),
          h('span', { class: 'room-card__what' }, `${b.start}–${b.end}`))
        : h('p', { class: 'room-card__free' }, 'Free for this whole slot.'),
      canReserve
        ? h('div', { class: 'room-card__actions' },
          h('a', { class: 'btn btn--primary btn--small', href: reserveLink,
            'aria-label': `Reserve ${room.room_id}` }, 'Reserve'))
        : null,
      b && user.role === 'admin' && !bookingEnded(b)
        ? h('div', { class: 'room-card__actions' },
          adminButtons({ ...b, room_id: room.room_id, booking_status: room.booking_status }, () => load(false)))
        : null);
  }

  function bookingEnded(b) {
    return new Date(`${b.date}T${b.end}:00+05:30`) <= new Date();
  }

  loadBuildings();
  load(true);

  // Leaving the screen: stop the live refresh.
  return () => {
    loadId++;
    clearTimeout(timer);
  };
}
