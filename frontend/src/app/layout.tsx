import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "BrandSentinel AI", description: "Governed content review" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
