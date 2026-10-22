// Screen 1: log in, or get a setup code and set a password (first login or
// forgotten password). API contract endpoints 1, 2 and 3.

import { ApiError, api, saveSession } from '../api.js';
import { alertBox, h, icon, toast } from '../ui.js';

export function renderLogin({ main, onLoggedIn }) {
  let mode = 'login';        // 'login' | 'request' | 'set'
  let collegeId = '';
  let notice = null;         // { message, kind } shown above the form

  function draw() {
    const card = h('div', { class: 'auth__card' },
      h('div', { class: 'auth__brand' },
        h('span', { class: 'brand__mark', 'aria-hidden': 'true' }, icon('logo', 28)),
        h('div', {},
          h('h1', { class: 'auth__title' }, 'RoomSync'),
          h('p', { class: 'auth__subtitle' }, 'Room booking and live occupancy'))),
      mode === 'login' ? loginForm() : setupForm());
    main.replaceChildren(h('div', { class: 'auth' }, card));
    main.querySelector('input:not([readonly])')?.focus();
  }

  function setMode(next, newNotice = null) {
    mode = next;
    notice = newNotice;
    draw();
  }

  // Disables the form while waiting, and shows the API's message on failure.
  async function submitting(form, work) {
    const button = form.querySelector('button[type="submit"]');
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Please wait…';
    form.querySelector('.alert')?.remove();
    try {
      await work();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Something went wrong.';
      form.prepend(alertBox(message, 'error'));
      button.disabled = false;
      button.textContent = label;
    }
  }

  function noticeBox() {
    return notice ? alertBox(notice.message, notice.kind) : null;
  }

  // --- Log in ----------------------------------------------------------------

  function loginForm() {
    const form = h('form', { novalidate: true },
      noticeBox(),
      h('div', { class: 'field' },
        h('label', { for: 'college-id' }, 'College ID'),
        h('input', {
          id: 'college-id', name: 'college_id', autocomplete: 'username', required: true,
          value: collegeId, placeholder: 'e.g. 1JS23CS044 or T002', autocapitalize: 'characters',
        })),
      h('div', { class: 'field' },
        h('label', { for: 'password' }, 'Password'),
        h('input', {
          id: 'password', name: 'password', type: 'password', autocomplete: 'current-password',
          required: true,
        })),
      h('button', { class: 'btn btn--primary btn--block', type: 'submit' }, 'Log in'));

    form.addEventListener('submit', event => {
      event.preventDefault();
      collegeId = form.college_id.value.trim();
      const password = form.password.value;
      if (!collegeId || !password) {
        form.querySelector('.alert')?.remove();
        form.prepend(alertBox('Enter your college ID and password.'));
        return;
      }
      submitting(form, async () => {
        const reply = await api('/auth/login', {
          method: 'POST', auth: false, body: { college_id: collegeId, password },
        });
        saveSession(reply.token, reply.user);
        toast(`Welcome, ${reply.user.name}.`);
        onLoggedIn();
      });
    });

    return [form, h('p', { class: 'auth__footer' },
      'First time here, or forgot your password? ',
      h('button', { class: 'link-button', type: 'button', onclick: () => setMode('request') },
        'Get a setup code'))];
  }

  // --- First login: request a code, then set a password ------------------------

  function steps() {
    return h('ol', { class: 'steps', 'aria-label': 'Steps' },
      h('li', mode === 'request' ? { 'aria-current': 'step' } : { class: 'done' }, '1. Get a code'),
      h('li', mode === 'set' ? { 'aria-current': 'step' } : {}, '2. Set your password'));
  }

  function setupForm() {
    const back = h('p', { class: 'auth__footer' },
      h('button', { class: 'link-button', type: 'button', onclick: () => setMode('login') },
        'Back to log in'));
    return [mode === 'request' ? requestForm() : setForm(), back];
  }

  function requestForm() {
    const form = h('form', { novalidate: true },
      steps(),
      noticeBox(),
      h('p', { class: 'muted' },
        'Enter your college ID. We will email a 6-digit code to your college email.'),
      h('div', { class: 'field' },
        h('label', { for: 'setup-id' }, 'College ID'),
        h('input', { id: 'setup-id', name: 'college_id', autocomplete: 'username',
          required: true, value: collegeId, autocapitalize: 'characters' })),
      h('button', { class: 'btn btn--primary btn--block', type: 'submit' }, 'Email me a code'));

    form.addEventListener('submit', event => {
      event.preventDefault();
      collegeId = form.college_id.value.trim();
      if (!collegeId) {
        form.querySelector('.alert')?.remove();
        form.prepend(alertBox('Enter your college ID.'));
        return;
      }
      submitting(form, async () => {
        const reply = await api('/auth/request-setup', {
          method: 'POST', auth: false, body: { college_id: collegeId },
        });
        setMode('set', { message: `${reply.message} It works for 15 minutes.`, kind: 'success' });
      });
    });
    return form;
  }

  function setForm() {
    const form = h('form', { novalidate: true },
      steps(),
      noticeBox(),
      h('div', { class: 'field' },
        h('label', { for: 'set-id' }, 'College ID'),
        h('input', { id: 'set-id', name: 'college_id', value: collegeId, readonly: true,
          autocomplete: 'username' })),
      h('div', { class: 'field' },
        h('label', { for: 'code' }, '6-digit code from the email'),
        h('input', { id: 'code', name: 'code', inputmode: 'numeric', autocomplete: 'one-time-code',
          maxlength: '6', pattern: '[0-9]{6}', required: true })),
      h('div', { class: 'field' },
        h('label', { for: 'new-password' }, 'New password'),
        h('input', { id: 'new-password', name: 'new_password', type: 'password',
          autocomplete: 'new-password', minlength: '8', required: true,
          'aria-describedby': 'pw-hint' }),
        h('span', { class: 'field__hint', id: 'pw-hint' }, 'At least 8 characters.')),
      h('div', { class: 'field' },
        h('label', { for: 'confirm-password' }, 'Type the new password again'),
        h('input', { id: 'confirm-password', name: 'confirm', type: 'password',
          autocomplete: 'new-password', required: true })),
      h('button', { class: 'btn btn--primary btn--block', type: 'submit' }, 'Set password'),
      h('p', { class: 'muted', style: 'font-size:0.85rem;text-align:center' },
        'No email? ',
        h('button', { class: 'link-button', type: 'button',
          onclick: () => setMode('request') }, 'Ask for a new code')));

    form.addEventListener('submit', event => {
      event.preventDefault();
      const code = form.code.value.trim();
      const password = form.new_password.value;
      const problem =
        !/^\d{6}$/.test(code) ? 'The code is the 6 digits from the email.'
          : password.length < 8 ? 'The new password needs at least 8 characters.'
            : password !== form.confirm.value ? 'The two passwords are not the same.'
              : null;
      if (problem) {
        form.querySelector('.alert')?.remove();
        form.prepend(alertBox(problem));
        return;
      }
      submitting(form, async () => {
        const reply = await api('/auth/set-password', {
          method: 'POST', auth: false,
          body: { college_id: collegeId, code, new_password: password },
        });
        setMode('login', { message: reply.message, kind: 'success' });
      });
    });
    return form;
  }

  draw();
}
