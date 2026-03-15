package com.emulator.service;

import com.emulator.model.request.FileOperationRequest;
import com.emulator.model.response.FileOperationResult;
import org.springframework.stereotype.Service;

import java.io.*;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

@Service
public class FileOperationService {

    private final ConfigService configService;
    private final Random random = new Random();

    private static final Map<String, int[]> SIZE_BRACKETS = Map.of(
            "small", new int[]{50, 100},
            "medium", new int[]{100, 500},
            "large", new int[]{500, 2048},
            "xlarge", new int[]{2048, 10240}
    );

    private static final Map<String, String> SIZE_BRACKET_DISPLAY = Map.of(
            "small", "50-100KB",
            "medium", "100-500KB",
            "large", "500KB-2MB",
            "xlarge", "2MB-10MB"
    );

    private static final String[] FORMATS = {"txt", "csv", "doc", "xls", "pdf"};
    private static final String[] BRACKETS = {"small", "medium", "large", "xlarge"};

    public FileOperationService(ConfigService configService) {
        this.configService = configService;
    }

    public FileOperationResult execute(FileOperationRequest req) {
        long start = System.currentTimeMillis();
        FileOperationResult result = new FileOperationResult();

        try {
            List<String> outputFolders = configService.getOutputFolders();
            if (outputFolders == null || outputFolders.isEmpty()) {
                result.setStatus("error");
                result.setErrorMessage("No output folders configured. POST /api/v1/config first.");
                result.setDurationMs(System.currentTimeMillis() - start);
                return result;
            }

            // Resolve bracket
            String bracket = req.getSizeBracket();
            if (bracket == null) bracket = BRACKETS[random.nextInt(BRACKETS.length)];
            int[] range = SIZE_BRACKETS.get(bracket);
            if (range == null) range = SIZE_BRACKETS.get("medium");

            // Resolve target size
            int targetSizeKb = req.getTargetSizeKb() != null ? req.getTargetSizeKb()
                    : range[0] + random.nextInt(range[1] - range[0]);
            int targetSizeBytes = targetSizeKb * 1024;

            // Resolve format
            String format = req.getOutputFormat();
            if (format == null) format = FORMATS[random.nextInt(FORMATS.length)];

            // Resolve output folder
            int folderIdx = req.getOutputFolderIdx() != null ? req.getOutputFolderIdx()
                    : random.nextInt(outputFolders.size());
            folderIdx = Math.min(folderIdx, outputFolders.size() - 1);
            String outputFolder = outputFolders.get(folderIdx);
            Files.createDirectories(Paths.get(outputFolder));

            // Read source files
            String dataFolder = req.isConfidential()
                    ? configService.getConfidentialFolder()
                    : configService.getNormalFolder();

            List<Path> sourceFiles = new ArrayList<>();
            int sourceFilesUsed = 0;

            if (dataFolder != null && Files.isDirectory(Paths.get(dataFolder))) {
                if (req.getSourceFileIds() != null) {
                    String[] ids = req.getSourceFileIds().split(";");
                    for (String id : ids) {
                        findFileById(Paths.get(dataFolder), id.trim()).ifPresent(sourceFiles::add);
                    }
                } else {
                    try (var stream = Files.walk(Paths.get(dataFolder))) {
                        stream.filter(Files::isRegularFile).limit(20).forEach(sourceFiles::add);
                    }
                }
            }

            // Build content
            StringBuilder content = new StringBuilder();
            for (Path sf : sourceFiles) {
                try {
                    String text = Files.readString(sf);
                    content.append(text);
                    sourceFilesUsed++;
                    if (content.length() >= targetSizeBytes) break;
                } catch (Exception ignored) {}
            }

            // Pad if needed
            while (content.length() < targetSizeBytes) {
                content.append("Lorem ipsum dolor sit amet, consectetur adipiscing elit. ");
            }
            if (content.length() > targetSizeBytes) {
                content.setLength(targetSizeBytes);
            }

            // Format content
            String finalContent = formatContent(content.toString(), format);

            // Generate filename
            String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
            String randomSuffix = String.format("%06x", random.nextInt(0xFFFFFF));
            String fileName = "file_" + timestamp + "_" + randomSuffix + "." + format;
            Path outputPath = Paths.get(outputFolder, fileName);

            Files.writeString(outputPath, finalContent);
            long actualSize = Files.size(outputPath);

            // ZIP if requested
            if (req.isMakeZip()) {
                Path zipPath = Paths.get(outputPath + ".zip");
                try (ZipOutputStream zos = new ZipOutputStream(new FileOutputStream(zipPath.toFile()))) {
                    zos.putNextEntry(new ZipEntry(fileName));
                    zos.write(Files.readAllBytes(outputPath));
                    zos.closeEntry();
                }
                Files.deleteIfExists(outputPath);
                outputPath = zipPath;
                actualSize = Files.size(zipPath);
                fileName = fileName + ".zip";
            }

            result.setStatus("completed");
            result.setSizeBracket(SIZE_BRACKET_DISPLAY.getOrDefault(bracket, bracket));
            result.setActualSizeBytes(actualSize);
            result.setOutputFormat(format);
            result.setOutputFolder(outputFolder);
            result.setOutputFile(outputPath.toString());
            result.setConfidential(req.isConfidential());
            result.setZipped(req.isMakeZip());
            result.setSourceFilesUsed(sourceFilesUsed);

        } catch (Exception e) {
            result.setStatus("error");
            result.setErrorMessage(e.getMessage());
        }

        result.setDurationMs(System.currentTimeMillis() - start);
        return result;
    }

    private String formatContent(String raw, String format) {
        return switch (format) {
            case "csv" -> {
                StringBuilder sb = new StringBuilder("id,timestamp,content\n");
                String[] lines = raw.split("(?<=\\G.{80})");
                for (int i = 0; i < lines.length; i++) {
                    sb.append(i).append(",").append(System.currentTimeMillis()).append(",\"").append(
                            lines[i].replace("\"", "\"\"")).append("\"\n");
                }
                yield sb.toString();
            }
            case "doc" -> "=== DOCUMENT HEADER ===\nGenerated by Emulator\n\n" + raw;
            case "xls" -> {
                StringBuilder sb = new StringBuilder("ID\tTimestamp\tContent\n");
                String[] lines = raw.split("(?<=\\G.{80})");
                for (int i = 0; i < lines.length; i++) {
                    sb.append(i).append("\t").append(System.currentTimeMillis()).append("\t").append(lines[i]).append("\n");
                }
                yield sb.toString();
            }
            case "pdf" -> "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n" + raw;
            default -> raw;
        };
    }

    private Optional<Path> findFileById(Path dir, String id) {
        try (var stream = Files.walk(dir)) {
            return stream.filter(Files::isRegularFile)
                    .filter(p -> {
                        String name = p.getFileName().toString();
                        String stem = name.contains(".") ? name.substring(0, name.lastIndexOf('.')) : name;
                        return stem.equalsIgnoreCase(id);
                    })
                    .findFirst();
        } catch (Exception e) {
            return Optional.empty();
        }
    }
}
