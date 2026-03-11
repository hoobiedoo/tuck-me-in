import React, { useState, useRef, useEffect } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Image,
} from "react-native";
import { Audio } from "expo-av";
import * as ImagePicker from "expo-image-picker";
import { useNavigation, useRoute } from "@react-navigation/native";
import type { BottomTabNavigationProp } from "@react-navigation/bottom-tabs";
import type { RouteProp } from "@react-navigation/native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiPost, apiPut } from "../services/api";
import WaveformTrimmer from "../components/WaveformTrimmer";
import type { MainTabsParamList } from "../navigation/MainTabs";

type RecordingState = "idle" | "recording" | "preview" | "uploading" | "done";
type Nav = BottomTabNavigationProp<MainTabsParamList, "Record">;
type Route = RouteProp<MainTabsParamList, "Record">;

export default function RecordStoryScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const initialTitle = route.params?.initialTitle || "";
  const requestId = route.params?.requestId;

  const { householdId, userId, user, maxDurationSeconds, subscriptionTier } = useAuth();
  const [title, setTitle] = useState(initialTitle);
  const [state, setState] = useState<RecordingState>("idle");
  const [recordDuration, setRecordDuration] = useState(0);
  const [recordingUri, setRecordingUri] = useState<string | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [exceedingLimit, setExceedingLimit] = useState(false);

  // Preview playback via HTMLAudioElement (avoids expo-av web emit bug)
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackPosition, setPlaybackPosition] = useState(0);
  const [playbackDuration, setPlaybackDuration] = useState(0);

  // Trim state
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);

  // Cover image state
  const [coverImageUri, setCoverImageUri] = useState<string | null>(null);

  // Update title when navigating to this tab with params
  useEffect(() => {
    if (route.params?.initialTitle) {
      setTitle(route.params.initialTitle);
    }
  }, [route.params?.initialTitle]);

  useEffect(() => {
    return () => {
      if (recordingRef.current) {
        recordingRef.current.stopAndUnloadAsync().catch(() => {});
      }
      if (timerRef.current) clearInterval(timerRef.current);
      cleanupAudio();
    };
  }, []);

  function cleanupAudio() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
  }

  function loadPreviewAudio(uri: string) {
    const audio = document.createElement("audio");
    audio.src = uri;
    audio.addEventListener("loadedmetadata", () => {
      const durMs = Math.round(audio.duration * 1000);
      setPlaybackDuration(durMs);
      setTrimStart(0);
      setTrimEnd(durMs);
    });
    audio.addEventListener("ended", () => {
      setIsPlaying(false);
      stopPolling();
    });
    audioRef.current = audio;
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      if (audioRef.current) {
        const posMs = Math.round(audioRef.current.currentTime * 1000);
        setPlaybackPosition(posMs);
        // Stop at trim end
        if (posMs >= trimEnd) {
          audioRef.current.pause();
          audioRef.current.currentTime = trimEnd / 1000;
          setPlaybackPosition(trimEnd);
          setIsPlaying(false);
          stopPolling();
        }
      }
    }, 50);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

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
        setRecordDuration((d) => {
          const newDuration = d + 1;
          // Check if exceeding tier limit
          if (newDuration > maxDurationSeconds && !exceedingLimit) {
            setExceedingLimit(true);
          }
          return newDuration;
        });
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

      await Audio.setAudioModeAsync({ allowsRecordingIOS: false });

      if (uri) {
        loadPreviewAudio(uri);
      }

      setState("preview");
      // Keep exceedingLimit state to show banner in preview
    } catch (err: any) {
      Alert.alert("Error", "Could not stop recording.");
      setState("idle");
    }
  }

  function togglePlayback() {
    if (!audioRef.current) return;

    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
      stopPolling();
    } else {
      const posMs = Math.round(audioRef.current.currentTime * 1000);
      // Start from trimStart if playhead is outside the trim region or at/past trimEnd
      if (posMs < trimStart || posMs >= trimEnd || audioRef.current.ended) {
        audioRef.current.currentTime = trimStart / 1000;
        setPlaybackPosition(trimStart);
      }
      audioRef.current.play();
      setIsPlaying(true);
      startPolling();
    }
  }

  function seekTo(positionMs: number) {
    if (!audioRef.current) return;
    audioRef.current.currentTime = positionMs / 1000;
    setPlaybackPosition(positionMs);
  }

  function handleTrimChange(startMs: number, endMs: number) {
    setTrimStart(startMs);
    setTrimEnd(endMs);
  }

  function discardRecording() {
    cleanupAudio();
    setRecordingUri(null);
    setCoverImageUri(null);
    setRecordDuration(0);
    setPlaybackPosition(0);
    setPlaybackDuration(0);
    setTrimStart(0);
    setTrimEnd(0);
    setIsPlaying(false);
    setExceedingLimit(false);
    setState("idle");
  }

  async function pickCoverImage() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert("Permission Required", "Please allow access to your photo library to add cover images.");
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });

    if (!result.canceled && result.assets[0]) {
      setCoverImageUri(result.assets[0].uri);
    }
  }

  async function uploadRecording() {
    if (!recordingUri || !householdId || !userId) return;

    if (audioRef.current && isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
      stopPolling();
    }

    setState("uploading");
    try {
      const hasTrim = trimStart > 0 || trimEnd < playbackDuration;

      const readerName = user ? `${user.firstName} ${user.lastName}`.trim() : "Unknown";
      const story = await apiPost("/stories", {
        householdId,
        readerId: userId,
        readerName,
        title: title.trim(),
        ...(hasTrim && { trimStartMs: trimStart, trimEndMs: trimEnd }),
      });

      // Upload cover image if provided
      if (coverImageUri) {
        try {
          const { uploadUrl } = await apiGet<{ uploadUrl: string }>(
            `/stories/${story.storyId}/cover-upload-url`
          );

          const coverResponse = await fetch(coverImageUri);
          const coverBlob = await coverResponse.blob();

          const coverRes = await fetch(uploadUrl, {
            method: "PUT",
            headers: { "Content-Type": "image/jpeg" },
            body: coverBlob,
          });

          if (!coverRes.ok) {
            console.warn("Cover image upload failed, continuing with audio upload");
          }
        } catch (err) {
          console.warn("Cover image upload error:", err);
          // Non-critical, continue with audio upload
        }
      }

      const { uploadUrl } = await apiGet<{ uploadUrl: string }>(
        `/stories/${story.storyId}/upload-url`
      );

      const fileResponse = await fetch(recordingUri);
      const blob = await fileResponse.blob();

      const res = await fetch(uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": "audio/mpeg" },
        body: blob,
      });

      if (!res.ok) throw new Error("Upload failed");

      // Confirm upload - this validates file size/duration on the server
      await apiPost(`/stories/${story.storyId}/confirm`, {});

      // Link story back to request if recording was triggered by one
      if (requestId) {
        try {
          await apiPut(`/requests/${requestId}`, {
            status: "completed",
            resultingStoryId: story.storyId,
          });
        } catch {
          // Non-critical
        }
      }

      cleanupAudio();
      setState("done");
    } catch (err: any) {
      Alert.alert("Upload Failed", err.message || "Please try again.");
      setState("preview");
    }
  }

  function handleDone() {
    // Reset state for next recording
    setTitle("");
    setRecordingUri(null);
    setCoverImageUri(null);
    setRecordDuration(0);
    setPlaybackPosition(0);
    setPlaybackDuration(0);
    setTrimStart(0);
    setTrimEnd(0);
    setIsPlaying(false);
    setExceedingLimit(false);
    setState("idle");
    navigation.navigate("Home");
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
  const trimmedDurationSeconds = Math.round(trimmedDuration / 1000);
  const isTrimmedTooLong = trimmedDurationSeconds > maxDurationSeconds;

  return (
    <View style={styles.container}>
      {state === "done" ? (
        <View style={styles.center}>
          <Text style={styles.doneIcon}>&#10003;</Text>
          <Text style={styles.doneTitle}>Story Uploaded!</Text>
          <Text style={styles.doneDesc}>
            "{title}" is now being processed and will appear in the Story Library shortly.
          </Text>
          <TouchableOpacity style={styles.primaryButton} onPress={handleDone}>
            <Text style={styles.primaryButtonText}>Back to Home</Text>
          </TouchableOpacity>
        </View>
      ) : state === "preview" ? (
        <View style={styles.content}>
          <Text style={styles.titlePreview}>{title}</Text>

          {/* Warning banner if recording exceeds tier limit */}
          {exceedingLimit && (
            <View style={styles.warningBanner}>
              <Text style={styles.warningText}>
                ⚠️ Recording is {formatTime(recordDuration)} - exceeds {maxDurationSeconds < 60 ? `${maxDurationSeconds}s` : `${Math.round(maxDurationSeconds / 60)}min`} limit ({subscriptionTier || "free"} plan)
              </Text>
              <Text style={styles.warningSubtext}>
                {isTrimmedTooLong
                  ? `Use trim handles below to shorten it to ${maxDurationSeconds < 60 ? `${maxDurationSeconds}s` : `${Math.round(maxDurationSeconds / 60)}min`} or less.`
                  : "✓ Trimmed duration is now within limit!"
                }
              </Text>
            </View>
          )}

          {/* Cover Image Selector */}
          <TouchableOpacity style={styles.coverImageBox} onPress={pickCoverImage}>
            {coverImageUri ? (
              <Image source={{ uri: coverImageUri }} style={styles.coverImage} />
            ) : (
              <View style={styles.coverPlaceholder}>
                <Text style={styles.coverPlaceholderIcon}>📷</Text>
                <Text style={styles.coverPlaceholderText}>Tap to add cover image</Text>
              </View>
            )}
          </TouchableOpacity>

          <View style={styles.previewBox}>
            {recordingUri && playbackDuration > 0 && (
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

            <View style={styles.timeRow}>
              <Text style={styles.timeText}>{formatMs(playbackPosition)}</Text>
              <Text style={styles.timeText}>{formatMs(playbackDuration)}</Text>
            </View>

            {hasTrim && (
              <View style={styles.trimInfo}>
                <Text style={styles.trimInfoText}>
                  Trimmed: {formatMs(trimStart)} - {formatMs(trimEnd)} ({formatMs(trimmedDuration)})
                </Text>
                <TouchableOpacity
                  onPress={() => { setTrimStart(0); setTrimEnd(playbackDuration); }}
                >
                  <Text style={styles.trimResetText}>Reset</Text>
                </TouchableOpacity>
              </View>
            )}

            <View style={styles.playbackControls}>
              <TouchableOpacity
                style={styles.skipButton}
                onPress={() => seekTo(Math.max(trimStart, playbackPosition - 5000))}
              >
                <Text style={styles.skipText}>-5s</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.playPauseButton} onPress={togglePlayback}>
                <Text style={styles.playPauseText}>{isPlaying ? "||" : ">"}</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.skipButton}
                onPress={() => seekTo(Math.min(trimEnd, playbackPosition + 5000))}
              >
                <Text style={styles.skipText}>+5s</Text>
              </TouchableOpacity>
            </View>
          </View>

          <Text style={styles.hint}>
            {isTrimmedTooLong
              ? `Drag the yellow handles to trim to ${maxDurationSeconds < 60 ? `${maxDurationSeconds}s` : `${Math.round(maxDurationSeconds / 60)}min`} or less.`
              : "Drag the yellow handles to trim your recording."
            }
          </Text>

          <View style={styles.previewActions}>
            <TouchableOpacity style={styles.secondaryButton} onPress={discardRecording}>
              <Text style={styles.secondaryButtonText}>Re-record</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.primaryButton, isTrimmedTooLong && styles.primaryButtonDisabled]}
              onPress={uploadRecording}
              disabled={isTrimmedTooLong}
            >
              <Text style={[styles.primaryButtonText, isTrimmedTooLong && styles.primaryButtonTextDisabled]}>
                {isTrimmedTooLong
                  ? `Too long (${formatMs(trimmedDuration)})`
                  : `Upload (${formatMs(trimmedDuration)})`
                }
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : state === "uploading" ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#5B9FB8" />
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

            {state === "recording" && exceedingLimit && (
              <View style={styles.warningBanner}>
                <Text style={styles.warningText}>
                  ⚠️ Exceeded {maxDurationSeconds < 60 ? `${maxDurationSeconds}s` : `${Math.round(maxDurationSeconds / 60)}min`} limit
                  {subscriptionTier === "free" && " - Upgrade to Premium"}
                </Text>
              </View>
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
            {state === "idle" && `Tap the red button to start recording. Max: ${maxDurationSeconds < 60 ? `${maxDurationSeconds}s` : `${Math.round(maxDurationSeconds / 60)}min`} (${subscriptionTier || "free"} plan)`}
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
    backgroundColor: "#FBF8F3",
  },
  content: {
    padding: 24,
  },
  label: {
    fontSize: 14,
    fontWeight: "600",
    color: "#4E535B",
    marginBottom: 6,
  },
  titlePreview: {
    fontSize: 20,
    fontWeight: "700",
    color: "#3D4148",
    marginBottom: 20,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#D6D1CA",
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
    borderColor: "#E8E3DC",
    marginBottom: 16,
  },
  timer: {
    fontSize: 48,
    fontWeight: "300",
    color: "#3D4148",
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
    borderColor: "#D6D1CA",
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
    borderColor: "#D6D1CA",
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
    color: "#9A9EA5",
    textAlign: "center",
    marginBottom: 20,
  },
  previewBox: {
    backgroundColor: "#2E3239",
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
  },
  timeRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 12,
    marginBottom: 16,
  },
  timeText: {
    fontSize: 13,
    color: "#9A9EA5",
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
    color: "#9A9EA5",
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
    color: "#9A9EA5",
  },
  playPauseButton: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: "#5B9FB8",
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
    backgroundColor: "#5B9FB8",
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
    borderColor: "#D6D1CA",
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 24,
    alignItems: "center",
  },
  secondaryButtonText: {
    color: "#7A7E85",
    fontSize: 16,
  },
  uploadingText: {
    fontSize: 16,
    color: "#5B9FB8",
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
    color: "#3D4148",
    marginBottom: 8,
  },
  doneDesc: {
    fontSize: 16,
    color: "#7A7E85",
    textAlign: "center",
    marginBottom: 24,
  },
  coverImageBox: {
    width: 120,
    height: 120,
    borderRadius: 12,
    backgroundColor: "#fff",
    borderWidth: 2,
    borderColor: "#E8E3DC",
    borderStyle: "dashed",
    marginBottom: 20,
    overflow: "hidden",
    alignSelf: "center",
  },
  coverImage: {
    width: "100%",
    height: "100%",
  },
  coverPlaceholder: {
    width: "100%",
    height: "100%",
    alignItems: "center",
    justifyContent: "center",
  },
  coverPlaceholderIcon: {
    fontSize: 36,
    marginBottom: 8,
  },
  coverPlaceholderText: {
    fontSize: 12,
    color: "#9A9EA5",
    textAlign: "center",
  },
  warningBanner: {
    backgroundColor: "#fef3c7",
    borderWidth: 1,
    borderColor: "#f59e0b",
    borderRadius: 8,
    padding: 12,
    marginTop: 12,
    marginBottom: 12,
  },
  warningText: {
    fontSize: 14,
    fontWeight: "600",
    color: "#92400e",
    textAlign: "center",
    marginBottom: 4,
  },
  warningSubtext: {
    fontSize: 12,
    color: "#92400e",
    textAlign: "center",
  },
  primaryButtonDisabled: {
    backgroundColor: "#9A9EA5",
    opacity: 0.6,
  },
  primaryButtonTextDisabled: {
    color: "#E8E3DC",
  },
});
