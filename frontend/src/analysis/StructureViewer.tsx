import { useEffect, useRef, useState } from "react";
import { Maximize2, Pause, Play } from "lucide-react";

interface Props {
  pdbText: string;
}

type ColorScheme = "chainname" | "sstruc" | "bfactor" | "residueindex" | "electrostatic";
type RepType = "cartoon" | "surface" | "ball+stick" | "ribbon" | "backbone";

const COLOR_OPTIONS: { value: ColorScheme; label: string }[] = [
  { value: "chainname",     label: "Chain" },
  { value: "sstruc",        label: "2° Struct" },
  { value: "residueindex",  label: "Rainbow" },
  { value: "bfactor",       label: "B-factor" },
  { value: "electrostatic", label: "Charge" },
];

const REP_OPTIONS: { value: RepType; label: string }[] = [
  { value: "cartoon",    label: "Cartoon" },
  { value: "surface",    label: "Surface" },
  { value: "ribbon",     label: "Ribbon" },
  { value: "ball+stick", label: "Atoms" },
  { value: "backbone",   label: "Backbone" },
];

function baseParams(color: ColorScheme, rep: RepType): Record<string, unknown> {
  const p: Record<string, unknown> = {
    colorScheme: color === "electrostatic" ? "electrostatic" : color,
    smoothSheet: true,
  };
  if (color === "bfactor")      { p.colorScale = "RdYlBu"; p.colorReverse = true; }
  if (color === "electrostatic"){ p.colorScale = "RdBu";   p.colorReverse = true; }
  if (rep === "cartoon")    { p.aspectRatio = 5; p.tubeDiameter = 0.4; }
  if (rep === "surface")    { p.opacity = 0.82; p.clipNear = 0; }
  if (rep === "ball+stick") { p.multipleBond = true; p.bondScale = 0.3; p.radiusScale = 0.5; }
  return p;
}

export function StructureViewer({ pdbText }: Props) {
  // containerRef is the NGL host — separate from React-managed children
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef     = useRef<any>(null);
  const compRef      = useRef<any>(null);
  const repObjRef    = useRef<any>(null);
  const loadedRef    = useRef(false); // mirrors loaded state for callbacks

  const [color,  setColor]  = useState<ColorScheme>("chainname");
  const [rep,    setRep]    = useState<RepType>("cartoon");
  const [spin,   setSpin]   = useState(false);
  const [loaded, setLoaded] = useState(false);

  const colorRef = useRef(color);
  const repRef   = useRef(rep);
  useEffect(() => { colorRef.current = color; }, [color]);
  useEffect(() => { repRef.current   = rep;   }, [rep]);
  useEffect(() => { loadedRef.current = loaded; }, [loaded]);

  // ── Mount NGL stage once ──────────────────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    import("ngl").then((NGL) => {
      // Guard against StrictMode double-mount or unmount-during-import
      if (!containerRef.current || stageRef.current) return;

      const stage = new NGL.Stage(container, {
        backgroundColor: "#080d1c",
        quality: "high",
        impostor: true,
        cameraFov: 40,
        lightColor: 0xffffff,
        lightIntensity: 1.2,
        ambientColor: 0x445566,
        ambientIntensity: 0.7,
      });
      stageRef.current = stage;

      // Sync canvas to whatever the container already measures
      stage.handleResize();

      const onWinResize = () => { if (stageRef.current) stageRef.current.handleResize(); };
      window.addEventListener("resize", onWinResize);

      // After any container resize: resize canvas AND re-center the loaded structure
      const ro = new ResizeObserver(() => {
        if (!stageRef.current) return;
        stageRef.current.handleResize();
        if (compRef.current && loadedRef.current) compRef.current.autoView();
      });
      ro.observe(container);

      if (pdbText) _load(stage, pdbText);

      (stage as any).__cleanup = () => {
        ro.disconnect();
        window.removeEventListener("resize", onWinResize);
      };
    });

    return () => {
      if (stageRef.current) {
        (stageRef.current as any).__cleanup?.();
        stageRef.current.dispose();
        stageRef.current = null;
        compRef.current   = null;
        repObjRef.current = null;
        loadedRef.current = false;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Reload when pdbText changes ───────────────────────────────────────────────
  useEffect(() => {
    if (!pdbText || !stageRef.current) return;
    _load(stageRef.current, pdbText);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdbText]);

  // ── Color — in-place update, no remove+add ────────────────────────────────────
  useEffect(() => {
    if (!repObjRef.current || !loaded) return;
    repObjRef.current.setParameters(baseParams(colorRef.current, repRef.current));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [color, loaded]);

  // ── Rep type — requires remove+add ───────────────────────────────────────────
  useEffect(() => {
    const comp = compRef.current;
    if (!comp || !loaded) return;
    comp.removeAllRepresentations();
    repObjRef.current = comp.addRepresentation(rep, baseParams(colorRef.current, rep));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rep, loaded]);

  // ── Spin ─────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || !loaded) return;
    try {
      if (spin) stage.setSpin([0, 1, 0], 0.008);
      else       stage.setSpin(null);
    } catch { /* no-op */ }
  }, [spin, loaded]);

  function _load(stage: any, text: string) {
    setLoaded(false);
    loadedRef.current = false;
    compRef.current   = null;
    repObjRef.current = null;
    stage.removeAllComponents();

    const blob = new Blob([text], { type: "text/plain" });
    stage
      .loadFile(blob as File, { ext: "pdb", defaultRepresentation: false })
      .then((component: any) => {
        if (!component || stage !== stageRef.current) return;
        compRef.current   = component;
        repObjRef.current = component.addRepresentation(
          repRef.current,
          baseParams(colorRef.current, repRef.current),
        );
        // handleResize before autoView so the camera distance is computed
        // against the actual canvas dimensions (not a 0×0 initial canvas)
        stage.handleResize();
        component.autoView();
        setLoaded(true);
        loadedRef.current = true;
      })
      .catch(() => {});
  }

  return (
    <div className="relative w-full h-full" style={{ minHeight: 280 }}>
      {/* NGL host — separate div so NGL's canvas doesn't mix with React's children */}
      <div ref={containerRef} className="absolute inset-0 rounded-xl" />

      {/* Toolbar — z-10 renders above NGL canvas */}
      {loaded && (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10
          flex items-center gap-1 flex-wrap justify-center
          bg-black/70 backdrop-blur-md border border-white/10
          rounded-2xl px-3 py-2 shadow-xl max-w-[calc(100%-16px)]"
        >
          <span className="text-[9px] font-bold uppercase tracking-wider text-slate-600">Color</span>
          {COLOR_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setColor(o.value)}
              className={`px-2 py-0.5 rounded-lg text-[10px] font-medium transition-colors ${
                color === o.value
                  ? "bg-indigo-500/30 text-indigo-300 border border-indigo-500/40"
                  : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"
              }`}
            >
              {o.label}
            </button>
          ))}

          <div className="w-px h-4 bg-white/10 mx-0.5" />

          <span className="text-[9px] font-bold uppercase tracking-wider text-slate-600">View</span>
          {REP_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setRep(o.value)}
              className={`px-2 py-0.5 rounded-lg text-[10px] font-medium transition-colors ${
                rep === o.value
                  ? "bg-violet-500/30 text-violet-300 border border-violet-500/40"
                  : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"
              }`}
            >
              {o.label}
            </button>
          ))}

          <div className="w-px h-4 bg-white/10 mx-0.5" />

          <button
            onClick={() => setSpin((v) => !v)}
            title={spin ? "Stop rotation" : "Auto-rotate"}
            className={`p-1.5 rounded-lg transition-colors ${
              spin
                ? "text-sky-400 bg-sky-500/20 border border-sky-500/30"
                : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"
            }`}
          >
            {spin ? <Pause size={11} /> : <Play size={11} />}
          </button>

          <button
            onClick={() => {
              stageRef.current?.handleResize();
              compRef.current?.autoView(400);
            }}
            title="Reset view"
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/5
              border border-transparent transition-colors"
          >
            <Maximize2 size={11} />
          </button>
        </div>
      )}

      {/* Loading spinner */}
      {!loaded && pdbText && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <div className="flex flex-col items-center gap-2">
            <div className="w-5 h-5 rounded-full border-2 border-indigo-500/30 border-t-indigo-400 animate-spin" />
            <span className="text-[11px] text-slate-600">Loading structure…</span>
          </div>
        </div>
      )}
    </div>
  );
}
