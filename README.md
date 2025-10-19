# AirWave Mock — Control AirWave V400 via Bluetooth

Summary

A small simulation and example project to control an AirWave device (firmware V400) from a Bluetooth source using Python. Integrates (or can wrap) the official vendor API to facilitate prototyping and testing without the physical device.

Version
Mock version 1.0.1

Features

- Target firmware: V400
- Communication: Bluetooth Low Energy (BLE)
- Includes: control scripts and mock server for testing
- Goal: enable rapid prototyping and CI-friendly tests without hardware

Requirements

- Python 3.8+
- BLE-capable Bluetooth adapter and drivers
- pip
- Optional: virtualenv or venv

Installation

1. Clone the repository:
    git clone /path/to/repo.git
    cd difluid-airwave-mock
2. Create and activate a virtual environment:
    python -m venv .venv
    source .venv/bin/activate   # macOS / Linux
    .venv\Scripts\activate      # Windows (PowerShell: .\.venv\Scripts\Activate.ps1)
3. Install dependencies:
    pip install -r requirements.txt

Configuration

- Environment variables (examples):
  - AIRWAVE_DEVICE_ID — device MAC address or UUID
  - AIRWAVE_API_KEY — API key if required by the vendor API
- Optional config file: config.yaml or .env

Usage

run script, the routine will discover the Airxwave via Bluetooth and perform bascic requests
to read content of the registers.

Contributing

- Open an issue to propose major changes.
- Fork → feature branch → PR with a clear description and tests.
- Follow PEP 8 code style and add tests for new features.

License

Authors & Contact

- TiLau (maintainer)
- For questions or bug reports, use the repository issue tracker.

Notes

- Ensure your machine's Bluetooth stack supports BLE.
- Keep the wrapped official API version up to date to follow protocol changes.
