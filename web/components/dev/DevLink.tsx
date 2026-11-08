import Link from "next/link";
import styles from "@/components/dev/dev.module.css";

// Top-bar link to the developer panel. Added to TopBar only.
export default function DevLink() {
  return (
    <Link className={styles.devLink} href="/dev">
      Developer
    </Link>
  );
}
