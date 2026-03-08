import React, { useEffect, useState, useRef, useCallback } from "react";
import {
  View,
  StyleSheet,
  PanResponder,
  LayoutChangeEvent,
  ActivityIndicator,
  Text,
  GestureResponderEvent,
  PanResponderGestureState,
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

const NUM_BARS = 100;
const BAR_GAP = 1;
const HANDLE_WIDTH = 14;
const HANDLE_HIT_SLOP = 20;

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
  const draggingRef = useRef<"start" | "end" | "seek" | null>(null);
  const trimRef = useRef({ start: trimStartMs, end: trimEndMs });

  // Keep ref in sync
  trimRef.current = { start: trimStartMs, end: trimEndMs };

  useEffect(() => {
    extractWaveform(audioUri);
  }, [audioUri]);

  async function extractWaveform(uri: string) {
    setLoading(true);
    try {
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      const response = await fetch(uri);
      const arrayBuffer = await response.arrayBuffer();
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
      const channelData = audioBuffer.getChannelData(0);

      // Downsample to NUM_BARS
      const samples: number[] = [];
      const blockSize = Math.floor(channelData.length / NUM_BARS);
      for (let i = 0; i < NUM_BARS; i++) {
        let sum = 0;
        const start = i * blockSize;
        for (let j = start; j < start + blockSize && j < channelData.length; j++) {
          sum += Math.abs(channelData[j]);
        }
        samples.push(sum / blockSize);
      }

      // Normalize to 0-1
      const max = Math.max(...samples, 0.01);
      setWaveform(samples.map((s) => s / max));
      audioContext.close();
    } catch (err) {
      // Fallback: generate flat waveform
      setWaveform(Array(NUM_BARS).fill(0.3));
    } finally {
      setLoading(false);
    }
  }

  function onLayout(e: LayoutChangeEvent) {
    setContainerWidth(e.nativeEvent.layout.width);
  }

  const msToX = useCallback(
    (ms: number) => (containerWidth > 0 ? (ms / durationMs) * containerWidth : 0),
    [containerWidth, durationMs]
  );

  const xToMs = useCallback(
    (x: number) => (containerWidth > 0 ? Math.round((x / containerWidth) * durationMs) : 0),
    [containerWidth, durationMs]
  );

  function clamp(val: number, min: number, max: number) {
    return Math.min(Math.max(val, min), max);
  }

  function getHandleFromTouch(pageX: number): "start" | "end" | "seek" {
    const startX = msToX(trimRef.current.start);
    const endX = msToX(trimRef.current.end);
    const distToStart = Math.abs(pageX - startX);
    const distToEnd = Math.abs(pageX - endX);

    if (distToStart <= HANDLE_HIT_SLOP && distToStart <= distToEnd) return "start";
    if (distToEnd <= HANDLE_HIT_SLOP) return "end";
    return "seek";
  }

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (e: GestureResponderEvent) => {
        const touchX = e.nativeEvent.locationX;
        draggingRef.current = getHandleFromTouch(touchX);

        if (draggingRef.current === "seek") {
          const ms = clamp(xToMs(touchX), 0, durationMs);
          onSeek(ms);
        }
      },
      onPanResponderMove: (e: GestureResponderEvent, gesture: PanResponderGestureState) => {
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
        <ActivityIndicator color="#7c3aed" />
        <Text style={styles.loadingText}>Loading waveform...</Text>
      </View>
    );
  }

  const trimStartX = msToX(trimStartMs);
  const trimEndX = msToX(trimEndMs);
  const playheadX = msToX(playbackPositionMs);
  const barWidth = containerWidth > 0 ? (containerWidth - (NUM_BARS - 1) * BAR_GAP) / NUM_BARS : 0;

  return (
    <View style={styles.container} onLayout={onLayout} {...panResponder.panHandlers}>
      {/* Waveform bars */}
      <View style={styles.waveformContainer}>
        {waveform.map((amplitude, i) => {
          const barX = i * (barWidth + BAR_GAP);
          const barCenter = barX + barWidth / 2;
          const inTrimRegion = barCenter >= trimStartX && barCenter <= trimEndX;
          const minHeight = 3;
          const maxHeight = 60;
          const height = minHeight + amplitude * (maxHeight - minHeight);

          return (
            <View
              key={i}
              style={[
                styles.bar,
                {
                  width: barWidth,
                  height,
                  backgroundColor: inTrimRegion ? "#7c3aed" : "#d1d5db",
                  opacity: inTrimRegion ? 1 : 0.5,
                  marginRight: i < NUM_BARS - 1 ? BAR_GAP : 0,
                },
              ]}
            />
          );
        })}
      </View>

      {/* Dimmed overlay - left of trim */}
      {trimStartX > 0 && (
        <View style={[styles.dimOverlay, { left: 0, width: trimStartX }]} />
      )}

      {/* Dimmed overlay - right of trim */}
      {trimEndX < containerWidth && (
        <View style={[styles.dimOverlay, { left: trimEndX, width: containerWidth - trimEndX }]} />
      )}

      {/* Left trim handle */}
      <View style={[styles.handleContainer, { left: trimStartX - HANDLE_WIDTH }]}>
        <View style={styles.handle}>
          <View style={styles.handleGrip} />
        </View>
      </View>

      {/* Right trim handle */}
      <View style={[styles.handleContainer, { left: trimEndX }]}>
        <View style={styles.handle}>
          <View style={styles.handleGrip} />
        </View>
      </View>

      {/* Trim region top/bottom borders */}
      <View
        style={[
          styles.trimBorderTop,
          { left: trimStartX, width: trimEndX - trimStartX },
        ]}
      />
      <View
        style={[
          styles.trimBorderBottom,
          { left: trimStartX, width: trimEndX - trimStartX },
        ]}
      />

      {/* Playhead */}
      <View style={[styles.playhead, { left: playheadX }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    height: 80,
    position: "relative",
    overflow: "visible",
  },
  loadingContainer: {
    height: 80,
    justifyContent: "center",
    alignItems: "center",
    flexDirection: "row",
    gap: 8,
  },
  loadingText: {
    fontSize: 13,
    color: "#9ca3af",
  },
  waveformContainer: {
    flexDirection: "row",
    alignItems: "center",
    height: 60,
    marginTop: 10,
  },
  bar: {
    borderRadius: 2,
  },
  dimOverlay: {
    position: "absolute",
    top: 0,
    height: 80,
    backgroundColor: "rgba(255,255,255,0.6)",
    zIndex: 5,
  },
  handleContainer: {
    position: "absolute",
    top: 0,
    width: HANDLE_WIDTH,
    height: 80,
    zIndex: 10,
    justifyContent: "center",
    alignItems: "center",
  },
  handle: {
    width: HANDLE_WIDTH,
    height: 80,
    backgroundColor: "#f59e0b",
    borderRadius: 4,
    justifyContent: "center",
    alignItems: "center",
  },
  handleGrip: {
    width: 4,
    height: 24,
    borderRadius: 2,
    backgroundColor: "rgba(255,255,255,0.7)",
  },
  trimBorderTop: {
    position: "absolute",
    top: 0,
    height: 3,
    backgroundColor: "#f59e0b",
    zIndex: 6,
  },
  trimBorderBottom: {
    position: "absolute",
    bottom: 0,
    height: 3,
    backgroundColor: "#f59e0b",
    zIndex: 6,
  },
  playhead: {
    position: "absolute",
    top: 0,
    width: 2,
    height: 80,
    backgroundColor: "#fff",
    zIndex: 15,
    marginLeft: -1,
  },
});
