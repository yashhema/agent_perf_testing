"""Confidential data loader for PII data from Excel files."""

import os
import random
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterator

import pandas as pd


class ConfidentialDataLoader:
    """Load and provide access to confidential data from Excel files.

    The ConfidentialData folder contains 14 Excel files with PII data:
    - Personal: FIRSTNAME, LASTNAME, FULLNAME, ADDR, CITY, ST, ZIP, PHONE, BIRTHDAY, EMAIL
    - SSN/Tax: SSN, EIN, ITIN, ATIN, PTIN
    - Passport: PASSPORT, PASSPORTISSUED, PASSPORTEXPIRE
    - Driver License: DL, DLSTATE, DLISSUED, DLEXPIRE
    - Credit Card: CC, CCNO, CCCSV, CCEXPIRE
    - Bank: BANK, ROUTING, BANKACCT
    - Other IDs: SIDN, MILITARYID, MEDICARE-MBI, HICN
    """

    # All columns available in the Excel files
    COLUMNS = [
        'FIRSTNAME', 'LASTNAME', 'FULLNAME', 'ADDR', 'CITY', 'ST', 'ZIP',
        'PHONE', 'BIRTHDAY', 'EMAIL', 'SSN', 'PASSPORT', 'PASSPORTISSUED',
        'PASSPORTEXPIRE', 'DL', 'DLSTATE', 'DLISSUED', 'DLEXPIRE', 'CC',
        'CCNO', 'CCCSV', 'CCEXPIRE', 'BANK', 'ROUTING', 'BANKACCT', 'EIN',
        'ITIN', 'ATIN', 'PTIN', 'SIDN', 'MILITARYID', 'MEDICARE-MBI', 'HICN'
    ]

    def __init__(self, data_dir: str, shuffle: bool = True):
        """Initialize the loader.

        Args:
            data_dir: Path to ConfidentialData folder
            shuffle: Whether to shuffle data for random access
        """
        self.data_dir = Path(data_dir)
        self._data: Optional[pd.DataFrame] = None
        self._index = 0
        self._shuffle = shuffle
        self._loaded = False

    def load(self) -> None:
        """Load all Excel files into a single DataFrame."""
        if self._loaded:
            return

        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")

        all_dfs = []
        excel_files = list(self.data_dir.glob("DLPTEST-State-*.xlsx"))

        if not excel_files:
            raise FileNotFoundError(f"No DLPTEST Excel files found in {self.data_dir}")

        for filepath in excel_files:
            try:
                xl = pd.ExcelFile(filepath)
                for sheet in xl.sheet_names:
                    if sheet.upper() != 'README':
                        df = pd.read_excel(filepath, sheet_name=sheet)
                        all_dfs.append(df)
            except Exception as e:
                print(f"Warning: Could not read {filepath}: {e}")
                continue

        if not all_dfs:
            raise ValueError("No data loaded from Excel files")

        self._data = pd.concat(all_dfs, ignore_index=True)

        # Shuffle for random access
        if self._shuffle:
            self._data = self._data.sample(frac=1).reset_index(drop=True)

        self._loaded = True
        print(f"Loaded {len(self._data):,} confidential records from {len(excel_files)} files")

    def _ensure_loaded(self) -> None:
        """Ensure data is loaded before access."""
        if not self._loaded:
            self.load()

    def get_next(self) -> Dict[str, Any]:
        """Get next record (cycles through data).

        Returns:
            Dictionary with column names as keys
        """
        self._ensure_loaded()

        if self._index >= len(self._data):
            self._index = 0

        record = self._data.iloc[self._index].to_dict()
        self._index += 1

        # Clean up NaN values
        return {k: (v if pd.notna(v) else None) for k, v in record.items()}

    def get_random(self) -> Dict[str, Any]:
        """Get random record.

        Returns:
            Dictionary with column names as keys
        """
        self._ensure_loaded()

        idx = random.randint(0, len(self._data) - 1)
        record = self._data.iloc[idx].to_dict()

        # Clean up NaN values
        return {k: (v if pd.notna(v) else None) for k, v in record.items()}

    def get_batch(self, count: int) -> List[Dict[str, Any]]:
        """Get a batch of records.

        Args:
            count: Number of records to return

        Returns:
            List of dictionaries
        """
        return [self.get_next() for _ in range(count)]

    def get_random_batch(self, count: int) -> List[Dict[str, Any]]:
        """Get a batch of random records.

        Args:
            count: Number of records to return

        Returns:
            List of dictionaries
        """
        return [self.get_random() for _ in range(count)]

    def get_column_values(self, column: str, count: int) -> List[Any]:
        """Get list of values from a specific column.

        Args:
            column: Column name
            count: Number of values to return

        Returns:
            List of values
        """
        self._ensure_loaded()

        if column not in self._data.columns:
            raise ValueError(f"Column '{column}' not found. Available: {list(self._data.columns)}")

        values = self._data[column].dropna()
        sample_size = min(count, len(values))
        return values.sample(n=sample_size).tolist()

    def get_unique_column_values(self, column: str, count: int) -> List[Any]:
        """Get unique values from a specific column.

        Args:
            column: Column name
            count: Number of unique values to return

        Returns:
            List of unique values
        """
        self._ensure_loaded()

        if column not in self._data.columns:
            raise ValueError(f"Column '{column}' not found")

        unique_values = self._data[column].dropna().unique()
        sample_size = min(count, len(unique_values))

        if sample_size < count:
            print(f"Warning: Only {len(unique_values)} unique values for {column}, requested {count}")

        return list(random.sample(list(unique_values), sample_size))

    def iterate(self) -> Iterator[Dict[str, Any]]:
        """Iterate through all records.

        Yields:
            Dictionary for each record
        """
        self._ensure_loaded()

        for idx in range(len(self._data)):
            record = self._data.iloc[idx].to_dict()
            yield {k: (v if pd.notna(v) else None) for k, v in record.items()}

    def reset(self) -> None:
        """Reset the sequential index to start."""
        self._index = 0

    @property
    def total_records(self) -> int:
        """Get total number of records."""
        self._ensure_loaded()
        return len(self._data)

    @property
    def columns(self) -> List[str]:
        """Get list of available columns."""
        self._ensure_loaded()
        return list(self._data.columns)

    def get_sample_record(self) -> Dict[str, Any]:
        """Get a sample record for inspection.

        Returns:
            First record in the dataset
        """
        self._ensure_loaded()
        record = self._data.iloc[0].to_dict()
        return {k: (v if pd.notna(v) else None) for k, v in record.items()}


# Module-level loader instance
_loader: Optional[ConfidentialDataLoader] = None


def get_loader(data_dir: str = None) -> ConfidentialDataLoader:
    """Get or create the global loader instance.

    Args:
        data_dir: Path to ConfidentialData folder (required on first call)

    Returns:
        ConfidentialDataLoader instance
    """
    global _loader

    if _loader is None:
        if data_dir is None:
            raise ValueError("data_dir required for first call to get_loader()")
        _loader = ConfidentialDataLoader(data_dir)

    return _loader


def reset_loader() -> None:
    """Reset the global loader instance."""
    global _loader
    _loader = None
