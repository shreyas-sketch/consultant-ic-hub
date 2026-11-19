// Every consultant screen, in one table. Screens are code-split: each loads on first visit.
import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router";
import { RequireAuth } from "@/app/components/RequireAuth";
import { ErrorBoundary } from "@/app/components/ErrorBoundary";
import Login from "@/app/features/auth/Login";

const f = {
  Home: lazy(() => import("@/app/features/home/Home")),
  Projects: lazy(() => import("@/app/features/projects/Projects")),
  Project: lazy(() => import("@/app/features/projects/Project")),
  Contacts: lazy(() => import("@/app/features/contacts/Contacts")),
  Inbox: lazy(() => import("@/app/features/inbox/Inbox")),
  Calendar: lazy(() => import("@/app/features/calendar/Calendar")),
  Files: lazy(() => import("@/app/features/files/Files")),
  Builder: lazy(() => import("@/app/features/files/Builder")),
  Automations: lazy(() => import("@/app/features/automations/Automations")),
  Payments: lazy(() => import("@/app/features/payments/Payments")),
  Reports: lazy(() => import("@/app/features/reports/Reports")),
  Agents: lazy(() => import("@/app/features/agents/Agents")),
  Approvals: lazy(() => import("@/app/features/approvals/Approvals")),
  Tasks: lazy(() => import("@/app/features/tasks/Tasks")),
  Settings: lazy(() => import("@/app/features/settings/Settings")),
  Onboarding: lazy(() => import("@/app/features/onboarding/Onboarding")),
  Time: lazy(() => import("@/app/features/time/Time")),
  Retainers: lazy(() => import("@/app/features/retainers/Retainers")),
  Estimates: lazy(() => import("@/app/features/estimates/Estimates")),
  OAuthConsent: lazy(() => import("@/app/features/oauth/OAuthConsent")),
  Admin: lazy(() => import("@/app/features/admin/Admin")),
};

// [path, screen, bare?]  bare = full-screen, without the app shell.
export const ROUTES = [
  ["/onboarding", f.Onboarding, true],
  ["/", f.Home],
  ["/projects", f.Projects],
  ["/projects/:id", f.Project],
  ["/contacts", f.Contacts],
  ["/contacts/:id", f.Contacts],
  ["/inbox", f.Inbox],
  ["/inbox/:projectId", f.Inbox],
  ["/calendar", f.Calendar],
  ["/files", f.Files],
  ["/files/:id", f.Builder, true],
  ["/templates/:tid", f.Builder, true],
  ["/automations", f.Automations],
  ["/automations/:id", f.Automations],
  ["/payments", f.Payments],
  ["/reports", f.Reports],
  ["/agents", f.Agents],
  ["/approvals", f.Approvals],
  ["/tasks", f.Tasks],
  ["/time", f.Time],
  ["/retainers", f.Retainers],
  ["/retainers/:id", f.Retainers],
  ["/estimates", f.Estimates],
  ["/estimates/:id", f.Estimates],
  ["/oauth/consent", f.OAuthConsent, true],
  ["/settings", f.Settings],
  ["/settings/:section", f.Settings],
];

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {ROUTES.map(([path, Screen, bare]) => (
        <Route key={path} path={path} element={<RequireAuth bare={bare}><Screen /></RequireAuth>} />
      ))}
      {/* Our own Admin screen does its own staff check. */}
      <Route path="/admin/*" element={<ErrorBoundary><Suspense fallback={null}><f.Admin /></Suspense></ErrorBoundary>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
