#!/usr/bin/env python3
"""
Standalone tool to extract figures from PDF files.

Usage:
    python extract_from_pdfs.py --input-dir ./pdfs --output-dir ./figures

This tool extracts figures from all PDF files in a directory using PyMuPDF.
It applies filtering heuristics to extract only actual figures (not logos,
icons, or other small images).
"""

import argparse
import logging
import sys
import json
from pathlib import Path

# Add current directory to path so pdf_extractor can be imported
sys.path.insert(0, str(Path(__file__).parent))

from pdf_extractor.extractor import PDFExtractor


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Extract figures from PDF files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic extraction
  python extract_from_pdfs.py --input-dir ./pdfs --output-dir ./figures

  # With custom filtering
  python extract_from_pdfs.py --input-dir ./pdfs --output-dir ./figures \\
    --min-width 300 --min-height 300 --format jpg

  # With caption detection and verbose output
  python extract_from_pdfs.py --input-dir ./pdfs --output-dir ./figures \\
    --detect-captions --verbose
"""
    )

    # Required arguments
    parser.add_argument(
        '--input-dir',
        required=True,
        type=Path,
        help='Directory containing PDF files'
    )
    parser.add_argument(
        '--output-dir',
        required=True,
        type=Path,
        help='Directory to save extracted figures'
    )

    # Filtering options
    parser.add_argument(
        '--min-width',
        type=int,
        default=200,
        help='Minimum figure width in pixels (default: 200)'
    )
    parser.add_argument(
        '--min-height',
        type=int,
        default=200,
        help='Minimum figure height in pixels (default: 200)'
    )
    parser.add_argument(
        '--min-size-kb',
        type=int,
        default=10,
        help='Minimum file size in KB (default: 10)'
    )
    parser.add_argument(
        '--similarity-threshold',
        type=int,
        default=10,
        help='Perceptual hash similarity threshold (0-64, lower=stricter). '
             '0=identical, 10=very similar, 20=similar, 30+=different (default: 10)'
    )
    parser.add_argument(
        '--max-white-percentage',
        type=int,
        default=60,
        help='Maximum percentage of white pixels (0-100). Images with more white '
             'pixels are skipped (helps filter PDF layers and artifacts, default: 60)'
    )

    # Output options
    parser.add_argument(
        '--format',
        choices=['png', 'jpg'],
        default='png',
        help='Output image format (default: png)'
    )

    # Feature flags
    parser.add_argument(
        '--detect-captions',
        action='store_true',
        help='Enable caption detection (looks for "Figure X" patterns)'
    )
    parser.add_argument(
        '--no-trim-whitespace',
        action='store_true',
        help='Disable automatic whitespace trimming around figures'
    )

    # Logging
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose logging (DEBUG level)'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Quiet mode (WARNING level only)'
    )

    args = parser.parse_args()

    # Setup logging
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger(__name__)

    # Validate input directory
    if not args.input_dir.exists():
        logger.error(f"Input directory does not exist: {args.input_dir}")
        return 1

    if not args.input_dir.is_dir():
        logger.error(f"Input path is not a directory: {args.input_dir}")
        return 1

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {args.output_dir}")

    # Set up rejected figures directory
    rejected_dir = args.output_dir / 'rejected'

    # Initialize extractor
    config = {
        'min_width': args.min_width,
        'min_height': args.min_height,
        'min_size_kb': args.min_size_kb,
        'similarity_threshold': args.similarity_threshold,
        'max_white_percentage': args.max_white_percentage,
        'format': args.format,
        'detect_captions': args.detect_captions,
        'trim_whitespace': not args.no_trim_whitespace,
        'use_grid_white_filter': True,  # Enable grid-based white filtering
        'grid_size': 5,
        'grid_white_threshold': 95.0,
        'max_white_cells': 10,  # Changed from 3 to 10
        'save_rejected': True,  # Save rejected figures
        'rejected_dir': rejected_dir
    }

    logger.debug(f"Extractor configuration: {config}")
    extractor = PDFExtractor(config)

    # Find PDFs
    pdf_files = list(args.input_dir.glob('**/*.pdf'))
    if not pdf_files:
        logger.warning(f"No PDF files found in {args.input_dir}")
        print(f"No PDF files found in {args.input_dir}")
        return 0

    print(f"\nFound {len(pdf_files)} PDF file(s)")
    print("=" * 60)

    # Process all PDFs
    results = extractor.process_directory(args.input_dir, args.output_dir)

    # Print summary
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"Total PDFs processed: {results['total_pdfs']}")
    print(f"Successful: {results['successful']}")
    print(f"Failed: {results['failed']}")
    print(f"Total figures extracted: {results['total_figures']}")

    if results['successful'] > 0:
        print(f"Average figures per PDF: {results['avg_figures_per_pdf']:.1f}")
    else:
        print("No PDFs were successfully processed")

    print("=" * 60)

    # Save detailed report
    report_path = args.output_dir / 'extraction_report.json'
    with open(report_path, 'w') as f:
        json.dump(results, f, indent=2, sort_keys=True)

    print(f"\nDetailed report saved to: {report_path}")
    print(f"Extracted figures saved to: {args.output_dir}")

    # Return appropriate exit code
    if results['failed'] > 0 and results['successful'] == 0:
        logger.error("All PDF extractions failed")
        return 1
    elif results['failed'] > 0:
        logger.warning(f"{results['failed']} PDF(s) failed to process")

    return 0


if __name__ == '__main__':
    sys.exit(main())
