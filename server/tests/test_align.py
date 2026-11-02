from types import SimpleNamespace

import numpy as np
import pytest

from marginalia import align
from marginalia.align import NONE, _viterbi, candidate_decks, detect_region


def test_detect_region_trims_a_bright_share_to_slide_aspect():
    frames = np.zeros((3, 90, 160), np.uint8)
    frames[:, 10:88, 20:140] = 240

    assert detect_region(frames, [16 / 9]) == (20, 15, 140, 83)


def test_detect_region_preserves_a_four_by_three_slide_and_its_title():
    frames = np.zeros((3, 216, 384), np.uint8)
    frames[:, 18:198, 72:312] = 240
    frames[:, 23:30, 125:260] = 0

    assert detect_region(frames, [16 / 9, 4 / 3]) == (72, 18, 312, 198)
    assert detect_region(frames) == (72, 18, 312, 198)


def test_similarity_normalizes_title_size_without_using_first_body_line():
    frame = np.full((align.CH, align.CW), 255, np.uint8)
    # A title built from tiny generated strokes, with a different rendered size.
    frame[5:9, 35:40] = 0
    frame[5:9, 50:55] = 0
    frame[8, 35:55] = 0
    correct = np.full_like(frame, 255)
    correct[4:10, 25:33] = 0
    correct[4:10, 49:57] = 0
    correct[9, 25:57] = 0
    correct[16:18, 10:90] = 0
    wrong = frame.copy()
    wrong[3:12] = 255
    wrong[4:10, 25:57] = 0
    wrong[16:18, 10:90] = 0

    scores = align.similarity(align._features(frame[None]), align._features(np.stack([correct, wrong])))

    assert scores[0, 0] > scores[0, 1]


def test_page_number_features_distinguish_identical_titles_during_animation():
    early, late = [np.full((180, 320), 255, np.uint8) for _ in range(2)]
    # 10 and 11, including faint rendered digits.
    for image in (early, late):
        image[4:10, 306] = 197
    early[4:10, 310:314] = 197
    early[5:9, 311:313] = 255
    late[4:10, 312] = 197
    frame = np.full((90, 160), 255, np.uint8)
    frame[2:5, 153] = 0
    frame[2:5, 156] = 0
    crops = np.full((2, align.CH, align.CW), 255, np.uint8)
    slides = align._features(crops, np.stack([align._number_crop(early), align._number_crop(late)]))
    features = align._features(crops[:1], align._number_crop(frame)[None])

    scores = align.similarity(features, slides)

    assert scores[0, 1] > scores[0, 0]


def test_viterbi_prefers_ordered_slides():
    path = _viterbi(
        np.array([[0.9, 0.1], [0.8, 0.4], [0.4, 0.85], [0.2, 0.9]], np.float32),
        [("deck", 1), ("deck", 2)],
        np.zeros(2, np.float32),
        none_level=0.1,
    )

    assert path.tolist() == [0, 0, 1, 1]


def test_viterbi_penalizes_a_brief_false_match_to_another_deck():
    path = _viterbi(
        np.array(
            [[0.95, 0.2, 0.1, 0.1], [0.2, 0.95, 0.1, 0.1], [0.1, 0.2, 0.95, 0.1], [0.1, 0.1, 0.2, 0.95], [0.1, 0.99, 0.2, 0.7]],
            np.float32,
        ),
        [("one", 1), ("one", 2), ("two", 1), ("two", 2)],
        np.zeros(4, np.float32),
        none_level=0.05,
    )

    assert path[-1] == 3
    assert NONE not in path


def test_candidate_decks_keeps_future_versions_and_uses_dates_only_as_a_prior():
    course = SimpleNamespace(
        info=lambda: {"hiddenDecks": []},
        manifest=lambda: {
            "decks": [
                {"id": "l2-process", "date": "2026-09-16", "rendered": True},
                {"id": "l2-process-260923", "date": "2026-09-23", "rendered": True},
                {"id": "l3-memory261007v2", "date": "2026-10-07", "rendered": True},
            ]
        },
    )

    decks = candidate_decks(course, "2026-09-23")
    assert decks == ["l2-process", "l2-process-260923", "l3-memory261007v2"]
    course.deck = lambda name: next(d for d in course.manifest()["decks"] if d["id"] == name)
    prior = align._deck_prior(course, [(d, 1) for d in decks], "2026-09-23")
    assert prior[1] > prior[0] > prior[2]


@pytest.mark.parametrize("blank_frames", [0, 3])
def test_viterbi_can_switch_decks_in_any_order_and_at_any_page(blank_frames):
    keys = [("alpha", 7), ("middle", 1), ("zulu", 4)]
    sim = np.array(
        [[0.1, 0.1, 0.95]] * 4
        + [[0.0, 0.0, 0.0]] * blank_frames
        + [[0.95, 0.1, 0.1]] * 4
        + [[0.1, 0.1, 0.95]] * 4,
        np.float32,
    )

    path = _viterbi(sim, keys, np.zeros(len(keys), np.float32), none_level=0.45)

    assert path.tolist() == [2] * 4 + [NONE] * blank_frames + [0] * 4 + [2] * 4


def test_align_course_skips_a_video_without_frames_and_continues(monkeypatch, course):
    course.save_manifest({
        "decks": [{"id": "deck", "source": "materials/deck.pdf", "rendered": True, "date": "2026-09-16"}],
        "videos": [
            {"id": video, "title": video, "kind": "video", "source": f"materials/{video}.mp4", "date": "2026-09-16"}
            for video in ("empty", "valid")
        ],
    })
    for video in ("empty", "valid"):
        course.source_path(f"materials/{video}.mp4").touch()
    monkeypatch.setattr(
        align.media, "sample_frames",
        lambda source, **_: iter([] if source.stem == "empty" else [(1.0, np.full((90, 160), 240, np.uint8))]),
    )
    crop = np.full((1, align.CH, align.CW), 240, np.uint8)
    monkeypatch.setattr(align, "slide_features", lambda *_: (align._features(crop), [("deck", 1)]))
    monkeypatch.setattr(align, "similarity", lambda *_: np.array([[0.95]], np.float32))

    empty = align.video_crops(course, "empty")
    assert empty["times"].shape == (0,)
    assert empty["crops"].shape == (0, align.CH, align.CW)
    assert empty["boxes"].shape == (0, 4)

    result = align.align_course(course)

    assert [(s["video"], s["deck"], s["slide"]) for s in result["segments"]] == [("valid", "deck", 1)]
    assert course.alignment() == result
