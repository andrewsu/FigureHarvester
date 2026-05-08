"""PDF figure extraction implementation."""

import fitz  # PyMuPDF
import hashlib
import logging
from pathlib import Path
from PIL import Image
from io import BytesIO
from typing import List, Dict, Optional, Set
import re

logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extract figures from PDF files."""

    def __init__(self, config: dict):
        """
        Initialize with configuration.

        Args:
            config: Configuration dictionary with extraction parameters
        """
        self.min_width = config.get('min_width', 200)
        self.min_height = config.get('min_height', 200)
        self.min_size_kb = config.get('min_size_kb', 10)
        self.min_aspect = config.get('min_aspect_ratio', 0.2)
        self.max_aspect = config.get('max_aspect_ratio', 5.0)
        self.format = config.get('format', 'png')
        self.detect_captions = config.get('detect_captions', False)
        # Perceptual hash similarity threshold (0-64, lower = more similar)
        # 0 = identical, 10 = very similar, 20 = similar, 30+ = different
        self.similarity_threshold = config.get('similarity_threshold', 10)
        # Trim whitespace around images
        self.trim_whitespace = config.get('trim_whitespace', True)
        # Grid-based white pixel filtering
        self.use_grid_white_filter = config.get('use_grid_white_filter', True)
        self.grid_size = config.get('grid_size', 5)
        self.grid_white_threshold = config.get('grid_white_threshold', 95.0)
        self.max_white_cells = config.get('max_white_cells', 3)
        # Dominant chromatic color filter (rejects solid-background logos like
        # Science/AAAS red+white). Triggers when a single saturated color
        # dominates the image — a strong logo signature that white-pixel
        # filters miss because the background isn't white.
        self.use_dominant_color_filter = config.get('use_dominant_color_filter', True)
        self.dominant_color_frac_threshold = config.get('dominant_color_frac_threshold', 40.0)
        self.dominant_color_saturation_threshold = config.get('dominant_color_saturation_threshold', 60)
        # Save rejected figures for analysis
        self.save_rejected = config.get('save_rejected', False)
        self.rejected_dir = config.get('rejected_dir', None)

    def _compute_perceptual_hash(self, image: Image.Image) -> str:
        """
        Compute perceptual hash (difference hash) for an image.

        Uses dHash algorithm: resize to 9x8, convert to grayscale,
        compute horizontal gradient differences.

        Args:
            image: PIL Image object

        Returns:
            64-character hex string representing the hash
        """
        # Resize to 9x8 (we need 9 for 8 differences)
        img_small = image.convert('L').resize((9, 8), Image.Resampling.LANCZOS)

        # Compute horizontal gradient
        pixels = list(img_small.getdata())
        difference = []

        for row in range(8):
            for col in range(8):
                pixel_left = pixels[row * 9 + col]
                pixel_right = pixels[row * 9 + col + 1]
                difference.append(pixel_left > pixel_right)

        # Convert to hex string
        hex_string = ''
        for i in range(0, 64, 4):
            # Take 4 bits at a time and convert to hex
            nibble = (difference[i] << 3) | (difference[i+1] << 2) | \
                    (difference[i+2] << 1) | difference[i+3]
            hex_string += format(nibble, 'x')

        return hex_string

    def _hamming_distance(self, hash1: str, hash2: str) -> int:
        """
        Compute Hamming distance between two perceptual hashes.

        Args:
            hash1: First hash (hex string)
            hash2: Second hash (hex string)

        Returns:
            Number of differing bits (0-64)
        """
        if len(hash1) != len(hash2):
            return 64  # Maximum distance if lengths differ

        # Convert hex to binary and count differences
        distance = 0
        for c1, c2 in zip(hash1, hash2):
            # XOR the nibbles and count set bits
            xor = int(c1, 16) ^ int(c2, 16)
            distance += bin(xor).count('1')

        return distance

    def _trim_whitespace(self, image: Image.Image, threshold: int = 250) -> Image.Image:
        """
        Trim whitespace from around an image.

        Args:
            image: PIL Image object
            threshold: Pixel intensity threshold (0-255). Pixels brighter than
                      this are considered whitespace. Default 250.

        Returns:
            Cropped PIL Image object
        """
        # Convert to grayscale for easier whitespace detection
        if image.mode == 'RGBA':
            # For RGBA, use alpha channel to detect transparent areas too
            # Create a grayscale version from RGB channels
            gray = image.convert('L')
            # Get alpha channel
            alpha = image.split()[3] if len(image.split()) > 3 else None

            # Find bounding box based on both grayscale and alpha
            bbox = gray.point(lambda x: 0 if x > threshold else 255).getbbox()

            # If alpha channel exists, also consider it
            if alpha:
                alpha_bbox = alpha.point(lambda x: 0 if x < 5 else 255).getbbox()
                if alpha_bbox and bbox:
                    # Use the smaller bounding box (more conservative crop)
                    bbox = (
                        max(bbox[0], alpha_bbox[0]),
                        max(bbox[1], alpha_bbox[1]),
                        min(bbox[2], alpha_bbox[2]),
                        min(bbox[3], alpha_bbox[3])
                    )
                elif alpha_bbox:
                    bbox = alpha_bbox
        else:
            # For RGB, just convert to grayscale
            gray = image.convert('L')
            # Find bounding box of non-white pixels
            bbox = gray.point(lambda x: 0 if x > threshold else 255).getbbox()

        if bbox:
            # Add small margin (2 pixels) to avoid cutting too close
            margin = 2
            width, height = image.size
            bbox = (
                max(0, bbox[0] - margin),
                max(0, bbox[1] - margin),
                min(width, bbox[2] + margin),
                min(height, bbox[3] + margin)
            )

            # Only crop if the result is reasonable (at least 10x10)
            if bbox[2] - bbox[0] >= 10 and bbox[3] - bbox[1] >= 10:
                return image.crop(bbox)

        # If no valid bbox found or result too small, return original
        return image

    def _calculate_white_percentage(self, image: Image.Image, threshold: int = 250) -> float:
        """
        Calculate percentage of white pixels in an image.

        Args:
            image: PIL Image object
            threshold: Pixel intensity threshold (0-255). Pixels brighter than
                      this are considered white. Default 250.

        Returns:
            Percentage of white pixels (0-100)
        """
        # Convert to grayscale for consistent measurement
        gray = image.convert('L')
        pixels = list(gray.getdata())

        # Count white pixels
        white_count = sum(1 for p in pixels if p > threshold)
        total_pixels = len(pixels)

        if total_pixels == 0:
            return 0.0

        return (white_count / total_pixels) * 100

    def _check_white_grid(self, image: Image.Image, grid_size: int = 5,
                          white_threshold: int = 250, white_percentage_threshold: float = 95.0,
                          max_white_cells: int = 3) -> bool:
        """
        Check if image has too many mostly-white grid cells.

        Divides image into grid_size x grid_size cells and checks if more than
        max_white_cells are mostly white (>white_percentage_threshold% white pixels).

        Args:
            image: PIL Image object (should already be trimmed of border whitespace)
            grid_size: Size of grid (default 5x5 = 25 cells)
            white_threshold: Pixel intensity threshold (0-255). Default 250.
            white_percentage_threshold: Percentage threshold for "mostly white" cell. Default 95.0.
            max_white_cells: Maximum allowed mostly-white cells. Default 3.

        Returns:
            True if image should be rejected (too many white cells), False otherwise
        """
        # Convert to grayscale
        gray = image.convert('L')
        width, height = gray.size

        # Calculate cell dimensions
        cell_width = width / grid_size
        cell_height = height / grid_size

        white_cells_count = 0

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

                # Check if this cell is mostly white
                if cell_white_percentage > white_percentage_threshold:
                    white_cells_count += 1

                    # Early exit if we've exceeded the threshold
                    if white_cells_count > max_white_cells:
                        return True

        return False

    def _check_dominant_chromatic_color(self, image: Image.Image,
                                         frac_threshold: float = 40.0,
                                         saturation_threshold: int = 60,
                                         n_colors: int = 32) -> bool:
        """
        Detect flat-background logos by a single dominant saturated color.

        Quantizes to n_colors and checks the most common color. If it covers
        more than frac_threshold% of pixels AND has saturation (max-min RGB)
        above saturation_threshold, the image is a logo on a colored background
        (e.g. Science/AAAS red+white). Achromatic dominants (black/white/gray
        line art, Western blots) have saturation ~0 and pass through.

        Returns True if the image should be rejected.
        """
        rgb = image.convert('RGB')
        quantized = rgb.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        if not palette:
            return False
        pixels = list(quantized.getdata())
        if not pixels:
            return False

        # Find dominant palette index
        counts = {}
        for p in pixels:
            counts[p] = counts.get(p, 0) + 1
        dom_idx, dom_count = max(counts.items(), key=lambda kv: kv[1])
        frac = (dom_count / len(pixels)) * 100

        r, g, b = palette[dom_idx*3:dom_idx*3+3]
        saturation = max(r, g, b) - min(r, g, b)

        return frac >= frac_threshold and saturation >= saturation_threshold

    def process_directory(self, input_dir: Path, output_dir: Path) -> dict:
        """
        Process all PDFs in directory.

        Args:
            input_dir: Directory containing PDF files
            output_dir: Directory to save extracted figures

        Returns:
            dict: Summary statistics with keys:
                - total_pdfs: Total number of PDFs processed
                - successful: Number of successful extractions
                - failed: Number of failed extractions
                - total_figures: Total figures extracted
                - avg_figures_per_pdf: Average figures per successful PDF
                - details: List of per-PDF results
        """
        pdf_files = list(input_dir.glob('**/*.pdf'))
        results = {
            'total_pdfs': len(pdf_files),
            'successful': 0,
            'failed': 0,
            'total_figures': 0,
            'details': []
        }

        for pdf_path in pdf_files:
            logger.info(f"Processing {pdf_path.name}...")
            print(f"Processing {pdf_path.name}...", end=' ')

            try:
                result = self.extract_from_pdf(pdf_path, output_dir)

                if result['success']:
                    results['successful'] += 1
                    results['total_figures'] += result['figures_count']
                    print(f"{result['figures_count']} figures extracted")
                else:
                    results['failed'] += 1
                    print(f"Failed: {result['error']}")

                results['details'].append({
                    'pdf': pdf_path.name,
                    'success': result['success'],
                    'figures_count': result['figures_count'],
                    'figures': result.get('figures', []),
                    'error': result.get('error')
                })

            except Exception as e:
                results['failed'] += 1
                logger.error(f"Unexpected error processing {pdf_path.name}: {e}")
                print(f"Error: {str(e)}")
                results['details'].append({
                    'pdf': pdf_path.name,
                    'success': False,
                    'figures_count': 0,
                    'error': str(e)
                })

        # Calculate average
        if results['successful'] > 0:
            results['avg_figures_per_pdf'] = results['total_figures'] / results['successful']
        else:
            results['avg_figures_per_pdf'] = 0.0

        return results

    def extract_from_pdf(self, pdf_path: Path, output_dir: Path) -> dict:
        """
        Extract figures from single PDF.

        Args:
            pdf_path: Path to PDF file
            output_dir: Directory to save figures

        Returns:
            dict: Result with keys:
                - success: Whether extraction succeeded
                - figures_count: Number of figures extracted
                - figures: List of saved figure filenames
                - error: Error message if failed
        """
        try:
            # Open PDF
            doc = fitz.open(pdf_path)

            # Extract figures
            figures = self._extract_images_from_pdf(doc, pdf_path.stem)

            doc.close()

            if not figures:
                return {
                    'success': True,
                    'figures_count': 0,
                    'figures': [],
                    'error': 'No figures found'
                }

            # Save figures
            saved_figures = []
            for idx, figure in enumerate(figures, 1):
                output_filename = f"{pdf_path.stem}_fig{idx}.{self.format}"
                output_path = output_dir / output_filename

                self._save_figure(figure['data'], output_path)
                saved_figures.append(output_filename)

                logger.debug(f"Saved {output_filename}")

            return {
                'success': True,
                'figures_count': len(saved_figures),
                'figures': saved_figures
            }

        except Exception as e:
            logger.error(f"Error extracting from {pdf_path.name}: {e}")
            return {
                'success': False,
                'figures_count': 0,
                'error': str(e)
            }

    def _extract_images_from_pdf(self, doc, pdf_name: str) -> List[dict]:
        """
        Extract and filter images from PDF document.

        Args:
            doc: PyMuPDF document object
            pdf_name: Name of PDF file (for logging)

        Returns:
            List of figure dictionaries
        """
        figures = []
        # Store perceptual hashes as dict {hash: figure_index}
        seen_hashes = {}

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_height = page.rect.height
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                try:
                    figure = self._process_image(
                        doc, page, page_num, img_info,
                        pdf_name, page_height, seen_hashes
                    )
                    if figure:
                        figures.append(figure)
                except Exception as e:
                    logger.warning(f"Failed to process image {img_index} on page {page_num}: {e}")
                    continue

        return figures

    def _process_image(self, doc, page, page_num: int, img_info: tuple,
                      pdf_name: str, page_height: float, seen_hashes: Dict[str, int]) -> Optional[dict]:
        """
        Process single image with filters.

        Args:
            doc: PyMuPDF document
            page: PyMuPDF page object
            page_num: Page number (0-indexed)
            img_info: Image info tuple from get_images()
            pdf_name: PDF filename for logging
            page_height: Height of page for position filtering
            seen_hashes: Dict of perceptual hashes -> figure index for deduplication

        Returns:
            Figure dictionary or None if filtered out
        """
        xref = img_info[0]

        # Extract image data
        base_image = doc.extract_image(xref)
        image_bytes = base_image["image"]

        # Open with Pillow for analysis
        image = Image.open(BytesIO(image_bytes))
        width, height = image.size

        # Compute perceptual hash for similarity detection
        perceptual_hash = self._compute_perceptual_hash(image)

        # Check for similar images using perceptual hash
        for existing_hash, fig_idx in seen_hashes.items():
            distance = self._hamming_distance(perceptual_hash, existing_hash)
            if distance <= self.similarity_threshold:
                logger.debug(f"Skipping similar image (distance: {distance}, threshold: {self.similarity_threshold})")
                return None

        # Size filters
        if width < self.min_width or height < self.min_height:
            logger.debug(f"Skipping small image: {width}x{height}")
            return None

        if len(image_bytes) < self.min_size_kb * 1024:
            logger.debug(f"Skipping small file: {len(image_bytes)} bytes")
            return None

        # Aspect ratio filter
        aspect_ratio = width / height
        if aspect_ratio < self.min_aspect or aspect_ratio > self.max_aspect:
            logger.debug(f"Skipping odd aspect ratio: {aspect_ratio:.2f}")
            return None

        # Position filter (exclude header on first page only, footer on all pages)
        image_rects = page.get_image_rects(xref)
        if image_rects:
            rect = image_rects[0]
            # Only apply header filter to first page (page_num == 0)
            if page_num == 0 and rect.y0 < page_height * 0.1:
                logger.debug(f"Skipping header image on first page")
                return None
            # Apply footer filter to all pages
            if rect.y1 > page_height * 0.9:
                logger.debug(f"Skipping footer image")
                return None

        # Convert to target format
        if self.format == 'png' and image.mode not in ['RGBA', 'RGB']:
            image = image.convert('RGBA')
        elif self.format == 'jpg' and image.mode not in ['RGB', 'L']:
            image = image.convert('RGB')

        # Trim whitespace BEFORE white pixel filtering
        trimmed_image = image
        if self.trim_whitespace:
            original_size = image.size
            trimmed_image = self._trim_whitespace(image)
            if trimmed_image.size != original_size:
                logger.debug(f"Trimmed whitespace: {original_size} -> {trimmed_image.size}")

        # Grid-based white pixel filter (applied to trimmed image)
        if self.use_grid_white_filter:
            if self._check_white_grid(trimmed_image, self.grid_size,
                                     white_percentage_threshold=self.grid_white_threshold,
                                     max_white_cells=self.max_white_cells):
                logger.debug(f"Skipping image with too many white grid cells")
                # Save rejected image if configured
                if self.save_rejected and self.rejected_dir:
                    self._save_rejected_figure(trimmed_image, pdf_name, page_num, xref)
                return None

        # Dominant chromatic color filter (catches solid-background logos)
        if self.use_dominant_color_filter:
            if self._check_dominant_chromatic_color(
                    trimmed_image,
                    frac_threshold=self.dominant_color_frac_threshold,
                    saturation_threshold=self.dominant_color_saturation_threshold):
                logger.debug("Skipping image dominated by a single saturated color (logo)")
                if self.save_rejected and self.rejected_dir:
                    self._save_rejected_figure(trimmed_image, pdf_name, page_num, xref)
                return None

        # Update dimensions after trimming
        width, height = trimmed_image.size
        image = trimmed_image

        # Detect caption if enabled
        caption = None
        if self.detect_captions and image_rects:
            caption = self._detect_caption(page, image_rects[0])

        # Save to bytes
        output = BytesIO()
        save_kwargs = {'format': self.format.upper()}
        if self.format == 'jpg':
            save_kwargs['quality'] = 95
        image.save(output, **save_kwargs)
        final_bytes = output.getvalue()

        # Store perceptual hash for future similarity checks
        seen_hashes[perceptual_hash] = len(seen_hashes)

        return {
            'data': final_bytes,
            'page_number': page_num + 1,
            'width': width,
            'height': height,
            'caption': caption
        }

    def _detect_caption(self, page, image_rect) -> Optional[str]:
        """
        Detect caption text near image.

        Args:
            page: PyMuPDF page object
            image_rect: Rectangle containing the image

        Returns:
            Caption text or None if not detected
        """
        try:
            # Search below image
            search_rect = fitz.Rect(
                image_rect.x0,
                image_rect.y1,
                image_rect.x1,
                image_rect.y1 + 100  # 100 points below
            )

            text = page.get_text("text", clip=search_rect)

            # Look for figure caption patterns
            patterns = [
                r'(Fig(?:ure)?\.?\s+\d+[A-Z]?\.?\s*[:-]?\s*.{0,200})',
                r'(Figure\s+\d+\.?\s*.{0,200})',
                r'(FIG\.?\s+\d+\.?\s*.{0,200})'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

            return None

        except Exception as e:
            logger.debug(f"Caption detection failed: {e}")
            return None

    def _save_figure(self, figure_data: bytes, output_path: Path):
        """
        Save figure to disk.

        Args:
            figure_data: Binary image data
            output_path: Path to save file
        """
        with open(output_path, 'wb') as f:
            f.write(figure_data)

    def _save_rejected_figure(self, image: Image.Image, pdf_name: str, page_num: int, xref: int):
        """
        Save a rejected figure for analysis.

        Args:
            image: PIL Image object
            pdf_name: PDF filename stem
            page_num: Page number (0-indexed)
            xref: Image xref number
        """
        if not self.rejected_dir:
            return

        try:
            # Create rejected directory if it doesn't exist
            self.rejected_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename
            filename = f"{pdf_name}_page{page_num+1}_xref{xref}.{self.format}"
            output_path = self.rejected_dir / filename

            # Save image
            save_kwargs = {'format': self.format.upper()}
            if self.format == 'jpg':
                save_kwargs['quality'] = 95
            image.save(output_path, **save_kwargs)

            logger.debug(f"Saved rejected figure: {filename}")
        except Exception as e:
            logger.warning(f"Failed to save rejected figure: {e}")
