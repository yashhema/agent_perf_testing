"""File builder service for creating test files."""

import os
import random
import string
import zipfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple
from pathlib import Path


class SizeBracket(str, Enum):
    """File size brackets."""
    SMALL = "50-100KB"      # 50KB to 100KB
    MEDIUM = "100-500KB"    # 100KB to 500KB
    LARGE = "500KB-2MB"     # 500KB to 2MB
    EXTRA_LARGE = "2MB-10MB"  # 2MB to 10MB


class OutputFormat(str, Enum):
    """Output file formats."""
    TXT = "txt"
    CSV = "csv"
    DOC = "doc"
    XLS = "xls"
    PDF = "pdf"


# Size bracket ranges in bytes
SIZE_RANGES = {
    SizeBracket.SMALL: (50 * 1024, 100 * 1024),
    SizeBracket.MEDIUM: (100 * 1024, 500 * 1024),
    SizeBracket.LARGE: (500 * 1024, 2 * 1024 * 1024),
    SizeBracket.EXTRA_LARGE: (2 * 1024 * 1024, 10 * 1024 * 1024),
}


@dataclass
class FileBuilderResult:
    """Result of file building operation."""
    success: bool
    output_path: str
    size_bracket: str
    actual_size_bytes: int
    output_format: str
    output_folder: str
    is_confidential: bool
    is_zipped: bool
    source_files_used: int
    error_message: Optional[str] = None


class FileBuilder:
    """Builds files from input folders."""

    def __init__(
        self,
        normal_folder: str,
        confidential_folder: str,
        output_folders: List[str],
    ):
        self.normal_folder = normal_folder
        self.confidential_folder = confidential_folder
        self.output_folders = output_folders
        self._normal_files: List[str] = []
        self._confidential_files: List[str] = []
        self._load_file_lists()

    def _load_file_lists(self) -> None:
        """Load list of available files from input folders (recursive)."""
        if self.normal_folder and os.path.isdir(self.normal_folder):
            self._normal_files = [
                os.path.join(dirpath, f)
                for dirpath, _, filenames in os.walk(self.normal_folder)
                for f in filenames
            ]

        if self.confidential_folder and os.path.isdir(self.confidential_folder):
            self._confidential_files = [
                os.path.join(dirpath, f)
                for dirpath, _, filenames in os.walk(self.confidential_folder)
                for f in filenames
            ]

    def _read_file_content(self, file_path: str, max_bytes: int = 0) -> str:
        """Read content from a file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                if max_bytes > 0:
                    return f.read(max_bytes)
                return f.read()
        except Exception:
            # If can't read as text, return empty
            return ""

    def _generate_random_content(self, size_bytes: int) -> str:
        """Generate random text content of specified size."""
        words = [
            "the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog",
            "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
            "data", "system", "process", "information", "report", "analysis",
            "document", "file", "record", "entry", "value", "result",
        ]
        content = []
        current_size = 0

        while current_size < size_bytes:
            line_words = random.choices(words, k=random.randint(8, 15))
            line = " ".join(line_words) + ".\n"
            content.append(line)
            current_size += len(line.encode("utf-8"))

        return "".join(content)[:size_bytes]

    def _combine_content(
        self,
        target_size: int,
        is_confidential: bool,
    ) -> Tuple[str, int]:
        """Combine content from source files to reach target size."""
        content_parts = []
        current_size = 0
        files_used = 0

        # Determine which files to use
        if is_confidential and self._confidential_files:
            # Mix normal and confidential files
            available_files = self._normal_files + self._confidential_files
        else:
            # Use only normal files
            available_files = self._normal_files

        if not available_files:
            # No source files available, generate random content
            return self._generate_random_content(target_size), 0

        # Shuffle to get random selection
        random.shuffle(available_files)

        for file_path in available_files:
            if current_size >= target_size:
                break

            remaining = target_size - current_size
            file_content = self._read_file_content(file_path, remaining)

            if file_content:
                content_parts.append(file_content)
                current_size += len(file_content.encode("utf-8"))
                files_used += 1

        # If still need more content, generate random
        if current_size < target_size:
            remaining = target_size - current_size
            content_parts.append(self._generate_random_content(remaining))

        return "".join(content_parts), files_used

    def _combine_content_by_ids(
        self,
        target_size: int,
        source_file_ids: str,
        is_confidential: bool,
    ) -> Tuple[str, int]:
        """Combine content from specific source files identified by ID.

        Source file IDs are matched against filenames (without extension) in the
        normal and confidential input folders. This enables deterministic file
        content selection driven by the operation sequence CSV.

        Args:
            target_size: Target content size in bytes
            source_file_ids: Semicolon-separated file IDs (e.g., "rfc791;rfc793;conf001")
            is_confidential: Whether to search confidential folder too
        """
        ids = [fid.strip() for fid in source_file_ids.split(";") if fid.strip()]

        # Build lookup: file_stem -> full_path
        available = {}
        for fpath in self._normal_files:
            stem = Path(fpath).stem
            available[stem] = fpath
        if is_confidential:
            for fpath in self._confidential_files:
                stem = Path(fpath).stem
                available[stem] = fpath

        content_parts = []
        current_size = 0
        files_used = 0

        for fid in ids:
            if current_size >= target_size:
                break
            fpath = available.get(fid)
            if fpath:
                remaining = target_size - current_size
                file_content = self._read_file_content(fpath, remaining)
                if file_content:
                    content_parts.append(file_content)
                    current_size += len(file_content.encode("utf-8"))
                    files_used += 1

        # Fill remaining with random content if source files weren't enough
        if current_size < target_size:
            remaining = target_size - current_size
            content_parts.append(self._generate_random_content(remaining))

        return "".join(content_parts), files_used

    def _format_as_csv(self, content: str) -> str:
        """Format content as CSV."""
        lines = content.split("\n")
        csv_lines = ["id,timestamp,content"]
        for i, line in enumerate(lines):
            if line.strip():
                # Escape quotes and wrap in quotes
                escaped = line.replace('"', '""')
                csv_lines.append(f'{i+1},"{datetime.now().isoformat()}","{escaped}"')
        return "\n".join(csv_lines)

    def _format_as_doc(self, content: str) -> str:
        """Format content as simple DOC-like format."""
        header = f"""Document Title: Generated Test Document
Created: {datetime.now().isoformat()}
Author: Emulator Service

{'=' * 60}

"""
        return header + content

    def _format_as_xls(self, content: str) -> str:
        """Format content as tab-separated (simple XLS-like format)."""
        lines = content.split("\n")
        xls_lines = ["ID\tTimestamp\tContent"]
        for i, line in enumerate(lines):
            if line.strip():
                xls_lines.append(f"{i+1}\t{datetime.now().isoformat()}\t{line}")
        return "\n".join(xls_lines)

    def _format_as_pdf(self, content: str) -> str:
        """Format content as simple text (PDF-like header)."""
        # Note: This creates a text file with PDF-like structure
        # For actual PDF, would need a library like reportlab
        header = f"""%PDF-1.4
%Emulator Generated Document
% Created: {datetime.now().isoformat()}

1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

% Content follows as text for testing purposes:
{'=' * 60}

"""
        return header + content

    def _format_content(self, content: str, output_format: OutputFormat) -> str:
        """Format content according to output format."""
        if output_format == OutputFormat.CSV:
            return self._format_as_csv(content)
        elif output_format == OutputFormat.DOC:
            return self._format_as_doc(content)
        elif output_format == OutputFormat.XLS:
            return self._format_as_xls(content)
        elif output_format == OutputFormat.PDF:
            return self._format_as_pdf(content)
        else:  # TXT
            return content

    def _generate_filename(self, output_format: OutputFormat) -> str:
        """Generate unique filename."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"file_{timestamp}_{random_suffix}.{output_format.value}"

    def _create_zip(self, file_path: str) -> str:
        """Create a zip file containing the given file."""
        zip_path = file_path + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(file_path, os.path.basename(file_path))
        # Remove original file
        os.remove(file_path)
        return zip_path

    def build(
        self,
        is_confidential: bool = False,
        make_zip: bool = False,
        size_bracket: Optional[str] = None,
        target_size_kb: Optional[int] = None,
        output_format: Optional[str] = None,
        output_folder_idx: Optional[int] = None,
        source_file_ids: Optional[str] = None,
    ) -> FileBuilderResult:
        """Build a file.

        When optional parameters are provided, uses them directly
        (deterministic mode — values from operation sequence CSV).
        When omitted, selects randomly (legacy/standalone mode).

        Args:
            is_confidential: Include confidential data sources
            make_zip: Compress output file
            size_bracket: "small"/"medium"/"large"/"xlarge" (None = random)
            target_size_kb: Exact target size in KB (None = random within bracket)
            output_format: "txt"/"csv"/"doc"/"xls"/"pdf" (None = random)
            output_folder_idx: Index into output_folders (None = random)
            source_file_ids: Semicolon-separated file IDs (None = auto-select)
        """
        try:
            # Size bracket: use provided or random
            BRACKET_MAP = {
                "small": SizeBracket.SMALL,
                "medium": SizeBracket.MEDIUM,
                "large": SizeBracket.LARGE,
                "xlarge": SizeBracket.EXTRA_LARGE,
            }
            if size_bracket is not None:
                resolved_bracket = BRACKET_MAP.get(size_bracket)
                if resolved_bracket is None:
                    resolved_bracket = random.choice(list(SizeBracket))
            else:
                resolved_bracket = random.choice(list(SizeBracket))

            # Output format: use provided or random
            FORMAT_MAP = {f.value: f for f in OutputFormat}
            if output_format is not None:
                resolved_format = FORMAT_MAP.get(output_format, random.choice(list(OutputFormat)))
            else:
                resolved_format = random.choice(list(OutputFormat))

            # Output folder: use provided index or random
            if output_folder_idx is not None and self.output_folders:
                idx = min(output_folder_idx, len(self.output_folders) - 1)
                output_folder = self.output_folders[idx]
            elif self.output_folders:
                output_folder = random.choice(self.output_folders)
            else:
                output_folder = tempfile.gettempdir()

            # Ensure output folder exists
            os.makedirs(output_folder, exist_ok=True)

            # Target size: use provided KB or random within bracket
            if target_size_kb is not None:
                target_size = target_size_kb * 1024
            else:
                min_size, max_size = SIZE_RANGES[resolved_bracket]
                target_size = random.randint(min_size, max_size)

            # Combine content from source files
            if source_file_ids is not None:
                content, files_used = self._combine_content_by_ids(
                    target_size, source_file_ids, is_confidential
                )
            else:
                content, files_used = self._combine_content(target_size, is_confidential)

            # Format content
            formatted_content = self._format_content(content, resolved_format)

            # Generate filename and write
            filename = self._generate_filename(resolved_format)
            output_path = os.path.join(output_folder, filename)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(formatted_content)

            actual_size = os.path.getsize(output_path)

            # Zip if requested
            is_zipped = False
            if make_zip:
                output_path = self._create_zip(output_path)
                actual_size = os.path.getsize(output_path)
                is_zipped = True

            return FileBuilderResult(
                success=True,
                output_path=output_path,
                size_bracket=resolved_bracket.value,
                actual_size_bytes=actual_size,
                output_format=resolved_format.value,
                output_folder=output_folder,
                is_confidential=is_confidential,
                is_zipped=is_zipped,
                source_files_used=files_used,
            )

        except Exception as e:
            return FileBuilderResult(
                success=False,
                output_path="",
                size_bracket="",
                actual_size_bytes=0,
                output_format="",
                output_folder="",
                is_confidential=is_confidential,
                is_zipped=make_zip,
                source_files_used=0,
                error_message=str(e),
            )


# Singleton instance
_file_builder: Optional[FileBuilder] = None


def get_file_builder() -> Optional[FileBuilder]:
    """Get the file builder instance."""
    return _file_builder


def init_file_builder(
    normal_folder: str,
    confidential_folder: str,
    output_folders: List[str],
) -> FileBuilder:
    """Initialize the file builder with configuration."""
    global _file_builder
    _file_builder = FileBuilder(
        normal_folder=normal_folder,
        confidential_folder=confidential_folder,
        output_folders=output_folders,
    )
    return _file_builder
