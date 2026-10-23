// Screen 1: the weekly timetable grid, the first page after login.
// API contract endpoints 26-28, 30 and 33 (and 12 and 34 to book a period).
//
// Laid out like the college's paper timetable: days down the side, periods
// across the top, a narrow LUNCH BREAK column, two-period labs as one merged
// cell, lab batches stacked, and whole-morning project blocks.
//
// - Teachers and admins start on their own week, students on their class's
//   sheet (with the course table underneath). Everyone can switch between
//   the Teacher, Class and Room views.
// - Today's row and the current period are highlighted, and the class
//   running now shows live people detection.
// - Teachers and admins click a free period's "+" to book it for one of
//   their subjects; a taken room shows the usual "already booked" pop-up.
// - On a phone it shows one day at a time; printing gives the paper sheet.

import { ApiError, api, query } from '../api.js';
import { adminButtons, conflictBody } from '../bookings-ui.js';
import {
  alertBox, bookingTag, busy, emptyState, h, isoDate, loading, niceDate, occupancyTag, openDialog, toast,
} from '../ui.js';

const LIVE_REFRESH_MS = 10000;
const STAFF = ['teacher', 'admin'];
const ACTIVE = ['scheduled', 'reserved'];
const VIEWS = [
  { kind: 'teacher', label: 'Teacher' },
  { kind: 'class', label: 'Class' },
  { kind: 'room', label: 'Room' },
];
// What the badge on a changed class says, by change-log action.
const CHANGE_LABELS = {
  reschedule: 'Moved',
  override: 'Overridden',
  remove: 'Removed',
  release: 'Released',
};
const PARAM_FOR = { teacher: 'teacher', class: 'class_id', room: 'room_id' };

// --- Small date helpers (the API's dates are India time, "YYYY-MM-DD") ------

function addDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  return isoDate(new Date(y, m - 1, d + days));
}

// "2026-07-20" -> "20/7/2026", as printed on the college sheet.
function sheetDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d}/${m}/${y}`;
}

// "2026-10-19" -> "Mon 19"
function shortDay(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' });
}

function startsInFuture(date, time) {
  return new Date(`${date}T${time}:00+05:30`) > new Date();
}

export function renderTimetable({ main, params, user }) {
  const isStaff = STAFF.includes(user.role);
  let view = {
    kind: params.get('view') || (isStaff ? 'teacher' : 'class'),
    id: params.get('id') || (isStaff ? user.college_id : user.class_id || ''),
  };
  let week = params.get('week') || '';        // empty = this week
  let body = null;                            // the last week reply
  let dayIndex = null;                        // the day shown on a phone
  let timer = null;
  let loadId = 0;

  // Lists for the pickers and the booking dialog, loaded once.
  const lists = { periods: [], teachers: [], classes: [], rooms: [], subjects: null, myPairs: null };

  // --- Layout ----------------------------------------------------------------

  const title = h('h1', {}, 'Timetable');
  const subtitle = h('p', {});
  const liveBox = h('div', { class: 'tt-live' });
  const viewTabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Show the timetable of a' });
  const pickerLabel = h('label', { for: 'tt-pick' }, 'Teacher');
  const picker = h('select', { id: 'tt-pick' });
  const weekLabel = h('span', { class: 'tt-week__label', 'aria-live': 'polite' });

  const toolbar = h('div', { class: 'toolbar tt-toolbar' },
    h('div', { class: 'field' }, h('span', { class: 'tt-toolbar__label' }, 'View'), viewTabs),
    h('div', { class: 'field tt-toolbar__pick' }, pickerLabel, picker),
    h('div', { class: 'field' },
      h('span', { class: 'tt-toolbar__label' }, 'Week'),
      h('div', { class: 'tt-week' },
        h('button', { class: 'btn btn--secondary btn--small', type: 'button', onclick: () => moveWeek(-7),
          'aria-label': 'Previous week' }, '‹ Previous'),
        h('button', { class: 'btn btn--secondary btn--small', type: 'button', onclick: () => setWeek('') },
          'This week'),
        h('button', { class: 'btn btn--secondary btn--small', type: 'button', onclick: () => moveWeek(7),
          'aria-label': 'Next week' }, 'Next ›'))),
    h('button', { class: 'btn btn--ghost btn--small tt-toolbar__print', type: 'button',
      onclick: () => window.print() }, 'Print'));

  const message = h('div');
  const content = h('div', { class: 'tt', 'aria-busy': 'true' }, loading('Loading the timetable…'));

  main.replaceChildren(
    h('div', { class: 'page-head tt-head' },
      h('div', {}, title, subtitle, weekLabel),
      liveBox),
    toolbar,
    message,
    content);

  picker.addEventListener('change', () => {
    view = { ...view, id: picker.value };
    load(true);
  });

  // --- Choosing what to show -----------------------------------------------

  function drawViewTabs() {
    viewTabs.replaceChildren(...VIEWS.map(v =>
      h('button', { type: 'button', 'aria-pressed': String(view.kind === v.kind),
        onclick: () => switchKind(v.kind) }, v.label)));
  }

  function optionsFor(kind) {
    if (kind === 'teacher') {
      return lists.teachers.map(t => ({ value: t.college_id,
        label: `${t.name}${t.initials ? ` (${t.initials})` : ''} · ${t.college_id}` }));
    }
    if (kind === 'class') {
      return lists.classes.map(c => ({ value: c.class_id,
        label: c.semester_label ? `${c.class_id} · ${c.semester_label}` : c.class_id }));
    }
    return lists.rooms.map(r => ({ value: r.room_id, label: `${r.room_id} · ${r.name}` }));
  }

  // A sensible first choice when switching view: yourself, your class, your
  // class's home room.
  function defaultId(kind) {
    const options = optionsFor(kind).map(o => o.value);
    const mine = {
      teacher: isStaff ? user.college_id : null,
      class: user.class_id,
      room: lists.classes.find(c => c.class_id === user.class_id)?.home_room_id,
    }[kind];
    return mine && options.includes(mine) ? mine : options[0] || '';
  }

  function switchKind(kind) {
    if (kind === view.kind) return;
    view = { kind, id: defaultId(kind) };
    load(true);
  }

  function drawPicker() {
    pickerLabel.textContent = VIEWS.find(v => v.kind === view.kind).label;
    const options = optionsFor(view.kind);
    // Keep a choice from the address even if the list does not have it.
    if (view.id && !options.some(o => o.value === view.id)) options.unshift({ value: view.id, label: view.id });
    picker.replaceChildren(...options.map(o => h('option', { value: o.value }, o.label)));
    picker.value = view.id;
  }

  function setWeek(iso) {
    week = iso;
    load(true);
  }

  function moveWeek(days) {
    if (body) setWeek(addDays(body.week_start, days));
  }

  // --- Loading ---------------------------------------------------------------

  async function loadLists() {
    const [periods, classes, rooms, teaching, people] = await Promise.all([
      api('/periods'),
      api('/classes'),
      api('/rooms'),
      api('/teaching'),
      user.role === 'admin' ? api('/users') : Promise.resolve([]),
    ]);
    lists.periods = periods.periods;
    lists.classes = classes;
    lists.rooms = rooms;
    // Teachers: everyone who teaches something, plus (for admins) every
    // teacher and admin, plus yourself.
    const byId = new Map();
    for (const row of teaching) byId.set(row.teacher.college_id, row.teacher);
    for (const p of people) {
      if (STAFF.includes(p.role) && !byId.has(p.college_id)) byId.set(p.college_id, { ...p, initials: null });
    }
    if (isStaff && !byId.has(user.college_id)) byId.set(user.college_id, { ...user, initials: null });
    lists.teachers = [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
    if (!view.id) view.id = defaultId(view.kind);
  }

  async function load(showLoading = false) {
    const id = ++loadId;
    clearTimeout(timer);
    drawViewTabs();
    drawPicker();
    history.replaceState(null, '', `#/timetable${query({ view: view.kind, id: view.id, week })}`);
    if (showLoading) {
      content.setAttribute('aria-busy', 'true');
      content.replaceChildren(loading('Loading the timetable…'));
    }
    if (!view.id) {
      content.setAttribute('aria-busy', 'false');
      content.replaceChildren(emptyState('📅', 'Nothing to show yet',
        `There is no ${view.kind} to show. Pick another view.`));
      return;
    }

    try {
      const reply = await api(`/timetable/week${query({ week_start: week, [PARAM_FOR[view.kind]]: view.id })}`);
      const courses = view.kind === 'class' ? await courseRows(view.id) : null;
      if (id !== loadId) return;
      body = reply;
      message.replaceChildren();
      draw(courses);
      if (thisWeek()) timer = setTimeout(() => load(false), LIVE_REFRESH_MS);
    } catch (error) {
      if (id !== loadId) return;
      if (error instanceof ApiError && error.status === 401) return;   // app.js shows the login page
      content.setAttribute('aria-busy', 'false');
      message.replaceChildren(alertBox(error.message || 'Could not load the timetable.'));
      if (showLoading || !body) {
        content.replaceChildren(emptyState('⚠', 'The timetable could not be loaded', null,
          h('button', { class: 'btn btn--primary', type: 'button', onclick: () => load(true) }, 'Try again')));
      }
    }
  }

  function thisWeek() {
    return body && body.today >= body.week_start && body.today <= addDays(body.week_start, 6);
  }

  // --- Drawing ---------------------------------------------------------------

  function draw(courses) {
    content.setAttribute('aria-busy', 'false');
    drawHead();
    if (dayIndex === null || dayIndex >= body.days.length) {
      const today = body.days.findIndex(d => d.date === body.today);
      dayIndex = today >= 0 ? today : 0;
    }
    const sheet = view.kind === 'class' ? sheetHeader(body.view.class_info) : null;
    // replaceChildren() would show a missing part as the word "null".
    content.replaceChildren(...[
      sheet,
      gridTable(),
      dayList(),
      courses ? courseTable(courses) : null,
      legend(),
    ].filter(Boolean));
  }

  function drawHead() {
    const v = body.view;
    if (v.kind === 'teacher') {
      title.textContent = v.teacher.name;
      subtitle.textContent = `${v.teacher.college_id}${v.teacher.initials ? ` · ${v.teacher.initials}` : ''}`;
    } else if (v.kind === 'class') {
      const c = v.class_info;
      title.textContent = `${c.class_id}${c.semester_label ? ` · ${c.semester_label}` : ''}`;
      subtitle.textContent = c.name;
    } else {
      title.textContent = v.room.room_id;
      subtitle.textContent = `${v.room.name} · ${v.room.capacity} seats`;
    }
    weekLabel.textContent = `Week of ${niceDate(body.week_start)} – ${niceDate(body.week_end)}`;

    const live = thisWeek();
    liveBox.replaceChildren(...[
      v.kind === 'room' && body.room_occupancy
        ? h('div', { class: 'tt-live__room' }, h('span', { class: 'muted' }, 'Now: '),
          occupancyTag(body.room_occupancy.occupancy, body.room_occupancy.head_count))
        : null,
      h('span', { class: live ? 'live' : 'live live--off' },
        h('span', { class: 'live__dot', 'aria-hidden': 'true' }),
        live ? 'This week · live detection updates every 10 s' : 'Not this week'),
    ].filter(Boolean));
  }

  // The paper sheet's header line, for a class.
  function sheetHeader(c) {
    const parts = [
      c.semester_label && ['SEMESTER', c.semester_label],
      c.home_room_id && ['Room No', c.home_room_id],
      c.wef_date && ['W.E.F', sheetDate(c.wef_date)],
    ].filter(Boolean);
    if (!parts.length) return null;
    return h('p', { class: 'tt-sheet' }, parts.map(([k, v], i) =>
      [i ? h('span', { class: 'tt-sheet__dot', 'aria-hidden': 'true' }, ' · ') : null,
        h('span', {}, `${k}: `, h('strong', {}, v))]));
  }

  // --- The full grid (laptop and print) -------------------------------------

  function gridTable() {
    const periods = lists.periods;
    const head = h('tr', {},
      h('th', { scope: 'col', class: 'tt-grid__corner' }, 'Day'),
      periods.map(p => p.bookable
        ? h('th', { scope: 'col' }, h('span', { class: 'tt-grid__period' }, p.label),
          h('span', { class: 'tt-grid__time' }, `${p.start}–${p.end}`))
        : h('th', { scope: 'col', class: 'tt-grid__lunch-head' },
          h('span', { class: 'visually-hidden' }, `${p.label} ${p.start}–${p.end}`))));

    const rows = body.days.map((day, i) => {
      const today = day.date === body.today;
      return h('tr', { class: today ? 'tt-grid__today' : null },
        h('th', { scope: 'row', class: 'tt-grid__day' },
          h('span', {}, shortDay(day.date).split(' ')[0]),
          h('span', { class: 'tt-grid__date' }, niceDate(day.date).split(' ').slice(1).join(' ')),
          today ? h('span', { class: 'tt-grid__today-label' }, 'Today') : null),
        day.cells.map(cell => {
          if (!cell.bookable) {
            // One narrow LUNCH BREAK column down the whole week, as on paper.
            return i === 0
              ? h('td', { class: 'tt-grid__lunch', rowspan: body.days.length },
                h('span', {}, 'LUNCH BREAK'))
              : null;
          }
          return h('td', { colspan: cell.periods.length > 1 ? cell.periods.length + lunchInside(cell) : null,
            class: cellClass(day, cell) }, cellContent(day, cell));
        }));
    });

    return h('div', { class: 'tt-grid-wrap' },
      h('table', { class: 'tt-grid' },
        h('caption', { class: 'visually-hidden' },
          `${title.textContent} timetable, week of ${niceDate(body.week_start)}`),
        h('thead', {}, head),
        h('tbody', {}, rows)));
  }

  // A merged cell never crosses lunch, but keep the column count right if
  // the period list ever changes.
  function lunchInside(cell) {
    const codes = lists.periods.map(p => p.period);
    const first = codes.indexOf(cell.periods[0]);
    const last = codes.indexOf(cell.periods[cell.periods.length - 1]);
    return lists.periods.slice(first, last + 1).filter(p => !p.bookable).length;
  }

  function isNow(day, cell) {
    return day.date === body.today && cell.periods.includes(body.current_period);
  }

  function cellClass(day, cell) {
    return [
      'tt-cell',
      cell.entries.length ? null : 'tt-cell--free',
      isNow(day, cell) ? 'tt-cell--now' : null,
    ].filter(Boolean).join(' ');
  }

  function cellContent(day, cell) {
    const now = isNow(day, cell) ? h('span', { class: 'tt-now' }, 'Now') : null;
    if (cell.entries.length) {
      return [now, h('div', { class: 'tt-cell__entries' }, cell.entries.map(e => entryButton(e, day, cell)))];
    }
    return [now, freeCell(day, cell)];
  }

  function freeCell(day, cell) {
    if (isStaff && startsInFuture(day.date, cell.start)) {
      return h('button', { class: 'tt-add', type: 'button',
        'aria-label': `Book ${niceDate(day.date)}, ${cell.period} ${cell.start}–${cell.end}`,
        title: 'Book this period', onclick: () => openBook(day, cell) }, '+');
    }
    return h('span', { class: 'visually-hidden' }, 'Free');
  }

  // --- One class or booking -------------------------------------------------

  function entryLines(e, cell) {
    const kind = body.view.kind;
    const home = kind === 'class' ? body.view.class_info.home_room_id : null;
    const code = e.subject_code || e.title;
    const who = e.teacher.initials ? ` (${e.teacher.initials})` : '';
    const main = kind === 'teacher'
      ? [h('strong', {}, code), e.batch ? ` ${e.batch}` : '']
      : [h('strong', {}, code), e.batch ? ` ${e.batch}` : '', who];
    const lines = [h('span', { class: 'tt-entry__main' }, main)];
    // A whole-morning block or a subject without a code shows its title too.
    if (e.subject_code && (cell.periods.length >= 3 || !e.room_id)) {
      lines.push(h('span', { class: 'tt-entry__title' }, e.title));
    }
    if (kind === 'teacher' && e.class_id) lines.push(h('span', {}, e.class_id));
    if (kind === 'room' && e.class_id) lines.push(h('span', {}, e.class_id));
    if (e.room_id && kind !== 'room' && e.room_id !== home) {
      lines.push(h('span', { class: 'tt-entry__room' }, kind === 'class' ? `/${e.room_id}` : e.room_id));
    }
    return lines;
  }

  function summary(e, day) {
    const parts = [
      e.subject_code ? `${e.subject_code} ${e.title}` : e.title,
      e.class_id && `${e.class_id}${e.batch ? ` batch ${e.batch}` : ''}`,
      e.teacher.name,
      e.room_id || 'no room',
      `${niceDate(day.date)} ${e.start}–${e.end}`,
      e.is_extra && 'extra class',
    ];
    if (e.change) {
      parts.push(`${CHANGE_LABELS[e.change.action] || e.change.action}${e.change.by ? ` by ${e.change.by}` : ''}: ${e.change.reason}`);
    }
    return parts.filter(Boolean).join(' · ');
  }

  function entryButton(e, day, cell) {
    const inactive = !ACTIVE.includes(e.booking_status);
    const cls = ['tt-entry',
      e.is_extra ? 'tt-entry--extra' : null,
      e.change ? 'tt-entry--changed' : null,
      inactive ? 'tt-entry--inactive' : null].filter(Boolean).join(' ');
    const text = summary(e, day);
    return h('button', { class: cls, type: 'button', title: text, 'aria-label': text,
      onclick: () => openEntry(e, day) },
      entryLines(e, cell),
      e.is_extra || e.change || inactive
        ? h('span', { class: 'tt-entry__badges' },
          e.is_extra ? h('span', { class: 'tt-badge tt-badge--extra' }, 'Extra') : null,
          e.change ? h('span', { class: 'tt-badge tt-badge--changed' },
            CHANGE_LABELS[e.change.action] || e.change.action) : null)
        : null,
      e.occupancy ? h('span', { class: 'tt-entry__live' },
        occupancyTag(e.occupancy.occupancy, e.occupancy.head_count)) : null);
  }

  function openEntry(e, day) {
    const booking = {
      booking_id: e.booking_id, room_id: e.room_id, date: day.date, start: e.start, end: e.end,
      purpose: e.purpose, booked_by: e.teacher, booking_status: e.booking_status, class_id: e.class_id,
    };
    const canChange = user.role === 'admin' && e.booking_id && ACTIVE.includes(e.booking_status)
      && new Date(`${day.date}T${e.end}:00+05:30`) > new Date();
    const close = h('button', { class: 'btn btn--secondary', type: 'button' }, 'Close');
    const d = openDialog({
      title: e.subject_code ? `${e.subject_code} · ${e.title}` : e.title,
      body: [
        h('div', { class: 'tags' },
          bookingTag(e.booking_status),
          e.is_extra ? h('span', { class: 'tt-badge tt-badge--extra' }, 'Extra class') : null,
          e.occupancy ? occupancyTag(e.occupancy.occupancy, e.occupancy.head_count) : null),
        e.change ? alertBox(
          `${CHANGE_LABELS[e.change.action] || e.change.action}${e.change.by ? ` by ${e.change.by}` : ''}. `
          + `Reason: ${e.change.reason}`, 'info') : null,
        e.change?.details ? h('p', { class: 'muted' }, e.change.details) : null,
        h('div', { class: 'booking-box' }, h('dl', {},
          h('dt', {}, 'When'), h('dd', {}, `${niceDate(day.date)}, ${e.start}–${e.end}`),
          h('dt', {}, 'Teacher'), h('dd', {}, `${e.teacher.name}${e.teacher.initials ? ` (${e.teacher.initials})` : ''}`),
          h('dt', {}, 'Class'), h('dd', {}, e.class_id ? `${e.class_id}${e.batch ? `, batch ${e.batch}` : ''}` : '—'),
          h('dt', {}, 'Room'), h('dd', {}, e.room_id || 'No room'),
          h('dt', {}, 'Purpose'), h('dd', {}, e.purpose))),
        e.booking_id ? null : h('p', { class: 'muted' },
          e.room_id ? 'From the timetable.' : 'From the timetable. It does not book a room.'),
      ],
      actions: [
        canChange ? adminButtons(booking, () => { d.close(); load(false); }) : null,
        close,
      ].flat().filter(Boolean),
    });
    close.addEventListener('click', () => d.close());
    close.focus();
  }

  // --- One day at a time (phones) -----------------------------------------

  function dayList() {
    const tabs = h('div', { class: 'tabs tt-days__tabs', role: 'group', 'aria-label': 'Day' },
      body.days.map((day, i) => h('button', { type: 'button', 'aria-pressed': String(i === dayIndex),
        onclick: () => { dayIndex = i; content.querySelector('.tt-days').replaceWith(dayList()); } },
      shortDay(day.date), day.date === body.today ? h('span', { class: 'visually-hidden' }, ' (today)') : null)));

    const day = body.days[dayIndex];
    const slots = day.cells.map(cell => {
      const label = cell.bookable
        ? `${cell.periods.length > 1 ? `${cell.periods[0]}–${cell.periods[cell.periods.length - 1]}` : cell.period}`
        : 'Lunch break';
      return h('li', { class: `tt-slot${cell.bookable ? '' : ' tt-slot--lunch'}${isNow(day, cell) ? ' tt-cell--now' : ''}` },
        h('div', { class: 'tt-slot__when' },
          h('strong', {}, label), h('span', {}, `${cell.start}–${cell.end}`),
          isNow(day, cell) ? h('span', { class: 'tt-now' }, 'Now') : null),
        cell.bookable
          ? h('div', { class: 'tt-slot__what' },
            cell.entries.length
              ? cell.entries.map(e => entryButton(e, day, cell))
              : [h('span', { class: 'muted' }, 'Free'), freeCell(day, cell)])
          : null);
    });
    return h('section', { class: 'tt-days', 'aria-label': 'One day' },
      tabs,
      h('h2', { class: 'tt-days__title' }, niceDate(day.date), day.date === body.today ? ' · Today' : ''),
      h('ol', { class: 'tt-days__list' }, slots),
      day.outside_periods.length
        ? h('p', { class: 'muted' }, `Also: ${day.outside_periods.map(e => `${e.start}–${e.end} ${e.title}`).join(', ')}`)
        : null);
  }

  // --- Course table (class view) --------------------------------------------

  async function courseRows(classId) {
    if (!lists.subjects) lists.subjects = await api('/subjects');
    const rows = await api(`/teaching${query({ class_id: classId })}`);
    const byCode = new Map();
    for (const row of rows) {
      const entry = byCode.get(row.subject.code) || { subject: row.subject, faculty: new Map() };
      const name = `${row.teacher.name}${row.teacher.initials ? ` (${row.teacher.initials})` : ''}`;
      entry.faculty.set(name, true);
      byCode.set(row.subject.code, entry);
    }
    return [...byCode.values()].sort((a, b) => a.subject.code.localeCompare(b.subject.code));
  }

  function courseTable(courses) {
    if (!courses.length) return null;
    const credits = courses.reduce((sum, c) => sum + c.subject.credits, 0);
    return h('section', { class: 'tt-courses', 'aria-labelledby': 'tt-courses-title' },
      h('h2', { id: 'tt-courses-title' }, 'Courses'),
      h('div', { class: 'table-wrap' }, h('table', {},
        h('thead', {}, h('tr', {},
          ['Code', 'Course title', 'Type', 'Faculty', 'Credits'].map(t => h('th', { scope: 'col' }, t)))),
        h('tbody', {}, courses.map(c => h('tr', {},
          h('td', {}, h('strong', {}, c.subject.code)),
          h('td', {}, c.subject.title),
          h('td', {}, c.subject.type),
          h('td', {}, [...c.faculty.keys()].join(', ')),
          h('td', { class: 'tt-courses__num' }, c.subject.credits)))),
        h('tfoot', {}, h('tr', {},
          h('th', { scope: 'row', colspan: 4 }, 'Total credits'),
          h('td', { class: 'tt-courses__num' }, credits))))));
  }

  function legend() {
    return h('p', { class: 'tt-legend muted' },
      h('span', { class: 'tt-badge tt-badge--extra' }, 'Extra'), ' one-time extra class · ',
      h('span', { class: 'tt-badge tt-badge--changed' }, 'Moved'), ' changed for this date (hover or tap for the reason)',
      isStaff ? ' · + book a free period' : '');
  }

  // --- Book this period (teachers and admins) -------------------------------

  async function myPairs() {
    if (!lists.myPairs) {
      const rows = await api(`/teaching${query({ teacher: user.college_id })}`);
      const seen = new Map();
      for (const row of rows) {
        const key = `${row.subject.code}|${row.class_id}`;
        if (!seen.has(key)) seen.set(key, { code: row.subject.code, title: row.subject.title, class_id: row.class_id });
      }
      lists.myPairs = [...seen.values()];
    }
    return lists.myPairs;
  }

  async function openBook(day, cell) {
    let pairs = [];
    try {
      pairs = await myPairs();
    } catch {
      // Without the list, a teacher can still book for "something else".
    }
    const what = h('select', { id: 'bk-what', name: 'what' },
      pairs.map(p => h('option', { value: `${p.code}|${p.class_id}` }, `${p.code} · ${p.class_id} — ${p.title}`)),
      h('option', { value: '' }, 'Something else (meeting, event)'));
    if (view.kind === 'class') {
      const match = pairs.find(p => p.class_id === view.id);
      if (match) what.value = `${match.code}|${match.class_id}`;
    }
    const purposeField = h('div', { class: 'field' },
      h('label', { for: 'bk-purpose' }, 'Purpose'),
      h('input', { id: 'bk-purpose', name: 'purpose', maxlength: '200', placeholder: 'e.g. Department meeting' }));
    const roomList = h('div', { class: 'tt-rooms', role: 'radiogroup', 'aria-labelledby': 'bk-rooms-label' });
    const errorBox = h('div');
    const submit = h('button', { class: 'btn btn--primary', type: 'submit' }, 'Book period');
    const cancel = h('button', { class: 'btn btn--secondary', type: 'button' }, 'Go back');

    const form = h('form', { class: 'stack', novalidate: true },
      errorBox,
      h('div', { class: 'booking-box' }, h('dl', {},
        h('dt', {}, 'When'), h('dd', {}, `${niceDate(day.date)}, ${cell.period} ${cell.start}–${cell.end}`))),
      h('div', { class: 'field' }, h('label', { for: 'bk-what' }, 'For'), what,
        h('span', { class: 'field__hint' }, 'Your own subjects. The purpose is filled in for you.')),
      purposeField,
      h('div', { class: 'field' }, h('span', { id: 'bk-rooms-label', class: 'tt-toolbar__label' }, 'Room'), roomList),
      h('div', { class: 'dialog__actions', style: 'padding:0' }, cancel, submit));

    const dialog = openDialog({ title: 'Book this period', body: form, wide: true });
    cancel.addEventListener('click', () => dialog.close());

    function chosenPair() {
      const [code, classId] = what.value.split('|');
      return what.value ? { code, class_id: classId } : null;
    }

    let roomsLoad = 0;
    async function loadRooms() {
      const id = ++roomsLoad;
      const pair = chosenPair();
      purposeField.hidden = Boolean(pair);
      roomList.replaceChildren(loading('Finding free rooms…'));
      try {
        const rooms = await api(`/rooms/free${query({ date: day.date, period: cell.period, class_id: pair?.class_id })}`);
        if (id !== roomsLoad) return;
        if (!rooms.length) {
          roomList.replaceChildren(h('p', { class: 'muted' }, 'No room is free for this period.'));
          return;
        }
        const wanted = view.kind === 'room' && rooms.some(r => r.room_id === view.id) ? view.id : rooms[0].room_id;
        roomList.replaceChildren(...rooms.map(r => h('label', { class: 'tt-room' },
          h('input', { type: 'radio', name: 'room_id', value: r.room_id, checked: r.room_id === wanted }),
          h('span', {}, h('strong', {}, r.room_id), ` · ${r.name}`),
          h('span', { class: 'muted' }, `${r.capacity} seats`),
          r.is_home_room ? h('span', { class: 'badge' }, 'Home room') : null)));
      } catch (error) {
        if (id === roomsLoad) roomList.replaceChildren(alertBox(error.message || 'Could not load free rooms.'));
      }
    }
    what.addEventListener('change', loadRooms);
    loadRooms();
    what.focus();

    async function book(roomId) {
      const pair = chosenPair();
      const request = { room_id: roomId, date: day.date, period: cell.period };
      if (pair) {
        Object.assign(request, { class_id: pair.class_id, subject_code: pair.code });
      } else {
        const purpose = form.purpose.value.trim();
        if (!purpose) {
          errorBox.replaceChildren(alertBox('Enter a purpose.'));
          form.purpose.focus();
          return;
        }
        request.purpose = purpose;
      }
      try {
        const reply = await busy(submit, () => api('/bookings', { method: 'POST', body: request }));
        dialog.close();
        toast(`Booked ${reply.room_id}, ${niceDate(reply.date)} ${reply.start}–${reply.end}.`);
        load(false);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          // The usual "already booked" pop-up, inside this dialog: who has the
          // room, and free rooms to book instead in one click.
          errorBox.replaceChildren(...conflictBody(error.body, roomId, picked => book(picked)).filter(Boolean));
          loadRooms();
        } else {
          errorBox.replaceChildren(alertBox(error.message || 'Could not book this period.'));
        }
        errorBox.scrollIntoView({ block: 'nearest' });
      }
    }

    form.addEventListener('submit', event => {
      event.preventDefault();
      const roomId = form.querySelector('input[name="room_id"]:checked')?.value;
      if (!roomId) {
        errorBox.replaceChildren(alertBox('Choose a room.'));
        return;
      }
      book(roomId);
    });
  }

  // --- Start ---------------------------------------------------------------

  drawViewTabs();
  loadLists()
    .then(() => load(true))
    .catch(error => {
      if (error instanceof ApiError && error.status === 401) return;
      content.setAttribute('aria-busy', 'false');
      content.replaceChildren(emptyState('⚠', 'The timetable could not be loaded', error.message,
        h('button', { class: 'btn btn--primary', type: 'button', onclick: () => location.reload() }, 'Try again')));
    });

  // Leaving the screen: stop the live refresh.
  return () => {
    loadId++;
    clearTimeout(timer);
  };
}
