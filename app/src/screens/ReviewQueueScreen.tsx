import React, { useEffect, useState, useCallback } from "react";
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
import { apiGet, apiPut } from "../services/api";

interface Assignment {
  childId: string;
  assignedAt: string;
  releasedAt: string;
  releasedBy: "parent" | "auto";
}

interface Story {
  storyId: string;
  title: string;
  readerId: string;
  readerName?: string;
  createdAt: string;
  assignments?: Assignment[];
}

interface Child {
  childId: string;
  name: string;
}

export default function ReviewQueueScreen() {
  const { householdId } = useAuth();
  const [stories, setStories] = useState<Story[]>([]);
  const [children, setChildren] = useState<Child[]>([]);
  const [selections, setSelections] = useState<Record<string, Set<string>>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    try {
      const [storyData, childData] = await Promise.all([
        apiGet<Story[]>(`/stories?householdId=${householdId}&view=review`),
        apiGet<Child[]>(`/households/${householdId}/children`),
      ]);
      setStories(storyData.sort((a, b) => a.createdAt.localeCompare(b.createdAt)));
      setChildren(childData);
      setSelections((prev) => {
        const next: Record<string, Set<string>> = {};
        for (const story of storyData) {
          const alreadyReleased = new Set((story.assignments || []).map((a) => a.childId));
          next[story.storyId] = prev[story.storyId] || alreadyReleased;
        }
        return next;
      });
    } catch (err: any) {
      window.alert("Could not load the review queue.");
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function toggleChild(storyId: string, childId: string) {
    setSelections((prev) => {
      const current = new Set(prev[storyId] || []);
      if (current.has(childId)) {
        current.delete(childId);
      } else {
        current.add(childId);
      }
      return { ...prev, [storyId]: current };
    });
  }

  async function handleRelease(story: Story) {
    const childIds = Array.from(selections[story.storyId] || []);
    if (childIds.length === 0) {
      window.alert("Select at least one child to release this recording to.");
      return;
    }
    setBusyId(story.storyId);
    try {
      await apiPut(`/stories/${story.storyId}/release`, { childIds });
      await loadData();
    } catch (err: any) {
      window.alert(err.message || "Could not release this recording.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleUnpublish(story: Story) {
    const confirmed = window.confirm(
      `Unpublish "${story.title}"? It will no longer be visible to any child, and ${story.readerName || "the contributor"} will be notified.`
    );
    if (!confirmed) return;
    setBusyId(story.storyId);
    try {
      await apiPut(`/stories/${story.storyId}/unpublish`, {});
      await loadData();
    } catch (err: any) {
      window.alert(err.message || "Could not unpublish this recording.");
    } finally {
      setBusyId(null);
    }
  }

  function alreadyReleasedTo(story: Story, childId: string): boolean {
    return (story.assignments || []).some((a) => a.childId === childId);
  }

  function renderStory({ item }: { item: Story }) {
    const busy = busyId === item.storyId;
    const releasedCount = (item.assignments || []).length;
    return (
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>{item.title}</Text>
          {releasedCount > 0 && (
            <View style={styles.releasedPill}>
              <Text style={styles.releasedPillText}>
                Released to {releasedCount} {releasedCount === 1 ? "child" : "children"}
              </Text>
            </View>
          )}
        </View>
        <Text style={styles.cardMeta}>
          From {item.readerName || "Unknown"} · {new Date(item.createdAt).toLocaleDateString()}
        </Text>

        <Text style={styles.sectionLabel}>Release to:</Text>
        <View style={styles.childRow}>
          {children.length === 0 ? (
            <Text style={styles.noChildrenText}>No children set up yet.</Text>
          ) : (
            children.map((child) => {
              const selected = selections[item.storyId]?.has(child.childId);
              const alreadyReleased = alreadyReleasedTo(item, child.childId);
              return (
                <TouchableOpacity
                  key={child.childId}
                  style={[styles.childChip, selected && styles.childChipSelected]}
                  onPress={() => toggleChild(item.storyId, child.childId)}
                >
                  <Text style={[styles.childChipText, selected && styles.childChipTextSelected]}>
                    {selected ? "✓ " : ""}{child.name}{alreadyReleased ? " (released)" : ""}
                  </Text>
                </TouchableOpacity>
              );
            })
          )}
        </View>

        <View style={styles.actionRow}>
          <TouchableOpacity
            style={styles.releaseButton}
            onPress={() => handleRelease(item)}
            disabled={busy}
          >
            {busy ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <Text style={styles.releaseButtonText}>Release</Text>
            )}
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.unpublishButton}
            onPress={() => handleUnpublish(item)}
            disabled={busy}
          >
            <Text style={styles.unpublishButtonText}>Unpublish</Text>
          </TouchableOpacity>
        </View>
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
          <Text style={styles.emptyTitle}>Nothing to review</Text>
          <Text style={styles.emptyDesc}>
            Recordings a family member publishes will show up here for you to release.
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
  card: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E8E3DC",
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: "#3D4148",
  },
  releasedPill: {
    backgroundColor: "#E4F4E9",
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  releasedPillText: {
    fontSize: 11,
    fontWeight: "600",
    color: "#157A45",
  },
  cardMeta: {
    fontSize: 13,
    color: "#7A7E85",
    marginTop: 2,
    marginBottom: 12,
  },
  sectionLabel: {
    fontSize: 12,
    fontWeight: "600",
    color: "#9A9EA5",
    textTransform: "uppercase",
    letterSpacing: 0.3,
    marginBottom: 8,
  },
  noChildrenText: {
    fontSize: 13,
    color: "#9A9EA5",
    fontStyle: "italic",
  },
  childRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 14,
  },
  childChip: {
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  childChipSelected: {
    borderColor: "#5B9FB8",
    backgroundColor: "#EBF3F7",
  },
  childChipText: {
    fontSize: 13,
    color: "#4E535B",
  },
  childChipTextSelected: {
    color: "#3E7690",
    fontWeight: "600",
  },
  actionRow: {
    flexDirection: "row",
    gap: 8,
  },
  releaseButton: {
    backgroundColor: "#5B9FB8",
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 18,
  },
  releaseButtonText: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "600",
  },
  unpublishButton: {
    borderWidth: 1,
    borderColor: "#ef4444",
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 18,
  },
  unpublishButtonText: {
    color: "#ef4444",
    fontSize: 14,
    fontWeight: "600",
  },
});
