# marketlens-sql

SQL-based market data pipeline: API ingestion, relational storage, and quantitative analysis (returns, volatility, correlations) with a dashboard.

## Project status

Early development. The repository currently contains the project setup only: pinned dependencies and Git configuration.

The pipeline is being built in stages:

1. Project foundation *(in progress)*
2. Relational database schema (SQLite)
3. Historical market data ingestion
4. Analytical SQL: returns, volatility, correlations and drawdowns
5. Streamlit dashboard
6. Static showcase on GitHub Pages

Each section of this README is added when the corresponding component exists.

## Requirements

- Python 3.11 or later
- Git

## Installation

```bash
git clone https://github.com/claudialbombin/marketlens-sql.git
cd marketlens-sql
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Disclaimer

This is an educational and portfolio project. It works with historical, delayed data and is not an investment recommendation tool.

## License

MIT. See [LICENSE](LICENSE).
