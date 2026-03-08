import React, { useState, useRef } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from "react-native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiPost } from "../services/api";

type RecordingState = "idle" | "recording" | "recorded" | "uploading" | "done";

interface Props {
  onBack: () => void;
}

export default function RecordStoryScreen({ onBack }: Props) {
  const { householdId, userId } = useAuth();
  const [title, setTitle] = useState("");
  const [state, setState] = useState<RecordingState>("idle");
  const [duration, setDuration] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function startRecording() {
    if (!title.trim()) {
      Alert.alert("Error", "Please enter a story title first.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setAudioBlob(blob);
        setState("recorded");
        stream.getTracks().forEach((t) => t.stop());
      };

      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setState("recording");
      setDuration(0);

      timerRef.current = setInterval(() => {
        setDuration((d) => d + 1);
      }, 1000);
    } catch (err: any) {
      Alert.alert("Microphone Error", "Could not access microphone. Please allow microphone access.");
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  function discardRecording() {
    setAudioBlob(null);
    setDuration(0);
    setState("idle");
  }

  async function uploadRecording() {
    if (!audioBlob || !householdId || !userId) return;

    setState("uploading");
    try {
      // 1. Create story record
      const story = await apiPost("/stories", {
        householdId,
        readerId: userId,
        title: title.trim(),
      });

      // 2. Get presigned upload URL
      const { uploadUrl } = await apiGet<{ uploadUrl: string }>(
        `/stories/${story.storyId}/upload-url`
      );

      // 3. Upload audio to S3
      const res = await fetch(uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": "audio/mpeg" },
        body: audioBlob,
      });

      if (!res.ok) throw new Error("Upload failed");

      // 4. Confirm upload — marks story as "ready"
      await apiPost(`/stories/${story.storyId}/confirm`, {});

      setState("done");
    } catch (err: any) {
      Alert.alert("Upload Failed", err.message || "Please try again.");
      setState("recorded");
    }
  }

  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

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
            <Text style={styles.timer}>{formatTime(duration)}</Text>

            {state === "recording" && (
              <Text style={styles.recordingDot}>Recording...</Text>
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

            {state === "recorded" && (
              <View style={styles.actionRow}>
                <TouchableOpacity style={styles.secondaryButton} onPress={discardRecording}>
                  <Text style={styles.secondaryButtonText}>Discard</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.primaryButton} onPress={uploadRecording}>
                  <Text style={styles.primaryButtonText}>Upload Story</Text>
                </TouchableOpacity>
              </View>
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
            {state === "recording" && "Tap the square to stop recording."}
            {state === "recorded" && `${formatTime(duration)} recorded. Upload or discard.`}
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
  recordingDot: {
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
  actionRow: {
    flexDirection: "row",
    gap: 12,
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
  primaryButton: {
    backgroundColor: "#7c3aed",
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 24,
    alignItems: "center",
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
  hint: {
    fontSize: 14,
    color: "#6b7280",
    textAlign: "center",
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
