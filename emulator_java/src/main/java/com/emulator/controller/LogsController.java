package com.emulator.controller;

import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

@RestController
@RequestMapping("/api/v1/logs")
public class LogsController {

    private static final Path EMULATOR_DIR = Paths.get(
            System.getProperty("os.name", "").toLowerCase().contains("win")
                    ? "C:\\emulator" : "/opt/emulator");

    /**
     * GET /api/v1/logs/download
     *
     * Collects all *.log files from the emulator directory, creates a
     * tar.gz archive, and returns it as a downloadable file.
     */
    @GetMapping("/download")
    public ResponseEntity<Resource> downloadLogs() throws IOException {
        // Find all log files
        List<String> logFileNames = new ArrayList<>();
        if (Files.isDirectory(EMULATOR_DIR)) {
            try (DirectoryStream<Path> stream = Files.newDirectoryStream(EMULATOR_DIR, "*.log")) {
                for (Path entry : stream) {
                    if (Files.isRegularFile(entry)) {
                        logFileNames.add(entry.getFileName().toString());
                    }
                }
            }
        }

        if (logFileNames.isEmpty()) {
            return ResponseEntity.noContent().build();
        }

        // Create tar.gz via system tar command
        Path tempTar = Files.createTempFile("emulator-logs-", ".tar.gz");
        try {
            List<String> cmd = new ArrayList<>();
            cmd.add("tar");
            cmd.add("-czf");
            cmd.add(tempTar.toAbsolutePath().toString());
            cmd.add("-C");
            cmd.add(EMULATOR_DIR.toAbsolutePath().toString());
            cmd.addAll(logFileNames);

            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            Process proc = pb.start();
            int exitCode = proc.waitFor();
            if (exitCode != 0) {
                String output = new String(proc.getInputStream().readAllBytes());
                throw new IOException("tar failed (exit " + exitCode + "): " + output);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("tar interrupted", e);
        }

        FileSystemResource resource = new FileSystemResource(tempTar.toFile());
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=emulator-logs.tar.gz")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .contentLength(Files.size(tempTar))
                .body(resource);
    }
}
