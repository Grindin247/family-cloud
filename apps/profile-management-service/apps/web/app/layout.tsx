import "./globals.css";

export const metadata = {
  title: "Profile Management",
  description: "Standalone workspace for account profiles, person preferences, and family relationship graphs.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
