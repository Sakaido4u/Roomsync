// Stand-in for screens not built yet.

import { h } from '../ui.js';

export function renderPlaceholder({ main }, title) {
  main.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', {}, title)),
    h('div', { class: 'empty-state' },
      h('div', { class: 'empty-state__icon', 'aria-hidden': 'true' }, '🛠'),
      h('h2', {}, 'Coming next'),
      h('p', {}, 'This screen will be built once the look of the first screens is agreed.')));
}
