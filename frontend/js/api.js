// Talking to the RoomSync backend.
//
// Every request goes through api(), which:
// - adds the login token ("Authorization: Bearer ...") when logged in,
// - turns the backend's error reply {"error", "message"} into an ApiError
//   whose .message can be shown to the user as it is,
// - logs the user out if the backend says the login is no longer valid.

const TOKEN_KEY = 'roomsync.token';
const USER_KEY = 'roomsync.user';

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `Request failed (${status}).`);
    this.status = status;
    this.code = body?.error || 'error';
    this.body = body || {};
  }
}

// --- The logged-in session, kept in the browser between page loads ------

export function getSession() {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const user = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    return token && user ? { token, user } : null;
  } catch {
    return null;
  }
}

export function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// --- Requests -------------------------------------------------------------

export async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const session = getSession();
  if (auth && session) headers.Authorization = `Bearer ${session.token}`;

  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, {
      error: 'network',
      message: 'Cannot reach the RoomSync server. Check that it is running and try again.',
    });
  }

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth && session) {
      // The token expired or the account was changed: back to the login page.
      clearSession();
      window.dispatchEvent(new CustomEvent('roomsync:logged-out', {
        detail: data?.message || 'Please log in again.',
      }));
    }
    throw new ApiError(response.status, data);
  }
  return data;
}

// Builds "?date=...&start=..." from an object, skipping empty values.
export function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}
