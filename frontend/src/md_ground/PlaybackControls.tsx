import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useMDStore } from "./store";

export function PlaybackControls() {
  const frames = useMDStore((s) => s.frames);
  const playbackIndex = useMDStore((s) => s.playbackIndex);
  const playing = useMDStore((s) => s.playing);
  const follow = useMDStore((s) => s.follow);
  const setPlaybackIndex = useMDStore((s) => s.setPlaybackIndex);
  const setPlaying = useMDStore((s) => s.setPlaying);
  const setFollow = useMDStore((s) => s.setFollow);

  const n = frames.length;
  const current = n ? frames[Math.min(playbackIndex, n - 1)] : null;
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

      <input
        type="range"
        min={0}
        max={Math.max(n - 1, 0)}
        value={Math.min(playbackIndex, Math.max(n - 1, 0))}
        onChange={(e) => setPlaybackIndex(Number(e.target.value))}
        className="flex-1 accent-indigo-500 h-1"
        disabled={!n}
      />

      <div className="text-[11px] text-slate-400 tabular-nums w-32 text-right">
        {current ? (
          <>
            step <b className="text-slate-200">{current.step}</b>
            {follow && <span className="ml-1 text-emerald-400">● live</span>}
          </>
        ) : (
          "—"
        )}
      </div>
    </div>
  );
}
