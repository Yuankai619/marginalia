"""Command-line entry points for local course processing."""

from __future__ import annotations

import argparse

from . import align, ingest, pipeline, slides, transcribe
from .store import Course


def _progress(_: float, message: str) -> None:
    print(message, flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marginalia")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "render", "align", "transcribe", "process"):
        command = commands.add_parser(name)
        command.add_argument("course")
        if name in {"render", "process"}:
            command.add_argument("--deck", dest="decks", action="append")
        if name in {"align", "transcribe"}:
            command.add_argument("--video", dest="videos", action="append")
    return parser


def main() -> None:
    args = _parser().parse_args()
    course = Course(args.course)
    if args.command == "scan":
        ingest.scan(course)
    elif args.command == "render":
        for deck in args.decks or [deck["id"] for deck in course.manifest()["decks"]]:
            slides.render_deck(course, deck, _progress)
    elif args.command == "align":
        align.align_course(course, _progress, args.videos)
    elif args.command == "transcribe":
        for video in args.videos or [video["id"] for video in course.manifest()["videos"]]:
            transcribe.transcribe_video(course, video, _progress)
    else:
        pipeline.process(course, args.decks, _progress)
