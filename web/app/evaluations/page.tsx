import type { Metadata } from "next";
import Evaluations from "@/components/evaluations/Evaluations";

export const metadata: Metadata = {
  title: "Evaluations · Road digital twin",
  description: "Reconstruction approaches compared on the shared evaluation harness.",
};

export default function Page() {
  return <Evaluations />;
}
