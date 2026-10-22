// The dashboard's starting point: header, menu and switching between screens.
//
// Screens are chosen by the part of the address after "#", for example
// http://127.0.0.1:8000/#/rooms. Each screen is a function that fills the
// <main> element and may return a "cleanup" function (used to stop timers
// such as the 5-second live refresh when you leave the screen).

import { api, clearSession, getSession } from './api.js';
import { ROLE_LABELS, h, icon, toast } from './ui.js';
import { renderLogin } from './views/login.js';
import { renderRooms } from './views/rooms.js';
import { renderReserve } from './views/reserve.js';
import { renderBookings } from './views/bookings.js';
import { renderNotifications } from './views/notifications.js';
import { renderAdmin } from './views/admin.js';
import { renderAdmins } from './views/admins.js';
import { renderMyClass } from './views/myclass.js';

const main = document.getElementById('main');
const header = document.getElementById('site-header');

// Who sees which menu item. The server still checks every request; this
// only hides buttons a role cannot use.
const STAFF = ['teacher', 'admin'];
const MENU = [
  { path: '/rooms', label: 'Rooms', roles: null },
  { path: '/reserve', label: 'Reserve', roles: STAFF },
  { path: '/bookings', label: 'My bookings', roles: STAFF },
  { path: '/admin', label: 'Admin', roles: ['admin'] },
  { path: '/admins', label: 'Admin rights', roles: ['super_admin'] },
  { path: '/class', label: 'My class', roles: STAFF },
];

const SCREENS = {
  '/rooms': renderRooms,
  '/reserve': renderReserve,
  '/bookings': renderBookings,
  '/notifications': renderNotifications,
  '/admin': renderAdmin,
  '/admins': renderAdmins,
  '/class': renderMyClass,
};

let cleanup = null;
let unreadTimer = null;

function currentRoute() {
  const [path, search = ''] = location.hash.replace(/^#/, '').split('?');
  return { path: path || '/rooms', params: new URLSearchParams(search) };
}

// Go to a screen. Setting the same address again does not fire
// "hashchange", so in that case the screen is redrawn directly.
export function go(path) {
  if (location.hash === `#${path}`) show();
  else location.hash = `#${path}`;
}

function allowed(item, user) {
  return !item.roles || item.roles.includes(user.role);
}

// --- Header -----------------------------------------------------------------

function renderHeader(user, path) {
  const navLinks = MENU.filter(item => allowed(item, user)).map(item =>
    h('a', { href: `#${item.path}`, 'aria-current': path === item.path ? 'page' : false },
      item.label));

  const role = user.is_cr ? `${ROLE_LABELS[user.role]} · CR` : ROLE_LABELS[user.role];

  header.replaceChildren(h('div', { class: 'site-header__inner' },
    h('a', { class: 'brand', href: '#/rooms' },
      h('span', { class: 'brand__mark', 'aria-hidden': 'true' }, icon('logo', 22)),
      'RoomSync'),
    h('nav', { class: 'nav', 'aria-label': 'Main' }, navLinks),
    h('div', { class: 'header-actions' },
      h('a', {
        class: 'bell', id: 'bell', href: '#/notifications',
        'aria-current': path === '/notifications' ? 'page' : false,
        'aria-label': 'Notifications',
      },
      icon('bell', 22),
      h('span', { class: 'bell__count', id: 'bell-count', hidden: true })),
      h('div', { class: 'user-menu' },
        h('div', { class: 'user-menu__text' },
          h('div', { class: 'user-menu__name' }, user.name),
          h('div', { class: 'user-menu__role' }, role)),
        h('button', { class: 'btn btn--secondary btn--small', type: 'button', onclick: logOut },
          'Log out')))));
  header.hidden = false;
  refreshUnread();
}

async function refreshUnread() {
  const badge = document.getElementById('bell-count');
  const bell = document.getElementById('bell');
  if (!badge || !getSession()) return;
  try {
    const unread = await api('/notifications?unread=true');
    badge.textContent = unread.length > 99 ? '99+' : String(unread.length);
    badge.hidden = unread.length === 0;
    bell.setAttribute('aria-label',
      unread.length ? `Notifications, ${unread.length} unread` : 'Notifications');
  } catch {
    // The bell is not important enough to show an error for.
  }
}

function logOut() {
  clearSession();
  go('/login');
  toast('You have logged out.');
}

// --- Switching screens ------------------------------------------------------

function show() {
  if (cleanup) {
    cleanup();
    cleanup = null;
  }
  const { path, params } = currentRoute();
  const session = getSession();

  if (!session || path === '/login') {
    if (session && path === '/login') return go(params.get('next') || '/rooms');
    header.hidden = true;
    header.replaceChildren();
    clearInterval(unreadTimer);
    unreadTimer = null;
    cleanup = renderLogin({ main, params, onLoggedIn: () => go(params.get('next') || '/rooms') });
    return;
  }

  const item = MENU.find(m => m.path === path);
  const screen = SCREENS[path];
  if (!screen || (item && !allowed(item, session.user))) return go('/rooms');

  renderHeader(session.user, path);
  if (!unreadTimer) unreadTimer = setInterval(refreshUnread, 30000);
  main.replaceChildren();
  cleanup = screen({ main, params, user: session.user, refreshUnread }) || null;
  main.focus({ preventScroll: true });
}

window.addEventListener('hashchange', show);
window.addEventListener('roomsync:logged-out', event => {
  toast(event.detail, 'error');
  go('/login');
});

show();
