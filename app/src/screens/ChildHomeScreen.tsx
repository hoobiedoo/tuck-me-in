import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, FlatList, Image, Pressable, StyleSheet, Text,
  useWindowDimensions, View,
} from "react-native";
import { useFocusEffect, useNavigation, useRoute } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import type { RouteProp } from "@react-navigation/native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet } from "../services/api";
import { AWS_CONFIG } from "../config/aws";
import type { MainStackParamList } from "../navigation/MainStack";

interface Story {
  storyId: string;
  title: string;
  readerId: string;
  readerName?: string;
  readerPhotoUrl?: string;
  audioKey: string;
  invitationAudioKey?: string;
  durationSeconds: number;
  coverImageUrl?: string;
  isNew?: boolean;
}

type Nav = NativeStackNavigationProp<MainStackParamList, "ChildHome">;
type Route = RouteProp<MainStackParamList, "ChildHome">;

const POLL_MS = 45000;
const DIM_AFTER_MS = 20000;

function seenKey(childId: string) {
  return `tuckMeIn.seenStories.${childId}`;
}

function loadSeen(childId: string): Set<string> {
  try {
    if (typeof window === "undefined") return new Set();
    const value = window.localStorage.getItem(seenKey(childId));
    return value ? new Set(JSON.parse(value)) : new Set();
  } catch {
    return new Set();
  }
}

function saveSeen(childId: string, ids: string[]) {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(seenKey(childId), JSON.stringify(ids));
    }
  } catch {
    // Best effort only.
  }
}

function audioUrl(key: string) {
  return `${AWS_CONFIG.audioCdnBase}/${key}`;
}

function familiarName(name?: string) {
  return name?.trim().split(/\s+/)[0] || "Your storyteller";
}

export default function ChildHomeScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const { childId, childName } = route.params;
  const { householdId } = useAuth();
  const { width, height } = useWindowDimensions();

  const [stories, setStories] = useState<Story[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeStory, setActiveStory] = useState<Story | null>(null);
  const [playing, setPlaying] = useState(false);
  const [complete, setComplete] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [invitationId, setInvitationId] = useState<string | null>(null);
  const storyAudio = useRef<HTMLAudioElement | null>(null);
  const invitationAudio = useRef<HTMLAudioElement | null>(null);
  const shelf = useRef<FlatList<Story>>(null);
  const contentVersion = useRef<number | null>(null);
  const dimTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const compact = width < 600;
  const landscape = width > height;
  const cardWidth = compact ? Math.min(230, width * 0.68) : landscape ? 230 : 250;
  const playerCoverWidth = compact ? Math.min(width * 0.6, 280) : Math.min(width * 0.34, 340);

  const loadStories = useCallback(async () => {
    if (!householdId) return;
    try {
      const data = await apiGet<Story[]>(
        `/stories?householdId=${householdId}&view=assigned&childId=${childId}`
      );
      const seen = loadSeen(childId);
      setStories(data.map((story) => ({ ...story, isNew: !seen.has(story.storyId) })));
      saveSeen(childId, data.map((story) => story.storyId));
    } finally {
      setLoading(false);
    }
  }, [childId, householdId]);

  const checkForUpdates = useCallback(async () => {
    if (!householdId) return;
    try {
      const household = await apiGet<{ contentVersion?: number }>(`/households/${householdId}`);
      const version = household.contentVersion ?? 0;
      if (contentVersion.current === null) contentVersion.current = version;
      else if (contentVersion.current !== version) {
        contentVersion.current = version;
        await loadStories();
      }
    } catch {
      // The next foreground poll retries.
    }
  }, [householdId, loadStories]);

  useEffect(() => { setLoading(true); void loadStories(); }, [loadStories]);

  useFocusEffect(useCallback(() => {
    void checkForUpdates();
    const interval = setInterval(checkForUpdates, POLL_MS);
    return () => clearInterval(interval);
  }, [checkForUpdates]));

  const clearDimTimer = useCallback(() => {
    if (dimTimer.current) clearTimeout(dimTimer.current);
    dimTimer.current = null;
  }, []);

  const scheduleDim = useCallback(() => {
    clearDimTimer();
    dimTimer.current = setTimeout(() => setControlsVisible(false), DIM_AFTER_MS);
  }, [clearDimTimer]);

  useEffect(() => {
    if (activeStory && playing && !complete) scheduleDim();
    else clearDimTimer();
    return clearDimTimer;
  }, [activeStory, clearDimTimer, complete, playing, scheduleDim]);

  useEffect(() => () => {
    clearDimTimer();
    storyAudio.current?.pause();
    invitationAudio.current?.pause();
  }, [clearDimTimer]);

  function stopInvitation() {
    invitationAudio.current?.pause();
    if (invitationAudio.current) invitationAudio.current.src = "";
    invitationAudio.current = null;
    setInvitationId(null);
  }

  function startStory(story: Story) {
    stopInvitation();
    storyAudio.current?.pause();
    if (storyAudio.current) storyAudio.current.src = "";
    const audio = new window.Audio(audioUrl(story.audioKey));
    audio.onended = () => {
      setPlaying(false);
      setComplete(true);
      setControlsVisible(true);
    };
    audio.onerror = () => {
      setPlaying(false);
      setControlsVisible(true);
    };
    void audio.play();
    storyAudio.current = audio;
    setActiveStory(story);
    setComplete(false);
    setPlaying(true);
    setControlsVisible(true);
  }

  function togglePlayback() {
    if (!storyAudio.current) return;
    if (playing) {
      storyAudio.current.pause();
      setPlaying(false);
      setControlsVisible(true);
    } else {
      if (complete) storyAudio.current.currentTime = 0;
      void storyAudio.current.play();
      setComplete(false);
      setPlaying(true);
    }
  }

  function toggleInvitation(story: Story) {
    if (!story.invitationAudioKey) return;
    if (invitationId === story.storyId) return stopInvitation();
    stopInvitation();
    const audio = new window.Audio(audioUrl(story.invitationAudioKey));
    audio.onended = stopInvitation;
    audio.onerror = stopInvitation;
    void audio.play();
    invitationAudio.current = audio;
    setInvitationId(story.storyId);
  }

  function renderStory({ item }: { item: Story }) {
    const invitationPlaying = invitationId === item.storyId;
    return (
      <View style={[styles.storyCard, { width: cardWidth }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Play ${item.title}, read by ${item.readerName || "your storyteller"}`}
          onPress={() => startStory(item)}
          style={({ pressed }) => [styles.coverButton, pressed && styles.pressed]}
        >
          {item.coverImageUrl ? (
            <Image source={{ uri: item.coverImageUrl }} style={styles.fill} resizeMode="cover" />
          ) : (
            <View style={styles.coverPlaceholder}>
              <Text style={styles.moon}>☾</Text>
              <Text style={styles.placeholderTitle} numberOfLines={3}>{item.title}</Text>
            </View>
          )}
          {item.isNew && <View style={styles.newBadge}><Text style={styles.newBadgeText}>NEW</Text></View>}
          <View style={styles.coverPlay}><Text style={styles.coverPlayIcon}>▶</Text></View>
        </Pressable>

        <Text style={styles.storyTitle} numberOfLines={2}>{item.title}</Text>
        <Pressable
          accessibilityRole={item.invitationAudioKey ? "button" : "text"}
          accessibilityLabel={item.invitationAudioKey ? `Hear ${familiarName(item.readerName)} introduce this story` : undefined}
          disabled={!item.invitationAudioKey}
          onPress={() => toggleInvitation(item)}
          style={({ pressed }) => [
            styles.storytellerRow,
            item.invitationAudioKey && styles.storytellerInteractive,
            pressed && styles.pressed,
          ]}
        >
          <View style={styles.avatar}>
            {item.readerPhotoUrl
              ? <Image source={{ uri: item.readerPhotoUrl }} style={styles.fill} />
              : <Text style={styles.avatarInitial}>{familiarName(item.readerName).charAt(0)}</Text>}
          </View>
          <View style={styles.storytellerCopy}>
            <Text style={styles.readBy}>READ BY</Text>
            <Text style={styles.readerName} numberOfLines={1}>{item.readerName || "Your storyteller"}</Text>
          </View>
          {item.invitationAudioKey && (
            <View style={[styles.listenButton, invitationPlaying && styles.listenActive]}>
              <Text style={[styles.listenIcon, invitationPlaying && styles.listenIconActive]}>
                {invitationPlaying ? "■" : "♪"}
              </Text>
            </View>
          )}
        </Pressable>
      </View>
    );
  }

  if (activeStory) {
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={controlsVisible ? undefined : "Show player controls"}
        onPress={() => {
          if (!controlsVisible) {
            setControlsVisible(true);
            if (playing) scheduleDim();
          }
        }}
        style={[styles.player, (!controlsVisible || complete) && styles.playerDimmed]}
      >
        {activeStory.coverImageUrl && (
          <Image source={{ uri: activeStory.coverImageUrl }} style={styles.playerBackdrop} blurRadius={18} />
        )}
        <View style={styles.playerShade} />
        <View style={[styles.playerTopBar, !controlsVisible && styles.hidden]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Back to stories"
            onPress={(event) => { event.stopPropagation(); setActiveStory(null); }}
            style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}
          >
            <Text style={styles.backIcon}>‹</Text><Text style={styles.backText}>Stories</Text>
          </Pressable>
        </View>

        <View style={styles.playerContent} pointerEvents="none">
          <View style={[styles.playerCoverFrame, { width: playerCoverWidth }]}>
            {activeStory.coverImageUrl
              ? <Image source={{ uri: activeStory.coverImageUrl }} style={styles.fill} />
              : <View style={styles.playerPlaceholder}><Text style={styles.playerMoon}>☾</Text></View>}
          </View>
          {complete ? (
            <View style={styles.goodnightBlock}>
              <Text style={styles.goodnightMoon}>☾</Text>
              <Text style={styles.goodnightTitle}>Goodnight, {childName}</Text>
              <Text style={styles.goodnightFrom}>A story from {familiarName(activeStory.readerName)}</Text>
            </View>
          ) : controlsVisible ? (
            <View style={styles.nowPlayingCopy}>
              <Text style={styles.nowPlayingTitle} numberOfLines={2}>{activeStory.title}</Text>
              <View style={styles.playerReaderRow}>
                <View style={styles.playerAvatar}>
                  {activeStory.readerPhotoUrl
                    ? <Image source={{ uri: activeStory.readerPhotoUrl }} style={styles.fill} />
                    : <Text style={styles.playerAvatarInitial}>{familiarName(activeStory.readerName).charAt(0)}</Text>}
                </View>
                <Text style={styles.nowPlayingReader}>Read by {activeStory.readerName || "your storyteller"}</Text>
              </View>
            </View>
          ) : null}
        </View>

        {!complete && (
          <View style={[styles.playerControls, !controlsVisible && styles.hidden]}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={playing ? "Pause story" : "Resume story"}
              onPress={(event) => { event.stopPropagation(); togglePlayback(); }}
              style={({ pressed }) => [styles.primaryControl, pressed && styles.primaryPressed]}
            >
              <Text style={styles.primaryIcon}>{playing ? "Ⅱ" : "▶"}</Text>
              <Text style={styles.primaryLabel}>{playing ? "Pause" : "Keep listening"}</Text>
            </Pressable>
          </View>
        )}
      </Pressable>
    );
  }

  return (
    <View style={styles.container}>
      <View style={[styles.glow, styles.glowOne]} /><View style={[styles.glow, styles.glowTwo]} />
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Text style={styles.eyebrow}>STORY TIME</Text>
          <Text style={[styles.heading, compact && styles.headingCompact]}>What should we hear tonight?</Text>
          <Text style={styles.subheading}>{childName}'s stories, read by people who love you.</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Return to child selection"
          onPress={() => navigation.navigate("ChildSelect")}
          style={({ pressed }) => [styles.parentButton, pressed && styles.pressed]}
        >
          <Text style={styles.parentIcon}>⌂</Text>{!compact && <Text style={styles.parentText}>Grown-ups</Text>}
        </Pressable>
      </View>

      {loading ? <View style={styles.center}><ActivityIndicator size="large" color="#5B858B" /></View>
      : stories.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyMoon}>☾</Text>
          <Text style={styles.emptyTitle}>Your story shelf is waiting</Text>
          <Text style={styles.emptyDesc}>A grown-up can add a story for bedtime.</Text>
        </View>
      ) : (
        <View style={styles.shelfArea}>
          <FlatList
            ref={shelf}
            data={stories}
            horizontal
            keyExtractor={(item) => item.storyId}
            renderItem={renderStory}
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.shelfContent}
            snapToInterval={cardWidth + 24}
            decelerationRate="fast"
          />
          <View style={styles.shelfFooter}>
            <Text style={styles.shelfHint}>Swipe to see more stories</Text>
            <View style={styles.arrowGroup}>
              <Pressable accessibilityRole="button" accessibilityLabel="Previous stories" onPress={() => shelf.current?.scrollToOffset({ offset: 0, animated: true })} style={({ pressed }) => [styles.arrowButton, pressed && styles.pressed]}><Text style={styles.arrow}>‹</Text></Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel="Next stories" onPress={() => shelf.current?.scrollToEnd({ animated: true })} style={({ pressed }) => [styles.arrowButton, pressed && styles.pressed]}><Text style={styles.arrow}>›</Text></Pressable>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { width: "100%", height: "100%" },
  container: { flex: 1, backgroundColor: "#F7F1E8", overflow: "hidden" },
  glow: { position: "absolute", borderRadius: 999, opacity: 0.5 },
  glowOne: { width: 420, height: 420, top: -210, right: -100, backgroundColor: "#D8E7E9" },
  glowTwo: { width: 300, height: 300, bottom: -180, left: -100, backgroundColor: "#E9DCCF" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingHorizontal: 32, paddingTop: 34, paddingBottom: 20, zIndex: 1 },
  headerCopy: { flex: 1, paddingRight: 16 },
  eyebrow: { color: "#718D91", fontSize: 12, fontWeight: "800", letterSpacing: 2.2, marginBottom: 8 },
  heading: { color: "#35464A", fontSize: 36, lineHeight: 42, fontWeight: "800", letterSpacing: -0.7 },
  headingCompact: { fontSize: 29, lineHeight: 35 },
  subheading: { color: "#738084", fontSize: 16, marginTop: 8 },
  parentButton: { minWidth: 52, minHeight: 52, borderRadius: 26, paddingHorizontal: 16, backgroundColor: "rgba(255,255,255,0.72)", borderWidth: 1, borderColor: "#DED7CD", flexDirection: "row", alignItems: "center", justifyContent: "center" },
  parentIcon: { color: "#708084", fontSize: 20 },
  parentText: { color: "#708084", fontSize: 13, fontWeight: "700", marginLeft: 7 },
  shelfArea: { flex: 1, justifyContent: "center" },
  shelfContent: { paddingHorizontal: 32, paddingTop: 10, paddingBottom: 14, alignItems: "center" },
  storyCard: { marginRight: 24 },
  coverButton: { width: "100%", aspectRatio: 0.82, borderRadius: 26, backgroundColor: "#FFF", overflow: "hidden", borderWidth: 3, borderColor: "rgba(255,255,255,0.9)" },
  coverPlaceholder: { flex: 1, padding: 24, backgroundColor: "#76969B", justifyContent: "center", alignItems: "center" },
  moon: { color: "#F9E6AD", fontSize: 68, lineHeight: 76 },
  placeholderTitle: { color: "white", fontSize: 22, lineHeight: 27, fontWeight: "800", textAlign: "center", marginTop: 12 },
  newBadge: { position: "absolute", top: 14, left: 14, paddingHorizontal: 11, paddingVertical: 6, borderRadius: 13, backgroundColor: "#D8796E" },
  newBadgeText: { color: "white", fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  coverPlay: { position: "absolute", right: 14, bottom: 14, width: 58, height: 58, borderRadius: 29, backgroundColor: "rgba(248,241,223,0.95)", justifyContent: "center", alignItems: "center" },
  coverPlayIcon: { color: "#45686D", fontSize: 23, marginLeft: 4 },
  storyTitle: { color: "#35464A", fontSize: 20, lineHeight: 25, fontWeight: "800", marginTop: 14, minHeight: 50 },
  storytellerRow: { minHeight: 64, marginTop: 8, flexDirection: "row", alignItems: "center", borderRadius: 20 },
  storytellerInteractive: { paddingRight: 8, backgroundColor: "rgba(255,255,255,0.58)" },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: "#D8E7E9", overflow: "hidden", alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "white" },
  avatarInitial: { color: "#496D72", fontSize: 22, fontWeight: "800" },
  storytellerCopy: { flex: 1, marginLeft: 10 },
  readBy: { color: "#899396", fontSize: 11, fontWeight: "700", letterSpacing: 0.7 },
  readerName: { color: "#4B5B5E", fontSize: 15, fontWeight: "800", marginTop: 1 },
  listenButton: { width: 42, height: 42, borderRadius: 21, backgroundColor: "#E4EFEE", alignItems: "center", justifyContent: "center" },
  listenActive: { backgroundColor: "#5D8085" },
  listenIcon: { color: "#486A70", fontSize: 18, fontWeight: "800" },
  listenIconActive: { color: "white" },
  shelfFooter: { paddingHorizontal: 32, paddingBottom: 24, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  shelfHint: { color: "#899396", fontSize: 13, fontWeight: "600" },
  arrowGroup: { flexDirection: "row" },
  arrowButton: { width: 52, height: 52, marginLeft: 10, borderRadius: 26, backgroundColor: "rgba(255,255,255,0.75)", borderWidth: 1, borderColor: "#DED7CD", alignItems: "center", justifyContent: "center" },
  arrow: { color: "#58767B", fontSize: 34, lineHeight: 37 },
  pressed: { opacity: 0.72, transform: [{ scale: 0.98 }] },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 30 },
  emptyMoon: { color: "#8CA7AA", fontSize: 78 },
  emptyTitle: { color: "#35464A", fontSize: 24, fontWeight: "800", textAlign: "center", marginTop: 16 },
  emptyDesc: { color: "#788588", fontSize: 16, textAlign: "center", marginTop: 8 },
  player: { flex: 1, backgroundColor: "#243538", overflow: "hidden" },
  playerDimmed: { backgroundColor: "#10191B" },
  playerBackdrop: { ...StyleSheet.absoluteFillObject, width: "100%", height: "100%", opacity: 0.2 },
  playerShade: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(19,31,33,0.68)" },
  playerTopBar: { position: "absolute", top: 0, left: 0, right: 0, padding: 24, zIndex: 3 },
  backButton: { alignSelf: "flex-start", minHeight: 54, paddingHorizontal: 18, borderRadius: 27, backgroundColor: "rgba(255,255,255,0.12)", flexDirection: "row", alignItems: "center" },
  backIcon: { color: "#F8F3E9", fontSize: 37, lineHeight: 38, marginRight: 6 },
  backText: { color: "#F8F3E9", fontSize: 16, fontWeight: "800" },
  playerContent: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 24, paddingTop: 62, paddingBottom: 150 },
  playerCoverFrame: { maxWidth: 340, aspectRatio: 0.82, borderRadius: 30, overflow: "hidden", borderWidth: 3, borderColor: "rgba(255,255,255,0.22)", backgroundColor: "#607F83" },
  playerPlaceholder: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#607F83" },
  playerMoon: { color: "#F7E6B4", fontSize: 92 },
  nowPlayingCopy: { alignItems: "center", marginTop: 22 },
  nowPlayingTitle: { color: "#FAF5EA", fontSize: 27, lineHeight: 33, fontWeight: "800", textAlign: "center" },
  playerReaderRow: { flexDirection: "row", alignItems: "center", marginTop: 12 },
  playerAvatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: "#D4E4E4", overflow: "hidden", alignItems: "center", justifyContent: "center", marginRight: 9 },
  playerAvatarInitial: { color: "#42666B", fontSize: 17, fontWeight: "800" },
  nowPlayingReader: { color: "#C7D4D3", fontSize: 15, fontWeight: "600" },
  playerControls: { position: "absolute", bottom: 28, left: 0, right: 0, alignItems: "center", zIndex: 3 },
  primaryControl: { minWidth: 210, minHeight: 74, paddingHorizontal: 30, borderRadius: 37, backgroundColor: "#F4E7C4", flexDirection: "row", alignItems: "center", justifyContent: "center" },
  primaryPressed: { opacity: 0.82, transform: [{ scale: 0.97 }] },
  primaryIcon: { color: "#35585D", fontSize: 25, fontWeight: "900", marginRight: 12 },
  primaryLabel: { color: "#35585D", fontSize: 18, fontWeight: "900" },
  hidden: { opacity: 0, pointerEvents: "none" },
  goodnightBlock: { alignItems: "center", marginTop: 20 },
  goodnightMoon: { color: "#EED99F", fontSize: 52 },
  goodnightTitle: { color: "#F8F1E2", fontSize: 28, fontWeight: "800", marginTop: 4 },
  goodnightFrom: { color: "#AEBFBE", fontSize: 15, marginTop: 8 },
});
