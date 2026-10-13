# Local WASM trial

The renderer source lives in the PebbleOS checkout at `tools/text2wasm`.
From this repository, with the sibling PebbleOS checkout:

```sh
docker run --rm --platform linux/amd64 \
  -v "$PWD/../pebbleos:/fw:ro" -v "$PWD:/work" \
  emscripten/emsdk:4.0.15 sh -c \
  'emcmake cmake -S /fw/tools/text2wasm -B /work/runtime/wasm-build && cmake --build /work/runtime/wasm-build --target text2wasm'
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

The nine LECO base fonts in `src/peblate/static/pebble/leco` are copied unchanged
from `resources/normal/base/pbf` at PebbleOS
`daa377d8a3d5a1eda69a8d0d2f54c5b4c5b2cbcd`. Their SHA-256 hashes and glyph
coverage match `pebbleos-translations/data/builtin_font_coverage.json`. They are
bundled in the Peblate wheel so LECO previews also work with renderer artifacts
that only contain Gothic base fonts. Updating these files requires updating
the coverage snapshot and rerunning the font tests and `leco-smoke.cjs`.

`node renderer/leco-smoke.cjs runtime/leco` checks all nine base fonts and the
Russian Health labels against the WASM renderer. Supply the compiled
`LECO_20_BOLD_NUMBERS_EXTENDED.pbf` and
`LECO_26_BOLD_NUMBERS_AM_PM_EXTENDED.pbf` in `runtime/leco` (from the editor's
preview endpoints or the pack compiler).

`extension-smoke.cjs` uses the PBF emitted by the Weblate smoke test and checks
that Hebrew pixels change with the extension while Latin base glyphs stay identical.
