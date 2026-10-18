import {Viewer, Display} from '/vendor/three-cad-viewer/three-cad-viewer.esm.min.js';

const box = document.getElementById('cad'), list = document.getElementById('list'), msg = document.getElementById('msg');
let display = null, viewer = null, current = null, curM = 0;

function sizes() { return {cadWidth: Math.max(300, box.clientWidth - 260), height: Math.max(300, box.clientHeight - 40), treeWidth: 240}; }

function fresh() {
  box.innerHTML = '';
  const s = sizes();
  display = new Display(box, {...s, theme: 'dark', pinning: false,
    keymap: {shift: 'shiftKey', ctrl: 'ctrlKey', meta: 'metaKey'}});
  viewer = new Viewer(display, {target: [0, 0, 0], up: 'Z'}, change => { window.__lastChange = change; });
}

async function load(path) {
  msg.textContent = '変換中…';
  const r = await fetch('/api/shapes?path=' + encodeURIComponent(path));
  if (!r.ok) { msg.textContent = 'error: ' + await r.text(); return; }
  const shapes = await r.json();
  fresh();
  viewer.render(shapes, {ambientIntensity: 1.0, directIntensity: 1.1, metalness: 0.3, roughness: 0.65,
    edgeColor: 0x707070, defaultOpacity: 0.5, normalLen: 0}, {target: [0, 0, 0], up: 'Z'});
  window.__viewer = viewer;
  msg.textContent = path;
}

async function refresh() {
  const all = await (await fetch('/api/models')).json();
  const steps = all.filter(m => /\.(step|stp)$/i.test(m.path));
  list.innerHTML = '';
  for (const m of steps) {
    const d = document.createElement('div');
    d.className = 'f' + (m.path === current ? ' on' : '');
    d.textContent = m.path;
    d.onclick = () => { current = m.path; curM = m.mtime; load(m.path); refresh(); };
    list.appendChild(d);
  }
  const cur = steps.find(m => m.path === current);
  if (cur && cur.mtime !== curM) { curM = cur.mtime; load(current); }
}
refresh();
setInterval(refresh, 3000);
