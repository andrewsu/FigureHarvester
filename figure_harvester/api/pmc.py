"""PMC API wrapper for fetching article metadata and figure URLs."""

import logging
import re
from typing import List, Optional
from lxml import etree
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from .rate_limiter import RateLimiter


logger = logging.getLogger(__name__)


class NotOpenAccessError(Exception):
    """Raised when article is not in PMC Open Access subset."""
    pass


class NoFiguresError(Exception):
    """Raised when article has no figures."""
    pass


class PMCAPI:
    """
    Wrapper for PMC API to fetch article metadata and figure URLs.

    Extracts figure URLs from PMC Open Access articles.
    """

    PMC_BASE_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles"
    PMC_EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    PMC_OA_SERVICE_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
    EUROPEPMC_RENDER_URL = "https://europepmc.org/backend/ptpmcrender.fcgi"

    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        """
        Initialize PMC API wrapper.

        Args:
            rate_limiter: Rate limiter instance (optional)
        """
        self.rate_limiter = rate_limiter or RateLimiter(requests_per_second=3.0)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'FigureHarvester/1.0 (Python requests)'
        })

    @retry(
        retry=retry_if_exception_type((requests.RequestException, RuntimeError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    def check_open_access(self, pmcid: str) -> bool:
        """
        Check if a PMC article is in the Open Access subset.

        Args:
            pmcid: PMC ID (e.g., "PMC1234567" or "1234567")

        Returns:
            True if article is Open Access, False otherwise

        Raises:
            NotOpenAccessError: If article is not in Open Access subset
            requests.RequestException: On network errors
        """
        self.rate_limiter.acquire()

        pmcid_clean = pmcid.replace("PMC", "")
        url = f"{self.PMC_OA_SERVICE_URL}?id=PMC{pmcid_clean}"

        logger.debug(f"Checking Open Access status for {pmcid}")

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        # Check for error in XML response
        if 'idIsNotOpenAccess' in response.text:
            logger.warning(f"{pmcid} is not in PMC Open Access subset")
            raise NotOpenAccessError(
                f"{pmcid} is not in PMC Open Access subset. "
                f"Figures are not available for programmatic download."
            )

        logger.debug(f"{pmcid} is Open Access")
        return True

    @retry(
        retry=retry_if_exception_type((requests.RequestException, RuntimeError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    def fetch_article_xml(self, pmcid: str) -> str:
        """
        Fetch article XML from PMC using efetch.

        Args:
            pmcid: PMC ID (e.g., "PMC1234567" or "1234567")

        Returns:
            Article XML as string

        Raises:
            NotOpenAccessError: If article is not in Open Access subset
            requests.RequestException: On network errors
        """
        # Remove "PMC" prefix if present
        pmcid_num = pmcid.replace("PMC", "")

        self.rate_limiter.acquire()

        logger.debug(f"Fetching XML for {pmcid}")

        url = f"{self.PMC_EUTILS_URL}/efetch.fcgi"
        params = {
            "db": "pmc",
            "id": pmcid_num,
            "retmode": "xml"
        }

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()

        # Check if article is in Open Access subset
        if "error" in response.text.lower() or len(response.text) < 100:
            raise NotOpenAccessError(
                f"{pmcid} is not available in PMC Open Access subset"
            )

        return response.text

    def extract_figure_urls_from_xml(self, pmcid: str, xml_content: str) -> List[str]:
        """
        Extract figure URLs from PMC article XML.

        Args:
            pmcid: PMC ID
            xml_content: Article XML content

        Returns:
            List of figure URLs

        Raises:
            NoFiguresError: If no figures found in article
        """
        logger.debug(f"Extracting figure URLs from {pmcid}")

        try:
            root = etree.fromstring(xml_content.encode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse XML for {pmcid}: {e}")
            raise NoFiguresError(f"Could not parse XML for {pmcid}")

        # Find all graphic elements (figures)
        # PMC XML uses <graphic> tags with xlink:href attributes
        namespaces = {
            'xlink': 'http://www.w3.org/1999/xlink'
        }

        figure_urls = []

        # Look for graphic elements
        graphics = root.xpath('.//graphic[@xlink:href]', namespaces=namespaces)

        for graphic in graphics:
            href = graphic.get('{http://www.w3.org/1999/xlink}href')
            if href:
                logger.debug(f"Found graphic href: {href}")

                # Ensure href has image extension
                if not any(href.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff']):
                    # Try adding .jpg extension (most common)
                    href = f"{href}.jpg"

                # Use Europe PMC render service (more reliable than NCBI bin path)
                figure_url = f"{self.EUROPEPMC_RENDER_URL}?acc={pmcid}&blobtype=image&blobname={href}"
                logger.debug(f"Constructed URL: {figure_url}")
                figure_urls.append(figure_url)

        if not figure_urls:
            raise NoFiguresError(f"No figures found in {pmcid}")

        logger.info(f"Found {len(figure_urls)} figures in {pmcid}")
        return figure_urls

    @retry(
        retry=retry_if_exception_type((requests.RequestException, RuntimeError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    def extract_figure_urls_from_html(self, pmcid: str) -> List[str]:
        """
        Extract figure URLs by parsing PMC article HTML page.

        This is a fallback method if XML parsing fails.

        Args:
            pmcid: PMC ID

        Returns:
            List of figure URLs

        Raises:
            NoFiguresError: If no figures found
            requests.RequestException: On network errors
        """
        self.rate_limiter.acquire()

        pmcid_num = pmcid.replace("PMC", "")
        url = f"{self.PMC_BASE_URL}/PMC{pmcid_num}/"

        logger.debug(f"Fetching HTML for {pmcid}")

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        html_content = response.text

        # Extract figure URLs using regex
        # Look for patterns like: /pmc/articles/PMC1234567/bin/filename.jpg
        pattern = rf'/pmc/articles/PMC{pmcid_num}/bin/[^"\s]+?\.(jpg|jpeg|png|gif|tif|tiff)'
        matches = re.findall(pattern, html_content, re.IGNORECASE)

        if not matches:
            raise NoFiguresError(f"No figures found in {pmcid}")

        # Build full URLs
        figure_urls = []
        seen = set()
        for match in matches:
            # match is a tuple (url_without_extension, extension)
            # We need to reconstruct the full path
            pass

        # Better approach: find all src and href attributes pointing to figures
        img_pattern = r'(https?://[^"\s]+/pmc/articles/PMC[0-9]+/bin/[^"\s]+?\.(jpg|jpeg|png|gif|tif|tiff))'
        rel_pattern = r'(/pmc/articles/PMC[0-9]+/bin/[^"\s]+?\.(jpg|jpeg|png|gif|tif|tiff))'

        # Find absolute URLs
        abs_matches = re.findall(img_pattern, html_content, re.IGNORECASE)
        for url, ext in abs_matches:
            if url not in seen:
                figure_urls.append(url)
                seen.add(url)

        # Find relative URLs and convert to absolute
        rel_matches = re.findall(rel_pattern, html_content, re.IGNORECASE)
        for url, ext in rel_matches:
            full_url = f"https://www.ncbi.nlm.nih.gov{url}"
            if full_url not in seen:
                figure_urls.append(full_url)
                seen.add(full_url)

        if not figure_urls:
            raise NoFiguresError(f"No figures found in {pmcid}")

        logger.info(f"Found {len(figure_urls)} figures in {pmcid}")
        return figure_urls

    def get_figure_urls(self, pmcid: str) -> List[str]:
        """
        Get figure URLs for a PMC article.

        Checks Open Access status first, then tries XML parsing,
        falls back to HTML parsing if that fails.

        Args:
            pmcid: PMC ID

        Returns:
            List of figure URLs

        Raises:
            NotOpenAccessError: If article is not in Open Access subset
            NoFiguresError: If no figures found
        """
        # First check if article is in Open Access subset
        self.check_open_access(pmcid)

        try:
            # Try XML first
            xml_content = self.fetch_article_xml(pmcid)
            return self.extract_figure_urls_from_xml(pmcid, xml_content)
        except NoFiguresError:
            # If no figures in XML, try HTML as fallback
            logger.info(f"No figures in XML for {pmcid}, trying HTML parsing")
            return self.extract_figure_urls_from_html(pmcid)
        except NotOpenAccessError:
            # Re-raise this - it's a fatal error
            raise
        except Exception as e:
            # If XML fails for other reasons, try HTML
            logger.warning(f"XML parsing failed for {pmcid}: {e}, trying HTML")
            return self.extract_figure_urls_from_html(pmcid)
