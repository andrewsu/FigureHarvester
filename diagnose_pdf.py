#!/usr/bin/env python3
"""
Diagnostic tool to analyze why a PDF isn't extracting figures.

Usage:
    python diagnose_pdf.py <pdf_path>

This script will show all images found in the PDF and which filters
are rejecting them.
"""

import sys
import argparse
from pathlib import Path
from io import BytesIO
import fitz  # PyMuPDF
from PIL import Image

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))


def calculate_white_percentage(image: Image.Image, threshold: int = 250) -> float:
    """Calculate percentage of white pixels in an image."""
    gray = image.convert('L')
    pixels = list(gray.getdata())
    white_count = sum(1 for p in pixels if p > threshold)
    total_pixels = len(pixels)
    if total_pixels == 0:
        return 0.0
    return (white_count / total_pixels) * 100


def diagnose_pdf(pdf_path: Path, min_width: int = 200, min_height: int = 200,
                 min_size_kb: int = 10, min_aspect: float = 0.2,
                 max_aspect: float = 5.0, max_white_percentage: float = 60.0):
    """Analyze all images in a PDF and show why they're filtered."""

    print(f"\n{'='*80}")
    print(f"Analyzing: {pdf_path.name}")
    print(f"{'='*80}\n")

    print("Filter settings:")
    print(f"  Min dimensions: {min_width}x{min_height} pixels")
    print(f"  Min file size: {min_size_kb} KB")
    print(f"  Aspect ratio range: {min_aspect} - {max_aspect}")
    print(f"  Max white percentage: {max_white_percentage}%")
    print(f"  Header/footer exclusion: top 10% of first page only, bottom 10% of all pages")
    print()

    try:
        doc = fitz.open(pdf_path)
        total_images = 0
        passed_all_filters = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_height = page.rect.height
            image_list = page.get_images(full=True)

            if not image_list:
                continue

            print(f"\n--- Page {page_num + 1} ({len(image_list)} images) ---")

            for img_index, img_info in enumerate(image_list):
                total_images += 1
                xref = img_info[0]

                print(f"\n  Image {img_index + 1}:")

                # Extract image data
                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image = Image.open(BytesIO(image_bytes))
                    width, height = image.size
                    file_size_kb = len(image_bytes) / 1024
                    aspect_ratio = width / height
                    white_percentage = calculate_white_percentage(image)

                    print(f"    Dimensions: {width}x{height} pixels")
                    print(f"    File size: {file_size_kb:.1f} KB")
                    print(f"    Aspect ratio: {aspect_ratio:.2f}")
                    print(f"    White pixels: {white_percentage:.1f}%")

                    # Check position
                    image_rects = page.get_image_rects(xref)
                    if image_rects:
                        rect = image_rects[0]
                        y0_percent = (rect.y0 / page_height) * 100
                        y1_percent = (rect.y1 / page_height) * 100
                        print(f"    Position: {y0_percent:.1f}% - {y1_percent:.1f}% from top")

                    # Apply filters
                    filters_failed = []

                    if width < min_width or height < min_height:
                        filters_failed.append(f"Size too small ({width}x{height} < {min_width}x{min_height})")

                    if file_size_kb < min_size_kb:
                        filters_failed.append(f"File too small ({file_size_kb:.1f} KB < {min_size_kb} KB)")

                    if aspect_ratio < min_aspect or aspect_ratio > max_aspect:
                        filters_failed.append(f"Aspect ratio out of range ({aspect_ratio:.2f} not in {min_aspect}-{max_aspect})")

                    if white_percentage > max_white_percentage:
                        filters_failed.append(f"Too many white pixels ({white_percentage:.1f}% > {max_white_percentage}%)")

                    if image_rects:
                        rect = image_rects[0]
                        # Header filter only applies to first page (page_num == 0)
                        if page_num == 0 and rect.y0 < page_height * 0.1:
                            filters_failed.append(f"In header region on first page (y0={y0_percent:.1f}% < 10%)")
                        # Footer filter applies to all pages
                        if rect.y1 > page_height * 0.9:
                            filters_failed.append(f"In footer region (y1={y1_percent:.1f}% > 90%)")

                    if filters_failed:
                        print(f"    Status: ❌ REJECTED")
                        for reason in filters_failed:
                            print(f"      - {reason}")
                    else:
                        print(f"    Status: ✅ PASSED all filters")
                        passed_all_filters += 1

                except Exception as e:
                    print(f"    Status: ❌ ERROR extracting image: {e}")

        doc.close()

        print(f"\n{'='*80}")
        print(f"SUMMARY")
        print(f"{'='*80}")
        print(f"Total images found: {total_images}")
        print(f"Passed all filters: {passed_all_filters}")
        print(f"Rejected: {total_images - passed_all_filters}")
        print()

    except Exception as e:
        print(f"ERROR: Failed to analyze PDF: {e}")
        return 1

    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Diagnose why a PDF is not extracting figures',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'pdf_path',
        type=Path,
        help='Path to PDF file to analyze'
    )
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
        '--max-white-percentage',
        type=float,
        default=60.0,
        help='Maximum percentage of white pixels (default: 60.0)'
    )

    args = parser.parse_args()

    if not args.pdf_path.exists():
        print(f"ERROR: PDF file not found: {args.pdf_path}")
        return 1

    return diagnose_pdf(
        args.pdf_path,
        min_width=args.min_width,
        min_height=args.min_height,
        min_size_kb=args.min_size_kb,
        max_white_percentage=args.max_white_percentage
    )


if __name__ == '__main__':
    sys.exit(main())
