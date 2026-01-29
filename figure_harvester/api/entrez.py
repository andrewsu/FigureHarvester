"""NCBI Entrez API wrapper for PMID to PMCID conversion."""

import http.client
import logging
from typing import Optional
from Bio import Entrez
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from .rate_limiter import RateLimiter


logger = logging.getLogger(__name__)


class NoPMCIDError(Exception):
    """Raised when a PMID has no corresponding PMC ID."""
    pass


class PMIDNotFoundError(Exception):
    """Raised when a PMID is not found in PubMed."""
    pass


class EntrezAPI:
    """
    Wrapper for NCBI Entrez E-utilities API.

    Handles PMID to PMCID conversion with rate limiting.
    """

    def __init__(
        self,
        email: str,
        api_key: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None
    ):
        """
        Initialize Entrez API wrapper.

        Args:
            email: Email address (required by NCBI)
            api_key: NCBI API key (optional, increases rate limit)
            rate_limiter: Rate limiter instance (optional)
        """
        self.email = email
        self.api_key = api_key
        self.rate_limiter = rate_limiter or RateLimiter(
            requests_per_second=10.0 if api_key else 3.0
        )

        # Configure Entrez
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key

        logger.info(
            f"Initialized EntrezAPI with rate limit: "
            f"{self.rate_limiter.rate} requests/sec"
        )

    @retry(
        retry=retry_if_exception_type((requests.RequestException, IOError, RuntimeError, http.client.IncompleteRead)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    def pmid_to_pmcid(self, pmid: str) -> str:
        """
        Convert PubMed ID to PubMed Central ID.

        Args:
            pmid: PubMed ID (e.g., "12345678")

        Returns:
            PMC ID (e.g., "PMC1234567")

        Raises:
            PMIDNotFoundError: If PMID is not found in PubMed
            NoPMCIDError: If PMID has no corresponding PMC ID
            requests.RequestException: On network errors (will retry)
        """
        # Rate limit before making request
        self.rate_limiter.acquire()

        logger.debug(f"Converting PMID {pmid} to PMCID")

        try:
            # Use elink to find PMC ID from PubMed ID
            handle = Entrez.elink(
                dbfrom="pubmed",
                db="pmc",
                id=pmid,
                retmode="xml"
            )
            record = Entrez.read(handle)
            handle.close()

            # Check if we got any results
            if not record:
                raise PMIDNotFoundError(f"PMID {pmid} not found in PubMed")

            # Extract PMC ID from linksets
            linksets = record[0].get("LinkSetDb", [])

            # Look for the pmc linkset
            pmc_ids = []
            for linkset in linksets:
                if linkset.get("DbTo") == "pmc":
                    links = linkset.get("Link", [])
                    pmc_ids = [link["Id"] for link in links]
                    break

            if not pmc_ids:
                raise NoPMCIDError(
                    f"PMID {pmid} has no corresponding PMC ID "
                    "(article may not be in PubMed Central)"
                )

            # Return the first PMC ID (usually only one)
            pmcid = f"PMC{pmc_ids[0]}" if not pmc_ids[0].startswith("PMC") else pmc_ids[0]
            logger.info(f"Converted PMID {pmid} to {pmcid}")
            return pmcid

        except (PMIDNotFoundError, NoPMCIDError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Error converting PMID {pmid}: {e}")
            raise

    @retry(
        retry=retry_if_exception_type((requests.RequestException, IOError, RuntimeError, http.client.IncompleteRead)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    def validate_pmid(self, pmid: str) -> bool:
        """
        Validate that a PMID exists in PubMed.

        Args:
            pmid: PubMed ID to validate

        Returns:
            True if PMID exists, False otherwise
        """
        self.rate_limiter.acquire()

        try:
            handle = Entrez.esummary(db="pubmed", id=pmid, retmode="xml")
            record = Entrez.read(handle)
            handle.close()

            # Check if we got a valid record
            return len(record) > 0 and "error" not in str(record).lower()

        except Exception as e:
            logger.warning(f"Could not validate PMID {pmid}: {e}")
            return False
