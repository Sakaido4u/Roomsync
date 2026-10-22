import { File, Paths } from 'expo-file-system';

// The room this phone watches and where the laptop's inference server is.
// Saved to a small file on the phone so they survive app restarts.
export type CameraSettings = {
  roomId: string;
  serverUrl: string;
};

// Change this to your laptop's IPv4 address (see camera-model-test/README.md).
// It is only the starting value; the address can also be edited on screen.
export const DEFAULT_SERVER_URL = 'http://192.168.1.7:8001';

export const DEFAULT_SETTINGS: CameraSettings = {
  roomId: '',
  serverUrl: DEFAULT_SERVER_URL,
};

const settingsFile = new File(Paths.document, 'camera-settings.json');

export function loadSettings(): CameraSettings {
  try {
    if (!settingsFile.exists) {
      return DEFAULT_SETTINGS;
    }
    const saved = JSON.parse(settingsFile.textSync());
    return {
      roomId: typeof saved.roomId === 'string' ? saved.roomId : '',
      serverUrl:
        typeof saved.serverUrl === 'string' && saved.serverUrl
          ? saved.serverUrl
          : DEFAULT_SERVER_URL,
    };
  } catch {
    // A damaged settings file should never stop the camera from starting.
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: CameraSettings): void {
  if (!settingsFile.exists) {
    settingsFile.create();
  }
  settingsFile.write(JSON.stringify(settings));
}

// Tidy what was typed: drop spaces around both values and a trailing "/".
export function cleanSettings(settings: CameraSettings): CameraSettings {
  return {
    roomId: settings.roomId.trim(),
    serverUrl: settings.serverUrl.trim().replace(/\/+$/, ''),
  };
}

// Returns a message to show, or null when the settings look usable.
export function settingsProblem(settings: CameraSettings): string | null {
  if (!settings.roomId) {
    return 'Enter the room ID, e.g. CSE-101.';
  }
  if (!/^https?:\/\/[^/\s]+/.test(settings.serverUrl)) {
    return 'Server address must look like http://192.168.1.7:8001';
  }
  return null;
}
