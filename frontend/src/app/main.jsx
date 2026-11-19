import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../index.css";
import { AppShell, useMe } from "./components/AppShell";
import { SkeletonList, Toaster } from "./components/ui";
import Login from "./pages/Login";

const Home = lazy(() => import("./pages/Home"));
const Projects = lazy(() => import("./pages/Projects"));
const Project = lazy(() => import("./pages/Project"));
const Contacts = lazy(() => import("./pages/Contacts"));
const Inbox = lazy(() => import("./pages/Inbox"));
const Calendar = lazy(() => import("./pages/Calendar"));
const Files = lazy(() => import("./pages/Files"));
const Builder = lazy(() => import("./pages/Builder"));
const Automations = lazy(() => import("./pages/Automations"));
const Payments = lazy(() => import("./pages/Payments"));
const Reports = lazy(() => import("./pages/Reports"));
const Agents = lazy(() => import("./pages/Agents"));
const Approvals = lazy(() => import("./pages/Approvals"));
const Tasks = lazy(() => import("./pages/Tasks"));
const Settings = lazy(() => import("./pages/Settings"));
const Onboarding = lazy(() => import("./pages/Onboarding"));
const Time = lazy(() => import("./pages/Time"));
const Retainers = lazy(() => import("./pages/Retainers"));
const Estimates = lazy(() => import("./pages/Estimates"));
const OAuthConsent = lazy(() => import("./pages/OAuthConsent"));
const Admin = lazy(() => import("./admin/Admin"));

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } } });

function Guard({ children, bare }) {
  const me = useMe();
  if (me.isLoading) return <div className="p-6"><SkeletonList /></div>;
  if (me.isError) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  const ws = me.data.workspaces.find((w) => w.id === me.data.current) || me.data.workspaces[0];
  if (!ws && me.data.user.is_admin) return <Navigate to="/admin" replace />;
  if (ws && !ws.onboarded && ws.role === "owner" && !bare && !location.pathname.startsWith("/onboarding")) return <Navigate to="/onboarding" replace />;
  return bare ? children : <AppShell>{children}</AppShell>;
}

const page = (el, bare) => <Guard bare={bare}><Suspense fallback={<div className="p-6"><SkeletonList /></div>}>{el}</Suspense></Guard>;

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/onboarding" element={page(<Onboarding />, true)} />
          <Route path="/" element={page(<Home />)} />
          <Route path="/projects" element={page(<Projects />)} />
          <Route path="/projects/:id" element={page(<Project />)} />
          <Route path="/contacts" element={page(<Contacts />)} />
          <Route path="/contacts/:id" element={page(<Contacts />)} />
          <Route path="/inbox" element={page(<Inbox />)} />
          <Route path="/inbox/:projectId" element={page(<Inbox />)} />
          <Route path="/calendar" element={page(<Calendar />)} />
          <Route path="/files" element={page(<Files />)} />
          <Route path="/files/:id" element={page(<Builder />, true)} />
          <Route path="/templates/:tid" element={page(<Builder />, true)} />
          <Route path="/automations" element={page(<Automations />)} />
          <Route path="/automations/:id" element={page(<Automations />)} />
          <Route path="/payments" element={page(<Payments />)} />
          <Route path="/reports" element={page(<Reports />)} />
          <Route path="/agents" element={page(<Agents />)} />
          <Route path="/approvals" element={page(<Approvals />)} />
          <Route path="/tasks" element={page(<Tasks />)} />
          <Route path="/time" element={page(<Time />)} />
          <Route path="/retainers" element={page(<Retainers />)} />
          <Route path="/retainers/:id" element={page(<Retainers />)} />
          <Route path="/estimates" element={page(<Estimates />)} />
          <Route path="/estimates/:id" element={page(<Estimates />)} />
          <Route path="/oauth/consent" element={page(<OAuthConsent />, true)} />
          <Route path="/settings" element={page(<Settings />)} />
          <Route path="/settings/:section" element={page(<Settings />)} />
          <Route path="/admin/*" element={<Suspense fallback={null}><Admin /></Suspense>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
