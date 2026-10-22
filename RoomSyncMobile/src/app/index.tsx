
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as FileSystem from 'expo-file-system/legacy';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  SafeAreaView,
  View,
  Text,
  Pressable,
  StyleSheet,
} from 'react-native';

// Replace this with your laptop's current IPv4 address.
const API_URL = 'http://192.168.1.7:8000/api/detect';

type CameraFacing = 'back' | 'front';

export default function CameraScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [count, setCount] = useState<number | null>(null);
  const [status, setStatus] = useState('Starting camera...');
  const [cameraReady, setCameraReady] = useState(false);
  const [facing, setFacing] = useState<CameraFacing>('back');

  const cameraRef = useRef<CameraView>(null);
  const busy = useRef(false);

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

  useEffect(() => {
    if (!cameraReady || !permission?.granted) {
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

        const response = await fetch(API_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            room_id: 'CSE-101',
            image_base64: photo.base64,
          }),
        });

        if (!response.ok) {
          throw new Error(`YOLO server returned ${response.status}`);
        }

        const result: {
          room_id: string;
          people_count: number;
          timestamp: string;
        } = await response.json();

        if (active) {
          setCount(result.people_count);
          setStatus(`Last updated: ${new Date().toLocaleTimeString()}`);
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
  }, [cameraReady, facing, permission?.granted]);

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

      <View style={styles.panel}>
        <Text style={styles.label}>PEOPLE DETECTED</Text>
        <Text style={styles.count}>{count ?? '—'}</Text>
        <Text style={styles.status}>{status}</Text>

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

        <Text style={styles.privacy}>
          Development prototype: camera frames are sent to your laptop
          for YOLO analysis. Temporary photo files are deleted after
          each request.
        </Text>
      </View>
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
  privacy: {
    color: '#aab6ca',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 16,
    lineHeight: 17,
  },
});
