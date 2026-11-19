// Consultant app entry: providers + routes. Nothing else lives here.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@/shared/styles/index.css";
import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/router";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AppProviders>
      <AppRoutes />
    </AppProviders>
  </StrictMode>,
);
