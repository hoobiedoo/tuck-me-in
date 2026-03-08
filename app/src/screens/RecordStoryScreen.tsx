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
          { progressUpdateIntervalMillis: 200 },
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
      // If at the end, restart from trim start
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

  function markTrimStart() {
    if (playbackPosition < trimEnd) {
      setTrimStart(playbackPosition);
    }
  }

  function markTrimEnd() {
    if (playbackPosition > trimStart) {
      setTrimEnd(playbackPosition);
    }
  }

  function resetTrim() {
    setTrimStart(0);
    setTrimEnd(playbackDuration);
  }

  async function previewTrimmed() {
    if (!soundRef.current) return;
    await soundRef.current.setPositionAsync(trimStart);
    await soundRef.current.playAsync();
    setIsPlaying(true);
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

    // Stop playback if playing
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

      // 4. Confirm upload — marks story as "ready"
      await apiPost(`/stories/${story.storyId}/confirm`, {});

      // Clean up sound
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
    return formatTime(Math.floor(ms / 1000));
  }

  const trimmedDuration = trimEnd - trimStart;
  const hasTrim = trimStart > 0 || trimEnd < playbackDuration;
  const progressPercent = playbackDuration > 0 ? (playbackPosition / playbackDuration) * 100 : 0;
  const trimStartPercent = playbackDuration > 0 ? (trimStart / playbackDuration) * 100 : 0;
  const trimWidthPercent = playbackDuration > 0 ? ((trimEnd - trimStart) / playbackDuration) * 100 : 100;

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
          <Text style={styles.label}>Story Title</Text>
          <Text style={styles.titlePreview}>{title}</Text>

          <View style={styles.previewBox}>
            {/* Time display */}
            <Text style={styles.previewTime}>
              {formatMs(playbackPosition)} / {formatMs(playbackDuration)}
            </Text>

            {/* Progress bar with trim region */}
            <View style={styles.progressContainer}>
              {/* Trim region highlight */}
              <View
                style={[
                  styles.trimRegion,
                  { left: `${trimStartPercent}%`, width: `${trimWidthPercent}%` },
                ]}
              />
              {/* Playback progress */}
              <View style={[styles.progressFill, { width: `${progressPercent}%` }]} />
              {/* Trim start marker */}
              {hasTrim && (
                <View style={[styles.trimMarker, { left: `${trimStartPercent}%` }]} />
              )}
              {/* Trim end marker */}
              {hasTrim && (
                <View
                  style={[
                    styles.trimMarker,
                    { left: `${trimStartPercent + trimWidthPercent}%` },
                  ]}
                />
              )}
            </View>

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

            {/* Trim controls */}
            <View style={styles.trimSection}>
              <Text style={styles.trimTitle}>Trim</Text>
              <View style={styles.trimControls}>
                <TouchableOpacity style={styles.trimButton} onPress={markTrimStart}>
                  <Text style={styles.trimButtonText}>Set Start</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.trimButton} onPress={markTrimEnd}>
                  <Text style={styles.trimButtonText}>Set End</Text>
                </TouchableOpacity>
                {hasTrim && (
                  <TouchableOpacity style={styles.trimResetButton} onPress={resetTrim}>
                    <Text style={styles.trimResetText}>Reset</Text>
                  </TouchableOpacity>
                )}
              </View>
              {hasTrim && (
                <View style={styles.trimInfo}>
                  <Text style={styles.trimInfoText}>
                    {formatMs(trimStart)} - {formatMs(trimEnd)} ({formatMs(trimmedDuration)})
                  </Text>
                  <TouchableOpacity onPress={previewTrimmed}>
                    <Text style={styles.previewTrimLink}>Preview from start</Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>
          </View>

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

            {state === "uploading" && (
              <View style={styles.uploadingRow}>
                <ActivityIndicator color="#7c3aed" />
                <Text style={styles.uploadingText}>Uploading...</Text>
              </View>
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
    fontSize: 18,
    fontWeight: "600",
    color: "#1f2937",
    marginBottom: 16,
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
  uploadingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  uploadingText: {
    fontSize: 16,
    color: "#7c3aed",
  },
  hint: {
    fontSize: 14,
    color: "#6b7280",
    textAlign: "center",
  },

  // Preview styles
  previewBox: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 24,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    marginBottom: 20,
  },
  previewTime: {
    fontSize: 16,
    fontWeight: "500",
    color: "#1f2937",
    textAlign: "center",
    fontVariant: ["tabular-nums"],
    marginBottom: 16,
  },
  progressContainer: {
    height: 8,
    backgroundColor: "#e5e7eb",
    borderRadius: 4,
    marginBottom: 20,
    overflow: "visible",
    position: "relative",
  },
  progressFill: {
    position: "absolute",
    top: 0,
    left: 0,
    height: 8,
    backgroundColor: "#7c3aed",
    borderRadius: 4,
    zIndex: 2,
  },
  trimRegion: {
    position: "absolute",
    top: -2,
    height: 12,
    backgroundColor: "rgba(124, 58, 237, 0.15)",
    borderRadius: 6,
    zIndex: 1,
  },
  trimMarker: {
    position: "absolute",
    top: -6,
    width: 3,
    height: 20,
    backgroundColor: "#7c3aed",
    borderRadius: 2,
    zIndex: 3,
    marginLeft: -1,
  },
  playbackControls: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 20,
    marginBottom: 20,
  },
  skipButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "#f3f4f6",
    alignItems: "center",
    justifyContent: "center",
  },
  skipText: {
    fontSize: 13,
    fontWeight: "600",
    color: "#6b7280",
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
  trimSection: {
    borderTopWidth: 1,
    borderTopColor: "#f3f4f6",
    paddingTop: 16,
  },
  trimTitle: {
    fontSize: 14,
    fontWeight: "600",
    color: "#374151",
    marginBottom: 10,
  },
  trimControls: {
    flexDirection: "row",
    gap: 8,
  },
  trimButton: {
    backgroundColor: "#f3f4f6",
    borderRadius: 6,
    paddingVertical: 8,
    paddingHorizontal: 14,
  },
  trimButtonText: {
    fontSize: 13,
    fontWeight: "600",
    color: "#374151",
  },
  trimResetButton: {
    paddingVertical: 8,
    paddingHorizontal: 14,
  },
  trimResetText: {
    fontSize: 13,
    color: "#9ca3af",
  },
  trimInfo: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 10,
  },
  trimInfoText: {
    fontSize: 13,
    color: "#6b7280",
    fontVariant: ["tabular-nums"],
  },
  previewTrimLink: {
    fontSize: 13,
    color: "#7c3aed",
    fontWeight: "600",
  },
  previewActions: {
    flexDirection: "row",
    gap: 12,
    justifyContent: "center",
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
