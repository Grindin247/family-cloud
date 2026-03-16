import Link from "next/link";
import "./globals.css";

const nav = [
  { href: "/", label: "Dashboard" },
  { href: "/families", label: "Families" },
  { href: "/goals", label: "Goals" },
  { href: "/decisions", label: "Decisions" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/budget", label: "Budget" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <h1 className="brand-title">Family Decision Studio</h1>
            <p className="brand-subtitle">Clear priorities. Shared ownership. Practical execution.</p>
            <nav className="nav-list">
              {nav.map((item) => (
                <Link key={item.href} href={item.href} className="nav-link">
                  {item.label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
