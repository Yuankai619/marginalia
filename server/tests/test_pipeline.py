from pathlib import Path

from marginalia import pipeline


class FakeCourse:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self._manifest = {
            "decks": [{"id": "deck-one", "rendered": True}, {"id": "deck-two", "rendered": False}],
            "videos": [{"id": "video-one"}, {"id": "video-two"}],
        }

    def manifest(self):
        return self._manifest

    def deck(self, deck):
        return next(item for item in self._manifest["decks"] if item["id"] == deck)

    def deck_dir(self, deck):
        return self.tmp_path / "decks" / deck

    def video_dir(self, video):
        return self.tmp_path / "videos" / video


def test_process_skips_existing_outputs_and_only_transcribes_target_videos(monkeypatch, tmp_path):
    course = FakeCourse(tmp_path)
    course.deck_dir("deck-one").mkdir(parents=True)
    (course.deck_dir("deck-one") / "slides.json").touch()
    course.video_dir("video-one").mkdir(parents=True)
    (course.video_dir("video-one") / "transcript.json").touch()
    rendered, transcribed = [], []

    monkeypatch.setattr(pipeline.ingest, "scan", lambda _: course.manifest())
    monkeypatch.setattr(pipeline.slides, "render_deck", lambda _, deck, __: rendered.append(deck))
    monkeypatch.setattr(
        pipeline.align,
        "align_course",
        lambda *_: {"segments": [{"video": "video-one", "deck": "deck-one"}, {"video": "video-two", "deck": "deck-two"}]},
    )
    monkeypatch.setattr(pipeline.transcribe, "transcribe_video", lambda _, video, __: transcribed.append(video))

    result = pipeline.process(course, ["deck-one"])

    assert rendered == []
    assert transcribed == []
    assert result["decks"] == ["deck-one"]
