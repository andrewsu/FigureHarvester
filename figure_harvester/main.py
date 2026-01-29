"""Command-line interface for FigureHarvester."""

import argparse
import os
import sys
from pathlib import Path
import yaml
from dotenv import load_dotenv

from .utils.logger import setup_logger
from .downloader.figure_downloader import FigureHarvester


def load_config(config_path: Path = None) -> dict:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config file (optional)

    Returns:
        Configuration dictionary
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    if not config_path.exists():
        return {}

    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def main():
    """Main CLI entry point."""
    # Load environment variables
    load_dotenv()

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Download figures from PubMed papers using PMC Open Access",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python -m figure_harvester.main pmids.txt

  # Specify output directory
  python -m figure_harvester.main pmids.txt --output ./my_figures

  # Use NCBI API key for higher rate limit
  python -m figure_harvester.main pmids.txt --api-key YOUR_API_KEY

  # Use custom config file
  python -m figure_harvester.main pmids.txt --config custom_config.yaml

  # Verbose logging
  python -m figure_harvester.main pmids.txt --verbose
        """
    )

    parser.add_argument(
        "input_file",
        type=Path,
        help="Input file containing PubMed IDs (one per line)"
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output directory for downloaded figures (default: ./figures)"
    )

    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        help="Path to config YAML file (default: config.yaml)"
    )

    parser.add_argument(
        "-e", "--email",
        type=str,
        default=None,
        help="Email address for NCBI API (required, can also use NCBI_EMAIL env var)"
    )

    parser.add_argument(
        "-k", "--api-key",
        type=str,
        default=None,
        help="NCBI API key (optional, increases rate limit to 10/sec)"
    )

    parser.add_argument(
        "-r", "--rate",
        type=float,
        default=None,
        help="Requests per second (default: 3 without API key, 10 with API key)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="FigureHarvester 1.0.0"
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Merge config with command-line arguments (CLI args take precedence)
    email = args.email or os.getenv("NCBI_EMAIL") or config.get("ncbi", {}).get("email")
    api_key = args.api_key or os.getenv("NCBI_API_KEY") or config.get("ncbi", {}).get("api_key")
    output_dir = args.output or config.get("download", {}).get("output_dir", "./figures")
    output_dir = Path(output_dir)

    # Validate email (required by NCBI)
    if not email:
        print(
            "Error: Email is required by NCBI E-utilities.\n"
            "Provide it via --email flag, NCBI_EMAIL env var, or config.yaml",
            file=sys.stderr
        )
        sys.exit(1)

    # Setup logging
    log_level = "DEBUG" if args.verbose else config.get("logging", {}).get("level", "INFO")
    log_file = config.get("logging", {}).get("file", "figure_harvester.log")

    logger = setup_logger(
        level=log_level,
        log_file=log_file,
        log_format=config.get("logging", {}).get("format"),
        max_size_mb=config.get("logging", {}).get("max_size_mb", 10)
    )

    # Determine rate limit
    if args.rate:
        requests_per_second = args.rate
    elif api_key:
        requests_per_second = 10.0
    else:
        requests_per_second = config.get("ncbi", {}).get("requests_per_second", 3.0)

    # Get other config values
    timeout = config.get("download", {}).get("timeout", 30)
    retry_attempts = config.get("download", {}).get("retry_attempts", 3)
    max_retry_attempts = config.get("resume", {}).get("max_retry_attempts", 3)
    retry_after_hours = config.get("resume", {}).get("retry_failed_after_hours", 24)

    # Log configuration
    logger.info("=" * 60)
    logger.info("FigureHarvester - PubMed Figure Downloader")
    logger.info("=" * 60)
    logger.info(f"Input file: {args.input_file}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Email: {email}")
    logger.info(f"API key: {'Yes' if api_key else 'No'}")
    logger.info(f"Rate limit: {requests_per_second} requests/sec")
    logger.info("=" * 60)

    try:
        # Initialize and run harvester
        harvester = FigureHarvester(
            input_file=args.input_file,
            output_dir=output_dir,
            email=email,
            api_key=api_key,
            requests_per_second=requests_per_second,
            timeout=timeout,
            retry_attempts=retry_attempts,
            max_retry_attempts=max_retry_attempts,
            retry_after_hours=retry_after_hours
        )

        results = harvester.run()

        # Exit with appropriate code
        if results["failed"] and not results["success"]:
            sys.exit(1)  # All failed
        elif results["failed"]:
            sys.exit(2)  # Some failed
        else:
            sys.exit(0)  # All successful

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Invalid input: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user. Progress has been saved.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
