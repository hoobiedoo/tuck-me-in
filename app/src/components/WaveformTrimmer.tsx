import React, { useEffect, useState, useRef, useCallback } from "react";
import {
  View,
  StyleSheet,
  PanResponder,
  LayoutChangeEvent,
  ActivityIndicator,
  Text,
  GestureResponderEvent,
} from "react-native";

interface Props {
  audioUri: string;
  durationMs: number;
  playbackPositionMs: number;
  trimStartMs: number;
  trimEndMs: number;
  onTrimChange: (startMs: number, endMs: number) => void;
  onSeek: (positionMs: number) => void;
}

const NUM_BARS = 80;
const BAR_GAP = 2;
const HANDLE_WIDTH = 12;
const HANDLE_HIT_SLOP = 24;
const WAVEFORM_HEIGHT = 80;

export default function WaveformTrimmer({
  audioUri,
  durationMs,
  playbackPositionMs,
  trimStartMs,
  trimEndMs,
  onTrimChange,
  onSeek,
}: Props) {
  const [waveform, setWaveform] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [containerWidth, setContainerWidth] = useState(0);
  const containerRef = useRef<View>(null);
  const containerLeftRef = useRef(0);
  const draggingRef = useRef<"start" | "end" | "seek" | null>(null);
  const trimRef = useRef({ start: trimStartMs, end: trimEndMs });

  trimRef.current = { start: trimStartMs, end: trimEndMs };

  useEffect(() => {
    extractWaveform(audioUri);
  }, [audioUri]);

  async function extractWaveform(uri: string) {
    setLoading(true);
    try {
      // Fetch the audio blob
      const response = await fetch(uri);
      const arrayBuffer = await response.arrayBuffer();

      // Decode with Web Audio API
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const audioContext = new AudioCtx();

      const audioBuffer = await new Promise<AudioBuffer>((resolve, reject) => {
        audioContext.decodeAudioData(arrayBuffer, resolve, reject);
      });

      const channelData = audioBuffer.getChannelData(0);
      const blockSize = Math.floor(channelData.length / NUM_BARS);
      const samples: number[] = [];

      for (let i = 0; i < NUM_BARS; i++) {
        let sum = 0;
        const offset = i * blockSize;
        for (let j = 0; j < blockSize && offset + j < channelData.length; j++) {
          sum += Math.abs(channelData[offset + j]);
        }
        samples.push(sum / blockSize);
      }

      const max = Math.max(...samples, 0.001);
      setWaveform(samples.map((s) => Math.max(0.05, s / max)));
      audioContext.close();
    } catch (err) {
      console.warn("Waveform extraction failed:", err);
      // Generate a simple fallback waveform
      const bars = [];
      for (let i = 0; i < NUM_BARS; i++) {
        bars.push(0.2 + Math.random() * 0.3);
      }
      setWaveform(bars);
    } finally {
      setLoading(false);
    }
  }

  function onLayout(e: LayoutChangeEvent) {
    setContainerWidth(e.nativeEvent.layout.width);
    // Measure absolute position for touch handling
    if (containerRef.current) {
      (containerRef.current as any).measureInWindow?.(
        (x: number) => { containerLeftRef.current = x; }
      );
    }
  }

  const msToX = useCallback(
    (ms: number) => (containerWidth > 0 && durationMs > 0 ? (ms / durationMs) * containerWidth : 0),
    [containerWidth, durationMs]
  );

  const xToMs = useCallback(
    (x: number) => (containerWidth > 0 && durationMs > 0 ? Math.round((x / containerWidth) * durationMs) : 0),
    [containerWidth, durationMs]
  );

  function clamp(val: number, min: number, max: number) {
    return Math.min(Math.max(val, min), max);
  }

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (e: GestureResponderEvent) => {
        const touchX = e.nativeEvent.locationX;
        const startX = msToX(trimRef.current.start);
        const endX = msToX(trimRef.current.end);
        const distToStart = Math.abs(touchX - startX);
        const distToEnd = Math.abs(touchX - endX);

        if (distToStart <= HANDLE_HIT_SLOP && distToStart <= distToEnd) {
          draggingRef.current = "start";
        } else if (distToEnd <= HANDLE_HIT_SLOP) {
          draggingRef.current = "end";
        } else {
          draggingRef.current = "seek";
          onSeek(clamp(xToMs(touchX), 0, durationMs));
        }
      },
      onPanResponderMove: (e: GestureResponderEvent) => {
        const touchX = e.nativeEvent.locationX;
        const ms = clamp(xToMs(touchX), 0, durationMs);

        if (draggingRef.current === "start") {
          const newStart = Math.min(ms, trimRef.current.end - 1000);
          onTrimChange(Math.max(0, newStart), trimRef.current.end);
        } else if (draggingRef.current === "end") {
          const newEnd = Math.max(ms, trimRef.current.start + 1000);
          onTrimChange(trimRef.current.start, Math.min(durationMs, newEnd));
        } else if (draggingRef.current === "seek") {
          onSeek(ms);
        }
      },
      onPanResponderRelease: () => {
        draggingRef.current = null;
      },
    })
  ).current;

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator color="#7c3aed" size="small" />
        <Text style={styles.loadingText}>Analyzing audio...</Text>
      </View>
    );
  }

  if (containerWidth === 0) {
    return <View style={styles.outerContainer} ref={containerRef} onLayout={onLayout} />;
  }

  const trimStartX = msToX(trimStartMs);
  const trimEndX = msToX(trimEndMs);
  const playheadX = msToX(playbackPositionMs);
  const barWidth = Math.max(1, (containerWidth - (NUM_BARS - 1) * BAR_GAP) / NUM_BARS);

  return (
    <View
      style={styles.outerContainer}
      ref={containerRef}
      onLayout={onLayout}
      {...panResponder.panHandlers}
    >
      {/* Waveform bars */}
      <View style={styles.barsRow}>
        {waveform.map((amplitude, i) => {
          const barX = i * (barWidth + BAR_GAP);
          const barCenter = barX + barWidth / 2;
          const inTrim = barCenter >= trimStartX && barCenter <= trimEndX;
          const height = Math.max(4, amplitude * (WAVEFORM_HEIGHT - 10));

          return (
            <View
              key={i}
              style={{
                width: barWidth,
                height,
                backgroundColor: inTrim ? "#7c3aed" : "#4b5563",
                borderRadius: barWidth / 2,
                marginRight: i < NUM_BARS - 1 ? BAR_GAP : 0,
                opacity: inTrim ? 1 : 0.4,
              }}
            />
          );
        })}
      </View>

      {/* Dim left region */}
      {trimStartX > 0 && (
        <View
          style={[styles.dimRegion, { left: 0, width: trimStartX }]}
          pointerEvents="none"
        />
      )}

      {/* Dim right region */}
      {trimEndX < containerWidth && (
        <View
          style={[styles.dimRegion, { left: trimEndX, right: 0 }]}
          pointerEvents="none"
        />
      )}

      {/* Left handle */}
      <View
        style={[styles.handle, { left: trimStartX - HANDLE_WIDTH }]}
        pointerEvents="none"
      >
        <View style={styles.handleBar}>
          <View style={styles.handleGrip} />
        </View>
      </View>

      {/* Right handle */}
      <View
        style={[styles.handle, { left: trimEndX }]}
        pointerEvents="none"
      >
        <View style={styles.handleBar}>
          <View style={styles.handleGrip} />
        </View>
      </View>

      {/* Top/bottom trim border */}
      <View
        style={[styles.trimBorder, styles.trimBorderTop, { left: trimStartX, width: Math.max(0, trimEndX - trimStartX) }]}
        pointerEvents="none"
      />
      <View
        style={[styles.trimBorder, styles.trimBorderBottom, { left: trimStartX, width: Math.max(0, trimEndX - trimStartX) }]}
        pointerEvents="none"
      />

      {/* Playhead */}
      <View
        style={[styles.playhead, { left: clamp(playheadX, 0, containerWidth) }]}
        pointerEvents="none"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  outerContainer: {
    height: WAVEFORM_HEIGHT,
    position: "relative",
  },
  loadingContainer: {
    height: WAVEFORM_HEIGHT,
    justifyContent: "center",
    alignItems: "center",
    flexDirection: "row",
    gap: 8,
  },
  loadingText: {
    fontSize: 13,
    color: "#9ca3af",
  },
  barsRow: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
  },
  dimRegion: {
    position: "absolute",
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(17, 24, 39, 0.5)",
    zIndex: 4,
  },
  handle: {
    position: "absolute",
    top: 0,
    width: HANDLE_WIDTH,
    height: WAVEFORM_HEIGHT,
    zIndex: 10,
  },
  handleBar: {
    width: HANDLE_WIDTH,
    height: WAVEFORM_HEIGHT,
    backgroundColor: "#f59e0b",
    borderRadius: 3,
    justifyContent: "center",
    alignItems: "center",
  },
  handleGrip: {
    width: 3,
    height: 20,
    borderRadius: 1.5,
    backgroundColor: "rgba(255,255,255,0.6)",
  },
  trimBorder: {
    position: "absolute",
    height: 2,
    backgroundColor: "#f59e0b",
    zIndex: 6,
  },
  trimBorderTop: {
    top: 0,
  },
  trimBorderBottom: {
    bottom: 0,
  },
  playhead: {
    position: "absolute",
    top: 0,
    width: 2,
    height: WAVEFORM_HEIGHT,
    backgroundColor: "#ffffff",
    zIndex: 15,
    marginLeft: -1,
  },
});
