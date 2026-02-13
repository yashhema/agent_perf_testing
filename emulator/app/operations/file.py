"""File operation - creates files in output folders."""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from ..config import get_config
from ..services.file_builder import FileBuilder, FileBuilderResult


@dataclass(frozen=True)
class FileOperationParams:
    """Parameters for file operation."""
    is_confidential: bool = False
    make_zip: bool = False
    # Deterministic fields — None means let the builder choose randomly
    size_bracket: Optional[str] = None
    target_size_kb: Optional[int] = None
    output_format: Optional[str] = None
    output_folder_idx: Optional[int] = None
    source_file_ids: Optional[str] = None


@dataclass(frozen=True)
class FileOperationResult:
    """Result of file operation."""
    operation: str
    status: str
    duration_ms: int
    size_bracket: str
    actual_size_bytes: int
    output_format: str
    output_folder: str
    output_file: str
    is_confidential: bool
    is_zipped: bool
    source_files_used: int
    error_message: Optional[str] = None


class FileOperation:
    """File operation - creates files from input folders and writes to output folder."""

    @staticmethod
    def _build_file(params: FileOperationParams) -> FileBuilderResult:
        """Build a file using the file builder."""
        config = get_config()

        builder = FileBuilder(
            normal_folder=config.input_folders.normal,
            confidential_folder=config.input_folders.confidential,
            output_folders=config.output_folders,
        )

        return builder.build(
            is_confidential=params.is_confidential,
            make_zip=params.make_zip,
            size_bracket=params.size_bracket,
            target_size_kb=params.target_size_kb,
            output_format=params.output_format,
            output_folder_idx=params.output_folder_idx,
            source_file_ids=params.source_file_ids,
        )

    @staticmethod
    async def execute(params: FileOperationParams) -> FileOperationResult:
        """Execute file operation asynchronously."""
        start_time = time.perf_counter()

        # Run file building in thread pool to not block async
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            FileOperation._build_file,
            params,
        )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        if result.success:
            return FileOperationResult(
                operation="FILE",
                status="completed",
                duration_ms=duration_ms,
                size_bracket=result.size_bracket,
                actual_size_bytes=result.actual_size_bytes,
                output_format=result.output_format,
                output_folder=result.output_folder,
                output_file=result.output_path,
                is_confidential=result.is_confidential,
                is_zipped=result.is_zipped,
                source_files_used=result.source_files_used,
            )
        else:
            return FileOperationResult(
                operation="FILE",
                status="failed",
                duration_ms=duration_ms,
                size_bracket="",
                actual_size_bytes=0,
                output_format="",
                output_folder="",
                output_file="",
                is_confidential=params.is_confidential,
                is_zipped=params.make_zip,
                source_files_used=0,
                error_message=result.error_message,
            )
