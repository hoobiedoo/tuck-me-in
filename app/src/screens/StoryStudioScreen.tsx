import React, { useEffect, useState } from "react";
import { ActivityIndicator, Image, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";
import { apiGet, apiPost } from "../services/api";

type Concept = Record<string, any> & { workingTitle: string; toddlerHook: string; familyConnection: string };
type IllustrationAsset = Record<string, any> & { assetKind: string; layerType: string };

// The Stage 2 output has no single "imageGenerationPrompt" field -- each of
// the five asset kinds carries its description under a different key (see
// illustration_spec_schema.py). Summarize per kind instead of assuming one.
function illustrationAssetSummary(asset: IllustrationAsset): string {
  switch (asset.assetKind) {
    case "NEW_IDENTITY":
      return asset.masterPrompt || "";
    case "VARIANT_OF_IDENTITY": {
      const m = asset.mutation || {};
      return [m.pose, m.gaze, m.view, m.expression?.mouth].filter(Boolean).join(" · ");
    }
    case "BACKGROUND": {
      const s = asset.scene || {};
      return [s.groundShape, s.skyType, s.otherElements].filter(Boolean).join(" · ");
    }
    case "PROCEDURAL_EFFECT":
      return `${asset.color || "?"} glow · radius ${asset.radius ?? "?"} · opacity ${asset.opacity ?? "?"}`;
    case "STATIC_PROP":
      return asset.physicalPrompt || "";
    default:
      return "";
  }
}
type GeneratedImage = { jobId: string; layerType: string; slotTag?: string; expressionKey?: string; cdnUrl?: string; error?: string };

const STYLE_LABELS: Record<string, string> = {
  watermark: "Watermark",
  crayon: "Crayon",
  cartoon: "Cartoon",
  cutout: "Cutout",
  watercolor: "Watercolor",
  sketched: "Sketched",
};

// A hard Lambda timeout isn't a catchable exception, so a job that times out
// server-side never gets marked "failed" -- it stays "queued" forever. Cap
// polling so that shows up as a clear error instead of spinning silently
// (matches the worker's own 900s ceiling, plus room for queueing/cold start).
const JOB_POLL_TIMEOUT_MS = 960_000;

// compose*/compose_illustration_spec actions never call Bedrock -- they
// just assemble the exact prompt text the real action would send. Downloading
// it lets a prompt change be validated by pasting into a plain chat UI
// instead of spending real tokens through this pipeline during development.
async function downloadPrompt(action: string, payload: Record<string, any>, filename: string): Promise<string> {
  const queued = await apiPost<any>("/story-production", { action, ...payload });
  const result = await waitForJob(queued.jobId);
  if (result.status === "refused") throw new Error(result.reason || "Could not compose prompt.");
  const text = result.assembledPrompt as string;
  if (Platform.OS !== "web" || typeof document === "undefined") {
    throw new Error("Prompt download is only available on web.");
  }
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  return text;
}

async function waitForJob(jobId: string): Promise<any> {
  const deadline = Date.now() + JOB_POLL_TIMEOUT_MS;
  for (;;) {
    const job = await apiGet<any>(`/story-production/${jobId}`);
    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error(job.errorMessage || "Generation failed");
    if (Date.now() > deadline) {
      throw new Error("Still generating after 16 minutes -- it may finish in the background; check back later.");
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

export default function StoryStudioScreen() {
  const [pack, setPack] = useState<any>();
  const [framework, setFramework] = useState<any>();
  const [cast, setCast] = useState<any>();
  const [intent, setIntent] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [selected, setSelected] = useState<Concept>();
  const [story, setStory] = useState<any>();
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [error, setError] = useState("");

  const [storyTemplateId, setStoryTemplateId] = useState("");
  const [styleId, setStyleId] = useState("");
  const [illustrationSpec, setIllustrationSpec] = useState<IllustrationAsset[]>();
  const [generatedImages, setGeneratedImages] = useState<GeneratedImage[]>();

  useEffect(() => {
    Promise.all([
      apiGet<any[]>("/theme-packs"),
      apiGet<any[]>("/developmental-frameworks"),
      apiGet<any[]>("/preset-cast-members"),
    ]).then(([packs, frameworks, castMembers]) => {
      setPack(packs[0]); setFramework(frameworks[0]); setCast(castMembers[0]);
      setStyleId((packs[0]?.styles || [])[0] || "");
    }).catch((e) => setError(e.message));
  }, []);

  async function generateConcepts() {
    setBusy(true); setBusyLabel("Working…"); setError(""); setStory(undefined);
    try {
      const queued = await apiPost<any>("/story-production", {
        action: "generate_concepts", themePackId: pack.themePackId,
        frameworkId: framework.frameworkId, languageCode: "en",
        castMemberId: cast.castMemberId, familyIntent: intent,
        creativeBriefAnswers: answers, conceptCount: 3,
      });
      const result = await waitForJob(queued.jobId);
      setConcepts(result.concepts); setSelected(undefined);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function downloadConceptsPrompt() {
    setBusy(true); setBusyLabel("Composing prompt…"); setError("");
    try {
      await downloadPrompt("compose_concepts", {
        themePackId: pack.themePackId, frameworkId: framework.frameworkId,
        languageCode: "en", castMemberId: cast.castMemberId, familyIntent: intent,
        creativeBriefAnswers: answers, conceptCount: 3,
      }, "stage0-concepts-prompt.txt");
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function generateStory() {
    if (!selected) return;
    setBusy(true); setBusyLabel("Writing…"); setError("");
    setStoryTemplateId(""); setIllustrationSpec(undefined); setGeneratedImages(undefined);
    try {
      const queued = await apiPost<any>("/story-production", {
        action: "generate_story", themePackId: pack.themePackId,
        frameworkId: framework.frameworkId, languageCode: "en",
        castMemberId: cast.castMemberId, selectedConcept: selected, minPageCount: 10,
      });
      const result = await waitForJob(queued.jobId);
      setStory(result.stage1Output);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function downloadStoryPrompt() {
    if (!selected) return;
    setBusy(true); setBusyLabel("Composing prompt…"); setError("");
    try {
      await downloadPrompt("compose", {
        themePackId: pack.themePackId, frameworkId: framework.frameworkId,
        languageCode: "en", castMemberId: cast.castMemberId,
        selectedConcept: selected, minPageCount: 10,
      }, "stage1-story-prompt.txt");
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function saveDraft() {
    setBusy(true); setBusyLabel("Saving…"); setError("");
    try {
      const queued = await apiPost<any>("/story-production", {
        action: "write_draft", themePackId: pack.themePackId,
        frameworkId: framework.frameworkId, languageCode: "en",
        castMemberId: cast.castMemberId, stage1Output: story, minPageCount: 10,
      });
      const result = await waitForJob(queued.jobId);
      setStoryTemplateId(result.storyTemplateId);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function generateIllustrationSpec() {
    setBusy(true); setBusyLabel("Designing illustrations…"); setError("");
    setIllustrationSpec(undefined); setGeneratedImages(undefined);
    try {
      const queued = await apiPost<any>("/story-production", {
        action: "generate_illustration_spec", themePackId: pack.themePackId,
        storyTemplateId, styleId, castMemberId: cast.castMemberId,
        castAlreadyHasBase: false, story,
      });
      const result = await waitForJob(queued.jobId);
      if (result.status === "refused") throw new Error(result.reason || "Illustration spec was refused.");
      setIllustrationSpec(result.assets);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function downloadIllustrationSpecPrompt() {
    setBusy(true); setBusyLabel("Composing prompt…"); setError("");
    try {
      await downloadPrompt("compose_illustration_spec", {
        themePackId: pack.themePackId, storyTemplateId, styleId,
        castMemberId: cast.castMemberId, castAlreadyHasBase: false, story,
      }, "stage2-illustration-prompt.txt");
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function generateIllustrations() {
    if (!illustrationSpec) return;
    setBusy(true); setBusyLabel("Rendering images…"); setError(""); setGeneratedImages(undefined);
    try {
      const queued = await apiPost<any>("/story-production", {
        action: "generate_illustrations", themePackId: pack.themePackId,
        storyTemplateId, styleId, castMemberId: cast.castMemberId,
        assets: illustrationSpec,
      });
      const enqueued = await waitForJob(queued.jobId);
      const images = await Promise.all(enqueued.jobs.map(async (job: any) => {
        try {
          const result = await waitForJob(job.jobId);
          return { ...job, cdnUrl: result.cdnUrl } as GeneratedImage;
        } catch (e: any) {
          return { ...job, error: e.message } as GeneratedImage;
        }
      }));
      setGeneratedImages(images);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  if (!pack || !framework || !cast) return <ActivityIndicator style={{ marginTop: 60 }} />;
  return <ScrollView contentContainerStyle={styles.page}>
    <Text style={styles.title}>Story Studio</Text>
    <Text style={styles.meta}>{pack.name} · {framework.displayName} · {cast.name}</Text>
    <Text style={styles.label}>What connection should this story create?</Text>
    <TextInput style={styles.input} multiline value={intent} onChangeText={setIntent} />
    {(framework.creativeBriefQuestions || []).map((q: any) => <View key={q.questionId}>
      <Text style={styles.label}>{q.prompt.replace("[cast]", cast.name)}</Text>
      <TextInput style={styles.input} value={answers[q.questionId] || ""}
        onChangeText={(value) => setAnswers({ ...answers, [q.questionId]: value })} />
    </View>)}
    <TouchableOpacity style={styles.button} disabled={busy || !intent.trim()} onPress={generateConcepts}>
      <Text style={styles.buttonText}>{busy ? busyLabel : "Generate 3 concepts"}</Text>
    </TouchableOpacity>
    <TouchableOpacity disabled={busy || !intent.trim()} onPress={downloadConceptsPrompt}>
      <Text style={styles.linkText}>Download prompt (no tokens spent)</Text>
    </TouchableOpacity>
    {!!error && <Text style={styles.error}>{error}</Text>}
    {concepts.map((concept) => <TouchableOpacity key={concept.workingTitle}
      style={[styles.card, selected === concept && styles.selected]} onPress={() => setSelected(concept)}>
      <Text style={styles.cardTitle}>{concept.workingTitle}</Text>
      <Text>{concept.toddlerHook}</Text><Text style={styles.connection}>{concept.familyConnection}</Text>
    </TouchableOpacity>)}
    {!!selected && <TouchableOpacity style={styles.button} disabled={busy} onPress={generateStory}>
      <Text style={styles.buttonText}>{busy ? busyLabel : "Generate full story"}</Text>
    </TouchableOpacity>}
    {!!selected && <TouchableOpacity disabled={busy} onPress={downloadStoryPrompt}>
      <Text style={styles.linkText}>Download prompt (no tokens spent)</Text>
    </TouchableOpacity>}

    {!!story && <View style={{ gap: 14 }}>
      <Text style={styles.title}>{story.storyTemplate.title}</Text>
      {story.pages.map((page: any) => <View style={styles.card} key={page.pageOrder}>
        <Text style={styles.label}>Page {Number(page.pageOrder)}</Text><Text>{page.textTemplate}</Text>
      </View>)}

      {storyTemplateId
        ? <Text style={styles.connection}>Saved to catalogue as draft ({storyTemplateId})</Text>
        : <TouchableOpacity style={styles.button} disabled={busy} onPress={saveDraft}>
            <Text style={styles.buttonText}>{busy ? busyLabel : "Save to catalogue"}</Text>
          </TouchableOpacity>}

      <Text style={styles.label}>Illustration style</Text>
      <View style={styles.row}>
        {(pack.styles || Object.keys(STYLE_LABELS)).map((s: string) => (
          <TouchableOpacity key={s} style={[styles.pill, styleId === s && styles.selected]} onPress={() => setStyleId(s)}>
            <Text>{STYLE_LABELS[s] || s}</Text>
          </TouchableOpacity>
        ))}
      </View>
      <TouchableOpacity style={styles.button} disabled={busy || !styleId || !storyTemplateId} onPress={generateIllustrationSpec}>
        <Text style={styles.buttonText}>{busy ? busyLabel : "Design illustrations"}</Text>
      </TouchableOpacity>
      <TouchableOpacity disabled={busy || !styleId || !storyTemplateId} onPress={downloadIllustrationSpecPrompt}>
        <Text style={styles.linkText}>Download prompt (no tokens spent)</Text>
      </TouchableOpacity>
    </View>}

    {!!illustrationSpec && <View style={{ gap: 14 }}>
      <Text style={styles.title}>Illustration spec ({illustrationSpec.length} assets)</Text>
      {illustrationSpec.map((asset, index) => <View style={styles.card} key={index}>
        <Text style={styles.cardTitle}>{asset.assetKind}{asset.identityKey ? ` · ${asset.identityKey}` : ""}{asset.variantKey ? ` · ${asset.variantKey}` : ""}</Text>
        <Text numberOfLines={3}>{illustrationAssetSummary(asset)}</Text>
      </View>)}
      <TouchableOpacity style={styles.button} disabled={busy} onPress={generateIllustrations}>
        <Text style={styles.buttonText}>{busy ? busyLabel : "Generate illustrations"}</Text>
      </TouchableOpacity>
    </View>}

    {!!generatedImages && <View style={{ gap: 14 }}>
      <Text style={styles.title}>Generated images ({generatedImages.length})</Text>
      <View style={styles.row}>
        {generatedImages.map((image) => <View style={styles.imageCard} key={image.jobId}>
          {image.cdnUrl
            ? <Image source={{ uri: image.cdnUrl }} style={styles.thumb} />
            : <Text style={styles.error}>{image.error || "Failed"}</Text>}
          <Text numberOfLines={1}>{image.layerType}{image.slotTag ? ` · ${image.slotTag}` : ""}</Text>
        </View>)}
      </View>
    </View>}
  </ScrollView>;
}

const styles = StyleSheet.create({
  page: { padding: 24, maxWidth: 900, width: "100%", alignSelf: "center", gap: 14 },
  title: { fontSize: 28, fontWeight: "700", color: "#263238" }, meta: { color: "#607D8B" },
  label: { fontWeight: "600", marginTop: 8 }, input: { borderWidth: 1, borderColor: "#B0BEC5", borderRadius: 10, padding: 12, minHeight: 48 },
  button: { backgroundColor: "#5B9FB8", padding: 14, borderRadius: 10, alignItems: "center" }, buttonText: { color: "white", fontWeight: "700" },
  card: { padding: 16, borderWidth: 1, borderColor: "#CFD8DC", borderRadius: 12, gap: 8 }, selected: { borderColor: "#5B9FB8", borderWidth: 3 },
  cardTitle: { fontSize: 19, fontWeight: "700" }, connection: { color: "#546E7A", fontStyle: "italic" }, error: { color: "#B00020" },
  linkText: { color: "#5B9FB8", textDecorationLine: "underline", textAlign: "center", marginTop: -6 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  pill: { borderWidth: 1, borderColor: "#CFD8DC", borderRadius: 20, paddingVertical: 8, paddingHorizontal: 14 },
  imageCard: { width: 140, gap: 6 }, thumb: { width: 140, height: 140, borderRadius: 10, backgroundColor: "#ECEFF1" },
});
