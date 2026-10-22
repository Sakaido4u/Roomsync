// Screen 7b (class teacher): choose the class's CR (endpoints 7, 25).
// The CR is told about changes to the class's bookings and can answer
// no-show reminders.

import { api } from '../api.js';
import { alertBox, busy, emptyState, h, loading, toast } from '../ui.js';

export function renderMyClass({ main }) {
  const content = h('div', { class: 'stack' }, loading());
  main.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'My class'),
        h('p', {}, 'Choose a class representative (CR). They get notifications about the class\'s bookings.'))),
    content);

  async function load() {
    try {
      const classes = await api('/classes/mine');
      content.replaceChildren(...(classes.length
        ? classes.map(classPanel)
        : [emptyState('🎓', 'You are not a class teacher',
          'Only a class\'s own class teacher can choose its CR.')]));
    } catch (error) {
      content.replaceChildren(alertBox(error.message));
    }
  }

  function classPanel(cls) {
    const current = cls.students.find(s => s.is_cr);
    const name = `cr-${cls.class_id}`;
    const option = (value, label, meta, checked) => h('li', { class: 'person' },
      h('label', {},
        h('input', { type: 'radio', name, value, checked }),
        h('span', {}, h('span', { class: 'person__name' }, label),
          meta ? h('span', { class: 'person__meta' }, ` · ${meta}`) : null)),
      checked && value ? h('span', { class: 'badge' }, 'Current CR') : null);

    const save = h('button', { class: 'btn btn--primary', type: 'submit' }, 'Save CR');
    const form = h('form', { class: 'panel' },
      h('h2', {}, `${cls.class_id} · ${cls.name}`),
      h('p', { class: 'panel__intro' }, `${cls.students.length} students`),
      h('fieldset', { style: 'border:0;padding:0;margin:0' },
        h('legend', { class: 'visually-hidden' }, `CR of ${cls.class_id}`),
        h('ul', { class: 'people' },
          option('', 'No CR', null, !current),
          cls.students.map(s => option(String(s.user_id), s.name, s.college_id, s.is_cr)))),
      h('div', { class: 'form-actions' }, save));

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const picked = form.querySelector(`input[name="${name}"]:checked`)?.value ?? '';
      try {
        const reply = await busy(save, () => api(`/classes/${encodeURIComponent(cls.class_id)}/cr`, {
          method: 'PUT', body: { student_id: picked ? Number(picked) : null },
        }));
        toast(reply.cr ? `${reply.cr.name} is now the CR of ${cls.class_id}.` : `${cls.class_id} has no CR now.`);
        load();
      } catch (error) {
        form.prepend(alertBox(error.message));
      }
    });
    return form;
  }

  load();
}
