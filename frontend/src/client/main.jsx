import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes, useParams } from "react-router";
import "./client.css";
import { Booking, FormPage } from "./pages/Public";
import { FileViewer, InvoicePage } from "./pages/FileViewer";
import Portal from "./pages/Portal";
import TaskPage from "./pages/TaskPage";

function Download() {
  const { token } = useParams();
  useEffect(() => { location.replace(`/api/public/d/${token}`); }, [token]);
  return null;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/c/:slug/form/:form" element={<FormPage />} />
        <Route path="/form/:form" element={<FormPage />} />
        <Route path="/c/:slug/book/:type" element={<Booking />} />
        <Route path="/book/:type" element={<Booking />} />
        <Route path="/c/:slug/f/:token" element={<FileViewer />} />
        <Route path="/f/:token" element={<FileViewer />} />
        <Route path="/c/:slug/preview/:fileId" element={<FileViewer preview />} />
        <Route path="/preview/:fileId" element={<FileViewer preview />} />
        <Route path="/c/:slug/i/:token" element={<InvoicePage />} />
        <Route path="/i/:token" element={<InvoicePage />} />
        <Route path="/c/:slug/d/:token" element={<Download />} />
        <Route path="/d/:token" element={<Download />} />
        <Route path="/c/:slug/t/:token" element={<TaskPage />} />
        <Route path="/t/:token" element={<TaskPage />} />
        <Route path="/c/:slug/portal" element={<Portal />} />
        <Route path="/portal" element={<Portal />} />
        <Route path="*" element={<p className="p-8">This page doesn't exist.</p>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
