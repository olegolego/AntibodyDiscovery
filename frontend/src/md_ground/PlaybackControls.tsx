import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useMDStore } from "./store";

export function PlaybackControls() {
  const frames = useMDStore((s) => s.frames);
  const playbackIndex = useMDStore((s) => s.playbackIndex);
  const playing = useMDStore((s) => s.playing);
  const follow = useMDStore((s) => s.follow);
  const segments = useMDStore((s) => s.segments);
  const setPlaybackIndex = useMDStore((s) => s.setPlaybackIndex);
  const setPlaying = useMDStore((s) => s.setPlaying);
  const setFollow = useMDStore((s) => s.setFollow);

  const n = frames.length;
  const current = n ? frames[Math.min(playbackIndex, n - 1)] : null;

  // Map each continuation seam (a global step) to a 0–1 position on the track so
  // the bar visibly shows where one run ended and the next began.
  const firstStep = n ? frames[0].step : 0;
  const lastStep = n ? frames[n - 1].step : 0;
  const span = lastStep - firstStep;
  const seams =
    span > 0
      ? segments
          .filter((st) => st > firstStep && st < lastStep)
          .map((st) => (st - firstStep) / span)
      : [];
  const iconBtn =
    "p-1.5 rounded-md text-slate-300 hover:text-white hover:bg-white/10 disabled:opacity-30 transition-colors";

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-surface border-t border-border">
      <button className={iconBtn} disabled={!n} onClick={() => setPlaybackIndex(0)} title="Jump to start">
        <SkipBack size={15} />
      </button>
      <button
        className={iconBtn}
        disabled={!n}
        onClick={() => {
          if (playing) {
            // Pause: stop replay AND detach from the live edge so the view freezes.
            setPlaying(false);
            setFollow(false);
          } else {
            // Resume: if parked at the newest frame, re-attach to live.
            setPlaying(true);
            if (playbackIndex >= n - 1) setFollow(true);
          }
        }}
        title={playing ? "Pause" : "Play"}
      >
        {playing ? <Pause size={16} /> : <Play size={16} fill="currentColor" />}
      </button>
      <button
        className={iconBtn}
        disabled={!n}
        onClick={() => { setFollow(true); setPlaybackIndex(n - 1); }}
        title="Jump to live"
      >
        <SkipForward size={15} />
      </button>

      <div className="relative flex-1 flex items-center">
        <input
          type="range"
          min={0}
          max={Math.max(n - 1, 0)}
          value={Math.min(playbackIndex, Math.max(n - 1, 0))}
          onChange={(e) => setPlaybackIndex(Number(e.target.value))}
          className="w-full accent-indigo-500 h-1"
          disabled={!n}
        />
        {/* Continuation seams: where each resumed run joined the timeline. */}
        {seams.map((f, i) => (
          <span
            key={i}
            className="pointer-events-none absolute top-1/2 -translate-y-1/2 h-3 w-px bg-amber-400/80"
            style={{ left: `${f * 100}%` }}
            title="Run continued here"
          />
        ))}
      </div>

      <div className="text-[11px] text-slate-400 tabular-nums w-32 text-right">
        {current ? (
          <>
            step <b className="text-slate-200">{current.step}</b>
            {segments.length > 0 && <span className="ml-1 text-amber-400/90">·{segments.length + 1} runs</span>}
            {follow && <span className="ml-1 text-emerald-400">● live</span>}
          </>
        ) : (
          "—"
        )}
      </div>
    </div>
  );
}
