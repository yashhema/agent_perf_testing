package com.emulator.service;

import com.emulator.model.request.SuspiciousRequest;
import com.emulator.model.response.OperationResult;
import com.emulator.util.PlatformUtil;
import org.springframework.stereotype.Service;

import java.io.*;
import java.nio.file.*;
import java.util.*;

@Service
public class SuspiciousOperationService {

    public OperationResult execute(SuspiciousRequest req) {
        long start = System.currentTimeMillis();
        String detail = "";
        String errorMessage = null;
        String osFamily = PlatformUtil.isWindows() ? "windows" : "linux";

        try {
            if (PlatformUtil.isWindows()) {
                detail = executeWindows(req.getActivityType(), req.getDurationMs());
            } else {
                detail = executeLinux(req.getActivityType(), req.getDurationMs());
            }
        } catch (Exception e) {
            errorMessage = e.getMessage();
        }

        // Sleep for duration
        try { Thread.sleep(req.getDurationMs()); } catch (InterruptedException ignored) {}

        long elapsed = System.currentTimeMillis() - start;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("activity_type", req.getActivityType());
        details.put("detail", detail);
        details.put("os_family", osFamily);
        details.put("error_message", errorMessage);

        return new OperationResult("suspicious", "completed", elapsed, details);
    }

    private String executeLinux(String activityType, int durationMs) throws Exception {
        return switch (activityType) {
            case "crontab_write" -> {
                Path tmp = Files.createTempFile("/tmp/", ".emulator_cron_test");
                Files.writeString(tmp, "* * * * * echo emulator_test\n");
                yield "Wrote crontab test entry to " + tmp;
            }
            case "tmp_executable" -> {
                Path tmp = Path.of("/tmp/.emulator_suspicious_bin");
                Files.writeString(tmp, "#!/bin/bash\necho suspicious");
                tmp.toFile().setExecutable(true);
                yield "Created executable at " + tmp;
            }
            case "process_spawn" -> {
                for (int i = 0; i < 3; i++) {
                    new ProcessBuilder("bash", "-c", "sleep 1").start();
                }
                yield "Spawned 3 bash processes";
            }
            case "hidden_file_create" -> {
                Path f1 = Path.of("/tmp/.emulator_hidden_1");
                Path f2 = Path.of("/tmp/.emulator_hidden_2");
                Files.writeString(f1, "hidden");
                Files.writeString(f2, "hidden");
                Files.deleteIfExists(f1);
                Files.deleteIfExists(f2);
                yield "Created and removed 2 hidden files in /tmp";
            }
            case "sensitive_file_access" -> {
                String[] files = {"/etc/shadow", "/etc/gshadow", "/etc/sudoers"};
                StringBuilder sb = new StringBuilder();
                for (String f : files) {
                    try { Files.readString(Path.of(f)); sb.append("Read ").append(f).append("; "); }
                    catch (Exception e) { sb.append("Failed to read ").append(f).append("; "); }
                }
                yield sb.toString();
            }
            default -> "Activity " + activityType + " executed (stub)";
        };
    }

    private String executeWindows(String activityType, int durationMs) throws Exception {
        return switch (activityType) {
            case "registry_write" -> {
                runCmd("reg", "add", "HKCU\\SOFTWARE\\EmulatorSuspiciousTest", "/v", "TestValue",
                        "/t", "REG_SZ", "/d", "test", "/f");
                runCmd("reg", "delete", "HKCU\\SOFTWARE\\EmulatorSuspiciousTest", "/f");
                yield "Created and deleted registry key";
            }
            case "scheduled_task" -> {
                runCmd("schtasks", "/create", "/tn", "EmulatorSuspiciousTest",
                        "/tr", "cmd /c echo test", "/sc", "once", "/st", "00:00", "/f");
                runCmd("schtasks", "/delete", "/tn", "EmulatorSuspiciousTest", "/f");
                yield "Created and deleted scheduled task";
            }
            case "service_query" -> {
                runCmd("sc", "query");
                yield "Enumerated all services";
            }
            case "hidden_file_create" -> {
                String tmp = System.getenv("TEMP");
                Path f1 = Path.of(tmp, ".emulator_hidden_1");
                Path f2 = Path.of(tmp, ".emulator_hidden_2");
                Files.writeString(f1, "hidden");
                Files.writeString(f2, "hidden");
                runCmd("attrib", "+H", f1.toString());
                runCmd("attrib", "+H", f2.toString());
                Files.deleteIfExists(f1);
                Files.deleteIfExists(f2);
                yield "Created and removed 2 hidden files";
            }
            case "wmi_query" -> {
                runCmd("wmic", "process", "list", "brief");
                yield "Enumerated processes via WMI";
            }
            default -> "Activity " + activityType + " executed (stub)";
        };
    }

    private void runCmd(String... cmd) {
        try {
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            Process p = pb.start();
            p.getInputStream().readAllBytes();
            p.waitFor();
        } catch (Exception ignored) {}
    }
}
