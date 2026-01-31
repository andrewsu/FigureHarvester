#!/usr/bin/env python3
"""
Analyze rejected figures to show grid-based white pixel analysis.

Usage:
    python analyze_rejected.py <rejected_dir>
"""

import sys
from pathlib import Path
from PIL import Image


def analyze_white_grid(image_path: Path, grid_size: int = 5, white_threshold: int = 250,
                       white_percentage_threshold: float = 95.0):
    """
    Analyze a single image using grid-based white pixel detection.

    Args:
        image_path: Path to image file
        grid_size: Size of grid (default 5x5)
        white_threshold: Pixel intensity threshold (0-255)
        white_percentage_threshold: Percentage threshold for "mostly white" cell

    Returns:
        dict with analysis results
    """
    try:
        image = Image.open(image_path)
        gray = image.convert('L')
        width, height = gray.size

        # Calculate cell dimensions
        cell_width = width / grid_size
        cell_height = height / grid_size

        white_cells = []
        cell_percentages = []

        for row in range(grid_size):
            for col in range(grid_size):
                # Define cell boundaries
                left = int(col * cell_width)
                top = int(row * cell_height)
                right = int((col + 1) * cell_width)
                bottom = int((row + 1) * cell_height)

                # Crop to cell
                cell = gray.crop((left, top, right, bottom))

                # Calculate white percentage in this cell
                pixels = list(cell.getdata())
                if not pixels:
                    continue

                white_count = sum(1 for p in pixels if p > white_threshold)
                cell_white_percentage = (white_count / len(pixels)) * 100
                cell_percentages.append(cell_white_percentage)

                # Check if this cell is mostly white
                if cell_white_percentage > white_percentage_threshold:
                    white_cells.append((row, col, cell_white_percentage))

        return {
            'path': image_path,
            'dimensions': (width, height),
            'white_cells_count': len(white_cells),
            'white_cells': white_cells,
            'all_percentages': cell_percentages,
            'would_reject': len(white_cells) > 3  # max_white_cells = 3
        }

    except Exception as e:
        return {
            'path': image_path,
            'error': str(e)
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_rejected.py <rejected_dir>")
        return 1

    rejected_dir = Path(sys.argv[1])

    if not rejected_dir.exists():
        print(f"Error: Directory not found: {rejected_dir}")
        return 1

    # Find all PNG files
    image_files = sorted(rejected_dir.glob('*.png'))

    if not image_files:
        print(f"No PNG files found in {rejected_dir}")
        return 0

    print(f"\n{'='*80}")
    print(f"REJECTED FIGURES ANALYSIS")
    print(f"{'='*80}\n")
    print(f"Analyzing {len(image_files)} rejected figures")
    print(f"Grid: 5x5 (25 cells per image)")
    print(f"White threshold: >95% white pixels per cell")
    print(f"Rejection criteria: >3 cells exceed threshold\n")
    print(f"{'='*80}\n")

    for image_path in image_files:
        result = analyze_white_grid(image_path)

        if 'error' in result:
            print(f"\n❌ {image_path.name}")
            print(f"   Error: {result['error']}")
            continue

        print(f"\n{'─'*80}")
        print(f"📄 {image_path.name}")
        print(f"   Dimensions: {result['dimensions'][0]}x{result['dimensions'][1]} pixels")
        print(f"   White cells (>95% white): {result['white_cells_count']}/25")
        print(f"   Status: {'✅ REJECTED (>3 white cells)' if result['would_reject'] else '⚠️  SHOULD NOT REJECT'}")

        if result['white_cells']:
            print(f"\n   White cells at positions:")
            for row, col, percentage in result['white_cells']:
                print(f"      - Cell [{row},{col}]: {percentage:.1f}% white")

        # Show grid visualization
        print(f"\n   Grid visualization (X = >95% white):")
        print(f"   ┌─────────────┐")
        for row in range(5):
            line = "   │ "
            for col in range(5):
                is_white = any(r == row and c == col for r, c, _ in result['white_cells'])
                line += "X " if is_white else "· "
            line += "│"
            print(line)
        print(f"   └─────────────┘")

    print(f"\n{'='*80}\n")

    # Summary
    total = len(image_files)
    correctly_rejected = sum(1 for f in image_files
                            if analyze_white_grid(f)['would_reject'])

    print(f"SUMMARY:")
    print(f"  Total rejected figures: {total}")
    print(f"  Correctly rejected (>3 white cells): {correctly_rejected}")
    print(f"  Incorrectly rejected (≤3 white cells): {total - correctly_rejected}")
    print()


if __name__ == '__main__':
    sys.exit(main())
