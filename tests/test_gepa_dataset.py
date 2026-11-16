"""Contract checks for slide manifests; these tests are not run by the prototype builder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.gepa.dataset import load_manifest


class SlideManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.images = self.base / "images"
        self.images.mkdir()
        self.manifest = self.base / "manifest.json"

    def add_image(self, relative_path: str) -> None:
        path = self.images / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image fixture")

    def write_examples(self, examples: list[dict]) -> None:
        self.manifest.write_text(json.dumps({"examples": examples}), encoding="utf-8")

    def test_loads_and_partitions_examples_with_neighbor_images(self) -> None:
        for path in ("deck-a/1.png", "deck-a/2.png", "deck-b/1.png"):
            self.add_image(path)
        self.write_examples(
            [
                {
                    "split": "train",
                    "example_id": "a-2",
                    "deck_id": "deck-a",
                    "slide_number": 2,
                    "target_slide_image": "deck-a/2.png",
                    "preceding_slide_image": "deck-a/1.png",
                    "target_duration_seconds": 30,
                },
                {
                    "split": "val",
                    "example_id": "b-1",
                    "deck_id": "deck-b",
                    "slide_number": 1,
                    "target_slide_image": "deck-b/1.png",
                },
            ]
        )

        splits = load_manifest(self.manifest, self.images)
        self.assertEqual((len(splits.train), len(splits.val), len(splits.test)), (1, 1, 0))
        self.assertEqual(splits.train[0].preceding_slide_image, (self.images / "deck-a/1.png").resolve())
        self.assertIsNone(splits.train[0].following_slide_image)
        self.assertEqual(splits.train[0].target_duration_seconds, 30.0)

    def test_rejects_deck_leakage_between_splits(self) -> None:
        self.add_image("deck-a/1.png")
        self.add_image("deck-a/2.png")
        self.write_examples(
            [
                {"split": "train", "example_id": "a-1", "deck_id": "deck-a", "slide_number": 1, "target_slide_image": "deck-a/1.png"},
                {"split": "test", "example_id": "a-2", "deck_id": "deck-a", "slide_number": 2, "target_slide_image": "deck-a/2.png"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "appears in both train and test"):
            load_manifest(self.manifest, self.images)

    def test_rejects_paths_outside_image_root(self) -> None:
        self.write_examples(
            [{"split": "train", "example_id": "escape", "deck_id": "deck-a", "slide_number": 1, "target_slide_image": "../outside.png"}]
        )

        with self.assertRaisesRegex(ValueError, "leaves image_root"):
            load_manifest(self.manifest, self.images)


if __name__ == "__main__":
    unittest.main()
