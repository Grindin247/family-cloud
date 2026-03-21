import "./globals.css";

export const metadata = {
  title: "Family Events",
  description: "Standalone raw event viewer for canonical family events.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
