"""Resume manager for tracking download progress."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)


class ResumeManager:
    """
    Manages download progress using a JSON manifest file.

    Tracks completed and failed downloads to enable resuming interrupted sessions.
    """

    def __init__(
        self,
        manifest_path: Path,
        output_dir: Path,
        max_retry_attempts: int = 3,
        retry_after_hours: int = 24
    ):
        """
        Initialize resume manager.

        Args:
            manifest_path: Path to manifest JSON file
            output_dir: Directory where figures are downloaded
            max_retry_attempts: Maximum retry attempts for failed PMIDs
            retry_after_hours: Hours before retrying failed PMIDs
        """
        self.manifest_path = Path(manifest_path)
        self.output_dir = Path(output_dir)
        self.max_retry_attempts = max_retry_attempts
        self.retry_after_hours = retry_after_hours
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Dict:
        """
        Load manifest from file or create new one.

        Returns:
            Manifest dictionary
        """
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    manifest = json.load(f)
                    logger.info(
                        f"Loaded manifest: {len(manifest.get('completed', {}))} "
                        f"completed, {len(manifest.get('failed', {}))} failed"
                    )
                    return manifest
            except Exception as e:
                logger.warning(f"Failed to load manifest: {e}, creating new one")

        return {"completed": {}, "failed": {}}

    def _save_manifest(self):
        """Save manifest to file."""
        try:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.manifest_path, 'w') as f:
                json.dump(self.manifest, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")

    def is_completed(self, pmid: str) -> bool:
        """
        Check if PMID has been successfully downloaded.

        Verifies that all figure files still exist on disk.

        Args:
            pmid: PubMed ID

        Returns:
            True if completed and files exist, False otherwise
        """
        if pmid not in self.manifest["completed"]:
            return False

        # Verify files still exist
        completed_info = self.manifest["completed"][pmid]
        figures = completed_info.get("figures", [])

        all_exist = all(
            (self.output_dir / fig).exists()
            for fig in figures
        )

        if not all_exist:
            logger.warning(
                f"PMID {pmid} marked completed but files missing, "
                "will re-download"
            )
            # Remove from completed since files are missing
            del self.manifest["completed"][pmid]
            self._save_manifest()
            return False

        return True

    def should_retry(self, pmid: str) -> bool:
        """
        Determine if a failed PMID should be retried.

        Args:
            pmid: PubMed ID

        Returns:
            True if should retry, False otherwise
        """
        if pmid not in self.manifest["failed"]:
            return True  # Not failed yet, so try it

        failed_info = self.manifest["failed"][pmid]
        attempts = failed_info.get("attempts", 0)

        # Check if max attempts reached
        if attempts >= self.max_retry_attempts:
            logger.debug(
                f"PMID {pmid} has reached max retry attempts ({attempts})"
            )
            return False

        # Check if enough time has passed since last attempt
        last_attempt_str = failed_info.get("last_attempt")
        if last_attempt_str:
            try:
                last_attempt = datetime.fromisoformat(last_attempt_str)
                time_since = datetime.now() - last_attempt
                if time_since < timedelta(hours=self.retry_after_hours):
                    logger.debug(
                        f"PMID {pmid} failed recently, waiting before retry"
                    )
                    return False
            except Exception as e:
                logger.warning(f"Failed to parse timestamp for {pmid}: {e}")

        return True

    def mark_completed(self, pmid: str, pmcid: str, figures: List[str]):
        """
        Mark PMID as successfully completed.

        Args:
            pmid: PubMed ID
            pmcid: PMC ID
            figures: List of downloaded figure filenames
        """
        self.manifest["completed"][pmid] = {
            "pmcid": pmcid,
            "figures": figures,
            "download_date": datetime.now().isoformat(),
            "status": "success"
        }

        # Remove from failed if it was there
        if pmid in self.manifest["failed"]:
            del self.manifest["failed"][pmid]

        self._save_manifest()
        logger.info(f"Marked PMID {pmid} as completed ({len(figures)} figures)")

    def mark_failed(self, pmid: str, error: Exception):
        """
        Mark PMID as failed.

        Args:
            pmid: PubMed ID
            error: Exception that caused the failure
        """
        if pmid not in self.manifest["failed"]:
            self.manifest["failed"][pmid] = {"attempts": 0}

        self.manifest["failed"][pmid].update({
            "error": str(error),
            "error_type": type(error).__name__,
            "attempts": self.manifest["failed"][pmid]["attempts"] + 1,
            "last_attempt": datetime.now().isoformat()
        })

        self._save_manifest()
        logger.warning(
            f"Marked PMID {pmid} as failed "
            f"(attempt {self.manifest['failed'][pmid]['attempts']}): {error}"
        )

    def get_statistics(self) -> Dict:
        """
        Get statistics about completed and failed downloads.

        Returns:
            Dictionary with statistics
        """
        completed_count = len(self.manifest["completed"])
        failed_count = len(self.manifest["failed"])

        total_figures = sum(
            len(info.get("figures", []))
            for info in self.manifest["completed"].values()
        )

        return {
            "completed": completed_count,
            "failed": failed_count,
            "total_figures": total_figures
        }

    def generate_error_report(self, output_path: Optional[Path] = None) -> str:
        """
        Generate a detailed error report for failed downloads.

        Args:
            output_path: Path to save error report (optional)

        Returns:
            Error report as string
        """
        if output_path is None:
            output_path = self.output_dir / "errors.json"

        error_report = {}
        for pmid, info in self.manifest["failed"].items():
            error_report[pmid] = {
                "error_type": info.get("error_type", "Unknown"),
                "message": info.get("error", "Unknown error"),
                "attempts": info.get("attempts", 0),
                "last_attempt": info.get("last_attempt", "Unknown")
            }

        # Save to file
        try:
            with open(output_path, 'w') as f:
                json.dump(error_report, f, indent=2)
            logger.info(f"Error report saved to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save error report: {e}")

        return json.dumps(error_report, indent=2)
