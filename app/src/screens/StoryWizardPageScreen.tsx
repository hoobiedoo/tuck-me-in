import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  Image,
  TextInput,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useNavigation, useRoute } from "@react-navigation/native";
import type { RouteProp } from "@react-navigation/native";
import { apiGet, apiPut } from "../services/api";
import { AWS_CONFIG } from "../config/aws";
import { colors } from "../theme";
import { notify } from "../utils/alerts";
import type { MainStackParamList } from "../navigation/MainStack";

interface Transform {
  center_x: number;
  center_y: number;
  width: number;
  height: number;
  rotation_degrees?: number;
}

interface Layer {
  assetId: string;
  cdnKey?: string;
  depthGroup?: string;
  zIndex?: number;
  transform?: Transform;
}

interface StoryInstance {
  storyInstanceId: string;
  storyTemplateId: string;
  contributorStatus: "draft" | "published" | "withdrawn";
  assignments?: { childId: string }[];
}

interface TemplateSlot {
  slotId: string;
  slotType: "CONTROLLED_VOCAB" | "CONTROLLED_VOCAB_WITH_OVERRIDE";
  slotTag: string;
  required?: boolean;
}

interface TemplatePage {
  pageOrder: string;
  slots: TemplateSlot[];
}

interface InstancePage {
  storyInstanceId: string;
  pageOrder: string;
  filledSlotValues: Record<string, { type: "asset"; assetId: string } | { type: "text"; value: string }>;
  resolvedText: string;
  compositionSpec: Layer[];
}

interface Asset {
  assetId: string;
  cdnKey?: string;
  displayLabel?: string;
}

type SlotOption = Asset[] | { suggestions: string[]; allowOverride: boolean };

const CANVAS_W = 2048;
const CANVAS_H = 1536;

type Route = RouteProp<MainStackParamList, "StoryWizardPage">;

function cdnUrl(key?: string): string | undefined {
  return key ? `${AWS_CONFIG.audioCdnBase}/${key}` : undefined;
}

function humanize(slotTag: string): string {
  return slotTag.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function StoryWizardPageScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<Route>();
  const { storyInstanceId } = route.params;

  const [currentPageOrder, setCurrentPageOrder] = useState(route.params.pageOrder);
  const [instance, setInstance] = useState<StoryInstance | null>(null);
  const [templatePages, setTemplatePages] = useState<TemplatePage[]>([]);
  const [page, setPage] = useState<InstancePage | null>(null);
  const [slotOptions, setSlotOptions] = useState<Record<string, SlotOption>>({});
  const [loading, setLoading] = useState(true);
  const [savingSlotId, setSavingSlotId] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [draftText, setDraftText] = useState<Record<string, string>>({});

  const loadPage = useCallback(
    async (pageOrder: string, storyInstance?: StoryInstance) => {
      setLoading(true);
      try {
        const [pageData, optionsData] = await Promise.all([
          apiGet<InstancePage>(`/story-instances/${storyInstanceId}/pages/${pageOrder}`),
          apiGet<Record<string, SlotOption>>(
            `/story-instances/${storyInstanceId}/pages/${pageOrder}/slot-options`
          ),
        ]);
        setPage(pageData);
        setSlotOptions(optionsData);
      } catch {
        notify("Error", "Could not load this page.");
      } finally {
        setLoading(false);
      }
    },
    [storyInstanceId]
  );

  useEffect(() => {
    (async () => {
      try {
        const instanceData = await apiGet<StoryInstance>(`/story-instances/${storyInstanceId}`);
        setInstance(instanceData);
        const pages = await apiGet<TemplatePage[]>(
          `/story-templates/${instanceData.storyTemplateId}/pages`
        );
        setTemplatePages(pages.sort((a, b) => a.pageOrder.localeCompare(b.pageOrder)));
      } catch {
        notify("Error", "Could not load this story.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storyInstanceId]);

  useEffect(() => {
    loadPage(currentPageOrder);
  }, [currentPageOrder, loadPage]);

  const locked = !!instance && ((instance.assignments || []).length > 0 || instance.contributorStatus === "withdrawn");

  async function goToPage(pageOrder: string) {
    setCurrentPageOrder(pageOrder);
    apiPut(`/story-instances/${storyInstanceId}/current-page`, { pageOrder }).catch(() => {});
  }

  async function pickAsset(slotId: string, assetId: string) {
    if (locked) return;
    setSavingSlotId(slotId);
    try {
      const updated = await apiPut<InstancePage>(
        `/story-instances/${storyInstanceId}/pages/${currentPageOrder}/slots`,
        { slots: { [slotId]: { type: "asset", assetId } } }
      );
      setPage(updated);
    } catch (err: any) {
      notify("Couldn't save that pick", err.message || "Please try again.");
    } finally {
      setSavingSlotId(null);
    }
  }

  async function pickText(slotId: string, value: string) {
    if (locked || !value.trim()) return;
    setSavingSlotId(slotId);
    try {
      const updated = await apiPut<InstancePage>(
        `/story-instances/${storyInstanceId}/pages/${currentPageOrder}/slots`,
        { slots: { [slotId]: { type: "text", value: value.trim() } } }
      );
      setPage(updated);
    } catch (err: any) {
      notify("Couldn't save that", err.message || "Please try again.");
    } finally {
      setSavingSlotId(null);
    }
  }

  function handleRecord() {
    // Per-page narration capture (local-first capture, background upload,
    // forced alignment) is a separate, in-progress build — same status as
    // the equivalent flow on BookDetailScreen.
    notify("Coming Soon", "Recording this page isn't built yet.");
  }

  async function handlePublish() {
    setPublishing(true);
    try {
      await apiPut(`/story-instances/${storyInstanceId}/publish`, {});
      notify("Published!", "Your story is ready for a grown-up to release it.", () => navigation.goBack());
    } catch (err: any) {
      notify("Not quite ready", err.message || "Please try again.");
    } finally {
      setPublishing(false);
    }
  }

  if (loading && !page) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }
  if (!page) return null;

  const currentTemplatePage = templatePages.find((p) => p.pageOrder === currentPageOrder);
  const slots = currentTemplatePage?.slots || [];

  // Progressive reveal: every filled slot, plus the next unfilled one.
  const revealed: TemplateSlot[] = [];
  for (const slot of slots) {
    revealed.push(slot);
    if (!page.filledSlotValues[slot.slotId]) break;
  }

  const pageIndex = templatePages.findIndex((p) => p.pageOrder === currentPageOrder);

  return (
    <View style={styles.container}>
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={styles.backButtonText}>‹ Back</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.publishButton} onPress={handlePublish} disabled={publishing || locked}>
          {publishing ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Text style={styles.publishButtonText}>Publish</Text>
          )}
        </TouchableOpacity>
      </View>

      {locked && (
        <View style={styles.lockedBanner}>
          <Text style={styles.lockedBannerText}>
            {instance?.contributorStatus === "withdrawn"
              ? "This story was withdrawn."
              : "This story has already been released and can no longer be edited."}
          </Text>
        </View>
      )}

      <View style={styles.dotsRow}>
        {templatePages.map((p) => (
          <TouchableOpacity key={p.pageOrder} onPress={() => goToPage(p.pageOrder)} style={styles.dotTouchable}>
            <View style={[styles.dot, p.pageOrder === currentPageOrder && styles.dotActive]} />
          </TouchableOpacity>
        ))}
      </View>
      <Text style={styles.pageLabel}>
        Page {pageIndex + 1} of {templatePages.length}
      </Text>

      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.canvas}>
          {[...page.compositionSpec]
            .sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0))
            .map((layer) => {
              const t = layer.transform;
              if (!t) return null;
              const left = ((t.center_x - t.width / 2) / CANVAS_W) * 100;
              const top = ((t.center_y - t.height / 2) / CANVAS_H) * 100;
              const width = (t.width / CANVAS_W) * 100;
              const height = (t.height / CANVAS_H) * 100;
              return (
                <Image
                  key={layer.assetId}
                  source={{ uri: cdnUrl(layer.cdnKey) }}
                  style={[
                    styles.layer,
                    {
                      left: `${left}%`,
                      top: `${top}%`,
                      width: `${width}%`,
                      height: `${height}%`,
                      transform: t.rotation_degrees ? [{ rotate: `${t.rotation_degrees}deg` }] : undefined,
                    },
                  ]}
                  resizeMode="contain"
                />
              );
            })}
        </View>

        <View style={styles.textCard}>
          <Text style={styles.storyText}>{page.resolvedText}</Text>
        </View>

        {loading ? (
          <ActivityIndicator size="small" color={colors.primary} style={{ marginTop: 20 }} />
        ) : (
          revealed.map((slot) => {
            const options = slotOptions[slot.slotId];
            const filled = page.filledSlotValues[slot.slotId];
            const busy = savingSlotId === slot.slotId;

            return (
              <View key={slot.slotId} style={styles.slotSection}>
                <Text style={styles.slotLabel}>{humanize(slot.slotTag)}</Text>

                {Array.isArray(options) ? (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                    {options.map((asset) => {
                      const selected = filled?.type === "asset" && filled.assetId === asset.assetId;
                      return (
                        <TouchableOpacity
                          key={asset.assetId}
                          style={[styles.assetTile, selected && styles.assetTileSelected]}
                          onPress={() => pickAsset(slot.slotId, asset.assetId)}
                          disabled={locked || busy}
                        >
                          <Image source={{ uri: cdnUrl(asset.cdnKey) }} style={styles.assetTileImage} resizeMode="contain" />
                          {!!asset.displayLabel && <Text style={styles.assetTileLabel}>{asset.displayLabel}</Text>}
                        </TouchableOpacity>
                      );
                    })}
                  </ScrollView>
                ) : options ? (
                  <View>
                    <View style={styles.chipRow}>
                      {options.suggestions.map((suggestion) => {
                        const selected = filled?.type === "text" && filled.value === suggestion;
                        return (
                          <TouchableOpacity
                            key={suggestion}
                            style={[styles.chip, selected && styles.chipSelected]}
                            onPress={() => pickText(slot.slotId, suggestion)}
                            disabled={locked || busy}
                          >
                            <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{suggestion}</Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                    {options.allowOverride && (
                      <View style={styles.overrideRow}>
                        <TextInput
                          style={styles.overrideInput}
                          placeholder="Or type your own..."
                          placeholderTextColor={colors.textMuted}
                          value={draftText[slot.slotId] ?? (filled?.type === "text" ? filled.value : "")}
                          onChangeText={(text) => setDraftText((prev) => ({ ...prev, [slot.slotId]: text }))}
                          editable={!locked}
                        />
                        <TouchableOpacity
                          style={styles.overrideButton}
                          onPress={() => pickText(slot.slotId, draftText[slot.slotId] || "")}
                          disabled={locked || busy}
                        >
                          {busy ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.overrideButtonText}>Use</Text>}
                        </TouchableOpacity>
                      </View>
                    )}
                  </View>
                ) : null}
              </View>
            );
          })
        )}

        <TouchableOpacity style={styles.recordButton} onPress={handleRecord} disabled={locked}>
          <Text style={styles.recordButtonText}>🎙 Record this page</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: colors.background },
  topBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 4,
  },
  backButtonText: { fontSize: 15, color: colors.primary, fontWeight: "600" },
  publishButton: { backgroundColor: colors.primary, borderRadius: 20, paddingVertical: 8, paddingHorizontal: 18 },
  publishButtonText: { color: "#fff", fontSize: 14, fontWeight: "600" },
  lockedBanner: { marginHorizontal: 20, marginTop: 8, padding: 12, borderRadius: 8, backgroundColor: colors.primaryLight },
  lockedBannerText: { fontSize: 13, color: colors.heading },
  dotsRow: { flexDirection: "row", justifyContent: "center", gap: 6, marginTop: 12 },
  dotTouchable: { padding: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.cardBorder },
  dotActive: { backgroundColor: colors.primary, width: 10, height: 10, borderRadius: 5 },
  pageLabel: { textAlign: "center", fontSize: 12, color: colors.textMuted, marginTop: 4 },
  scrollContent: { padding: 20, paddingBottom: 48 },
  canvas: {
    width: "100%",
    aspectRatio: CANVAS_W / CANVAS_H,
    backgroundColor: colors.card,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.cardBorder,
    overflow: "hidden",
    position: "relative",
  },
  layer: { position: "absolute" },
  textCard: { marginTop: 16, padding: 16, backgroundColor: colors.card, borderRadius: 12, borderWidth: 1, borderColor: colors.cardBorder },
  storyText: { fontSize: 17, lineHeight: 26, color: colors.text, textAlign: "center" },
  slotSection: { marginTop: 24 },
  slotLabel: { fontSize: 14, fontWeight: "700", color: colors.heading, marginBottom: 10 },
  assetTile: {
    width: 88,
    marginRight: 10,
    padding: 8,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: "transparent",
    backgroundColor: colors.card,
    alignItems: "center",
  },
  assetTileSelected: { borderColor: colors.primary, backgroundColor: colors.primaryLight },
  assetTileImage: { width: 64, height: 64, marginBottom: 4 },
  assetTileLabel: { fontSize: 11, color: colors.text, textAlign: "center" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderColor: colors.inputBorder, borderRadius: 20, paddingHorizontal: 14, paddingVertical: 8 },
  chipSelected: { borderColor: colors.primary, backgroundColor: colors.primaryLight },
  chipText: { fontSize: 14, color: colors.heading },
  chipTextSelected: { color: colors.primaryDark, fontWeight: "600" },
  overrideRow: { flexDirection: "row", gap: 8, marginTop: 10 },
  overrideInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.inputBorder,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.text,
    backgroundColor: colors.card,
  },
  overrideButton: { backgroundColor: colors.primary, borderRadius: 10, paddingHorizontal: 16, justifyContent: "center" },
  overrideButtonText: { color: "#fff", fontSize: 14, fontWeight: "600" },
  recordButton: {
    marginTop: 32,
    backgroundColor: colors.darkSurface,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  recordButtonText: { color: "#fff", fontSize: 15, fontWeight: "600" },
});
