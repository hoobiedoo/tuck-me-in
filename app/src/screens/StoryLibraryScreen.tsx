import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from "react-native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiDelete } from "../services/api";
import { AWS_CONFIG } from "../config/aws";

interface Story {
  storyId: string;
  title: string;
  readerId: string;
  readerName?: string;
  audioKey: string;
  durationSeconds: number;
  createdAt: string;
  status: string;
}

export default function StoryLibraryScreen() {
  const { householdId, userId, userRole } = useAuth();
  const [stories, setStories] = useState<Story[]>([]);
  const [loading, setLoading] = useState(true);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const loadStories = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    try {
      const data = await apiGet<Story[]>(`/stories?householdId=${householdId}`);
      setStories(data);
    } catch (err: any) {
      Alert.alert("Error", "Could not load stories.");
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => {
    loadStories();
  }, [loadStories]);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
        audioRef.current = null;
      }
    };
  }, []);

  function handlePlay(story: Story) {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
      if (playingId === story.storyId) {
        setPlayingId(null);
        return;
      }
    }

    const audioUrl = `${AWS_CONFIG.audioCdnBase}/${story.audioKey}`;
    try {
      const audio = new window.Audio(audioUrl);
      audio.onended = () => {
        setPlayingId(null);
        audioRef.current = null;
      };
      audio.onerror = () => {
        Alert.alert("Playback Error", "Could not play this story.");
        setPlayingId(null);
        audioRef.current = null;
      };
      audio.play();
      audioRef.current = audio;
      setPlayingId(story.storyId);
    } catch (err: any) {
      Alert.alert("Playback Error", "Could not play this story.");
    }
  }

  async function handleDelete(story: Story) {
    const confirmed = window.confirm(`Are you sure you want to delete "${story.title}"?`);
    if (!confirmed) return;

    try {
      if (playingId === story.storyId && audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
        audioRef.current = null;
        setPlayingId(null);
      }
      await apiDelete(`/stories/${story.storyId}`);
      setStories((prev) => prev.filter((s) => s.storyId !== story.storyId));
    } catch (err: any) {
      Alert.alert("Error", "Could not delete story.");
    }
  }

  function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function renderStory({ item }: { item: Story }) {
    const isPlaying = playingId === item.storyId;
    return (
      <View style={[styles.storyCard, isPlaying && styles.storyCardPlaying]}>
        <TouchableOpacity style={styles.storyInfo} onPress={() => handlePlay(item)}>
          <Text style={styles.storyTitle}>{item.title}</Text>
          <Text style={styles.storyMeta}>
            Read by {item.readerName || "Unknown"} · {formatDuration(item.durationSeconds)} · {new Date(item.createdAt).toLocaleDateString()}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => handlePlay(item)} style={styles.playButtonWrap}>
          <Text style={styles.playButton}>{isPlaying ? "||" : ">"}</Text>
        </TouchableOpacity>
        {(item.readerId === userId || userRole === "admin") && (
          <TouchableOpacity onPress={() => handleDelete(item)} style={styles.deleteButtonWrap}>
            <Text style={styles.deleteButton}>✕</Text>
          </TouchableOpacity>
        )}
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#5B9FB8" />
        </View>
      ) : stories.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No stories yet</Text>
          <Text style={styles.emptyDesc}>
            Record your first bedtime story to see it here.
          </Text>
        </View>
      ) : (
        <FlatList
          data={stories}
          keyExtractor={(item) => item.storyId}
          renderItem={renderStory}
          contentContainerStyle={styles.list}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#FBF8F3",
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: "600",
    color: "#3D4148",
    marginBottom: 8,
  },
  emptyDesc: {
    fontSize: 14,
    color: "#7A7E85",
    textAlign: "center",
  },
  list: {
    padding: 24,
  },
  storyCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E8E3DC",
    flexDirection: "row",
    alignItems: "center",
  },
  storyCardPlaying: {
    borderColor: "#5B9FB8",
    backgroundColor: "#EBF3F7",
  },
  storyInfo: {
    flex: 1,
  },
  storyTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: "#3D4148",
    marginBottom: 4,
  },
  storyMeta: {
    fontSize: 13,
    color: "#7A7E85",
  },
  playButtonWrap: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  playButton: {
    fontSize: 24,
    color: "#5B9FB8",
    fontWeight: "bold",
    textAlign: "center",
  },
  deleteButtonWrap: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    marginLeft: 4,
  },
  deleteButton: {
    fontSize: 18,
    color: "#9A9EA5",
    fontWeight: "bold",
  },
});
