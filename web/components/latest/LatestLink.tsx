import Link from "next/link";
import styles from "@/components/dev/dev.module.css";

// Top-bar link to the Latest build view. Added to TopBar only; the published view is unchanged.
export default function LatestLink() {
  return (
    <Link className={styles.devLink} style={{ marginLeft: 0 }} href="/latest">
      Latest build
    </Link>
  );
}
