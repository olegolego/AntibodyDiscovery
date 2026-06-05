import { useCallback, useEffect, useRef } from "react";
import { Maximize2 } from "lucide-react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
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

  useEffect(() => {
    const mount = mountRef.current!;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0f1e);

    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 20000);
    camera.position.set(20, 16, 28);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    // Screen-space panning makes right-drag move the scene right (the world-space
    // default pans along the ground plane, which feels broken from most angles).
    controls.screenSpacePanning = true;
    controls.rotateSpeed = 0.65;
    controls.zoomSpeed = 0.9;
    controls.panSpeed = 0.8;
    controls.minDistance = 0.5;
    controls.maxDistance = 12000;
    controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(1, 1, 1);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x6688ff, 0.4);
    rim.position.set(-1, -0.5, -1);
    scene.add(rim);

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
      const geo = new THREE.SphereGeometry(1, 16, 12);
      const mat = new THREE.MeshStandardMaterial({ roughness: 0.4, metalness: 0.1 });
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
        new THREE.LineBasicMaterial({ color: 0x33406a })
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
        st.bondLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x9ca3ff, transparent: true, opacity: 0.5 }));
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
      <button
        onClick={fit}
        title="Fit view to structure"
        className="absolute top-3 right-3 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-slate-200 bg-surface/80 backdrop-blur border border-border hover:border-slate-500 hover:text-white"
      >
        <Maximize2 size={13} /> Fit view
      </button>
    </div>
  );
}
