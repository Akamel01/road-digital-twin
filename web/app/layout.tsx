import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import "./globals.css";

export const metadata: Metadata = {
  title: "Road digital twin",
  description: "Measurable digital twin of road infrastructure. Non-commercial research demo.",
};

// Manrope, as in the mockup. next/font self-hosts it at build time, so the export has no third-party font request.
const manrope = Manrope({ subsets: ["latin"], weight: ["500", "700"], variable: "--font-manrope" });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={manrope.variable}>
      <body>{children}</body>
    </html>
  );
}
