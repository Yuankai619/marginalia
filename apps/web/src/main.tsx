import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { initialTheme } from "@/lib/theme";
import { App } from "./App";
import "./styles/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("找不到應用程式根節點");

// Apply the saved theme before the first paint so dark mode does not flash.
document.documentElement.classList.toggle("dark", initialTheme() === "dark");

const router = createBrowserRouter([{ path: "*", element: <App /> }], {
  basename: import.meta.env.BASE_URL,
});

createRoot(root).render(
  <StrictMode>
    <TooltipProvider delay={300}>
      <RouterProvider router={router} />
    </TooltipProvider>
    <Toaster
      position="bottom-right"
      toastOptions={{ className: "!font-sans" }}
    />
  </StrictMode>,
);
