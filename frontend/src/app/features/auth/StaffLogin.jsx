// Email + password sign-in for our own team (the Admin screen). Consultants log in with a phone code instead.
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { post } from "@/shared/api";
import { Wordmark } from "@/app/layout/AppShell";
import { Button, Field, Input } from "@/app/ui";

export default function StaffLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const qc = useQueryClient();

  async function submit(e) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await post("/api/auth/staff", { email, password });
      qc.clear();
      nav("/admin", { replace: true });
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-5">
      <div className="w-full max-w-sm rise">
        <Wordmark />
        <h1 className="mt-8 text-[32px] font-extrabold leading-tight tracking-[-0.02em]">Team <span className="text-gold">sign-in</span></h1>
        <p className="mt-2 font-light text-ivory-70">For the product team's Admin screen. Consultants log in with a code on their phone.</p>
        <form className="mt-8 space-y-3" noValidate onSubmit={submit}>
          <Field label="Email">
            <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {err && <p className="text-[14px] text-alert" role="alert">{err.message}</p>}
          <Button variant="primary" size="lg" className="w-full" busy={busy} disabled={!email.trim() || !password}>Sign in</Button>
        </form>
        <Link to="/login" className="mt-6 block text-center text-[14px] text-ivory-70 hover:text-ivory">Consultant? Log in with your phone</Link>
      </div>
    </div>
  );
}
