package com.emulator.service;

import com.emulator.model.request.ConfigRequest;
import org.springframework.stereotype.Service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.locks.ReentrantLock;

@Service
public class ConfigService {

    private final ReentrantLock lock = new ReentrantLock();
    private List<String> outputFolders = new ArrayList<>();
    private String partnerFqdn;
    private int partnerPort = 8080;
    private String statsOutputDir = "./stats";
    private double statsIntervalSec = 1.0;
    private int maxMemorySamples = 10000;
    private List<String> serviceMonitorPatterns = new ArrayList<>();
    private boolean configured = false;

    // Auto-detect data directories
    private String normalFolder;
    private String confidentialFolder;

    public ConfigService() {
        autoDetectDataFolders();
    }

    private void autoDetectDataFolders() {
        // Try relative to working directory
        Path dataDir = Paths.get("data");
        if (Files.isDirectory(dataDir.resolve("normal"))) {
            normalFolder = dataDir.resolve("normal").toAbsolutePath().toString();
        }
        if (Files.isDirectory(dataDir.resolve("confidential"))) {
            confidentialFolder = dataDir.resolve("confidential").toAbsolutePath().toString();
        }
    }

    public Map<String, Object> setConfig(ConfigRequest req) {
        lock.lock();
        try {
            if (req.getOutputFolders() != null) {
                this.outputFolders = new ArrayList<>(req.getOutputFolders());
                // Create output directories
                for (String folder : outputFolders) {
                    try { Files.createDirectories(Paths.get(folder)); } catch (Exception ignored) {}
                }
            }
            if (req.getPartner() != null) {
                this.partnerFqdn = req.getPartner().getFqdn();
                this.partnerPort = req.getPartner().getPort();
            }
            if (req.getStats() != null) {
                this.statsOutputDir = req.getStats().getOutputDir();
                this.statsIntervalSec = req.getStats().getDefaultIntervalSec();
                this.maxMemorySamples = req.getStats().getMaxMemorySamples();
                this.serviceMonitorPatterns = req.getStats().getServiceMonitorPatterns() != null
                        ? new ArrayList<>(req.getStats().getServiceMonitorPatterns()) : new ArrayList<>();
                try { Files.createDirectories(Paths.get(statsOutputDir)); } catch (Exception ignored) {}
            }
            this.configured = true;
            return toMap();
        } finally {
            lock.unlock();
        }
    }

    public Map<String, Object> getConfigMap() {
        lock.lock();
        try {
            return toMap();
        } finally {
            lock.unlock();
        }
    }

    private Map<String, Object> toMap() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("is_configured", configured);
        result.put("output_folders", outputFolders);

        Map<String, Object> inputFolders = new LinkedHashMap<>();
        inputFolders.put("normal", normalFolder);
        inputFolders.put("confidential", confidentialFolder);
        result.put("input_folders", inputFolders);

        Map<String, Object> partner = new LinkedHashMap<>();
        partner.put("fqdn", partnerFqdn);
        partner.put("port", partnerPort);
        result.put("partner", partner);

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("output_dir", statsOutputDir);
        stats.put("default_interval_sec", statsIntervalSec);
        stats.put("max_memory_samples", maxMemorySamples);
        stats.put("service_monitor_patterns", serviceMonitorPatterns);
        result.put("stats", stats);

        return result;
    }

    public List<String> getOutputFolders() { return outputFolders; }
    public String getPartnerFqdn() { return partnerFqdn; }
    public int getPartnerPort() { return partnerPort; }
    public String getStatsOutputDir() { return statsOutputDir; }
    public double getStatsIntervalSec() { return statsIntervalSec; }
    public int getMaxMemorySamples() { return maxMemorySamples; }
    public List<String> getServiceMonitorPatterns() { return serviceMonitorPatterns; }
    public boolean isConfigured() { return configured; }
    public String getNormalFolder() { return normalFolder; }
    public String getConfidentialFolder() { return confidentialFolder; }
}
