import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LoadingState } from "./components/ui/states";
import { CourseHome } from "./pages/CourseHome";
import { Courses } from "./pages/Courses";

// The reader carries the markdown, KaTeX and chat code; the course pages do not need it.
const Reader = lazy(() =>
  import("./pages/Reader").then((m) => ({ default: m.Reader })),
);

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Courses />} />
      <Route path="/c/:courseId" element={<CourseHome />} />
      <Route
        path="/c/:courseId/d/:deckId/:slide"
        element={
          <Suspense
            fallback={<LoadingState label="開啟閱讀器" className="h-dvh" />}
          >
            <Reader />
          </Suspense>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
