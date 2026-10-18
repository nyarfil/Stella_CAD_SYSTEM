# Third-party code

`vendor/three/` is an unmodified subset of **three.js r186** (npm `three@0.186.0`).

- License: MIT, see `vendor/three/LICENSE` (Copyright 2010-2026 three.js authors)
- Source: https://registry.npmjs.org/three/-/three-0.186.0.tgz, sha1 `08f70ce80dffa9247a567b421165bec630e86f8d` (matches the registry value)
- Included files: `build/three.module.js`, `build/three.core.js`, `examples/jsm/controls/OrbitControls.js`, `examples/jsm/loaders/GLTFLoader.js`, `examples/jsm/utils/BufferGeometryUtils.js`, `examples/jsm/utils/SkeletonUtils.js`
- Added 2026-10-18 with the owner's approval. No other external code is bundled; the page loads nothing from the network.

## three-cad-viewer 5.1.3 (added 2026-10-18, owner delegated approval)

`vendor/three-cad-viewer/` holds the unmodified `dist/three-cad-viewer.esm.min.js` and `three-cad-viewer.css`.

- Package: `three-cad-viewer@5.1.3` (bernhard-42), MIT, `vendor/three-cad-viewer/LICENSE`. Installed with `npm install --ignore-scripts` in an isolated scratch dir; only the built files were copied.
- The ESM bundle is self-contained: it embeds three.js r184 (MIT), postprocessing 6.39.0 (Zlib, `LICENSE.postprocessing`) and n8ao 1.10.1 (`LICENSE.n8ao`, the file is CC0 1.0 although the npm metadata says ISC; both are permissive).
- The bundle contains URL strings for downloading optional HDR lighting maps from polyhaven.org (Studio tab). They are fetched only if the user selects such an environment; nothing is loaded from the network by default.
- The simple mesh page (`static/index.html`) keeps using three.js r186 from `vendor/three/`; the CAD page uses the bundled r184 and does not share it.
