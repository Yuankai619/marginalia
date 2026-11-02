from types import SimpleNamespace

import numpy as np

from marginalia.align import NONE, _viterbi, candidate_decks, detect_region


def test_detect_region_trims_a_bright_share_to_slide_aspect():
    frames = np.zeros((3, 90, 160), np.uint8)
    frames[:, 20:88, 20:140] = 240

    assert detect_region(frames) == (20, 20, 140, 88)


def test_viterbi_prefers_ordered_slides():
    path = _viterbi(
        np.array([[0.9, 0.1], [0.8, 0.4], [0.4, 0.85], [0.2, 0.9]], np.float32),
        [("deck", 1), ("deck", 2)],
        np.zeros(2, np.float32),
        none_level=0.1,
    )

    assert path.tolist() == [0, 0, 1, 1]


def test_viterbi_does_not_return_to_an_earlier_deck_after_switching():
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


def test_candidate_decks_uses_the_latest_version_available_on_lecture_day():
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

    assert candidate_decks(course, "2026-09-23") == ["l2-process-260923"]
