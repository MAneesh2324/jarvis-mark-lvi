// JARVIS simulation board — 3D scenes (three.js, bundled locally; no network).
//
// Python drives it with three calls:
//   Sim3D.load(model)    model = {scene, series, series_t, units, title, x_unit, status}
//   Sim3D.setTime(t)     show the state at time t; null = play the whole run as a time-lapse loop
//   Sim3D.setStatus(s)   'success' | 'failed' | null — tints the stage
// and reads Sim3D.currentTime() to mark the chart.
//
// Scenes: tree (fruit tree), grow (one object on a pedestal), fill (glass tank),
//         dots (a population), columns (any model: one glowing column per quantity).

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';

const CYAN = new THREE.Color('#18d3ed');
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const lerp = (a, b, k) => a + (b - a) * k;

// ── deterministic noise so every tree looks the same between runs ─────────────
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

// ── renderer, camera, post-processing ────────────────────────────────────────
const canvas = document.getElementById('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.92;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color('#00060a');
scene.fog = new THREE.FogExp2('#00060a', 0.055);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.38, 0.5, 0.9);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// ── lights ───────────────────────────────────────────────────────────────────
scene.add(new THREE.HemisphereLight('#bfe9ff', '#0a1a12', 0.55));
const sun = new THREE.DirectionalLight('#fff1d6', 1.9);
sun.position.set(5, 9, 4);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -6; sun.shadow.camera.right = 6; sun.shadow.camera.top = 8; sun.shadow.camera.bottom = -4;
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02; sun.shadow.radius = 4;
scene.add(sun);
const rim = new THREE.DirectionalLight(CYAN, 1.6);
rim.position.set(-6, 4, -6);
scene.add(rim);

// ── the stage every scene stands on ──────────────────────────────────────────
const stage = new THREE.Group();
scene.add(stage);
const ground = new THREE.Mesh(new THREE.CircleGeometry(5.2, 96),
  new THREE.MeshStandardMaterial({ color: '#06141c', roughness: 0.85, metalness: 0.1 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
stage.add(ground);
const ringMat = new THREE.MeshBasicMaterial({ color: CYAN, transparent: true, opacity: 0.85 });
const rings = [];
for (const [r, w] of [[5.2, 0.035], [4.4, 0.012], [3.2, 0.01]]) {
  const m = new THREE.Mesh(new THREE.RingGeometry(r - w, r, 128), ringMat.clone());
  m.rotation.x = -Math.PI / 2; m.position.y = 0.005; stage.add(m); rings.push(m);
}
const grid = new THREE.PolarGridHelper(5.2, 24, 8, 96, '#0d3347', '#0d3347');
grid.position.y = 0.003; stage.add(grid);
// a scan ring that sweeps up and down the model
const scan = new THREE.Mesh(new THREE.TorusGeometry(2.6, 0.012, 8, 160),
  new THREE.MeshBasicMaterial({ color: CYAN, transparent: true, opacity: 0.6 }));
scan.rotation.x = Math.PI / 2; stage.add(scan);
// floating dust
const dust = (() => {
  const n = 700, g = new THREE.BufferGeometry(), p = new Float32Array(n * 3), r = rng(7);
  for (let i = 0; i < n; i++) { const a = r() * Math.PI * 2, d = Math.sqrt(r()) * 6; p.set([Math.cos(a) * d, r() * 7, Math.sin(a) * d], i * 3); }
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: CYAN, size: 0.025, transparent: true, opacity: 0.55, depthWrite: false }));
  scene.add(pts); return pts;
})();

// ── model state ──────────────────────────────────────────────────────────────
let model = null, built = null, forcedTime = null, status = null;
let shownTime = 0;
const clock = new THREE.Clock();
const hud = document.getElementById('hud');

function seriesAt(name, t) {
  if (!model || !model.series || !model.series[name]) return 0;
  const ts = model.series_t, v = model.series[name];
  if (t <= ts[0]) return v[0];
  for (let i = 1; i < ts.length; i++) if (t <= ts[i]) { const k = (t - ts[i - 1]) / ((ts[i] - ts[i - 1]) || 1); return lerp(v[i - 1], v[i], k); }
  return v[v.length - 1];
}
function frac(name, max, t) { return name ? clamp(seriesAt(name, t) / (max || 1), 0, 1) : 0; }
function colorOf(sc, t) {
  const a = new THREE.Color(sc.from || '#7cc242'), b = new THREE.Color(sc.to || '#d62828');
  return a.lerp(b, frac(sc.color, sc.color_max || 100, t));
}
function clear() { if (built) { stage.remove(built.group); built.group.traverse(o => { o.geometry && o.geometry.dispose(); }); } built = null; }

// ── shared models ────────────────────────────────────────────────────────────
function appleGeometry() {
  // a lathe profile: dimpled top, round shoulders, narrower base
  const pts = [];
  for (let i = 0; i <= 32; i++) {
    const a = (i / 32) * Math.PI;
    const r = Math.sin(a) * (1 + 0.08 * Math.sin(a * 2)) * (1 - 0.12 * Math.max(0, Math.cos(a)));
    let y = -Math.cos(a) * 0.92;
    if (i < 3 || i > 29) y += (i < 3 ? 0.12 : -0.08) * (1 - Math.sin(a));
    pts.push(new THREE.Vector2(Math.max(0.001, r), y));
  }
  const g = new THREE.LatheGeometry(pts, 40);
  g.computeVertexNormals();
  return g;
}
const APPLE = appleGeometry();
function fruitMesh(color) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(APPLE, new THREE.MeshPhysicalMaterial({ color, roughness: 0.42, clearcoat: 0.45, clearcoatRoughness: 0.35, envMapIntensity: 0.6 }));
  body.castShadow = true; g.add(body);
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.035, 0.38, 6), new THREE.MeshStandardMaterial({ color: '#5a3b1f', roughness: 0.9 }));
  stem.position.y = 0.95; stem.rotation.z = 0.25; g.add(stem);
  const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.2, 10, 6), new THREE.MeshStandardMaterial({ color: '#3fa34d', roughness: 0.6 }));
  leaf.scale.set(1, 0.18, 0.5); leaf.position.set(0.18, 1.05, 0); leaf.rotation.z = -0.5; g.add(leaf);
  g.userData.body = body;
  return g;
}
function bumpy(geo, amount, seed) {
  // displacement is a smooth function of position, so vertices shared by two faces move together (no cracks)
  geo = mergeVertices(geo.deleteAttribute('normal').deleteAttribute('uv'));
  const p = geo.attributes.position, v = new THREE.Vector3(), o = seed * 1.37;
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    const n = Math.sin(v.x * 3.1 + o) * Math.sin(v.y * 2.7 + o * 2) * Math.sin(v.z * 3.3 + o * 3)
            + 0.5 * Math.sin(v.x * 7.3 + v.z * 5.1 + o);
    v.multiplyScalar(1 + n * amount); p.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals(); return geo;
}
function leafGeometry() {
  const sh = new THREE.Shape();
  sh.moveTo(0, 0); sh.bezierCurveTo(0.09, 0.05, 0.1, 0.18, 0, 0.28); sh.bezierCurveTo(-0.1, 0.18, -0.09, 0.05, 0, 0);
  const g = new THREE.ShapeGeometry(sh, 4); g.translate(0, -0.02, 0); return g;
}

// ── scene: a fruit tree ──────────────────────────────────────────────────────
function buildTree(sc) {
  const group = new THREE.Group(), r = rng(11);
  const bark = new THREE.MeshStandardMaterial({ color: '#5b3a22', roughness: 0.95 });
  const tips = [];
  function limb(from, dir, len, rad, depth) {
    const to = from.clone().add(dir.clone().multiplyScalar(len));
    const bend = new THREE.Vector3((r() - .5) * .25 * len, 0.05 * len, (r() - .5) * .25 * len);
    const mid = from.clone().lerp(to, 0.5).add(bend);
    const tube = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([from, mid, to]), 14, rad, 10), bark);
    tube.castShadow = true; tube.receiveShadow = true; group.add(tube);
    const cap = new THREE.Mesh(new THREE.SphereGeometry(rad, 10, 8), bark); cap.position.copy(to); group.add(cap);
    if (depth === 0) { tips.push(to); return; }
    const kids = depth === 3 ? 4 : 3;
    for (let k = 0; k < kids; k++) {
      const yaw = (k / kids) * Math.PI * 2 + r() * 0.8;
      const out = new THREE.Vector3(Math.cos(yaw), 0, Math.sin(yaw));
      const d = dir.clone().multiplyScalar(0.55).add(out.multiplyScalar(depth === 3 ? 0.95 : 0.7)).add(new THREE.Vector3(0, 0.35, 0)).normalize();
      limb(to, d, len * (0.7 + r() * 0.12), rad * 0.6, depth - 1);
    }
    tips.push(to);
  }
  limb(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0.04, 1, 0.02), 1.45, 0.2, 3);
  // flared roots
  for (let k = 0; k < 5; k++) {
    const a = k / 5 * Math.PI * 2 + 0.3, root = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.55, 8), bark);
    root.position.set(Math.cos(a) * 0.16, 0.08, Math.sin(a) * 0.16); root.rotation.set(Math.sin(a) * 1.1, 0, -Math.cos(a) * 1.1); group.add(root);
  }
  // canopy: smooth lumpy clusters for volume, then thousands of real leaves on top
  const leafMat = new THREE.MeshStandardMaterial({ color: '#1f4d24', roughness: 0.95, envMapIntensity: 0.25 });
  const clusters = [];
  const centres = tips.filter(p => p.y > 1.6);
  centres.forEach((p, i) => {
    const s = 0.5 + r() * 0.3;
    const m = new THREE.Mesh(bumpy(new THREE.IcosahedronGeometry(s * 0.86, 4), 0.16, 100 + i), leafMat);
    m.position.copy(p).add(new THREE.Vector3(0, 0.15, 0)); m.castShadow = true; m.receiveShadow = true;
    group.add(m); clusters.push({ m, s });
  });
  const LEAVES = 2600, leafGeo = leafGeometry();
  const leaves = new THREE.InstancedMesh(leafGeo, new THREE.MeshStandardMaterial({ roughness: 0.78, side: THREE.DoubleSide, envMapIntensity: 0.3 }), LEAVES);
  leaves.castShadow = true; leaves.receiveShadow = true;
  const mm = new THREE.Matrix4(), qq = new THREE.Quaternion(), ss = new THREE.Vector3(), pp = new THREE.Vector3(), cc = new THREE.Color(), up = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < LEAVES; i++) {
    const { m, s } = clusters[i % clusters.length];
    const dir = new THREE.Vector3(r() - .5, r() - .35, r() - .5).normalize();
    pp.copy(m.position).add(dir.clone().multiplyScalar(s * (0.92 + r() * 0.22)));
    qq.setFromUnitVectors(up, dir).multiply(new THREE.Quaternion().setFromAxisAngle(up, r() * Math.PI * 2));
    ss.setScalar(0.75 + r() * 0.6); mm.compose(pp, qq, ss); leaves.setMatrixAt(i, mm);
    leaves.setColorAt(i, cc.setHSL(0.26 + r() * 0.07, 0.5 + r() * 0.2, 0.13 + r() * 0.12));
  }
  group.add(leaves);
  // fruit hanging on the outside and underside of the canopy, each on a short stalk
  const fruits = [], blossoms = [];
  const n = clamp(sc.fruits || 22, 4, 60);
  for (let i = 0; i < n; i++) {
    const { m, s } = clusters[(i * 7) % clusters.length];
    const dir = new THREE.Vector3(r() - .5, -0.25 - r() * .55, r() - .5).normalize();
    const pos = m.position.clone().add(dir.multiplyScalar(s * 1.08));
    const f = fruitMesh('#7cc242'); f.position.copy(pos); f.rotation.set((r() - .5) * .3, r() * 6, (r() - .5) * .3);
    group.add(f); fruits.push(f);
    const b = new THREE.Group();
    for (let k = 0; k < 5; k++) {
      const petal = new THREE.Mesh(new THREE.SphereGeometry(0.075, 8, 6), new THREE.MeshStandardMaterial({ color: '#fff0f6', emissive: '#ffb6d3', emissiveIntensity: 0.35, roughness: 0.6 }));
      petal.scale.set(1, 0.3, 0.6); const a = k / 5 * Math.PI * 2; petal.position.set(Math.cos(a) * 0.07, 0, Math.sin(a) * 0.07); b.add(petal);
    }
    b.position.copy(m.position).add(dir.clone().normalize().multiplyScalar(s * 1.14)); group.add(b); blossoms.push(b);
  }
  const grass = new THREE.Mesh(new THREE.CircleGeometry(2.3, 64), new THREE.MeshStandardMaterial({ color: '#1f4a23', roughness: 1 }));
  grass.rotation.x = -Math.PI / 2; grass.position.y = 0.01; grass.receiveShadow = true; group.add(grass);
  const green = new THREE.Color('#2d6e33'), autumn = new THREE.Color('#5d7a26');
  return {
    group, height: 4.0,
    update(t) {
      const size = frac(sc.size, sc.max, t);
      const col = colorOf(sc, t);
      const visible = sc.count ? Math.round(clamp(seriesAt(sc.count, t), 0, n)) : n;
      fruits.forEach((f, i) => {
        f.visible = i < visible && size > 0.01;
        f.scale.setScalar(0.03 + 0.17 * size);
        f.userData.body.material.color.copy(col);
      });
      const bloomK = clamp(1 - size * 5, 0, 1);
      blossoms.forEach(b => { b.visible = bloomK > 0.03; b.scale.setScalar(0.5 + bloomK); });
      leafMat.color.copy(green).lerp(autumn, frac(sc.color, sc.color_max || 100, t) * 0.35);
    },
  };
}

// ── scene: one object growing on a pedestal ──────────────────────────────────
function buildGrow(sc) {
  const group = new THREE.Group();
  const ped = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.3, 0.35, 64), new THREE.MeshStandardMaterial({ color: '#0b2230', metalness: 0.6, roughness: 0.35 }));
  ped.position.y = 0.175; ped.receiveShadow = true; ped.castShadow = true; group.add(ped);
  const glow = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.02, 8, 96), new THREE.MeshBasicMaterial({ color: CYAN }));
  glow.rotation.x = Math.PI / 2; glow.position.y = 0.36; group.add(glow);
  const fruity = /apple|fruit|orange|peach|plum|cherry|tomato|mango|pear/i.test(sc.label || '');
  const obj = fruity ? fruitMesh('#7cc242') : new THREE.Mesh(bumpy(new THREE.IcosahedronGeometry(1, 5), 0.06, 3),
    new THREE.MeshPhysicalMaterial({ color: '#7cc242', roughness: 0.25, transmission: 0.25, thickness: 1, clearcoat: 0.8 }));
  obj.castShadow = true; group.add(obj);
  const mat = fruity ? obj.userData.body.material : obj.material;
  return {
    group, height: 3.4,
    update(t, time) {
      const s = 0.12 + 1.15 * frac(sc.size, sc.max, t);
      obj.scale.setScalar(s); obj.position.y = 0.36 + s * (fruity ? 0.92 : 1);
      obj.rotation.y = time * 0.4; mat.color.copy(colorOf(sc, t));
    },
  };
}

// ── scene: a glass tank filling and draining ─────────────────────────────────
function buildFill(sc) {
  const group = new THREE.Group(), H = 3.2, R = 1.15;
  const glass = new THREE.Mesh(new THREE.CylinderGeometry(R, R, H, 64, 1, true),
    new THREE.MeshPhysicalMaterial({ color: '#cfefff', transmission: 1, thickness: 0.15, roughness: 0.04, ior: 1.45, transparent: true, opacity: 0.35, side: THREE.DoubleSide }));
  glass.position.y = H / 2; group.add(glass);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(R * 1.12, R * 1.18, 0.2, 64), new THREE.MeshStandardMaterial({ color: '#0b2230', metalness: 0.7, roughness: 0.3 }));
  base.position.y = 0.1; base.receiveShadow = true; group.add(base);
  for (let i = 1; i < 10; i++) {                     // level marks
    const m = new THREE.Mesh(new THREE.TorusGeometry(R * 1.005, 0.006, 4, 64, 0.7), new THREE.MeshBasicMaterial({ color: CYAN }));
    m.rotation.x = Math.PI / 2; m.position.y = 0.2 + (H - 0.3) * i / 10; group.add(m);
  }
  const liquidMat = new THREE.MeshPhysicalMaterial({ color: '#2fa3ff', roughness: 0.1, transmission: 0.55, thickness: 2, emissive: '#0a3a66', emissiveIntensity: 0.4 });
  const liquid = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.97, R * 0.97, 1, 64), liquidMat);
  group.add(liquid);
  const surf = new THREE.Mesh(new THREE.CircleGeometry(R * 0.97, 64, 0, Math.PI * 2), new THREE.MeshPhysicalMaterial({ color: '#7fd0ff', roughness: 0.05, emissive: '#1a6aa8', emissiveIntensity: 0.6, side: THREE.DoubleSide }));
  surf.rotation.x = -Math.PI / 2; group.add(surf);
  const sp = surf.geometry.attributes.position, base0 = sp.array.slice();
  return {
    group, height: H + 0.4,
    update(t, time) {
      const level = 0.02 + 0.96 * frac(sc.size, sc.max, t), h = 0.2 + (H - 0.3) * level;
      liquid.scale.y = h - 0.2; liquid.position.y = 0.2 + (h - 0.2) / 2; surf.position.y = h;
      for (let i = 0; i < sp.count; i++) {
        const x = base0[i * 3], y = base0[i * 3 + 1];
        sp.setZ(i, 0.03 * Math.sin(x * 4 + time * 2.2) * Math.cos(y * 3 + time * 1.7));
      }
      sp.needsUpdate = true;
      const c = colorOf({ ...sc, from: sc.from || '#2fa3ff', to: sc.to || '#2fa3ff' }, t);
      liquidMat.color.copy(c); surf.material.color.copy(c).offsetHSL(0, 0, 0.15);
    },
  };
}

// ── scene: a population of particles ────────────────────────────────────────
function buildDots(sc) {
  const group = new THREE.Group(), n = 900, r = rng(5);
  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.06, 10, 8), new THREE.MeshStandardMaterial({ roughness: 0.4, emissive: '#000000' }), n);
  mesh.castShadow = true;
  const home = [], m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
  for (let i = 0; i < n; i++) { const a = r() * Math.PI * 2, d = Math.sqrt(r()) * 3.4; home.push([Math.cos(a) * d, 0.08 + r() * 2.6 * (1 - d / 4), Math.sin(a) * d, r() * 6]); }
  group.add(mesh);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(3.7, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: CYAN, wireframe: true, transparent: true, opacity: 0.08 }));
  group.add(dome);
  return {
    group, height: 3.8,
    update(t, time) {
      const count = Math.round(n * frac(sc.size, sc.max, t)), col = colorOf(sc, t);
      mesh.material.color.copy(col); mesh.material.emissive.copy(col).multiplyScalar(0.12);
      for (let i = 0; i < n; i++) {
        const [x, y, z, ph] = home[i];
        p.set(x + 0.08 * Math.sin(time + ph), y + 0.06 * Math.sin(time * 1.3 + ph * 2), z + 0.08 * Math.cos(time * 0.9 + ph));
        s.setScalar(i < count ? 1 : 0); m.compose(p, q, s); mesh.setMatrixAt(i, m);
      }
      mesh.instanceMatrix.needsUpdate = true;
    },
  };
}

// ── scene: one glowing column per quantity (works for any model) ─────────────
function label(text) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 96;
  const x = c.getContext('2d'); x.font = '600 38px Menlo, Courier New, monospace'; x.fillStyle = '#8ffcff'; x.textAlign = 'center';
  x.fillText(text.toUpperCase().slice(0, 22), 256, 60);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
  sp.scale.set(2.2, 0.41, 1); return sp;
}
function buildColumns(sc) {
  const group = new THREE.Group(), names = Object.keys(model.series || {}).slice(0, 6), cols = [];
  const max = {}; names.forEach(n => { max[n] = Math.max(...model.series[n].map(Math.abs), 1e-9); });
  names.forEach((n, i) => {
    const a = (i / names.length) * Math.PI * 2 + 0.4, d = names.length > 1 ? 2.1 : 0;
    const mat = new THREE.MeshPhysicalMaterial({ color: CYAN, emissive: CYAN, emissiveIntensity: 0.18, roughness: 0.3, metalness: 0.2, clearcoat: 0.6, envMapIntensity: 0.5 });
    const col = new THREE.Mesh(new THREE.BoxGeometry(0.62, 1, 0.62), mat); col.castShadow = true;
    col.position.set(Math.cos(a) * d, 0, Math.sin(a) * d); group.add(col);
    const tag = label(n.replace(/_/g, ' ')); tag.position.set(col.position.x, 0.4, col.position.z); group.add(tag);
    cols.push({ n, col, tag, mat });
  });
  return {
    group, height: 4,
    update(t) {
      cols.forEach(({ n, col, tag, mat }, i) => {
        const k = clamp(Math.abs(seriesAt(n, t)) / max[n], 0, 1), h = 0.05 + 3 * k;
        col.scale.y = h; col.position.y = h / 2; tag.position.y = h + 0.45;
        mat.color.setHSL(0.52 - 0.5 * k * (i % 2 ? 0.2 : 0.35), 0.9, 0.42); mat.emissive.copy(mat.color);
      });
    },
  };
}

const BUILDERS = { tree: buildTree, grow: buildGrow, fill: buildFill, dots: buildDots, columns: buildColumns };

// ── camera framing and the frame loop ────────────────────────────────────────
function frame(h) { built.height = h; }
function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false); composer.setSize(w, h); bloom.setSize(w, h);
  camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function duration() { const ts = (model && model.series_t) || [0, 1]; return [ts[0], ts[ts.length - 1]]; }

function tick() {
  requestAnimationFrame(tick);
  const time = clock.getElapsedTime();
  if (model && built) {
    const [t0, t1] = duration();
    if (forcedTime !== null) shownTime = forcedTime;
    else { const loop = 10, hold = 1.6, k = (time % (loop + hold)) / loop; shownTime = lerp(t0, t1, Math.min(1, k)); }
    built.update(shownTime, time);
    const h = built.height || 4;
    const ang = time * 0.12, aspect = Math.max(.6, camera.aspect);
    const dist = (h * 2.35 + 2.2) / Math.min(1, aspect);
    camera.position.set(Math.sin(ang) * dist, h * 0.55 + 0.9, Math.cos(ang) * dist);
    camera.lookAt(0, h * 0.5, 0);
    scan.position.y = (Math.sin(time * 0.9) * 0.5 + 0.5) * h;
    scan.scale.setScalar(0.75 + 0.35 * Math.sin(time * 0.9 + 1));
    hudText(shownTime);
  }
  const tint = status === 'success' ? new THREE.Color('#00ff88') : status === 'failed' ? new THREE.Color('#ff3355') : CYAN;
  rings.forEach((m, i) => { m.material.color.copy(tint); m.material.opacity = 0.55 + 0.35 * Math.sin(clock.elapsedTime * 2 + i); });
  scan.material.color.copy(tint); rim.color.copy(tint);
  dust.rotation.y += 0.0008;
  composer.render();
}

function hudText(t) {
  if (!hud || !model) return;
  const unit = model.x_unit || '';
  const names = Object.keys(model.series || {}).slice(0, 4);
  const vals = names.map(n => `<b>${n.replace(/_/g, ' ')}</b> ${seriesAt(n, t).toFixed(1)} ${(model.units || {})[n] || ''}`).join('<br>');
  hud.innerHTML = `<div class="t">${(model.title || '').toUpperCase()}</div><div class="d">${unit.replace(/s$/, '').toUpperCase()} ${Math.round(t)}</div>${vals}`;
}

window.Sim3D = {
  load(m) {
    model = m; clear();
    const sc = Object.assign({ type: 'columns' }, m.scene || {});
    const make = BUILDERS[sc.type] || buildColumns;
    built = make(sc); stage.add(built.group); frame(built.height);
    status = m.status || null;
    resize();
    return true;
  },
  setTime(t) { forcedTime = (t === null || t === undefined) ? null : Number(t); return true; },
  setStatus(s) { status = s || null; return true; },
  currentTime() { return shownTime; },
  ready: true,
};
resize();
tick();
document.title = 'sim3d-ready';
