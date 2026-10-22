// Screen 7a (super admin): grant and remove admin rights (endpoints 5, 6, 24).

import { api } from '../api.js';
import { alertBox, confirmDialog, emptyState, h, loading, toast } from '../ui.js';

export function renderAdmins({ main }) {
  const content = h('div', { class: 'split' }, loading());
  main.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Admin rights'),
        h('p', {}, 'Admins can override, reschedule and remove bookings, upload the timetable and add rooms. Only teachers can be made admins.'))),
    content);

  async function load() {
    try {
      const [teachers, admins] = await Promise.all([api('/users?role=teacher'), api('/users?role=admin')]);
      content.replaceChildren(
        panel('Admins', `${admins.length} with admin rights`, admins, person =>
          button('Remove admin rights', 'btn--secondary', person, () => change(person, false))),
        panel('Teachers', 'Give a teacher admin rights', teachers, person =>
          button('Make admin', 'btn--primary', person, () => change(person, true))));
    } catch (error) {
      content.replaceChildren(alertBox(error.message));
    }
  }

  function panel(title, intro, people, action) {
    return h('section', { class: 'panel' },
      h('h2', {}, title), h('p', { class: 'panel__intro' }, intro),
      people.length
        ? h('ul', { class: 'people' }, people.map(p => h('li', { class: 'person' },
          h('div', {}, h('div', { class: 'person__name' }, p.name),
            h('div', { class: 'person__meta' }, `${p.college_id} · ${p.department}`)),
          action(p))))
        : emptyState('👤', `No ${title.toLowerCase()}`, null));
  }

  function button(label, cls, person, onclick) {
    return h('button', { class: `btn ${cls} btn--small`, type: 'button',
      'aria-label': `${label}: ${person.name}`, onclick }, label);
  }

  async function change(person, makeAdmin) {
    const sure = await confirmDialog({
      title: makeAdmin ? `Make ${person.name} an admin?` : `Remove ${person.name}'s admin rights?`,
      message: makeAdmin
        ? 'They will be able to change anyone\'s bookings (always with a reason), upload the timetable and add rooms. This takes effect immediately.'
        : 'They become a teacher again, immediately. Their own bookings are kept.',
      confirmLabel: makeAdmin ? 'Make admin' : 'Remove rights',
      danger: !makeAdmin,
    });
    if (!sure) return;
    try {
      const user = makeAdmin
        ? await api('/admin/admins', { method: 'POST', body: { user_id: person.user_id } })
        : await api(`/admin/admins/${person.user_id}`, { method: 'DELETE' });
      toast(`${user.name} is now ${user.role === 'admin' ? 'an admin' : 'a teacher'}.`);
      load();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  load();
}
