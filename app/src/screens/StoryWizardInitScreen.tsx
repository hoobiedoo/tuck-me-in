import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  Image,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useNavigation } from "@react-navigation/native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiPost } from "../services/api";
import { notify } from "../utils/alerts";
import { AWS_CONFIG } from "../config/aws";
import { colors } from "../theme";

interface ThemePack {
  themePackId: string;
  name: string;
  description?: string;
  coverImageKey?: string;
  styles: string[];
  developmentalFrameworks: string[];
  tierRequired: "free" | "premium";
}

interface PresetCastMember {
  castMemberId: string;
  name: string;
}

interface StoryTemplate {
  storyTemplateId: string;
  developmentalFramework: string;
  castMemberId?: string;
  isQuickStoryDefault: boolean;
}

interface DevelopmentalFramework {
  frameworkId: string;
  displayName: string;
  parentFacingDescription?: string;
}

const STYLE_LABELS: Record<string, string> = {
  watermark: "Watermark",
  crayon: "Crayon",
  cartoon: "Cartoon",
  cutout: "Cutout",
  watercolor: "Watercolor",
  sketched: "Sketched",
};

type Step = "pack" | "style" | "framework" | "cast" | "mode";

function cdnUrl(key?: string): string | undefined {
  return key ? `${AWS_CONFIG.audioCdnBase}/${key}` : undefined;
}

export default function StoryWizardInitScreen() {
  const navigation = useNavigation<any>();
  const { householdId } = useAuth();

  const [step, setStep] = useState<Step>("pack");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const [packs, setPacks] = useState<ThemePack[]>([]);
  const [pack, setPack] = useState<ThemePack | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [framework, setFramework] = useState<string | null>(null);
  const [frameworksById, setFrameworksById] = useState<Record<string, DevelopmentalFramework>>({});
  const [castMembers, setCastMembers] = useState<PresetCastMember[]>([]);
  const [castMember, setCastMember] = useState<PresetCastMember | null>(null);
  const [templates, setTemplates] = useState<StoryTemplate[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const [packData, frameworkData] = await Promise.all([
          apiGet<ThemePack[]>("/theme-packs"),
          apiGet<DevelopmentalFramework[]>("/developmental-frameworks"),
        ]);
        setPacks(packData);
        setFrameworksById(Object.fromEntries(frameworkData.map((f) => [f.frameworkId, f])));
      } catch {
        notify("Error", "Could not load story worlds.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function choosePack(p: ThemePack) {
    setPack(p);
    setStyle(null);
    setFramework(null);
    setCastMember(null);
    setStep("style");
  }

  async function chooseStyle(s: string) {
    setStyle(s);
    setStep("framework");
  }

  async function chooseFramework(f: string) {
    if (!pack) return;
    setFramework(f);
    setLoading(true);
    try {
      const [castData, templateData] = await Promise.all([
        apiGet<PresetCastMember[]>(`/preset-cast-members?themePackId=${pack.themePackId}&styleId=${style}`),
        apiGet<StoryTemplate[]>(`/story-templates?themePackId=${pack.themePackId}`),
      ]);
      setCastMembers(castData);
      setTemplates(templateData.filter((t) => t.developmentalFramework === f));
      setStep("cast");
    } catch {
      notify("Error", "Could not load the cast for this world.");
    } finally {
      setLoading(false);
    }
  }

  function chooseCast(member: PresetCastMember) {
    setCastMember(member);
    setStep("mode");
  }

  async function start(quickFill: boolean) {
    if (!pack || !style || !framework || !castMember || !householdId) return;

    const castTemplates = templates.filter(
      (template) => !template.castMemberId || template.castMemberId === castMember.castMemberId
    );
    const quickTemplate = castTemplates.find((template) => template.isQuickStoryDefault);
    const template = quickFill ? quickTemplate || castTemplates[0] : castTemplates[0] || quickTemplate;
    if (!template) {
      notify("Not ready yet", "This world doesn't have a story ready for this theme yet — try another combination.");
      return;
    }

    setCreating(true);
    try {
      const instance = await apiPost<{ storyInstanceId: string; currentPageOrder: string }>(
        "/story-instances",
        {
          themePackId: pack.themePackId,
          styleId: style,
          developmentalFramework: framework,
          storyTemplateId: template.storyTemplateId,
          castSelection: { type: "preset", castMemberId: castMember.castMemberId },
          quickFill,
        }
      );
      navigation.replace("StoryWizardPage", {
        storyInstanceId: instance.storyInstanceId,
        pageOrder: instance.currentPageOrder,
      });
    } catch (err: any) {
      notify("Couldn't start this story", err.message || "Please try again.");
    } finally {
      setCreating(false);
    }
  }

  function goBack() {
    if (step === "style") setStep("pack");
    else if (step === "framework") setStep("style");
    else if (step === "cast") setStep("framework");
    else if (step === "mode") setStep("cast");
    else navigation.goBack();
  }

  if (loading && step === "pack") {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <TouchableOpacity style={styles.backButton} onPress={goBack}>
        <Text style={styles.backButtonText}>‹ Back</Text>
      </TouchableOpacity>

      {step === "pack" && (
        <Step title="Pick a world">
          <Grid>
            {packs.map((p) => (
              <Tile key={p.themePackId} label={p.name} imageUrl={cdnUrl(p.coverImageKey)} onPress={() => choosePack(p)} />
            ))}
          </Grid>
        </Step>
      )}

      {step === "style" && pack && (
        <Step title="Pick a look">
          <Grid>
            {pack.styles.map((s) => (
              <Tile key={s} label={STYLE_LABELS[s] || s} onPress={() => chooseStyle(s)} />
            ))}
          </Grid>
        </Step>
      )}

      {step === "framework" && pack && (
        <Step title="What kind of story?">
          <Grid>
            {pack.developmentalFrameworks.map((f) => (
              <Tile
                key={f}
                label={frameworksById[f]?.displayName || f}
                description={frameworksById[f]?.parentFacingDescription}
                onPress={() => chooseFramework(f)}
                wide
              />
            ))}
          </Grid>
        </Step>
      )}

      {step === "cast" && (
        loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color={colors.primary} />
          </View>
        ) : (
          <Step title="Who's the star?">
            <Grid>
              {castMembers.length === 0 ? (
                <Text style={styles.emptyText}>No cast available for this world and look yet.</Text>
              ) : (
                castMembers.map((c) => (
                  <Tile key={c.castMemberId} label={c.name} onPress={() => chooseCast(c)} />
                ))
              )}
            </Grid>
          </Step>
        )
      )}

      {step === "mode" && (
        <Step title="How much do you want to customize?">
          <TouchableOpacity style={styles.modeCard} onPress={() => start(true)} disabled={creating}>
            <Text style={styles.modeCardTitle}>Quick Story</Text>
            <Text style={styles.modeCardDesc}>We'll pick everything for you — ready in seconds.</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.modeCard} onPress={() => start(false)} disabled={creating}>
            <Text style={styles.modeCardTitle}>Customize</Text>
            <Text style={styles.modeCardDesc}>Fill in the blanks together, page by page.</Text>
          </TouchableOpacity>
          {creating && <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: 16 }} />}
        </Step>
      )}
    </View>
  );
}

function Step({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <ScrollView contentContainerStyle={styles.stepContent}>
      <Text style={styles.stepTitle}>{title}</Text>
      {children}
    </ScrollView>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <View style={styles.grid}>{children}</View>;
}

function Tile({
  label,
  description,
  imageUrl,
  onPress,
  wide,
}: {
  label: string;
  description?: string;
  imageUrl?: string;
  onPress: () => void;
  wide?: boolean;
}) {
  return (
    <TouchableOpacity style={[styles.tile, wide && styles.tileWide]} onPress={onPress}>
      {wide ? null : imageUrl ? (
        <Image source={{ uri: imageUrl }} style={styles.tileImage} />
      ) : (
        <View style={[styles.tileImage, styles.tileImagePlaceholder]} />
      )}
      <View style={wide ? styles.tileWideTextBlock : undefined}>
        <Text style={[styles.tileLabel, wide && styles.tileLabelWide]}>{label}</Text>
        {!!description && <Text style={styles.tileDescription}>{description}</Text>}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: colors.background },
  backButton: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 8 },
  backButtonText: { fontSize: 15, color: colors.primary, fontWeight: "600" },
  stepContent: { padding: 20, paddingTop: 8 },
  stepTitle: { fontSize: 22, fontWeight: "700", color: colors.text, marginBottom: 20 },
  emptyText: { fontSize: 14, color: colors.textMuted, fontStyle: "italic" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  tile: {
    width: "31%",
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 10,
    borderWidth: 1,
    borderColor: colors.cardBorder,
    alignItems: "center",
  },
  tileWide: { width: "100%", padding: 16 },
  tileWideTextBlock: { gap: 4 },
  tileImage: { width: "100%", aspectRatio: 1, borderRadius: 8, marginBottom: 8, backgroundColor: colors.primaryLight },
  tileImagePlaceholder: {},
  tileLabel: { fontSize: 13, fontWeight: "600", color: colors.text, textAlign: "center" },
  tileLabelWide: { fontSize: 16, textAlign: "left" },
  tileDescription: { fontSize: 13, color: colors.textSecondary, textAlign: "left" },
  modeCard: {
    backgroundColor: colors.card,
    borderRadius: 14,
    padding: 20,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: colors.cardBorder,
  },
  modeCardTitle: { fontSize: 18, fontWeight: "700", color: colors.text, marginBottom: 6 },
  modeCardDesc: { fontSize: 14, color: colors.textSecondary },
});
