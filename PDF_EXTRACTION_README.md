# PDF Figure Extraction Tool

A standalone tool for extracting figures from PDF files. This tool uses PyMuPDF to parse PDFs and extract images, applying intelligent filtering to identify actual figures (not logos, icons, or decorative elements).

## Features

- ✅ Batch processing of all PDFs in a directory
- ✅ Intelligent filtering based on size, aspect ratio, and position
- ✅ Optional caption detection ("Figure X", "Fig. X" patterns)
- ✅ Deduplication of repeated images
- ✅ Configurable output format (PNG or JPG)
- ✅ Detailed extraction statistics and JSON report
- ✅ Graceful error handling

## Installation

### Prerequisites

- Python 3.7+
- PyMuPDF (fitz)
- Pillow

### Install Dependencies

```bash
pip install -r requirements.txt
```

Or install specific dependencies:

```bash
pip install PyMuPDF>=1.23.0 Pillow>=10.0.0
```

## Usage

### Basic Usage

Extract figures from all PDFs in a directory:

```bash
python extract_from_pdfs.py \
  --input-dir ./pdfs \
  --output-dir ./figures
```

### Advanced Usage

#### Custom Filtering Parameters

Extract only large figures (strict filtering):

```bash
python extract_from_pdfs.py \
  --input-dir ./pdfs \
  --output-dir ./figures \
  --min-width 300 \
  --min-height 300 \
  --min-size-kb 50
```

#### With Caption Detection

Enable caption detection to find "Figure X" patterns:

```bash
python extract_from_pdfs.py \
  --input-dir ./pdfs \
  --output-dir ./figures \
  --detect-captions \
  --verbose
```

#### Output as JPEG

Save extracted figures as JPG instead of PNG:

```bash
python extract_from_pdfs.py \
  --input-dir ./pdfs \
  --output-dir ./figures \
  --format jpg
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--input-dir` | Directory containing PDF files (required) | - |
| `--output-dir` | Directory to save extracted figures (required) | - |
| `--min-width` | Minimum figure width in pixels | 200 |
| `--min-height` | Minimum figure height in pixels | 200 |
| `--min-size-kb` | Minimum file size in KB | 10 |
| `--similarity-threshold` | Perceptual hash similarity threshold (0-64) | 10 |
| `--max-white-percentage` | Max white pixels % | 60 |
| `--format` | Output format: png or jpg | png |
| `--detect-captions` | Enable caption detection | False |
| `--no-trim-whitespace` | Disable automatic whitespace trimming | False |
| `--verbose`, `-v` | Verbose logging (DEBUG level) | False |
| `--quiet`, `-q` | Quiet mode (WARNING level only) | False |

## Output

### Extracted Figures

Figures are saved with the following naming convention:

```
{pdf_name}_fig{N}.{format}
```

Examples:
- `paper1.pdf` → `paper1_fig1.png`, `paper1_fig2.png`, etc.
- `article.pdf` → `article_fig1.png`, `article_fig2.png`, etc.

### Extraction Report

A JSON report is generated at `{output_dir}/extraction_report.json`:

```json
{
  "avg_figures_per_pdf": 3.6,
  "details": [
    {
      "error": null,
      "figures": [
        "paper1_fig1.png",
        "paper1_fig2.png",
        "paper1_fig3.png"
      ],
      "figures_count": 3,
      "pdf": "paper1.pdf",
      "success": true
    }
  ],
  "failed": 0,
  "successful": 5,
  "total_figures": 18,
  "total_pdfs": 5
}
```

## Filtering Heuristics

The tool applies several filters to distinguish figures from non-figure images:

### Size Filtering
- **Minimum dimensions**: 200x200 pixels (configurable)
- **Minimum file size**: 10 KB (configurable)
- **Rationale**: Excludes logos, icons, and small decorative images

### Aspect Ratio Filtering
- **Valid range**: 0.2 to 5.0 (width/height)
- **Rationale**: Excludes extreme banners, dividers, and malformed images

### Position Filtering
- **Excluded regions**: Top 10% of first page only, bottom 10% of all pages
- **Rationale**: Removes journal headers on first page and footers/page numbers throughout document

### Deduplication
- **Method**: Perceptual hash (dHash) with Hamming distance
- **Scope**: Within each PDF
- **Threshold**: Similarity threshold of 10 (0=identical, 64=completely different)
- **Behavior**: Keeps first occurrence of each unique/similar image

### White Pixel Filtering
- **Max threshold**: 60% white pixels (configurable with `--max-white-percentage`)
- **Rationale**: Filters out intermediate PDF layers and construction artifacts

## Caption Detection (Optional)

When enabled with `--detect-captions`, the tool searches for text below each image matching these patterns:

- `Figure X`
- `Fig. X`
- `FIG. X`
- With optional colons, periods, and description text

Captions are included in the extraction report metadata but do not affect which images are extracted.

## Examples

### Example 1: Process Research Papers

```bash
# Extract from journal PDFs
python extract_from_pdfs.py \
  --input-dir ~/Downloads/research_papers \
  --output-dir ~/Documents/extracted_figures

# Output:
Found 10 PDF files
=============================================================
Processing paper1.pdf... 4 figures extracted
Processing paper2.pdf... 3 figures extracted
Processing paper3.pdf... 0 figures extracted
...

=============================================================
EXTRACTION SUMMARY
=============================================================
Total PDFs processed: 10
Successful: 10
Failed: 0
Total figures extracted: 35
Average figures per PDF: 3.5
=============================================================
```

### Example 2: Strict Filtering for High-Quality Figures

```bash
# Extract only large, high-quality figures
python extract_from_pdfs.py \
  --input-dir ./pdfs \
  --output-dir ./figures_hq \
  --min-width 400 \
  --min-height 400 \
  --min-size-kb 50 \
  --format jpg
```

### Example 3: Debug Mode

```bash
# Run with verbose logging to troubleshoot
python extract_from_pdfs.py \
  --input-dir ./pdfs \
  --output-dir ./figures \
  --verbose

# Logs include:
# - Image dimensions and file sizes
# - Reason for filtering out each image
# - Caption detection results
```

## Testing Accuracy

To evaluate extraction accuracy:

1. **Extract figures** from test PDFs
2. **Manually count** actual figures in original PDFs
3. **Count extracted** figures in output directory
4. **Calculate metrics**:
   - **Precision**: What % of extracted images are actual figures?
   - **Recall**: What % of actual figures were extracted?
   - **F1 Score**: Harmonic mean of precision and recall

Example calculation:
```
Test PDF: paper1.pdf
- Actual figures in PDF: 5
- Images extracted: 6
- Manual inspection: 5 are figures, 1 is a large logo

Metrics:
- True Positives (TP): 5
- False Positives (FP): 1
- False Negatives (FN): 0

Precision = TP / (TP + FP) = 5 / 6 = 83.3%
Recall = TP / (TP + FN) = 5 / 5 = 100%
F1 = 2 * (P * R) / (P + R) = 2 * (0.833 * 1.0) / (1.833) = 90.9%
```

## Limitations

- **Scanned PDFs**: Images from scanned PDFs will be entire page images, not individual figures
- **Encrypted PDFs**: Password-protected PDFs will fail to process
- **Vector graphics**: SVG-style vector graphics may not be extracted correctly
- **Caption detection**: Limited to English language patterns
- **Layout complexity**: Very complex layouts may confuse position filtering

## Troubleshooting

### No Figures Extracted

If no figures are extracted from PDFs that clearly contain figures:

1. **Try more permissive filtering**:
   ```bash
   python extract_from_pdfs.py \
     --input-dir ./pdfs \
     --output-dir ./figures \
     --min-width 100 \
     --min-height 100 \
     --verbose
   ```

2. **Check the verbose logs** to see why images were filtered out

3. **Manually inspect** the PDF to verify it contains extractable images (not just vector graphics or scanned pages)

### Too Many False Positives

If many non-figure images (logos, etc.) are extracted:

1. **Use stricter filtering**:
   ```bash
   python extract_from_pdfs.py \
     --input-dir ./pdfs \
     --output-dir ./figures \
     --min-width 300 \
     --min-height 300 \
     --min-size-kb 50
   ```

2. **Review the extraction report** to identify problematic PDFs

3. **Consider pre-filtering PDFs** by removing those with many small images

## Future Enhancements

Potential improvements for future versions:

- Integration with FigureHarvester for PMID-based extraction
- Machine learning-based figure classification
- Support for vector graphics extraction
- Multi-language caption detection
- Parallel processing for faster batch operations
- Web UI for manual review and correction

## License

This tool is part of the FigureHarvester project.

## Support

For issues or questions:
1. Check the verbose logs (`--verbose`)
2. Review the extraction report JSON
3. Open an issue with sample PDFs and logs
