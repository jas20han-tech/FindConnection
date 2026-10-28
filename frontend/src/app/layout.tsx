import type { Metadata, Viewport } from "next";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "GraphRAG Studio — Graph Intelligence Platform",
  description:
    "Hybrid Graph RAG workspace: PDF ingestion, Personalized PageRank retrieval, multi-hop paths, cascade simulation and streaming grounded synthesis.",
  applicationName: "GraphRAG Studio",
};

export const viewport: Viewport = {
  themeColor: "#07090E",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="h-screen w-screen overflow-hidden bg-obsidian text-slate-100 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
