import "./globals.css";

export const metadata = {
  title: "Education Management",
  description: "Standalone visibility and correction workspace for family education tracking.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
