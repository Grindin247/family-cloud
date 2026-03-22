import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Planning Workspace",
  description: "Plan management service web client",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
