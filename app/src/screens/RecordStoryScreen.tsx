import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from "react-native";
import { Audio, AVPlaybackStatus } from "expo-av";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiPost } from "../services/api";
import WaveformTrimmer from "../components/WaveformTrimmer";

type RecordingState = "idle" | "recording" | "preview" | "uploading" | "done";

interface Props {
  onBack: () => void;
}

export default function RecordStoryScreen({ onBack }: Props) {
  const { householdId, userId } = useAuth();
  const [title, setTitle] = useState("");
  const [state, setState] = useState<RecordingState>("idle");
  const [recordDuration, setRecordDuration] = useState(0);
  const [recordingUri, setRecordingUri] = useState<string | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Preview state
  const soundRef = useRef<Audio.Sound | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackPosition, setPlaybackPosition] = useState(0);
  const [playbackDuration, setPlaybackDuration] = useState(0);

  // Trim state
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);

  useEffect(() => {
    return () => {
      if (recordingRef.current) {
        recordingRef.current.stopAndUnloadAsync().catch(() => {});
      }
      if (soundRef.current) {
        soundRef.current.unloadAsync().catch(() => {});
      }
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const onPlaybackStatusUpdate = useCallback((status: AVPlaybackStatus) => {
    if (!status.isLoaded) return;
    setPlaybackPosition(status.positionMillis);
    setPlaybackDuration(status.durationMillis || 0);
    if (status.didJustFinish) {
      setIsPlaying(false);
    }
  }, []);

  async function startRecording() {
    if (!title.trim()) {
      Alert.alert("Error", "Please enter a story title first.");
      return;
    }
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Permission Required", "Please allow microphone access to record stories.");
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = recording;
      setState("recording");
      setRecordDuration(0);

      timerRef.current = setInterval(() => {
        setRecordDuration((d) => d + 1);
      }, 1000);
    } catch (err: any) {
      Alert.alert("Microphone Error", "Could not start recording. Please check microphone permissions.");
    }
  }

  async function stopRecording() {
    if (!recordingRef.current) return;

    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    try {
      await recordingRef.current.stopAndUnloadAsync();
      const uri = recordingRef.current.getURI();
      recordingRef.current = null;
      setRecordingUri(uri);

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        playsInSilentModeIOS: true,
      });

      // Load for preview
      if (uri) {
        const { sound } = await Audio.Sound.createAsync(
          { uri },
          { progressUpdateIntervalMillis: 100 },
          onPlaybackStatusUpdate
        );
        soundRef.current = sound;

        const status = await sound.getStatusAsync();
        if (status.isLoaded && status.durationMillis) {
          setPlaybackDuration(status.durationMillis);
          setTrimStart(0);
          setTrimEnd(status.durationMillis);
        }
      }

      setState("preview");
    } catch (err: any) {
      Alert.alert("Error", "Could not stop recording.");
      setState("idle");
    }
  }

  async function togglePlayback() {
    if (!soundRef.current) return;

    if (isPlaying) {
      await soundRef.current.pauseAsync();
      setIsPlaying(false);
    } else {
      const status = await soundRef.current.getStatusAsync();
      if (status.isLoaded && status.didJustFinish) {
        await soundRef.current.setPositionAsync(trimStart);
      }
      await soundRef.current.playAsync();
      setIsPlaying(true);
    }
  }

  async function seekTo(positionMs: number) {
    if (!soundRef.current) return;
    await soundRef.current.setPositionAsync(positionMs);
    setPlaybackPosition(positionMs);
  }

  function handleTrimChange(startMs: number, endMs: number) {
    setTrimStart(startMs);
    setTrimEnd(endMs);
  }

  async function discardRecording() {
    if (soundRef.current) {
      await soundRef.current.unloadAsync();
      soundRef.current = null;
    }
    setRecordingUri(null);
    setRecordDuration(0);
    setPlaybackPosition(0);
    setPlaybackDuration(0);
    setTrimStart(0);
    setTrimEnd(0);
    setIsPlaying(false);
    setState("idle");
  }

  async function uploadRecording() {
    if (!recordingUri || !householdId || !userId) return;

    if (soundRef.current && isPlaying) {
      await soundRef.current.pauseAsync();
      setIsPlaying(false);
    }

    setState("uploading");
    try {
      const hasTrim = trimStart > 0 || trimEnd < playbackDuration;

      // 1. Create story record
      const story = await apiPost("/stories", {
        householdId,
        readerId: userId,
        title: title.trim(),
        ...(hasTrim && {
          trimStartMs: trimStart,
          trimEndMs: trimEnd,
        }),
      });

      // 2. Get presigned upload URL
      const { uploadUrl } = await apiGet<{ uploadUrl: string }>(
        `/stories/${story.storyId}/upload-url`
      );

      // 3. Read file and upload to S3
      const fileResponse = await fetch(recordingUri);
      const blob = await fileResponse.blob();

      const res = await fetch(uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": "audio/mpeg" },
        body: blob,
      });

      if (!res.ok) throw new Error("Upload failed");

      // 4. Confirm upload
      await apiPost(`/stories/${story.storyId}/confirm`, {});

      if (soundRef.current) {
        await soundRef.current.unloadAsync();
        soundRef.current = null;
      }

      setState("done");
    } catch (err: any) {
      Alert.alert("Upload Failed", err.message || "Please try again.");
      setState("preview");
    }
  }

  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function formatMs(ms: number): string {
    return formatTime(Math.round(ms / 1000));
  }

  const trimmedDuration = trimEnd - trimStart;
  const hasTrim = trimStart > 0 || trimEnd < playbackDuration;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack}>
          <Text style={styles.backButton}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Record a Story</Text>
        <View style={{ width: 40 }} />
      </View>

      {state === "done" ? (
        <View style={styles.center}>
          <Text style={styles.doneIcon}>&#10003;</Text>
          <Text style={styles.doneTitle}>Story Uploaded!</Text>
          <Text style={styles.doneDesc}>
            "{title}" is now being processed and will appear in the Story Library shortly.
          </Text>
          <TouchableOpacity style={styles.primaryButton} onPress={onBack}>
            <Text style={styles.primaryButtonText}>Back to Home</Text>
          </TouchableOpacity>
        </View>
      ) : state === "preview" ? (
        <View style={styles.content}>
          <Text style={styles.titlePreview}>{title}</Text>

          {/* Waveform trimmer */}
          <View style={styles.previewBox}>
            {recordingUri && (
              <WaveformTrimmer
                audioUri={recordingUri}
                durationMs={playbackDuration}
                playbackPositionMs={playbackPosition}
                trimStartMs={trimStart}
                trimEndMs={trimEnd}
                onTrimChange={handleTrimChange}
                onSeek={seekTo}
              />
            )}

            {/* Time display */}
            <View style={styles.timeRow}>
              <Text style={styles.timeText}>{formatMs(playbackPosition)}</Text>
              <Text style={styles.timeText}>{formatMs(playbackDuration)}</Text>
            </View>

            {/* Trim info */}
            {hasTrim && (
              <View style={styles.trimInfo}>
                <Text style={styles.trimInfoText}>
                  Trimmed: {formatMs(trimStart)} - {formatMs(trimEnd)} ({formatMs(trimmedDuration)})
                </Text>
                <TouchableOpacity
                  onPress={() => {
                    setTrimStart(0);
                    setTrimEnd(playbackDuration);
                  }}
                >
                  <Text style={styles.trimResetText}>Reset</Text>
                </TouchableOpacity>
              </View>
            )}

            {/* Playback controls */}
            <View style={styles.playbackControls}>
              <TouchableOpacity
                style={styles.skipButton}
                onPress={() => seekTo(Math.max(0, playbackPosition - 5000))}
              >
                <Text style={styles.skipText}>-5s</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.playPauseButton} onPress={togglePlayback}>
                <Text style={styles.playPauseText}>{isPlaying ? "||" : ">"}</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.skipButton}
                onPress={() => seekTo(Math.min(playbackDuration, playbackPosition + 5000))}
              >
                <Text style={styles.skipText}>+5s</Text>
              </TouchableOpacity>
            </View>
          </View>

          <Text style={styles.hint}>Drag the yellow handles to trim your recording.</Text>

          {/* Actions */}
          <View style={styles.previewActions}>
            <TouchableOpacity style={styles.secondaryButton} onPress={discardRecording}>
              <Text style={styles.secondaryButtonText}>Re-record</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.primaryButton} onPress={uploadRecording}>
              <Text style={styles.primaryButtonText}>
                Upload{hasTrim ? ` (${formatMs(trimmedDuration)})` : ""}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : state === "uploading" ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#7c3aed" />
          <Text style={styles.uploadingText}>Uploading story...</Text>
        </View>
      ) : (
        <View style={styles.content}>
          <Text style={styles.label}>Story Title</Text>
          <TextInput
            style={styles.input}
            placeholder="e.g. Goodnight Moon"
            value={title}
            onChangeText={setTitle}
            editable={state === "idle"}
          />

          <View style={styles.recorderBox}>
            <Text style={styles.timer}>{formatTime(recordDuration)}</Text>

            {state === "recording" && (
              <Text style={styles.recordingLabel}>Recording...</Text>
            )}

            {state === "idle" && (
              <TouchableOpacity style={styles.recordButton} onPress={startRecording}>
                <View style={styles.recordDot} />
              </TouchableOpacity>
            )}

            {state === "recording" && (
              <TouchableOpacity style={styles.stopButton} onPress={stopRecording}>
                <View style={styles.stopSquare} />
              </TouchableOpacity>
            )}
          </View>

          <Text style={styles.hint}>
            {state === "idle" && "Tap the red button to start recording."}
            {state === "recording" && "Tap the square to stop and preview."}
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#f8f4ff",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 60,
    paddingBottom: 16,
  },
  backButton: {
    fontSize: 16,
    color: "#7c3aed",
    fontWeight: "600",
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: "bold",
    color: "#5b21b6",
  },
  content: {
    padding: 24,
  },
  label: {
    fontSize: 14,
    fontWeight: "600",
    color: "#374151",
    marginBottom: 6,
  },
  titlePreview: {
    fontSize: 20,
    fontWeight: "700",
    color: "#1f2937",
    marginBottom: 20,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 8,
    padding: 14,
    fontSize: 16,
    marginBottom: 24,
  },
  recorderBox: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 32,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#e5e7eb",
    marginBottom: 16,
  },
  timer: {
    fontSize: 48,
    fontWeight: "300",
    color: "#1f2937",
    fontVariant: ["tabular-nums"],
    marginBottom: 24,
  },
  recordingLabel: {
    color: "#dc2626",
    fontSize: 14,
    fontWeight: "600",
    marginBottom: 16,
  },
  recordButton: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 4,
    borderColor: "#d1d5db",
    alignItems: "center",
    justifyContent: "center",
  },
  recordDot: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "#dc2626",
  },
  stopButton: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 4,
    borderColor: "#d1d5db",
    alignItems: "center",
    justifyContent: "center",
  },
  stopSquare: {
    width: 28,
    height: 28,
    borderRadius: 4,
    backgroundColor: "#dc2626",
  },
  hint: {
    fontSize: 14,
    color: "#9ca3af",
    textAlign: "center",
    marginBottom: 20,
  },

  // Preview styles
  previewBox: {
    backgroundColor: "#1f2937",
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
  },
  timeRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 10,
    marginBottom: 16,
  },
  timeText: {
    fontSize: 13,
    color: "#9ca3af",
    fontVariant: ["tabular-nums"],
  },
  trimInfo: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    borderRadius: 8,
    padding: 10,
  },
  trimInfoText: {
    fontSize: 13,
    color: "#f59e0b",
    fontVariant: ["tabular-nums"],
  },
  trimResetText: {
    fontSize: 13,
    color: "#9ca3af",
    fontWeight: "600",
  },
  playbackControls: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 20,
  },
  skipButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(255,255,255,0.1)",
    alignItems: "center",
    justifyContent: "center",
  },
  skipText: {
    fontSize: 13,
    fontWeight: "600",
    color: "#9ca3af",
  },
  playPauseButton: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: "#7c3aed",
    alignItems: "center",
    justifyContent: "center",
  },
  playPauseText: {
    fontSize: 24,
    fontWeight: "bold",
    color: "#fff",
  },
  previewActions: {
    flexDirection: "row",
    gap: 12,
  },
  primaryButton: {
    backgroundColor: "#7c3aed",
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 24,
    alignItems: "center",
    flex: 1,
  },
  primaryButtonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  secondaryButton: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 24,
    alignItems: "center",
  },
  secondaryButtonText: {
    color: "#6b7280",
    fontSize: 16,
  },
  uploadingText: {
    fontSize: 16,
    color: "#7c3aed",
    marginTop: 12,
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  doneIcon: {
    fontSize: 64,
    color: "#16a34a",
    marginBottom: 16,
  },
  doneTitle: {
    fontSize: 24,
    fontWeight: "bold",
    color: "#1f2937",
    marginBottom: 8,
  },
  doneDesc: {
    fontSize: 16,
    color: "#6b7280",
    textAlign: "center",
    marginBottom: 24,
  },
});
