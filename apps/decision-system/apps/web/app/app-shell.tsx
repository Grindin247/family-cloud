"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  clearForwardAuthSession,
  getKeycloakLogoutUrl,
  getLoginUrl,
  MeResponse,
} from "../lib/api";

const nav = [
  { href: "/", label: "Dashboard", detail: "Scorecards, recent activity, and roadmap momentum." },
  { href: "/families", label: "Families", detail: "Households, memberships, and person records." },
  { href: "/goals", label: "Goals", detail: "Family priorities and personal commitments." },
  { href: "/decisions", label: "Decisions", detail: "Capture, score, and track decision work." },
  { href: "/roadmap", label: "Roadmap", detail: "Schedule follow-through and progress reviews." },
  { href: "/budget", label: "Budget", detail: "Thresholds, allowances, and discretionary spend." },
];

function initials(value: string | null): string {
  if (!value) return "?";
  const cleaned = value.split("@")[0].replace(/[^a-zA-Z0-9]+/g, " ").trim();
  if (!cleaned) return "?";
  const parts = cleaned.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMessage, setAuthMessage] = useState("");
  const [authAction, setAuthAction] = useState<"logout" | "switch-account" | null>(null);

  async function loadMe() {
    try {
      setAuthLoading(true);
      setAuthMessage("");
      const data = await api.getMe();
      setMe(data);
    } catch (error) {
      setMe({ authenticated: false, email: null, memberships: [] });
      setAuthMessage(error instanceof Error ? error.message : "Could not load account status.");
    } finally {
      setAuthLoading(false);
    }
  }

  useEffect(() => {
    void loadMe();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has("signed_out")) return;
    setAuthMessage(
      params.has("switch_account")
        ? "Signed out. Use Login when you're ready to continue with a different account."
        : "Signed out. Login will take you back through the family sign-in flow."
    );
  }, []);

  const membershipLabel = useMemo(() => {
    const count = me?.memberships.length ?? 0;
    if (count === 0) return "No linked families yet";
    if (count === 1) return "1 linked family";
    return `${count} linked families`;
  }, [me]);

  function runBrowserLogout(mode: "logout" | "switch-account") {
    try {
      setAuthAction(mode);
      setAuthMessage("");
      clearForwardAuthSession();
      const keycloakLogoutUrl = getKeycloakLogoutUrl(mode);
      window.setTimeout(() => {
        if (keycloakLogoutUrl) {
          window.location.assign(keycloakLogoutUrl);
          return;
        }
        window.location.assign(getLoginUrl());
      }, 450);
    } catch (error) {
      setAuthMessage(error instanceof Error ? error.message : "Could not sign out.");
      setAuthAction(null);
    }
  }

  function handleLogin() {
    window.location.assign(getLoginUrl());
  }

  return (
    <div className="portal-shell decision-shell">
      <div className="portal-orb portal-orb-left" aria-hidden="true" />
      <div className="portal-orb portal-orb-right" aria-hidden="true" />
      <div className="decision-orb decision-orb-gold" aria-hidden="true" />
      <div className="decision-orb decision-orb-leaf" aria-hidden="true" />

      <div className="app-shell">
        <aside className="sidebar">
          <div className="sidebar-section sidebar-brand">
            <span className="eyebrow">Family Cloud</span>
            <h1 className="brand-title">Decision Client</h1>
            <p className="brand-subtitle">Shared family planning with scoped goals, personal ownership, and event-backed history.</p>
          </div>

          <div className="sidebar-section account-card">
            <div className="account-topline">
              <div className="account-avatar">{initials(me?.email ?? null)}</div>
              <div>
                <div className="account-label">Account</div>
                <div className="account-email">{authLoading ? "Checking session..." : me?.email ?? "Guest mode"}</div>
              </div>
            </div>
            <div className="account-meta">
              <span className={`status-chip ${me?.authenticated ? "status-live" : "status-dim"}`}>
                {authLoading ? "Loading" : me?.authenticated ? "Signed in" : "Signed out"}
              </span>
              <span className="tile-kind">{membershipLabel}</span>
            </div>
            {me?.memberships?.length ? (
              <div className="membership-list">
                {me.memberships.slice(0, 3).map((membership) => (
                  <div className="membership-chip" key={`${membership.family_id}-${membership.member_id}`}>
                    <strong>{membership.family_name}</strong>
                    <span>{membership.role}</span>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="auth-actions">
              {me?.authenticated ? (
                <>
                  <button
                    className="btn-secondary"
                    type="button"
                    onClick={() => runBrowserLogout("logout")}
                    disabled={authAction !== null}
                  >
                    {authAction === "logout" ? "Signing out..." : "Logout"}
                  </button>
                  <button
                    className="btn-primary"
                    type="button"
                    onClick={() => runBrowserLogout("switch-account")}
                    disabled={authAction !== null}
                  >
                    {authAction === "switch-account" ? "Switching..." : "Switch account"}
                  </button>
                </>
              ) : (
                <button className="btn-primary" type="button" onClick={handleLogin}>
                  Login
                </button>
              )}
            </div>
            <p className="auth-note">
              Logout clears this app session. Switch account also ends the family SSO session so a different person can sign in next.
            </p>
            {authMessage ? <p className="auth-message">{authMessage}</p> : null}
          </div>

          <nav className="nav-list" aria-label="Decision client navigation">
            {nav.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link key={item.href} href={item.href} className={`nav-link ${isActive ? "is-active" : ""}`}>
                  <span className="nav-label">{item.label}</span>
                  <span className="nav-detail">{item.detail}</span>
                </Link>
              );
            })}
          </nav>
        </aside>

        <main className="content">{children}</main>
      </div>
    </div>
  );
}
