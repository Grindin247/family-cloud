import "./globals.css";

export const metadata = {
  title: "Questions",
  description: "Standalone queued question review and answer workspace.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
