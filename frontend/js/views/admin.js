// Screen 6: admin tools.
// - Change a booking: override / reschedule / remove with a reason (15-17).
// - Upload timetable: a CSV file becomes weekly scheduled classes (19).
// - Add a room (11).

import { api, query } from '../api.js';
import { adminButtons } from '../bookings-ui.js';
import {
  alertBox, bookingTag, busy, confirmDialog, emptyState, h, loading, niceDate, toast, todayIso,
} from '../ui.js';

// Short labels so the three tabs fit on one line on a phone.
const SECTIONS = [
  ['change', 'Change bookings'],
  ['timetable', 'Timetable'],
  ['room', 'Add room'],
];

export function renderAdmin({ main, params }) {
  let section = SECTIONS.some(([key]) => key === params.get('tab')) ? params.get('tab') : 'change';
  const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Admin tools' });
  const content = h('div', { role: 'tabpanel' });
  main.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Admin'), h('p', {}, 'Change bookings, upload the timetable and add rooms.'))),
    h('div', { style: 'margin-bottom:16px' }, tabs),
    content);

  function draw() {
    tabs.replaceChildren(...SECTIONS.map(([key, label]) =>
      h('button', { type: 'button', role: 'tab', 'aria-selected': String(section === key),
        onclick: () => {
          section = key;
          history.replaceState(null, '', `#/admin?tab=${key}`);
          draw();
        } }, label)));
    content.replaceChildren();
    ({ change: changeSection, timetable: timetableSection, room: roomSection })[section](content);
  }
  draw();
}

// --- Change a booking ---------------------------------------------------------

function changeSection(content) {
  const roomSelect = h('select', { id: 'ch-room' });
  const dateInput = h('input', { id: 'ch-date', type: 'date', value: todayIso() });
  const list = h('div');
  content.append(h('section', { class: 'panel' },
    h('h2', {}, 'Change a booking'),
    h('p', { class: 'panel__intro' },
      'Pick a room and day. Every change needs a reason; the teacher and the class CR are told by notification and email.'),
    h('div', { class: 'form-grid', style: 'margin-bottom:16px' },
      h('div', { class: 'field' }, h('label', { for: 'ch-room' }, 'Room'), roomSelect),
      h('div', { class: 'field' }, h('label', { for: 'ch-date' }, 'Date'), dateInput)),
    list));

  async function load() {
    if (!roomSelect.value) return;
    list.replaceChildren(loading());
    try {
      const bookings = await api(`/rooms/${encodeURIComponent(roomSelect.value)}/schedule${query({ date: dateInput.value })}`);
      if (!bookings.length) {
        list.replaceChildren(emptyState('✓', 'Nothing booked', `${roomSelect.value} is free all day on ${niceDate(dateInput.value)}.`));
        return;
      }
      const now = new Date();
      list.replaceChildren(h('ul', { class: 'list' }, bookings.map(b => {
        const ended = new Date(`${b.date}T${b.end}:00+05:30`) <= now;
        return h('li', { class: 'row' },
          h('div', { class: 'row__time' }, `${b.start}–${b.end}`),
          h('div', { class: 'row__main' },
            h('div', { class: 'tags' }, bookingTag(b.booking_status)),
            h('span', { class: 'row__title' }, b.purpose),
            h('span', { class: 'row__meta' }, [b.booked_by.name, b.class_id].filter(Boolean).join(' · '))),
          h('div', { class: 'row__actions' },
            ended ? h('span', { class: 'row__meta' }, 'Already ended') : adminButtons(b, load)));
      })));
    } catch (error) {
      list.replaceChildren(alertBox(error.message));
    }
  }

  roomSelect.addEventListener('change', load);
  dateInput.addEventListener('change', load);
  api('/rooms').then(rooms => {
    roomSelect.append(...rooms.map(r => h('option', { value: r.room_id }, `${r.room_id} · ${r.name}`)));
    load();
  }).catch(error => list.replaceChildren(alertBox(error.message)));
}

// --- Timetable upload -----------------------------------------------------------

const COLUMNS = ['room_id', 'class_id', 'teacher', 'subject', 'weekday', 'start', 'end'];
const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
const TEMPLATE = `${COLUMNS.join(',')}
CSE-101,CSE-7A,T002,Computer Networks,tuesday,14:30,15:30
CSE-LAB2,CSE-7A,T003,Networks Lab,monday,09:00,11:00
`;

// Splits one CSV line, allowing "quoted, values".
function splitCsvLine(line) {
  const cells = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { cells.push(cell.trim()); cell = ''; }
    else cell += c;
  }
  cells.push(cell.trim());
  return cells;
}

// CSV text -> { entries, problems }. teachers maps college ID -> user_id.
function parseTimetable(text, teachers) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const problems = [];
  if (!lines.length) return { entries: [], problems: ['The file is empty.'] };
  const header = splitCsvLine(lines[0]).map(c => c.toLowerCase());
  const missing = COLUMNS.filter(c => !header.includes(c));
  if (missing.length) return { entries: [], problems: [`Missing column(s): ${missing.join(', ')}. Download the template to see the format.`] };

  const entries = [];
  lines.slice(1).forEach((line, i) => {
    const lineNo = i + 2;
    const cells = splitCsvLine(line);
    const row = Object.fromEntries(header.map((name, j) => [name, cells[j] ?? '']));
    const weekday = row.weekday.toLowerCase();
    const teacherId = teachers.get(row.teacher.toUpperCase());
    const time = /^\d{1,2}:\d{2}$/;
    if (COLUMNS.some(c => !row[c])) problems.push(`Line ${lineNo}: every column needs a value.`);
    else if (!WEEKDAYS.includes(weekday)) problems.push(`Line ${lineNo}: "${row.weekday}" is not a weekday.`);
    else if (!time.test(row.start) || !time.test(row.end)) problems.push(`Line ${lineNo}: times must look like 09:00.`);
    else if (!teacherId) problems.push(`Line ${lineNo}: no teacher with college ID "${row.teacher}".`);
    else {
      entries.push({
        room_id: row.room_id.toUpperCase(), class_id: row.class_id, teacher_id: teacherId,
        subject: row.subject, weekday, start: row.start.padStart(5, '0'), end: row.end.padStart(5, '0'),
        teacher: row.teacher.toUpperCase(),
      });
    }
  });
  if (!entries.length && !problems.length) problems.push('The file has a header but no entries.');
  return { entries, problems };
}

function timetableSection(content) {
  let teachers = null;   // college ID -> user_id
  let parsed = { entries: [], problems: [] };

  const templateLink = h('a', {
    class: 'btn btn--ghost btn--small', download: 'timetable-template.csv',
    href: URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv' })),
  }, 'Download template');
  const fileInput = h('input', { id: 'tt-file', type: 'file', accept: '.csv,text/csv', 'aria-describedby': 'tt-hint' });
  const preview = h('div');
  const result = h('div');
  const uploadButton = h('button', { class: 'btn btn--primary', type: 'submit', disabled: true }, 'Upload timetable');

  const form = h('form', { class: 'panel', novalidate: true },
    h('h2', {}, 'Upload timetable'),
    h('p', { class: 'panel__intro' },
      'Each line becomes one scheduled class every week of the semester. Uploading again replaces the earlier timetable for that semester (past classes stay).'),
    h('div', { class: 'form-grid' },
      h('div', { class: 'field' }, h('label', { for: 'tt-start' }, 'Semester starts'),
        h('input', { id: 'tt-start', name: 'semester_start', type: 'date', required: true })),
      h('div', { class: 'field' }, h('label', { for: 'tt-end' }, 'Semester ends'),
        h('input', { id: 'tt-end', name: 'semester_end', type: 'date', required: true })),
      h('div', { class: 'field span-2 file-drop' },
        h('label', { for: 'tt-file' }, 'Timetable file (CSV)'),
        fileInput,
        h('span', { class: 'field__hint', id: 'tt-hint' },
          'Columns: room_id, class_id, teacher (college ID, e.g. T002), subject, weekday, start, end. ',
          templateLink))),
    preview,
    h('div', { class: 'form-actions' }, uploadButton),
    result);
  content.append(form);

  async function loadTeachers() {
    if (teachers) return teachers;
    const people = await api('/users');
    teachers = new Map(people.filter(p => p.role === 'teacher' || p.role === 'admin')
      .map(p => [p.college_id.toUpperCase(), p.user_id]));
    return teachers;
  }

  fileInput.addEventListener('change', async () => {
    result.replaceChildren();
    const file = fileInput.files[0];
    if (!file) return;
    preview.replaceChildren(loading('Reading the file…'));
    try {
      parsed = parseTimetable(await file.text(), await loadTeachers());
    } catch (error) {
      parsed = { entries: [], problems: [error.message] };
    }
    drawPreview();
  });

  function drawPreview() {
    uploadButton.disabled = !parsed.entries.length || parsed.problems.length > 0;
    preview.replaceChildren(...[
      parsed.problems.length
        ? h('div', { class: 'stack', style: 'margin-top:16px' },
          alertBox(`Fix these lines in the file, then choose it again (${parsed.problems.length}):`),
          h('ul', {}, parsed.problems.map(p => h('li', {}, p))))
        : null,
      parsed.entries.length
        ? h('div', { style: 'margin-top:16px' },
          h('p', { style: 'margin-bottom:8px' }, h('strong', {}, parsed.entries.length), ' entries ready to upload:'),
          h('div', { class: 'table-wrap', style: 'max-height:280px' }, table(
            ['Room', 'Class', 'Teacher', 'Subject', 'Day', 'Time'],
            parsed.entries.map(e => [e.room_id, e.class_id, e.teacher, e.subject, e.weekday, `${e.start}–${e.end}`]))))
        : null,
    ].filter(Boolean));
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    result.replaceChildren();
    const start = form.semester_start.value;
    const end = form.semester_end.value;
    if (!start || !end) return result.append(alertBox('Choose the semester start and end dates.'));
    const sure = await confirmDialog({
      title: 'Upload this timetable?',
      message: `${parsed.entries.length} entries for ${niceDate(start)} – ${niceDate(end)}. This replaces any earlier timetable for this semester: its classes that have not started yet are rebuilt from this file.`,
      confirmLabel: 'Upload',
    });
    if (!sure) return;
    try {
      const reply = await busy(uploadButton, () => api('/timetable', {
        method: 'POST',
        body: { semester_start: start, semester_end: end,
          entries: parsed.entries.map(({ teacher, ...entry }) => entry) },
      }));
      drawResult(reply);
    } catch (error) {
      result.append(alertBox(error.message));
    }
  });

  function drawResult(reply) {
    const clean = !reply.clashes.length && !reply.skipped_dates.length;
    result.replaceChildren(h('div', { class: 'stack', style: 'margin-top:18px' },
      alertBox(`${reply.scheduled_bookings_created} scheduled classes created.${clean ? ' No clashes.' : ''}`, 'success'),
      reply.clashes.length
        ? h('div', { class: 'stack' },
          h('h3', {}, `Not saved: entries that clash with each other (${reply.clashes.length})`),
          h('p', { class: 'muted' }, 'These need the same room at the same time. Fix them in the file and upload again.'),
          h('div', { class: 'table-wrap' }, table(['Room', 'Day', 'Time', 'Entries'],
            reply.clashes.map(c => [c.room_id, c.weekday, `${c.start}–${c.end}`, c.entries.join(' / ')]))))
        : null,
      reply.skipped_dates.length
        ? h('div', { class: 'stack' },
          h('h3', {}, `Skipped weeks: the room was already booked (${reply.skipped_dates.length})`),
          h('p', { class: 'muted' }, 'The other weeks of these classes were saved. Decide what to move, then use "Change bookings".'),
          h('div', { class: 'table-wrap' }, table(['Date', 'Room', 'Class', 'Already booked by', 'For'],
            reply.skipped_dates.map(s => [
              `${niceDate(s.date)}, ${s.start}–${s.end}`, s.room_id, s.entry,
              `${s.existing_booking.booked_by.name} (${s.existing_booking.start}–${s.existing_booking.end})`,
              s.existing_booking.purpose]))))
        : null));
  }
}

function table(headers, rows) {
  return h('table', {},
    h('thead', {}, h('tr', {}, headers.map(text => h('th', { scope: 'col' }, text)))),
    h('tbody', {}, rows.map(cells => h('tr', {}, cells.map(text => h('td', {}, text))))));
}

// --- Add a room -------------------------------------------------------------------

function roomSection(content) {
  const form = h('form', { class: 'panel', novalidate: true },
    h('h2', {}, 'Add a room'),
    h('p', { class: 'panel__intro' }, 'New rooms appear on the room grid straight away.'),
    h('div', { class: 'form-grid' },
      field('rm-id', 'Room ID', h('input', { id: 'rm-id', name: 'room_id', required: true, placeholder: 'e.g. CSE-103',
        pattern: '[A-Za-z0-9-]{2,20}', 'aria-describedby': 'rm-id-hint' }),
      'Letters, numbers and dashes, 2–20 characters.'),
      field('rm-name', 'Name', h('input', { id: 'rm-name', name: 'name', required: true, maxlength: '100', placeholder: 'e.g. CSE Classroom 103' })),
      field('rm-type', 'Type', h('select', { id: 'rm-type', name: 'type' },
        h('option', { value: 'classroom' }, 'Classroom'), h('option', { value: 'lab' }, 'Lab'),
        h('option', { value: 'meeting_room' }, 'Meeting room'))),
      field('rm-building', 'Building', h('input', { id: 'rm-building', name: 'building', required: true, maxlength: '50', placeholder: 'e.g. Main' })),
      field('rm-floor', 'Floor', h('input', { id: 'rm-floor', name: 'floor', type: 'number', min: '-2', max: '50', value: '0' })),
      field('rm-capacity', 'Seats', h('input', { id: 'rm-capacity', name: 'capacity', type: 'number', min: '1', max: '1000', required: true })),
      field('rm-dept', 'Department', h('input', { id: 'rm-dept', name: 'department', required: true, maxlength: '20', placeholder: 'e.g. CSE' })),
      field('rm-camera', 'Camera (optional)', h('input', { id: 'rm-camera', name: 'camera_stream', maxlength: '500',
        placeholder: 'e.g. phone://RoomSyncMobile', 'aria-describedby': 'rm-camera-hint' }),
      'Set this if a camera watches the room; the no-show check only runs for rooms with a camera. Never shown on the dashboard.')),
    h('div', { class: 'form-actions' }, h('button', { class: 'btn btn--primary', type: 'submit' }, 'Add room')));
  content.append(form);

  form.addEventListener('submit', async event => {
    event.preventDefault();
    form.querySelector(':scope > .alert')?.remove();
    const v = name => form[name].value.trim();
    const body = {
      room_id: v('room_id'), name: v('name'), type: v('type'), building: v('building'),
      floor: Number(v('floor') || 0), capacity: Number(v('capacity')), department: v('department'),
      camera_stream: v('camera_stream') || null,
    };
    if (!body.room_id || !body.name || !body.building || !body.department || !body.capacity) {
      form.prepend(alertBox('Fill in every field except the camera.'));
      return;
    }
    try {
      const room = await busy(form.querySelector('button[type=submit]'), () => api('/rooms', { method: 'POST', body }));
      toast(`${room.room_id} added.`);
      form.reset();
    } catch (error) {
      form.prepend(alertBox(error.message));
    }
  });
}

function field(id, label, input, hint) {
  return h('div', { class: 'field' }, h('label', { for: id }, label), input,
    hint ? h('span', { class: 'field__hint', id: `${id}-hint` }, hint) : null);
}
