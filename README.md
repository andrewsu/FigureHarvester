# FigureHarvester

A Python tool to download figures from PubMed papers using the PubMed Central (PMC) Open Access subset.

## Features

- Download figures from PMC Open Access articles using PubMed IDs
- Automatic PMID to PMCID conversion
- Rate limiting to respect NCBI API guidelines (3 req/sec default, 10 req/sec with API key)
- Resume capability - skip already downloaded figures
- Progress tracking with progress bars
- Comprehensive error reporting
- Retry logic with exponential backoff
- Configurable via YAML or command-line arguments

## Requirements

- Python 3.7 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/andrewsu/FigureHarvester.git
cd FigureHarvester
```

2. Install dependencies:
```bash
pip3 install -r requirements.txt
```

Note: If your system uses `python` for Python 3, you can use `pip install` instead. Throughout this README, replace `python3` with `python` if needed.

3. (Optional) Get an NCBI API key for higher rate limits:
   - Visit https://www.ncbi.nlm.nih.gov/account/settings/
   - Create an account and generate an API key
   - This increases your rate limit from 3 to 10 requests per second

## Quick Start

1. Create a text file with PubMed IDs (one per line):
```
16129776
20301613
25378319
```

2. Run the harvester:
```bash
python3 -m figure_harvester.main pmids.txt --email your_email@example.com
```

Figures will be downloaded to the `./figures` directory with names like:
- `PMID_16129776_fig1.jpg`
- `PMID_16129776_fig2.png`
- `PMID_20301613_fig1.jpg`

## Configuration

### Using config.yaml

Edit `config.yaml` to set default values:

```yaml
ncbi:
  email: "your_email@example.com"
  api_key: null
  requests_per_second: 3

download:
  output_dir: "./figures"
  timeout: 30
  retry_attempts: 3

resume:
  manifest_file: "manifest.json"
  max_retry_attempts: 3
  retry_failed_after_hours: 24

logging:
  level: "INFO"
  file: "figure_harvester.log"
```

### Using environment variables

Create a `.env` file:
```bash
NCBI_EMAIL=your_email@example.com
NCBI_API_KEY=your_api_key_here
```

### Command-line arguments

Command-line arguments override config file settings:

```bash
python3 -m figure_harvester.main pmids.txt \
  --email your_email@example.com \
  --api-key YOUR_API_KEY \
  --output ./my_figures \
  --rate 10 \
  --verbose
```

## Usage Examples

### Basic usage
```bash
python3 -m figure_harvester.main pmids.txt --email your@email.com
```

### Specify output directory
```bash
python3 -m figure_harvester.main pmids.txt --output ./my_figures --email your@email.com
```

### Use API key for higher rate limit
```bash
python3 -m figure_harvester.main pmids.txt --api-key YOUR_KEY --email your@email.com
```

### Custom config file
```bash
python3 -m figure_harvester.main pmids.txt --config custom_config.yaml
```

### Verbose logging
```bash
python3 -m figure_harvester.main pmids.txt --verbose --email your@email.com
```

### Resume interrupted download
Simply re-run the same command. The tool automatically:
- Skips PMIDs that were successfully downloaded
- Retries failed PMIDs (up to 3 attempts)
- Uses `manifest.json` to track progress

```bash
# Run once
python3 -m figure_harvester.main pmids.txt --email your@email.com

# If interrupted (Ctrl+C), just run again
python3 -m figure_harvester.main pmids.txt --email your@email.com
```

## Command-Line Options

```
positional arguments:
  input_file            Input file containing PubMed IDs (one per line)

optional arguments:
  -h, --help            Show help message and exit
  -o OUTPUT, --output OUTPUT
                        Output directory for downloaded figures (default: ./figures)
  -c CONFIG, --config CONFIG
                        Path to config YAML file (default: config.yaml)
  -e EMAIL, --email EMAIL
                        Email address for NCBI API (required)
  -k API_KEY, --api-key API_KEY
                        NCBI API key (optional, increases rate limit)
  -r RATE, --rate RATE  Requests per second (default: 3 without API key, 10 with)
  -v, --verbose         Enable verbose (DEBUG) logging
  --version             Show version and exit
```

## How It Works

1. **Read PMIDs**: Loads PubMed IDs from input file
2. **Convert to PMCIDs**: Uses NCBI E-utilities to convert PMID → PMCID
3. **Check Open Access**: Verifies article is in PMC Open Access subset
4. **Extract Figure URLs**: Parses PMC XML/HTML to find figure URLs
5. **Download Figures**: Downloads each figure with retry logic
6. **Track Progress**: Updates `manifest.json` to enable resuming

## Limitations

- **Only PMC Open Access articles**: Not all PubMed papers are available in PMC's Open Access subset. Papers that aren't available will be marked as failed with a `NotOpenAccessError`.
- **Rate Limits**: Respects NCBI rate limits (3 req/sec without API key, 10 req/sec with key)
- **Figure Quality**: Downloads figures as provided by PMC (quality varies by publisher)

## Error Handling

The tool handles several types of errors gracefully:

- **NoPMCIDError**: PMID not available in PMC (many papers aren't in PMC)
- **NotOpenAccessError**: Article is in PMC but not in Open Access subset
- **NoFiguresError**: Article has no figures
- **Network errors**: Automatic retry with exponential backoff

Failed PMIDs are saved to `errors.json`:
```json
{
  "12345678": {
    "error_type": "NoPMCIDError",
    "message": "PMID has no corresponding PMC ID",
    "attempts": 3,
    "last_attempt": "2026-01-28T10:30:00"
  }
}
```

## Output Files

- **Figures**: `PMID_12345_fig1.jpg`, `PMID_12345_fig2.png`, etc.
- **manifest.json**: Tracks completed and failed downloads
- **errors.json**: Detailed error report for failed PMIDs
- **figure_harvester.log**: Detailed logs (rotates at 10MB)

## Troubleshooting

### "Email is required by NCBI E-utilities"
Provide your email via:
- Command line: `--email your@email.com`
- Environment variable: `NCBI_EMAIL=your@email.com`
- Config file: `ncbi.email: "your@email.com"`

### "PMID has no corresponding PMC ID"
This is expected - not all PubMed papers are in PMC. The tool will continue with other PMIDs.

### Rate limit errors (429)
The tool automatically handles rate limits with exponential backoff. If you're still seeing issues:
- Get an NCBI API key to increase limit to 10 req/sec
- Reduce rate with `--rate 1` (1 request per second)

### No figures found
Some articles genuinely have no figures. Check the PMC webpage manually to verify.

### Resume not working
Ensure you're using the same output directory. The tool looks for `manifest.json` in the output directory.

## Development

### Project Structure
```
FigureHarvester/
├── figure_harvester/
│   ├── api/              # API wrappers (Entrez, PMC)
│   ├── downloader/       # Download orchestration
│   ├── utils/            # Utilities (logging, etc.)
│   └── main.py           # CLI entry point
├── tests/                # Unit tests
├── requirements.txt      # Dependencies
├── config.yaml          # Configuration
└── README.md            # This file
```

### Running Tests
```bash
pytest tests/
```

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

This project is provided as-is for research and educational purposes.

## Acknowledgments

- Uses NCBI E-utilities and PubMed Central APIs
- Built with BioPython, requests, and other excellent Python libraries

## Citation

If you use FigureHarvester in your research, please cite:
```
FigureHarvester: A tool for downloading figures from PubMed Central
https://github.com/andrewsu/FigureHarvester
```

## Support

For issues, questions, or feature requests, please open an issue on GitHub:
https://github.com/andrewsu/FigureHarvester/issues
