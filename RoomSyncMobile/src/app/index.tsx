
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as FileSystem from 'expo-file-system/legacy';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  SafeAreaView,
  ScrollView,
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
} from 'react-native';

import {
  CameraSettings,
  cleanSettings,
  loadSettings,
  saveSettings,
  settingsProblem,
} from '@/lib/camera-settings';

type CameraFacing = 'back' | 'front';

type DetectResult = {
  room_id: string;
  people_count: number;
  timestamp: string;
  backend_status?: 'synced' | 'not_synced';
  backend_error?: string;
};

export default function CameraScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [count, setCount] = useState<number | null>(null);
  const [status, setStatus] = useState('Starting camera...');
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [facing, setFacing] = useState<CameraFacing>('back');

  // Saved settings drive the requests; the draft is what is being typed.
  const [settings, setSettings] = useState<CameraSettings>(loadSettings);
  const [draft, setDraft] = useState<CameraSettings>(settings);
  const [editing, setEditing] = useState(settingsProblem(settings) !== null);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);

  const cameraRef = useRef<CameraView>(null);
  const busy = useRef(false);

  const settingsReady = settingsProblem(settings) === null;

  const handleCameraReady = useCallback(() => {
    setCameraReady(true);
    setStatus('Camera ready. Detecting people...');
  }, []);

  const switchCamera = useCallback(() => {
    setCameraReady(false);
    busy.current = false;
    setFacing(current => (current === 'back' ? 'front' : 'back'));
    setStatus('Switching camera...');
  }, []);

  const saveDraft = useCallback(() => {
    const cleaned = cleanSettings(draft);
    const problem = settingsProblem(cleaned);
    if (problem) {
      setSettingsMessage(problem);
      return;
    }
    try {
      saveSettings(cleaned);
      setSettingsMessage(null);
    } catch {
      setSettingsMessage('Saved for now, but could not remember it for next time.');
    }
    setSettings(cleaned);
    setDraft(cleaned);
    setEditing(false);
    setCount(null);
    setSyncStatus(null);
  }, [draft]);

  useEffect(() => {
    if (!cameraReady || !permission?.granted || !settingsReady) {
      return;
    }

    let active = true;

    const timer = setInterval(async () => {
      if (busy.current || !cameraRef.current) {
        return;
      }

      busy.current = true;
      let imageUri: string | undefined;

      try {
        const photo = await cameraRef.current.takePictureAsync({
          quality: 0.4,
          base64: true,
          skipProcessing: true,
        });

        if (!photo?.base64) {
          throw new Error('No image data returned');
        }

        imageUri = photo.uri;

        const response = await fetch(`${settings.serverUrl}/api/detect`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            room_id: settings.roomId,
            image_base64: photo.base64,
          }),
        });

        if (!response.ok) {
          throw new Error(`YOLO server returned ${response.status}`);
        }

        const result: DetectResult = await response.json();

        if (active) {
          setCount(result.people_count);
          setStatus(`Last updated: ${new Date().toLocaleTimeString()}`);
          setSyncStatus(
            result.backend_status === 'synced'
              ? 'Synced to RoomSync'
              : `Not synced: ${result.backend_error ?? 'unknown reason'}`
          );
        }
      } catch (error) {
        if (active) {
          setStatus(
            error instanceof Error ? error.message : 'Detection failed'
          );
        }
      } finally {
        if (imageUri) {
          try {
            await FileSystem.deleteAsync(imageUri, {
              idempotent: true,
            });
          } catch {
            if (active) {
              setStatus('Warning: temporary image cleanup failed');
            }
          }
        }

        busy.current = false;
      }
    }, 2500);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [cameraReady, facing, permission?.granted, settings, settingsReady]);

  if (!permission) {
    return (
      <View style={styles.center}>
        <Text style={styles.text}>Checking camera permission...</Text>
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.center}>
        <Text style={styles.text}>Camera access is required.</Text>
        <Pressable style={styles.button} onPress={requestPermission}>
          <Text style={styles.buttonText}>Allow Camera</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <Text style={styles.title}>RoomSync</Text>
      <Text style={styles.subtitle}>Live Classroom People Count</Text>

      <View style={styles.cameraBox}>
        <CameraView
          key={facing}
          ref={cameraRef}
          style={styles.camera}
          facing={facing}
          onCameraReady={handleCameraReady}
        />
      </View>

      <ScrollView
        style={styles.scroll}
        keyboardShouldPersistTaps="handled"
      >
        {editing ? (
          <View style={styles.panel}>
            <Text style={styles.label} nativeID="roomLabel">ROOM ID</Text>
            <TextInput
              style={styles.input}
              value={draft.roomId}
              onChangeText={roomId => setDraft(d => ({ ...d, roomId }))}
              placeholder="CSE-101"
              placeholderTextColor="#5d6b82"
              autoCapitalize="characters"
              autoCorrect={false}
              accessibilityLabelledBy="roomLabel"
            />

            <Text style={[styles.label, styles.fieldGap]} nativeID="serverLabel">
              INFERENCE SERVER (LAPTOP)
            </Text>
            <TextInput
              style={styles.input}
              value={draft.serverUrl}
              onChangeText={serverUrl => setDraft(d => ({ ...d, serverUrl }))}
              placeholder="http://192.168.1.7:8001"
              placeholderTextColor="#5d6b82"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              accessibilityLabelledBy="serverLabel"
            />

            {settingsMessage && (
              <Text style={styles.warning}>{settingsMessage}</Text>
            )}

            <Pressable
              style={styles.button}
              onPress={saveDraft}
              accessibilityRole="button"
            >
              <Text style={styles.buttonText}>Save and start</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.panel}>
            <Text style={styles.label}>PEOPLE DETECTED · {settings.roomId}</Text>
            <Text style={styles.count}>{count ?? '—'}</Text>
            <Text style={styles.status}>{status}</Text>
            {syncStatus && (
              <Text
                style={
                  syncStatus.startsWith('Synced') ? styles.status : styles.warning
                }
              >
                {syncStatus}
              </Text>
            )}

            <Pressable
              style={styles.button}
              onPress={switchCamera}
              accessibilityRole="button"
              accessibilityLabel="Switch between front and rear cameras"
            >
              <Text style={styles.buttonText}>
                Switch to {facing === 'back' ? 'Front' : 'Rear'} Camera
              </Text>
            </Pressable>

            <Pressable
              style={styles.secondaryButton}
              onPress={() => {
                setDraft(settings);
                setSettingsMessage(null);
                setEditing(true);
              }}
              accessibilityRole="button"
            >
              <Text style={styles.secondaryButtonText}>
                Change room or server
              </Text>
            </Pressable>
          </View>
        )}

        <Text style={styles.privacy}>
          Camera frames are sent to the laptop on this Wi-Fi network for
          counting and are not stored there. The RoomSync backend only
          receives yes/no and a head count, never an image. Temporary photo
          files on this phone are deleted after each request.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b1220',
    padding: 20,
    paddingTop: 45,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0b1220',
    padding: 24,
  },
  title: {
    color: '#ffffff',
    fontSize: 30,
    fontWeight: 'bold',
  },
  subtitle: {
    color: '#aab6ca',
    marginBottom: 20,
    marginTop: 5,
  },
  cameraBox: {
    height: '45%',
    overflow: 'hidden',
    borderRadius: 18,
    backgroundColor: '#172235',
  },
  camera: {
    flex: 1,
  },
  scroll: {
    flex: 1,
  },
  panel: {
    backgroundColor: '#172235',
    borderRadius: 18,
    padding: 22,
    marginTop: 18,
    alignItems: 'center',
  },
  label: {
    color: '#aab6ca',
    letterSpacing: 2,
    fontSize: 12,
    fontWeight: 'bold',
  },
  fieldGap: {
    marginTop: 14,
  },
  input: {
    alignSelf: 'stretch',
    backgroundColor: '#0b1220',
    color: '#ffffff',
    borderColor: '#2b3a55',
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginTop: 6,
    fontSize: 16,
  },
  count: {
    color: '#ffffff',
    fontSize: 56,
    fontWeight: 'bold',
  },
  status: {
    color: '#56e0b5',
    textAlign: 'center',
    marginTop: 8,
    fontSize: 12,
  },
  warning: {
    color: '#ffb86b',
    textAlign: 'center',
    marginTop: 8,
    fontSize: 12,
  },
  text: {
    color: '#ffffff',
    fontSize: 16,
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#56e0b5',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 10,
    marginTop: 16,
  },
  buttonText: {
    color: '#07131b',
    fontWeight: 'bold',
    fontSize: 14,
  },
  secondaryButton: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    marginTop: 8,
  },
  secondaryButtonText: {
    color: '#56e0b5',
    fontSize: 14,
  },
  privacy: {
    color: '#aab6ca',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 16,
    marginBottom: 12,
    lineHeight: 17,
  },
});
