"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { resolvePortal, PortalAccent, PortalGroup, PortalIcon } from "../lib/portal";

function groupCopy(group: PortalGroup): string {
  if (group === "Start") return "Fresh starts for the next thing you need to capture.";
  if (group === "Plan") return "Shared workspaces for decisions, tasks, and momentum.";
  if (group === "Keep") return "The family memory shelf for everyday information.";
  return "Relaxed spaces for the things you want close at hand.";
}

function TileIcon({ icon }: { icon: PortalIcon }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

  switch (icon) {
    case "doc":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path {...common} d="M10 5.5h8l4 4v17H10z" />
          <path {...common} d="M18 5.5v4h4" />
          <path {...common} d="M13 15h6M13 19h6M13 23h4" />
        </svg>
      );
    case "whiteboard":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <rect {...common} x="6" y="7" width="20" height="14" rx="2.5" />
          <path {...common} d="M12 26h8M16 21v5M10 11c2 1 3 4 5 4 2.5 0 2.5-5 5-5 1.2 0 2 .6 3 1.5" />
        </svg>
      );
    case "chat":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path {...common} d="M8 8.5h16a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3h-8l-5 3v-3H8a3 3 0 0 1-3-3v-8a3 3 0 0 1 3-3Z" />
          <path {...common} d="M11.5 14.5h9M11.5 18h6" />
        </svg>
      );
    case "tasks":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path {...common} d="M12 8h12M12 16h12M12 24h12" />
          <path {...common} d="m7 8 1.5 1.5L10.5 7M7 16l1.5 1.5L10.5 15M7 24l1.5 1.5L10.5 23" />
        </svg>
      );
    case "goals":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <circle {...common} cx="16" cy="16" r="9" />
          <circle {...common} cx="16" cy="16" r="4.5" />
          <path {...common} d="M16 7v3M25 16h-3M16 25v-3M7 16h3" />
        </svg>
      );
    case "notes":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path {...common} d="M10 6.5h12a2 2 0 0 1 2 2v15l-4-3H10a2 2 0 0 1-2-2v-10a2 2 0 0 1 2-2Z" />
          <path {...common} d="M12.5 11.5h9M12.5 15.5h9M12.5 19.5h5" />
        </svg>
      );
    case "files":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path {...common} d="M5.5 10A2.5 2.5 0 0 1 8 7.5h5l2 2.5h9A2.5 2.5 0 0 1 26.5 12.5v10A2.5 2.5 0 0 1 24 25H8a2.5 2.5 0 0 1-2.5-2.5Z" />
          <path {...common} d="M5.5 12h21" />
        </svg>
      );
    case "media":
      return (
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <rect {...common} x="6" y="7" width="20" height="18" rx="3" />
          <path {...common} d="m12.5 13.5 8 3.5-8 3.5z" />
        </svg>
      );
  }
}

function AccentSeeds({ accent }: { accent: PortalAccent }) {
  return (
    <div className={`tile-seeds tile-seeds-${accent}`} aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

export default function HomePage() {
  const [hostname, setHostname] = useState("");

  useEffect(() => {
    setHostname(window.location.hostname);
  }, []);

  const portal = useMemo(() => resolvePortal(hostname), [hostname]);

  return (
    <main className="portal-shell">
      <div className="portal-orb portal-orb-left" aria-hidden="true" />
      <div className="portal-orb portal-orb-right" aria-hidden="true" />

      <section className="hero">
        <div className="eyebrow">Family Cloud Home</div>
        <h1 className="hero-title">Everything your family uses, in one place.</h1>
        <div className="hero-note">
          {portal.familyDomain ? (
            <span>
              Connected to <strong>{portal.familyDomain}</strong>
            </span>
          ) : (
            <span>Family domain not detected yet. Tile links will resolve once the portal is opened on its home host.</span>
          )}
        </div>
      </section>

      <section className="group-list" aria-label="Family Cloud tools">
        {portal.groups.map((group) => (
          <section className="group-card" key={group.name} aria-labelledby={`group-${group.name}`}>
            <div className="group-head">
              <div>
                <h2 id={`group-${group.name}`}>{group.name}</h2>
              </div>
              <p>{groupCopy(group.name)}</p>
            </div>

            <div className="tile-grid">
              {group.tiles.map((tile, tileIndex) => {
                const style = {
                  ["--tile-index" as string]: String(tileIndex),
                } as React.CSSProperties;

                const inner = (
                  <>
                    <AccentSeeds accent={tile.accent} />
                    <div className="tile-topline">
                      <span className={`status-chip status-${tile.status}`}>{tile.label}</span>
                      <span className="tile-kind">{tile.kind}</span>
                    </div>
                    <div className={`tile-icon accent-${tile.accent}`}>
                      <TileIcon icon={tile.icon} />
                    </div>
                    <div className="tile-copy">
                      <h3>{tile.title}</h3>
                      <p>{tile.subtitle}</p>
                    </div>
                    <div className="tile-footer">
                      <span>{tile.launchMode === "disabled" ? "Coming soon" : "Open tool"}</span>
                      <span className="tile-arrow" aria-hidden="true">
                        {tile.launchMode === "disabled" ? "..." : "->"}
                      </span>
                    </div>
                  </>
                );

                if (tile.launchMode === "disabled" || !tile.resolvedHref) {
                  return (
                    <article className="portal-tile is-disabled" key={tile.id} style={style} aria-disabled="true">
                      {inner}
                    </article>
                  );
                }

                return (
                  <Link className="portal-tile" href={tile.resolvedHref} key={tile.id} style={style}>
                    {inner}
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </section>
    </main>
  );
}
