import { Suspense } from "react";
import { Navigate, useLocation } from "react-router";
import { AppShell, useMe } from "@/app/layout/AppShell";
import { SkeletonList } from "@/app/ui";
import { ErrorBoundary } from "./ErrorBoundary";

const Loading = () => <div className="p-6"><SkeletonList /></div>;

/** Logged in? In a practice? Set up? Then render the screen inside the shell (or bare). */
export function RequireAuth({ children, bare }) {
  const me = useMe();
  const loc = useLocation();
  if (me.isLoading) return <Loading />;
  if (me.isError) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  const ws = me.data.workspaces.find((w) => w.id === me.data.current) || me.data.workspaces[0];
  if (!ws && me.data.user.is_admin) return <Navigate to="/admin" replace />;
  if (ws && !ws.onboarded && ws.role === "owner" && !bare && !loc.pathname.startsWith("/onboarding")) return <Navigate to="/onboarding" replace />;
  const screen = (
    <ErrorBoundary resetKey={loc.pathname}>
      <Suspense fallback={<Loading />}>{children}</Suspense>
    </ErrorBoundary>
  );
  return bare ? screen : <AppShell>{screen}</AppShell>;
}
