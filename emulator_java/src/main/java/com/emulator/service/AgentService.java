package com.emulator.service;

import com.emulator.util.PlatformUtil;
import org.springframework.stereotype.Service;

import java.nio.file.*;
import java.util.*;

@Service
public class AgentService {

    private static final Map<String, AgentConfig> AGENTS = Map.of(
            "crowdstrike", new AgentConfig(
                    List.of("/opt/CrowdStrike", "C:\\Program Files\\CrowdStrike"),
                    List.of("falcon-sensor", "CSFalconService"),
                    "CSFalconService", "falcon-sensor"),
            "sentinelone", new AgentConfig(
                    List.of("/opt/sentinelone", "C:\\Program Files\\SentinelOne"),
                    List.of("sentinelone", "SentinelAgent"),
                    "SentinelAgent", "sentinelone"),
            "carbonblack", new AgentConfig(
                    List.of("/opt/carbonblack", "C:\\Program Files\\CarbonBlack"),
                    List.of("cbagentd", "CbDefense"),
                    "CbDefense", "cbagentd")
    );

    public Map<String, Object> getAgentInfo(String agentType) {
        AgentConfig config = AGENTS.get(agentType.toLowerCase());
        if (config == null) return null;

        boolean installed = false;
        String installPath = null;
        String serviceStatus = "unknown";

        for (String path : config.installPaths) {
            if (Files.isDirectory(Paths.get(path))) {
                installed = true;
                installPath = path;
                break;
            }
        }

        if (installed) {
            serviceStatus = checkServiceStatus(config);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("agent_type", agentType.toLowerCase());
        result.put("installed", installed);
        result.put("version", null);
        result.put("service_status", serviceStatus);
        result.put("install_path", installPath);
        return result;
    }

    public Map<String, Object> installAgent(String agentType, String installerPath, Map<String, Object> options) {
        Map<String, Object> result = new LinkedHashMap<>();
        try {
            ProcessBuilder pb;
            if (PlatformUtil.isWindows()) {
                List<String> cmd = new ArrayList<>(List.of(installerPath, "/install", "/quiet"));
                if (options != null) {
                    options.forEach((k, v) -> cmd.add(k + "=" + v));
                }
                pb = new ProcessBuilder(cmd);
            } else {
                pb = new ProcessBuilder("bash", "-c", "dpkg -i " + installerPath + " || rpm -i " + installerPath);
            }
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String output = new String(p.getInputStream().readAllBytes());
            int exitCode = p.waitFor();

            if (exitCode == 0) {
                result.put("success", true);
                result.put("message", "Agent " + agentType + " installed successfully");
            } else {
                result.put("success", false);
                result.put("message", "Installation failed: " + output);
                result.put("exit_code", exitCode);
            }
        } catch (Exception e) {
            result.put("success", false);
            result.put("message", "Installation failed: " + e.getMessage());
            result.put("exit_code", -1);
        }
        return result;
    }

    public Map<String, Object> uninstallAgent(String agentType, boolean force) {
        Map<String, Object> result = new LinkedHashMap<>();
        try {
            ProcessBuilder pb;
            if (PlatformUtil.isWindows()) {
                pb = new ProcessBuilder("wmic", "product", "where",
                        "name like '%" + agentType + "%'", "call", "uninstall", "/nointeractive");
            } else {
                pb = new ProcessBuilder("bash", "-c",
                        "dpkg -r " + agentType + " 2>/dev/null || rpm -e " + agentType + " 2>/dev/null");
            }
            pb.redirectErrorStream(true);
            Process p = pb.start();
            p.getInputStream().readAllBytes();
            p.waitFor();

            result.put("success", true);
            result.put("message", "Agent " + agentType + " uninstalled successfully");
        } catch (Exception e) {
            result.put("success", false);
            result.put("message", "Uninstall failed: " + e.getMessage());
        }
        return result;
    }

    public Map<String, Object> controlService(String agentType, String action) {
        AgentConfig config = AGENTS.get(agentType.toLowerCase());
        if (config == null) {
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("success", false);
            r.put("message", "Unknown agent type: " + agentType);
            return r;
        }

        String serviceName = PlatformUtil.isWindows() ? config.windowsServiceName : config.linuxServiceName;
        Map<String, Object> result = new LinkedHashMap<>();

        try {
            ProcessBuilder pb;
            if (PlatformUtil.isWindows()) {
                if ("restart".equals(action)) {
                    runCmd("sc", "stop", serviceName);
                    Thread.sleep(2000);
                    pb = new ProcessBuilder("sc", "start", serviceName);
                } else {
                    pb = new ProcessBuilder("sc", action, serviceName);
                }
            } else {
                pb = new ProcessBuilder("systemctl", action, serviceName);
            }
            pb.redirectErrorStream(true);
            Process p = pb.start();
            p.getInputStream().readAllBytes();
            p.waitFor();

            result.put("success", true);
            result.put("message", "Service " + serviceName + " " + action + " successful");
        } catch (Exception e) {
            result.put("success", false);
            result.put("message", "Service control failed: " + e.getMessage());
        }
        return result;
    }

    private String checkServiceStatus(AgentConfig config) {
        try {
            String serviceName = PlatformUtil.isWindows() ? config.windowsServiceName : config.linuxServiceName;
            ProcessBuilder pb;
            if (PlatformUtil.isWindows()) {
                pb = new ProcessBuilder("sc", "query", serviceName);
            } else {
                pb = new ProcessBuilder("systemctl", "is-active", serviceName);
            }
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String output = new String(p.getInputStream().readAllBytes());
            int exit = p.waitFor();
            if (exit == 0) {
                if (output.contains("RUNNING") || output.trim().equals("active")) return "running";
                if (output.contains("STOPPED") || output.trim().equals("inactive")) return "stopped";
            }
        } catch (Exception ignored) {}
        return "unknown";
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

    private record AgentConfig(List<String> installPaths, List<String> serviceNames,
                                String windowsServiceName, String linuxServiceName) {}
}
