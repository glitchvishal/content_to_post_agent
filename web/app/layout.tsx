import type { Metadata, Viewport } from "next";
import Header from "@/components/Header";
import "./globals.css";

export const metadata: Metadata = {
  title: "Content-to-Post Agent",
  description: "Turn an article into LinkedIn and X posts, checked by an AI judge and approved by you.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Header />
        <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
