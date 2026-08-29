import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiPut } from "../services/api";
import { colors } from "../theme";
import { notify } from "../utils/alerts";

interface Assignment {
  childId: string;
}

interface StoryInstance {
  storyInstanceId: string;
  themePackId: string;
  contributorStatus: "draft" | "published" | "withdrawn";
  assignments?: Assignment[];
  currentPageOrder: string;
  createdBy: string;
  createdAt: string;
}

interface ThemePack {
  themePackId: string;
  name: string;
}

interface Child {
  childId: string;
  name: string;
}

export default function StoryWizardHomeScreen() {
  const navigation = useNavigation<any>();
  const { householdId, userId, userRole } = useAuth();
  const [instances, setInstances] = useState<StoryInstance[]>([]);
  const [packsById, setPacksById] = useState<Record<string, ThemePack>>({});
  const [children, setChildren] = useState<Child[]>([]);
  const [selections, setSelections] = useState<Record<string, Set<string>>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    try {
      const [instanceData, packData, childData] = await Promise.all([
        apiGet<StoryInstance[]>(`/story-instances?householdId=${householdId}`),
        apiGet<ThemePack[]>("/theme-packs"),
        apiGet<Child[]>(`/households/${householdId}/children`),
      ]);
      setInstances(instanceData.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
      setPacksById(Object.fromEntries(packData.map((p) => [p.themePackId, p])));
      setChildren(childData);
    } catch (err: any) {
      notify("Error", "Could not load your stories.");
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  function statusLabel(instance: StoryInstance): string {
    if (instance.contributorStatus === "withdrawn") return "Withdrawn";
    if ((instance.assignments || []).length > 0) return "Released";
    if (instance.contributorStatus === "published") return "Ready to release";
    return "In progress";
  }

  function toggleChild(storyInstanceId: string, childId: string) {
    setSelections((prev) => {
      const current = new Set(prev[storyInstanceId] || []);
      if (current.has(childId)) current.delete(childId);
      else current.add(childId);
      return { ...prev, [storyInstanceId]: current };
    });
  }

  async function handleRelease(instance: StoryInstance) {
    const childIds = Array.from(selections[instance.storyInstanceId] || []);
    if (childIds.length === 0) {
      notify("Pick a child", "Select at least one child to release this story to.");
      return;
    }
    setBusyId(instance.storyInstanceId);
    try {
      await apiPut(`/story-instances/${instance.storyInstanceId}/release`, { childIds });
      await load();
    } catch (err: any) {
      notify("Couldn't release this story", err.message || "Please try again.");
    } finally {
      setBusyId(null);
    }
  }

  function handleOpen(instance: StoryInstance) {
    if (instance.contributorStatus !== "draft") return;
    navigation.getParent()?.navigate("StoryWizardPage", {
      storyInstanceId: instance.storyInstanceId,
      pageOrder: instance.currentPageOrder,
    });
  }

  function renderInstance({ item }: { item: StoryInstance }) {
    const pack = packsById[item.themePackId];
    const released = (item.assignments || []).length > 0;
    const busy = busyId === item.storyInstanceId;

    return (
      <TouchableOpacity
        style={styles.card}
        activeOpacity={item.contributorStatus === "draft" ? 0.7 : 1}
        onPress={() => handleOpen(item)}
      >
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>{pack?.name || "Story"}</Text>
          <View style={[styles.pill, released ? styles.pillReleased : styles.pillInProgress]}>
            <Text style={styles.pillText}>{statusLabel(item)}</Text>
          </View>
        </View>
        {item.contributorStatus === "draft" && (
          <Text style={styles.cardMeta}>Tap to continue where you left off</Text>
        )}

        {userRole === "admin" && item.contributorStatus === "published" && !released && (
          <View style={styles.releaseBox}>
            <Text style={styles.sectionLabel}>Release to:</Text>
            <View style={styles.childRow}>
              {children.length === 0 ? (
                <Text style={styles.noChildrenText}>No children set up yet.</Text>
              ) : (
                children.map((child) => {
                  const selected = selections[item.storyInstanceId]?.has(child.childId);
                  return (
                    <TouchableOpacity
                      key={child.childId}
                      style={[styles.childChip, selected && styles.childChipSelected]}
                      onPress={() => toggleChild(item.storyInstanceId, child.childId)}
                    >
                      <Text style={[styles.childChipText, selected && styles.childChipTextSelected]}>
                        {selected ? "✓ " : ""}
                        {child.name}
                      </Text>
                    </TouchableOpacity>
                  );
                })
              )}
            </View>
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
          </View>
        )}
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Your Stories</Text>
        <TouchableOpacity
          style={styles.newButton}
          onPress={() => navigation.getParent()?.navigate("StoryWizardInit")}
        >
          <Text style={styles.newButtonText}>+ New Story</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : instances.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No stories yet</Text>
          <Text style={styles.emptyDesc}>
            Build a Mad Libs–style story together — pick a world, a cast, and fill in the blanks.
          </Text>
        </View>
      ) : (
        <FlatList
          data={instances}
          keyExtractor={(item) => item.storyInstanceId}
          renderItem={renderInstance}
          contentContainerStyle={styles.list}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 8,
  },
  headerTitle: { fontSize: 22, fontWeight: "700", color: colors.text },
  newButton: {
    backgroundColor: colors.primary,
    borderRadius: 20,
    paddingVertical: 8,
    paddingHorizontal: 16,
  },
  newButtonText: { color: "#fff", fontSize: 14, fontWeight: "600" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  emptyTitle: { fontSize: 20, fontWeight: "600", color: colors.text, marginBottom: 8 },
  emptyDesc: { fontSize: 14, color: colors.textSecondary, textAlign: "center" },
  list: { padding: 20 },
  card: {
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.cardBorder,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
  },
  cardTitle: { fontSize: 16, fontWeight: "600", color: colors.text },
  cardMeta: { fontSize: 13, color: colors.textSecondary, marginTop: 4 },
  pill: { borderRadius: 12, paddingHorizontal: 10, paddingVertical: 3 },
  pillInProgress: { backgroundColor: colors.primaryLight },
  pillReleased: { backgroundColor: "#E4F4E9" },
  pillText: { fontSize: 11, fontWeight: "600", color: colors.primaryDark },
  releaseBox: { marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.cardBorder },
  sectionLabel: {
    fontSize: 12,
    fontWeight: "600",
    color: colors.textMuted,
    textTransform: "uppercase",
    letterSpacing: 0.3,
    marginBottom: 8,
  },
  noChildrenText: { fontSize: 13, color: colors.textMuted, fontStyle: "italic" },
  childRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  childChip: {
    borderWidth: 1,
    borderColor: colors.inputBorder,
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  childChipSelected: { borderColor: colors.primary, backgroundColor: colors.primaryLight },
  childChipText: { fontSize: 13, color: colors.heading },
  childChipTextSelected: { color: colors.primaryDark, fontWeight: "600" },
  releaseButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  releaseButtonText: { color: "#fff", fontSize: 14, fontWeight: "600" },
});
