import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';

const view = document.getElementById('view'), side = document.getElementById('flist');
const info = document.getElementById('info');
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.localClippingEnabled = true;
view.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1d21);
const cam = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
cam.up.set(0, 0, 1);
const ctl = new OrbitControls(cam, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.1));
const dl = new THREE.DirectionalLight(0xffffff, 1.4);
dl.position.set(1, -1.5, 2);
scene.add(dl);
const plane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);
let obj = null, box = null, current = null, curM = 0;

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h);
  cam.aspect = w / h;
  cam.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();

function applyMat() {
  if (!obj) return;
  const axis = document.getElementById('axis').value;
  const t = +document.getElementById('pos').value;
  const wire = document.getElementById('wire').checked;
  obj.traverse(o => {
    if (!o.isMesh) return;
    o.material = new THREE.MeshStandardMaterial({
      color: 0xc9d1dc, metalness: 0.1, roughness: 0.6, side: THREE.DoubleSide,
      wireframe: wire, clippingPlanes: axis ? [plane] : []
    });
  });
  if (axis && box) {
    const i = 'XYZ'.indexOf(axis);
    const n = [0, 0, 0];
    n[i] = -1;
    plane.normal.set(n[0], n[1], n[2]);
    const lo = box.min.getComponent(i), hi = box.max.getComponent(i);
    plane.constant = lo + t * (hi - lo);
  }
}
for (const id of ['axis', 'pos', 'wire']) document.getElementById(id).addEventListener('input', applyMat);

async function load(path, keepCam) {
  const r = await fetch('/api/mesh?path=' + encodeURIComponent(path));
  if (!r.ok) { info.textContent = 'error: ' + await r.text(); return; }
  const gltf = await new GLTFLoader().parseAsync(await r.arrayBuffer(), '');
  if (obj) scene.remove(obj);
  obj = gltf.scene;
  scene.add(obj);
  box = new THREE.Box3().setFromObject(obj);
  const s = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  info.textContent = `${path}  ${s.x.toFixed(2)} x ${s.y.toFixed(2)} x ${s.z.toFixed(2)} (model units)`;
  if (!keepCam) {
    const d = Math.max(s.x, s.y, s.z) * 2.2 || 10;
    cam.position.set(c.x + d * 0.6, c.y - d * 0.8, c.z + d * 0.6);
    ctl.target.copy(c);
    ctl.update();
  }
  applyMat();
}

async function refresh() {
  const list = await (await fetch('/api/models')).json();
  side.innerHTML = '';
  for (const m of list) {
    const d = document.createElement('div');
    d.className = 'f' + (m.path === current ? ' on' : '');
    d.textContent = m.path;
    d.onclick = () => { current = m.path; curM = m.mtime; load(m.path, false); refresh(); };
    side.appendChild(d);
  }
  const cur = list.find(m => m.path === current);
  if (cur && cur.mtime !== curM) { curM = cur.mtime; load(current, true); }
}
refresh();
setInterval(refresh, 3000);
(function loop() { requestAnimationFrame(loop); renderer.render(scene, cam); })();
