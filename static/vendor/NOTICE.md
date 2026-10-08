# Local browser dependency

The graph renderer uses **PixiJS 8.19.0** under the MIT license, retained in [PIXI-LICENSE.txt](PIXI-LICENSE.txt).

- Project: https://github.com/pixijs/pixijs
- Browser distribution: https://cdn.jsdelivr.net/npm/pixi.js@8.19.0/dist/pixi.min.js
- Local file: `pixi-8.19.0.min.js`
- SHA-256: `83b2d7edf27bb77460f5f5f5e25cd73c91b77a53f44c80ac63096d6c0b5cfda7`
- License SHA-256: `5ce7447bc57f7349ffc48338782fbcabe613696e00712b20d66bc58e780f9473`

`network-pixi.js` is an independent adapter for this project's graph interactions. Molio's implementation was reviewed as an architectural reference and was not copied.

The course graph page includes **@antv/g6 5.1.1**, published by the AntV project under the MIT license. Its complete license is retained in [G6-LICENSE.txt](G6-LICENSE.txt).

- Project: https://github.com/antvis/G6
- Browser distribution: https://cdn.jsdelivr.net/npm/@antv/g6@5.1.1/dist/g6.min.js
- License source: https://cdn.jsdelivr.net/npm/@antv/g6@5.1.1/LICENSE
- Local file: `g6-5.1.1.min.js`
- SHA-256: `3e091a94fd08994a383ff34bfba256bb8e382e4be4042197a206d2ecc0957331`
- License SHA-256: `d296127a77fae081300d5b18fcfa5ccda75cd16670c1b46dc890a8903ca95128`

The file is served locally; the page does not load a remote runtime script. Other projects discussed in `docs/v7-alignment.md` were design references, not vendored dependencies. This package was copied from the newly authored graph prototype; no pre-existing ChatEval business implementation was imported.
