from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaggle_runner_run", ROOT / "kaggle_runner" / "run.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class KaggleRunnerHelperTests(unittest.TestCase):
    @staticmethod
    def campaign_job(strategy: str, count: int = 5) -> dict:
        reels = [
            {
                "index": index,
                "flux_prompt": f"still {index}",
                "ltx_motion_prompt": f"motion {index}",
                "seed": 100 + index,
                "animate": index in {0, 2, 4},
                "motion_source_index": 0,
            }
            for index in range(count)
        ]
        return {
            "mode": "generate_still",
            "strategy": strategy,
            "campaign": {"strategy": strategy, "reels": reels},
        }

    def test_legal_dimensions_are_bounded_multiples_of_32(self) -> None:
        width, height = runner.legal_dimensions(768, 432)
        self.assertEqual((width % 32, height % 32), (0, 0))
        self.assertLessEqual(width * height, runner.MAX_PIXELS)
        self.assertAlmostEqual(width / height, 16 / 9, delta=0.1)

    def test_legal_dimensions_handles_bad_values(self) -> None:
        self.assertEqual(runner.legal_dimensions("bad", None), (704, 480))

    def test_legal_frames(self) -> None:
        self.assertEqual(runner.legal_frames(81), 81)
        self.assertEqual(runner.legal_frames(80), 73)
        self.assertEqual(runner.legal_frames(999), 81)
        self.assertEqual(runner.legal_frames(None), 49)

    def test_retry_settings_are_legal_and_progressively_cheaper(self) -> None:
        attempts = runner.retry_settings(704, 480, 81)
        self.assertGreaterEqual(len(attempts), 2)
        costs = []
        for width, height, frames in attempts:
            self.assertEqual(width % 32, 0)
            self.assertEqual(height % 32, 0)
            self.assertEqual((frames - 1) % 8, 0)
            costs.append(width * height * frames)
        self.assertEqual(costs, sorted(costs, reverse=True))

    def test_find_asset_rejects_traversal(self) -> None:
        with self.assertRaises(ValueError):
            runner.find_asset(Path("/tmp"), "../secret", required=True)

    def test_find_job_reads_nested_dataset(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            dataset = root / "mounted-dataset"
            dataset.mkdir()
            (dataset / "job.json").write_text(
                json.dumps({"id": "job-1"}), encoding="utf-8"
            )
            with patch.object(runner, "INPUT_DIR", root):
                found_dir, job = runner.find_job()
            self.assertEqual(found_dir, dataset)
            self.assertEqual(job["id"], "job-1")

    def test_find_job_rejects_ambiguous_or_invalid_manifests(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "job.json").write_text("[]", encoding="utf-8")
            (root / "two" / "job.json").write_text("{bad", encoding="utf-8")
            with patch.object(runner, "INPUT_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "exactly one valid"):
                    runner.find_job()

            (root / "one" / "job.json").write_text('{"id":"one"}', encoding="utf-8")
            (root / "two" / "job.json").write_text('{"id":"two"}', encoding="utf-8")
            with patch.object(runner, "INPUT_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "found 2"):
                    runner.find_job()

    def test_find_asset_handles_required_optional_and_ambiguous_files(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertIsNone(runner.find_asset(root, None, required=False))
            with self.assertRaises(ValueError):
                runner.find_asset(root, None, required=True)
            (root / "nested").mkdir()
            asset = root / "nested" / "source.png"
            asset.write_bytes(b"png")
            self.assertEqual(
                runner.find_asset(root, "source.png", required=True), asset
            )
            (root / "other").mkdir()
            (root / "other" / "source.png").write_bytes(b"png")
            with self.assertRaisesRegex(FileNotFoundError, "found 2"):
                runner.find_asset(root, "source.png", required=True)

    def test_atomic_json_replaces_file_and_serializes_values(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "manifest.json"
            runner.atomic_json(path, {"status": "running", "path": Path("/tmp/out")})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"path": "/tmp/out", "status": "running"},
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_validate_job_requires_supported_mode_and_prompt(self) -> None:
        runner.validate_job({"mode": "generate_still", "prompt": "product"})
        with self.assertRaisesRegex(ValueError, "mode"):
            runner.validate_job({"mode": "unknown", "prompt": "product"})
        with self.assertRaisesRegex(ValueError, "prompt"):
            runner.validate_job({"mode": "uploaded_image", "prompt": " "})

    def test_safe_error_redacts_tokens(self) -> None:
        message = runner.safe_error(
            RuntimeError("token=hf_abcdefghijklmnopqrstuvwxyz api_key=secret")
        )
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", message)
        self.assertNotIn("secret", message)

    def test_scenes_become_the_consecutive_shots_of_one_reel(self) -> None:
        plan = runner.plan_batch(self.campaign_job("credit_saver"))
        shots = runner.planned_shots(plan)
        self.assertEqual(len(shots), 3)
        self.assertEqual([shot["reel_index"] for shot in shots], [0, 1, 2])
        self.assertEqual(len({shot["prompt"] for shot in shots}), 3)
        self.assertEqual(
            runner.planned_model_load_counts(self.campaign_job("credit_saver")),
            {"flux": 1, "ltx_image_to_video": 1},
        )

    def test_credit_modes_buy_shots_for_the_same_single_reel(self) -> None:
        counts = {
            strategy: len(
                runner.planned_shots(runner.plan_batch(self.campaign_job(strategy)))
            )
            for strategy in ("credit_saver", "balanced", "unique_visuals")
        }
        self.assertEqual(counts, {"credit_saver": 3, "balanced": 4, "unique_visuals": 6})
        self.assertLessEqual(max(counts.values()), runner.MAX_REEL_SHOTS)

        shots = runner.planned_shots(runner.plan_batch(self.campaign_job("unique_visuals")))
        # Six shots over five scenes wraps around, reseeded so it is not a repeat.
        self.assertEqual([shot["reel_index"] for shot in shots], [0, 1, 2, 3, 4, 0])
        self.assertNotEqual(shots[0]["seed"], shots[5]["seed"])

        with self.assertRaisesRegex(ValueError, "strategy"):
            runner.plan_batch(self.campaign_job("bargain_bin"))

    def test_uploaded_campaign_skips_flux_load(self) -> None:
        job = self.campaign_job("credit_saver", count=3)
        job["mode"] = "uploaded_image"
        self.assertEqual(
            runner.planned_model_load_counts(job),
            {"flux": 0, "ltx_image_to_video": 1},
        )

    def test_campaign_json_and_top_level_reels_are_supported(self) -> None:
        job = self.campaign_job("credit_saver", count=3)
        campaign = job.pop("campaign")
        job["campaign_json"] = json.dumps(campaign)
        self.assertEqual(len(runner.plan_batch(job)["reels"]), 3)

        job.pop("campaign_json")
        job["reels"] = campaign["reels"]
        self.assertEqual(len(runner.plan_batch(job)["reels"]), 3)

    def test_campaign_hard_limit_and_legacy_compatibility(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 3 and 5"):
            runner.plan_batch(self.campaign_job("credit_saver", count=2))

        legacy = {
            "mode": "uploaded_image",
            "prompt": "legacy product",
            "seed": 9,
        }
        plan = runner.plan_batch(legacy)
        self.assertTrue(plan["legacy"])
        self.assertEqual(plan["reels"][0]["prompt"], "legacy product")
        self.assertEqual(len(runner.planned_shots(plan)), 1)

    def test_crossfade_overlaps_shots_instead_of_cutting_between_them(self) -> None:
        from PIL import Image

        black = [Image.new("RGB", (8, 8), (0, 0, 0)) for _ in range(10)]
        white = [Image.new("RGB", (8, 8), (255, 255, 255)) for _ in range(10)]
        joined = runner.join_shots_with_crossfade([black, white], overlap=4)
        # The overlap is consumed from both shots, so the reel gets shorter.
        self.assertEqual(len(joined), 16)
        middle = [frame.getpixel((0, 0))[0] for frame in joined[6:10]]
        self.assertEqual(middle, sorted(middle))
        self.assertTrue(0 < middle[0] < middle[-1] < 255)
        self.assertEqual(joined[0].getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(joined[-1].getpixel((0, 0)), (255, 255, 255))

    def test_crossfade_keeps_a_single_shot_untouched(self) -> None:
        from PIL import Image

        frames = [Image.new("RGB", (4, 4), (7, 7, 7)) for _ in range(5)]
        self.assertEqual(len(runner.join_shots_with_crossfade([frames])), 5)
        with self.assertRaises(ValueError):
            runner.join_shots_with_crossfade([[]])

    def test_voice_mapping_accepts_only_known_indian_voices(self) -> None:
        self.assertEqual(runner.resolve_voice("female_hindi", "hindi"), "hi-IN-SwaraNeural")
        self.assertEqual(runner.resolve_voice("male_english", "english"), "en-IN-PrabhatNeural")
        self.assertEqual(
            runner.resolve_voice("arbitrary; rm -rf /", "english"),
            "en-IN-NeerjaNeural",
        )
        self.assertIn(
            runner.resolve_voice("hi-IN-MadhurNeural", "bilingual"),
            runner.KNOWN_EDGE_VOICES,
        )

    def test_srt_timing_is_unicode_and_non_overlapping(self) -> None:
        text = runner.build_srt(["गरमा गरम बिरयानी", "Order now — अभी"], 6.0)
        self.assertIn("गरमा गरम बिरयानी", text)
        self.assertIn("00:00:00,000 -->", text)
        self.assertIn("00:00:06,000", text)
        blocks = text.strip().split("\n\n")
        self.assertEqual(len(blocks), 2)
        first_end = blocks[0].splitlines()[1].split(" --> ")[1]
        second_start = blocks[1].splitlines()[1].split(" --> ")[0]
        self.assertEqual(first_end, second_start)

    def test_ffmpeg_args_are_list_based_vertical_h264_and_safe(self) -> None:
        root = Path("/tmp/a path:with'quotes")
        args = runner.build_reel_ffmpeg_args(
            "/usr/bin/ffmpeg",
            video=root / "source.mp4",
            end_card=root / "end.png",
            watermark=root / "mark.png",
            output=root / "final.mp4",
            content_duration=8.0,
            voice=root / "voice.mp3",
            music=root / "music.mp3",
            total_duration=10.5,
        )
        self.assertIsInstance(args, list)
        self.assertIn("libx264", args)
        self.assertIn("yuv420p", args)
        filter_graph = args[args.index("-filter_complex") + 1]
        self.assertIn("scale=1080:1920", filter_graph)
        self.assertIn("flags=lanczos", filter_graph)
        self.assertIn("acompressor=", filter_graph)
        self.assertIn("loudnorm=I=-16", filter_graph)
        self.assertIn("amix=inputs=2:duration=longest,", filter_graph)
        self.assertNotIn("rm -rf", filter_graph)
        self.assertEqual(args[-1], str(root / "final.mp4"))

    def test_only_the_brand_mark_is_drawn_over_the_footage(self) -> None:
        root = Path("/tmp/reel")
        common = {
            "video": root / "source.mp4",
            "end_card": root / "end.png",
            "output": root / "final.mp4",
            "content_duration": 9.0,
            "voice": None,
            "music": None,
            "total_duration": 11.5,
        }
        branded = runner.build_reel_ffmpeg_args(
            "/usr/bin/ffmpeg", watermark=root / "mark.png", **common
        )
        graph = branded[branded.index("-filter_complex") + 1]
        self.assertNotIn("subtitles=", graph)
        self.assertNotIn("drawtext", graph)
        self.assertIn("overlay=W-w-54:H-h-54", graph)
        self.assertIn("[branded][end]concat=n=2:v=1:a=0[vout]", graph)

        bare = runner.build_reel_ffmpeg_args("/usr/bin/ffmpeg", watermark=None, **common)
        bare_graph = bare[bare.index("-filter_complex") + 1]
        self.assertNotIn("overlay=", bare_graph)
        self.assertIn("[content][end]concat=n=2:v=1:a=0[vout]", bare_graph)

    def test_brand_block_comes_from_campaign_variables(self) -> None:
        brand = runner.brand_identity(
            {"app_name": "Zayka Now", "platforms": "Android & iOS", "cta_url": "zayka.app"}
        )
        self.assertEqual(brand["name"], "Zayka Now")
        self.assertEqual(brand["platforms"], "Available for Android & iOS")
        self.assertEqual(brand["kind"], runner.DEFAULT_APP_KIND)
        self.assertEqual(brand["url"], "zayka.app")

        fallback = runner.brand_identity({"app_name": "  "})
        self.assertEqual(fallback["name"], "Aonla Online")
        self.assertEqual(
            fallback["platforms"], f"Available for {runner.DEFAULT_PLATFORMS}"
        )
        self.assertEqual(fallback["url"], "")

    def test_only_the_hook_and_cta_are_spoken(self) -> None:
        reel = {
            "hook": "Aonla ki nayi pizza night",
            "narration": "A much longer paragraph that would overrun a short reel.",
            "cta": "Order now on Aonla Online",
        }
        self.assertEqual(
            runner.reel_voice_lines(reel),
            ["Aonla ki nayi pizza night", "Order now on Aonla Online"],
        )
        self.assertEqual(runner.reel_voice_lines({"narration": "only body"}), ["only body"])

    def _system_font(self, *names: str) -> Path | None:
        for name in names or ("*.ttf",):
            for root in runner.SYSTEM_FONT_DIRS:
                matches = sorted(root.rglob(name)) if root.is_dir() else []
                if matches:
                    return matches[0]
        return None

    def test_latin_wording_never_uses_a_devanagari_only_font(self) -> None:
        devanagari = self._system_font("*Devanagari*.ttf")
        latin = self._system_font(*runner.LATIN_FONT_NAMES)
        if devanagari is None or latin is None:
            self.skipTest("Both a Devanagari and a Latin system font are required.")
        # Noto Sans Devanagari has no Latin glyphs, so "Aonla Online" drew boxes.
        self.assertEqual(runner.font_for("Aonla Online", [devanagari, latin]), latin)
        self.assertEqual(runner.font_for("आन्ला ऑनलाइन", [latin, devanagari]), devanagari)

    def test_font_choice_falls_back_to_script_when_unmeasurable(self) -> None:
        latin = Path("/fonts/DejaVuSans.ttf")
        devanagari = Path("/fonts/NotoSansDevanagari-Regular.ttf")
        with patch.object(runner, "_font_covers", return_value=None):
            self.assertEqual(runner.font_for("Aonla", [devanagari, latin]), latin)
            self.assertEqual(runner.font_for("आन्ला", [latin, devanagari]), devanagari)
        with self.assertRaises(ValueError):
            runner.font_for("Aonla", [])

    def test_brand_assets_render_at_delivery_size(self) -> None:
        from PIL import Image

        font = self._system_font()
        if font is None:
            self.skipTest("No system TrueType font is available to render brand assets.")
        fonts = [font]
        brand = runner.brand_identity({"app_name": "Aonla Online"})
        with TemporaryDirectory() as raw:
            root = Path(raw)
            end_card = root / "end.png"
            runner.create_end_card(end_card, fonts, brand)
            with Image.open(end_card) as opened:
                self.assertEqual(opened.size, (runner.FINAL_WIDTH, runner.FINAL_HEIGHT))

            thumbnail = root / "reel_001.thumb.jpg"
            runner.create_thumbnail(
                thumbnail, fonts, brand, hero=Image.new("RGB", (480, 704), (30, 90, 60))
            )
            with Image.open(thumbnail) as opened:
                self.assertEqual(opened.format, "JPEG")
                self.assertEqual(opened.size, (runner.FINAL_WIDTH, runner.FINAL_HEIGHT))

            mark = runner.create_watermark(root / "mark.png", fonts, brand)
            with Image.open(mark) as opened:
                self.assertEqual(opened.mode, "RGBA")
                self.assertLess(opened.width, runner.FINAL_WIDTH // 2)

    def test_ffmpeg_audio_graph_stays_compatible_with_ffmpeg_4_2(self) -> None:
        root = Path("/tmp/reel")
        common = {
            "video": root / "source.mp4",
            "end_card": root / "end.png",
            "watermark": root / "mark.png",
            "output": root / "final.mp4",
            "content_duration": 8.0,
            "total_duration": 10.5,
        }
        for voice, music in (
            (root / "voice.mp3", root / "music.mp3"),
            (root / "voice.mp3", None),
            (None, root / "music.mp3"),
            (None, None),
        ):
            args = runner.build_reel_ffmpeg_args(
                "/usr/bin/ffmpeg", voice=voice, music=music, **common
            )
            filter_graph = args[args.index("-filter_complex") + 1]
            # `normalize` was added to amix in ffmpeg 4.4; imageio-ffmpeg ships 4.2.2.
            self.assertNotIn("normalize", filter_graph)
            self.assertNotIn("amix=inputs=1", filter_graph)
            self.assertIn("[aout]", filter_graph)

    def test_narration_fallback_paths(self) -> None:
        uploaded = Path("/safe/voice.mp3")
        self.assertEqual(runner.narration_fallback(True, uploaded), ("edge_tts", None))
        source, warning = runner.narration_fallback(False, uploaded)
        self.assertEqual(source, "uploaded_voice_over")
        self.assertIn("uploaded voice-over", warning or "")
        source, warning = runner.narration_fallback(False, None)
        self.assertEqual(source, "captions_music_only")
        self.assertIn("music only", warning or "")

    def test_gated_still_model_falls_back_when_unauthenticated(self) -> None:
        model, warning = runner.resolve_still_model(runner.FLUX_MODEL, False)
        self.assertEqual(model, runner.FALLBACK_STILL_MODEL)
        assert warning is not None
        self.assertIn("gated", warning)
        self.assertIn(runner.HF_SECRET_LABEL, warning)

    def test_gated_still_model_is_kept_when_a_token_is_present(self) -> None:
        self.assertEqual(
            runner.resolve_still_model(runner.FLUX_MODEL, True),
            (runner.FLUX_MODEL, None),
        )

    def test_open_still_model_never_warns(self) -> None:
        self.assertEqual(
            runner.resolve_still_model(runner.FALLBACK_STILL_MODEL, False),
            (runner.FALLBACK_STILL_MODEL, None),
        )

    def test_still_call_kwargs_match_the_model_family(self) -> None:
        flux = runner.still_call_kwargs(runner.FLUX_MODEL)
        self.assertEqual(flux["max_sequence_length"], 256)
        turbo = runner.still_call_kwargs(runner.SDXL_TURBO_MODEL)
        quality = runner.still_call_kwargs(runner.SDXL_QUALITY_MODEL)
        self.assertEqual(turbo["num_inference_steps"], 4)
        self.assertEqual(turbo["guidance_scale"], 0.0)
        self.assertEqual(quality["num_inference_steps"], 24)
        self.assertEqual(quality["guidance_scale"], 7.0)
        self.assertNotIn("max_sequence_length", quality)

    def test_clip_prompt_keeps_the_scenario_detail_it_cannot_fit(self) -> None:
        prompt = (
            "photorealistic vertical 9:16 food commercial still, appetizing evening light, "
            "steam and texture, shallow depth of field, no text, no watermark, no logo. "
            "overhead pepperoni and basil, steam, no text"
        )
        fitted = runner.fit_still_prompt(prompt, lambda text: len(text.split()) <= 14)
        self.assertTrue(len(fitted.split()) <= 14)
        self.assertTrue(fitted.endswith("overhead pepperoni and basil, steam, no text"))
        self.assertTrue(fitted.startswith("photorealistic vertical 9:16"))
        self.assertNotIn("shallow depth of field", fitted)

    def test_prompt_that_already_fits_is_untouched(self) -> None:
        prompt = "hero plate of biryani, steam"
        self.assertEqual(runner.fit_still_prompt(prompt, lambda _text: True), prompt)

    def test_single_overlong_clause_is_trimmed_word_by_word(self) -> None:
        prompt = "one two three four five six"
        fitted = runner.fit_still_prompt(prompt, lambda text: len(text.split()) <= 3)
        self.assertEqual(fitted, "one two three")

    @staticmethod
    def fake_pipe() -> object:
        class Tokenizer:
            model_max_length = 77

            def __call__(self, text: str, verbose: bool = True):
                assert verbose is False
                return type("Encoded", (), {"input_ids": text.split()})()

        class T5Tokenizer(Tokenizer):
            model_max_length = 512

        class Pipe:
            tokenizer = Tokenizer()
            tokenizer_2 = T5Tokenizer()

        return Pipe()

    def test_clip_budget_counts_tokens_of_every_clip_tower(self) -> None:
        fits = runner.clip_prompt_fits(self.fake_pipe(), runner.FALLBACK_STILL_MODEL)
        self.assertTrue(fits(" ".join(["token"] * 77)))
        self.assertFalse(fits(" ".join(["token"] * 78)))

    def test_flux_keeps_the_full_prompt_on_its_t5_encoder(self) -> None:
        prompt = " ".join(["token"] * 90)
        clip_prompt, t5_prompt = runner.still_prompt_pair(
            self.fake_pipe(), runner.FLUX_MODEL, prompt
        )
        # FLUX's CLIP tower still truncates at 77, so only its copy is shortened.
        self.assertEqual(len(clip_prompt.split()), 77)
        self.assertEqual(t5_prompt, prompt)

    def test_open_model_has_no_second_encoder_to_fall_back_on(self) -> None:
        prompt = " ".join(["token"] * 90)
        clip_prompt, t5_prompt = runner.still_prompt_pair(
            self.fake_pipe(), runner.FALLBACK_STILL_MODEL, prompt
        )
        self.assertEqual(len(clip_prompt.split()), 77)
        self.assertIsNone(t5_prompt)

    def test_open_models_render_at_their_useful_native_density(self) -> None:
        self.assertEqual(runner.native_still_size(runner.FLUX_MODEL, 704, 480), (704, 480))
        width, height = runner.native_still_size(runner.FALLBACK_STILL_MODEL, 704, 480)
        self.assertEqual(height, 512)
        self.assertEqual(width % 8, 0)
        self.assertAlmostEqual(width / height, 704 / 480, places=1)
        quality_width, quality_height = runner.native_still_size(
            runner.SDXL_QUALITY_MODEL, 480, 704
        )
        self.assertEqual(quality_width, 768)
        self.assertEqual(quality_height % 8, 0)
        self.assertAlmostEqual(quality_width / quality_height, 480 / 704, places=2)
        self.assertEqual(
            runner.native_still_size(runner.FALLBACK_STILL_MODEL, 1024, 768), (1024, 768)
        )

    def test_environment_token_is_used_when_no_kaggle_secret_exists(self) -> None:
        with patch.dict("os.environ", {"HF_TOKEN": " hf_abc "}, clear=False):
            self.assertTrue(runner.configure_huggingface_auth())
            self.assertEqual(runner.huggingface_token(), "hf_abc")

    def test_missing_token_reports_unauthenticated(self) -> None:
        with patch.dict(
            "os.environ",
            {"HF_TOKEN": "", "HUGGING_FACE_HUB_TOKEN": "", "HUGGINGFACE_TOKEN": ""},
            clear=False,
        ):
            self.assertFalse(runner.configure_huggingface_auth())

    def test_caption_font_downloads_from_the_first_working_mirror(self) -> None:
        valid = b"\x00\x01\x00\x00" + b"font"

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read(_size: int) -> bytes:
                return valid

        calls: list[str] = []

        def urlopen(url: str, timeout: int = 0):
            calls.append(url)
            if len(calls) == 1:
                raise OSError("404")
            return Response()

        with patch("urllib.request.urlopen", urlopen):
            self.assertEqual(runner.download_caption_font(), valid)
        self.assertEqual(calls, list(runner.FONT_DOWNLOAD_URLS[:2]))

    def test_caption_font_reports_every_mirror_it_tried(self) -> None:
        def urlopen(url: str, timeout: int = 0):
            raise OSError("HTTP Error 404: Not Found")

        with patch("urllib.request.urlopen", urlopen):
            with self.assertRaises(RuntimeError) as caught:
                runner.download_caption_font()
        self.assertIn("404", str(caught.exception))
        for url in runner.FONT_DOWNLOAD_URLS:
            self.assertIn(url, str(caught.exception))

    def test_missing_devanagari_font_degrades_instead_of_failing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            substitute = root / "DejaVuSans.ttf"
            substitute.write_bytes(b"\x00\x01\x00\x00")

            def discover(_dir: Path) -> Path:
                raise RuntimeError("no mirror reachable")

            with patch.object(runner, "discover_devanagari_font", discover):
                with patch.object(runner, "SYSTEM_FONT_DIRS", (root,)):
                    fonts, warning = runner.prepare_brand_fonts(root / "fonts")

            self.assertEqual(fonts, [substitute])
            assert warning is not None
            self.assertIn("Hindi wording", warning)

    def test_font_failure_propagates_when_no_substitute_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            def discover(_dir: Path) -> Path:
                raise RuntimeError("no mirror reachable")

            with patch.object(runner, "discover_devanagari_font", discover):
                with patch.object(runner, "SYSTEM_FONT_DIRS", (root,)):
                    with patch.object(runner, "discover_latin_font", lambda: None):
                        with self.assertRaises(RuntimeError):
                            runner.prepare_brand_fonts(root / "fonts")

    def test_both_scripts_get_a_font_when_available(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            latin = root / "DejaVuSans.ttf"
            devanagari = root / "NotoSansDevanagari-Regular.ttf"
            for path in (latin, devanagari):
                path.write_bytes(b"\x00\x01\x00\x00")

            with patch.object(runner, "discover_latin_font", lambda: latin):
                with patch.object(runner, "discover_devanagari_font", lambda _dir: devanagari):
                    fonts, warning = runner.prepare_brand_fonts(root / "fonts")

            self.assertEqual(fonts, [latin, devanagari])
            self.assertIsNone(warning)

    def test_bilingual_script_retains_both_languages(self) -> None:
        script = runner.reel_script(
            {"narration": "आज ऑर्डर करें।", "companion_narration": "Order today."}
        )
        self.assertEqual(script, "आज ऑर्डर करें।\n\nOrder today.")


if __name__ == "__main__":
    unittest.main()
