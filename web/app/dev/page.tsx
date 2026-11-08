import type { Metadata } from "next";
import DevPanel from "@/components/dev/DevPanel";

export const metadata: Metadata = {
  title: "Developer panel",
};

export default function DevPage() {
  return <DevPanel />;
}
