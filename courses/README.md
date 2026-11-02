# courses/

Put each course in its own folder. Only this README is tracked; everything else here stays on your machine.

```
courses/<course-id>/
  course.json        optional: {"title": "...", "hiddenDecks": [], "videoUrls": {}}
  materials/         drop pptx / pdf / mp4 / zip here (any sub-folders)
```

Then open the app (`pnpm dev`) and press 開始生成, or run `cd server && uv run marginalia process <course-id>`.
