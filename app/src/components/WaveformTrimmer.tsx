import React, { useEffect, useState, useRef } from "react";
import {
  View,
  StyleSheet,
  Text,
  ActivityIndicator,
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

const NUM_BARS = 60;
const WAVEFORM_HEIGHT = 80;
const HANDLE_WIDTH = 14;

export default function WaveformTrimmer({
  audioUri,
  durationMs,
  playbackPositionMs,
  trimStartMs,
  trimEndMs,
  onTrimChange,
  onSeek,
}: Props) {
  const [waveform, setWaveform] = useState<number[] | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef<"left" | "right" | null>(null);

  useEffect(() => {
    extractWaveform(audioUri);
  }, [audioUri]);

  // Mouse/touch drag handling via DOM events
  useEffect(() => {
    function getContainerX(clientX: number): number {
      if (!containerRef.current) return 0;
      const rect = containerRef.current.getBoundingClientRect();
      return Math.max(0, Math.min(clientX - rect.left, rect.width));
    }

    function xToMs(x: number): number {
      if (!containerRef.current || durationMs <= 0) return 0;
      const rect = containerRef.current.getBoundingClientRect();
      return Math.round((x / rect.width) * durationMs);
    }

    function onPointerDown(e: PointerEvent) {
      if (!containerRef.current) return;
      const x = getContainerX(e.clientX);
      const ms = xToMs(x);
      const rect = containerRef.current.getBoundingClientRect();
      const trimStartX = (trimStartMs / durationMs) * rect.width;
      const trimEndX = (trimEndMs / durationMs) * rect.width;

      const distToLeft = Math.abs(x - trimStartX);
      const distToRight = Math.abs(x - trimEndX);

      if (distToLeft < 20 && distToLeft <= distToRight) {
        draggingRef.current = "left";
        e.preventDefault();
      } else if (distToRight < 20) {
        draggingRef.current = "right";
        e.preventDefault();
      } else {
        // Tap to seek
        onSeek(Math.max(0, Math.min(ms, durationMs)));
      }
    }

    function onPointerMove(e: PointerEvent) {
      if (!draggingRef.current || !containerRef.current) return;
      e.preventDefault();
      const x = getContainerX(e.clientX);
      const ms = xToMs(x);

      if (draggingRef.current === "left") {
        const newStart = Math.max(0, Math.min(ms, trimEndMs - 500));
        onTrimChange(newStart, trimEndMs);
      } else {
        const newEnd = Math.min(durationMs, Math.max(ms, trimStartMs + 500));
        onTrimChange(trimStartMs, newEnd);
      }
    }

    function onPointerUp() {
      draggingRef.current = null;
    }

    const el = containerRef.current;
    if (el) {
      el.addEventListener("pointerdown", onPointerDown);
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
    }

    return () => {
      if (el) {
        el.removeEventListener("pointerdown", onPointerDown);
      }
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [durationMs, trimStartMs, trimEndMs, onTrimChange, onSeek]);

  async function extractWaveform(uri: string) {
    try {
      const response = await fetch(uri);
      const arrayBuffer = await response.arrayBuffer();
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const ctx = new AudioCtx();

      const audioBuffer = await new Promise<AudioBuffer>((resolve, reject) => {
        ctx.decodeAudioData(arrayBuffer, resolve, reject);
      });

      const raw = audioBuffer.getChannelData(0);
      const blockSize = Math.floor(raw.length / NUM_BARS);
      const samples: number[] = [];

      for (let i = 0; i < NUM_BARS; i++) {
        let sum = 0;
        for (let j = 0; j < blockSize; j++) {
          sum += Math.abs(raw[i * blockSize + j]);
        }
        samples.push(sum / blockSize);
      }

      const peak = Math.max(...samples, 0.001);
      setWaveform(samples.map((s) => Math.max(0.08, s / peak)));
      ctx.close();
    } catch (err) {
      console.warn("Waveform decode failed, using fallback:", err);
      // Fallback: random-ish bars so trimming still works
      const bars: number[] = [];
      for (let i = 0; i < NUM_BARS; i++) {
        bars.push(0.15 + Math.sin(i * 0.5) * 0.15 + Math.random() * 0.2);
      }
      setWaveform(bars);
    }
  }

  if (!waveform) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color="#7c3aed" size="small" />
        <Text style={styles.loadingText}>Analyzing audio...</Text>
      </View>
    );
  }

  const trimStartPct = durationMs > 0 ? (trimStartMs / durationMs) * 100 : 0;
  const trimEndPct = durationMs > 0 ? (trimEndMs / durationMs) * 100 : 100;
  const playheadPct = durationMs > 0 ? (playbackPositionMs / durationMs) * 100 : 0;

  return (
    <div
      ref={containerRef}
      style={{
        position: "relative",
        height: WAVEFORM_HEIGHT,
        touchAction: "none",
        userSelect: "none",
      }}
    >
      {/* Waveform bars */}
      <div style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        height: WAVEFORM_HEIGHT,
        gap: 2,
      }}>
        {waveform.map((amp, i) => {
          const pct = ((i + 0.5) / NUM_BARS) * 100;
          const inTrim = pct >= trimStartPct && pct <= trimEndPct;
          const h = Math.max(4, amp * (WAVEFORM_HEIGHT - 8));
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: h,
                borderRadius: 2,
                backgroundColor: inTrim ? "#7c3aed" : "#4b5563",
                opacity: inTrim ? 1 : 0.35,
                transition: "opacity 0.1s",
              }}
            />
          );
        })}
      </div>

      {/* Dim left region */}
      <div style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: `${trimStartPct}%`,
        height: WAVEFORM_HEIGHT,
        backgroundColor: "rgba(17,24,39,0.45)",
        pointerEvents: "none",
      }} />

      {/* Dim right region */}
      <div style={{
        position: "absolute",
        top: 0,
        right: 0,
        width: `${100 - trimEndPct}%`,
        height: WAVEFORM_HEIGHT,
        backgroundColor: "rgba(17,24,39,0.45)",
        pointerEvents: "none",
      }} />

      {/* Top border */}
      <div style={{
        position: "absolute",
        top: 0,
        left: `${trimStartPct}%`,
        width: `${trimEndPct - trimStartPct}%`,
        height: 3,
        backgroundColor: "#f59e0b",
        pointerEvents: "none",
      }} />

      {/* Bottom border */}
      <div style={{
        position: "absolute",
        bottom: 0,
        left: `${trimStartPct}%`,
        width: `${trimEndPct - trimStartPct}%`,
        height: 3,
        backgroundColor: "#f59e0b",
        pointerEvents: "none",
      }} />

      {/* Left handle */}
      <div style={{
        position: "absolute",
        top: 0,
        left: `${trimStartPct}%`,
        marginLeft: -HANDLE_WIDTH,
        width: HANDLE_WIDTH,
        height: WAVEFORM_HEIGHT,
        backgroundColor: "#f59e0b",
        borderRadius: "3px 0 0 3px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "ew-resize",
        pointerEvents: "none",
      }}>
        <div style={{
          width: 3,
          height: 20,
          borderRadius: 2,
          backgroundColor: "rgba(255,255,255,0.6)",
        }} />
      </div>

      {/* Right handle */}
      <div style={{
        position: "absolute",
        top: 0,
        left: `${trimEndPct}%`,
        width: HANDLE_WIDTH,
        height: WAVEFORM_HEIGHT,
        backgroundColor: "#f59e0b",
        borderRadius: "0 3px 3px 0",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "ew-resize",
        pointerEvents: "none",
      }}>
        <div style={{
          width: 3,
          height: 20,
          borderRadius: 2,
          backgroundColor: "rgba(255,255,255,0.6)",
        }} />
      </div>

      {/* Playhead */}
      <div style={{
        position: "absolute",
        top: 0,
        left: `${playheadPct}%`,
        width: 2,
        height: WAVEFORM_HEIGHT,
        backgroundColor: "#ffffff",
        marginLeft: -1,
        pointerEvents: "none",
        zIndex: 20,
      }} />
    </div>
  );
}

const styles = StyleSheet.create({
  loading: {
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
});
