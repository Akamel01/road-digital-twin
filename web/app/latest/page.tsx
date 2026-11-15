import type { Metadata } from "next";
import LatestBuild from "@/components/latest/LatestBuild";

export const metadata: Metadata = {
  title: "Latest build · Road digital twin",
  description: "The newest area build and its gate scorecard. Not gate-passed unless every gate is GO.",
};

export default function Page() {
  return <LatestBuild />;
}
