package com.emulator.service;

import com.emulator.model.request.DiskRequest;
import com.emulator.model.response.OperationResult;
import org.springframework.stereotype.Service;

import java.io.*;
import java.nio.file.*;
import java.util.*;

@Service
public class DiskOperationService {

    public OperationResult execute(DiskRequest req) {
        long start = System.currentTimeMillis();
        long bytesWritten = 0, bytesRead = 0;

        try {
            Path tempFile = Files.createTempFile("emulator_disk_", ".tmp");
            int blockSize = req.getBlockSizeKb() * 1024;
            byte[] block = new byte[blockSize];
            new Random().nextBytes(block);
            long deadline = System.nanoTime() + (long) req.getDurationMs() * 1_000_000L;

            try (RandomAccessFile raf = new RandomAccessFile(tempFile.toFile(), "rw")) {
                // Pre-create file
                long totalBytes = (long) req.getSizeMb() * 1024 * 1024;
                raf.setLength(totalBytes);

                while (System.nanoTime() < deadline) {
                    switch (req.getMode()) {
                        case "write":
                            raf.seek(0);
                            while (raf.getFilePointer() < totalBytes && System.nanoTime() < deadline) {
                                raf.write(block);
                                bytesWritten += blockSize;
                            }
                            raf.getFD().sync();
                            break;
                        case "read":
                            raf.seek(0);
                            byte[] readBuf = new byte[blockSize];
                            while (raf.getFilePointer() < totalBytes && System.nanoTime() < deadline) {
                                int n = raf.read(readBuf);
                                if (n <= 0) { raf.seek(0); continue; }
                                bytesRead += n;
                            }
                            break;
                        case "mixed":
                            raf.seek(0);
                            boolean doWrite = true;
                            while (System.nanoTime() < deadline) {
                                if (doWrite) {
                                    if (raf.getFilePointer() >= totalBytes) raf.seek(0);
                                    raf.write(block);
                                    bytesWritten += blockSize;
                                } else {
                                    if (raf.getFilePointer() >= totalBytes) raf.seek(0);
                                    byte[] rb = new byte[blockSize];
                                    int n = raf.read(rb);
                                    if (n > 0) bytesRead += n;
                                }
                                doWrite = !doWrite;
                            }
                            raf.getFD().sync();
                            break;
                    }
                }
            }
            Files.deleteIfExists(tempFile);
        } catch (Exception e) {
            // Continue - report what we managed
        }

        long elapsed = System.currentTimeMillis() - start;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("requested_duration_ms", req.getDurationMs());
        details.put("mode", req.getMode());
        details.put("size_mb", req.getSizeMb());
        details.put("block_size_kb", req.getBlockSizeKb());
        details.put("bytes_written", bytesWritten);
        details.put("bytes_read", bytesRead);

        return new OperationResult("DISK", "completed", elapsed, details);
    }
}
