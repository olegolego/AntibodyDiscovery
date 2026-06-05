import { useCallback, useEffect, useRef, useState } from "react";
import { Circle, Maximize2, Square } from "lucide-react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { useMDStore } from "./store";

interface ViewData {
  n: number;
  types: { color: string; radius: number }[];
  typeIndex: number[];
  boxLengths: [number, number, number];
  positions: Float32Array | null; // current frame, or the spec's initial positions
}

// Renders the particle system with three.js. The render loop reads the store via
// getState() (no React re-render per frame) and advances playback itself, so the
// 60fps draw loop is fully decoupled from WebSocket frame arrival.
export function Viewer3D() {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const fitFnRef = useRef<(() => void) | null>(null);
  const canvasElRef = useRef<HTMLCanvasElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const stateRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    mesh: THREE.InstancedMesh | null;
    boxHelper: THREE.LineSegments | null;
    bondLines: THREE.LineSegments | null;
    radii: Float32Array;
    specPosRef: unknown;       // identity of spec.positions we last flattened
    specPosArr: Float32Array | null;
    raf: number;
    lastAdvance: number;
    framedSetup: string;
    setup: string;
  } | null>(null);

  const fit = useCallback(() => fitFnRef.current?.(), []);

  // Record the live WebGL canvas to a downloadable WebM video (great for slides).
  const toggleRecord = useCallback(() => {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    const canvas = canvasElRef.current;
    if (!canvas || typeof canvas.captureStream !== "function" || typeof MediaRecorder === "undefined") {
      setRecError("Video recording isn't supported in this browser (try Chrome).");
      return;
    }
    try {
      const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find(
        (m) => MediaRecorder.isTypeSupported(m)
      );
      const stream = canvas.captureStream(60);
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = () => {
        const blob = new Blob(chunks, { type: "video/webm" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "md-ground.webm";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        setRecording(false);
      };
      recorderRef.current = rec;
      rec.start();
      setRecError(null);
      setRecording(true);
    } catch (e) {
      setRecError(`Recording failed: ${(e as Error).message}`);
    }
  }, [recording]);

  useEffect(() => {
    const mount = mountRef.current!;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x080b18);

    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 20000);
    camera.position.set(20, 16, 28);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    // Filmic tone-mapping + sRGB output gives punchy, vivid colour and soft
    // highlight roll-off (the "shiny" look) instead of flat, washed-out shading.
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    // A generated room environment gives the spheres real reflections so the
    // metallic/clearcoat material actually looks glossy.
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    // The canvas must visually fill the container; setSize(...false) below only
    // sizes the drawing buffer, so CSS controls display size. Without this the
    // canvas stays at its default 300×150 in a corner and OrbitControls only
    // responds to drags over that little patch.
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.position = "absolute";
    renderer.domElement.style.inset = "0";
    mount.appendChild(renderer.domElement);
    canvasElRef.current = renderer.domElement;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    // Screen-space panning makes right-drag move the scene right (the world-space
    // default pans along the ground plane, which feels broken from most angles).
    controls.screenSpacePanning = true;
    controls.rotateSpeed = 0.65;
    controls.zoomSpeed = 0.9;
    controls.panSpeed = 0.8;
    // Zoom toward the cursor (not just the orbit centre) so you can dive into any
    // region; the wide distance range gives lots of variability from extreme
    // close-ups to a full pull-back.
    controls.zoomToCursor = true;
    controls.minDistance = 0.2;
    controls.maxDistance = 20000;
    controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };

    // Soft ambient + a white key for form, then two saturated rim lights
    // (indigo + cyan) that wrap the spheres in colourful highlights.
    scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(1, 1.2, 1);
    scene.add(key);
    const rimA = new THREE.PointLight(0x6366f1, 120, 0, 2); // indigo
    rimA.position.set(-18, 10, -14);
    scene.add(rimA);
    const rimB = new THREE.PointLight(0x22d3ee, 90, 0, 2);  // cyan
    rimB.position.set(16, -10, 18);
    scene.add(rimB);
    const rimC = new THREE.PointLight(0xec4899, 70, 0, 2);  // pink fill
    rimC.position.set(0, 18, -18);
    scene.add(rimC);

    const st = {
      renderer, scene, camera, controls,
      mesh: null as THREE.InstancedMesh | null,
      boxHelper: null as THREE.LineSegments | null,
      bondLines: null as THREE.LineSegments | null,
      radii: new Float32Array(0),
      specPosRef: null as unknown,
      specPosArr: null as Float32Array | null,
      raf: 0, lastAdvance: 0, framedSetup: "", setup: "",
    };
    stateRef.current = st;

    function resize() {
      const w = mount.clientWidth || 1;
      const h = mount.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(mount);

    const dummy = new THREE.Object3D();
    const tmpColor = new THREE.Color();

    // Resolve the data to draw: a live/replayed frame if running, otherwise the
    // spec's initial positions (so an imported structure shows up immediately).
    // Falls back to metadata-only (no positions) before anything is loaded.
    function getView(): ViewData {
      const s = useMDStore.getState();
      const running = s.frames.length > 0;
      const positions: Float32Array | null = running
        ? s.frames[Math.min(s.playbackIndex, s.frames.length - 1)].positions
        : flattenSpecPositions(s.spec.positions);

      const types = running && s.particleTypes.length ? s.particleTypes : s.spec.particle_types;
      const typeIndex = running && s.typeIndex.length ? s.typeIndex : s.spec.type_index;
      const boxLengths = (running ? s.boxLengths : s.spec.box.lengths) as [number, number, number];
      const n = positions ? positions.length / 3 : s.spec.n_particles;
      return { n, types, typeIndex, boxLengths, positions };
    }

    function flattenSpecPositions(pos: number[][] | null | undefined): Float32Array | null {
      if (!pos || pos.length === 0) return null;
      if (st.specPosRef === pos && st.specPosArr) return st.specPosArr;
      const arr = new Float32Array(pos.length * 3);
      for (let i = 0; i < pos.length; i++) {
        arr[i * 3] = pos[i][0]; arr[i * 3 + 1] = pos[i][1]; arr[i * 3 + 2] = pos[i][2];
      }
      st.specPosRef = pos;
      st.specPosArr = arr;
      return arr;
    }

    function fitTo(positions: Float32Array | null, box: [number, number, number]) {
      let cx: number, cy: number, cz: number, radius: number;
      if (positions && positions.length >= 3) {
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
        for (let i = 0; i < positions.length; i += 3) {
          const x = positions[i], y = positions[i + 1], z = positions[i + 2];
          if (x < minX) minX = x; if (x > maxX) maxX = x;
          if (y < minY) minY = y; if (y > maxY) maxY = y;
          if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
        }
        cx = (minX + maxX) / 2; cy = (minY + maxY) / 2; cz = (minZ + maxZ) / 2;
        radius = 0.5 * Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) || 5;
      } else {
        cx = box[0] / 2; cy = box[1] / 2; cz = box[2] / 2;
        radius = 0.5 * Math.hypot(box[0], box[1], box[2]) || 10;
      }
      const fov = (camera.fov * Math.PI) / 180;
      const dist = (radius / Math.sin(fov / 2)) * 1.15;
      const dir = new THREE.Vector3(0.6, 0.5, 1).normalize();
      controls.target.set(cx, cy, cz);
      camera.position.set(cx + dir.x * dist, cy + dir.y * dist, cz + dir.z * dist);
      controls.update();
    }

    // Exposed to the React "Fit view" button.
    fitFnRef.current = () => {
      const v = getView();
      fitTo(v.positions, v.boxLengths);
    };

    function ensureSetup(v: ViewData) {
      const sig = `${v.n}|${v.types.map((t) => t.color + t.radius).join(",")}|${v.boxLengths.join(",")}`;
      if (sig === st.setup && st.mesh) return;
      st.setup = sig;

      if (st.mesh) {
        scene.remove(st.mesh);
        st.mesh.geometry.dispose();
        (st.mesh.material as THREE.Material).dispose();
      }
      const geo = new THREE.SphereGeometry(1, 24, 18);
      // Glossy clearcoat material: reflective and slightly metallic so the
      // env-map and coloured rim lights read as wet, shiny highlights. The
      // per-instance colour (set below) tints each sphere by particle type.
      const mat = new THREE.MeshPhysicalMaterial({
        roughness: 0.22,
        metalness: 0.45,
        clearcoat: 0.85,
        clearcoatRoughness: 0.18,
        envMapIntensity: 1.25,
      });
      const mesh = new THREE.InstancedMesh(geo, mat, Math.max(v.n, 1));
      mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(v.n, 1) * 3), 3);
      const radii = new Float32Array(v.n);
      for (let i = 0; i < v.n; i++) {
        const t = v.types[v.typeIndex[i] ?? 0] ?? v.types[0];
        tmpColor.set(t?.color ?? "#6366f1");
        mesh.setColorAt(i, tmpColor);
        radii[i] = t?.radius ?? 0.5;
      }
      mesh.instanceColor.needsUpdate = true;
      mesh.visible = false; // shown once we actually have positions
      scene.add(mesh);
      st.mesh = mesh;
      st.radii = radii;

      // Box wireframe spanning [0, L).
      if (st.boxHelper) {
        scene.remove(st.boxHelper);
        st.boxHelper.geometry.dispose();
      }
      const [lx, ly, lz] = v.boxLengths;
      const boxLines = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.BoxGeometry(lx, ly, lz)),
        new THREE.LineBasicMaterial({ color: 0x4858a8, transparent: true, opacity: 0.6 })
      );
      boxLines.position.set(lx / 2, ly / 2, lz / 2);
      boxLines.visible = useMDStore.getState().view.showBox;
      scene.add(boxLines);
      st.boxHelper = boxLines;

      // Frame the camera once per distinct setup, without yanking it mid-navigation.
      if (st.framedSetup !== sig) {
        st.framedSetup = sig;
        fitTo(v.positions, v.boxLengths);
      }
    }

    function advancePlayback(now: number) {
      const s = useMDStore.getState();
      if (!s.playing || s.frames.length === 0 || s.follow) return;
      if (now - st.lastAdvance < 33) return; // replay buffered frames at ~30 fps
      st.lastAdvance = now;
      if (s.playbackIndex < s.frames.length - 1) {
        useMDStore.getState().setPlaybackIndex(s.playbackIndex + 1);
      }
    }

    function updateBonds(pos: Float32Array) {
      const s = useMDStore.getState();
      const bonds = s.spec.bonds;
      if (!s.view.showBonds || bonds.length === 0) {
        if (st.bondLines) st.bondLines.visible = false;
        return;
      }
      if (!st.bondLines || st.bondLines.geometry.attributes.position.count !== bonds.length * 2) {
        if (st.bondLines) {
          scene.remove(st.bondLines);
          st.bondLines.geometry.dispose();
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(bonds.length * 6), 3));
        st.bondLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xc4b5fd, transparent: true, opacity: 0.65 }));
        scene.add(st.bondLines);
      }
      const arr = st.bondLines.geometry.attributes.position.array as Float32Array;
      for (let k = 0; k < bonds.length; k++) {
        const b = bonds[k];
        arr[k * 6 + 0] = pos[b.i * 3]; arr[k * 6 + 1] = pos[b.i * 3 + 1]; arr[k * 6 + 2] = pos[b.i * 3 + 2];
        arr[k * 6 + 3] = pos[b.j * 3]; arr[k * 6 + 4] = pos[b.j * 3 + 1]; arr[k * 6 + 5] = pos[b.j * 3 + 2];
      }
      st.bondLines.geometry.attributes.position.needsUpdate = true;
      st.bondLines.visible = true;
    }

    function loop(now: number) {
      st.raf = requestAnimationFrame(loop);
      const v = getView();
      ensureSetup(v);
      advancePlayback(now);

      const mesh = st.mesh;
      if (mesh) {
        if (v.positions) {
          const pos = v.positions;
          const n = Math.min(pos.length / 3, st.radii.length);
          for (let i = 0; i < n; i++) {
            const r = st.radii[i];
            dummy.position.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
            dummy.scale.set(r, r, r);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
          }
          mesh.instanceMatrix.needsUpdate = true;
          mesh.visible = true;
          updateBonds(pos);
        } else {
          mesh.visible = false;
          if (st.bondLines) st.bondLines.visible = false;
        }
      }

      controls.update();
      renderer.render(scene, camera);
    }

    st.raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(st.raf);
      ro.disconnect();
      controls.dispose();
      pmrem.dispose();
      renderer.dispose();
      if (st.mesh) {
        st.mesh.geometry.dispose();
        (st.mesh.material as THREE.Material).dispose();
      }
      mount.removeChild(renderer.domElement);
    };
  }, []);

  // React to the box-visibility toggle without rebuilding the scene.
  const showBox = useMDStore((s) => s.view.showBox);
  useEffect(() => {
    const st = stateRef.current;
    if (st?.boxHelper) st.boxHelper.visible = showBox;
  }, [showBox]);

  return (
    <div className="relative w-full h-full">
      <div ref={mountRef} className="w-full h-full" />
      <div className="absolute top-3 right-3 flex items-center gap-2">
        <button
          onClick={toggleRecord}
          title={recording ? "Stop recording & download .webm" : "Record the view to a video"}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border backdrop-blur ${
            recording
              ? "text-white bg-red-600/80 border-red-500"
              : "text-slate-200 bg-surface/80 border-border hover:border-slate-500 hover:text-white"
          }`}
        >
          {recording ? <Square size={12} fill="white" /> : <Circle size={12} className="text-red-400" fill="currentColor" />}
          {recording ? "Stop" : "Record"}
        </button>
        <button
          onClick={fit}
          title="Fit view to structure"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-slate-200 bg-surface/80 backdrop-blur border border-border hover:border-slate-500 hover:text-white"
        >
          <Maximize2 size={13} /> Fit view
        </button>
      </div>
      {recError && (
        <div className="absolute top-12 right-3 text-[11px] text-red-300 bg-red-950/80 border border-red-500/30 rounded px-2 py-1 max-w-xs">
          {recError}
        </div>
      )}
    </div>
  );
}
