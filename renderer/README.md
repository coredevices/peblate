# Local WASM trial

The renderer source lives in the PebbleOS checkout at `tools/text2wasm`.
From this repository, with the sibling PebbleOS checkout:

```sh
docker run --rm --platform linux/amd64 \
  -v "$PWD/../pebbleos:/fw:ro" -v "$PWD:/work" \
  emscripten/emsdk:4.0.15 sh -c \
  'cmake -S /fw/tools/text2wasm -B /work/runtime/wasm-build && cmake --build /work/runtime/wasm-build --target text2wasm'
mkdir -p src/peblate/static/pebble/renderer
cp runtime/wasm-build/dist/renderer.js src/peblate/static/pebble/renderer/
cp runtime/wasm-build/dist/GOTHIC*.pbf src/peblate/static/pebble/renderer/
cp runtime/wasm-build/dist/revision.txt src/peblate/static/pebble/renderer/
uv build --wheel --out-dir examples/docker/wheels
docker compose --env-file .env -f examples/docker/compose.yaml up -d --build weblate
```

This checkout dependency is only for producing the development artifact.
Deployment should download a versioned renderer bundle from firmware CI.

`smoke.cjs` executes the generated WASM under Node in the same container and
checks blank input, ordinary text, umlauts, and missing-glyph fallback.
It does not establish Hebrew or Arabic glyph coverage.

`extension-smoke.cjs` uses the PBF emitted by the Weblate smoke test and checks
that Hebrew pixels change with the extension while Latin base glyphs stay identical.
