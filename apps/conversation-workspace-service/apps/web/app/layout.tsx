import "./globals.css";

export const metadata = {
  title: "Chat",
  description: "Shared family conversation workspace for human and assistant collaboration.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
