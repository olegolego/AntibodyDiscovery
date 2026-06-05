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
  phase: string; // current pipeline phase: minimize | equilibrate | production
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
  pushFrame: (step: number, time: number, positions: number[], energy: Energy, phase?: string) => void;
  setPlaybackIndex: (i: number) => void;
  setPlaying: (p: boolean) => void;
  setFollow: (f: boolean) => void;
  setSummary: (s: Summary) => void;
  resetPlayback: () => void;
  toggleView: (k: keyof ViewOptions) => void;
  loadRun: (run: SavedRunData) => void;
}

// Shape of a downloaded run JSON (see exporters.ts).
export interface SavedRunData {
  spec: SystemSpec;
  particle_types: ParticleType[];
  type_index: number[];
  box_lengths: [number, number, number];
  energy_history: ({ step: number } & Energy)[];
  frames: { step: number; time: number; positions: number[] }[];
  summary: Summary | null;
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
  phase: "",
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
      phase: "",
      energyHistory: [],
      playbackIndex: 0,
      playing: true,
      follow: true,
      summary: null,
    }),

  pushFrame: (step, time, positions, energy, phase) =>
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
      return { frames, energyHistory, playbackIndex, phase: phase ?? s.phase };
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

  loadRun: (run) =>
    set({
      spec: run.spec,
      particleTypes: run.particle_types,
      typeIndex: run.type_index,
      boxLengths: run.box_lengths,
      frames: run.frames.map((f) => ({
        step: f.step,
        time: f.time,
        positions: Float32Array.from(f.positions),
        energy: { kinetic: 0, potential: 0, total: 0, temperature: 0 },
      })),
      energyHistory: run.energy_history,
      summary: run.summary,
      status: "done",
      error: null,
      phase: "",
      playbackIndex: 0,
      playing: true,
      follow: false,
      totalSteps: run.frames.length ? run.frames[run.frames.length - 1].step : 0,
    }),
}));
