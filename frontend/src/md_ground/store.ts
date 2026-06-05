import { create } from "zustand";
import type {
  Energy,
  InitMessage,
  MDFrame,
  ParticleType,
  SimStatus,
  Summary,
  SystemSpec,
} from "./types";
import { defaultSpec } from "./types";

// Cap the playback buffer so a long run can't grow memory without bound. Older
// frames fall off the front (ring semantics) — the scrubber spans what's kept.
const MAX_FRAMES = 2000;

interface ViewOptions {
  showBox: boolean;
  showBonds: boolean;
  showVelocities: boolean;
  colorBySpeed: boolean;
}

interface MDState {
  spec: SystemSpec;
  status: SimStatus;
  error: string | null;

  // init metadata (from the backend on run start)
  particleTypes: ParticleType[];
  typeIndex: number[];
  boxLengths: [number, number, number];
  totalSteps: number;

  // playback buffer
  frames: MDFrame[];
  playbackIndex: number;
  playing: boolean;
  follow: boolean; // stick to the newest frame as it streams in
  energyHistory: { step: number; kinetic: number; potential: number; total: number; temperature: number }[];
  summary: Summary | null;

  view: ViewOptions;

  // actions
  setSpec: (spec: SystemSpec) => void;
  patchSpec: (patch: Partial<SystemSpec>) => void;
  setStatus: (status: SimStatus, error?: string | null) => void;
  applyInit: (msg: InitMessage) => void;
  pushFrame: (step: number, time: number, positions: number[], energy: Energy) => void;
  setPlaybackIndex: (i: number) => void;
  setPlaying: (p: boolean) => void;
  setFollow: (f: boolean) => void;
  setSummary: (s: Summary) => void;
  resetPlayback: () => void;
  toggleView: (k: keyof ViewOptions) => void;
}

export const useMDStore = create<MDState>((set) => ({
  spec: defaultSpec(),
  status: "idle",
  error: null,

  particleTypes: [],
  typeIndex: [],
  boxLengths: [12, 12, 12],
  totalSteps: 0,

  frames: [],
  playbackIndex: 0,
  playing: false,
  follow: true,
  energyHistory: [],
  summary: null,

  view: { showBox: true, showBonds: true, showVelocities: false, colorBySpeed: false },

  setSpec: (spec) => set({ spec }),
  patchSpec: (patch) => set((s) => ({ spec: { ...s.spec, ...patch } })),
  setStatus: (status, error = null) => set({ status, error }),

  applyInit: (msg) =>
    set({
      particleTypes: msg.particle_types,
      typeIndex: msg.type_index,
      boxLengths: msg.box.lengths as [number, number, number],
      totalSteps: msg.total_steps,
      frames: [],
      energyHistory: [],
      playbackIndex: 0,
      playing: true,
      follow: true,
      summary: null,
    }),

  pushFrame: (step, time, positions, energy) =>
    set((s) => {
      const frame: MDFrame = {
        step,
        time,
        positions: Float32Array.from(positions),
        energy,
      };
      const frames = s.frames.length >= MAX_FRAMES ? s.frames.slice(1) : s.frames.slice();
      frames.push(frame);
      const energyHistory =
        s.energyHistory.length >= MAX_FRAMES ? s.energyHistory.slice(1) : s.energyHistory.slice();
      energyHistory.push({ step, ...energy });
      // If following, jump the playhead to the freshest frame.
      const playbackIndex = s.follow ? frames.length - 1 : s.playbackIndex;
      return { frames, energyHistory, playbackIndex };
    }),

  setPlaybackIndex: (i) =>
    set((s) => ({
      playbackIndex: Math.max(0, Math.min(i, s.frames.length - 1)),
      follow: i >= s.frames.length - 1,
    })),
  setPlaying: (playing) => set({ playing }),
  setFollow: (follow) => set({ follow }),
  setSummary: (summary) => set({ summary }),

  resetPlayback: () =>
    set({ frames: [], energyHistory: [], playbackIndex: 0, playing: false, summary: null }),

  toggleView: (k) => set((s) => ({ view: { ...s.view, [k]: !s.view[k] } })),
}));
