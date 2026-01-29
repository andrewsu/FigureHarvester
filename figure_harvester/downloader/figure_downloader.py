"""Main figure downloader orchestration."""

import logging
import os
from pathlib import Path
from typing import Dict, List
import requests
from tqdm import tqdm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from ..api.entrez import EntrezAPI, NoPMCIDError, PMIDNotFoundError
from ..api.pmc import PMCAPI, NotOpenAccessError, NoFiguresError
from ..api.rate_limiter import RateLimiter
from .resume_manager import ResumeManager


logger = logging.getLogger(__name__)


class FigureHarvester:
    """
    Main orchestrator for downloading figures from PubMed papers.

    Coordinates API calls, downloads, and progress tracking.
    """

    def __init__(
        self,
        input_file: Path,
        output_dir: Path,
        email: str,
        api_key: str = None,
        requests_per_second: float = 3.0,
        timeout: int = 30,
        retry_attempts: int = 3,
        max_retry_attempts: int = 3,
        retry_after_hours: int = 24
    ):
        """
        Initialize FigureHarvester.

        Args:
            input_file: Path to file containing PMIDs (one per line)
            output_dir: Directory to save downloaded figures
            email: Email for NCBI API (required)
            api_key: NCBI API key (optional)
            requests_per_second: API rate limit
            timeout: HTTP timeout in seconds
            retry_attempts: Retry attempts for downloads
            max_retry_attempts: Max retry attempts for failed PMIDs
            retry_after_hours: Hours before retrying failed PMIDs
        """
        self.input_file = Path(input_file)
        self.output_dir = Path(output_dir)
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self.retry_attempts = retry_attempts

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.rate_limiter = RateLimiter(requests_per_second=requests_per_second)
        self.entrez_api = EntrezAPI(email, api_key, self.rate_limiter)
        self.pmc_api = PMCAPI(self.rate_limiter)
        self.resume_manager = ResumeManager(
            manifest_path=self.output_dir / "manifest.json",
            output_dir=self.output_dir,
            max_retry_attempts=max_retry_attempts,
            retry_after_hours=retry_after_hours
        )

        # Session for downloads
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'FigureHarvester/1.0 (Python requests)'
        })

        logger.info(f"Initialized FigureHarvester with output dir: {output_dir}")

    def load_pmids(self) -> List[str]:
        """
        Load PMIDs from input file.

        Returns:
            List of PMIDs

        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If file is empty or invalid
        """
        if not self.input_file.exists():
            raise FileNotFoundError(f"Input file not found: {self.input_file}")

        with open(self.input_file, 'r') as f:
            pmids = [line.strip() for line in f if line.strip()]

        if not pmids:
            raise ValueError("Input file is empty")

        # Validate PMID format (should be numeric)
        invalid_pmids = [p for p in pmids if not p.isdigit()]
        if invalid_pmids:
            logger.warning(
                f"Found {len(invalid_pmids)} invalid PMIDs "
                f"(non-numeric): {invalid_pmids[:5]}"
            )
            pmids = [p for p in pmids if p.isdigit()]

        logger.info(f"Loaded {len(pmids)} PMIDs from {self.input_file}")
        return pmids

    def get_file_extension(self, url: str) -> str:
        """
        Extract file extension from URL.

        Args:
            url: Figure URL

        Returns:
            File extension including dot (e.g., ".jpg")
        """
        ext = os.path.splitext(url)[1].lower()
        if not ext or ext not in ['.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff']:
            ext = '.jpg'  # Default extension
        return ext

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    def download_figure(self, url: str, filepath: Path) -> bool:
        """
        Download a single figure with retry logic.

        Args:
            url: Figure URL
            filepath: Path to save figure

        Returns:
            True if successful, False otherwise

        Raises:
            requests.RequestException: On network errors (will retry)
        """
        logger.debug(f"Downloading {url} to {filepath}")

        response = self.session.get(url, stream=True, timeout=self.timeout)
        if response.status_code != 200:
            logger.warning(f"HTTP {response.status_code} for URL: {url}")
        response.raise_for_status()

        # Download with progress
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # Verify file was created and has content
        if not filepath.exists() or filepath.stat().st_size == 0:
            raise IOError(f"Downloaded file is empty or missing: {filepath}")

        logger.debug(f"Successfully downloaded {filepath.name}")
        return True

    def process_pmid(self, pmid: str, pbar: tqdm) -> Dict:
        """
        Process a single PMID: convert to PMCID, extract figures, download.

        Args:
            pmid: PubMed ID
            pbar: Progress bar instance

        Returns:
            Result dictionary with status and details
        """
        result = {
            "pmid": pmid,
            "status": "failed",
            "pmcid": None,
            "figures": [],
            "error": None
        }

        try:
            # Step 1: Convert PMID to PMCID
            pbar.set_description(f"Converting {pmid}")
            pmcid = self.entrez_api.pmid_to_pmcid(pmid)
            result["pmcid"] = pmcid

            # Step 2: Get figure URLs
            pbar.set_description(f"Fetching figures for {pmid}")
            figure_urls = self.pmc_api.get_figure_urls(pmcid)

            # Step 3: Download each figure
            downloaded_figures = []
            for idx, fig_url in enumerate(figure_urls, 1):
                pbar.set_description(f"Downloading fig {idx}/{len(figure_urls)} for {pmid}")

                ext = self.get_file_extension(fig_url)
                filename = f"PMID_{pmid}_fig{idx}{ext}"
                filepath = self.output_dir / filename

                try:
                    self.download_figure(fig_url, filepath)
                    downloaded_figures.append(filename)
                except Exception as e:
                    logger.warning(
                        f"Failed to download figure {idx} for {pmid}: {e}"
                    )
                    # Continue with other figures even if one fails

            if not downloaded_figures:
                raise NoFiguresError(f"Failed to download any figures for {pmid}")

            # Mark as completed
            self.resume_manager.mark_completed(pmid, pmcid, downloaded_figures)
            result["status"] = "success"
            result["figures"] = downloaded_figures

        except (NoPMCIDError, NotOpenAccessError, NoFiguresError, PMIDNotFoundError) as e:
            # Expected errors - log and mark as failed
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
            self.resume_manager.mark_failed(pmid, e)
            logger.info(f"PMID {pmid}: {type(e).__name__} - {e}")

        except Exception as e:
            # Unexpected errors
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
            self.resume_manager.mark_failed(pmid, e)
            logger.error(f"Unexpected error for PMID {pmid}: {e}", exc_info=True)

        return result

    def run(self) -> Dict:
        """
        Main execution: process all PMIDs and download figures.

        Returns:
            Summary dictionary with statistics
        """
        logger.info("Starting FigureHarvester")

        # Load PMIDs
        pmids = self.load_pmids()

        # Results tracking
        results = {
            "success": [],
            "failed": [],
            "skipped": []
        }

        # Process each PMID with progress bar
        with tqdm(total=len(pmids), desc="Processing PMIDs", unit="PMID") as pbar:
            for pmid in pmids:
                try:
                    # Check if already completed
                    if self.resume_manager.is_completed(pmid):
                        logger.info(f"Skipping {pmid} (already completed)")
                        results["skipped"].append(pmid)
                        pbar.update(1)
                        continue

                    # Check if should retry
                    if not self.resume_manager.should_retry(pmid):
                        logger.info(f"Skipping {pmid} (max retries reached)")
                        results["skipped"].append(pmid)
                        pbar.update(1)
                        continue

                    # Process PMID
                    result = self.process_pmid(pmid, pbar)

                    if result["status"] == "success":
                        results["success"].append(result)
                    else:
                        results["failed"].append(result)

                except Exception as e:
                    logger.error(f"Critical error processing {pmid}: {e}", exc_info=True)
                    results["failed"].append({
                        "pmid": pmid,
                        "error": str(e),
                        "error_type": type(e).__name__
                    })

                finally:
                    pbar.update(1)

        # Generate summary
        summary = self._generate_summary(results)
        logger.info("\n" + summary)

        # Generate error report
        if results["failed"]:
            self.resume_manager.generate_error_report()

        return results

    def _generate_summary(self, results: Dict) -> str:
        """
        Generate summary report.

        Args:
            results: Results dictionary

        Returns:
            Summary string
        """
        total_figures = sum(len(r.get("figures", [])) for r in results["success"])

        summary = f"""
╔══════════════════════════════════════════════════════════╗
║              FigureHarvester Summary                     ║
╠══════════════════════════════════════════════════════════╣
║ Successful:  {len(results['success']):>4} PMIDs                              ║
║ Failed:      {len(results['failed']):>4} PMIDs                              ║
║ Skipped:     {len(results['skipped']):>4} PMIDs                              ║
║ Total:       {len(results['success']) + len(results['failed']) + len(results['skipped']):>4} PMIDs                              ║
║                                                          ║
║ Figures Downloaded: {total_figures:>4}                              ║
║ Output Directory:   {str(self.output_dir):<30} ║
╚══════════════════════════════════════════════════════════╝
"""
        return summary
