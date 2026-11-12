`offset-loot.png` is a small crop of the user-supplied Tarkov screenshot
2026-11-11 223447. It contains only the public game inventory artwork and slots.
The crop starts at an arbitrary offset, not a grid origin. `offset-loot-ocr.json`
replays the actual local RU/EN OCR output with coordinates shifted to that crop.
It tests geometry and duplicate handling without downloading OCR models in unit tests.
