import React, { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";
import { apiGet, apiPost } from "../services/api";

type Concept = Record<string, any> & { workingTitle: string; toddlerHook: string; familyConnection: string };

async function waitForJob(jobId: string): Promise<any> {
  for (;;) {
    const job = await apiGet<any>(`/story-production/${jobId}`);
    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error(job.errorMessage || "Generation failed");
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
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      apiGet<any[]>("/theme-packs"),
      apiGet<any[]>("/developmental-frameworks"),
      apiGet<any[]>("/preset-cast-members"),
    ]).then(([packs, frameworks, castMembers]) => {
      setPack(packs[0]); setFramework(frameworks[0]); setCast(castMembers[0]);
    }).catch((e) => setError(e.message));
  }, []);

  async function generateConcepts() {
    setBusy(true); setError(""); setStory(undefined);
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

  async function generateStory() {
    if (!selected) return;
    setBusy(true); setError("");
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
      <Text style={styles.buttonText}>{busy ? "Working…" : "Generate 3 concepts"}</Text>
    </TouchableOpacity>
    {!!error && <Text style={styles.error}>{error}</Text>}
    {concepts.map((concept) => <TouchableOpacity key={concept.workingTitle}
      style={[styles.card, selected === concept && styles.selected]} onPress={() => setSelected(concept)}>
      <Text style={styles.cardTitle}>{concept.workingTitle}</Text>
      <Text>{concept.toddlerHook}</Text><Text style={styles.connection}>{concept.familyConnection}</Text>
    </TouchableOpacity>)}
    {!!selected && <TouchableOpacity style={styles.button} disabled={busy} onPress={generateStory}>
      <Text style={styles.buttonText}>{busy ? "Writing…" : "Generate full story"}</Text>
    </TouchableOpacity>}
    {!!story && <View><Text style={styles.title}>{story.storyTemplate.title}</Text>
      {story.pages.map((page: any) => <View style={styles.card} key={page.pageOrder}>
        <Text style={styles.label}>Page {Number(page.pageOrder)}</Text><Text>{page.textTemplate}</Text>
      </View>)}</View>}
  </ScrollView>;
}

const styles = StyleSheet.create({
  page: { padding: 24, maxWidth: 900, width: "100%", alignSelf: "center", gap: 14 },
  title: { fontSize: 28, fontWeight: "700", color: "#263238" }, meta: { color: "#607D8B" },
  label: { fontWeight: "600", marginTop: 8 }, input: { borderWidth: 1, borderColor: "#B0BEC5", borderRadius: 10, padding: 12, minHeight: 48 },
  button: { backgroundColor: "#5B9FB8", padding: 14, borderRadius: 10, alignItems: "center" }, buttonText: { color: "white", fontWeight: "700" },
  card: { padding: 16, borderWidth: 1, borderColor: "#CFD8DC", borderRadius: 12, gap: 8 }, selected: { borderColor: "#5B9FB8", borderWidth: 3 },
  cardTitle: { fontSize: 19, fontWeight: "700" }, connection: { color: "#546E7A", fontStyle: "italic" }, error: { color: "#B00020" },
});
