import Link from "next/link";
import styles from "@/components/dev/dev.module.css";

// Top-bar link to the Evaluations view. Added to TopBar only; the published view is unchanged.
export default function EvaluationsLink() {
  return (
    <Link className={styles.devLink} style={{ marginLeft: 0 }} href="/evaluations" title="Evaluations">
      Evals
    </Link>
  );
}
