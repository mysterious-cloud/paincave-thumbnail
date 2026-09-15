"""Offline behavior and provider-contract tests; never call a real API."""

import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import anthropic
import httpx
from PIL import Image
from together import Together

SPEC = importlib.util.spec_from_file_location(
    "generate", Path(__file__).parents[1] / "src/generate.py"
)
g = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(g)


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.track = Path(temp.name)
        (self.track / "metadata.json").write_text(
            json.dumps(
                {
                    "title": "Audit",
                    "genres": ["tech-house"],
                    "bpm": 120,
                    "key": "A minor",
                }
            )
        )
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "ANTHROPIC_API_KEY": "audit-placeholder",
                    "TOGETHER_API_KEY": "audit-placeholder",
                },
                clear=True,
            )
        )
        self.enterContext(
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("Network forbidden"),
            )
        )
        self.prompt = self.enterContext(
            patch.object(
                g, "build_prompt", return_value="An amber moon over a cobalt sea"
            )
        )
        self.render = self.enterContext(
            patch.object(
                g, "generate_image", return_value=Image.new("RGB", (512, 512), "red")
            )
        )
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def run_generator(self, **kwargs):
        g.generate(str(self.track), **kwargs)

    def snapshot(self):
        return {name: (self.track / name).read_bytes() for name in g.OUTPUTS}

    def test_fresh_generation_saves_recipe_and_correct_outputs(self):
        self.run_generator(seed=42)
        self.assertEqual(
            {p.name for p in self.track.glob("thumb.*")}
            | {p.name for p in self.track.glob("thumb_*.*")},
            {
                "thumb.avif",
                "thumb_256.avif",
                "thumb_128.avif",
                "thumb_64.avif",
            },
        )
        self.render.assert_called_once()
        for name, size in g.OUTPUTS.items():
            self.assertTrue(g.valid_image(self.track / name, size))
        recipe = g.read_json(self.track / "thumbnail.json")
        self.assertEqual(recipe, g.read_json(self.track / "thumbnail-prompt.json"))
        self.assertEqual(recipe["seed"], 42)
        self.assertEqual(recipe["image_model"], g.DEFAULT_IMAGE_MODEL)
        self.assertEqual(recipe["steps"], 28)

    def test_existing_art_skips_even_with_new_settings_and_no_metadata_or_keys(self):
        self.run_generator()
        before = self.snapshot()
        self.prompt.reset_mock()
        self.render.reset_mock()
        (self.track / "metadata.json").unlink()
        with patch.dict(os.environ, {}, clear=True):
            self.run_generator(seed=99, new_prompt=True)
        self.assertEqual(before, self.snapshot())
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_missing_and_corrupt_derivatives_repair_locally(self):
        self.run_generator()
        before = self.snapshot()
        (self.track / "thumb_128.avif").unlink()
        (self.track / "thumb_64.avif").write_bytes(b"broken")
        self.prompt.reset_mock()
        self.render.reset_mock()
        with patch.dict(os.environ, {}, clear=True):
            self.run_generator()
        self.assertEqual(before["thumb.avif"], (self.track / "thumb.avif").read_bytes())
        self.assertEqual(
            before["thumb_256.avif"], (self.track / "thumb_256.avif").read_bytes()
        )
        self.assertTrue(g.valid_image(self.track / "thumb_128.avif", 128))
        self.assertTrue(g.valid_image(self.track / "thumb_64.avif", 64))
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_invalid_master_requires_explicit_regeneration(self):
        (self.track / "thumb.avif").write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "--regenerate"):
            self.run_generator()
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_wrong_codec_with_avif_extension_is_repaired(self):
        self.run_generator()
        png = io.BytesIO()
        Image.new("RGB", (128, 128), "red").save(png, "PNG")
        (self.track / "thumb_128.avif").write_bytes(png.getvalue())
        self.assertFalse(g.valid_image(self.track / "thumb_128.avif", 128))
        self.render.reset_mock()
        self.run_generator()
        self.assertTrue(g.valid_image(self.track / "thumb_128.avif", 128))
        self.render.assert_not_called()

    def test_missing_avif_codec_fails_before_spending(self):
        with patch.object(
            g.features, "check", side_effect=lambda codec: codec != "avif"
        ):
            with self.assertRaisesRegex(ValueError, "AVIF support"):
                self.run_generator()
            self.run_generator(prompt_only=True)
        self.render.assert_not_called()
        self.prompt.assert_called_once()  # Prompt-only remains usable without image codecs.

    def test_prompt_only_is_saved_and_reused_for_generation(self):
        os.environ.pop("TOGETHER_API_KEY")
        self.run_generator(prompt_only=True, seed=42)
        self.render.assert_not_called()
        os.environ["TOGETHER_API_KEY"] = "audit-placeholder"
        os.environ.pop("ANTHROPIC_API_KEY")
        self.run_generator()
        self.prompt.assert_called_once()
        self.assertEqual(self.render.call_args.args[0]["seed"], 42)

    def test_cached_prompt_only_needs_no_keys(self):
        self.run_generator(prompt_only=True)
        with patch.dict(os.environ, {}, clear=True):
            self.run_generator(prompt_only=True)
        self.prompt.assert_called_once()
        self.render.assert_not_called()

    def test_failed_render_retry_preserves_prompt_seed_and_settings(self):
        self.render.side_effect = ValueError("image request failed")
        with self.assertRaisesRegex(ValueError, "image request failed"):
            self.run_generator(seed=123, steps=9)
        original = self.render.call_args.args[0]
        self.render.side_effect = None
        os.environ.pop("ANTHROPIC_API_KEY")
        self.run_generator()
        self.prompt.assert_called_once()
        self.assertEqual(original, self.render.call_args.args[0])

    def test_regenerate_reuses_prompt_and_accepts_seed_override(self):
        self.run_generator(seed=42)
        self.render.return_value = Image.new("RGB", (512, 512), "blue")
        before = self.snapshot()
        self.run_generator(regenerate=True, seed=77)
        self.prompt.assert_called_once()
        self.assertNotEqual(before["thumb.avif"], self.snapshot()["thumb.avif"])
        self.assertEqual(self.render.call_args.args[0]["seed"], 77)

    def test_explicit_new_prompt_replaces_cached_prompt(self):
        self.run_generator(prompt_only=True)
        self.prompt.return_value = "A floating arch"
        self.run_generator(prompt_only=True, new_prompt=True)
        self.assertEqual(self.prompt.call_count, 2)
        self.assertEqual(
            g.read_json(self.track / "thumbnail-prompt.json")["prompt"],
            "A floating arch",
        )

    def test_supplied_prompt_and_json_recipe_skip_claude(self):
        for filename, text in (
            ("prompt.txt", "A floating arch"),
            ("recipe.json", json.dumps({"prompt": "A floating arch", "seed": 45})),
        ):
            with self.subTest(filename=filename):
                path = self.track / filename
                path.write_text(text)
                self.run_generator(prompt_only=True, prompt_file=path)
                self.assertEqual(
                    g.read_json(self.track / "thumbnail-prompt.json")["prompt"],
                    "A floating arch",
                )
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_model_override_does_not_reuse_other_models_steps(self):
        self.run_generator(prompt_only=True)
        os.environ["IMAGE_MODEL"] = "another/model"
        self.run_generator()
        recipe = self.render.call_args.args[0]
        self.assertEqual(recipe["image_model"], "another/model")
        self.assertIsNone(recipe["steps"])
        self.prompt.assert_called_once()

    def test_missing_image_key_fails_before_claude(self):
        os.environ.pop("TOGETHER_API_KEY")
        with self.assertRaisesRegex(ValueError, "TOGETHER_API_KEY"):
            self.run_generator()
        self.prompt.assert_not_called()

    def test_retired_model_fails_before_claude(self):
        os.environ["IMAGE_MODEL"] = "black-forest-labs/FLUX.1-schnell"
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.run_generator()
        self.prompt.assert_not_called()

    def test_invalid_inputs_do_not_spend(self):
        for metadata in ("[]", '{"genres": "house"}', "not JSON"):
            with self.subTest(metadata=metadata):
                (self.track / "metadata.json").write_text(metadata)
                with self.assertRaises(ValueError):
                    self.run_generator()
        for record in (
            {},
            {"prompt": ""},
            {"prompt": "Moon", "seed": -1},
            {"prompt": "Moon", "steps": 0},
            {"prompt": "Moon", "version": 99},
        ):
            with self.subTest(record=record):
                (self.track / "thumbnail-prompt.json").write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    self.run_generator()
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_concurrent_writer_is_refused_before_spending(self):
        with g.track_lock(self.track):
            with self.assertRaisesRegex(ValueError, "already running"):
                self.run_generator()
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_encoding_failure_preserves_all_active_files(self):
        self.run_generator()
        before = self.snapshot()
        old_recipe = (self.track / "thumbnail.json").read_bytes()
        save = Image.Image.save

        def fail(image, path, *args, **kwargs):
            if Path(path).name == "thumb_128.avif":
                raise OSError("disk failure")
            return save(image, path, *args, **kwargs)

        self.render.return_value = Image.new("RGB", (512, 512), "blue")
        with patch.object(Image.Image, "save", fail):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.run_generator(regenerate=True)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(old_recipe, (self.track / "thumbnail.json").read_bytes())

    def test_interrupted_publication_recovers_without_api_calls(self):
        self.run_generator()
        self.render.return_value = Image.new("RGB", (512, 512), "blue")
        write = g.atomic_write

        def fail(path, data):
            if path.name == "thumb_128.avif":
                raise OSError("interrupted promotion")
            return write(path, data)

        with patch.object(g, "atomic_write", fail):
            with self.assertRaisesRegex(OSError, "interrupted promotion"):
                self.run_generator(regenerate=True, seed=77)
        expected = {
            name: (self.track / ".thumbnail-stage" / name).read_bytes()
            for name in g.OUTPUTS
        }
        self.prompt.reset_mock()
        self.render.reset_mock()
        with patch.dict(os.environ, {}, clear=True):
            self.run_generator()
        self.assertEqual(expected, self.snapshot())
        self.assertEqual(g.read_json(self.track / "thumbnail.json")["seed"], 77)
        self.assertFalse((self.track / ".thumbnail-stage").exists())
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_invalid_staged_batch_does_not_change_active_art(self):
        self.run_generator()
        before = self.snapshot()
        stage = self.track / ".thumbnail-stage"
        stage.mkdir()
        (stage / "batch.json").write_text(
            json.dumps({"outputs": {"thumb.avif": "invalid"}})
        )
        self.prompt.reset_mock()
        self.render.reset_mock()
        with self.assertRaisesRegex(ValueError, "Invalid staged"):
            self.run_generator()
        self.assertEqual(before, self.snapshot())
        self.prompt.assert_not_called()
        self.render.assert_not_called()

    def test_cli_rejects_bad_seed_without_spending(self):
        with patch.object(
            g.sys, "argv", ["generate.py", str(self.track), "--seed", "-1"]
        ):
            with self.assertRaises(SystemExit) as error:
                g.main()
        self.assertEqual(error.exception.code, 2)
        self.prompt.assert_not_called()
        self.render.assert_not_called()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("Network forbidden"),
            )
        )
        self.recipe = {
            "prompt": "A moon",
            "image_model": g.DEFAULT_IMAGE_MODEL,
            "seed": 42,
            "steps": 28,
        }

    def image_response(self, data, requests):
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={"id": "audit", "model": "audit", "object": "list", "data": data},
            )

        client = Together(
            api_key="audit-placeholder",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with patch.object(g, "Together", return_value=client):
            return g.generate_image(self.recipe)

    def test_together_wire_contract_and_image_decode(self):
        buf = io.BytesIO()
        Image.new("RGB", (512, 512), "blue").save(buf, "PNG")
        requests = []
        result = self.image_response(
            [
                {
                    "index": 0,
                    "type": "b64_json",
                    "b64_json": base64.b64encode(buf.getvalue()).decode(),
                }
            ],
            requests,
        )
        self.assertEqual(result.size, (512, 512))
        self.assertEqual(
            requests,
            [
                {
                    "prompt": "A moon",
                    "model": g.DEFAULT_IMAGE_MODEL,
                    "seed": 42,
                    "steps": 28,
                    "width": 512,
                    "height": 512,
                    "n": 1,
                    "response_format": "base64",
                    "output_format": "png",
                }
            ],
        )

    def test_image_server_error_is_not_automatically_resubmitted(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(500, json={"error": {"message": "temporary failure"}})

        def client_factory(**kwargs):
            return Together(
                api_key="audit-placeholder",
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                **kwargs,
            )

        with patch.object(g, "Together", side_effect=client_factory):
            with self.assertRaises(g.TogetherError):
                g.generate_image(self.recipe)
        self.assertEqual(len(requests), 1)

    def test_invalid_image_responses_are_rejected(self):
        buf = io.BytesIO()
        Image.new("RGB", (768, 512)).save(buf, "PNG")
        cases = [
            None,
            [],
            [{"index": 0, "type": "url", "url": "https://example.com/image.png"}],
        ]
        for content in (
            "%%%",
            base64.b64encode(b"not an image").decode(),
            base64.b64encode(buf.getvalue()).decode(),
        ):
            cases.append([{"index": 0, "type": "b64_json", "b64_json": content}])
        for data in cases:
            with self.subTest(data=str(data)[:80]), self.assertRaises(ValueError):
                self.image_response(data, [])

    def test_anthropic_receives_genres_and_rejects_truncation(self):
        requests = []
        for stop in ("end_turn", "max_tokens"):

            def handler(request):
                requests.append(json.loads(request.content))
                return httpx.Response(
                    200,
                    json={
                        "id": "msg_audit",
                        "model": "claude-haiku-4-5",
                        "role": "assistant",
                        "type": "message",
                        "content": [{"type": "text", "text": "A floating moon"}],
                        "stop_reason": stop,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    },
                )

            client = anthropic.Anthropic(
                api_key="audit-placeholder",
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
            with (
                patch.dict(
                    os.environ, {"ANTHROPIC_API_KEY": "audit-placeholder"}, clear=True
                ),
                patch.object(g.anthropic, "Anthropic", return_value=client),
            ):
                if stop == "end_turn":
                    self.assertEqual(
                        g.build_prompt({"title": "Audit", "genres": ["tech-house"]}),
                        "A floating moon",
                    )
                else:
                    with self.assertRaisesRegex(ValueError, "did not finish"):
                        g.build_prompt({"title": "Audit", "genres": ["tech-house"]})
        self.assertEqual(
            json.loads(requests[0]["messages"][0]["content"])["genres"], ["tech-house"]
        )


if __name__ == "__main__":
    unittest.main()
